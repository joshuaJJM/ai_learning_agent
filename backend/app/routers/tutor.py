"""AI Tutor 接口。

刻意不做成 `POST /chat`——Tutor 是有状态的 Session（契约 §九）。
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from fastapi import APIRouter, Depends, status

from .. import repositories
from ..dependencies import current_user
from ..errors import (
    QUESTION_NOT_RECOGNIZED,
    SESSION_COMPLETED,
    SESSION_NOT_FOUND,
    WRONG_QUESTION_NOT_FOUND,
    ApiError,
)
from ..schemas import (
    TutorAnswerRequest,
    TutorSessionCreateRequest,
    TutorSessionResponse,
    TutorTurnResponse,
)
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
) -> TutorSessionResponse:
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
        raise ApiError(WRONG_QUESTION_NOT_FOUND, "错题不存在") from exc
    except ValueError as exc:
        raise ApiError(
            QUESTION_NOT_RECOGNIZED, "没能识别出这道题，换一张更清晰的照片试试"
        ) from exc

    return TutorSessionResponse(**tutor_service.session_response(session))


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


@router.post(
    "/sessions/{session_id}/turns",
    response_model=TutorTurnResponse,
    summary="提交作答，Agent 决定下一步",
)
async def submit_turn(
    session_id: str,
    payload: TutorAnswerRequest,
    user: dict[str, Any] = Depends(current_user),
) -> TutorTurnResponse:
    try:
        result = tutor_service.submit_answer(
            user["user_id"],
            session_id,
            selected_key=payload.selected_key,
            text=payload.text,
            self_reported_confidence=payload.self_reported_confidence,
        )
    except LookupError as exc:
        raise ApiError(SESSION_NOT_FOUND, "Tutor Session 不存在") from exc
    except RuntimeError as exc:
        raise ApiError(SESSION_COMPLETED, "这个 Session 已经完成了") from exc

    session = result["session"]
    return TutorTurnResponse(
        tutor_session_id=session_id,
        evaluation=result["evaluation"],
        turn=result["turn"],
        phase=session["phase"],
        completed=session["completed"],
        progress=result["turn"]["progress"],
        student_understanding=session["student_understanding"],
        knowledge_changes=result["knowledge_changes"],
        next_action=session.get("next_action"),
    )
