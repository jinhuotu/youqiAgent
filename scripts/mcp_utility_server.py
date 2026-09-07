"""通用工具 MCP（stdio）：中国标准时间。

在运维台「MCP 管理」以 stdio 注册后，对话即可调用。

Command: python
Args（每行一项）:
  scripts/mcp_utility_server.py

手动探测：
  poetry run python scripts/mcp_utility_server.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone, tzinfo

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("youqi-utility")


def _cn_tz() -> tzinfo:
    """Asia/Shanghai；Windows 无时区数据时回退固定 UTC+8。"""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Asia/Shanghai")
    except Exception:  # noqa: BLE001
        return timezone(timedelta(hours=8), name="UTC+8")


_TZ_CN = _cn_tz()


@mcp.tool()
def get_china_time() -> str:
    """查询当前中国标准时间（Asia/Shanghai，UTC+8）。"""
    now = datetime.now(_TZ_CN)
    weekday = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    payload = {
        "timezone": "Asia/Shanghai",
        "offset": "+08:00",
        "iso": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekday,
        "display": f"{now.strftime('%Y年%m月%d日 %H:%M:%S')}（星期{weekday}）",
    }
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")
