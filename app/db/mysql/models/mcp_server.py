"""MCP Server 配置 ORM。"""

import enum
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Enum, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.mysql.models.base import Base, TimestampMixin, UserScopedMixin
from app.db.mysql.models.model_config import _enum_values


class McpTransport(str, enum.Enum):
    """MCP 传输协议。"""

    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


class McpScope(str, enum.Enum):
    """MCP Server 作用域。"""

    PUBLIC = "public"
    PRIVATE = "private"


class McpServer(Base, TimestampMixin, UserScopedMixin):
    """外部 MCP Server 配置。"""

    __tablename__ = "mcp_servers"
    __table_args__ = {"comment": "外部 MCP Server 配置表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        comment="唯一标识名称",
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="描述",
    )
    transport: Mapped[McpTransport] = mapped_column(
        Enum(McpTransport, values_callable=_enum_values),
        nullable=False,
        default=McpTransport.STDIO,
        comment="传输协议 stdio/sse/http",
    )
    command: Mapped[Optional[str]] = mapped_column(
        String(256),
        nullable=True,
        comment="stdio 启动命令",
    )
    args: Mapped[Optional[list[Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="stdio 参数数组",
    )
    url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
        comment="sse/http 服务地址",
    )
    env_cipher: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="环境变量 JSON（加密存储）",
    )
    scope: Mapped[McpScope] = mapped_column(
        Enum(McpScope, values_callable=_enum_values),
        nullable=False,
        default=McpScope.PUBLIC,
        index=True,
        comment="作用域",
    )
    status: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=1,
        comment="1启用 0禁用",
    )
    tool_cache: Mapped[Optional[list[Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="最近同步的工具列表缓存",
    )
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="最近同步时间",
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
        comment="最近错误信息",
    )
