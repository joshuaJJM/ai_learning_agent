"""模型输出解析与重试的测试。

重点覆盖一类真实坏输出：模型在中文正文里把中文引号打成了 ASCII 的 `"`，
导致 JSON 字符串提前闭合。这类问题不修的话，整张试卷的分析会直接失败。
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.llm import LlmClient, LlmReply, LlmUnavailable, extract_json


# ---------------------------------------------------------------------------
# extract_json：正常与常见变体
# ---------------------------------------------------------------------------

def test_plain_json() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_json_inside_markdown_fence() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_surrounded_by_prose() -> None:
    text = '好的，分析结果如下：\n{"a": 1}\n希望有帮助。'
    assert extract_json(text) == {"a": 1}


def test_trailing_comma() -> None:
    assert extract_json('{"a": 1,}') == {"a": 1}
    assert extract_json('{"a": [1, 2,]}') == {"a": [1, 2]}


def test_chinese_quotes_used_as_delimiters() -> None:
    """整段没有 ASCII 引号时，说明模型拿中文引号当定界符了。"""
    assert extract_json('{“a”: 1, “b”: “x”}') == {"a": 1, "b": "x"}


def test_escaped_quotes_are_preserved() -> None:
    result = extract_json('{"a": "he said \\"hi\\""}')
    assert result == {"a": 'he said "hi"'}


def test_valid_json_with_chinese_text_is_untouched() -> None:
    text = '{"diagnosis": "学生把「单调递增」理解反了", "ok": true}'
    assert extract_json(text) == {
        "diagnosis": "学生把「单调递增」理解反了",
        "ok": True,
    }


def test_empty_or_garbage() -> None:
    assert extract_json("") is None
    assert extract_json("完全没有 JSON") is None
    assert extract_json("{不是合法的}") is None


# ---------------------------------------------------------------------------
# extract_json：核心 —— 正文里混入裸 ASCII 引号
# ---------------------------------------------------------------------------

def test_unescaped_quotes_inside_chinese_text() -> None:
    """最典型的坏输出：中文里本该用「」或 “”，却打了 ASCII 的 "。"""
    broken = '{"diagnosis": "学生把"单调递增"理解反了"}'
    result = extract_json(broken)
    assert result is not None
    assert result["diagnosis"] == '学生把"单调递增"理解反了'


def test_multiple_stray_quotes() -> None:
    broken = '{"text": "他说"你好"，然后走了", "ok": true}'
    result = extract_json(broken)
    assert result is not None
    assert result["text"] == '他说"你好"，然后走了'
    assert result["ok"] is True


def test_stray_quotes_in_nested_array_of_objects() -> None:
    broken = (
        '{"questions": [{"stem": "求"单调区间"", "answer": "C"}, '
        '{"stem": "求导", "answer": "A"}]}'
    )
    result = extract_json(broken)
    assert result is not None
    assert result["questions"][0]["stem"] == '求"单调区间"'
    assert result["questions"][1]["answer"] == "A"


def test_stray_quotes_with_fence_and_prose() -> None:
    broken = '分析完成：\n```json\n{"d": "他说"对""}\n```\n以上。'
    result = extract_json(broken)
    assert result is not None
    assert result["d"] == '他说"对"'


# ---------------------------------------------------------------------------
# complete_json：解析失败要能重试
# ---------------------------------------------------------------------------

class _StubClient(LlmClient):
    """把 HTTP 层换成脚本化回复，用来验证重试逻辑。"""

    def __init__(self, replies: list[str]) -> None:
        super().__init__()
        self._replies = list(replies)
        self.calls = 0

    @property
    def configured(self) -> bool:  # type: ignore[override]
        return True

    async def complete(self, messages, **kwargs) -> LlmReply:  # type: ignore[override]
        self.calls += 1
        text = self._replies.pop(0) if self._replies else "{}"
        return LlmReply(text=text, model="stub", provider="stub", latency_ms=1)


def test_complete_json_retries_until_valid() -> None:
    client = _StubClient(["不是 JSON", '{"a": ', '{"a": 1}'])

    async def run() -> dict:
        payload, _ = await client.complete_json([{"role": "user", "content": "x"}], attempts=5)
        return payload

    assert asyncio.run(run()) == {"a": 1}
    assert client.calls == 3


def test_complete_json_accepts_repairable_output_on_first_try() -> None:
    """能被修好的坏输出不该浪费重试次数。"""
    client = _StubClient(['{"d": "他说"对""}'])

    async def run() -> dict:
        payload, _ = await client.complete_json([{"role": "user", "content": "x"}], attempts=5)
        return payload

    assert asyncio.run(run()) == {"d": '他说"对"'}
    assert client.calls == 1


def test_complete_json_gives_up_after_attempts() -> None:
    client = _StubClient(["垃圾"] * 10)

    async def run() -> None:
        await client.complete_json([{"role": "user", "content": "x"}], attempts=3)

    with pytest.raises(LlmUnavailable):
        asyncio.run(run())
    assert client.calls == 3
