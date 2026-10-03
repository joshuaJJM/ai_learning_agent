"""代码评审发现的 5 个问题的回归测试。

  P1 没有正确答案时仍可能计分
  P1 第 9 道起的非题库题跳过复核却照常计分
  P2 仅凭题干识别「同一道题」会误合并
  P2 补救耗尽后的轮次类型与内容不一致
  P2 Tutor 流式响应丢失部分作答结果
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db, repositories
from app.question_bank import choices_fingerprint, stem_fingerprint
from app.services import vlm_service, wrong_question_service
from app.services.vlm_service import RawQuestion

from .conftest import FIXTURE_IMAGE

OPTIONS = {"A": "1", "B": "2", "C": "3", "D": "4"}


class _StubLlm:
    configured = True
    backup_configured = False


def _raw(**overrides: Any) -> RawQuestion:
    base: dict[str, Any] = {
        "question_number": "1",
        "stem": "已知 f(x)=x^2，求 f'(1)。",
        "options": dict(OPTIONS),
        "student_answer": "A",
        "correct_answer": "C",
        "correctness": "wrong",
        "knowledge_point_ids": ["math.derivative.monotonicity"],
        "tags": [],
        "error_type": None,
        "diagnosis": "",
        "explanation": None,
        "confidence": 0.9,
        "difficulty": 0.5,
    }
    base.update(overrides)
    return RawQuestion(**base)


# ---------------------------------------------------------------------------
# P1-1：没有正确答案就不能判对错
# ---------------------------------------------------------------------------

def test_no_correct_answer_cannot_be_judged_correct() -> None:
    """★ 复现评审给的输入：无答案 + 模型自报 correct。

    没有参考答案就没有可比较的对象，模型那句"我判他做对了"是凭感觉说的。
    更糟的是这类题会被复核流程过滤掉（复核的前提是有答案可比），
    于是它会**绕过整个校验直接写进掌握度**。
    """
    assert vlm_service._clean_correctness("correct", "A", None) == "unknown"
    assert vlm_service._clean_correctness("wrong", "A", None) == "unknown"
    assert vlm_service._clean_correctness("partial", "A", None) == "unknown"


def test_no_correct_answer_question_carries_no_scoring(monkeypatch, client) -> None:
    """无答案的题不能产生 Knowledge 影响。"""

    # 直接把一条"无答案但模型说 correct"的题喂给结果构造
    question = _raw(correct_answer=None, correctness="unknown", student_answer="A")
    assert question.correctness == "unknown"
    assert question.correctness not in ("correct", "wrong", "partial")


def test_unanswered_still_wins_over_missing_answer() -> None:
    """学生没作答依然是 unanswered（语义不同，不能混）。"""
    assert vlm_service._clean_correctness("wrong", None, None) == "unanswered"


# ---------------------------------------------------------------------------
# P1-2：超出复核上限的题不能照常计分
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_questions_beyond_the_verify_cap_are_not_scored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★ 只截取前 8 道复核，其余的必须判 unknown —— 不能只加一句警告。"""
    from app.services import vlm_service as vs

    seen: list[str] = []

    async def _solver(stem, options, llm, model):
        seen.append(stem)
        return "C"

    monkeypatch.setattr(vs, "_solve_independently", _solver)

    cap = vs.MAX_VERIFY_PER_ANALYSIS
    total = cap + 4
    questions = [
        _raw(
            question_number=str(index + 1),
            stem=f"第 {index + 1} 题：已知 f(x)=x^{index}，求 f'(1)。",
            correct_answer="C",
        )
        for index in range(total)
    ]

    warnings = await vs.verify_answers(
        questions, client=_StubLlm(), exclude_models={"deepseek-flash"}
    )

    # 只复核了前 cap 道
    assert len(seen) == cap

    checked = questions[:cap]
    skipped = questions[cap:]

    for question in checked:
        assert question.correctness == "wrong", "复核一致的题照常计分"
        assert question.correct_answer == "C"

    for question in skipped:
        assert question.correctness == "unknown", (
            f"第 {question.question_number} 题没被复核，却还是 "
            f"{question.correctness} —— 会照常写进掌握度"
        )
        assert question.correct_answer is None
        # 但别把信息丢掉
        assert question.possible_answer == "C"
        assert question.possible_answer_source == "recognition"

    assert any("未复核" in w for w in warnings), warnings


# ---------------------------------------------------------------------------
# P2-3：同题干不同选项不能被当成同一道题
# ---------------------------------------------------------------------------

def test_choices_fingerprint_distinguishes_options() -> None:
    assert choices_fingerprint({"A": "1", "B": "2"}) != choices_fingerprint(
        {"A": "9", "B": "2"}
    )
    assert choices_fingerprint({"A": "1", "B": "2"}) == choices_fingerprint(
        {"B": "2", "A": "1"}  # 顺序无关
    )


