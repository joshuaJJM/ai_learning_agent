"""标准 AI 直连接口。

给前端"跟踪训练"用的最简形态：**发一个问题，拿回一个回答**。

    POST /api/v1/ai/chat
    {"prompt": "为什么 f'(x) > 0 说明函数单调递增？"}
    → {"reply": "..."}

单轮只填 prompt；需要多轮时填 messages。想指定模型就填 model。
这个接口不做任何教学状态管理——需要状态请用 /tutor/sessions。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..config import get_settings
from ..dependencies import current_user
from ..errors import SERVICE_UNAVAILABLE, VALIDATION_ERROR, ApiError, request_id_of
from ..schemas import (
    AiChatMessage,
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


@router.post("/chat", response_model=AiChatResponse, summary="最简问答")
async def chat(
    payload: AiChatRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> AiChatResponse:
    rid = request_id_of(request)
    messages: list[dict[str, Any]] = []
    if payload.system:
        messages.append({"role": "system", "content": payload.system})

    if payload.messages:
        messages.extend(m.model_dump() for m in payload.messages)
    elif payload.prompt:
        messages.append({"role": "user", "content": payload.prompt})
    else:
        raise ApiError(VALIDATION_ERROR, "prompt 与 messages 至少要提供一个")

    settings = get_settings()
    llm = get_llm()
    started = time.time()

    if not llm.configured:
        return AiChatResponse(
            reply=MOCK_REPLY,
            model="mock",
            provider="mock",
            latency_ms=int((time.time() - started) * 1000),
            request_id=rid,
        )

    try:
        reply = await llm.complete(
            messages,
            model=payload.model,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens or 1024,
            json_mode=payload.json_mode,
        )
    except LlmUnavailable as exc:
        if settings.llm_fallback_to_mock:
            return AiChatResponse(
                reply=MOCK_REPLY,
                model="mock",
                provider="mock",
                latency_ms=int((time.time() - started) * 1000),
                request_id=rid,
            )
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
