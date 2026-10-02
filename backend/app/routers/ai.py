"""标准 AI 直连接口。

给前端"跟踪训练"用的最简形态：**发一个问题，拿回一个回答**。

    POST /api/v1/ai/chat
    {"prompt": "为什么 f'(x) > 0 说明函数单调递增？"}
    → {"reply": "..."}

    POST /api/v1/ai/chat
    {"prompt": "...", "stream": true}
    → text/event-stream（SSE）

单轮只填 prompt；需要多轮时填 messages。想指定模型就填 model。
这个接口不做任何教学状态管理——需要状态请用 /tutor/sessions。

流式实现要点（为什么不是简单地在生成器里 yield）：

1. **降级必须在开流之前决定。** 一旦响应头发出（HTTP 200 已定），后面出任何
   问题都不可能再改成 503，所以"模型没配 / 调用失败要不要走兜底"这件事
   放在生成器之前判断完。
2. **生成器里的 yield 是唯一的 await 点**，用同一个 try/except 收口，
   就不会出现"抛出后客户端只拿到半句话、又不知道该不该渲染"的状态。
3. **Mock 也走流式。** 前端只维护一套渲染逻辑，不需要为兜底文案分叉。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..config import get_settings
from ..dependencies import current_user
from ..errors import SERVICE_UNAVAILABLE, VALIDATION_ERROR, ApiError, request_id_of
from ..schemas import (
    AiChatRequest,
    AiChatResponse,
    AiModelInfo,
    AiModelsResponse,
)
from ..services.llm import LlmUnavailable, get_llm

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

MOCK_REPLY = (
    "后端当前没有连上大模型，所以无法回答这个问题。\n"
    "（原因：未配置 LLM_API_KEY，或已开启 FORCE_MOCK_LLM 离线模式，"
    "或模型调用失败后触发了降级。）\n"
    "教学功能（Tutor / 练习 / 试卷分析）不受影响，它们有本地兜底逻辑。"
)

MOCK_MODEL = "mock"
MOCK_PROVIDER = "mock"

# 一次性响应的默认 max_tokens（与 AiChatRequest 的默认值保持一致）
DEFAULT_MAX_TOKENS = 1024

# 兜底文案按字数切块推送，让 Mock 也有一点"逐字出现"的观感。
_MOCK_CHUNK_CHARS = 12
_MOCK_CHUNK_DELAY = 0.015


def _build_messages(payload: AiChatRequest) -> list[dict[str, Any]]:
    """把 prompt / messages / system 归一成 OpenAI 格式的 messages。"""
    messages: list[dict[str, Any]] = []
    if payload.system:
        messages.append({"role": "system", "content": payload.system})

    if payload.messages:
        messages.extend(m.model_dump() for m in payload.messages)
    elif payload.prompt:
        messages.append({"role": "user", "content": payload.prompt})
    else:
        raise ApiError(VALIDATION_ERROR, "prompt 与 messages 至少要提供一个")
    return messages


def _mock_meta(started: float, rid: str) -> dict[str, Any]:
    """兜底响应的非正文字段（一次性响应的 kwargs 与流式 done 事件共用）。

    刻意不含 `reply`，这样可直接展开进 `AiChatResponse(reply=..., **kwargs)`
    而不会重复传参。
    """
    return {
        "model": MOCK_MODEL,
        "provider": MOCK_PROVIDER,
        "latency_ms": int((time.time() - started) * 1000),
        "request_id": rid,
        "usage": None,
    }


def _sse(event: str, payload: dict[str, Any]) -> str:
    """把一个事件编码成 SSE 帧。

    `ensure_ascii=False` 保证中文按 UTF-8 原样下发，而不是被转义成 \\uXXXX。
    """
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n"


async def _stream_mock(rid: str, started: float) -> AsyncIterator[str]:
    """兜底文案的流式版本：先 meta，再分块 delta，最后 done。"""
    yield _sse("meta", {"request_id": rid, "model": MOCK_MODEL, "provider": MOCK_PROVIDER})
    for index in range(0, len(MOCK_REPLY), _MOCK_CHUNK_CHARS):
        yield _sse("delta", {"content": MOCK_REPLY[index : index + _MOCK_CHUNK_CHARS]})
        await asyncio.sleep(_MOCK_CHUNK_DELAY)
    yield _sse("done", {**_mock_meta(started, rid), "reply": MOCK_REPLY})


async def _stream(
    messages: list[dict[str, Any]],
    payload: AiChatRequest,
    *,
    rid: str,
    started: float,
) -> AsyncIterator[str]:
    """真实模型的 SSE 流：meta → delta* → done（或 error）。"""
    llm = get_llm()
    target_model = payload.model or llm.default_model()

    yield _sse(
        "meta",
        {
            "request_id": rid,
            "model": target_model,
            "provider": "siliconflow",
        },
    )

    pieces: list[str] = []
    usage: dict[str, Any] | None = None
    first_token_ms: int | None = None

    try:
        async for chunk in llm.astream(
            messages,
            model=payload.model,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens or DEFAULT_MAX_TOKENS,
            json_mode=payload.json_mode,
        ):
            if chunk.content:
                if first_token_ms is None:
                    first_token_ms = int((time.time() - started) * 1000)
                pieces.append(chunk.content)
                yield _sse("delta", {"content": chunk.content})
            if chunk.usage:
                usage = chunk.usage
    except LlmUnavailable as exc:
        # 响应头早已发出（200），这里只能以 error 事件收尾，不能再改状态码。
        yield _sse(
            "error",
            {
                "error_code": SERVICE_UNAVAILABLE,
                "message": f"模型暂时不可用：{exc}",
                "request_id": rid,
            },
        )
        return

    yield _sse(
        "done",
        {
            "reply": "".join(pieces),
            "model": target_model,
            "provider": "siliconflow",
            "latency_ms": int((time.time() - started) * 1000),
            "first_token_ms": first_token_ms,
            "request_id": rid,
            "usage": usage,
        },
    )


@router.post(
    "/chat",
    response_model=AiChatResponse,
    summary="最简问答（支持流式）",
    responses={
        200: {
            "description": (
                "默认返回一次性 JSON。请求体带 `stream: true` 时改返回 "
                "`text/event-stream`，事件序列为 `meta` → `delta`* → `done`，"
                "失败时最后一个事件是 `error`。"
            ),
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": (
                        'event: meta\n'
                        'data: {"request_id": "abc", "model": "deepseek-ai/DeepSeek-V3.2", '
                        '"provider": "siliconflow"}\n\n'
                        'event: delta\n'
                        'data: {"content": "因为"}\n\n'
                        'event: done\n'
                        'data: {"reply": "因为……", "latency_ms": 1234, '
                        '"first_token_ms": 320, "usage": null}\n\n'
                    ),
                }
            },
        }
    },
)
async def chat(
    payload: AiChatRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
):
    rid = request_id_of(request)
    messages = _build_messages(payload)

    settings = get_settings()
    llm = get_llm()
    started = time.time()

    if payload.stream:
        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 关掉 nginx 缓冲，否则 SSE 会被攒着一次性发出，流式就没意义了
            "X-Accel-Buffering": "no",
            "X-Request-ID": rid,
        }

        if not llm.configured:
            return StreamingResponse(
                _stream_mock(rid, started),
                media_type="text/event-stream",
                headers=headers,
            )

        return StreamingResponse(
            _stream(messages, payload, rid=rid, started=started),
            media_type="text/event-stream",
            headers=headers,
        )

    if not llm.configured:
        return AiChatResponse(reply=MOCK_REPLY, **_mock_meta(started, rid))

    try:
        reply = await llm.complete(
            messages,
            model=payload.model,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens or DEFAULT_MAX_TOKENS,
            json_mode=payload.json_mode,
        )
    except LlmUnavailable as exc:
        if settings.llm_fallback_to_mock:
            return AiChatResponse(reply=MOCK_REPLY, **_mock_meta(started, rid))
        raise ApiError(SERVICE_UNAVAILABLE, f"模型暂时不可用：{exc}") from exc

    return AiChatResponse(
        reply=reply.text,
        model=reply.model,
        provider=reply.provider,
        latency_ms=reply.latency_ms,
        request_id=rid,
        usage=reply.usage,
    )


@router.get("/models", response_model=AiModelsResponse, summary="可用模型列表")
async def models() -> AiModelsResponse:
    settings = get_settings()
    items = [
        AiModelInfo(
            id=settings.llm_model,
            label=f"{settings.llm_model}（默认文本）",
            kind="text",
            is_default=True,
        ),
        AiModelInfo(
            id=settings.llm_fallback_model,
            label=f"{settings.llm_fallback_model}（文本备选）",
            kind="text",
        ),
        AiModelInfo(
            id=settings.vlm_model,
            label=f"{settings.vlm_model}（默认视觉）",
            kind="vision",
        ),
        AiModelInfo(
            id=settings.vlm_fallback_model,
            label=f"{settings.vlm_fallback_model}（视觉备选）",
            kind="vision",
        ),
    ]
    return AiModelsResponse(
        default_model=settings.llm_model,
        default_vision_model=settings.vlm_model,
        models=items,
    )
