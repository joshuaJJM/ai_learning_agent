"""SQLite 持久化基础设施。

设计取舍（48H 场景）：
  - **只考虑单用户**，但仍然把 user_id 贯穿全表，未来多用户不用改结构。
  - Evidence 用**关系表 + 明确列**，因为它要被 Knowledge Engine 反复聚合查询。
  - 其余对象（homework / question / tutor session / practice session …）用
    **JSON 文档列 + 少量索引列**。这些对象字段多、嵌套深、且几乎总是整取整存，
    用文档存能省掉大量样板代码和 schema 迁移成本。
  - 连接是 thread-local 的：Homework 分析在后台线程跑，不能共用连接。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import get_settings

_local = threading.local()
_init_lock = threading.Lock()
_initialized = False

# backend/ 目录，用于把相对 database_path 锚定住，不受 CWD 影响
BACKEND_ROOT = Path(__file__).resolve().parent.parent


SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id       TEXT PRIMARY KEY,
        device_id     TEXT,
        display_name  TEXT,
        is_demo       INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tokens (
        token       TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        created_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence (
        evidence_id         TEXT PRIMARY KEY,
        user_id             TEXT NOT NULL,
        knowledge_point_id  TEXT NOT NULL,
        source_type         TEXT NOT NULL,
        source_id           TEXT,
        question_id         TEXT,
        result              TEXT NOT NULL,
        score               REAL NOT NULL,
        difficulty          REAL NOT NULL,
        error_type          TEXT,
        confidence          REAL NOT NULL DEFAULT 1.0,
        detail              TEXT,
        created_at          TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_evidence_user_kp ON evidence(user_id, knowledge_point_id)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_user_created ON evidence(user_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS homeworks (
        homework_id TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        analysis_id TEXT,
        created_at  TEXT NOT NULL,
        doc         TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS questions (
        question_id TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        homework_id TEXT,
        correctness TEXT,
        created_at  TEXT NOT NULL,
        doc         TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_questions_homework ON questions(homework_id)",
    """
    CREATE TABLE IF NOT EXISTS wrong_questions (
        wrong_question_id   TEXT PRIMARY KEY,
        user_id             TEXT NOT NULL,
        knowledge_point_id  TEXT,
        status              TEXT NOT NULL DEFAULT 'open',
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL,
        doc                 TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_wq_user_kp ON wrong_questions(user_id, knowledge_point_id)",
    """
    CREATE TABLE IF NOT EXISTS analyses (
        analysis_id TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        status      TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        doc         TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tutor_sessions (
        tutor_session_id TEXT PRIMARY KEY,
        user_id          TEXT NOT NULL,
        status           TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL,
        doc              TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tutor_turns (
        turn_id          TEXT PRIMARY KEY,
        tutor_session_id TEXT NOT NULL,
        seq              INTEGER NOT NULL,
        created_at       TEXT NOT NULL,
        doc              TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_turns_session ON tutor_turns(tutor_session_id, seq)",
    """
    CREATE TABLE IF NOT EXISTS practice_sessions (
        practice_session_id TEXT PRIMARY KEY,
        user_id             TEXT NOT NULL,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL,
        doc                 TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS books (
        book_id TEXT PRIMARY KEY,
        doc     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entitlements (
        entitlement_id TEXT PRIMARY KEY,
        user_id        TEXT NOT NULL,
        book_id        TEXT NOT NULL,
        created_at     TEXT NOT NULL,
        doc            TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency (
        key         TEXT PRIMARY KEY,
        user_id     TEXT,
        endpoint    TEXT,
        response    TEXT NOT NULL,
        created_at  TEXT NOT NULL
    )
    """,
)


def db_path() -> Path:
    raw = Path(get_settings().database_path)
    if not raw.is_absolute():
        raw = BACKEND_ROOT / raw
    return raw


def uploads_dir() -> Path:
    path = BACKEND_ROOT / "data" / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_conn() -> sqlite3.Connection:
    """取当前线程的连接。"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


def init_db() -> None:
    global _initialized
    with _init_lock:
        if _initialized:
            return
        conn = get_conn()
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.commit()
        _initialized = True


def reset_connection_cache() -> None:
    """测试用：切库后丢掉缓存的连接。"""
    global _initialized
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
    _initialized = False


# --------------------------------------------------------------------------
# 通用小工具
# --------------------------------------------------------------------------

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def execute(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    conn = get_conn()
    cursor = conn.execute(sql, tuple(params))
    conn.commit()
    return cursor


def query_all(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return get_conn().execute(sql, tuple(params)).fetchall()


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return get_conn().execute(sql, tuple(params)).fetchone()


# --------------------------------------------------------------------------
# 文档表通用读写
# --------------------------------------------------------------------------

def upsert_doc(
    table: str,
    key_col: str,
    key: str,
    doc: dict[str, Any],
    **columns: Any,
) -> None:
    """整对象 upsert：JSON 存 doc 列，同时把少数字段抽成索引列。"""
    payload = json.dumps(doc, ensure_ascii=False)
    cols = [key_col, *columns.keys(), "doc"]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in [*columns.keys(), "doc"])
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT({key_col}) DO UPDATE SET {updates}"
    )
    execute(sql, [key, *columns.values(), payload])


def get_doc(table: str, key_col: str, key: str) -> dict[str, Any] | None:
    row = query_one(f"SELECT doc FROM {table} WHERE {key_col} = ?", [key])
    if row is None:
        return None
    return json.loads(row["doc"])


def list_docs(
    table: str,
    where: str = "",
    params: Iterable[Any] = (),
    order_by: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sql = f"SELECT doc FROM {table}"
    if where:
        sql += f" WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    if limit is not None:
        sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    return [json.loads(row["doc"]) for row in query_all(sql, params)]


def count_docs(table: str, where: str = "", params: Iterable[Any] = ()) -> int:
    sql = f"SELECT COUNT(*) AS n FROM {table}"
    if where:
        sql += f" WHERE {where}"
    row = query_one(sql, params)
    return int(row["n"]) if row else 0


def delete_doc(table: str, key_col: str, key: str) -> None:
    execute(f"DELETE FROM {table} WHERE {key_col} = ?", [key])
