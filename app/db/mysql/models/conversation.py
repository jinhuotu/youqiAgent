"""会话主表 ORM。"""

from typing import Optional

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql.models.base import Base, TimestampMixin, UserScopedMixin


class Conversation(Base, TimestampMixin, UserScopedMixin):
    """会话主表。

    绑定用户与模型，记录轮数、历史总结等内容，
    支持多轮对话与自动/主动总结。
    """

    __tablename__ = "conversations"
    __table_args__ = {"comment": "会话主表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        default="新会话",
        comment="会话标题",
    )
    model_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="绑定的模型配置ID",
    )
    round_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="消息轮数（user+assistant 计为一轮）",
    )
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="历史对话总结内容",
    )
