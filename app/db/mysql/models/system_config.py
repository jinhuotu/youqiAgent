"""全局系统配置表 ORM。"""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql.models.base import Base, TimestampMixin


class SystemConfig(Base, TimestampMixin):
    """全局系统配置表（键值对）。

    注意：本表不绑定具体用户，user_id 固定为系统级标识。
    """

    __tablename__ = "system_config"
    __table_args__ = {"comment": "全局系统配置表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 系统配置也保留 user_id 字段以满足规范，固定为 "0" 表示系统级
    user_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="0",
        index=True,
        comment="系统级配置固定为 0",
    )
    config_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        comment="配置键",
    )
    config_value: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="配置值")
    description: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        default="",
        comment="配置说明",
    )
