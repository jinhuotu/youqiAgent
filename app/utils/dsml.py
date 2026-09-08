"""从模型正文解析/剥离非标准工具调用标记（DeepSeek / 豆包 DSML）。"""

from __future__ import annotations

import json
import re
import secrets
from typing import Any

# DeepSeek / 豆包可能用 ASCII `|` 或全角 `｜`，且常写成双竖线：
#   <|DSML|tool_calls>  或  <｜｜DSML｜｜tool_calls>
_PIPE_CHARS = "|\uff5c"

_OPEN_DELIM = re.compile(
    r"<\s*\|(?:\s*\|)*\s*DSML\s*\|(?:\s*\|)*",
    re.IGNORECASE,
)
_CLOSE_DELIM = re.compile(
    r"</\s*\|(?:\s*\|)*\s*DSML\s*\|(?:\s*\|)*",
    re.IGNORECASE,
)

_DSML_BLOCK = re.compile(
    r"<\|DSML\|\s*tool_calls\s*>(?P<body>.*?)</\|DSML\|\s*tool_calls\s*>",
    re.DOTALL | re.IGNORECASE,
)
_DSML_INVOKE = re.compile(
    r"<\|DSML\|\s*invoke\s+name=\"(?P<name>[^\"]+)\"\s*>(?P<body>.*?)</\|DSML\|\s*invoke\s*>",
    re.DOTALL | re.IGNORECASE,
)
_DSML_PARAM = re.compile(
    r"<\|DSML\|\s*parameter\s+name=\"(?P<name>[^\"]+)\"[^>]*>(?P<value>.*?)</\|DSML\|\s*parameter\s*>",
    re.DOTALL | re.IGNORECASE,
)
_DSML_ANY = re.compile(
    r"<\|DSML\|\s*[^>]*>.*?(?:</\|DSML\|\s*[^>]*>|$)",
    re.DOTALL | re.IGNORECASE,
)


def normalize_dsml_delimiters(text: str) -> str:
    """把全角/双竖线/夹空格的 DSML 定界符统一成 <|DSML|...>。"""
    if not text:
        return ""
    out = text.replace("\uff5c", "|")
    out = _OPEN_DELIM.sub("<|DSML|", out)
    out = _CLOSE_DELIM.sub("</|DSML|", out)
    return out


def looks_like_dsml(text: str) -> bool:
    if not text:
        return False
    n = text.replace("\uff5c", "|").upper()
    return "DSML|" in n or "<|DSML" in n or "||DSML" in n


def strip_tool_call_markup(text: str) -> str:
    """去掉正文中的工具调用标记，仅保留自然语言。"""
    if not text:
        return ""
    out = normalize_dsml_delimiters(text)
    out = _DSML_BLOCK.sub("", out)
    out = _DSML_ANY.sub("", out)
    out = re.sub(r"<\|DSML\|[^>]*>", "", out, flags=re.IGNORECASE)
    out = re.sub(r"</\|DSML\|[^>]*>", "", out, flags=re.IGNORECASE)
    out = re.sub(
        rf"<[{re.escape(_PIPE_CHARS)}]+\s*DSML\s*[{re.escape(_PIPE_CHARS)}]+[^>]*>",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        rf"</[{re.escape(_PIPE_CHARS)}]+\s*DSML\s*[{re.escape(_PIPE_CHARS)}]+[^>]*>",
        "",
        out,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def _parse_invoke_args(body: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for pm in _DSML_PARAM.finditer(body or ""):
        pname = (pm.group("name") or "").strip()
        pval = (pm.group("value") or "").strip()
        if not pname:
            continue
        try:
            params[pname] = json.loads(pval)
        except json.JSONDecodeError:
            params[pname] = pval
    return params


def parse_tool_calls_from_content(content: str) -> tuple[str, list[dict[str, Any]]]:
    """若 content 内嵌 DSML，解析为 LangChain 风格 tool_calls，并清洗正文。"""
    raw = normalize_dsml_delimiters(content or "")
    if not raw.strip():
        return "", []

    tool_calls: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for inv in _DSML_INVOKE.finditer(raw):
        name = (inv.group("name") or "").strip()
        if not name:
            continue
        args = _parse_invoke_args(inv.group("body") or "")
        fingerprint = (name, json.dumps(args, ensure_ascii=False, sort_keys=True))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        tool_calls.append(
            {
                "id": f"dsml_{secrets.token_hex(8)}",
                "name": name,
                "args": args,
            }
        )

    cleaned = strip_tool_call_markup(raw)
    return cleaned, tool_calls
