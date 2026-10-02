"""VLM 流水线的并行与降级测试。

契约要求上传的图片允许并行处理；同时 JSON 不合法的重试次数是
「主模型 5 次 + 备选模型 5 次」，而不是总共 5 次。
"""

from __future__ import annotations

import asyncio
import base64
import copy

import pytest

from app.config import get_settings
from app.question_bank import get_bank
from app.services import vlm_service
from app.services.llm import LlmClient, LlmReply, LlmUnavailable
from app.services.vlm_service import JSON_ATTEMPTS_PER_MODEL, analyze_images

# 用真实题库里的题目，避免走"未命中题库"的分支
BANK_QUESTION = get_bank().get("math.derivative.monotonicity.0009")
assert BANK_QUESTION is not None

VLM_PAYLOAD = {
    "questions": [
        {
            "question_number": "17",
            "stem": BANK_QUESTION.stem,
            "options": dict(BANK_QUESTION.options),
            "student_answer": None,
            "answer": BANK_QUESTION.answer,
            "correctness": "unknown",
            "knowledge_point_ids": ["math.derivative.monotonicity"],
            "error_type": None,
            "diagnosis": "测试用",
            "confidence": 0.9,
            "difficulty": 3,
        }
    ]
}


def _image_index(messages) -> int | None:
    """从带图消息里还原出这张图是第几张（测试用的图把序号塞在最后一个字节）。"""
    content = messages[0]["content"]
    if not isinstance(content, list):
        return None
    url = content[1]["image_url"]["url"]
    return base64.b64decode(url.split(",", 1)[1])[-1]


class FakeVlm(LlmClient):
    """记录并发度与调用参数的假客户端。"""

    def __init__(
        self,
        *,
        failing_models: set[str] | None = None,
        failing_images: set[int] | None = None,
        payload: dict | None = None,
        delay: float = 0.05,
    ) -> None:
        super().__init__()
        self.failing_models = failing_models or set()
        self.failing_images = failing_images or set()
        self.payload = payload if payload is not None else VLM_PAYLOAD
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.models_called: list[str] = []
        self.attempts_passed: list[int | None] = []

    @property
    def configured(self) -> bool:  # type: ignore[override]
        return True

    async def complete_json(self, messages, **kwargs):  # type: ignore[override]
        model = kwargs.get("model")
        self.models_called.append(model)
        self.attempts_passed.append(kwargs.get("attempts"))

        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)

            index = _image_index(messages)
            if index is not None:
                if model in self.failing_models or index in self.failing_images:
                    raise LlmUnavailable(f"模拟失败: model={model} image={index}")
                return copy.deepcopy(self.payload), LlmReply(
                    text="", model=model or "stub", provider="stub", latency_ms=1
                )

            return {"answer": "C"}, LlmReply(
                text="", model=model or "stub", provider="stub", latency_ms=1
            )
        finally:
            self.active -= 1


def _images(count: int) -> list[tuple[bytes, str]]:
    return [(b"\x89PNG fake " + bytes([i]), "image/png") for i in range(count)]


def test_images_are_processed_in_parallel() -> None:
    client = FakeVlm(delay=0.08)

    async def run() -> None:
        await analyze_images(_images(3), client=client)

    asyncio.run(run())

    assert len(client.models_called) == 3
    assert client.max_active >= 2, "3 张图片应当并发处理，而不是串行"


def test_each_model_gets_five_json_attempts() -> None:
    client = FakeVlm()

    async def run() -> None:
        await analyze_images(_images(1), client=client)

    asyncio.run(run())
    assert client.attempts_passed == [JSON_ATTEMPTS_PER_MODEL]
    assert JSON_ATTEMPTS_PER_MODEL == 5


def test_falls_back_to_secondary_model() -> None:
    settings = get_settings()
    client = FakeVlm(failing_models={settings.vlm_model})

    async def run():
        return await analyze_images(_images(1), client=client)

    outcome = asyncio.run(run())

    assert settings.vlm_fallback_model in client.models_called
    assert client.models_called[0] == settings.vlm_model
    assert any("降级" in w for w in outcome.warnings)
    assert outcome.model == settings.vlm_fallback_model


def test_primary_model_is_tried_five_times_before_fallback() -> None:
    """主模型失败时，两次调用都应带上 5 次尝试额度。"""
    settings = get_settings()
    client = FakeVlm(failing_models={settings.vlm_model})

    async def run() -> None:
        await analyze_images(_images(1), client=client)

    asyncio.run(run())
    assert client.attempts_passed == [JSON_ATTEMPTS_PER_MODEL, JSON_ATTEMPTS_PER_MODEL]
    assert client.models_called == [settings.vlm_model, settings.vlm_fallback_model]


def test_all_models_failing_raises() -> None:
    settings = get_settings()
    client = FakeVlm(failing_models={settings.vlm_model, settings.vlm_fallback_model})

    async def run() -> None:
        await analyze_images(_images(1), client=client)

    with pytest.raises(LlmUnavailable):
        asyncio.run(run())


def test_partial_failure_keeps_the_good_images() -> None:
    """3 张里坏 2 张，不该整单失败 —— 能识别的部分要保住。"""
    client = FakeVlm(failing_images={0, 2})

    async def run():
        return await analyze_images(_images(3), client=client)

    outcome = asyncio.run(run())
    assert len(outcome.questions) == 1
    assert any("识别失败" in w for w in outcome.warnings)


def test_bank_matched_question_skips_second_opinion() -> None:
    """命中题库的题可信，不该再花一次模型调用去二次求解。"""
    client = FakeVlm()

    async def run():
        return await analyze_images(_images(1), client=client)

    outcome = asyncio.run(run())
    assert outcome.questions[0].bank_question_id == BANK_QUESTION.id
    # 只应有 1 次（认图）调用，没有额外的求解调用
    assert len(client.models_called) == 1


def test_unmatched_question_triggers_second_opinion() -> None:
    """没命中题库、且学生作答了 → 必须走独立求解校验。"""
    payload = copy.deepcopy(VLM_PAYLOAD)
    payload["questions"][0]["stem"] = "一道题库里没有的题：求 f(x) = x^2 的导数。"
    payload["questions"][0]["student_answer"] = "A"
    payload["questions"][0]["knowledge_point_ids"] = ["math.derivative.basic"]

    client = FakeVlm(payload=payload)

    async def run():
        return await analyze_images(_images(1), client=client)

    asyncio.run(run())
    # 1 次认图 + 1 次独立求解
    assert len(client.models_called) == 2


def test_second_opinion_runs_in_parallel() -> None:
    """多道未命中题库的题，二次校验应并发。"""
    payload = {"questions": []}
    for index in range(4):
        payload["questions"].append(
            {
                "question_number": str(index + 1),
                "stem": f"题库里没有的第 {index} 题：求 f(x) = x^{index + 2} 的导数。",
                "options": {"A": "1", "B": "2", "C": "C", "D": "4"},
                "student_answer": "A",
                "answer": "C",
                "correctness": "wrong",
                "knowledge_point_ids": ["math.derivative.basic"],
                "error_type": "procedural",
                "diagnosis": "测试",
                "confidence": 0.9,
                "difficulty": 2,
            }
        )

    client = FakeVlm(payload=payload, delay=0.06)

    async def run() -> None:
        await analyze_images(_images(1), client=client)

    asyncio.run(run())
    # 1 次认图 + 4 次求解；若串行 max_active 会一直是 1
    assert len(client.models_called) == 5
    assert client.max_active >= 2, "二次求解应当并发"
