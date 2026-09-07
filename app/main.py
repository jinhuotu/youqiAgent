"""项目启动入口。

FastAPI 应用工厂 + 命令行启动；负责：
- 日志初始化
- 全局异常处理注册
- 内部鉴权中间件挂载
- 路由注册
- 生命周期内初始化向量库 / 知识库任务队列
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.internal import router as internal_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logger import get_logger, setup_logger
from app.core.startup import check_dependencies, validate_settings
from app.middleware.internal_auth import InternalAuthMiddleware

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时初始化基础设施，关闭时释放资源。"""
    settings = get_settings()
    log.info(f"服务启动中... env={settings.env}, version={settings.app_version}")

    validate_settings(settings)
    deps = check_dependencies()
    app.state.deps = deps

    # 初始化预留知识库集合（失败不阻断启动）
    try:
        from app.services.vector_service import VectorService

        VectorService().init_knowledge_base()
    except Exception as e:
        log.warning(f"向量库初始化跳过: {e}")

    # 启动知识库任务队列 worker，并恢复卡住任务
    try:
        from app.services.kb_job_queue import recover_stuck_jobs, start_workers, stop_workers

        start_workers()
        recovered = recover_stuck_jobs()
        if recovered:
            log.info(f"已重新入队卡住文档任务: {recovered}")
        app.state.kb_queue_stop = stop_workers
    except Exception as e:
        log.warning(f"知识库任务队列启动失败: {e}")

    yield

    stop = getattr(app.state, "kb_queue_stop", None)
    if callable(stop):
        stop()
    try:
        from app.services.mcp_session import mcp_session_manager

        await mcp_session_manager.close_all()
    except Exception as e:
        log.warning(f"关闭 MCP 会话失败: {e}")
    log.info("服务已关闭")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    settings = get_settings()
    setup_logger(log_level=settings.log_level)

    app = FastAPI(
        title="Agent AI Service",
        description="内部 AI 能力下沉服务 - 面向 Java 业务后端",
        version=settings.app_version,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # 全局异常处理
    register_exception_handlers(app)

    # CORS（需允许前端自定义鉴权头；中间件按 LIFO 执行，先加鉴权再加 CORS）
    app.add_middleware(InternalAuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    log.info(
        f"CORS origins={settings.cors_origin_list}"
        + (f", regex={settings.cors_origin_regex}" if settings.cors_origin_regex else "")
    )

    @app.get("/health", tags=["健康检查"])
    def health() -> dict:
        """存活探针（轻量，不探测依赖）。"""
        return {"status": "ok", "version": settings.app_version}

    @app.get("/ready", tags=["健康检查"])
    def ready() -> JSONResponse:
        """就绪探针：检查 MySQL / Redis。"""
        deps = check_dependencies()
        chroma_ok = True
        try:
            from app.db.vector.chroma_impl import get_vector_store

            chroma_ok = bool(get_vector_store().health_check())
        except Exception:
            chroma_ok = False
        deps["chroma"] = chroma_ok
        ok = deps.get("mysql", False)
        body = {
            "status": "ok" if ok else "not_ready",
            "version": settings.app_version,
            "dependencies": deps,
        }
        return JSONResponse(status_code=200 if ok else 503, content=body)

    app.include_router(internal_router)
    return app


app = create_app()


def run() -> None:
    """命令行启动入口：poetry run start。"""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=not settings.is_production,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
