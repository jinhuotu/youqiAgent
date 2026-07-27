"""提示词模板表 ORM。"""

import enum
from typing import Optional

from sqlalchemy import Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql.models.base import Base, TimestampMixin, UserScopedMixin
from app.db.mysql.models.model_config import ModelType, _enum_values


class TemplateScope(str, enum.Enum):
    """模板作用域。"""

    PUBLIC = "public"
    PRIVATE = "private"


class PromptTemplate(Base, TimestampMixin, UserScopedMixin):
    """提示词模板表。

    支持变量占位符，对话时可选择模板注入 system prompt。
    """

    __tablename__ = "prompt_templates"
    __table_args__ = {"comment": "提示词模板表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="模板名称")
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="模板内容，支持 {var} 变量占位符",
    )
    model_type: Mapped[Optional[ModelType]] = mapped_column(
        Enum(ModelType, values_callable=_enum_values),
        nullable=True,
        comment="适用模型类型，空表示通用",
    )
    scope: Mapped[TemplateScope] = mapped_column(
        Enum(TemplateScope, values_callable=_enum_values),
        nullable=False,
        default=TemplateScope.PRIVATE,
        index=True,
        comment="作用域 public/private",
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="模板描述",
    )
