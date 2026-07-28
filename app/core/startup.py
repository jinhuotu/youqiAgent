"""生产环境启动校验。"""

from app.core.config import Settings
from app.core.logger import get_logger
from app.db.mysql.session import check_mysql_connection
from app.db.redis import check_redis_connection

log = get_logger("core.startup")


def validate_settings(settings: Settings) -> None:
    """校验关键配置；生产环境缺失则直接抛错阻断启动。"""
    errors: list[str] = []

    if not settings.service_token_list:
        errors.append("INTERNAL_SERVICE_TOKENS 未配置")

    key = (settings.encryption_key or "").strip()
    if not key or key.startswith("your_"):
        msg = "ENCRYPTION_KEY 未配置或仍为占位值"
        if settings.is_production:
            errors.append(msg)
        else:
            log.warning(f"{msg}（开发环境允许，API Key 将明文存储）")

    if settings.is_production and errors:
        raise RuntimeError("生产环境配置校验失败: " + "; ".join(errors))

    for e in errors:
        log.warning(f"配置告警: {e}")


def check_dependencies(*, require_redis: bool = False) -> dict[str, bool]:
    """探测基础设施连通性。"""
    status = {
        "mysql": check_mysql_connection(),
        "redis": check_redis_connection(),
    }
    if require_redis and not status["redis"]:
        raise RuntimeError("Redis 不可用，知识库任务队列无法启动")
    if not status["mysql"]:
        log.warning("MySQL 连接检测失败")
    if not status["redis"]:
        log.warning("Redis 连接检测失败（知识库任务将降级为临时线程）")
    return status
