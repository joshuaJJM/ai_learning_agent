"""数据访问层。

Router 不直接碰 SQL；所有读写都收敛到这里。
Evidence 是唯一被 Knowledge Engine 聚合查询的表，所以它有明确列；
其他对象整存整取，走 db.py 的文档表helper。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from . import db, knowledge
from .mastery import EvidenceRecord, normalize_outcome

# ---------------------------------------------------------------------------
# 用户 / 令牌
# ---------------------------------------------------------------------------

def create_user(
    device_id: str | None = None,
    display_name: str | None = None,
    is_demo: bool = False,
) -> dict[str, Any]:
    user_id = db.new_id("user")
    doc = {
        "user_id": user_id,
        "device_id": device_id,
        "display_name": display_name or "同学",
        "is_demo": is_demo,
        "created_at": db.to_iso(db.utcnow()),
    }
    db.execute(
        "INSERT INTO users (user_id, device_id, display_name, is_demo, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [user_id, device_id, doc["display_name"], int(is_demo), doc["created_at"]],
    )
    return doc


def get_user(user_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM users WHERE user_id = ?", [user_id])
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "device_id": row["device_id"],
        "display_name": row["display_name"],
        "is_demo": bool(row["is_demo"]),
        "created_at": row["created_at"],
    }


def find_user_by_device(device_id: str) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT user_id FROM users WHERE device_id = ? ORDER BY created_at LIMIT 1",
        [device_id],
    )
    return get_user(row["user_id"]) if row else None


def issue_token(user_id: str) -> str:
    token = db.new_id("tok")
    db.execute(
        "INSERT INTO tokens (token, user_id, created_at) VALUES (?, ?, ?)",
        [token, user_id, db.to_iso(db.utcnow())],
    )
    return token


def resolve_token(token: str) -> str | None:
    row = db.query_one("SELECT user_id FROM tokens WHERE token = ?", [token])
    return row["user_id"] if row else None


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def add_evidence(
    user_id: str,
    knowledge_point_id: str,
    result: str,
    difficulty: float,
    source_type: str,
    source_id: str | None = None,
    question_id: str | None = None,
    error_type: str | None = None,
    confidence: float = 1.0,
    detail: str | None = None,
    answer_excerpt: str | None = None,
    created_at: datetime | None = None,
) -> str:
    evidence_id = db.new_id("ev")
    created = created_at or db.utcnow()
    outcome = normalize_outcome(result)
    from .mastery import OUTCOME_SCORES

    payload = {
        "answer_excerpt": answer_excerpt,
        "reason": detail,
    }
    db.execute(
        """
        INSERT INTO evidence (
            evidence_id, user_id, knowledge_point_id, source_type, source_id,
            question_id, result, score, difficulty, error_type, confidence,
            detail, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            evidence_id,
            user_id,
            knowledge_point_id,
            source_type,
            source_id,
            question_id,
            outcome,
            OUTCOME_SCORES.get(outcome, 0.5),
            difficulty,
            error_type,
            confidence,
            json.dumps(payload, ensure_ascii=False),
            db.to_iso(created),
        ],
    )
    return evidence_id


def _row_to_record(row: sqlite3.Row) -> EvidenceRecord:
    detail_raw = row["detail"]
    answer_excerpt = None
    reason = None
    if detail_raw:
        try:
            parsed = json.loads(detail_raw)
            answer_excerpt = parsed.get("answer_excerpt")
            reason = parsed.get("reason")
        except (json.JSONDecodeError, AttributeError):
            reason = detail_raw
    return EvidenceRecord(
        id=row["evidence_id"],
        user_id=row["user_id"],
        kp_id=row["knowledge_point_id"],
        outcome=row["result"],
        difficulty=row["difficulty"],
        source=row["source_type"],
        created_at=db.from_iso(row["created_at"]) or db.utcnow(),
        error_type=row["error_type"],
        question_id=row["question_id"],
        answer_excerpt=answer_excerpt,
        reason=reason,
        confidence=row["confidence"] if row["confidence"] is not None else 1.0,
    )


