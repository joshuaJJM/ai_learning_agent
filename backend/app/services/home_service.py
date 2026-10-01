"""首页聚合。

契约 §2 特别强调：**不要让首页同时请求五六个 API**。
服务器一次把首页需要的东西全给出去——
薄弱点、下一步建议、知识概览、最近错题、最近学习记录。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import db, repositories
from . import (
    knowledge_service,
    recommendation_service,
    wrong_question_service,
)


def _greeting(display_name: str | None) -> str:
    hour = datetime.now(timezone.utc).astimezone().hour
    if hour < 6:
        part = "夜深了"
    elif hour < 11:
        part = "早上好"
    elif hour < 14:
        part = "中午好"
    elif hour < 18:
        part = "下午好"
    else:
        part = "晚上好"
    name = display_name or "同学"
    return f"{part}，{name}"


def _summary_node(node: Any, weak_ids: set[str]) -> dict[str, Any]:
    return {
        "knowledge_point_id": node.knowledge_point_id,
        "name": node.name,
        "mastery": node.mastery,
        "confidence": node.confidence,
        "evidence_count": node.evidence_count,
        "trend": node.trend,
        "is_weak": node.knowledge_point_id in weak_ids or node.mastery < 0.60,
    }


def build_home(user: dict[str, Any]) -> dict[str, Any]:
    user_id = user["user_id"]
    tree = knowledge_service.build_tree(user_id)
    weakest = knowledge_service.weakest_points(user_id, limit=5)
    weak_ids = {w.knowledge_point_id for w in weakest if w.mastery < 0.65}

    next_action = recommendation_service.next_action(user_id)

    wrong_count = repositories.count_wrong_questions(user_id, status="open")
    recent_wrong = wrong_question_service.list_for_user(user_id, status="open", limit=3)

    activities: list[dict[str, Any]] = []
    for item in repositories.recent_activities(user_id, limit=8):
        occurred = item.get("occurred_at")
        if not occurred:
            continue
        activities.append(
            {
                "activity_type": item["activity_type"],
                "title": item["title"],
                "subtitle": item.get("subtitle", ""),
                "reference_id": item.get("reference_id"),
                "occurred_at": occurred,
            }
        )

    weakest_node = None
    if weakest:
        top = weakest[0]
        weakest_node = {
            "knowledge_point_id": top.knowledge_point_id,
            "name": top.name,
            "mastery": top.mastery,
            "confidence": top.confidence,
            "evidence_count": knowledge_service.mastery_of(
                user_id, top.knowledge_point_id
            ).evidence_count,
            "trend": knowledge_service.mastery_of(
                user_id, top.knowledge_point_id
            ).trend,
            "is_weak": top.mastery < 0.65,
        }

    stats = {
        "total_evidence": repositories.evidence_count(user_id),
        "homework_count": repositories.count_homeworks(user_id),
        "wrong_question_open": wrong_count,
        "tutor_session_count": repositories.count_tutor_sessions(user_id),
        "practice_attempt_count": repositories.count_practice_attempts(user_id),
        "streak_days": repositories.streak_days(user_id),
    }

    return {
        "user_id": user_id,
        "greeting": _greeting(user.get("display_name")),
        "next_action": next_action.model_dump(mode="json"),
        "knowledge_summary": [_summary_node(node, weak_ids) for node in tree],
        "weakest": weakest_node,
        "wrong_question_count": wrong_count,
        "recent_wrong_questions": recent_wrong,
        "recent_activities": activities,
        "stats": stats,
        "updated_at": db.utcnow(),
    }
