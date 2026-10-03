"""`unanswered` 状态、`possible_answer`、`retrying` 阶段，以及请求耗时日志。

这一批改动都围绕同一件事：**把"没法算分"的几种情况分清楚**。

  correct / wrong / partial   算分
  unanswered                  学生没作答 —— 不计分，但要让前端能说"这题你没做"
  unknown                     复核没通过 —— 不计分，但给出「可能答案」作参考
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db
from app.services import homework_service, vlm_service
from app.services.vlm_service import RawQuestion

from .conftest import FIXTURE_IMAGE

OPTIONS = {"A": "1", "B": "2", "C": "3", "D": "4"}


class _StubLlm:
    """测试用的假客户端。

    测试环境是 `FORCE_MOCK_LLM=true`，真实客户端的 `configured` 为 False，
    `verify_answers` 会在第一行就返回 —— 那样根本测不到校验逻辑。
    """

    configured = True
    backup_configured = False


def _raw(**overrides) -> RawQuestion:
    base = {
        "question_number": "1",
        "stem": "已知 f(x)=x^2，求 f'(1)。",
        "options": dict(OPTIONS),
        "student_answer": "A",
        "correct_answer": "C",
        "correctness": "wrong",
        "knowledge_point_ids": ["math.derivative.monotonicity"],
        "tags": ["利用导数判断函数单调性与单调区间"],
        "error_type": None,
        "diagnosis": "",
        "explanation": None,
        "confidence": 0.9,
        "difficulty": 0.5,
    }
    base.update(overrides)
    return RawQuestion(**base)


# ---------------------------------------------------------------------------
# unanswered 与 unknown 是两个不同的状态
# ---------------------------------------------------------------------------

def test_student_not_answered_is_unanswered_not_unknown() -> None:
    assert vlm_service._clean_correctness("wrong", None, "C") == "unanswered"


def test_unanswered_survives_the_payload_pipeline() -> None:
    payload = {
        "questions": [
            {
                "question_number": "1",
                "stem": "已知 f(x)=x^2，求 f'(1)。",
                "options": dict(OPTIONS),
                "student_answer": None,  # 学生没作答
                "answer": "C",
                "correctness": "unknown",  # 模型还可能照着旧 prompt 填 unknown
            }
        ]
    }
    questions = vlm_service.raw_questions_from_payload(payload)
    assert len(questions) == 1
    # 判定以服务端为准：没作答就是 unanswered，不采信模型的 unknown
    assert questions[0].correctness == "unanswered"
    assert questions[0].correct_answer == "C"


def test_prompt_tells_the_model_to_use_unanswered() -> None:
    """prompt 里不能再写「学生未作答填 unknown」，否则模型和我们会打架。"""
    prompt = vlm_service.build_prompt()
    assert "unanswered" in prompt
    assert "学生未作答填 unknown" not in prompt


def test_unanswered_and_unknown_are_both_excluded_from_mastery() -> None:
    assert "unanswered" in homework_service.NO_MASTERY_IMPACT
    assert "unknown" in homework_service.NO_MASTERY_IMPACT
    assert "correct" not in homework_service.NO_MASTERY_IMPACT
    assert "wrong" not in homework_service.NO_MASTERY_IMPACT


# ---------------------------------------------------------------------------
# unanswered 不计入掌握度（端到端）
# ---------------------------------------------------------------------------

def _upload_with(
    client: TestClient, headers: dict[str, str], monkeypatch, question: dict
) -> dict:
    from app.services import vlm_service as vs
    from app.services.vlm_service import VlmOutcome

    async def _analyze(images, **kwargs):
        outcome = VlmOutcome(generated_by="fake-vlm", model="fake")
        outcome.questions.append(RawQuestion(**question))
        return outcome

    monkeypatch.setattr(vs, "analyze_images", _analyze)
    with FIXTURE_IMAGE.open("rb") as handle:
        created = client.post(
            "/api/v1/homework/analyses",
            headers=headers,
            files={"images": ("page.png", handle, "image/png")},
            data={"subject": "mathematics"},
        )
    return client.get(
        f"/api/v1/homework/analyses/{created.json()['analysis_id']}", headers=headers
    ).json()


def test_unanswered_question_does_not_touch_mastery(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """★ 学生没作答的题，**完全不能影响掌握度**。"""
    before = client.get("/api/v1/knowledge/mastery-overview", headers=auth_headers).json()

    detail = _upload_with(
        client,
        auth_headers,
        monkeypatch,
        {
            "question_number": "1",
            "stem": "已知 f(x)=x^2，求 f'(1)。",
            "options": dict(OPTIONS),
            "student_answer": None,
            "correct_answer": "C",
            "correctness": "unanswered",
            "knowledge_point_ids": ["math.derivative.monotonicity"],
            "tags": ["利用导数判断函数单调性与单调区间"],
            "error_type": None,
            "diagnosis": "",
            "explanation": None,
            "confidence": 0.95,
            "difficulty": 0.5,
        },
    )

    assert detail["status"] == "completed"
    assert detail["unanswered_count"] == 1
    assert detail["unknown_count"] == 0
    assert detail["question_results"][0]["correctness"] == "unanswered"
    assert detail["knowledge_changes"] == [], "未作答不该产生掌握度变化"

    after = client.get("/api/v1/knowledge/mastery-overview", headers=auth_headers).json()
    assert after["score"] == before["score"], "未作答不该动综合掌握度"


def test_unanswered_question_is_not_added_to_wrong_questions(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict, monkeypatch
) -> None:
    before = db.count_docs("wrong_questions", "user_id = ?", [demo_user["user_id"]])
    detail = _upload_with(
        client,
        auth_headers,
        monkeypatch,
        {
            "question_number": "1",
            "stem": "已知 f(x)=x^2，求 f'(1)。",
            "options": dict(OPTIONS),
            "student_answer": None,
            "correct_answer": "C",
            "correctness": "unanswered",
            "knowledge_point_ids": ["math.derivative.monotonicity"],
            "tags": ["利用导数判断函数单调性与单调区间"],
            "error_type": None,
            "diagnosis": "",
            "explanation": None,
            "confidence": 0.95,
            "difficulty": 0.5,
        },
    )
    assert detail["status"] == "completed"
    after = db.count_docs("wrong_questions", "user_id = ?", [demo_user["user_id"]])
    assert after == before, "未作答不该进错题本"


# ---------------------------------------------------------------------------
# possible_answer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unverified_answer_keeps_a_possible_answer(monkeypatch) -> None:
    """★ 复核失败时不该把信息也丢掉 —— 正确答案明明就在手里。"""
    from app.services import vlm_service as vs

    async def _never(stem, options, llm, model):
        return None  # 独立求解拿不到结果

    monkeypatch.setattr(vs, "_solve_independently", _never)
    questions = [_raw(correct_answer="C")]
    await vs.verify_answers(questions, client=_StubLlm(), exclude_models={"deepseek-flash"})

    question = questions[0]
    assert question.correctness == "unknown"
    assert question.correct_answer is None, "没复核过的答案不能拿去算分"
    assert question.possible_answer == "C", "但要把可能答案留下来"
    assert question.possible_answer_source == "recognition"


@pytest.mark.asyncio
async def test_disagreement_prefers_the_independent_solver(monkeypatch) -> None:
    """两个模型各执一词时，以**独立求解**的答案为准 —— 它没看错图的风险。"""
    from app.services import vlm_service as vs

    async def _solver(stem, options, llm, model):
        return "D"

    monkeypatch.setattr(vs, "_solve_independently", _solver)
    questions = [_raw(correct_answer="B")]
    await vs.verify_answers(questions, client=_StubLlm(), exclude_models={"deepseek-flash"})

    question = questions[0]
    assert question.correctness == "unknown"
    assert question.correct_answer is None
    assert question.possible_answer == "D"
    assert question.possible_answer_source != "recognition"


@pytest.mark.asyncio
async def test_agreement_clears_possible_answer(monkeypatch) -> None:
    from app.services import vlm_service as vs

    async def _solver(stem, options, llm, model):
        return "C"

    monkeypatch.setattr(vs, "_solve_independently", _solver)
    questions = [_raw(correct_answer="C")]
    await vs.verify_answers(questions, client=_StubLlm(), exclude_models={"deepseek-flash"})

    assert questions[0].correctness == "wrong"
    assert questions[0].correct_answer == "C"
    assert questions[0].possible_answer is None


@pytest.mark.asyncio
async def test_unanswered_questions_are_still_verified(monkeypatch) -> None:
    """原来「没作答就不校验」的过滤已删除 —— 未作答的题也要复核正确答案。"""
    from app.services import vlm_service as vs

    seen: list[str] = []

    async def _solver(stem, options, llm, model):
        seen.append(stem)
        return "C"

    monkeypatch.setattr(vs, "_solve_independently", _solver)
    questions = [_raw(question_number="7", student_answer=None, correct_answer="C")]
    await vs.verify_answers(questions, client=_StubLlm(), exclude_models={"deepseek-flash"})
    assert len(seen) == 1 and "f(x)" in seen[0], seen


# ---------------------------------------------------------------------------
# retrying 阶段
# ---------------------------------------------------------------------------

def test_retrying_is_a_distinct_stage_state() -> None:
    stages = homework_service._stages(1, retrying=True)
    assert stages[1]["state"] == "retrying"
    assert stages[0]["state"] == "done"
    assert stages[2]["state"] == "pending"


def test_failed_still_wins_over_retrying() -> None:
    stages = homework_service._stages(1, failed=True, retrying=True)
    assert stages[1]["state"] == "failed"


def test_progress_carries_a_human_readable_retry_note() -> None:
    progress = homework_service._progress(1, 0.25, retrying=True, retry_note="换模型")
    assert progress["retrying"] is True
    assert progress["retry_note"] == "换模型"
    assert progress["current_stage_key"] == "questions_detected"


def test_normal_progress_has_no_retry_fields() -> None:
    progress = homework_service._progress(1, 0.25)
    assert "retrying" not in progress
    assert "retry_note" not in progress


# ---------------------------------------------------------------------------
# 请求耗时
# ---------------------------------------------------------------------------

def test_every_response_reports_its_duration(client: TestClient) -> None:
    response = client.get("/health")
    assert "X-Response-Time-Ms" in response.headers
    assert int(response.headers["X-Response-Time-Ms"]) >= 0
    assert response.headers.get("X-Request-ID")
