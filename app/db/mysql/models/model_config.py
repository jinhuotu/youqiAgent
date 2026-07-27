"""模型配置表 ORM。"""

import enum

from sqlalchemy import Enum, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql.models.base import Base, TimestampMixin, UserScopedMixin


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """让 SQLAlchemy 持久化 Enum.value（如 text），而非成员名（如 TEXT）。"""
    return [item.value for item in enum_cls]


class ModelType(str, enum.Enum):
    """模型模态类型枚举。"""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    MULTIMODAL = "multimodal"
    EMBEDDING = "embedding"


class ModelScope(str, enum.Enum):
    """模型作用域：公共 / 私有。"""

    PUBLIC = "public"
    PRIVATE = "private"


class ModelConfig(Base, TimestampMixin, UserScopedMixin):
    """大模型配置表。

    存储用户自定义或公共的模型接入信息。
    api_key 字段在业务层加密后写入，禁止明文。
    """

    __tablename__ = "models"
    __table_args__ = {"comment": "大模型配置表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="模型展示名称")
    type: Mapped[ModelType] = mapped_column(
        Enum(ModelType, values_callable=_enum_values),
        nullable=False,
        default=ModelType.TEXT,
        comment="模态类型",
    )
    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="openai_compatible",
        comment="提供商标识：openai_compatible / ollama / deepseek / zhipu 等",
    )
    base_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="接口请求地址")
    api_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="API密钥（加密存储）",
    )
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="模型标识符")
    max_context: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=8192,
        comment="最大上下文长度（token）",
    )
    scope: Mapped[ModelScope] = mapped_column(
        Enum(ModelScope, values_callable=_enum_values),
        nullable=False,
        default=ModelScope.PRIVATE,
        index=True,
        comment="作用域 public/private",
    )
    status: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=1,
        comment="状态：1启用 0禁用",
    )
