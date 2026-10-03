"""真实试卷（一页 9 题）失败后的三项修复。

线上事故：一页 9 道题的真实试卷照片，整页识别失败、**一题都没批改出来**，
白等 369 秒。三个独立问题：

  P0  视觉调用要模型一次写完 9 道题的解题步骤，输出超过 max_tokens 上限
  P1  顶到最大预算仍被截断时还在重试，每次都被同样切断
  P2  进度卡片在 369 秒里一直停在 25%（回调只在降级时触发）
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import pytest

from app.services import vlm_service
from app.services.llm import MAX_OUTPUT_TOKENS, LlmUnavailable, LlmReply

# ---------------------------------------------------------------------------
# P0：解析改成单独一步 —— 单次请求的输出长度不再随题目数增长
# ---------------------------------------------------------------------------


def test_recognition_prompt_no_longer_asks_for_explanations() -> None:
    """★ 视觉调用不该再要求写解析 —— 那是整页失败的根因。

    一页 9 道题的中文解题步骤实测超过 16000 token，整个请求被切断，
    连带题干、选项、判定全部拿不到。**一道题写不出来，整页都没了。**
    """
    prompt = vlm_service.build_prompt("mathematics", None)
    assert "explanation" not in prompt, "识别提示词里不该再要 explanation"
    assert "不要输出解析" in prompt, "要明确告诉模型不要写解析"
    # 但判定需要的字段一个都不能少
    for field in (
        "question_number",
        "stem",
        "options",
        "student_answer",
        "answer",
        "correctness",
        "knowledge_point_ids",
        "tags",
        "error_type",
        "diagnosis",
        "confidence",
        "difficulty",
    ):
        assert field in prompt, f"识别提示词少了 {field}"


def test_explain_prompt_is_per_question() -> None:
    """解析提示词只围绕**一道题**，所以输出长度与页面上有几道题无关。"""
    prompt = vlm_service.EXPLAIN_PROMPT
    assert "{stem}" in prompt and "{options}" in prompt and "{answer}" in prompt
    assert "explanation" in prompt and "diagnosis" in prompt


class _ExplainSpy:
    """记录解析调用的假客户端。"""

    def __init__(self, *, reply: dict[str, Any] | None = None, fail: bool = False):
        self.configured = True
        self.calls: list[dict[str, Any]] = []
        self.reply = reply if reply is not None else {
            "diagnosis": "把区间写反了",
            "explanation": "f'(x)=3x(x-2)>0 得 x<0 或 x>2。",
        }
        self.fail = fail

    async def complete_json(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self.fail:
            raise LlmUnavailable("模拟失败")
        return copy.deepcopy(self.reply), LlmReply(
            text="", model="stub", provider="stub", latency_ms=1
        )


def _q(number: str, *, correctness: str = "wrong", **over: Any):
    base = dict(
        question_number=number,
        stem=f"第 {number} 题：求 f(x)=x^2 的导数。",
        options={"A": "1", "B": "2x", "C": "3", "D": "4"},
        student_answer="A",
        correct_answer="B",
        correctness=correctness,
        knowledge_point_ids=["math.derivative.monotonicity"],
        tags=[],
        error_type="procedural",
        diagnosis="",
        explanation=None,
        confidence=0.9,
        difficulty=2.0,
    )
    base.update(over)
    return vlm_service.RawQuestion(**base)


def test_explain_fills_explanation_for_wrong_questions() -> None:
    spy = _ExplainSpy()
    questions = [_q("1"), _q("2")]
    warnings = asyncio.run(vlm_service.explain_questions(questions, client=spy))

    assert warnings == []
    assert len(spy.calls) == 2, "每题一个请求"
    for question in questions:
        assert question.explanation == "f'(x)=3x(x-2)>0 得 x<0 或 x>2。"
        assert question.diagnosis == "把区间写反了"
    # 每次请求只带一道题，且**不带图**（纯文本，便宜得多）
    for call in spy.calls:
        assert call.get("vision") is not True, "解析不该重传图片"
        assert call["max_tokens"] <= 2000


def test_explain_skips_correct_and_unknown_questions() -> None:
    """答对的题不需要解析；unknown 的题答案没确认，写了可能是错的。"""
    spy = _ExplainSpy()
    questions = [
        _q("1", correctness="correct"),
        _q("2", correctness="unknown", correct_answer=None),
        _q("3", correctness="unanswered", correct_answer=None),
        _q("4", correctness="wrong"),
    ]
    asyncio.run(vlm_service.explain_questions(questions, client=spy))

    assert len(spy.calls) == 1, "只有第 4 题该被补解析"
    assert questions[0].explanation is None
    assert questions[1].explanation is None
    assert questions[3].explanation is not None


def test_explain_failure_does_not_break_the_analysis() -> None:
    """解析补不上不该让整页批改失败 —— 判定和统计都是好的。"""
    spy = _ExplainSpy(fail=True)
    questions = [_q("1")]
    warnings = asyncio.run(vlm_service.explain_questions(questions, client=spy))

    assert questions[0].explanation is None
    assert questions[0].correctness == "wrong", "判定不受影响"
    assert any("解析生成失败" in w for w in warnings)


def test_explain_runs_in_parallel() -> None:
    """9 道题串行等 9 次太慢，必须并发。"""
    active = 0
    peak = 0

    class _Slow(_ExplainSpy):
        async def complete_json(self, messages, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.03)
                return copy.deepcopy(self.reply), LlmReply(
                    text="", model="stub", provider="stub", latency_ms=1
                )
            finally:
                active -= 1

    asyncio.run(
        vlm_service.explain_questions([_q(str(i)) for i in range(9)], client=_Slow())
    )
    assert peak >= 2, "解析生成应当并发"


# ---------------------------------------------------------------------------
# P1：顶到最大预算仍被截断时不要再重试
# ---------------------------------------------------------------------------


class _AlwaysTruncated:
    """每次都返回被 max_tokens 截断的响应。"""

    configured = True
    backup_configured = False

    def __init__(self) -> None:
        self.attempts = 0
        self.budgets: list[int] = []

    async def complete(self, messages, *, max_tokens=2048, **kwargs):
        self.attempts += 1
        self.budgets.append(max_tokens)
        return LlmReply(
            text='{"questions":[{"stem":"写到一半',
            model="stub",
            provider="stub",
            latency_ms=1,
            raw={"choices": [{"finish_reason": "length"}]},
        )


def test_truncation_at_max_budget_stops_immediately() -> None:
    """★ 顶到上限还被截断 → 立刻放弃，不要试满 5 次。

    线上实测：3 个模型各重试到底，白等 369 秒才失败，
    而这个结果从第一次截断就已经注定了。
    """
    from app.services.llm import LlmClient

    class _Stub(LlmClient):
        def __init__(self) -> None:
            super().__init__()
            self.inner = _AlwaysTruncated()

        async def complete(self, messages, **kwargs):
            return await self.inner.complete(messages, **kwargs)

    stub = _Stub()
    with pytest.raises(LlmUnavailable) as exc:
        asyncio.run(
            stub.complete_json(
                [{"role": "user", "content": "test"}],
                model="stub",
                max_tokens=4000,
                attempts=5,
            )
        )

    # 4000 → 8000 → 16000，到顶后再试也是白试，所以总共 3 次
    assert stub.inner.attempts == 3, (
        f"顶到最大预算后应当立刻停，实际调用了 {stub.inner.attempts} 次"
    )
    assert max(stub.inner.budgets) == MAX_OUTPUT_TOKENS
    assert "截断" in str(exc.value)


def test_consecutive_invalid_json_still_retries() -> None:
    """非截断的坏 JSON 仍然要重试 —— 那种重试是有用的。"""

    class _BadJson:
        configured = True

        def __init__(self) -> None:
            self.attempts = 0

        async def complete(self, messages, *, max_tokens=2048, **kwargs):
            self.attempts += 1
            return LlmReply(
                text="这不是 JSON",
                model="stub",
                provider="stub",
                latency_ms=1,
                raw={"choices": [{"finish_reason": "stop"}]},
            )

    from app.services.llm import LlmClient

    class _Stub(LlmClient):
        def __init__(self) -> None:
            super().__init__()
            self.inner = _BadJson()

        async def complete(self, messages, **kwargs):
            return await self.inner.complete(messages, **kwargs)

    stub = _Stub()
    with pytest.raises(LlmUnavailable):
        asyncio.run(
            stub.complete_json(
                [{"role": "user", "content": "test"}], model="stub", attempts=5
            )
        )
    assert stub.inner.attempts == 5, "坏 JSON 应当试满次数"


# ---------------------------------------------------------------------------
# P2：进度回调从第一个模型就开始发
# ---------------------------------------------------------------------------


class _RetrySpy:
    """第一次调用就失败，逼出降级。"""

    def __init__(self) -> None:
        self.configured = True
        self.backup_configured = True

    async def complete_json(self, messages, **kwargs):
        raise LlmUnavailable("模拟失败")


def _images(count: int = 1) -> list[tuple[bytes, str]]:
    return [(b"\x89PNG fake", "image/png") for _ in range(count)]


def test_progress_callback_fires_for_the_first_model_too(monkeypatch) -> None:
    """★ 回调必须从链上**第一个**模型就开始发。

    以前只在"降级到下一个模型"时触发，于是第一个模型的每次尝试期间
    前端收不到任何东西 —— 进度卡片看起来卡死。
    """
    from app.config import get_settings

    settings = get_settings()
    chain = vlm_service.recognition_models(settings, _RetrySpy())
    assert len(chain) >= 3, "这个测试需要至少 3 个模型的链"

    seen: list[dict[str, Any]] = []

    class _Fails:
        configured = True
        backup_configured = True

        async def complete_json(self, messages, **kwargs):
            raise LlmUnavailable("模拟失败")

    with pytest.raises(LlmUnavailable):
        asyncio.run(
            vlm_service.analyze_images(
                _images(1), client=_Fails(), on_retry=seen.append
            )
        )

    # 每个模型开始前都回调一次
    assert len(seen) == len(chain), f"应当每个模型回调一次，实际 {len(seen)}"
    assert seen[0]["model_index"] == 0
    assert seen[0]["failed_model"] is None, "第一个模型没有'上一个失败者'"
    assert seen[0]["model"] == chain[0]
    assert seen[1]["failed_model"] == chain[0], "第二个模型的失败者是链首"
    assert seen[0]["model_total"] == len(chain)


def test_first_model_progress_note_says_identifying_not_retrying() -> None:
    """还在用第一个模型时是"正在识别"，**不是**"正在重试"。"""
    from app.schemas import AnalysisProgress
    from app.services import homework_service

    identifying = homework_service._progress(
        1, 0.25, retrying=False, retry_note="第 1 张：正在用 Qwen 识别（模型 1/3）"
    )
    # `_progress` 内部只在重试时带这个键；响应模型会补默认 False
    assert identifying.get("retrying") is not True
    assert "正在用" in identifying["retry_note"]
    assert AnalysisProgress(**identifying).retrying is False

    degraded = homework_service._progress(
        1,
        0.25,
        retrying=True,
        retry_note="第 1 张：Qwen 未成功，正在用 X 重试（模型 2/3）",
    )
    assert degraded["retrying"] is True
    assert "未成功" in degraded["retry_note"]
    assert AnalysisProgress(**degraded).retrying is True