def evidence_records(
    user_id: str, knowledge_point_id: str | None = None
) -> list[EvidenceRecord]:
    if knowledge_point_id:
        rows = db.query_all(
            "SELECT * FROM evidence WHERE user_id = ? AND knowledge_point_id = ? "
            "ORDER BY created_at",
            [user_id, knowledge_point_id],
        )
    else:
        rows = db.query_all(
            "SELECT * FROM evidence WHERE user_id = ? ORDER BY created_at", [user_id]
        )
    return [_row_to_record(r) for r in rows]


def evidence_rows(
    user_id: str, knowledge_point_id: str | None = None, limit: int | None = None
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM evidence WHERE user_id = ?"
    params: list[Any] = [user_id]
    if knowledge_point_id:
        sql += " AND knowledge_point_id = ?"
        params.append(knowledge_point_id)
    sql += " ORDER BY created_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db.query_all(sql, params)


def evidence_count(user_id: str) -> int:
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM evidence WHERE user_id = ?", [user_id]
    )
    return int(row["n"]) if row else 0


def distinct_knowledge_points(user_id: str) -> list[str]:
    rows = db.query_all(
        "SELECT DISTINCT knowledge_point_id FROM evidence WHERE user_id = ?",
        [user_id],
    )
    return [r["knowledge_point_id"] for r in rows]


def question_history(user_id: str) -> dict[str, dict[str, Any]]:
    """题目维度的作答历史，供推荐算法避免重复出题、安排错题重做。

    返回 {question_id: {attempts, wrong_count, last_result, last_at}}
    """
    rows = db.query_all(
        "SELECT question_id, result, created_at FROM evidence "
        "WHERE user_id = ? AND question_id IS NOT NULL ORDER BY created_at",
        [user_id],
    )
    history: dict[str, dict[str, Any]] = {}
    for row in rows:
        question_id = row["question_id"]
        entry = history.setdefault(
            question_id,
            {"attempts": 0, "wrong_count": 0, "last_result": None, "last_at": None},
        )
        entry["attempts"] += 1
        entry["last_result"] = row["result"]
        entry["last_at"] = row["created_at"]
        if normalize_outcome(row["result"]) == "incorrect":
            entry["wrong_count"] += 1
    return history


# ---------------------------------------------------------------------------
# Homework / Question / Analysis
# ---------------------------------------------------------------------------

def save_homework(doc: dict[str, Any]) -> None:
    db.upsert_doc(
        "homeworks",
        "homework_id",
        doc["homework_id"],
        doc,
        user_id=doc["user_id"],
        analysis_id=doc.get("analysis_id"),
        created_at=doc["created_at"],
    )


def get_homework(homework_id: str) -> dict[str, Any] | None:
    return db.get_doc("homeworks", "homework_id", homework_id)


