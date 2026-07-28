"""MCP 工具命名与缓存辅助测试。"""

from app.services.mcp_tool_adapter import (
    cache_to_discovered,
    parse_qualified_tool_name,
    qualify_tool_name,
    tools_to_cache,
)
from app.services.mcp_session import DiscoveredTool


def test_qualify_and_parse_tool_name() -> None:
    q = qualify_tool_name("file-system", "read_file")
    assert q == "file-system__read_file"
    server, tool = parse_qualified_tool_name(q)
    assert server == "file-system"
    assert tool == "read_file"


def test_tools_cache_roundtrip() -> None:
    tools = [
        DiscoveredTool(name="a", description="d", input_schema={"type": "object"}),
    ]
    cache = tools_to_cache(tools)
    back = cache_to_discovered(cache)
    assert len(back) == 1
    assert back[0].name == "a"
    assert back[0].input_schema["type"] == "object"
