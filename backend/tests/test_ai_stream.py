"""AI 对话流式接口的测试。

分两层覆盖：

1. `LlmClient.astream` —— 用假的 httpx 传输层喂真实形态的 SSE，
   覆盖"数据片 / 只带 usage 的收尾片 / [DONE] / 鉴权失败 / 中途断流"。
   这一层不依赖网络，也不依赖测试环境的 Mock 开关。
2. `POST /api/v1/ai/chat` 带 `stream: true` —— 走 Mock 分支验证 SSE 帧格式、
   事件顺序与增量拼接结果（测试环境 FORCE_MOCK_LLM=true）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.services.llm import LlmClient, LlmUnavailable, LlmStreamDelta


# ---------------------------------------------------------------------------
# 假的 httpx 传输层
# ---------------------------------------------------------------------------

def _sse_body(chunks: list[dict[str, Any]], *, done: bool = True) -> bytes:
    lines = [f"data: {json.dumps(c, ensure_ascii=False)}" for c in chunks]
    if done:
        lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode("utf-8")


def _chunk(content: str | None, usage: dict[str, Any] | None = None) -> dict[str, Any]:
    delta = {} if content is None else {"content": content}
    return {"choices": [{"delta": delta}], "usage": usage}


def _fake_client(body: bytes, *, status_code: int = 200) -> httpx.AsyncClient:
    """构造一个只回放固定 SSE 体的 AsyncClient。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture()
def live_llm() -> LlmClient:
    """一个"已配置"的客户端，但把 .env 里的真实配置整体替换掉。"""
    from app.config import Settings

    settings = Settings(
        llm_base_url="https://example.invalid/v1",
        llm_api_key="sk-test",
        force_mock_llm=False,
        llm_timeout_seconds=5.0,
    )
    return LlmClient(settings)


def _collect(client: LlmClient, fake: httpx.AsyncClient, **kwargs: Any) -> list[LlmStreamDelta]:
    async def run() -> list[LlmStreamDelta]:
        client._client = fake
        return [d async for d in client.astream([{"role": "user", "content": "hi"}], **kwargs)]

    return asyncio.run(run())


# ---------------------------------------------------------------------------
# 1. astream：SSE 解析
# ---------------------------------------------------------------------------

def test_astream_parses_deltas_in_order(live_llm: LlmClient) -> None:
    body = _sse_body([_chunk("因为"), _chunk("导数"), _chunk("表示变化率")])
    deltas = _collect(live_llm, _fake_client(body))

    assert "".join(d.content for d in deltas) == "因为导数表示变化率"
    # 没有 usage 的片不应伪造出 usage
    assert all(d.usage is None for d in deltas)


def test_astream_yields_usage_from_final_chunk(live_llm: LlmClient) -> None:
    """provider 在最后补一片只有 usage、choices 为空的收尾片。"""
    usage = {"prompt_tokens": 5, "completion_tokens": 9, "total_tokens": 14}
    body = _sse_body(
        [
            _chunk("答"),
            _chunk("案"),
            {"choices": [], "usage": usage},
        ]
    )
    deltas = _collect(live_llm, _fake_client(body))

    assert "".join(d.content for d in deltas) == "答案"
    assert [d.usage for d in deltas if d.usage] == [usage]


def test_astream_survives_noise_and_missing_done(live_llm: LlmClient) -> None:
    """非 JSON 心跳行、空 data 行、缺少 [DONE] 都不能让解析崩掉。"""
    raw = (
        ": keep-alive\n\n"
        "data: \n\n"
        "data: not-json\n\n"
        'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    deltas = _collect(live_llm, _fake_client(raw))
    assert "".join(d.content for d in deltas) == "ok"


def test_astream_endpoint_without_done_terminates(live_llm: LlmClient) -> None:
    """provider 直接关流、不补 [DONE] 时也要正常结束，不能挂住。"""
    deltas = _collect(live_llm, _fake_client(_sse_body([_chunk("尾")], done=False)))
    assert "".join(d.content for d in deltas) == "尾"


def test_astream_auth_failure_raises(live_llm: LlmClient) -> None:
    body = b'{"message":"bad key"}'
    with pytest.raises(LlmUnavailable) as exc:
        _collect(live_llm, _fake_client(body, status_code=401))
    assert "401" in str(exc.value)
    assert exc.value.status_code == 401


def test_astream_non_200_raises_with_body(live_llm: LlmClient) -> None:
    body = b'{"message":"rate limited"}'
    with pytest.raises(LlmUnavailable) as exc:
        _collect(live_llm, _fake_client(body, status_code=429))
    assert exc.value.status_code == 429


def test_astream_refuses_when_not_configured() -> None:
    from app.config import Settings

    client = LlmClient(Settings(llm_api_key="", force_mock_llm=True))

    async def run() -> None:
        async for _ in client.astream([{"role": "user", "content": "hi"}]):
            pass

    with pytest.raises(LlmUnavailable):
        asyncio.run(run())


def test_astream_sends_stream_flag_and_usage_option(live_llm: LlmClient) -> None:
    """请求体必须带 stream=true 与 include_usage，否则拿不到 usage。"""
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, content=_sse_body([_chunk("x")]))

    fake = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run() -> None:
        live_llm._client = fake
        async for _ in live_llm.astream(
            [{"role": "user", "content": "hi"}], max_tokens=64, json_mode=True
        ):
            pass

    asyncio.run(run())
    assert seen["stream"] is True
    assert seen["stream_options"] == {"include_usage": True}
    assert seen["max_tokens"] == 64


# ---------------------------------------------------------------------------
# 2. /api/v1/ai/chat?stream=true：SSE 帧
# ---------------------------------------------------------------------------

