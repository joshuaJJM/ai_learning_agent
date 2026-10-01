"""统一错误格式。

契约要求（§二十三）：所有接口返回统一的
    { "error_code": ..., "message": ..., "request_id": ... }

iOS 只根据 error_code 做逻辑分支，绝不解析中文文案。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# 错误码常量：客户端可依赖，改名等于破坏契约。
INVALID_IMAGE = "INVALID_IMAGE"
VLM_TIMEOUT = "VLM_TIMEOUT"
QUESTION_NOT_RECOGNIZED = "QUESTION_NOT_RECOGNIZED"
SESSION_EXPIRED = "SESSION_EXPIRED"
SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
ANALYSIS_NOT_FOUND = "ANALYSIS_NOT_FOUND"
KNOWLEDGE_POINT_NOT_FOUND = "KNOWLEDGE_POINT_NOT_FOUND"
WRONG_QUESTION_NOT_FOUND = "WRONG_QUESTION_NOT_FOUND"
BOOK_NOT_FOUND = "BOOK_NOT_FOUND"
BOOK_NOT_OWNED = "BOOK_NOT_OWNED"
INVALID_SERIAL_NUMBER = "INVALID_SERIAL_NUMBER"
UNAUTHORIZED = "UNAUTHORIZED"
NOT_FOUND = "NOT_FOUND"
VALIDATION_ERROR = "VALIDATION_ERROR"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
NO_QUESTIONS_AVAILABLE = "NO_QUESTIONS_AVAILABLE"
SESSION_COMPLETED = "SESSION_COMPLETED"
RATE_LIMITED = "RATE_LIMITED"
INTERNAL_ERROR = "INTERNAL_ERROR"
SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"

# 默认 HTTP 状态码
_STATUS_FOR = {
    UNAUTHORIZED: status.HTTP_401_UNAUTHORIZED,
    SESSION_EXPIRED: status.HTTP_401_UNAUTHORIZED,
    NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ANALYSIS_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    SESSION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    KNOWLEDGE_POINT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    WRONG_QUESTION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    BOOK_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    BOOK_NOT_OWNED: status.HTTP_403_FORBIDDEN,
    INVALID_SERIAL_NUMBER: status.HTTP_400_BAD_REQUEST,
    INVALID_IMAGE: status.HTTP_400_BAD_REQUEST,
    QUESTION_NOT_RECOGNIZED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    VALIDATION_ERROR: status.HTTP_422_UNPROCESSABLE_ENTITY,
    IDEMPOTENCY_CONFLICT: status.HTTP_409_CONFLICT,
    NO_QUESTIONS_AVAILABLE: status.HTTP_404_NOT_FOUND,
    SESSION_COMPLETED: status.HTTP_409_CONFLICT,
    VLM_TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
    RATE_LIMITED: status.HTTP_429_TOO_MANY_REQUESTS,
    SERVICE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


class ApiError(Exception):
    """业务异常，会被 handler 渲染成统一错误体。"""

    def __init__(
        self,
        error_code: str,
        message: str,
        http_status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.http_status = http_status or _STATUS_FOR.get(
            error_code, status.HTTP_400_BAD_REQUEST
        )
        self.details = details or {}


def error_body(
    error_code: str, message: str, request_id: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "error_code": error_code,
        "message": message,
        "request_id": request_id,
    }
    if details:
        body["details"] = details
    return body


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "") or "unknown"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=error_body(
                exc.error_code, exc.message, request_id_of(request), exc.details
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_body(
                VALIDATION_ERROR,
                "请求参数不合法",
                request_id_of(request),
                {"errors": _safe_errors(exc.errors())},
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(
                INTERNAL_ERROR,
                "服务器内部错误",
                request_id_of(request),
                {"type": type(exc).__name__},
            ),
        )


def _safe_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉不能 JSON 序列化的字段（例如异常对象）。"""
    cleaned: list[dict[str, Any]] = []
    for err in errors:
        item = {k: v for k, v in err.items() if k in ("type", "loc", "msg")}
        item["loc"] = [str(x) for x in item.get("loc", [])]
        cleaned.append(item)
    return cleaned
