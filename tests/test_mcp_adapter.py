"""MCP 工具命名与缓存辅助测试。"""

import re

from app.services.mcp_tool_adapter import (
    cache_to_discovered,
    parse_qualified_tool_name,
    qualify_tool_name,
    restore_mcp_arguments,
    tools_to_cache,
)
from app.services.mcp_session import DiscoveredTool


def test_qualify_and_parse_tool_name() -> None:
    q = qualify_tool_name("file-system", "read_file")
    assert q == "file-system__read_file"
    server, tool = parse_qualified_tool_name(q)
    assert server == "file-system"
    assert tool == "read_file"


def test_qualify_tool_name_strips_non_ascii() -> None:
    q = qualify_tool_name("通用工具（时间）", "get_china_time", server_id=12)
    assert q == "s12__get_china_time"
    assert re.fullmatch(r"[a-zA-Z0-9_-]+", q)


def test_restore_mcp_schema_argument() -> None:
    assert restore_mcp_arguments({"sql_schema": "sale", "table": "SaleOrder"}) == {
        "schema": "sale",
        "table": "SaleOrder",
    }


def test_tools_cache_roundtrip() -> None:
    tools = [
        DiscoveredTool(name="a", description="d", input_schema={"type": "object"}),
    ]
    cache = tools_to_cache(tools)
    back = cache_to_discovered(cache)
    assert len(back) == 1
    assert back[0].name == "a"
    assert back[0].input_schema["type"] == "object"
