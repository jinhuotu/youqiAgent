"""MCP Server 响应 Schema。"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.mysql.models.mcp_server import McpScope, McpTransport


class McpToolInfo(BaseModel):
    """缓存/发现的工具摘要。"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class McpServerResponse(BaseModel):
    """MCP Server 详情。

    env 明文仅对管理员回传，便于运维台编辑回显；普通用户仅见 has_env。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    transport: McpTransport
    command: Optional[str] = None
    args: Optional[list[Any]] = None
    url: Optional[str] = None
    has_env: bool = False
    env: Optional[dict[str, str]] = None
    scope: McpScope
    status: int
    tool_cache: Optional[list[McpToolInfo]] = None
    tool_count: int = 0
    last_sync_at: Optional[datetime] = None
    last_error: Optional[str] = None
    user_id: str
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


class McpTestResponse(BaseModel):
    """测试/同步结果。"""

    ok: bool
    message: str
    tools: list[McpToolInfo] = Field(default_factory=list)
