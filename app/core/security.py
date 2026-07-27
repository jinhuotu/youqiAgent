"""安全工具模块：加密、脱敏。

敏感信息（API Key、密码）在数据库中加密存储，在日志中自动脱敏，
禁止在任何响应或日志中明文输出。
"""

import re
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


# 常见敏感字段匹配模式（用于日志脱敏）
_SENSITIVE_PATTERNS = [
    # API Key / Token 类
    re.compile(
        r'(?i)(api[_-]?key|access[_-]?token|secret[_-]?key|password|authorization)'
        r'["\s:=]+["\']?([^\s"\']{8,})',
    ),
    # Bearer Token
    re.compile(r'(?i)(Bearer\s+)([A-Za-z0-9\-._~+/]+=*)'),
    # sk- 开头的常见 API Key
    re.compile(r'(sk-[A-Za-z0-9]{10,})'),
]


def _get_fernet() -> Optional[Fernet]:
    """获取 Fernet 加密实例；密钥未配置时返回 None。"""
    key = get_settings().encryption_key
    if not key or key.startswith("your_"):
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def encrypt_text(plain: str) -> str:
    """加密明文文本。

    Args:
        plain: 明文

    Returns:
        加密后的字符串；若加密密钥未配置则原样返回（开发兜底）
    """
    if not plain:
        return plain
    fernet = _get_fernet()
    if fernet is None:
        return plain
    return fernet.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_text(cipher: str) -> str:
    """解密密文。

    Args:
        cipher: 密文

    Returns:
        解密后的明文；解密失败时原样返回（兼容历史明文数据）
    """
    if not cipher:
        return cipher
    fernet = _get_fernet()
    if fernet is None:
        return cipher
    try:
        return fernet.decrypt(cipher.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        # 兼容未加密的历史数据
        return cipher


def mask_api_key(api_key: Optional[str], visible: int = 4) -> str:
    """脱敏 API Key，仅保留前后少量字符。

    Args:
        api_key: 原始 API Key
        visible: 首尾各保留的可见字符数

    Returns:
        脱敏后的字符串，如 sk-****xxxx
    """
    if not api_key:
        return ""
    if len(api_key) <= visible * 2:
        return "*" * len(api_key)
    return f"{api_key[:visible]}{'*' * 8}{api_key[-visible:]}"


def mask_sensitive_text(text: str) -> str:
    """对任意文本做敏感信息自动脱敏。

    Args:
        text: 原始日志/文本内容

    Returns:
        脱敏后的文本
    """
    if not text:
        return text
    result = text
    for pattern in _SENSITIVE_PATTERNS:
        result = pattern.sub(
            lambda m: (
                f"{m.group(1)}***MASKED***"
                if m.lastindex and m.lastindex >= 2
                else "***MASKED***"
            ),
            result,
        )
    return result


@lru_cache(maxsize=1)
def generate_encryption_key() -> str:
    """生成新的 Fernet 加密密钥（工具方法，供运维初始化使用）。"""
    return Fernet.generate_key().decode("utf-8")
