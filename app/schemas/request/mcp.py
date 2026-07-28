"""MCP Server 请求 Schema。"""

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.db.mysql.models.mcp_server import McpScope, McpTransport


class McpServerCreateRequest(BaseModel):
    """创建 MCP Server。"""

    name: str = Field(..., min_length=1, max_length=128, description="唯一名称")
    description: Optional[str] = Field(default=None, max_length=512)
    transport: McpTransport = Field(default=McpTransport.STDIO)
    command: Optional[str] = Field(default=None, max_length=256)
    args: Optional[list[str]] = Field(default=None, description="stdio 参数，每行一项")
    url: Optional[str] = Field(default=None, max_length=1024)
    env: Optional[dict[str, str]] = Field(default=None, description="环境变量")
    scope: McpScope = Field(default=McpScope.PUBLIC)
    status: int = Field(default=1, ge=0, le=1)

    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        name = v.strip()
        if not name:
            raise ValueError("名称不能为空")
        return name

    @model_validator(mode="after")
    def _transport_fields(self) -> "McpServerCreateRequest":
        if self.transport == McpTransport.STDIO:
            if not (self.command or "").strip():
                raise ValueError("stdio 协议必须填写命令")
        else:
            if not (self.url or "").strip():
                raise ValueError("sse/http 协议必须填写 URL")
        return self


class McpServerUpdateRequest(BaseModel):
    """更新 MCP Server。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=512)
    transport: Optional[McpTransport] = None
    command: Optional[str] = Field(default=None, max_length=256)
    args: Optional[list[str]] = None
    url: Optional[str] = Field(default=None, max_length=1024)
    env: Optional[dict[str, str]] = None
    scope: Optional[McpScope] = None
    status: Optional[int] = Field(default=None, ge=0, le=1)
