"""Demo 辅助接口。

现场演示前的准备工作都在这里：一键铺开历史数据、一键清空重来。
不参与真实业务流程，但能救命。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import db, repositories
from ..dependencies import current_user
from ..seed.demo import DEMO_PLAN, seed_demo
from ..services import knowledge_service

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])


@router.post("/seed", summary="写入 Demo 学习历史（把综合应用压到 43% 附近）")
async def seed(
    reset: bool = True,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return seed_demo(user["user_id"], reset=reset)


@router.post("/reset", summary="清空该用户的学习数据")
async def reset(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    from ..seed.demo import reset_user_data

    counts = reset_user_data(user["user_id"])
    return {"user_id": user["user_id"], "deleted": counts}


@router.get("/status", summary="当前 Demo 数据概览")
async def status(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    user_id = user["user_id"]
    estimates = knowledge_service.mastery_map(user_id)
    return {
        "user_id": user_id,
        "evidence_count": repositories.evidence_count(user_id),
        "wrong_question_count": repositories.count_wrong_questions(user_id),
        "tutor_session_count": repositories.count_tutor_sessions(user_id),
        "mastery": {
            kp_id: round(estimates[kp_id].mastery, 4) for kp_id in estimates
        },
        "seed_plan_points": list(DEMO_PLAN.keys()),
        "server_time": db.to_iso(db.utcnow()),
    }
