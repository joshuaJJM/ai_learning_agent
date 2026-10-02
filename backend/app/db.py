"""持久化基础设施：MySQL（生产） / SQLite（本地开发与测试）。

设计取舍：
  - **只考虑单用户**，但仍然把 user_id 贯穿全表，未来多用户不用改结构。
  - Evidence 用**关系表 + 明确列**，因为它要被 Knowledge Engine 反复聚合查询。
  - 其余对象（homework / question / tutor session / practice session …）用
    **JSON 文档列 + 少量索引列**。这些对象字段多、嵌套深、且几乎总是整取整存，
    用文档存能省掉大量样板代码和 schema 迁移成本。
  - 连接是 thread-local 的：Homework 分析在后台协程里跑，不能共用连接。

两种方言的差异都收敛在本文件里，`repositories.py` 与业务层不用关心：
  - 占位符：SQLite `?` / MySQL `%s`（统一写 `?`，出口处翻译）
  - upsert：SQLite `ON CONFLICT … DO UPDATE` / MySQL `ON DUPLICATE KEY UPDATE`
  - 索引：MySQL 5.7 的 `CREATE INDEX` 不支持 IF NOT EXISTS，所以索引写在建表语句里
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


# ---------------------------------------------------------------------------
# 方言
# ---------------------------------------------------------------------------

def _use_mysql() -> bool:
    return get_settings().use_mysql


# 列宽刻意保守：utf8mb4 下索引键长上限 767 字节（MySQL 5.7 默认行格式），
# 所以被索引的字符串列不要超过 VARCHAR(191)。
_MYSQL_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id       VARCHAR(64)  NOT NULL,
        device_id     VARCHAR(128) NULL,
        display_name  VARCHAR(255) NULL,
        is_demo       TINYINT      NOT NULL DEFAULT 0,
        created_at    VARCHAR(40)  NOT NULL,
        PRIMARY KEY (user_id),
        KEY idx_users_device (device_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS tokens (
        token       VARCHAR(64) NOT NULL,
        user_id     VARCHAR(64) NOT NULL,
        created_at  VARCHAR(40) NOT NULL,
        PRIMARY KEY (token),
        KEY idx_tokens_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence (
        evidence_id         VARCHAR(64)  NOT NULL,
        user_id             VARCHAR(64)  NOT NULL,
        knowledge_point_id  VARCHAR(64)  NOT NULL,
        source_type         VARCHAR(32)  NOT NULL,
        source_id           VARCHAR(64)  NULL,
        question_id         VARCHAR(64)  NULL,
        result              VARCHAR(32)  NOT NULL,
        score               DOUBLE       NOT NULL,
        difficulty          DOUBLE       NOT NULL,
        error_type          VARCHAR(64)  NULL,
        confidence          DOUBLE       NOT NULL DEFAULT 1.0,
        detail              LONGTEXT     NULL,
        created_at          VARCHAR(40)  NOT NULL,
        PRIMARY KEY (evidence_id),
        KEY idx_evidence_user_kp (user_id, knowledge_point_id),
        KEY idx_evidence_user_created (user_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS homeworks (
        homework_id VARCHAR(64) NOT NULL,
        user_id     VARCHAR(64) NOT NULL,
        analysis_id VARCHAR(64) NULL,
        created_at  VARCHAR(40) NOT NULL,
        doc         LONGTEXT    NOT NULL,
        PRIMARY KEY (homework_id),
        KEY idx_homeworks_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS questions (
        question_id VARCHAR(64) NOT NULL,
        user_id     VARCHAR(64) NOT NULL,
        homework_id VARCHAR(64) NULL,
        correctness VARCHAR(32) NULL,
        created_at  VARCHAR(40) NOT NULL,
        doc         LONGTEXT    NOT NULL,
        PRIMARY KEY (question_id),
        KEY idx_questions_homework (homework_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS wrong_questions (
        wrong_question_id   VARCHAR(64) NOT NULL,
        user_id             VARCHAR(64) NOT NULL,
        knowledge_point_id  VARCHAR(64) NULL,
        status              VARCHAR(32) NOT NULL DEFAULT 'open',
        created_at          VARCHAR(40) NOT NULL,
        updated_at          VARCHAR(40) NOT NULL,
        doc                 LONGTEXT    NOT NULL,
        PRIMARY KEY (wrong_question_id),
        KEY idx_wq_user_kp (user_id, knowledge_point_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS analyses (
        analysis_id VARCHAR(64) NOT NULL,
        user_id     VARCHAR(64) NOT NULL,
        status      VARCHAR(32) NOT NULL,
        created_at  VARCHAR(40) NOT NULL,
        updated_at  VARCHAR(40) NOT NULL,
        doc         LONGTEXT    NOT NULL,
        PRIMARY KEY (analysis_id),
        KEY idx_analyses_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS tutor_sessions (
        tutor_session_id VARCHAR(64) NOT NULL,
        user_id          VARCHAR(64) NOT NULL,
        status           VARCHAR(32) NOT NULL,
        created_at       VARCHAR(40) NOT NULL,
        updated_at       VARCHAR(40) NOT NULL,
        doc              LONGTEXT    NOT NULL,
        PRIMARY KEY (tutor_session_id),
        KEY idx_tutor_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS tutor_turns (
        turn_id          VARCHAR(64) NOT NULL,
        tutor_session_id VARCHAR(64) NOT NULL,
        seq              INT         NOT NULL,
        created_at       VARCHAR(40) NOT NULL,
        doc              LONGTEXT    NOT NULL,
        PRIMARY KEY (turn_id),
        KEY idx_turns_session (tutor_session_id, seq)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS practice_sessions (
        practice_session_id VARCHAR(64) NOT NULL,
        user_id             VARCHAR(64) NOT NULL,
        created_at          VARCHAR(40) NOT NULL,
        updated_at          VARCHAR(40) NOT NULL,
        doc                 LONGTEXT    NOT NULL,
        PRIMARY KEY (practice_session_id),
        KEY idx_practice_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS books (
        book_id VARCHAR(64) NOT NULL,
        doc     LONGTEXT    NOT NULL,
        PRIMARY KEY (book_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS entitlements (
        entitlement_id VARCHAR(64) NOT NULL,
        user_id        VARCHAR(64) NOT NULL,
        book_id        VARCHAR(64) NOT NULL,
        created_at     VARCHAR(40) NOT NULL,
        doc            LONGTEXT    NOT NULL,
        PRIMARY KEY (entitlement_id),
        KEY idx_entitlements_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS tag_scores (
        user_id    VARCHAR(64) NOT NULL,
        tag        VARCHAR(96) NOT NULL,
        score      INT         NOT NULL DEFAULT 0,
        updated_at VARCHAR(40) NOT NULL,
        PRIMARY KEY (user_id, tag)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency (
        idem_key    VARCHAR(128) NOT NULL,
        user_id     VARCHAR(64)  NULL,
        endpoint    VARCHAR(128) NULL,
        created_at  VARCHAR(40)  NOT NULL,
        doc         LONGTEXT     NOT NULL,
        PRIMARY KEY (idem_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
)


SQLITE_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id       TEXT PRIMARY KEY,
        device_id     TEXT,
        display_name  TEXT,
        is_demo       INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_device ON users(device_id)",
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
    CREATE TABLE IF NOT EXISTS tag_scores (
        user_id    TEXT NOT NULL,
        tag        TEXT NOT NULL,
        score      INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, tag)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency (
        idem_key    TEXT PRIMARY KEY,
        user_id     TEXT,
        endpoint    TEXT,
        created_at  TEXT NOT NULL,
        doc         TEXT NOT NULL
    )
    """,
)


