"""连接必须处于自动提交模式 —— 否则长期只读的线程会看到永远不变的世界。

线上真实事故（复现过一次，损失是"已完成的分析被改写成失败"）：

  MySQL 默认 REPEATABLE READ。连接上第一次 SELECT 开启事务并**钉住当时
  的快照**；只要不提交/回滚，这个连接之后读到的永远是最初那份数据。
  而 `query_all` / `query_one` 从来不提交 —— 于是任何**长期只读**的线程
  都被冻结在它第一次读时的世界。

  看门狗正是这样的线程：

    22:14  看门狗首次扫描 → 钉住快照 S1（分析还在 processing）
    22:15  分析完成（另一个连接写入并提交）→ 库里已经是 completed
    22:15+ 看门狗每次扫描仍看到 S1 → "还在 processing，而且很旧"
    22:29  按 S1 判超时，把 S1 写回去 → **覆盖掉已完成的结果**

  现象：analysis 文档被改回「0 题 / failed / percent 0.25」，
  而 questions / evidence 表里数据都在（它们写在主线程的连接上，提交了）。

  最坑的是：给 `_fail_orphan` 加"落笔前重读"**挡不住** —— 重读走的是
  同一个连接、同一个快照，看起来仍然"确实该收"。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402


def test_mysql_connections_are_autocommit(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ MySQL 连接必须 autocommit=True。

    本地开发用 SQLite，环境里没有 pymysql —— 所以**注入一个假的**，
    让这条断言真的跑起来，而不是被 skip 掉。这个 bug 只在 MySQL 上出现，
    跳过它就等于没有防护。
    """
    captured: dict = {}
    calls: list = []

    class _FakeRaw:
        def cursor(self):
            return self

        def execute(self, *a, **k):
            return self

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

        def ping(self):
            pass

    class _FakeDictCursor:
        pass

    def fake_connect(**kwargs):
        calls.append(kwargs)
        return _FakeRaw()

    fake_pymysql = types.ModuleType("pymysql")
    fake_pymysql.connect = fake_connect  # type: ignore[attr-defined]
    fake_cursors = types.ModuleType("pymysql.cursors")
    fake_cursors.DictCursor = _FakeDictCursor  # type: ignore[attr-defined]
    fake_pymysql.cursors = fake_cursors  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "pymysql", fake_pymysql)
    monkeypatch.setitem(sys.modules, "pymysql.cursors", fake_cursors)

    # `_connect` 读的是 `settings.use_mysql`（只读属性，改不了），
    # 所以给 `db.get_settings` 换一个替身。
    class _StubSettings:
        use_mysql = True
        mysql_host = "127.0.0.1"
        mysql_port = 3306
        mysql_user = "u"
        mysql_password = "p"
        mysql_database = "d"

    monkeypatch.setattr(db, "get_settings", lambda: _StubSettings())

    db._connect()
    assert calls, "没有走到 pymysql.connect"
    captured = calls[-1]

    assert captured.get("autocommit") is True, (
        "MySQL 连接必须 autocommit=True —— 否则读事务会一直开着、"
        "把连接钉在第一次读的快照上（见本文件顶部的说明）"
    )


def test_sqlite_connections_are_autocommit() -> None:
    """SQLite 同理。默认 isolation_level 虽然不会给 SELECT 开事务，
    但显式设成 None（自动提交）能保证这条不变量在两种方言上一致。"""
    conn = db._connect()
    try:
        assert conn.isolation_level is None
    finally:
        conn.close()


def test_reads_do_not_leave_an_open_transaction() -> None:
    """读操作之后连接必须处于干净状态（没有未提交的事务）。"""
    conn = db.get_conn()
    db.query_all("SELECT 1 AS n")
    db.query_one("SELECT 1 AS n")
    # SQLite 下 in_transaction 为 False 表示没有开着的事务
    assert not getattr(conn, "in_transaction", False), (
        "读操作留下了未结束的事务 —— 在 MySQL 上这意味着快照被钉住"
    )
