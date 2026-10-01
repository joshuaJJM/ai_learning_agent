"""错题库。

错题不是"收藏夹"——它是 Evidence 的可视化出口：
学生能点进去看到"为什么系统认为我这个知识点是 43%"。
所以错题条目里保留了原题、学生答案、正确答案、诊断与来源。
"""

from __future__ import annotations

from typing import Any

from .. import db, knowledge, repositories


def summary(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "wrong_question_id": doc["wrong_question_id"],
        "question_id": doc["question_id"],
        "question_number": doc.get("question_number", ""),
        "question_content": doc.get("question_content", ""),
        "knowledge_point_id": doc.get("knowledge_point_id"),
        "knowledge_point_name": doc.get("knowledge_point_name"),
        "error_type": doc.get("error_type"),
        "error_label": doc.get("error_label"),
        "status": doc.get("status", "open"),
        "created_at": doc["created_at"],
    }


def detail(doc: dict[str, Any]) -> dict[str, Any]:
    payload = summary(doc)
    payload.update(
        {
            "question_type": doc.get("question_type", "single_choice"),
            "choices": doc.get("choices", {}),
            "student_answer": doc.get("student_answer"),
            "correct_answer": doc.get("correct_answer"),
            "explanation": doc.get("explanation"),
            "correctness": doc.get("correctness", "wrong"),
            "diagnosis": doc.get("diagnosis", ""),
            "image_url": doc.get("image_url"),
            "source_type": doc.get("source_type"),
            "source_id": doc.get("source_id"),
            "source_name": doc.get("source_name"),
            "favorite": bool(doc.get("favorite", False)),
            "updated_at": doc.get("updated_at", doc["created_at"]),
            "can_start_tutor": True,
        }
    )
    return payload


def list_for_user(
    user_id: str,
    *,
    knowledge_point_id: str | None = None,
    book_id: str | None = None,
    status: str | None = None,
    since: Any = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    docs = repositories.list_wrong_questions(
        user_id,
        knowledge_point_id=knowledge_point_id,
        book_id=book_id,
        status=status,
        since=since,
        limit=limit,
    )
    return [summary(d) for d in docs]


def get(user_id: str, wrong_question_id: str) -> dict[str, Any] | None:
    doc = repositories.get_wrong_question(wrong_question_id)
    if doc is None or doc.get("user_id") != user_id:
        return None
    return detail(doc)


def patch(
    user_id: str,
    wrong_question_id: str,
    *,
    status: str | None = None,
    favorite: bool | None = None,
) -> dict[str, Any] | None:
    doc = repositories.get_wrong_question(wrong_question_id)
    if doc is None or doc.get("user_id") != user_id:
        return None
    if status is not None:
        doc["status"] = status
    if favorite is not None:
        doc["favorite"] = favorite
    doc["updated_at"] = db.to_iso(db.utcnow())
    repositories.save_wrong_question(doc)
    return detail(doc)
