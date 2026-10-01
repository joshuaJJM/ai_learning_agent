"""错题库接口。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from .. import knowledge
from ..dependencies import current_user
from ..errors import WRONG_QUESTION_NOT_FOUND, ApiError
from ..schemas import (
    WrongQuestionDetail,
    WrongQuestionListResponse,
    WrongQuestionPatchRequest,
)
from ..services import wrong_question_service

router = APIRouter(prefix="/api/v1/wrong-questions", tags=["wrong-questions"])


@router.get("", response_model=WrongQuestionListResponse)
async def list_wrong_questions(
    knowledge_point_id: str | None = Query(default=None),
    book_id: str | None = Query(default=None),
    status: str | None = Query(default=None, description="open | resolved | archived"),
    date_from: datetime | None = Query(default=None, description="只看这个时间之后的错题"),
    limit: int = Query(default=100, ge=1, le=500),
    user: dict[str, Any] = Depends(current_user),
) -> WrongQuestionListResponse:
    if knowledge_point_id and not knowledge.is_known(knowledge_point_id):
        raise ApiError(
            "KNOWLEDGE_POINT_NOT_FOUND", f"未知知识点: {knowledge_point_id}"
        )
    items = wrong_question_service.list_for_user(
        user["user_id"],
        knowledge_point_id=knowledge_point_id,
        book_id=book_id,
        status=status,
        since=date_from,
        limit=limit,
    )
    return WrongQuestionListResponse(
        user_id=user["user_id"], total=len(items), items=items
    )


@router.get("/{wrong_question_id}", response_model=WrongQuestionDetail)
async def get_wrong_question(
    wrong_question_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> WrongQuestionDetail:
    payload = wrong_question_service.get(user["user_id"], wrong_question_id)
    if payload is None:
        raise ApiError(WRONG_QUESTION_NOT_FOUND, "错题不存在")
    return WrongQuestionDetail(**payload)


@router.patch("/{wrong_question_id}", response_model=WrongQuestionDetail)
async def patch_wrong_question(
    wrong_question_id: str,
    payload: WrongQuestionPatchRequest,
    user: dict[str, Any] = Depends(current_user),
) -> WrongQuestionDetail:
    updated = wrong_question_service.patch(
        user["user_id"],
        wrong_question_id,
        status=payload.status,
        favorite=payload.favorite,
    )
    if updated is None:
        raise ApiError(WRONG_QUESTION_NOT_FOUND, "错题不存在")
    return WrongQuestionDetail(**updated)
