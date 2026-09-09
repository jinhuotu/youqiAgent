"""将 MCP 工具适配为 LangChain StructuredTool。"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model

from app.core.logger import get_logger
from app.db.mysql.models.mcp_server import McpServer
from app.services.mcp_session import DiscoveredTool, mcp_session_manager

log = get_logger("agent.tool_adapter")

# OpenAI / DeepSeek function.name 仅允许 ASCII：^[a-zA-Z0-9_-]+$
_OPENAI_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_OPENAI_NAME_MAX = 64


def _ascii_slug(text: str, fallback: str) -> str:
    """去掉非 ASCII 字母数字，压缩连续下划线。"""
    slug = _OPENAI_NAME_RE.sub("_", text or "")
    slug = re.sub(r"_+", "_", slug).strip("_-")
    if slug and re.search(r"[a-zA-Z0-9]", slug):
        return slug
    return fallback


def qualify_tool_name(
    server_name: str,
    tool_name: str,
    *,
    server_id: int | None = None,
) -> str:
    """生成符合 OpenAI function.name 规则的全局唯一工具名。

    Python ``str.isalnum()`` 会把中文当成合法字符，但 DeepSeek 等会 400：
    Invalid tools[n].function.name，须匹配 ``^[a-zA-Z0-9_-]+$``。
    """
    fallback_server = f"s{server_id}" if server_id is not None else "mcp"
    safe_server = _ascii_slug(server_name, fallback_server)
    safe_tool = _ascii_slug(tool_name, "tool")
    name = f"{safe_server}__{safe_tool}"
    if len(name) <= _OPENAI_NAME_MAX:
        return name
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    return f"{safe_server[:18]}__{safe_tool[:28]}_{digest}"[:_OPENAI_NAME_MAX]


def parse_qualified_tool_name(qualified: str) -> tuple[str, str]:
    """解析 server__tool 名称。"""
    if "__" not in qualified:
        return "", qualified
    server, tool = qualified.split("__", 1)
    return server, tool


# Pydantic BaseModel 已占用 schema 等方法名，MCP 的 schema 参数需改名再回写
_RESERVED_ARG_RENAME = {"schema": "sql_schema"}


class _McpArgsBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


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
        desc = prop.get("description") or ""
        field_name = _RESERVED_ARG_RENAME.get(key, key)
        extra: dict[str, Any] = {"description": desc}
        if field_name != key:
            extra["alias"] = key
            if key == "schema":
                extra["description"] = (
                    f"{desc} SQL Server 架构名，须按用户意图传入："
                    "sale/purc/make/invn/qual/finance/cust/hman/dbo/comn/report 等。"
                    "默认 dbo 会漏掉业务表，禁止不传 schema 就断言没有数据。"
                ).strip()
        fields[field_name] = (
            Optional[py_type] if default is None else py_type,
            Field(default=default, **extra),
        )
    if not fields:
        fields["payload"] = (
            Optional[dict],
            Field(default=None, description="可选原始参数对象"),
        )
    model_name = f"McpArgs_{name}"[:60]
    return create_model(model_name, __base__=_McpArgsBase, **fields)  # type: ignore[call-overload]


def restore_mcp_arguments(args: dict[str, Any]) -> dict[str, Any]:
    """把适配层改名的参数还原为 MCP 原始字段名。"""
    out = dict(args)
    for original, renamed in _RESERVED_ARG_RENAME.items():
        if renamed in out and original not in out:
            out[original] = out.pop(renamed)
        elif renamed in out:
            out.pop(renamed, None)
    return out


def _make_tool(row: McpServer, t: DiscoveredTool) -> StructuredTool:
    qname = qualify_tool_name(row.name, t.name, server_id=row.id)
    args_model = _schema_to_pydantic(qname, t.input_schema or {})
    server_row = row
    tool_name = t.name
    description = t.description or f"MCP tool {t.name} from {row.name}"
    if tool_name == "list_tables":
        description = (
            f"{description} 默认只列出 dbo。"
            "必须先按问题选架构再查：销售→sale，采购→purc，生产/工位班组→make，"
            "库存→invn，质检→qual，财务→finance，客户→cust。不要写死某一张表。"
        )

    async def _arun(**kwargs: Any) -> str:
        args = {k: v for k, v in kwargs.items() if v is not None}
        if set(args.keys()) == {"payload"} and isinstance(args.get("payload"), dict):
            args = args["payload"]
        args = restore_mcp_arguments(args)
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