# ---------------------------------------------------------------------------
# 连接
# ---------------------------------------------------------------------------

class _MySqlConnection:
    """把 pymysql 包一层，接口对齐 sqlite3.Connection。

    sqlite3 有 `conn.execute(sql, params)`，pymysql 只能走 cursor，
    业务层不该关心这个差别。
    """

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def execute(self, sql: str, params: Iterable[Any] = ()) -> Any:
        cursor = self._raw.cursor()
        cursor.execute(_translate(sql), tuple(params))
        return cursor

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    def ping(self) -> None:
        # MySQL 会回收空闲连接，长驻进程必须 ping 一下再重连
        self._raw.ping(reconnect=True)


def _translate(sql: str) -> str:
    """占位符统一写 `?`，出口处翻译成 pymysql 的 `%s`。"""
    return sql.replace("?", "%s") if _use_mysql() else sql


def db_path() -> Path:
    raw = Path(get_settings().database_path)
    if not raw.is_absolute():
        raw = BACKEND_ROOT / raw
    return raw


def storage_label() -> str:
    """给日志和 /health 用的人类可读描述。"""
    settings = get_settings()
    if settings.use_mysql:
        return (
            f"mysql://{settings.mysql_user}@{settings.mysql_host}:"
            f"{settings.mysql_port}/{settings.mysql_database}"
        )
    return str(db_path())


