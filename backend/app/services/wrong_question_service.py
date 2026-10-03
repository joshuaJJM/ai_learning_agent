"""错题库。

错题不是"收藏夹"——它是 Evidence 的可视化出口：
学生能点进去看到"为什么系统认为我这个知识点是 43%"。
所以错题条目里保留了原题、学生答案、正确答案、诊断与来源。

**数据模型（前端 Phase 6 反馈后明确下来的）**

    canonical question（题干指纹）
        └── attempts / evidence      ← 每次作答的完整历史，**永不删除**
                └── current wrong-question projection   ← 本模块

一行错题 = **一道当前需要复习的规范题目**，不是"某次作业里的某道题"。

同一道题在不同作业里做错多次，只会有一条错题项：
第一次创建（`wrong_question_id` 就此固定，之后不再变），
后续每次做错合并进去 —— `attempt_count` 累加、`attempts` 追加明细、
快照刷新成最近一次的内容。**前端拿到的 id 始终稳定**。

历史不会被丢：每次作答的原始记录在 `questions` 表，
知识点层面的证据在 `evidence` 表（带 `question_stem_hash`），
两者都不受合并影响。
"""

from __future__ import annotations

from typing import Any

from .. import db, knowledge, repositories

#: 错题项里最多保留多少条 attempt 明细（更早的仍可在 Evidence 里查到）
MAX_KEPT_ATTEMPTS = 20


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
        # ★ 规范题目身份：同一道题的多次做错共享同一个值。
        # 客户端**不需要**用它去重（列表已经是去重后的），
        # 但可以用它做本地缓存键或跨设备对齐。
        "question_stem_hash": doc.get("question_stem_hash"),
        # ★ 这道题累计做错几次。UI 可以显示「做错 3 次」。
        "attempt_count": int(doc.get("attempt_count") or 1),
        "first_wrong_at": doc.get("first_wrong_at") or doc["created_at"],
        "last_wrong_at": doc.get("last_wrong_at") or doc.get("updated_at"),
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
            # ★ 逐次作答明细（最早的在前）。展示「这道题我错过哪几次」用。
            "attempts": list(doc.get("attempts") or []),
        }
    )
    return payload


def record_attempt(
    user_id: str,
    *,
    question_stem_hash: str,
    snapshot: dict[str, Any],
    attempt: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    """记录一次「做错」，返回该规范题目的当前错题项。

    - 这道题**第一次**做错 → 新建一条（`wrong_question_id` 就此固定）
    - **再次**做错 → 合并进已有那条，不新建

    `snapshot` 是最近一次做错的题目快照（题干、选项、答案、诊断…），
    `attempt` 是这次的作答明细（question_id / homework_id / 选了什么）。

    **不删除任何历史**：`questions` 与 `evidence` 都不受影响。
    """
    existing = repositories.find_wrong_question_by_stem(user_id, question_stem_hash)

    # 题干指纹不含选项，所以「同题干、不同选项」会撞到一起 ——
    # 那是两道不同的题，合并会把其中一道的快照覆盖掉。
    # 用选项指纹消歧（与题库侧的 disambiguate 同一套规则）。
    key = question_stem_hash
    if existing is not None:
        from ..question_bank import choices_fingerprint

        if choices_fingerprint(existing.get("choices")) != choices_fingerprint(
            snapshot.get("choices")
        ):
            key = f"{question_stem_hash}-{choices_fingerprint(snapshot.get('choices'))}"
            existing = repositories.find_wrong_question_by_stem(user_id, key)

    if existing is None:
        doc = {
            "wrong_question_id": db.new_id("wq"),
            **snapshot,
            "user_id": user_id,
            "question_stem_hash": key,
            "status": "open",
            "favorite": False,
            "attempt_count": 1,
            "first_wrong_at": now,
            "last_wrong_at": now,
            "attempts": [attempt],
            "created_at": now,
            "updated_at": now,
        }
        repositories.save_wrong_question(doc)
        return doc

    # 合并：刷新快照 + 累加作答历史
    attempts = list(existing.get("attempts") or [])
    if not attempts:
        # 兼容老数据（加 attempts 字段之前创建的）
        attempts.append(
            {
                "question_id": existing.get("question_id"),
                "homework_id": existing.get("source_id"),
                "student_answer": existing.get("student_answer"),
                "correctness": existing.get("correctness"),
                "created_at": existing.get("created_at"),
            }
        )
    # ⚠️ 计数必须**累加**，不能在截断后的列表上重算 ——
    # 明细有上限（MAX_KEPT_ATTEMPTS），一旦超出，`len(attempts)` 就永远
    # 停在 20，越做错次数反而越小。
    prior_count = int(existing.get("attempt_count") or 0) or len(attempts)
    attempts.append(attempt)

    existing.update(snapshot)
    # 用消歧后的 key，不是原始指纹 —— 否则"同题干不同选项"的消歧
    # 会在合并这一步被撤销，两道题又撞回同一行。
    existing["question_stem_hash"] = key
    existing["attempts"] = [a for a in attempts if a][-MAX_KEPT_ATTEMPTS:]
    existing["attempt_count"] = prior_count + 1
    existing["last_wrong_at"] = now
    existing["updated_at"] = now
    # 又做错了 → 这条重新变成"待复习"。已经标记 resolved/archived 的也拉回来，
    # 否则学生会看到一道"已解决"的题其实是错的。
    existing["status"] = "open"
    repositories.save_wrong_question(existing)
    return existing


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
