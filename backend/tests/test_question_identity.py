"""题目身份：内容指纹做稳定 ID。

背景：题库文件给的 id 是「第001题」这种序号。序号在题库重新生成时会整体
平移（第001题变成别的题），于是历史 Evidence 会挂到错误的题上。

做法：id 不合规时改用**题干内容指纹** —— 内容没变指纹就不变，
内容真改了才视为另一道题。这条性质是这个文件要钉住的核心。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from fastapi.testclient import TestClient

from app import db
from app.question_bank import QuestionBank, stable_question_id, stem_fingerprint
from app.question_bank import get_bank

from .conftest import FIXTURE_IMAGE


def _write_bank(directory: pathlib.Path, questions: list[dict[str, Any]]) -> pathlib.Path:
    payload = {
        "schema_version": "1.0",
        "bank_id": "math.derivative.testbank",
        "bank_name": "测试题库",
        "language": "zh-CN",
        "version": "1.0.0",
        "updated_at": "2026-10-02",
        "questions": questions,
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "math.derivative.testbank.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _question(stem: str) -> dict[str, Any]:
    """只给题干，id 由测试按位置重新分配（模拟题库生成器的行为）。"""
    return {
        "id": "",
        "type": "single_choice",
        "stem": stem,
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "answer": "A",
        "knowledge_point_ids": ["math.derivative.monotonicity"],
        "tags": ["利用导数判断函数单调性与单调区间"],
    }


def _renumber(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按位置重新编号 —— 题库生成器就是这么干的。

    这是问题的根源：题目顺序一变，序号就全部错位。
    """
    return [
        {**item, "id": f"第{index:03d}题"} for index, item in enumerate(questions, start=1)
    ]


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

def test_fingerprint_only_depends_on_content() -> None:
    """同样的题干，不管原始序号是什么，指纹都一样。"""
    assert stem_fingerprint("已知 f(x)=x^2") == stem_fingerprint("已知 f(x)=x^2")
    # 空白差异不算差异
    assert stem_fingerprint("已知 f(x)=x^2") == stem_fingerprint(" 已知  f(x)=x^2 ")
    # 内容变了就是另一道题
    assert stem_fingerprint("已知 f(x)=x^2") != stem_fingerprint("已知 f(x)=x^3")


def test_stable_id_keeps_conforming_ids() -> None:
    conforming = "math.derivative.monotonicity.0001"
    assert stable_question_id("math.derivative.x", conforming, "任意题干") == conforming


def test_stable_id_replaces_sequential_ids() -> None:
    qid = stable_question_id("math.derivative.comprehensive", "第001题", "已知 f(x)=x^2")
    assert qid.startswith("math.derivative.comprehensive.")
    assert qid.isascii()
    # math.<主题>.<分组>.<编号> —— 形状符合录入标准
    assert qid.count(".") == 3


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------

def test_loaded_bank_ids_are_stable_and_unique() -> None:
    bank = get_bank()
    ids = [q.id for q in bank.all()]

    assert len(ids) == len(set(ids)), "题目 id 必须唯一"
    assert all(i.isascii() for i in ids), "题目 id 必须是 ASCII"
    for question in bank.all():
        assert question.id == stable_question_id(
            question.bank_id, question.source_id, question.stem
        )


def test_question_number_is_preserved_for_display() -> None:
    bank = get_bank()
    numbers = [q.question_number for q in bank.all()]
    # 「第001题」…「第073题」→ 001 … 073
    assert numbers[0] == "001"
    assert numbers[-1] == "073"
    assert all(n.isdigit() for n in numbers)


def test_reordering_the_bank_keeps_ids_stable(tmp_path: pathlib.Path) -> None:
    """★ 核心性质：题库重新生成（顺序变了、序号跟着重排）后，同一道题的 id 不变。

    这正是旧方案（直接拿序号当 id）会挂错历史的原因：
    第001题在重新生成后变成了另一道题。
    """
    stems = [
        "已知 f(x)=x^2，求 f'(1)。",
        "已知 f(x)=x-ln(x)，求单调区间。",
        "已知 f(x)=x^3-3x，求极值。",
    ]
    # 同一批题，两种顺序 —— 生成器会按位置重新编号
    first_order = _renumber([_question(s) for s in stems])
    second_order = _renumber([_question(s) for s in reversed(stems)])

    before = QuestionBank().load(
        _write_bank(tmp_path / "a", first_order).parent
    )
    after = QuestionBank().load(
        _write_bank(tmp_path / "b", second_order).parent
    )

    # 内容指纹做 id → 同一道题两次都一样
    assert {q.stem: q.id for q in before.all()} == {
        q.stem: q.id for q in after.all()
    }, "顺序变化不该改变题目身份"

    # 而序号确实错位了 —— 这就是要修的问题本身
    assert {q.source_id: q.stem for q in before.all()} != {
        q.source_id: q.stem for q in after.all()
    }, "序号在重新生成后确实会指向别的题"


def test_same_stem_twice_is_rejected_not_silently_merged(tmp_path: pathlib.Path) -> None:
    bank = QuestionBank().load(
        _write_bank(
            tmp_path,
            _renumber([_question("完全一样的题干"), _question("完全一样的题干")]),
        ).parent
    )
    assert bank.stats()["question_count"] == 1
    assert any("指纹" in w for w in bank.report.warnings)


# ---------------------------------------------------------------------------
# Evidence 带上指纹
# ---------------------------------------------------------------------------

def _hash_count(user_id: str) -> int:
    return db.count_docs(
        "evidence", "user_id = ? AND question_stem_hash IS NOT NULL", [user_id]
    )


def test_practice_evidence_carries_stem_hash(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    session = client.post(
        "/api/v1/practice/sessions", headers=auth_headers, json={"count": 1}
    ).json()
    question = session["next_question"]

    client.post(
        f"/api/v1/practice/sessions/{session['practice_session_id']}/answers",
        headers=auth_headers,
        json={"question_id": question["question_id"], "selected_key": "A"},
    )

    row = db.query_one(
        "SELECT question_id, question_stem_hash FROM evidence "
        "WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        [demo_user["user_id"]],
    )
    assert row is not None
    assert row["question_id"] == question["question_id"]
    assert row["question_stem_hash"] == stem_fingerprint(question["stem"])


def test_homework_evidence_carries_stem_hash(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict, fake_vlm: None
) -> None:
    before = _hash_count(demo_user["user_id"])
    with FIXTURE_IMAGE.open("rb") as handle:
        created = client.post(
            "/api/v1/homework/analyses",
            headers=auth_headers,
            files={"images": ("page.png", handle, "image/png")},
            data={"subject": "mathematics"},
        )
    analysis_id = created.json()["analysis_id"]
    detail = client.get(
        f"/api/v1/homework/analyses/{analysis_id}", headers=auth_headers
    ).json()
    assert detail["status"] == "completed"

    assert _hash_count(demo_user["user_id"]) > before, "作业链路也要写指纹"


def test_stem_hash_is_exposed_in_knowledge_detail(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    session = client.post(
        "/api/v1/practice/sessions", headers=auth_headers, json={"count": 1}
    ).json()
    question = session["next_question"]
    client.post(
        f"/api/v1/practice/sessions/{session['practice_session_id']}/answers",
        headers=auth_headers,
        json={"question_id": question["question_id"], "selected_key": "A"},
    )

    kp_id = question["knowledge_points"][0]["knowledge_point_id"]
    body = client.get(f"/api/v1/knowledge/{kp_id}", headers=auth_headers).json()
    assert body["evidence"], "应当有证据"
    assert any(item.get("question_stem_hash") for item in body["evidence"])
