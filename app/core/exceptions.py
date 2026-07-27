"""全局异常定义与统一异常处理。

区分五类错误：参数错误、鉴权失败、资源不存在、业务错误、系统错误。
生产环境禁止返回堆栈信息，仅返回标准化错误提示。
"""

from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.logger import get_logger

log = get_logger("exceptions")


# ==================== 错误码定义 ====================
class ErrorCode:
    """统一业务错误码。"""

    SUCCESS = 0
    PARAM_ERROR = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    BUSINESS_ERROR = 422
    SYSTEM_ERROR = 500


# ==================== 业务异常基类 ====================
class AppException(Exception):
    """应用业务异常基类。

    Attributes:
        code: 业务错误码
        message: 错误提示信息
        detail: 可选详细信息（生产环境不对外暴露）
        http_status: HTTP 状态码
    """

    def __init__(
        self,
        message: str,
        code: int = ErrorCode.BUSINESS_ERROR,
        detail: Optional[Any] = None,
        http_status: int = 400,
    ) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        self.http_status = http_status
        super().__init__(message)


class ParamError(AppException):
    """参数校验错误。"""

    def __init__(self, message: str = "参数错误", detail: Optional[Any] = None) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.PARAM_ERROR,
            detail=detail,
            http_status=400,
        )


class UnauthorizedError(AppException):
    """鉴权失败。"""

    def __init__(self, message: str = "鉴权失败，请检查服务密钥") -> None:
        super().__init__(
            message=message,
            code=ErrorCode.UNAUTHORIZED,
            http_status=401,
        )


class ForbiddenError(AppException):
    """无权限访问。"""

    def __init__(self, message: str = "无权限访问该资源") -> None:
        super().__init__(
            message=message,
            code=ErrorCode.FORBIDDEN,
            http_status=403,
        )


class NotFoundError(AppException):
    """资源不存在。"""

    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(
            message=message,
            code=ErrorCode.NOT_FOUND,
            http_status=404,
        )


class BusinessError(AppException):
    """业务逻辑错误。"""

    def __init__(self, message: str, detail: Optional[Any] = None) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.BUSINESS_ERROR,
            detail=detail,
            http_status=422,
        )


class SystemError(AppException):
    """系统内部错误。"""

    def __init__(self, message: str = "系统内部错误", detail: Optional[Any] = None) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.SYSTEM_ERROR,
            detail=detail,
            http_status=500,
        )


def _build_error_body(
    code: int,
    message: str,
    detail: Optional[Any] = None,
) -> dict[str, Any]:
    """构建标准错误响应体。"""
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "data": None,
    }
    # 仅非生产环境返回 detail
    settings = get_settings()
    if detail is not None and not settings.is_production:
        body["detail"] = detail
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。

    Args:
        app: FastAPI 应用实例
    """

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        """处理业务自定义异常。"""
        log.warning(
            f"业务异常: code={exc.code}, msg={exc.message}, path={request.url.path}"
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=_build_error_body(exc.code, exc.message, exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """处理 Pydantic 参数校验异常。"""
        log.warning(f"参数校验失败: path={request.url.path}, errors={exc.errors()}")
        return JSONResponse(
            status_code=400,
            content=_build_error_body(
                ErrorCode.PARAM_ERROR,
                "请求参数校验失败",
                detail=exc.errors(),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """处理 HTTP 异常。"""
        code = exc.status_code
        message = str(exc.detail) if exc.detail else "请求错误"
        if code == 401:
            err_code = ErrorCode.UNAUTHORIZED
        elif code == 403:
            err_code = ErrorCode.FORBIDDEN
        elif code == 404:
            err_code = ErrorCode.NOT_FOUND
        else:
            err_code = code
        return JSONResponse(
            status_code=code,
            content=_build_error_body(err_code, message),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """兜底处理未捕获异常。"""
        log.exception(f"未捕获系统异常: path={request.url.path}, error={exc}")
        settings = get_settings()
        detail = str(exc) if not settings.is_production else None
        return JSONResponse(
            status_code=500,
            content=_build_error_body(
                ErrorCode.SYSTEM_ERROR,
                "系统内部错误，请稍后重试",
                detail=detail,
            ),
        )
