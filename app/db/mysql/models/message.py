"""对话消息明细表 ORM。"""

import enum

from sqlalchemy import Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql.models.base import Base, TimestampMixin, UserScopedMixin
from app.db.mysql.models.model_config import _enum_values


class MessageRole(str, enum.Enum):
    """消息角色枚举。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(Base, TimestampMixin, UserScopedMixin):
    """对话消息明细表。

    每条消息绑定会话与用户，用于历史上下文加载与分页查询。
    """

    __tablename__ = "messages"
    __table_args__ = {"comment": "对话消息明细表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="所属会话ID",
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, values_callable=_enum_values),
        nullable=False,
        comment="消息角色",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息内容")
    token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="估算 token 数",
    )
