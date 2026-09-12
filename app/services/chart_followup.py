"""查库结果跟进绘图：识别 SQL/图表工具、抽取图片 URL、强制跟进提示。"""

from __future__ import annotations

import json
import re

_SQL_QUERY_NAMES = {
    "execute_query",
    "execute_sql",
    "run_query",
    "query",
    "sql_query",
}

_CHART_NAME_RE = re.compile(
    r"generate_.+(?:chart|diagram|map|graph|spreadsheet)",
    re.I,
)

CHART_FOLLOWUP_HINT = (
    "execute_query 已返回数据。你必须立刻调用 generate_*_chart"
    "（generate_column_chart / generate_bar_chart / generate_line_chart / generate_pie_chart 等）"
    "把结果画成图：选 1 个分类字段作 category 或 time、1 个数值字段作 value，"
    "映射为工具要求的 data（通常 [{category, value}] 或 [{time, value}]），点数不超过 30。"
    "禁止只输出表格就结束；绘图失败再说明原因。"
)


def short_tool_name(qualified: str) -> str:
    """server__tool → tool。"""
    name = (qualified or "").strip()
    if "__" not in name:
        return name
    return name.split("__")[-1]


def is_sql_query_tool(name: str) -> bool:
    """是否为真正跑 SQL 的查询工具（不含 list_tables / describe_table）。"""
    short = short_tool_name(name).lower()
    if short in _SQL_QUERY_NAMES:
        return True
    return short.startswith("execute_") and "query" in short


def is_chart_tool(name: str) -> bool:
    """是否为 AntV mcp-server-chart 一类绘图工具。"""
    raw = name or ""
    short = short_tool_name(raw)
    if _CHART_NAME_RE.search(short):
        return True
    lowered = raw.lower().replace("_", "-")
    return "mcp-server-chart" in lowered


def query_result_has_rows(result_text: str) -> bool:
    """查询结果是否包含可绘图的数据行。"""
    text = (result_text or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith(("工具执行失败", "未知工具", "[tool error]")):
        return False
    if re.search(r"\b0 rows?\b", lowered) or "查询结果为空" in text:
        return False
    try:
        data = json.loads(text)
    except Exception:
        return len(text) >= 20
    if data in ([], {}, None):
        return False
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        if data.get("success") is False:
            return False
        for key in ("rows", "data", "result", "items", "recordset"):
            val = data.get(key)
            if isinstance(val, list):
                return len(val) > 0
        return True
    return True


def _looks_like_url(value: str) -> bool:
    v = (value or "").strip()
    return v.startswith(("http://", "https://", "/"))


def extract_chart_image_url(result_text: str) -> str | None:
    """从图表工具返回值中取出图片 URL（AntV 为 resultObj）。"""
    text = (result_text or "").strip()
    if not text:
        return None
    payloads: list[object] = []
    try:
        payloads.append(json.loads(text))
    except Exception:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                payloads.append(json.loads(match.group(0)))
            except Exception:
                pass
    for data in payloads:
        if not isinstance(data, dict):
            continue
        if data.get("success") is False:
            continue
        for key in ("resultObj", "url", "image", "imageUrl", "image_url"):
            val = data.get(key)
            if isinstance(val, str) and _looks_like_url(val):
                return val.strip()
    md = re.search(r"!\[[^\]]*\]\((https?://[^)\s]+)\)", text)
    if md:
        return md.group(1)
    quoted = re.search(r'"resultObj"\s*:\s*"(https?://[^"]+)"', text)
    if quoted:
        return quoted.group(1)
    return None


def append_chart_markdown(text: str, urls: list[str]) -> str:
    """把尚未出现在正文里的图表 URL 追加为 Markdown 图片。"""
    body = text or ""
    extras: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not url or url in seen or url in body:
            continue
        seen.add(url)
        extras.append(f"![图表]({url})")
    if not extras:
        return body
    prefix = body.rstrip()
    joined = "\n\n".join(extras)
    return f"{prefix}\n\n{joined}" if prefix else joined
