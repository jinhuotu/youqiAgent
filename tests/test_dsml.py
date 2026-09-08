"""DSML 工具调用解析测试。"""

from app.utils.dsml import parse_tool_calls_from_content, strip_tool_call_markup


def test_parse_deepseek_dsml_chart_invoke() -> None:
    raw = """数据已取到。接下来生成柱状图。
<|DSML|tool_calls>
<|DSML|invoke name="mcp-server-chart__generate_column_chart">
<|DSML|parameter name="title" string="true">最近10条销售订单数量对比</|DSML|parameter>
<|DSML|parameter name="values" string="true">[800, 100, 80]</|DSML|parameter>
</|DSML|invoke>
</|DSML|tool_calls>
"""
    cleaned, calls = parse_tool_calls_from_content(raw)
    assert "数据已取到" in cleaned
    assert "DSML" not in cleaned
    assert len(calls) == 1
    assert calls[0]["name"] == "mcp-server-chart__generate_column_chart"
    assert calls[0]["args"]["title"] == "最近10条销售订单数量对比"
    assert calls[0]["args"]["values"] == [800, 100, 80]


def test_strip_double_pipe_dsml() -> None:
    raw = "<||DSML||tool_calls>x</||DSML||tool_calls>只留这句话"
    assert strip_tool_call_markup(raw) == "只留这句话"


def test_parse_sql_execute_query_double_pipe() -> None:
    raw = """先查该视图/表的列结构，用 INFORMATION_SCHEMA。
<||DSML||tool_calls>
<||DSML||invoke name="sqlserver-official__execute_query">
<||DSML||parameter name="query" string="true">SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='sale' AND TABLE_NAME='SaleOrder'</||DSML||parameter>
</||DSML||invoke>
</||DSML||tool_calls>
"""
    cleaned, calls = parse_tool_calls_from_content(raw)
    assert cleaned == "先查该视图/表的列结构，用 INFORMATION_SCHEMA。"
    assert "DSML" not in cleaned
    assert len(calls) == 1
    assert calls[0]["name"] == "sqlserver-official__execute_query"
    assert "SaleOrder" in calls[0]["args"]["query"]


def test_parse_invoke_without_outer_block() -> None:
    raw = """<|DSML|invoke name="sqlserver-official__list_tables">
<|DSML|parameter name="schema">dbo</|DSML|parameter>
</|DSML|invoke>
"""
    cleaned, calls = parse_tool_calls_from_content(raw)
    assert "DSML" not in cleaned
    assert calls[0]["name"] == "sqlserver-official__list_tables"
    assert calls[0]["args"]["schema"] == "dbo"


def test_spaced_double_pipe_delimiters() -> None:
    raw = (
        '< | | DSML | | tool_calls>'
        '< | | DSML | | invoke name="foo">'
        '< | | DSML | | parameter name="x">1</ | | DSML | | parameter>'
        '</ | | DSML | | invoke>'
        '</ | | DSML | | tool_calls>'
        "done"
    )
    cleaned, calls = parse_tool_calls_from_content(raw)
    assert cleaned == "done"
    assert calls[0]["name"] == "foo"
    assert calls[0]["args"]["x"] == 1
