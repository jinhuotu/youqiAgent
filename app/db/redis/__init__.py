"""Redis 客户端封装。

用于缓存公共模型配置、流式会话状态，并预留限流/分布式锁扩展。
"""

from typing import Any, Optional

import redis

from app.core.config import get_settings
from app.core.logger import get_logger

log = get_logger("db.redis")

_redis_client: Optional[redis.Redis] = None

# 缓存键前缀
CACHE_PREFIX_PUBLIC_MODELS = "ai:models:public"
CACHE_PREFIX_STREAM_STATE = "ai:stream:state:"


def get_redis() -> redis.Redis:
    """获取全局 Redis 客户端（懒加载单例）。"""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            db=settings.redis_db,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
        )
        log.info(f"Redis 客户端已创建: {settings.redis_host}:{settings.redis_port}")
    return _redis_client


def check_redis_connection() -> bool:
    """探测 Redis 连接是否正常。"""
    try:
        client = get_redis()
        return bool(client.ping())
    except Exception as e:
        log.warning(f"Redis 连接检测失败: {e}")
        return False


class RedisCache:
    """Redis 缓存操作封装。"""

    def __init__(self) -> None:
        self._client = get_redis()

    def get(self, key: str) -> Optional[str]:
        """获取字符串缓存。"""
        try:
            return self._client.get(key)
        except Exception as e:
            log.warning(f"Redis GET 失败 key={key}: {e}")
            return None

    def set(self, key: str, value: str, ttl: int = 300) -> bool:
        """设置字符串缓存。

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期秒数，默认 5 分钟
        """
        try:
            self._client.setex(key, ttl, value)
            return True
        except Exception as e:
            log.warning(f"Redis SET 失败 key={key}: {e}")
            return False

    def delete(self, key: str) -> bool:
        """删除缓存键。"""
        try:
            self._client.delete(key)
            return True
        except Exception as e:
            log.warning(f"Redis DELETE 失败 key={key}: {e}")
            return False

    def set_json(self, key: str, data: Any, ttl: int = 300) -> bool:
        """序列化 JSON 后写入缓存。"""
        import json

        try:
            return self.set(key, json.dumps(data, ensure_ascii=False), ttl=ttl)
        except Exception as e:
            log.warning(f"Redis set_json 失败 key={key}: {e}")
            return False

    def get_json(self, key: str) -> Optional[Any]:
        """读取并反序列化 JSON 缓存。"""
        import json

        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None
