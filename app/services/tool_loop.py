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
from app.utils.dsml import parse_tool_calls_from_content, strip_tool_call_markup

log = get_logger("services.tool_loop")

DisconnectChecker = Callable[[], Awaitable[bool]]

_TABLE_FORMAT_HINT = (
    "展示多行查询结果或结构化列表时，请使用 Markdown 表格"
    "（形如 | 列1 | 列2 | 与 | --- | --- |），"
    "不要用空格对齐的纯文本伪表格，便于前端渲染为可横向滚动的真实表格。"
    "禁止在回复中输出 DSML/XML 工具标记；必须通过 function calling 调用工具。"
    "数据已拿到后直接给出表格或结论，不要把工具调用写成正文。"
)


def _with_table_format_hint(messages: list[BaseMessage]) -> list[BaseMessage]:
    """在工具对话中补充表格输出格式提示。"""
    out: list[BaseMessage] = []
    found = False
    for msg in messages:
        if not found and isinstance(msg, SystemMessage):
            text = str(msg.content or "")
            if "Markdown 表格" not in text:
                out.append(SystemMessage(content=f"{text}\n\n{_TABLE_FORMAT_HINT}"))
            else:
                out.append(msg)
            found = True
        else:
            out.append(msg)
    if not found:
        out.insert(0, SystemMessage(content=_TABLE_FORMAT_HINT))
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


def _as_history_ai(spoken: str, tool_calls: list[dict[str, Any]]) -> AIMessage:
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
    return AIMessage(content=spoken or "", tool_calls=formatted)


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

    for round_i in range(max_rounds):
        if is_disconnected is not None and await is_disconnected():
            yield {
                "event": "final",
                "data": {"content": "", "cancelled": True},
            }
            return

        log.info(f"Tool loop 轮次 {round_i + 1}/{max_rounds}")
        ai: AIMessage = await bound.ainvoke(lc_messages)  # type: ignore[assignment]
        spoken, tool_calls, from_dsml = _extract_tool_calls(ai)

        if not tool_calls:
            yield {"event": "final", "data": {"content": spoken, "cancelled": False}}
            return

        # DSML 写在 content 里时，必须改写成结构化 tool_calls，否则下一轮无法接 ToolMessage
        lc_messages.append(_as_history_ai(spoken, tool_calls) if from_dsml else ai)
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

            yield {
                "event": "tool_result",
                "data": {
                    "id": call_id,
                    "name": name,
                    "content": result_text,
                    "round": round_i + 1,
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
            lc_messages.append(_as_history_ai(spoken, extra_calls))
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
            yield {
                "event": "tool_result",
                "data": {
                    "id": tc.get("id") or "",
                    "name": name,
                    "content": result_text,
                    "round": max_rounds,
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
            "content": spoken,
            "cancelled": False,
            "truncated": True,
        },
    }
