"""请求上下文模块。

使用 contextvars 在异步请求链路中透传 user_id / role 等上下文，
实现全链路数据隔离与日志关联，无需显式传参。
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RequestContext:
    """单次请求的上下文信息。"""

    user_id: str = ""
    role: str = "user"
    request_id: str = ""
    # 扩展字段预留
    extra: dict = field(default_factory=dict)

    @property
    def is_admin(self) -> bool:
        """判断当前用户是否为管理员角色。"""
        return self.role.lower() == "admin"


# 进程内请求上下文变量（协程安全）
_request_context: ContextVar[Optional[RequestContext]] = ContextVar(
    "request_context", default=None
)


def set_request_context(ctx: RequestContext) -> None:
    """设置当前请求上下文。

    Args:
        ctx: 请求上下文对象
    """
    _request_context.set(ctx)


def get_request_context() -> Optional[RequestContext]:
    """获取当前请求上下文，未设置时返回 None。"""
    return _request_context.get()


def get_current_user_id() -> str:
    """获取当前请求的 user_id，未设置时返回空字符串。"""
    ctx = get_request_context()
    return ctx.user_id if ctx else ""


def get_current_role() -> str:
    """获取当前请求的角色，默认 user。"""
    ctx = get_request_context()
    return ctx.role if ctx else "user"


def clear_request_context() -> None:
    """清除当前请求上下文。"""
    _request_context.set(None)
