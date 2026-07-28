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

log = get_logger("services.tool_loop")

DisconnectChecker = Callable[[], Awaitable[bool]]

_TABLE_FORMAT_HINT = (
    "展示多行查询结果或结构化列表时，请使用 Markdown 表格"
    "（形如 | 列1 | 列2 | 与 | --- | --- |），"
    "不要用空格对齐的纯文本伪表格，便于前端渲染为可横向滚动的真实表格。"
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
        tool_calls = getattr(ai, "tool_calls", None) or []

        if not tool_calls:
            text = _content_to_text(ai.content)
            yield {"event": "final", "data": {"content": text, "cancelled": False}}
            return

        lc_messages.append(ai)
        for tc in tool_calls:
            if is_disconnected is not None and await is_disconnected():
                yield {
                    "event": "final",
                    "data": {"content": _content_to_text(ai.content), "cancelled": True},
                }
                return

            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            call_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
            if not isinstance(args, dict):
                try:
                    args = json.loads(args) if isinstance(args, str) else {}
                except Exception:
                    args = {}

            yield {
                "event": "tool_call",
                "data": {
                    "id": call_id,
                    "name": name,
                    "arguments": args,
                    "round": round_i + 1,
                },
            }

            tool = tool_map.get(name or "")
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

    # 超过轮次：再要一次不带工具的收尾
    log.warning("Tool loop 达到最大轮次，请求最终总结")
    closing = await chat_model.ainvoke(lc_messages)
    yield {
        "event": "final",
        "data": {
            "content": _content_to_text(getattr(closing, "content", "")),
            "cancelled": False,
            "truncated": True,
        },
    }
