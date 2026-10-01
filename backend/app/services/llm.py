"""LLM / VLM 统一接入层。

所有模型调用都必须经过这里，Router 与 Service 都不直接依赖具体 Provider。
需要换模型 / 换厂商时，只改 .env，不改代码。

关键设计：**失败就抛异常，由业务层决定怎么降级**。
因为不同场景的降级方式完全不同——
  - 试卷分析失败 → 回退到题库匹配出的确定性结果
  - 自由问答失败 → 返回一个友好的兜底文案
把"降级"写死在 HTTP 层里是做不出好 Demo 的。
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import httpx

from ..config import Settings, get_settings


class LlmUnavailable(RuntimeError):
    """模型调用失败（网络、超时、限流、鉴权、返回体异常）。"""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class LlmReply:
    text: str
    model: str
    provider: str
    latency_ms: int
    usage: dict[str, Any] | None = None
    degraded: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


def image_part(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
    }


def build_user_message(text: str, images: Sequence[tuple[bytes, str]] = ()) -> dict[str, Any]:
    if not images:
        return {"role": "user", "content": text}
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for raw, mime in images:
        content.append(image_part(raw, mime))
    return {"role": "user", "content": content}


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any] | None:
    """从模型输出里尽量抠出一个 JSON 对象。

    模型经常会加上 ```json 围栏或前后废话，这里做三层兜底解析。
    """
    if not text:
        return None
    candidates: list[str] = [text.strip()]

    fenced = _JSON_FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


class LlmClient:
    """OpenAI 兼容的异步客户端。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.settings.llm_api_key) and not self.settings.force_mock_llm

    @property
    def mode(self) -> str:
        return "live" if self.configured else "mock"

    async def _get_client(self) -> httpx.AsyncClient:
        async with self._lock:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    timeout=httpx.Timeout(self.settings.llm_timeout_seconds, connect=15.0),
                    limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
                )
            return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def default_model(self, *, vision: bool = False) -> str:
        return self.settings.vlm_model if vision else self.settings.llm_model

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.6,
        max_tokens: int = 1024,
        json_mode: bool = False,
        vision: bool = False,
        retries: int = 1,
    ) -> LlmReply:
        if not self.configured:
            raise LlmUnavailable("LLM 未配置或已强制 Mock 模式")

        target_model = model or self.default_model(vision=vision)
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode and self.settings.llm_json_mode:
            payload["response_format"] = {"type": "json_object"}

        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            started = time.time()
            try:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.settings.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                last_error = LlmUnavailable(f"模型调用超时: {exc}")
            except httpx.HTTPError as exc:
                last_error = LlmUnavailable(f"模型调用网络错误: {exc}")
            else:
                latency = int((time.time() - started) * 1000)
                if response.status_code == 200:
                    try:
                        data = response.json()
                        text = data["choices"][0]["message"]["content"] or ""
                    except (KeyError, IndexError, ValueError) as exc:
                        last_error = LlmUnavailable(f"模型返回体异常: {exc}")
                    else:
                        return LlmReply(
                            text=text,
                            model=target_model,
                            provider="siliconflow",
                            latency_ms=latency,
                            usage=data.get("usage"),
                            raw=data,
                        )
                elif response.status_code in (401, 403):
                    # 鉴权问题重试没有意义
                    raise LlmUnavailable(
                        f"模型鉴权失败 (HTTP {response.status_code})",
                        status_code=response.status_code,
                    )
                elif response.status_code in (429, 500, 502, 503, 504):
                    last_error = LlmUnavailable(
                        f"模型端错误 HTTP {response.status_code}: {response.text[:200]}",
                        status_code=response.status_code,
                    )
                else:
                    raise LlmUnavailable(
                        f"模型调用失败 HTTP {response.status_code}: {response.text[:200]}",
                        status_code=response.status_code,
                    )

            if attempt < retries:
                await asyncio.sleep(0.8 * (attempt + 1))

        raise last_error or LlmUnavailable("模型调用失败")

    async def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        vision: bool = False,
        retries: int = 1,
    ) -> tuple[dict[str, Any], LlmReply]:
        reply = await self.complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            vision=vision,
            retries=retries,
        )
        parsed = extract_json(reply.text)
        if parsed is None:
            raise LlmUnavailable(f"模型未返回合法 JSON: {reply.text[:200]}")
        return parsed, reply


_client: LlmClient | None = None


def get_llm() -> LlmClient:
    global _client
    if _client is None:
        _client = LlmClient()
    return _client


async def shutdown_llm() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