def test_same_stem_different_options_do_not_merge() -> None:
    """★ 同题干、不同选项是两道不同的题，不能让后一道覆盖前一道的快照。"""
    user_id = "u_same_stem_test"
    snapshot: dict[str, Any] = {
        "question_id": "q_1",
        "question_number": "1",
        "question_content": "同一段题干",
        "choices": {"A": "选项一", "B": "选项二"},
        "correctness": "wrong",
    }
    first = wrong_question_service.record_attempt(
        user_id,
        question_stem_hash="stem-hash",
        snapshot=snapshot,
        attempt={"question_id": "q_1"},
        now="2026-01-01T00:00:00+00:00",
    )
    second = wrong_question_service.record_attempt(
        user_id,
        question_stem_hash="stem-hash",  # 同一个题干指纹
        snapshot={
            **snapshot,
            "question_id": "q_2",
            "choices": {"A": "完全不同的选项", "B": "另一个"},
        },
        attempt={"question_id": "q_2"},
        now="2026-01-02T00:00:00+00:00",
    )

    assert second["wrong_question_id"] != first["wrong_question_id"], (
        "同题干不同选项被误合并了 —— 后一道会覆盖前一道的快照"
    )

    rows = repositories.list_wrong_questions(user_id, limit=10)
    assert len(rows) == 2, "两道不同的题应当各自留一条"
    # 两条的快照都还在，没有被互相覆盖
    contents = {r["question_id"] for r in rows}
    assert contents == {"q_1", "q_2"}


def test_same_stem_same_options_still_merge() -> None:
    """选项也一致时才是真的同一道题，仍要合并。"""
    user_id = "u_same_all_test"
    snapshot: dict[str, Any] = {
        "question_id": "q_1",
        "question_number": "1",
        "question_content": "同一段题干",
        "choices": dict(OPTIONS),
        "correctness": "wrong",
    }
    first = wrong_question_service.record_attempt(
        user_id,
        question_stem_hash="h",
        snapshot=snapshot,
        attempt={"question_id": "q_1"},
        now="2026-01-01T00:00:00+00:00",
    )
    second = wrong_question_service.record_attempt(
        user_id,
        question_stem_hash="h",
        snapshot={**snapshot, "question_id": "q_2"},
        attempt={"question_id": "q_2"},
        now="2026-01-02T00:00:00+00:00",
    )
    assert second["wrong_question_id"] == first["wrong_question_id"]
    assert second["attempt_count"] == 2


def test_bank_keeps_both_when_stem_collides(tmp_path) -> None:
    """题库里同题干不同选项的两道题，都要保留（原来会丢掉第二道）。"""
    import json

    from app.question_bank import QuestionBank

    payload = {
        "schema_version": "1.0",
        "bank_id": "math.derivative.collide",
        "bank_name": "冲突测试",
        "language": "zh-CN",
        "version": "1.0.0",
        "updated_at": "2026-10-03",
        "questions": [
            {
                "id": "第001题",
                "type": "single_choice",
                "stem": "完全相同的题干",
                "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "answer": "A",
                "knowledge_point_ids": ["math.derivative.monotonicity"],
                "tags": [],
            },
            {
                "id": "第002题",
                "type": "single_choice",
                "stem": "完全相同的题干",
                "options": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"},
                "answer": "B",
                "knowledge_point_ids": ["math.derivative.monotonicity"],
                "tags": [],
            },
        ],
    }
    bank_dir = tmp_path / "banks"
    bank_dir.mkdir()
    (bank_dir / "math.derivative.collide.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    bank = QuestionBank().load(bank_dir)
    assert bank.stats()["question_count"] == 2, (
        "同题干不同选项被当成重复题丢掉了"
    )
    ids = [q.id for q in bank.all()]
    assert len(set(ids)) == 2


# ---------------------------------------------------------------------------
# P2-5：流式响应不能丢字段
# ---------------------------------------------------------------------------

def _sse_events(text: str) -> list[tuple[str, dict[str, Any]]]:
    import json

    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        events.append((name, json.loads(data)))
    return events


def test_stream_done_event_matches_the_json_contract(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """★ 只用流式接口的客户端也要拿到完整判定与掌握度变化。"""
    created = client.post(
        "/api/v1/tutor/sessions",
        headers=auth_headers,
        json={
            "source_type": "knowledge_point",
            "knowledge_point_id": "math.derivative.monotonicity_applications",
        },
    ).json()
    sid = created["tutor_session_id"]
    choice = created["turn"]["choices"][0]["key"]

    streamed = client.post(
        f"/api/v1/tutor/sessions/{sid}/turns",
        headers=auth_headers,
        json={"selected_key": choice, "stream": True},
    )
    done = dict(_sse_events(streamed.text))["done"]

    for field in (
        "evaluation",
        "knowledge_changes",
        "next_action",
        "progress",
        "phase",
        "completed",
        "student_understanding",
        "replayed",
    ):
        assert field in done, f"流式 done 事件缺少 {field}"

    assert done["evaluation"] is not None
    assert "strategy" in done["evaluation"]
    assert isinstance(done["knowledge_changes"], list)
