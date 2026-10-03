"""第二轮代码评审的 2 个问题（都是上一轮修复引出的下游问题）。

  P1 题库匹配只比题干 → 同题干不同选项时挑错那一道、采用错答案
  P2 复核流程把 unanswered 改写成 unknown → 丢失「学生没作答」的状态
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.question_bank import BankQuestion, QuestionBank
from app.services import vlm_service
from app.services.vlm_service import RawQuestion

OPTIONS_A = {"A": "选项甲", "B": "选项乙", "C": "选项丙", "D": "选项丁"}
OPTIONS_B = {"A": "完全不同的甲", "B": "完全不同的乙", "C": "完全不同的丙", "D": "完全不同的丁"}

SHARED_STEM = "已知函数 f(x) = x^2，则下列说法正确的是"


def _bank_question(qid: str, options: dict[str, str], answer: str) -> BankQuestion:
    return BankQuestion(
        id=qid,
        source_id=f"第{qid}题",
        question_number=qid,
        bank_id="math.derivative.collide",
        type="single_choice",
        stem=SHARED_STEM,
        options=dict(options),
        answer=answer,
        explanation="",
        knowledge_point_ids=("math.derivative.monotonicity",),
        tags=(),
        source_ref="",
        difficulty=0.5,
    )


class _FakeBank:
    def __init__(self, questions: list[BankQuestion]) -> None:
        self._questions = questions

    def all(self) -> list[BankQuestion]:
        return list(self._questions)

    def get(self, question_id: str) -> BankQuestion | None:
        return next((q for q in self._questions if q.id == question_id), None)


@pytest.fixture()
def colliding_bank(monkeypatch: pytest.MonkeyPatch) -> None:
    """两道题干完全相同、选项完全不同的题。"""
    bank = _FakeBank(
        [
            _bank_question("q-alpha", OPTIONS_A, "A"),
            _bank_question("q-beta", OPTIONS_B, "B"),
        ]
    )
    monkeypatch.setattr(vlm_service, "get_bank", lambda: bank)


# ---------------------------------------------------------------------------
# P1：匹配必须核对选项
# ---------------------------------------------------------------------------

def test_options_similarity_ignores_keys_but_not_text() -> None:
    assert vlm_service.options_similarity(OPTIONS_A, dict(OPTIONS_A)) == 1.0
    # 键顺序无关
    assert vlm_service.options_similarity(
        {"A": "甲", "B": "乙"}, {"B": "乙", "A": "甲"}
    ) == 1.0
    # 文字不同就是不相似
    assert vlm_service.options_similarity(OPTIONS_A, OPTIONS_B) < 0.5


def test_exact_stem_single_candidate_still_matches(colliding_bank: None, monkeypatch) -> None:
    """只有一道题时行为不变（别把正常匹配也搞坏）。"""
    monkeypatch.setattr(
        vlm_service, "get_bank", lambda: _FakeBank([_bank_question("q-one", OPTIONS_A, "A")])
    )
    matched, score = vlm_service.match_bank_question(SHARED_STEM, OPTIONS_A)
    assert matched is not None and matched.id == "q-one"
    assert score == 1.0


def test_same_stem_resolved_by_options(colliding_bank: None) -> None:
    """★ 同题干两道题时，靠选项挑对那一道。"""
    matched, _ = vlm_service.match_bank_question(SHARED_STEM, OPTIONS_A)
    assert matched is not None and matched.id == "q-alpha"
    assert matched.answer == "A"

    matched_b, _ = vlm_service.match_bank_question(SHARED_STEM, OPTIONS_B)
    assert matched_b is not None and matched_b.id == "q-beta"
    assert matched_b.answer == "B", "学生做的是第二道，就该用第二道的答案"


def test_same_stem_with_unrecognisable_options_gets_no_endorsement(
    colliding_bank: None,
) -> None:
    """★ 判不出是哪一道时**不给题库背书**。

    拿错答案去判分比"不判"严重得多 —— 学生会看到"我明明选对了却判我错"。
    """
    matched, _ = vlm_service.match_bank_question(SHARED_STEM, {"A": "??", "B": "??"})
    assert matched is None, "分不清是哪道题却给了题库背书"

    matched_none, _ = vlm_service.match_bank_question(SHARED_STEM, None)
    assert matched_none is None, "没有选项就更分不清"


def test_student_answering_the_second_question_is_not_marked_wrong(
    colliding_bank: None,
) -> None:
    """★ 评审给的那个场景：学生按第二题选 B，不能被当成第一题判错。"""
    payload = {
        "questions": [
            {
                "question_number": "1",
                "stem": SHARED_STEM,
                "options": dict(OPTIONS_B),
                "student_answer": "B",
                "answer": "B",
                "correctness": "correct",
            }
        ]
    }
    questions = vlm_service.raw_questions_from_payload(payload)
    assert len(questions) == 1
    question = questions[0]

    assert question.bank_question_id == "q-beta", (
        f"匹配到了 {question.bank_question_id}，应当是选项一致的那一道"
    )
    assert question.correct_answer == "B"
    assert question.correctness == "correct", (
        f"学生按第二题选 B 是对的，却被判成 {question.correctness}"
    )


def test_fuzzy_match_with_mismatched_options_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """题干像、选项明显不是同一道题 → 同样不背书。"""
    near = "已知函数 f(x) = x^2，则下列说法正确的一项是"  # 只差两个字
    monkeypatch.setattr(
        vlm_service,
        "get_bank",
        lambda: _FakeBank([_bank_question("q-near", OPTIONS_A, "A")]),
    )
    matched, score = vlm_service.match_bank_question(near, OPTIONS_A)
    assert score >= vlm_service.BANK_MATCH_THRESHOLD
    assert matched is not None, "选项一致时模糊命中仍应采信"

    refused, _ = vlm_service.match_bank_question(near, OPTIONS_B)
    assert refused is None, "题干像但选项完全不同，不该采用题库答案"


# ---------------------------------------------------------------------------
# P2：复核不能把 unanswered 改写成 unknown
# ---------------------------------------------------------------------------

class _StubLlm:
    configured = True
    backup_configured = False


def _unanswered(**overrides: Any) -> RawQuestion:
    base: dict[str, Any] = {
        "question_number": "1",
        "stem": "已知 f(x)=x^2，求 f'(1)。",
        "options": dict(OPTIONS_A),
        "student_answer": None,
        "correct_answer": "C",
        "correctness": "unanswered",
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


def test_mark_not_scored_keeps_unanswered() -> None:
    question = _unanswered()
    vlm_service._mark_not_scored(question, possible="C", source="recognition")
    assert question.correctness == "unanswered", "「你没做」被改写成「我没算准」了"
    assert question.possible_answer == "C"


def test_mark_not_scored_still_marks_answered_ones_unknown() -> None:
    question = _unanswered(student_answer="A", correctness="wrong")
    vlm_service._mark_not_scored(question, possible="C", source="recognition")
    assert question.correctness == "unknown"


@pytest.mark.asyncio
async def test_solver_failure_keeps_unanswered(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _never(stem, options, llm, model):
        return None

    monkeypatch.setattr(vlm_service, "_solve_independently", _never)
    questions = [_unanswered()]
    await vlm_service.verify_answers(
        questions, client=_StubLlm(), exclude_models={"deepseek-flash"}
    )
    assert questions[0].correctness == "unanswered"


@pytest.mark.asyncio
async def test_disagreement_keeps_unanswered(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _solver(stem, options, llm, model):
        return "D"

    monkeypatch.setattr(vlm_service, "_solve_independently", _solver)
    questions = [_unanswered()]
    await vlm_service.verify_answers(
        questions, client=_StubLlm(), exclude_models={"deepseek-flash"}
    )
    assert questions[0].correctness == "unanswered"
    assert questions[0].possible_answer == "D"


@pytest.mark.asyncio
async def test_over_cap_keeps_unanswered(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _solver(stem, options, llm, model):
        return "C"

    monkeypatch.setattr(vlm_service, "_solve_independently", _solver)
    cap = vlm_service.MAX_VERIFY_PER_ANALYSIS
    questions = [
        _unanswered(
            question_number=str(i + 1),
            stem=f"第 {i + 1} 题：已知 f(x)=x^{i}，求 f'(1)。",
        )
        for i in range(cap + 2)
    ]
    await vlm_service.verify_answers(
        questions, client=_StubLlm(), exclude_models={"deepseek-flash"}
    )
    for question in questions[cap:]:
        assert question.correctness == "unanswered", (
            f"第 {question.question_number} 题超出复核上限后，"
            f"「未作答」被改成了 {question.correctness}"
        )


def test_unanswered_and_unknown_have_different_meaning() -> None:
    """两种"不计分"必须能被前端区分开。"""
    answered = _unanswered(student_answer="A", correctness="wrong")
    vlm_service._mark_not_scored(answered, possible="C", source="recognition")
    untouched = _unanswered()

    assert answered.correctness != untouched.correctness
    assert {answered.correctness, untouched.correctness} == {"unknown", "unanswered"}