def uploads_dir() -> Path:
    path = BACKEND_ROOT / "data" / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> Any:
    settings = get_settings()
    if settings.use_mysql:
        import pymysql
        from pymysql.cursors import DictCursor

        raw = pymysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=10,
        )
        return _MySqlConnection(raw)

    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get_conn() -> Any:
    """取当前线程的连接。"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    elif _use_mysql():
        try:
            conn.ping()
        except Exception:  # noqa: BLE001 - 连接失效就重连
            try:
                conn.close()
            finally:
                conn = _connect()
                _local.conn = conn
    return conn


def init_db() -> None:
    global _initialized
    with _init_lock:
        if _initialized:
            return
        conn = get_conn()
        statements = _MYSQL_SCHEMA if _use_mysql() else SQLITE_SCHEMA
        for statement in statements:
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


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------

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


def execute(sql: str, params: Iterable[Any] = ()) -> Any:
    conn = get_conn()
    cursor = conn.execute(sql, tuple(params))
    conn.commit()
    return cursor


def query_all(sql: str, params: Iterable[Any] = ()) -> list[Any]:
    return list(get_conn().execute(sql, tuple(params)).fetchall())


def query_one(sql: str, params: Iterable[Any] = ()) -> Any | None:
    return get_conn().execute(sql, tuple(params)).fetchone()


# ---------------------------------------------------------------------------
# 文档表通用读写
# ---------------------------------------------------------------------------

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

    if _use_mysql():
        updates = ", ".join(f"{c}=VALUES({c})" for c in [*columns.keys(), "doc"])
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {updates}"
        )
    else:
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
    sql = f"SELECT COUNT(1) AS n FROM {table}"
    if where:
        sql += f" WHERE {where}"
    row = query_one(sql, params)
    return int(row["n"]) if row else 0


def delete_doc(table: str, key_col: str, key: str) -> None:
    execute(f"DELETE FROM {table} WHERE {key_col} = ?", [key])


def bump_counter(
    table: str,
    key_columns: Sequence[str],
    key_values: Sequence[Any],
    delta_column: str,
    delta: int,
    **extra: Any,
) -> None:
    """把某个计数列加上 delta，行不存在时以 0 为起点创建。

    这是 tag_scores 的核心操作（标签 +1 / -1），
    和 upsert_doc 的「整体覆盖」语义不同，所以单独一个函数。
    """
    columns = [*key_columns, delta_column, *extra.keys()]
    placeholders = ", ".join("?" for _ in columns)
    conflict = ", ".join(key_columns)

    if _use_mysql():
        updates = [f"{delta_column} = {delta_column} + VALUES({delta_column})"]
        updates += [f"{name} = VALUES({name})" for name in extra]
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {', '.join(updates)}"
        )
    else:
        updates = [f"{delta_column} = {delta_column} + excluded.{delta_column}"]
        updates += [f"{name} = excluded.{name}" for name in extra]
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict}) DO UPDATE SET {', '.join(updates)}"
        )

    execute(sql, [*key_values, delta, *extra.values()])
