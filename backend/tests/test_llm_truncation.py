"""输出被 `max_tokens` 截断时的处理。

真实事故：前端上传一张有 9 道题的试卷，VLM 要给每题写 diagnosis + explanation，
3000 token 在中途被切断 → JSON 非法。而 `complete_json` 那时只会**原样重试**，
每次都得到同样被切断的输出，5 次全废（每次约 110 秒），
然后换备选模型再来 5 次 —— 白等 9 分钟，最后整体失败。

`finish_reason == "length"` 是明确信号：必须**放大预算**，而不是重发同一个请求。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.llm import (
    MAX_OUTPUT_TOKENS,
    JSON_RETRY_HINT,
    LlmClient,
    LlmReply,
    LlmUnavailable,
    _finish_reason,
)


def _reply(text: str, *, finish_reason: str | None = "stop") -> LlmReply:
    raw: dict[str, Any] = {}
    if finish_reason is not None:
        raw = {"choices": [{"finish_reason": finish_reason}]}
    return LlmReply(text=text, model="fake", provider="fake", latency_ms=1, raw=raw)


class _FakeClient(LlmClient):
    """记录每次调用的 max_tokens，并按剧本返回。"""

    def __init__(self, script: list[LlmReply]) -> None:
        self.script = script
        self.calls: list[int] = []

    async def complete(self, messages, **kwargs):  # type: ignore[override]
        self.calls.append(kwargs.get("max_tokens"))
        return self.script.pop(0)


GOOD = '{"questions": [{"question_number": "1"}]}'
CUT = '{"questions": [{"question_number": "1", "stem": "被截断的题'


# ---------------------------------------------------------------------------
# finish_reason 解析
# ---------------------------------------------------------------------------

def test_finish_reason_is_read_from_raw() -> None:
    assert _finish_reason(_reply("x", finish_reason="length")) == "length"
    assert _finish_reason(_reply("x", finish_reason="stop")) == "stop"
    assert _finish_reason(_reply("x", finish_reason=None)) is None
    assert _finish_reason(LlmReply(text="x", model="m", provider="p", latency_ms=1)) is None


# ---------------------------------------------------------------------------
# 截断 → 放大预算，而不是原样重试
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_truncation_escalates_max_tokens_instead_of_blind_retry() -> None:
    client = _FakeClient([_reply(CUT, finish_reason="length"), _reply(GOOD)])
    parsed, _ = await client.complete_json(
        [{"role": "user", "content": "x"}], max_tokens=1000, attempts=5
    )

    assert parsed["questions"]
    assert len(client.calls) == 2
    assert client.calls[0] == 1000
    assert client.calls[1] == 2000, "截断后必须放大预算，而不是重发 1000"


@pytest.mark.asyncio
async def test_max_tokens_is_capped() -> None:
    """连续截断时预算翻倍但有上限，不能无限膨胀。"""
    # 1000 → 2000 → 4000 → 8000 → 16000（到顶）→ 这次成功
    client = _FakeClient(
        [_reply(CUT, finish_reason="length") for _ in range(4)] + [_reply(GOOD)]
    )

    parsed, _ = await client.complete_json(
        [{"role": "user", "content": "x"}], max_tokens=1000, attempts=5
    )
    assert parsed["questions"]
    assert client.calls == [1000, 2000, 4000, 8000, MAX_OUTPUT_TOKENS]
    assert max(client.calls) == MAX_OUTPUT_TOKENS


@pytest.mark.asyncio
async def test_persistent_truncation_raises_a_clear_error() -> None:
    """一直是截断 → 报错必须说清是截断，而不是笼统的「JSON 非法」。"""
    client = _FakeClient([_reply(CUT, finish_reason="length") for _ in range(4)])

    with pytest.raises(LlmUnavailable) as excinfo:
        await client.complete_json(
            [{"role": "user", "content": "x"}], max_tokens=MAX_OUTPUT_TOKENS
        )

    message = str(excinfo.value)
    assert "截断" in message
    assert "max_tokens" in message


# ---------------------------------------------------------------------------
# 不是截断的坏 JSON → 保持原来的「加提示重试」路径
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_json_still_uses_the_retry_hint() -> None:
    client = _FakeClient([_reply("这不是 JSON"), _reply(GOOD)])
    parsed, _ = await client.complete_json(
        [{"role": "user", "content": "x"}], max_tokens=999, attempts=3
    )

    assert parsed["questions"]
    assert client.calls == [999, 999], "非截断的重试不该改预算"


@pytest.mark.asyncio
async def test_malformed_json_error_message_is_unchanged() -> None:
    client = _FakeClient([_reply("不是 JSON") for _ in range(2)])
    with pytest.raises(LlmUnavailable) as excinfo:
        await client.complete_json([{"role": "user", "content": "x"}], attempts=2)
    assert "未返回合法 JSON" in str(excinfo.value)


def test_retry_hint_mentions_json_only() -> None:
    """健全性检查：重试提示本身没有被误改。"""
    assert "JSON" in JSON_RETRY_HINT
