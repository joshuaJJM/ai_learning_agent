"""标签系统。

标签用于练习推荐：每个标签有一个分数，答对某道题则它的所有标签 +1、答错 -1。
推荐时把所有标签按分数升序排列，返回包含分数最低那个标签的题目。

客户端**不需要自己实现任何推荐逻辑**，直接调 `/tags/recommend` 即可。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..dependencies import current_user
from ..schemas import (
    TagRecommendation,
    TagRecommendResponse,
    TagScore,
    TagScoresResponse,
)
from ..services import practice_service, tag_service

router = APIRouter(prefix="/api/v1/tags", tags=["tags"])


@router.get("", response_model=TagScoresResponse, summary="全部标签的分数（升序）")
async def list_tag_scores(
    user: dict[str, Any] = Depends(current_user),
) -> TagScoresResponse:
    user_id = user["user_id"]
    # 首次访问时把全部标签以 0 分建档
    tag_service.initialize_scores(user_id)
    ordered = tag_service.ranked_tags(user_id)
    return TagScoresResponse(
        user_id=user_id,
        tag_count=len(ordered),
        weakest=TagScore(**ordered[0]) if ordered else None,
        strongest=TagScore(**ordered[-1]) if ordered else None,
        tags=[TagScore(**item) for item in ordered],
    )


@router.get(
    "/recommend",
    response_model=TagRecommendResponse,
    summary="按标签推荐题目：取分数最低的标签，返回包含它的题",
)
async def recommend_by_tag(
    count: int = Query(default=5, ge=1, le=20),
    user: dict[str, Any] = Depends(current_user),
) -> TagRecommendResponse:
    user_id = user["user_id"]
    tag_service.initialize_scores(user_id)
    picks = tag_service.pick_questions(user_id, limit=count)

    recommendations: list[TagRecommendation] = []
    for pick in picks:
        # current_question 接受一个最小会话结构，返回不含答案的题目载荷
        question_payload = practice_service.current_question(
            {"question_ids": [pick["question_id"]], "served_index": 0}
        )
        recommendations.append(
            TagRecommendation(
                tag=pick["tag"],
                tag_score=pick["tag_score"],
                question_id=pick["question_id"],
                question_tags=pick["question_tags"],
                question=question_payload,
            )
        )

    ordered = tag_service.ranked_tags(user_id)
    return TagRecommendResponse(
        user_id=user_id,
        weakest=TagScore(**ordered[0]) if ordered else None,
        recommendations=recommendations,
    )
