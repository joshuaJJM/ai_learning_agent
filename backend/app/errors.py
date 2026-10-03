"""统一错误格式。

契约要求：所有接口返回统一的
    { "error_code": ..., "message": ..., "request_id": ... }

iOS 只根据 error_code 做逻辑分支，绝不解析中文文案。

**错误码只有一个事实来源**：下面的 `_CODES`。它同时喂给四个地方，
所以不可能出现「文档写了但代码不抛」这种漂移：

  1. 模块级常量 —— 业务代码 `from .errors import XXX` 直接用
  2. `ErrorCode` 枚举 —— 渲染进 OpenAPI schema，前端可据此生成映射表
  3. `_STATUS_FOR` —— 每个码的默认 HTTP 状态
  4. `GET /api/v1/meta/error-codes` —— 前端运行时拉取

加新错误码只改 `_CODES` 一处。

**不要往里放「以后可能会用」的码。** 前端会为文档里的每个码写一条分支，
死码等于让他们维护永远走不到的代码 —— 之前 `SESSION_EXPIRED`、
`RATE_LIMITED`、`BOOK_NOT_OWNED` 就是这么混进来的（定义了但从不抛出），
已经清掉。真要加功能时再加码。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# 唯一事实来源：错误码 -> (默认 HTTP 状态, 中文含义)
# ---------------------------------------------------------------------------

_CODES: dict[str, tuple[int, str]] = {
    # 认证
    "UNAUTHORIZED": (status.HTTP_401_UNAUTHORIZED, "未认证，或 token 无效"),
    # 找不到
    "NOT_FOUND": (status.HTTP_404_NOT_FOUND, "目标资源不存在"),
    "ANALYSIS_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "分析任务不存在"),
    "SESSION_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "Tutor / 练习 Session 不存在"),
    "KNOWLEDGE_POINT_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "知识点 id 不存在"),
    "WRONG_QUESTION_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "错题不存在"),
    "BOOK_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "图书不存在"),
    "QUESTION_NOT_FOUND": (
        status.HTTP_404_NOT_FOUND,
        "这道题不在该分析里",
    ),
    "NO_QUESTIONS_AVAILABLE": (status.HTTP_404_NOT_FOUND, "这一组题已经做完了"),
    # 请求不合法
    "INVALID_IMAGE": (status.HTTP_400_BAD_REQUEST, "图片为空 / 过大 / 不是图片"),
    "INVALID_ANSWER": (
        status.HTTP_400_BAD_REQUEST,
        "选项不是这道题的合法选项（单选题只能填 A/B/C/D 之一）",
    ),
    "INVALID_SERIAL_NUMBER": (
        status.HTTP_400_BAD_REQUEST,
        "序列号无效、格式不对，或已用于兑换其他书",
    ),
    "QUESTION_NOT_IN_SESSION": (
        status.HTTP_400_BAD_REQUEST,
        "提交的题不是当前练习的当前这一题",
    ),
    "QUESTION_NOT_RECOGNIZED": (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "没有从图片中识别出题目",
    ),
    "VALIDATION_ERROR": (status.HTTP_422_UNPROCESSABLE_ENTITY, "请求参数不合法"),
    # 状态冲突
    "SESSION_COMPLETED": (status.HTTP_409_CONFLICT, "Session 已结束，不能再作答"),
    "IDEMPOTENCY_CONFLICT": (
        status.HTTP_409_CONFLICT,
        "同一个幂等键的请求正在处理中，稍后重试",
    ),
    "QUESTION_NOT_CONFIRMABLE": (
        status.HTTP_409_CONFLICT,
        "这道题不能人工确认标准答案（学生未作答，没有可判定的作答）",
    ),
    "QUESTION_ALREADY_RESOLVED": (
        status.HTTP_409_CONFLICT,
        "这道题的标准答案已经确认过，且这次给的答案不一样；"
        "重复提交同一答案会直接回放原结果",
    ),
    # 服务端
    "VLM_TIMEOUT": (status.HTTP_504_GATEWAY_TIMEOUT, "视觉模型超时或不可用"),
    "ANALYSIS_INTERRUPTED": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "服务在分析过程中重启，任务已中断，请重新上传",
    ),
    "ANALYSIS_TIMEOUT": (
        status.HTTP_504_GATEWAY_TIMEOUT,
        "分析超过最长处理时间仍未完成，已终止，请重试",
    ),
    "SERVICE_UNAVAILABLE": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "依赖的服务暂时不可用",
    ),
    "INTERNAL_ERROR": (status.HTTP_500_INTERNAL_SERVER_ERROR, "服务端内部错误"),
}

# 从单一来源派生模块级常量，业务代码照旧 `from .errors import XXX`
for _code_name in _CODES:
    globals()[_code_name] = _code_name

#: OpenAPI 里会渲染成 enum，前端可以直接生成映射表
ErrorCode = Enum("ErrorCode", {name: name for name in _CODES}, type=str)

# 默认 HTTP 状态码
_STATUS_FOR: dict[str, int] = {
    code: http_status for code, (http_status, _) in _CODES.items()
}


def error_code_catalog() -> list[dict[str, Any]]:
    """给 `GET /api/v1/meta/error-codes` 与文档生成用的完整清单。"""
    return [
        {"error_code": code, "http_status": http_status, "description": description}
        for code, (http_status, description) in _CODES.items()
    ]


def all_error_codes() -> list[str]:
    return list(_CODES)


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
