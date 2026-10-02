"""AI Tutor 接口。

刻意不做成 `POST /chat`——Tutor 是有状态的 Session（契约 §九）。

提交作答支持两种返回：

  - `stream: false`（默认）→ 普通 JSON，契约不变
  - `stream: true`          → SSE：`meta` → `delta`×N → `turn` → `done`

**服务端始终是 Tutor 状态的唯一权威**：当前阶段、下一教学策略、补救层级、
正确答案、是否结束补救、掌握度变化、会话是否完成，全部由服务端决定。
`delta` 只承载自然语言，客户端**不要**从里面解析题目或选项 ——
所有可交互数据都通过最终的结构化 `turn` 事件下发。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from .. import repositories
from ..dependencies import (
    current_user,
    idempotency_key_header,
    resolve_idempotency_key,
)
from ..errors import (
    IDEMPOTENCY_CONFLICT,
    QUESTION_NOT_RECOGNIZED,
    SESSION_COMPLETED,
    SESSION_NOT_FOUND,
    WRONG_QUESTION_NOT_FOUND,
    ApiError,
    request_id_of,
)
from ..schemas import (
    TutorAnswerRequest,
    TutorSessionCreateRequest,
    TutorSessionResponse,
    TutorTurnResponse,
)
from ..sse import SSE_HEADERS, chunk_text, sse_frame

# 流式打字机的节奏。tutor 的文案来自教学脚本（确定性文本），
# 这里按片下发只是为了前端能边收边渲染，不涉及模型调用。
STREAM_CHUNK_CHARS = 18
STREAM_CHUNK_DELAY = 0.012
from ..services import tutor_service

router = APIRouter(prefix="/api/v1/tutor", tags=["tutor"])


def _decode_base64_image(raw: str) -> tuple[bytes, str]:
    text = raw.strip()
    mime = "image/jpeg"
    if text.startswith("data:"):
        header, _, text = text.partition(",")
        if ";" in header:
            mime = header[5:].split(";")[0] or mime
    try:
        return base64.b64decode(text, validate=False), mime
    except (binascii.Error, ValueError) as exc:
        raise ApiError("INVALID_IMAGE", f"图片 base64 解析失败: {exc}") from exc


@router.post(
    "/sessions",
    response_model=TutorSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建 Tutor Session（三个入口共用）",
)
async def create_session(
    payload: TutorSessionCreateRequest,
    user: dict[str, Any] = Depends(current_user),
    header_key: str | None = Depends(idempotency_key_header),
) -> TutorSessionResponse:
    endpoint = "POST /api/v1/tutor/sessions"
    raw_key = resolve_idempotency_key(header_key, payload.client_request_id)
    idem_key = f"tutor-create:{user['user_id']}:{raw_key}" if raw_key else None

    if idem_key and not repositories.reserve_idempotency(
        idem_key, user["user_id"], endpoint
    ):
        cached = repositories.get_idempotent_response(idem_key)
        if cached:
            return TutorSessionResponse(**cached)
        raise ApiError(IDEMPOTENCY_CONFLICT, "同一个请求正在处理中，请稍后重试")

    image = None
    if payload.image_base64:
        image = _decode_base64_image(payload.image_base64)

    try:
        session = await tutor_service.create_session(
            user["user_id"],
            source_type=payload.source_type,
            knowledge_point_id=payload.knowledge_point_id,
            wrong_question_id=payload.wrong_question_id,
            question_text=payload.question_text,
            image=image,
        )
    except LookupError as exc:
        if idem_key:
            repositories.release_idempotency(idem_key)
        raise ApiError(WRONG_QUESTION_NOT_FOUND, "错题不存在") from exc
    except ValueError as exc:
        if idem_key:
            repositories.release_idempotency(idem_key)
        raise ApiError(
            QUESTION_NOT_RECOGNIZED, "没能识别出这道题，换一张更清晰的照片试试"
        ) from exc

    body = tutor_service.session_response(session)
    if idem_key:
        repositories.put_idempotent_response(idem_key, user["user_id"], endpoint, body)
    return TutorSessionResponse(**body)


@router.get(
    "/sessions/{session_id}",
    response_model=TutorSessionResponse,
    summary="读取 Session 完整状态",
)
async def get_session(
    session_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> TutorSessionResponse:
    session = repositories.get_tutor_session(session_id)
    if session is None or session.get("user_id") != user["user_id"]:
        raise ApiError(SESSION_NOT_FOUND, "Tutor Session 不存在")
    return TutorSessionResponse(**tutor_service.session_response(session))


async def _stream_turn(
    body: dict[str, Any], request_id: str
) -> AsyncIterator[str]:
    """把一轮作答渲染成 SSE。

    事件顺序固定：`meta` → `delta`×N → `turn` → `done`。

    - `delta` 只是自然语言的打字机效果，**不是权威数据**
    - `turn` 才是最终权威结构化结果，所有可交互 UI 都读它
    - 客户端应以 `turn` 为准覆盖 delta 累积出来的文本
    """
    turn = body["turn"]
    try:
        yield sse_frame(
            "meta",
            {
                "request_id": request_id,
                "tutor_session_id": body["tutor_session_id"],
                "seq": turn["seq"],
                "phase": body["phase"],
                "turn_type": turn["turn_type"],
                "remedial_depth": turn.get("remedial_depth", 0),
            },
        )
        for piece in chunk_text(turn["text"], STREAM_CHUNK_CHARS):
            if piece:
                yield sse_frame("delta", {"content": piece})
                if STREAM_CHUNK_DELAY:
                    await asyncio.sleep(STREAM_CHUNK_DELAY)
        yield sse_frame("turn", turn)
        yield sse_frame(
            "done",
            {
                "request_id": request_id,
                "seq": turn["seq"],
                "phase": body["phase"],
                "completed": body["completed"],
                "progress": body["progress"],
                "student_understanding": body["student_understanding"],
            },
        )
    except Exception as exc:  # noqa: BLE001 — 流已经开出去了，只能以事件收尾
        yield sse_frame(
            "error",
            {
                "error_code": "INTERNAL_ERROR",
                "message": "生成这一轮时出错",
                "request_id": request_id,
                "detail": type(exc).__name__,
            },
        )


def _stream_response(body: dict[str, Any], request_id: str) -> StreamingResponse:
    return StreamingResponse(
        _stream_turn(body, request_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post(
    "/sessions/{session_id}/turns",
    response_model=TutorTurnResponse,
    summary="提交作答，Agent 决定下一步",
    responses={
        200: {
            "description": (
                "默认返回 JSON。请求体带 `\"stream\": true` 时改为 "
                "`text/event-stream`：meta → delta×N → turn → done。"
            ),
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": (
                        'event: meta\n'
                        'data: {"request_id":"...","tutor_session_id":"tut_...",'
                        '"seq":3,"phase":"diagnose","turn_type":"simpler_question",'
                        '"remedial_depth":1}\n\n'
                        'event: delta\n'
                        'data: {"content":"还是不对。我们把这一步再拆细一点"}\n\n'
                        'event: turn\n'
                        'data: {"turn_id":"turn_...","seq":3,'
                        '"turn_type":"simpler_question","choices":[...],'
                        '"strategy":"simplify","remedial_depth":1,'
                        '"answer_reveal":null,...}\n\n'
                        'event: done\n'
                        'data: {"request_id":"...","seq":3,"completed":false,...}\n\n'
                    ),
                }
            },
        }
    },
)
async def submit_turn(
    session_id: str,
    payload: TutorAnswerRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    header_key: str | None = Depends(idempotency_key_header),
) -> Any:
    endpoint = f"POST /api/v1/tutor/sessions/{session_id}/turns"
    raw_key = resolve_idempotency_key(header_key, payload.client_request_id)
    idem_key = f"tutor:{user['user_id']}:{session_id}:{raw_key}" if raw_key else None
    request_id = request_id_of(request)

    # **先占位再干活**：只「先查缓存」的话，两个并发请求会同时未命中，
    # 于是各追一条 turn、各写一次 Evidence，掌握度被算两遍。
    if idem_key and not repositories.reserve_idempotency(
        idem_key, user["user_id"], endpoint
    ):
        cached = repositories.get_idempotent_response(idem_key)
        if cached:
            # 重放：校验/计算都不用再做，直接按原来的方式回放
            replayed = {**cached, "replayed": True}
            if payload.stream:
                return _stream_response(replayed, request_id)
            return TutorTurnResponse(**replayed)
        raise ApiError(
            IDEMPOTENCY_CONFLICT, "同一个请求正在处理中，请稍后重试"
        )

    # 先把所有可能失败的事做完 —— 这样 404 / 409 走正常的 HTTP 状态码，
    # 而不是在已经开流之后再塞一个 error 事件。
    try:
        result = tutor_service.submit_answer(
            user["user_id"],
            session_id,
            selected_key=payload.selected_key,
            text=payload.text,
            self_reported_confidence=payload.self_reported_confidence,
            answering_turn_id=payload.answering_turn_id,
        )
    except LookupError as exc:
        if idem_key:
            repositories.release_idempotency(idem_key)
        raise ApiError(SESSION_NOT_FOUND, "Tutor Session 不存在") from exc
    except RuntimeError as exc:
        if idem_key:
            repositories.release_idempotency(idem_key)
        raise ApiError(SESSION_COMPLETED, "这个 Session 已经完成了") from exc

    body = {**result["body"], "replayed": bool(result.get("replayed"))}
    if idem_key:
        # 缓存里不带 replayed —— 重放时由读取方标成 true
        repositories.put_idempotent_response(
            idem_key, user["user_id"], endpoint, result["body"]
        )

    if payload.stream:
        return _stream_response(body, request_id)
    return TutorTurnResponse(**body)
