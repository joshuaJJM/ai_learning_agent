"""Knowledge State 接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import db, knowledge, repositories
from ..dependencies import current_user
from ..errors import KNOWLEDGE_POINT_NOT_FOUND, ApiError
from ..schemas import (
    KnowledgeDetailResponse,
    KnowledgeResponse,
    NextAction,
)
from ..services import knowledge_service, recommendation_service

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.get("", response_model=KnowledgeResponse)
async def get_knowledge(user: dict[str, Any] = Depends(current_user)) -> KnowledgeResponse:
    user_id = user["user_id"]
    weakest = knowledge_service.weakest_points(user_id, limit=5)
    return KnowledgeResponse(
        user_id=user_id,
        subject="mathematics",
        updated_at=db.utcnow(),
        tree=knowledge_service.build_tree(user_id),
        weakest=weakest,
        next_action=recommendation_service.next_action(user_id),
        total_evidence=repositories.evidence_count(user_id),
    )


@router.get("/{knowledge_point_id}", response_model=KnowledgeDetailResponse)
async def get_knowledge_point(
    knowledge_point_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> KnowledgeDetailResponse:
    if not knowledge.is_known(knowledge_point_id):
        raise ApiError(
            KNOWLEDGE_POINT_NOT_FOUND, f"未知知识点: {knowledge_point_id}"
        )
    payload = knowledge_service.knowledge_detail(user["user_id"], knowledge_point_id)
    payload["recommended_action"] = recommendation_service.next_action(
        user["user_id"], preferred_kp_id=knowledge_point_id
    )
    return KnowledgeDetailResponse(**payload)
