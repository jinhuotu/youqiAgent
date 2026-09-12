"""对话工具调用循环（MCP / LangChain tools）。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.core.config import get_settings
from app.core.logger import get_logger
from app.services.chart_followup import (
    CHART_FOLLOWUP_HINT,
    append_chart_markdown,
    extract_chart_image_url,
    is_chart_tool,
    is_sql_query_tool,
    query_result_has_rows,
)
from app.utils.dsml import parse_tool_calls_from_content, strip_tool_call_markup

log = get_logger("services.tool_loop")

DisconnectChecker = Callable[[], Awaitable[bool]]

_TOOL_LOOP_HINT = (
    "展示多行查询结果或结构化列表时，请使用 Markdown 表格"
    "（形如 | 列1 | 列2 | 与 | --- | --- |），"
    "不要用空格对齐的纯文本伪表格，便于前端渲染为可横向滚动的真实表格。"
    "禁止在回复中输出 DSML/XML 工具标记；必须通过 function calling 调用工具。"
    "execute_query 一旦返回多行或汇总数据，必须立刻再调用 generate_*_chart 绘图"
    "（柱状 generate_column_chart、条形 generate_bar_chart、折线 generate_line_chart、"
    "占比 generate_pie_chart）。把查询结果映射为工具 data："
    "1 个分类字段→category 或 time，1 个数值字段→value，点数不超过 30，不要塞整张宽表。"
    "图表工具返回的 resultObj 是图片 URL，最终回复必须用 Markdown 图片写出：![图表](url)。"
    "表格可以同时给，但不能替代绘图；没有 generate_*_chart 工具时才可以只给表格。"
    "SQL 查询范围：只能使用 MCP 已配置的连接及当前默认库（如 BestMesDB_MESSOFT）。"
    "禁止跨库：不要查其它 BestMesDB_*，不要用「其它库.schema.表」，不要 list_databases 后让用户选工厂。"
    "本库按业务架构（schema）分模块，不要写死某一张表名。"
    "查数固定三步且尽量短：①按用户意图选定 schema；②list_tables(schema=该架构) 定位表；"
    "③describe_table 最多一次后立刻 execute_query（Top N 或汇总）。"
    "意图→架构对照：销售/订单/发货/合同→sale；采购/请购→purc；生产/工单/工序/工位/班组→make；"
    "库存/仓库/物料库存→invn；质检/质量→qual；财务/应收应付→finance；客户→cust；"
    "人事/员工/部门→hman；通用主数据/物料档案→dbo 或 comn；报表→report。"
    "list_tables 默认 dbo，不传 schema 会漏掉业务表。禁止只扫 dbo 就断言「没有该业务」。"
    "若同一单据有头表+明细表（表名常成对，如 Xxx 与 XxxItem），必须一并查出，不要只出头表。"
    "头表金额为 0 时以明细数量/金额为准。状态编码尽量译成中文，找不到字典则保留编码。"
    "不要先 list_connections / test_connection / list_databases。探查类工具合计不超过 3 次。"
)


def _with_table_format_hint(messages: list[BaseMessage]) -> list[BaseMessage]:
    """在工具对话中补充表格输出格式与 SQL 范围提示。"""
    out: list[BaseMessage] = []
    found = False
    for msg in messages:
        if not found and isinstance(msg, SystemMessage):
            text = str(msg.content or "")
            if "只能使用 MCP 已配置的连接" not in text:
                out.append(SystemMessage(content=f"{text}\n\n{_TOOL_LOOP_HINT}"))
            else:
                out.append(msg)
            found = True
        else:
            out.append(msg)
    if not found:
        out.insert(0, SystemMessage(content=_TOOL_LOOP_HINT))
    return out


def dict_messages_to_lc(messages: list[dict[str, str]]) -> list[BaseMessage]:
    """标准 role/content 字典 → LangChain Message。"""
    result: list[BaseMessage] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            result.append(SystemMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
        else:
            result.append(HumanMessage(content=content))
    return result


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def _normalize_tool_calls(raw: Any) -> list[dict[str, Any]]:
    """LangChain tool_calls → 统一 dict 列表。"""
    out: list[dict[str, Any]] = []
    for tc in raw or []:
        if isinstance(tc, dict):
            name = tc.get("name") or ""
            call_id = tc.get("id") or ""
            args = tc.get("args") or tc.get("arguments") or {}
        else:
            name = getattr(tc, "name", "") or ""
            call_id = getattr(tc, "id", "") or ""
            args = getattr(tc, "args", {}) or {}
        if not isinstance(args, dict):
            try:
                args = json.loads(args) if isinstance(args, str) else {}
            except Exception:
                args = {}
        out.append({"id": call_id, "name": name, "args": args})
    return out


def _lookup_tool(name: str, tool_map: dict[str, BaseTool]) -> BaseTool | None:
    if name in tool_map:
        return tool_map[name]
    compact = (name or "").replace("__", "_")
    for key, tool in tool_map.items():
        if key.replace("__", "_") == compact:
            return tool
    return None


def _reasoning_kwargs(ai: Any) -> dict[str, Any]:
    """取出 DeepSeek thinking 的 reasoning_content，多轮必须原样回传。"""
    extra: dict[str, Any] = {}
    ak = getattr(ai, "additional_kwargs", None) or {}
    if isinstance(ak, dict) and ak.get("reasoning_content"):
        extra["reasoning_content"] = ak["reasoning_content"]
    rm = getattr(ai, "response_metadata", None) or {}
    if "reasoning_content" not in extra and isinstance(rm, dict) and rm.get("reasoning_content"):
        extra["reasoning_content"] = rm["reasoning_content"]
    return extra


def _as_history_ai(
    spoken: str,
    tool_calls: list[dict[str, Any]],
    *,
    source: Any = None,
) -> AIMessage:
    """把解析出的调用写成带 tool_calls 的助手消息，供后续 ToolMessage 衔接。"""
    formatted: list[dict[str, Any]] = []
    for tc in tool_calls:
        formatted.append(
            {
                "name": tc.get("name") or "",
                "args": tc.get("args") if isinstance(tc.get("args"), dict) else {},
                "id": tc.get("id") or "",
                "type": "tool_call",
            }
        )
    return AIMessage(
        content=spoken or "",
        tool_calls=formatted,
        additional_kwargs=_reasoning_kwargs(source),
    )


def _extract_tool_calls(ai: AIMessage) -> tuple[str, list[dict[str, Any]], bool]:
    """优先用结构化 tool_calls；否则从 DSML 正文解析。

    Returns:
        (给用户看的正文, 工具调用, 是否从 DSML 解析而来)
    """
    text = _content_to_text(ai.content)
    structured = _normalize_tool_calls(getattr(ai, "tool_calls", None) or [])
    if structured:
        return strip_tool_call_markup(text), structured, False
    cleaned, parsed = parse_tool_calls_from_content(text)
    if parsed:
        log.info(f"从 DSML 正文解析出 {len(parsed)} 个工具调用")
        return cleaned, parsed, True
    return strip_tool_call_markup(text), [], False


async def run_tool_loop(
    chat_model: BaseChatModel,
    messages: list[dict[str, str]],
    tools: list[BaseTool],
    *,
    is_disconnected: Optional[DisconnectChecker] = None,
) -> AsyncIterator[dict[str, Any]]:
    """执行 bind_tools + 多轮 tool call。

    Yields:
        {"event": "tool_call"|"tool_result"|"final", "data": {...}}
        final.data.content 为最终助手文本
    """
    settings = get_settings()
    max_rounds = max(1, settings.mcp_tool_max_rounds)
    if not tools:
        # 无工具：交给调用方走普通路径
        yield {"event": "final", "data": {"content": "", "skipped": True}}
        return

    tool_map = {t.name: t for t in tools}
    bound = chat_model.bind_tools(tools)
    lc_messages = _with_table_format_hint(dict_messages_to_lc(messages))
    has_chart_tools = any(is_chart_tool(name) for name in tool_map)
    pending_chart = False
    chart_nudge_used = False
    chart_urls: list[str] = []

    for round_i in range(max_rounds):
        if is_disconnected is not None and await is_disconnected():
            yield {
                "event": "final",
                "data": {"content": "", "cancelled": True},
            }
            return

        log.info(f"Tool loop 轮次 {round_i + 1}/{max_rounds}")
        yield {
            "event": "status",
            "data": {"message": f"正在调用模型（第 {round_i + 1} 轮）…", "round": round_i + 1},
        }
        ai: AIMessage = await bound.ainvoke(lc_messages)  # type: ignore[assignment]
        spoken, tool_calls, from_dsml = _extract_tool_calls(ai)

        if not tool_calls:
            if has_chart_tools and pending_chart and not chart_nudge_used:
                chart_nudge_used = True
                log.info("查询已返回数据但未绘图，注入图表跟进提示")
                lc_messages.append(SystemMessage(content=CHART_FOLLOWUP_HINT))
                yield {
                    "event": "status",
                    "data": {"message": "正在根据查询结果绘图…", "round": round_i + 1},
                }
                continue
            yield {
                "event": "final",
                "data": {
                    "content": append_chart_markdown(spoken, chart_urls),
                    "cancelled": False,
                },
            }
            return

        # DSML 写在 content 里时，必须改写成结构化 tool_calls，否则下一轮无法接 ToolMessage
        lc_messages.append(
            _as_history_ai(spoken, tool_calls, source=ai) if from_dsml else ai
        )
        for tc in tool_calls:
            if is_disconnected is not None and await is_disconnected():
                yield {
                    "event": "final",
                    "data": {"content": spoken, "cancelled": True},
                }
                return

            name = tc.get("name") or ""
            call_id = tc.get("id") or ""
            args = tc.get("args") if isinstance(tc.get("args"), dict) else {}

            yield {
                "event": "tool_call",
                "data": {
                    "id": call_id,
                    "name": name,
                    "arguments": args,
                    "round": round_i + 1,
                },
            }

            tool = _lookup_tool(name, tool_map)
            if tool is None:
                result_text = f"未知工具: {name}"
            else:
                try:
                    result_text = await tool.ainvoke(args)
                    if not isinstance(result_text, str):
                        result_text = json.dumps(result_text, ensure_ascii=False, default=str)
                except Exception as e:
                    log.exception(f"工具执行失败: {name}")
                    result_text = f"工具执行失败: {e}"

            image_url = None
            if is_sql_query_tool(name) and query_result_has_rows(str(result_text)):
                pending_chart = True
            if is_chart_tool(name):
                image_url = extract_chart_image_url(str(result_text))
                if image_url:
                    chart_urls.append(image_url)
                    pending_chart = False
                elif not str(result_text).startswith(("工具执行失败", "未知工具", "[tool error]")):
                    pending_chart = False

            yield {
                "event": "tool_result",
                "data": {
                    "id": call_id,
                    "name": name,
                    "content": result_text,
                    "round": round_i + 1,
                    **({"image_url": image_url} if image_url else {}),
                },
            }
            lc_messages.append(
                ToolMessage(content=result_text, tool_call_id=call_id or name or "tool")
            )

    # 超过轮次：再要一次不带工具的收尾；若仍吐 DSML 则再执行一轮后总结
    log.warning("Tool loop 达到最大轮次，请求最终总结")
    closing = await chat_model.ainvoke(lc_messages)
    spoken, extra_calls, from_dsml = _extract_tool_calls(closing)  # type: ignore[arg-type]
    if extra_calls:
        log.info(f"收尾回复含 DSML，补执行 {len(extra_calls)} 个工具")
        if from_dsml:
            lc_messages.append(_as_history_ai(spoken, extra_calls, source=closing))
        else:
            lc_messages.append(closing)  # type: ignore[arg-type]
        for tc in extra_calls:
            name = tc.get("name") or ""
            args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
            tool = _lookup_tool(name, tool_map)
            if tool is None:
                result_text = f"未知工具: {name}"
            else:
                try:
                    result_text = await tool.ainvoke(args)
                    if not isinstance(result_text, str):
                        result_text = json.dumps(result_text, ensure_ascii=False, default=str)
                except Exception as e:
                    result_text = f"工具执行失败: {e}"
            yield {
                "event": "tool_call",
                "data": {
                    "id": tc.get("id") or "",
                    "name": name,
                    "arguments": args,
                    "round": max_rounds,
                },
            }
            image_url = extract_chart_image_url(str(result_text)) if is_chart_tool(name) else None
            if image_url:
                chart_urls.append(image_url)
            yield {
                "event": "tool_result",
                "data": {
                    "id": tc.get("id") or "",
                    "name": name,
                    "content": result_text,
                    "round": max_rounds,
                    **({"image_url": image_url} if image_url else {}),
                },
            }
            lc_messages.append(
                ToolMessage(
                    content=result_text,
                    tool_call_id=str(tc.get("id") or name or "tool"),
                )
            )
        closing = await chat_model.ainvoke(lc_messages)
        spoken = strip_tool_call_markup(_content_to_text(getattr(closing, "content", "")))
    yield {
        "event": "final",
        "data": {
            "content": append_chart_markdown(spoken, chart_urls),
            "cancelled": False,
            "truncated": True,
        },
    }
