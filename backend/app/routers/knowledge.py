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
    MasteryOverviewResponse,
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


@router.get(
    "/mastery-overview",
    response_model=MasteryOverviewResponse,
    summary="综合掌握度（一个两位百分比数字）",
)
async def get_mastery_overview(
    user: dict[str, Any] = Depends(current_user),
) -> MasteryOverviewResponse:
    """首页那个大数字。

    算法见 `knowledge_service.overall_mastery`：已练知识点的**置信度加权平均**
    再乘**覆盖率**。刻意偏低不偏高 —— 宁可保守，也不给学生一个虚高的数字。

    注意：必须声明在 `/{knowledge_point_id}` **之前**，
    否则 "mastery-overview" 会被当成知识点 id 匹配掉。
    """
    return MasteryOverviewResponse(**knowledge_service.overall_mastery(user["user_id"]))


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