def _parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event, data = "message", ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        events.append((event, json.loads(data) if data else {}))
    return events


def test_chat_stream_mock_emits_sse(client, auth_headers) -> None:
    """测试环境强制 Mock：应回 SSE，且事件序列为 meta → delta* → done。"""
    response = client.post(
        "/api/v1/ai/chat",
        json={"prompt": "什么是导数？", "stream": True},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    names = [name for name, _ in events]

    assert names[0] == "meta"
    assert names[-1] == "done"
    assert "delta" in names
    # 不允许出现 error
    assert "error" not in names

    meta = events[0][1]
    assert meta["model"] == "mock"
    assert meta["provider"] == "mock"
    assert meta["request_id"]

    # 增量拼接必须等于 done.reply 里给出的完整文案
    streamed = "".join(payload["content"] for name, payload in events if name == "delta")
    done = events[-1][1]
    assert streamed == done["reply"]
    assert done["reply"].strip()


def test_chat_stream_deltas_are_utf8_not_escaped(client, auth_headers) -> None:
    """中文必须以 UTF-8 原样下发，不能被转义成 \\uXXXX。"""
    response = client.post(
        "/api/v1/ai/chat",
        json={"prompt": "hi", "stream": True},
        headers=auth_headers,
    )
    assert "\\u" not in response.text
    assert "后端当前没有连上大模型" in response.text


def test_chat_without_stream_still_returns_json(client, auth_headers) -> None:
    """加流式不能破坏原有的一次性 JSON 行为（向后兼容）。"""
    response = client.post(
        "/api/v1/ai/chat",
        json={"prompt": "什么是导数？"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    body = response.json()
    assert set(body) >= {"reply", "model", "provider", "latency_ms", "request_id"}
    assert body["model"] == "mock"
    assert body["reply"].strip()


def test_chat_stream_requires_prompt_or_messages(client, auth_headers) -> None:
    """流式下参数校验失败仍要在开流之前返回 422，而不是流里报错。"""
    response = client.post(
        "/api/v1/ai/chat",
        json={"stream": True},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 3. 路由里的真实模型流分支（_stream）
# ---------------------------------------------------------------------------
# 测试环境 FORCE_MOCK_LLM=true，所以上面的端到端用例走的是 _stream_mock。
# 这里把 LLM 客户端换成桩，专门覆盖 _stream 这条真实路径：
# 正常逐片下发，以及"开流之后模型才失败"必须以 error 事件收尾且不能抛异常。


class _StubLlm:
    def __init__(self, *, chunks: list[LlmStreamDelta] | None = None, boom: bool = False) -> None:
        self._chunks = chunks or []
        self._boom = boom
        self.seen: dict[str, Any] = {}

    def default_model(self) -> str:
        return "stub-model"

    @property
    def configured(self) -> bool:
        return True

    async def astream(self, messages: list[dict[str, Any]], **kwargs: Any):
        self.seen = kwargs
        if self._boom:
            raise LlmUnavailable("上游 500")
        for chunk in self._chunks:
            yield chunk


def _post_stream(client, auth_headers, stub: _StubLlm):
    import app.routers.ai as ai_router

    original = ai_router.get_llm
    ai_router.get_llm = lambda: stub  # type: ignore[assignment]
    try:
        return client.post(
            "/api/v1/ai/chat",
            json={"prompt": "hi", "stream": True, "max_tokens": 32},
            headers=auth_headers,
        )
    finally:
        ai_router.get_llm = original  # type: ignore[assignment]


def test_chat_stream_live_path_emits_provider_chunks(client, auth_headers) -> None:
    usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
    stub = _StubLlm(
        chunks=[
            LlmStreamDelta(content="因"),
            LlmStreamDelta(content="为"),
            LlmStreamDelta(usage=usage),
        ]
    )
    response = _post_stream(client, auth_headers, stub)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    names = [name for name, _ in events]

    assert names == ["meta", "delta", "delta", "done"]
    assert events[0][1]["model"] == "stub-model"
    assert "".join(p["content"] for n, p in events if n == "delta") == "因为"
    assert events[-1][1]["reply"] == "因为"
    assert events[-1][1]["usage"] == usage
    assert events[-1][1]["first_token_ms"] is not None

    # 路由必须把请求参数透传给客户端
    assert stub.seen["max_tokens"] == 32


def test_chat_stream_midstream_failure_emits_error_event(client, auth_headers) -> None:
    """响应头已发出后失败：必须以 error 收尾，且 HTTP 状态仍是 200。"""
    response = _post_stream(client, auth_headers, _StubLlm(boom=True))

    assert response.status_code == 200  # 不能再改成 503
    events = _parse_sse(response.text)
    names = [name for name, _ in events]

    assert names == ["meta", "error"]
    assert "done" not in names
    error = events[-1][1]
    assert error["error_code"] == "SERVICE_UNAVAILABLE"
    assert "上游 500" in error["message"]


def test_chat_stream_api_error_from_mock(client, auth_headers) -> None:
    """未配置模型时流式也回 SSE，前端不需要为兜底分叉。"""
    import app.routers.ai as ai_router

    class _Unconfigured:
        def default_model(self) -> str:
            return "mock"

        @property
        def configured(self) -> bool:
            return False

    original = ai_router.get_llm
    ai_router.get_llm = lambda: _Unconfigured()  # type: ignore[assignment]
    try:
        response = client.post(
            "/api/v1/ai/chat",
            json={"prompt": "hi", "stream": True},
            headers=auth_headers,
        )
    finally:
        ai_router.get_llm = original  # type: ignore[assignment]

    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    assert events[0][0] == "meta"
    assert events[-1][0] == "done"
    assert events[-1][1]["provider"] == "mock"
