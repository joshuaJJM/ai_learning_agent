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
        question_stem_hash  VARCHAR(40)  NULL,
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
        book_id             VARCHAR(64) NULL,
        question_stem_hash  VARCHAR(40) NULL,
        status              VARCHAR(32) NOT NULL DEFAULT 'open',
        created_at          VARCHAR(40) NOT NULL,
        updated_at          VARCHAR(40) NOT NULL,
        doc                 LONGTEXT    NOT NULL,
        PRIMARY KEY (wrong_question_id),
        KEY idx_wq_user_kp (user_id, knowledge_point_id),
        KEY idx_wq_book (user_id, book_id),
        -- 规范题目身份：同一道题多次做错只保留一条「当前待复习项」
        UNIQUE KEY uk_wq_user_stem (user_id, question_stem_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS analyses (
        analysis_id  VARCHAR(64) NOT NULL,
        user_id      VARCHAR(64) NOT NULL,
        status       VARCHAR(32) NOT NULL,
        batch_number INT         NOT NULL DEFAULT 0,
        created_at   VARCHAR(40) NOT NULL,
        updated_at   VARCHAR(40) NOT NULL,
        doc          LONGTEXT    NOT NULL,
        PRIMARY KEY (analysis_id),
        KEY idx_analyses_user (user_id),
        KEY idx_analyses_batch (user_id, batch_number)
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
        question_stem_hash  TEXT,
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
        book_id             TEXT,
        question_stem_hash  TEXT,
        status              TEXT NOT NULL DEFAULT 'open',
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL,
        doc                 TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_wq_user_kp ON wrong_questions(user_id, knowledge_point_id)",
    "CREATE INDEX IF NOT EXISTS idx_wq_book ON wrong_questions(user_id, book_id)",
    # 同一道题多次做错只保留一条「当前待复习项」
    "CREATE UNIQUE INDEX IF NOT EXISTS uk_wq_user_stem ON wrong_questions(user_id, question_stem_hash)",
    """
    CREATE TABLE IF NOT EXISTS analyses (
        analysis_id  TEXT PRIMARY KEY,
        user_id      TEXT NOT NULL,
        status       TEXT NOT NULL,
        batch_number INTEGER NOT NULL DEFAULT 0,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        doc          TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_analyses_batch ON analyses(user_id, batch_number)",
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
        _run_migrations(conn)
        ensure_batch_uniqueness(conn)
        _initialized = True


# ---------------------------------------------------------------------------
# 轻量迁移
# ---------------------------------------------------------------------------
#
# `CREATE TABLE IF NOT EXISTS` 对**已存在**的表不会加列，所以在生产库里
# 新增字段必须显式 ALTER。MySQL 5.7 不支持 `ADD COLUMN IF NOT EXISTS`
# （那是 MariaDB 的扩展），SQLite 也不支持，所以先查再改。

# (表名, 列名, 列定义) —— 只追加，不要修改已有条目
_COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    # 上传批次号：按用户递增，给前端的「近 50 批」列表用
    ("analyses", "batch_number", "INT NOT NULL DEFAULT 0"),
    # 错题所属图书：筛选必须在 SQL 里做，不能先 LIMIT 再在 Python 里过滤
    ("wrong_questions", "book_id", "VARCHAR(64) NULL"),
    # 题干指纹：让「这道题的作答历史」独立于题库版本被追溯。
    # 题库重新生成后 question_id 可能指向别的题，但指纹只跟内容走。
    ("evidence", "question_stem_hash", "VARCHAR(40) NULL"),
    # 错题的**规范题目身份**。之前一行错题对应「某一次作业里的某道题」，
    # 同一道题在不同作业里做错就会各留一行，列表上看起来是重复的。
    # 加上指纹后，同一道题只保留一条「当前待复习项」，多次做错合并进去。
    ("wrong_questions", "question_stem_hash", "VARCHAR(40) NULL"),
)

# (表名, 索引名, 列, 是否唯一)
_INDEX_MIGRATIONS: tuple[tuple[str, str, str, bool], ...] = (
    ("analyses", "idx_analyses_batch", "user_id, batch_number", False),
    ("wrong_questions", "idx_wq_book", "user_id, book_id", False),
    # 唯一索引在**合并完重复行之后**才建（见 _merge_duplicate_wrong_questions），
    # 否则存量重复数据会让建索引直接失败。
    ("wrong_questions", "uk_wq_user_stem", "user_id, question_stem_hash", True),
)


def _table_columns(conn: Any, table: str) -> set[str]:
    if _use_mysql():
        rows = conn.execute(
            "SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?",
            [table],
        ).fetchall()
    else:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    names: set[str] = set()
    for row in rows:
        try:
            names.add(str(row["name"]))
        except (KeyError, TypeError):
            names.add(str(row[1]))
    return names


def _index_names(conn: Any, table: str) -> set[str]:
    if _use_mysql():
        rows = conn.execute(
            "SELECT DISTINCT INDEX_NAME AS name FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?",
            [table],
        ).fetchall()
        return {str(row["name"]) for row in rows}
    rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _run_migrations(conn: Any) -> None:
    applied: list[str] = []
    for table, column, definition in _COLUMN_MIGRATIONS:
        if column in _table_columns(conn, table):
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.commit()
        applied.append(f"{table}.{column}")

    # 错题的规范身份要先回填、再合并历史重复行，**最后**才能建唯一索引。
    merged = _backfill_wrong_question_hashes(conn)
    if merged:
        applied.append(f"合并重复错题 {merged} 行")

    # 新加的列通常也要配索引
    for table, index_name, columns, unique in _INDEX_MIGRATIONS:
        if index_name in _index_names(conn, table):
            continue
        keyword = "UNIQUE INDEX" if unique else "INDEX"
        try:
            conn.execute(f"CREATE {keyword} {index_name} ON {table} ({columns})")
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            # 唯一索引建不上说明还有重复行（不该发生，合并应当已经清干净）。
            # 这里**不能吞掉**：宁可日志里响亮地报出来，也不要让唯一性悄悄失效。
            import logging

            logging.getLogger("haoxue").warning(
                "索引 %s 创建失败（可能有残留重复行）: %s", index_name, exc
            )
            continue
        applied.append(index_name)

    if applied:
        import logging

        logging.getLogger("haoxue").info("数据库迁移已应用: %s", ", ".join(applied))


def _per_user_max_batch(conn: Any) -> dict[str, int]:
    """每个用户当前已分配的最大批次号（只看非 0 的）。"""
    rows = conn.execute(
        "SELECT user_id, MAX(batch_number) AS n FROM analyses "
        "WHERE batch_number > 0 GROUP BY user_id"
    ).fetchall()
    result: dict[str, int] = {}
    for row in rows:
        try:
            result[str(row["user_id"])] = int(row["n"] or 0)
        except (KeyError, TypeError):
            result[str(row[0])] = int(row[1] or 0)
    return result


#: 合并重复错题时，最多保留多少条 attempt 明细（更早的仍有 Evidence 可查）
MAX_KEPT_ATTEMPTS = 20


def _backfill_wrong_question_hashes(conn: Any) -> int:
    """给错题补上题干指纹，并把同一道题的历史重复行**合并**成一条。

    背景：`wrong_questions` 原来是一行对应「某次作业里的某道题」，
    同一道题在不同作业里做错就各留一行，列表上看起来完全是重复的
    （前端 Phase 6 报的就是这个）。

    正确的模型是：**行 = 当前待复习的规范题目**，多次做错合并进同一条，
    但 attempt 明细要留下来 —— 历史本身有价值，不能一删了之。

    返回合并掉的（删除的）行数。
    """
    import json

    from .question_bank import stem_fingerprint

    rows = conn.execute(
        "SELECT wrong_question_id, user_id, doc FROM wrong_questions"
    ).fetchall()
    if not rows:
        return 0

    def cell(row: Any, key: str, index: int) -> Any:
        try:
            return row[key]
        except (KeyError, TypeError):
            return row[index]

    # 1) 回填指纹（老数据的 doc 里没有这个字段，从题干现算）
    parsed: list[tuple[str, str, dict[str, Any], str]] = []
    for row in rows:
        wid = str(cell(row, "wrong_question_id", 0))
        uid = str(cell(row, "user_id", 1))
        raw_doc = cell(row, "doc", 2)
        try:
            doc = json.loads(raw_doc) if isinstance(raw_doc, str) else dict(raw_doc)
        except (TypeError, ValueError):
            doc = {}
        digest = str(doc.get("question_stem_hash") or "")
        if not digest:
            digest = stem_fingerprint(str(doc.get("question_content") or ""))
        parsed.append((wid, uid, doc, digest))

    changed = 0
    for wid, _uid, _doc, digest in parsed:
        conn.execute(
            "UPDATE wrong_questions SET question_stem_hash = ? "
            "WHERE wrong_question_id = ? AND (question_stem_hash IS NULL "
            "OR question_stem_hash <> ?)",
            [digest, wid, digest],
        )
        changed += 1
    if changed:
        conn.commit()

    # 2) 按 (user_id, 指纹) 分组，多于一条的合并
    groups: dict[tuple[str, str], list[tuple[str, str, dict[str, Any], str]]] = {}
    for item in parsed:
        groups.setdefault((item[1], item[3]), []).append(item)

    merged_rows = 0
    for (uid, digest), members in groups.items():
        if len(members) < 2:
            # 单条也要补齐 attempts / attempt_count —— 否则老数据的这些字段
            # 是 NULL，详情接口会返回空 attempts，与合并后的数据形状不一致。
            wid, _u, only, _d = members[0]
            if not (only.get("attempts") and only.get("attempt_count")):
                single = only.get("attempts") or [
                    {
                        "question_id": only.get("question_id"),
                        "homework_id": only.get("source_id"),
                        "student_answer": only.get("student_answer"),
                        "correctness": only.get("correctness"),
                        "created_at": only.get("created_at"),
                    }
                ]
                single = [a for a in single if a]
                only["attempts"] = single
                only["attempt_count"] = int(only.get("attempt_count") or 0) or len(single)
                only["first_wrong_at"] = only.get("first_wrong_at") or only.get(
                    "created_at"
                )
                only["last_wrong_at"] = (
                    only.get("last_wrong_at")
                    or only.get("updated_at")
                    or only.get("created_at")
                )
                only["question_stem_hash"] = digest
                conn.execute(
                    "UPDATE wrong_questions SET doc = ?, question_stem_hash = ? "
                    "WHERE wrong_question_id = ?",
                    [json.dumps(only, ensure_ascii=False), digest, wid],
                )
            continue

        # 存活者取**最早创建**的那条：id 最稳定，前端可能已经引用过它
        members.sort(key=lambda m: str(m[2].get("created_at") or ""))
        keeper_id, _u, keeper, _d = members[0]
        duplicates = members[1:]

        attempts: list[dict[str, Any]] = list(keeper.get("attempts") or [])
        if not attempts:
            # 老数据没有 attempts 字段，用 kept 自己的那条补上
            attempts.append(
                {
                    "question_id": keeper.get("question_id"),
                    "homework_id": keeper.get("source_id"),
                    "student_answer": keeper.get("student_answer"),
                    "correctness": keeper.get("correctness"),
                    "created_at": keeper.get("created_at"),
                }
            )
        for _wid, _u, dup, _dd in duplicates:
            attempts.extend(dup.get("attempts") or [])
            if not dup.get("attempts"):
                attempts.append(
                    {
                        "question_id": dup.get("question_id"),
                        "homework_id": dup.get("source_id"),
                        "student_answer": dup.get("student_answer"),
                        "correctness": dup.get("correctness"),
                        "created_at": dup.get("created_at"),
                    }
                )

        attempts = [a for a in attempts if a]
        attempts.sort(key=lambda a: str(a.get("created_at") or ""))
        # 快照取**最近一次**做错的内容
        latest = duplicates[-1][2] if duplicates else keeper

        keeper["attempts"] = attempts[-MAX_KEPT_ATTEMPTS:]
        keeper["attempt_count"] = len(attempts)
        keeper["first_wrong_at"] = keeper.get("created_at")
        keeper["last_wrong_at"] = latest.get("created_at") or keeper.get("created_at")
        for field in (
            "question_id",
            "question_number",
            "question_content",
            "choices",
            "student_answer",
            "correct_answer",
            "explanation",
            "correctness",
            "error_type",
            "error_label",
            "diagnosis",
            "image_url",
            "source_id",
            "source_name",
            "book_id",
        ):
            if latest.get(field) is not None:
                keeper[field] = latest[field]
        keeper["question_stem_hash"] = digest
        keeper["status"] = "open"
        keeper["updated_at"] = latest.get("created_at") or keeper.get("updated_at")

        for _wid, _u, _dup, _dd in duplicates:
            conn.execute(
                "DELETE FROM wrong_questions WHERE wrong_question_id = ?", [_wid]
            )
            merged_rows += 1

        conn.execute(
            "UPDATE wrong_questions SET doc = ?, question_stem_hash = ?, "
            "status = ?, updated_at = ? WHERE wrong_question_id = ?",
            [
                json.dumps(keeper, ensure_ascii=False),
                digest,
                keeper["status"],
                keeper["updated_at"],
                keeper_id,
            ],
        )
        import logging

        logging.getLogger("haoxue").info(
            "错题去重: %s 的同一道题由 %d 条合并为 1 条（累计做错 %d 次）",
            uid,
            len(members),
            len(attempts),
        )

    if merged_rows:
        conn.commit()
    return merged_rows


def _backfill_batch_numbers(conn: Any) -> int:
    """给历史分析补批次号（迁移加列时默认全是 0）。

    必须在建 (user_id, batch_number) 唯一索引**之前**跑：
    同一用户的多行如果都是 0，唯一索引根本建不起来。

    关键：新号要**从该用户已有的最大号之后接着编**。
    列是后来加的，所以库里很可能已经混着两种情况 ——
    加列前的老记录是 0，加列后新上传的已经拿到 1、2……
    如果一律从 1 开始补，就会和已存在的 1 撞车，唯一索引建不起来。
    """
    rows = conn.execute(
        "SELECT user_id, analysis_id FROM analyses WHERE batch_number = 0 "
        "ORDER BY user_id, created_at, analysis_id"
    ).fetchall()
    if not rows:
        return 0

    # 起点 = 该用户已分配的最大号（没有则 0）
    counters = _per_user_max_batch(conn)
    execute = getattr(conn, "execute")
    for row in rows:
        try:
            user_id, analysis_id = str(row["user_id"]), str(row["analysis_id"])
        except (KeyError, TypeError):
            user_id, analysis_id = str(row[0]), str(row[1])
        counters[user_id] = counters.get(user_id, 0) + 1
        if _use_mysql():
            execute(
                "UPDATE analyses SET batch_number = %s WHERE analysis_id = %s",
                (counters[user_id], analysis_id),
            )
        else:
            execute(
                "UPDATE analyses SET batch_number = ? WHERE analysis_id = ?",
                (counters[user_id], analysis_id),
            )
    conn.commit()
    return len(rows)


def _duplicate_batch_groups(conn: Any) -> list[tuple[str, int, int]]:
    rows = conn.execute(
        "SELECT user_id, batch_number, COUNT(1) AS n FROM analyses "
        "GROUP BY user_id, batch_number HAVING COUNT(1) > 1"
    ).fetchall()
    result: list[tuple[str, int, int]] = []
    for row in rows:
        try:
            result.append((str(row["user_id"]), int(row["batch_number"]), int(row["n"])))
        except (KeyError, TypeError):
            result.append((str(row[0]), int(row[1]), int(row[2])))
    return result


def ensure_batch_uniqueness(conn: Any) -> None:
    """给 (user_id, batch_number) 加唯一约束（幂等，可重复调用）。

    并发上传时 `MAX(batch_number) + 1` 会算出同一个号。有了唯一索引，
    插入冲突会直接报错，由 repositories.insert_analysis 重试拿下一个号 ——
    这是「用户内递增且唯一」的真正保证，而不是靠时序运气。
    """
    index_name = "uk_analyses_batch"
    if index_name in _index_names(conn, "analyses"):
        return

    backfilled = _backfill_batch_numbers(conn)

    # 回填之后再确认一次：万一历史数据本身就有重复（例如手工导入过），
    # 建索引会直接失败并让服务起不来。这里给出可读的报错而不是抛 SQL 异常。
    duplicates = _duplicate_batch_groups(conn)
    if duplicates:
        import logging

        logging.getLogger("haoxue").error(
            "批次号存在重复，跳过唯一约束创建: %s", duplicates[:5]
        )
        return

    conn.execute(
        f"CREATE UNIQUE INDEX {index_name} ON analyses (user_id, batch_number)"
    )
    conn.commit()

    import logging

    logging.getLogger("haoxue").info(
        "已建立批次号唯一约束 %s（回填 %d 行历史数据）", index_name, backfilled
    )


def is_duplicate_error(exc: Exception) -> bool:
    """判断异常是不是唯一键冲突（两种方言的报错文案不同）。"""
    text = str(exc).lower()
    return "duplicate" in text or "unique" in text or "1062" in text


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
