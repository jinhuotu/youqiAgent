"""LLM / Embedding 共用的 httpx 客户端。

默认不读取 HTTP(S)_PROXY，避免 Windows 上 Clash/VPN 注入失效代理后
出现 openai.APIConnectionError（堆栈落在 httpcore http_proxy.py）。
需要走代理时把 LLM_HTTP_TRUST_ENV=true。
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.core.logger import get_logger

log = get_logger("services.llm.http")


def llm_httpx_trust_env() -> bool:
    return get_settings().llm_http_trust_env


def build_sync_http_client(*, connect: float = 8.0, read: float = 90.0) -> httpx.Client:
    trust = llm_httpx_trust_env()
    if not trust:
        log.info("LLM HTTP 直连，忽略系统代理")
    return httpx.Client(
        trust_env=trust,
        timeout=httpx.Timeout(read, connect=connect, write=30.0, pool=connect),
    )


def build_async_http_client(*, connect: float = 8.0, read: float = 90.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        trust_env=llm_httpx_trust_env(),
        timeout=httpx.Timeout(read, connect=connect, write=30.0, pool=connect),
    )
