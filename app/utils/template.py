"""提示词模板变量渲染工具。"""

import re
from typing import Any, Optional


_VAR_PATTERN = re.compile(r"\{(\w+)\}")


def render_template(content: str, variables: Optional[dict[str, Any]] = None) -> str:
    """渲染模板中的 {var} 占位符。

    Args:
        content: 模板原文
        variables: 变量字典；缺失变量保留原占位符

    Returns:
        渲染后的文本
    """
    if not variables:
        return content

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key in variables:
            return str(variables[key])
        return match.group(0)

    return _VAR_PATTERN.sub(_replace, content)
