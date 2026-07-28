"""模型管理业务服务。

实现公共/私有模型的 CRUD，严格按 user_id 做数据隔离。
公共模型配置启用 Redis 缓存以降低数据库压力。
"""

from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import get_current_role, get_current_user_id
from app.core.exceptions import BusinessError, ForbiddenError, NotFoundError
from app.core.logger import get_logger
from app.core.security import decrypt_text, encrypt_text, mask_api_key
from app.db.mysql.models.conversation import Conversation
from app.db.mysql.models.knowledge import KnowledgeBase
from app.db.mysql.models.model_config import ModelConfig, ModelScope, ModelType
from app.db.redis import CACHE_PREFIX_PUBLIC_MODELS, RedisCache
from app.schemas.request.model import ModelCreateRequest, ModelUpdateRequest
from app.schemas.response.model import ModelResponse

log = get_logger("services.model")


class ModelService:
    """模型配置业务逻辑。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.cache = RedisCache()
        self.settings = get_settings()

    def _to_response(self, row: ModelConfig) -> ModelResponse:
        """ORM 转响应，API Key 脱敏。"""
        plain = decrypt_text(row.api_key or "")
        return ModelResponse(
            id=row.id,
            name=row.name,
            type=row.type,
            provider=row.provider,
            base_url=row.base_url,
            api_key_masked=mask_api_key(plain),
            model_id=row.model_id,
            max_context=row.max_context,
            scope=row.scope,
            user_id=row.user_id,
            status=row.status,
            create_time=row.create_time,
            update_time=row.update_time,
        )

    def _visible_query(self, user_id: str):
        """构建当前用户可见模型的基础查询：公共 + 自己的私有。"""
        return select(ModelConfig).where(
            or_(
                ModelConfig.scope == ModelScope.PUBLIC,
                (ModelConfig.scope == ModelScope.PRIVATE) & (ModelConfig.user_id == user_id),
            )
        )

    def list_models(
        self,
        *,
        model_type: Optional[ModelType] = None,
        status: Optional[int] = None,
    ) -> list[ModelResponse]:
        """获取当前用户可用模型列表。

        Args:
            model_type: 按模态类型筛选
            status: 按启用状态筛选
        """
        user_id = get_current_user_id()
        stmt = self._visible_query(user_id)
        if model_type is not None:
            stmt = stmt.where(ModelConfig.type == model_type)
        if status is not None:
            stmt = stmt.where(ModelConfig.status == status)
        stmt = stmt.order_by(ModelConfig.id.desc())
        rows = self.db.scalars(stmt).all()
        log.info(f"查询模型列表，user_id={user_id}, count={len(rows)}")
        return [self._to_response(r) for r in rows]

    def get_model(self, model_id: int) -> ModelResponse:
        """获取单个模型详情（可见性校验）。"""
        row = self._get_accessible_row(model_id)
        return self._to_response(row)

    def get_model_orm(self, model_id: int) -> ModelConfig:
        """获取 ORM 行（供聊天等内部调用，含可见性校验）。"""
        return self._get_accessible_row(model_id)

    def get_chat_model_orm(self, model_id: int) -> ModelConfig:
        """获取可用于对话的模型（排除 embedding）。"""
        row = self._get_accessible_row(model_id)
        if row.type == ModelType.EMBEDDING:
            raise BusinessError(
                f"「{row.name}」是向量模型，不能用于对话；请选择 text/multimodal 等对话模型"
            )
        return row

    def get_embedding_model_orm(self, model_id: int) -> ModelConfig:
        """获取可用于知识库 Embedding 的模型。"""
        row = self._get_accessible_row(model_id)
        if row.type != ModelType.EMBEDDING:
            raise BusinessError(
                f"「{row.name}」不是向量模型；知识库 Embedding 请选择 type=embedding 的配置"
            )
        return row

    def _get_accessible_row(self, model_id: int) -> ModelConfig:
        """按可见性获取模型行，不可见则 404。"""
        user_id = get_current_user_id()
        row = self.db.get(ModelConfig, model_id)
        if row is None:
            raise NotFoundError("模型不存在")
        # 公共模型所有人可见；私有模型仅创建者可见
        if row.scope == ModelScope.PRIVATE and row.user_id != user_id:
            raise NotFoundError("模型不存在")
        return row

    def create_model(self, req: ModelCreateRequest) -> ModelResponse:
        """新增模型配置。

        公共模型仅管理员可创建；私有模型绑定当前 user_id。
        """
        user_id = get_current_user_id()
        role = get_current_role()

        if req.scope == ModelScope.PUBLIC:
            if not self.settings.enable_admin_role or role != "admin":
                raise ForbiddenError("仅管理员可创建公共模型")
            owner_id = "0"
        else:
            owner_id = user_id

        row = ModelConfig(
            name=req.name,
            type=req.type,
            provider=req.provider,
            base_url=req.base_url,
            api_key=encrypt_text(req.api_key or ""),
            model_id=req.model_id,
            max_context=req.max_context,
            scope=req.scope,
            user_id=owner_id,
            status=req.status,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        self._invalidate_public_cache(row)
        log.info(f"创建模型成功: id={row.id}, name={row.name}, scope={row.scope}")
        return self._to_response(row)

    def update_model(self, model_id: int, req: ModelUpdateRequest) -> ModelResponse:
        """修改模型配置（权限校验）。"""
        row = self._get_editable_row(model_id)
        data = req.model_dump(exclude_unset=True)

        # 作用域变更为公共时需管理员权限
        if "scope" in data and data["scope"] == ModelScope.PUBLIC:
            if not self.settings.enable_admin_role or get_current_role() != "admin":
                raise ForbiddenError("仅管理员可将模型设为公共")
            data["user_id"] = "0"

        if "api_key" in data and data["api_key"] is not None:
            data["api_key"] = encrypt_text(data["api_key"])

        for key, value in data.items():
            if hasattr(row, key):
                setattr(row, key, value)

        self.db.commit()
        self.db.refresh(row)
        self._invalidate_public_cache(row)
        log.info(f"更新模型成功: id={row.id}")
        return self._to_response(row)

    def delete_model(self, model_id: int) -> None:
        """删除模型配置。

        若仍被会话或知识库引用则拒绝删除，避免产生脏引用。
        """
        row = self._get_editable_row(model_id)
        conv_count = self.db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.model_id == model_id)
        ) or 0
        kb_count = self.db.scalar(
            select(func.count())
            .select_from(KnowledgeBase)
            .where(KnowledgeBase.embedding_model_id == model_id)
        ) or 0
        if conv_count or kb_count:
            raise BusinessError(
                f"模型仍被引用，无法删除（会话 {conv_count} 个，知识库 {kb_count} 个）。"
                "请先更换或删除相关会话/知识库后再试"
            )
        self.db.delete(row)
        self.db.commit()
        self._invalidate_public_cache(row)
        log.info(f"删除模型成功: id={model_id}")

    def _get_editable_row(self, model_id: int) -> ModelConfig:
        """获取可编辑的模型行。

        规则：
        - 私有模型：仅创建者可编辑/删除
        - 公共模型：仅管理员可编辑/删除
        """
        user_id = get_current_user_id()
        role = get_current_role()
        row = self.db.get(ModelConfig, model_id)
        if row is None:
            raise NotFoundError("模型不存在")

        if row.scope == ModelScope.PUBLIC:
            if not self.settings.enable_admin_role or role != "admin":
                raise ForbiddenError("仅管理员可管理公共模型")
        else:
            if row.user_id != user_id:
                raise ForbiddenError("无权操作该私有模型")
        return row

    def _invalidate_public_cache(self, row: ModelConfig) -> None:
        """公共模型变更时清理缓存。"""
        if row.scope == ModelScope.PUBLIC:
            self.cache.delete(CACHE_PREFIX_PUBLIC_MODELS)

    def count_enabled_by_type(self) -> dict[str, int]:
        """统计已启用模型按模态类型的数量（系统信息用）。"""
        rows = self.db.scalars(
            select(ModelConfig).where(ModelConfig.status == 1)
        ).all()
        counts: dict[str, int] = {}
        for r in rows:
            key = r.type.value if hasattr(r.type, "value") else str(r.type)
            counts[key] = counts.get(key, 0) + 1
        return counts
