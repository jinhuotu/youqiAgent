"""内部接口鉴权中间件。

所有 /api/v1/internal/** 路径必须校验：
1. X-Service-Token 与配置的服务密钥比对（支持多密钥）
2. X-User-Id 注入请求上下文，作为全链路数据隔离依据
3. 可选 X-Role，默认 user
校验失败统一返回 401。

使用纯 ASGI 中间件（非 BaseHTTPMiddleware），避免与 BackgroundTasks /
长耗时后台任务组合时阻塞整个 Uvicorn 事件循环（表现为 /health 与所有接口超时）。
"""

import uuid

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.context import RequestContext, clear_request_context, set_request_context
from app.core.exceptions import ErrorCode
from app.core.logger import get_logger, logger

log = get_logger("middleware.auth")

INTERNAL_PATH_PREFIX = "/api/v1/internal"


class InternalAuthMiddleware:
    """服务间调用鉴权与用户上下文透传中间件（纯 ASGI）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith(INTERNAL_PATH_PREFIX):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        settings = get_settings()
        service_token = request.headers.get("X-Service-Token", "").strip()
        user_id = request.headers.get("X-User-Id", "").strip()
        role = request.headers.get("X-Role", "user").strip() or "user"
        request_id = request.headers.get("X-Request-Id", "").strip() or str(uuid.uuid4())

        # 1) 校验服务密钥
        valid_tokens = settings.service_token_list
        if not valid_tokens or service_token not in valid_tokens:
            log.warning(f"鉴权失败: 无效 Service-Token, path={path}")
            response = JSONResponse(
                status_code=401,
                content={
                    "code": ErrorCode.UNAUTHORIZED,
                    "message": "鉴权失败，请检查 X-Service-Token",
                    "data": None,
                },
            )
            await response(scope, receive, send)
            return

        # 2) 强制要求 X-User-Id
        if not user_id:
            log.warning(f"鉴权失败: 缺少 X-User-Id, path={path}")
            response = JSONResponse(
                status_code=401,
                content={
                    "code": ErrorCode.UNAUTHORIZED,
                    "message": "鉴权失败，缺少 X-User-Id",
                    "data": None,
                },
            )
            await response(scope, receive, send)
            return

        # 3) 注入请求上下文，并绑定到日志
        ctx = RequestContext(user_id=user_id, role=role, request_id=request_id)
        set_request_context(ctx)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = request_id
            await send(message)

        with logger.contextualize(user_id=user_id):
            log.info(
                f"内部鉴权通过: path={path}, user_id={user_id}, "
                f"role={role}, request_id={request_id}"
            )
            try:
                await self.app(scope, receive, send_with_request_id)
            finally:
                clear_request_context()
