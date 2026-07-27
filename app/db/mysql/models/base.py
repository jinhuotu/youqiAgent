"""SQLAlchemy 声明式基类与公共混入。"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""

    pass


class TimestampMixin:
    """自动维护创建/更新时间的混入类。"""

    create_time: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )


class UserScopedMixin:
    """用户隔离混入：所有业务表必须包含 user_id 并建立索引。"""

    user_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="所属用户ID，公共资源为 0",
    )
