"""查库后跟进绘图的纯函数测试。"""

from app.services.chart_followup import (
    append_chart_markdown,
    extract_chart_image_url,
    is_chart_tool,
    is_sql_query_tool,
    query_result_has_rows,
    short_tool_name,
)


def test_short_and_sql_chart_names() -> None:
    assert short_tool_name("sqlserver-official__execute_query") == "execute_query"
    assert is_sql_query_tool("sqlserver-official__execute_query")
    assert is_sql_query_tool("execute_query")
    assert not is_sql_query_tool("sqlserver-official__list_tables")
    assert is_chart_tool("antv_mcp-server-chart__generate_column_chart")
    assert is_chart_tool("generate_pie_chart")
    assert is_chart_tool("s3__generate_bar_chart")
    assert not is_chart_tool("get_china_time")


def test_query_result_has_rows() -> None:
    assert query_result_has_rows('[{"name": "A", "qty": 1}]')
    assert query_result_has_rows('{"rows": [{"id": 1}]}')
    assert not query_result_has_rows("[]")
    assert not query_result_has_rows("工具执行失败: timeout")
    assert not query_result_has_rows("0 rows")


def test_extract_and_append_chart_url() -> None:
    url = "https://mdn.alipayobjects.com/chart.png"
    payload = '{"success": true, "resultObj": "%s"}' % url
    assert extract_chart_image_url(payload) == url
    assert extract_chart_image_url('{"success": false, "errorMessage": "bad"}') is None
    text = append_chart_markdown("本月订单如下", [url])
    assert f"![图表]({url})" in text
    assert append_chart_markdown(f"见图 ![图表]({url})", [url]) == f"见图 ![图表]({url})"
