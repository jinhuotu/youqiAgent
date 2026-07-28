"""将 MCP 工具适配为 LangChain StructuredTool。"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from app.core.logger import get_logger
from app.db.mysql.models.mcp_server import McpServer
from app.services.mcp_session import DiscoveredTool, mcp_session_manager

log = get_logger("agent.tool_adapter")


def qualify_tool_name(server_name: str, tool_name: str) -> str:
    """生成全局唯一工具名。"""
    safe_server = "".join(c if c.isalnum() or c in "_-" else "_" for c in server_name)
    safe_tool = "".join(c if c.isalnum() or c in "_-" else "_" for c in tool_name)
    return f"{safe_server}__{safe_tool}"


def parse_qualified_tool_name(qualified: str) -> tuple[str, str]:
    """解析 server__tool 名称。"""
    if "__" not in qualified:
        return "", qualified
    server, tool = qualified.split("__", 1)
    return server, tool


def _schema_to_pydantic(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """从 JSON Schema 生成简易 Pydantic 入参模型。"""
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields: dict[str, Any] = {}
    for key, prop in props.items():
        if not isinstance(prop, dict):
            prop = {}
        typ = prop.get("type", "string")
        py_type: Any = str
        if typ == "integer":
            py_type = int
        elif typ == "number":
            py_type = float
        elif typ == "boolean":
            py_type = bool
        elif typ == "array":
            py_type = list
        elif typ == "object":
            py_type = dict
        default = ... if key in required else None
        fields[key] = (
            Optional[py_type] if default is None else py_type,
            Field(default=default, description=prop.get("description") or ""),
        )
    if not fields:
        fields["payload"] = (
            Optional[dict],
            Field(default=None, description="可选原始参数对象"),
        )
    model_name = f"McpArgs_{name}"[:60]
    return create_model(model_name, **fields)  # type: ignore[call-overload]


def _make_tool(row: McpServer, t: DiscoveredTool) -> StructuredTool:
    qname = qualify_tool_name(row.name, t.name)
    args_model = _schema_to_pydantic(qname, t.input_schema or {})
    server_row = row
    tool_name = t.name
    description = t.description or f"MCP tool {t.name} from {row.name}"

    async def _arun(**kwargs: Any) -> str:
        args = {k: v for k, v in kwargs.items() if v is not None}
        if set(args.keys()) == {"payload"} and isinstance(args.get("payload"), dict):
            args = args["payload"]
        log.info(f"调用 MCP 工具: server={server_row.name}, tool={tool_name}")
        return await mcp_session_manager.call_tool(server_row, tool_name, args)

    def _run(**kwargs: Any) -> str:
        raise RuntimeError("MCP 工具仅支持异步调用")

    return StructuredTool.from_function(
        coroutine=_arun,
        func=_run,
        name=qname,
        description=description,
        args_schema=args_model,
    )


def build_langchain_tools(
    servers: list[tuple[McpServer, list[DiscoveredTool]]],
) -> list[StructuredTool]:
    """将多个 MCP Server 的工具转为 LangChain Tools。"""
    return [_make_tool(row, t) for row, discovered in servers for t in discovered]


def tools_to_cache(tools: list[DiscoveredTool]) -> list[dict[str, Any]]:
    """DiscoveredTool → 可 JSON 缓存结构。"""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema or {},
        }
        for t in tools
    ]


def cache_to_discovered(cache: Any) -> list[DiscoveredTool]:
    """缓存 JSON → DiscoveredTool。"""
    if not cache or not isinstance(cache, list):
        return []
    out: list[DiscoveredTool] = []
    for item in cache:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        out.append(
            DiscoveredTool(
                name=name,
                description=str(item.get("description") or ""),
                input_schema=item.get("input_schema")
                if isinstance(item.get("input_schema"), dict)
                else {},
            )
        )
    return out
