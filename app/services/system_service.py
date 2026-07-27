"""系统信息业务服务。"""

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import get_current_user_id
from app.core.logger import get_logger
from app.db.mysql.session import check_mysql_connection
from app.db.redis import check_redis_connection
from app.schemas.response.system import SystemInfoResponse
from app.services.conversation_service import ConversationService
from app.services.model_service import ModelService
from app.services.vector_service import VectorService

log = get_logger("services.system")


class SystemService:
    """系统运行状态概览。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def get_info(self) -> SystemInfoResponse:
        """汇总系统信息。"""
        model_service = ModelService(self.db)
        conv_service = ConversationService(self.db)
        type_counts = model_service.count_enabled_by_type()
        enabled_total = sum(type_counts.values())
        user_conv_total = conv_service.count_by_user(get_current_user_id())

        mysql_ok = check_mysql_connection()
        redis_ok = check_redis_connection()
        try:
            chroma_ok = VectorService().health_check()
        except Exception:
            chroma_ok = False

        log.info(
            f"系统信息查询: models={enabled_total}, convs={user_conv_total}, "
            f"mysql={mysql_ok}, redis={redis_ok}, chroma={chroma_ok}"
        )
        return SystemInfoResponse(
            version=self.settings.app_version,
            env=self.settings.env,
            enabled_model_total=enabled_total,
            model_type_counts=type_counts,
            user_conversation_total=user_conv_total,
            mysql_status=mysql_ok,
            redis_status=redis_ok,
            chroma_status=chroma_ok,
        )
