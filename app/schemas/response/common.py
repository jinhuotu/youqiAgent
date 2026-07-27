"""统一 API 响应模型。"""

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """标准成功/失败响应信封。

    Attributes:
        code: 业务码，0 表示成功
        message: 提示信息
        data: 业务数据载荷
    """

    code: int = Field(default=0, description="业务码，0=成功")
    message: str = Field(default="success", description="提示信息")
    data: Optional[T] = Field(default=None, description="业务数据")

    @classmethod
    def ok(cls, data: Optional[T] = None, message: str = "success") -> "ApiResponse[T]":
        """构造成功响应。"""
        return cls(code=0, message=message, data=data)

    @classmethod
    def fail(cls, code: int, message: str, data: Optional[T] = None) -> "ApiResponse[T]":
        """构造失败响应。"""
        return cls(code=code, message=message, data=data)


class PageResult(BaseModel, Generic[T]):
    """分页结果。"""

    items: list[T] = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, description="总条数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页条数")