def list_homeworks(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return db.list_docs(
        "homeworks",
        "user_id = ?",
        [user_id],
        order_by="created_at DESC",
        limit=limit,
    )


def count_homeworks(user_id: str) -> int:
    return db.count_docs("homeworks", "user_id = ?", [user_id])


def save_question(doc: dict[str, Any]) -> None:
    db.upsert_doc(
        "questions",
        "question_id",
        doc["question_id"],
        doc,
        user_id=doc["user_id"],
        homework_id=doc.get("homework_id"),
        correctness=doc.get("correctness"),
        created_at=doc["created_at"],
    )


def get_question(question_id: str) -> dict[str, Any] | None:
    return db.get_doc("questions", "question_id", question_id)


def list_questions_by_homework(homework_id: str) -> list[dict[str, Any]]:
    return db.list_docs(
        "questions",
        "homework_id = ?",
        [homework_id],
        order_by="created_at",
    )


def save_analysis(doc: dict[str, Any]) -> None:
    db.upsert_doc(
        "analyses",
        "analysis_id",
        doc["analysis_id"],
        doc,
        user_id=doc["user_id"],
        status=doc["status"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def get_analysis(analysis_id: str) -> dict[str, Any] | None:
    return db.get_doc("analyses", "analysis_id", analysis_id)


def list_analyses(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return db.list_docs(
        "analyses",
        "user_id = ?",
        [user_id],
        order_by="created_at DESC",
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Wrong questions
# ---------------------------------------------------------------------------

def save_wrong_question(doc: dict[str, Any]) -> None:
    db.upsert_doc(
        "wrong_questions",
        "wrong_question_id",
        doc["wrong_question_id"],
        doc,
        user_id=doc["user_id"],
        knowledge_point_id=doc.get("knowledge_point_id"),
        status=doc.get("status", "open"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def get_wrong_question(wrong_question_id: str) -> dict[str, Any] | None:
    return db.get_doc("wrong_questions", "wrong_question_id", wrong_question_id)


def list_wrong_questions(
    user_id: str,
    knowledge_point_id: str | None = None,
    book_id: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if knowledge_point_id:
        clauses.append("knowledge_point_id = ?")
        params.append(knowledge_point_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    items = db.list_docs(
        "wrong_questions",
        " AND ".join(clauses),
        params,
        order_by="created_at DESC",
        limit=limit,
    )
    if book_id:
        items = [i for i in items if i.get("book_id") == book_id]
    if since:
        items = [
            i
            for i in (items)
            if (db.from_iso(i.get("created_at")) or db.utcnow()) >= since
        ]
    return items


def count_wrong_questions(user_id: str, status: str | None = None) -> int:
    if status:
        return db.count_docs(
            "wrong_questions", "user_id = ? AND status = ?", [user_id, status]
        )
    return db.count_docs("wrong_questions", "user_id = ?", [user_id])


# ---------------------------------------------------------------------------
# Tutor
# ---------------------------------------------------------------------------

def save_tutor_session(doc: dict[str, Any]) -> None:
    db.upsert_doc(
        "tutor_sessions",
        "tutor_session_id",
        doc["tutor_session_id"],
        doc,
        user_id=doc["user_id"],
        status=doc.get("status", "active"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def get_tutor_session(tutor_session_id: str) -> dict[str, Any] | None:
    return db.get_doc("tutor_sessions", "tutor_session_id", tutor_session_id)


def count_tutor_sessions(user_id: str) -> int:
    return db.count_docs("tutor_sessions", "user_id = ?", [user_id])


def append_tutor_turn(tutor_session_id: str, seq: int, doc: dict[str, Any]) -> None:
    db.upsert_doc(
        "tutor_turns",
        "turn_id",
        doc["turn_id"],
        doc,
        tutor_session_id=tutor_session_id,
        seq=seq,
        created_at=doc["created_at"],
    )


def list_tutor_turns(tutor_session_id: str) -> list[dict[str, Any]]:
    return db.list_docs(
        "tutor_turns",
        "tutor_session_id = ?",
        [tutor_session_id],
        order_by="seq",
    )


# ---------------------------------------------------------------------------
# Practice
# ---------------------------------------------------------------------------

def save_practice_session(doc: dict[str, Any]) -> None:
    db.upsert_doc(
        "practice_sessions",
        "practice_session_id",
        doc["practice_session_id"],
        doc,
        user_id=doc["user_id"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def get_practice_session(practice_session_id: str) -> dict[str, Any] | None:
    return db.get_doc(
        "practice_sessions", "practice_session_id", practice_session_id
    )


def count_practice_attempts(user_id: str) -> int:
    sessions = db.list_docs("practice_sessions", "user_id = ?", [user_id])
    return sum(len(s.get("attempts", [])) for s in sessions)


# ---------------------------------------------------------------------------
# Books / Entitlements
# ---------------------------------------------------------------------------

def save_book(doc: dict[str, Any]) -> None:
    db.upsert_doc("books", "book_id", doc["book_id"], doc)


def get_book(book_id: str) -> dict[str, Any] | None:
    return db.get_doc("books", "book_id", book_id)


def list_books() -> list[dict[str, Any]]:
    return db.list_docs("books", order_by="book_id")


def grant_entitlement(user_id: str, book_id: str, source: str, serial: str | None = None) -> str:
    entitlement_id = db.new_id("ent")
    doc = {
        "entitlement_id": entitlement_id,
        "user_id": user_id,
        "book_id": book_id,
        "source": source,
        "serial_number": serial,
        "created_at": db.to_iso(db.utcnow()),
    }
    db.upsert_doc(
        "entitlements",
        "entitlement_id",
        entitlement_id,
        doc,
        user_id=user_id,
        book_id=book_id,
        created_at=doc["created_at"],
    )
    return entitlement_id


def list_entitlements(user_id: str) -> list[dict[str, Any]]:
    return db.list_docs("entitlements", "user_id = ?", [user_id])


def owns_book(user_id: str, book_id: str) -> bool:
    row = db.query_one(
        "SELECT 1 FROM entitlements WHERE user_id = ? AND book_id = ? LIMIT 1",
        [user_id, book_id],
    )
    return row is not None


def find_entitlement_by_serial(serial: str) -> dict[str, Any] | None:
    rows = db.list_docs("entitlements")
    for item in rows:
        if item.get("serial_number") == serial:
            return item
    return None


# ---------------------------------------------------------------------------
# 幂等
# ---------------------------------------------------------------------------

def get_idempotent_response(key: str) -> dict[str, Any] | None:
    """幂等命中检查。

    列名用 `idem_key` 而不是 `key` —— `key` 是 MySQL 保留字。
    走文档表接口，两种方言都不用特殊语法。
    """
    return db.get_doc("idempotency", "idem_key", key)


def put_idempotent_response(
    key: str, user_id: str | None, endpoint: str, response: dict[str, Any]
) -> None:
    db.upsert_doc(
        "idempotency",
        "idem_key",
        key,
        response,
        user_id=user_id,
        endpoint=endpoint,
        created_at=db.to_iso(db.utcnow()),
    )


# ---------------------------------------------------------------------------
# 活动流（首页用）
# ---------------------------------------------------------------------------

def recent_activities(user_id: str, limit: int = 8) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for hw in list_homeworks(user_id, limit=limit):
        items.append(
            {
                "activity_type": "homework",
                "title": hw.get("title") or "作业分析",
                "subtitle": hw.get("subtitle") or "",
                "reference_id": hw.get("homework_id"),
                "occurred_at": hw.get("created_at"),
            }
        )

    for session in db.list_docs(
        "tutor_sessions", "user_id = ?", [user_id], order_by="updated_at DESC", limit=limit
    ):
        kp_id = session.get("knowledge_point_id")
        point = knowledge.get_point(kp_id) if kp_id else None
        items.append(
            {
                "activity_type": "tutor",
                "title": f"AI Tutor · {point.name if point else '综合'}",
                "subtitle": "已完成" if session.get("completed") else "进行中",
                "reference_id": session.get("tutor_session_id"),
                "occurred_at": session.get("updated_at"),
            }
        )

    for session in db.list_docs(
        "practice_sessions", "user_id = ?", [user_id], order_by="updated_at DESC", limit=limit
    ):
        attempts = session.get("attempts", [])
        items.append(
            {
                "activity_type": "practice",
                "title": "针对性练习",
                "subtitle": f"完成 {len(attempts)} 题",
                "reference_id": session.get("practice_session_id"),
                "occurred_at": session.get("updated_at"),
            }
        )

    items.sort(key=lambda x: x.get("occurred_at") or "", reverse=True)
    return items[:limit]


def streak_days(user_id: str) -> int:
    rows = db.query_all(
        "SELECT created_at FROM evidence WHERE user_id = ? ORDER BY created_at DESC",
        [user_id],
    )
    days = {
        (db.from_iso(r["created_at"]) or db.utcnow()).astimezone(timezone.utc).date()
        for r in rows
    }
    if not days:
        return 0
    today = db.utcnow().date()
    streak = 0
    cursor = today
    if cursor not in days:
        cursor = cursor - timedelta(days=1)
    while cursor in days:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak
