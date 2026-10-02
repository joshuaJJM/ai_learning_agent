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
from typing import Any, AsyncIterator, Sequence

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


@dataclass
class LlmStreamDelta:
    """流式增量：`content` 是本次新增的文本片段。

    `usage` 只在最后一片（provider 支持 `stream_options.include_usage` 时）出现。
    """

    content: str = ""
    usage: dict[str, Any] | None = None


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
_TRAILING_COMMA = re.compile(r",\s*([}\]])")

# 模型回答里常见的坏 JSON 变体
SMART_OPEN = "\u201c"  # “
SMART_CLOSE = "\u201d"  # ”


JSON_RETRY_HINT = (
    "上面这个回答不是合法的 JSON（解析失败了）。请重新输出，并严格遵守：\n"
    "1. 只输出一个 JSON 对象，前后不要有任何解释文字，也不要用 markdown 围栏；\n"
    '2. 字符串内部不要出现 ASCII 双引号 "，需要引号时请改用中文引号 「」 或 “”；\n'
    "3. 最后一项后面不要留多余的逗号。"
)

#: 输出被 `max_tokens` 截断时，最多放大到这个预算再试。
#:
#: 真实事故：一张有 9 道题的试卷，VLM 要给每题写 diagnosis + explanation，
#: 3000 token 直接在中途被切断 → JSON 非法 → 原样重试 5 次，每次都同样被切断，
#: 白等 9 分钟然后整体失败。`finish_reason == "length"` 是明确信号，
#: 遇到它必须**放大预算**，而不是重发同一个请求。
MAX_OUTPUT_TOKENS = 16000


def _finish_reason(reply: LlmReply) -> str | None:
    """取 provider 返回的 finish_reason（`length` = 被 max_tokens 截断）。"""
    choices = reply.raw.get("choices") if isinstance(reply.raw, dict) else None
    if not choices:
        return None
    return choices[0].get("finish_reason")


def _strip_fence(text: str) -> str:
    fenced = _JSON_FENCE.search(text)
    return fenced.group(1).strip() if fenced else text.strip()


def _outermost_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return text
    return text[start : end + 1]


def _normalize_smart_quotes(text: str) -> str:
    """整段没有 ASCII 引号、只有中文引号时，说明模型把中文引号当成了 JSON 定界符。"""
    if '"' not in text and (SMART_OPEN in text or SMART_CLOSE in text):
        return text.replace(SMART_OPEN, '"').replace(SMART_CLOSE, '"')
    return text


def _escape_stray_quotes(text: str) -> str:
    """转义 JSON 字符串**内部**未转义的 ASCII 双引号。

    这是最常见的一类坏输出：模型在中文文本里本该写「引号」或 “引号”，
    却打了 ASCII 的 "，于是字符串提前闭合、整个 JSON 解析失败。例如：

        {"diagnosis": "学生把"单调递增"理解反了"}

    判断方法：遇到引号时往后看第一个非空白字符，
    如果是 , } ] : 就认为它是正常的闭合引号；否则它是正文里的裸引号，补上反斜杠。
    """
    out: list[str] = []
    in_string = False
    escaped = False
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        if escaped:
            out.append(char)
            escaped = False
            index += 1
            continue

        if char == "\\":
            out.append(char)
            escaped = True
            index += 1
            continue

        if char == '"':
            if not in_string:
                in_string = True
                out.append(char)
                index += 1
                continue

            lookahead = index + 1
            while lookahead < length and text[lookahead] in " \t\r\n":
                lookahead += 1
            following = text[lookahead] if lookahead < length else ""

            if following in (",", "}", "]", ":"):
                in_string = False
                out.append(char)
            else:
                out.append('\\"')
            index += 1
            continue

        out.append(char)
        index += 1

    return "".join(out)


def _drop_trailing_commas(text: str) -> str:
    return _TRAILING_COMMA.sub(r"\1", text)


def _variants(raw: str) -> list[str]:
    """逐步加固的候选串：原样 → 中文引号归一 → 转义裸引号 → 去尾逗号。"""
    variants = [raw]

    normalized = _normalize_smart_quotes(raw)
    if normalized != raw:
        variants.append(normalized)

    for source in list(variants):
        escaped = _escape_stray_quotes(source)
        if escaped != source:
            variants.append(escaped)

    for source in list(variants):
        trimmed = _drop_trailing_commas(source)
        if trimmed != source:
            variants.append(trimmed)

    return variants


def extract_json(text: str) -> dict[str, Any] | None:
    """从模型输出里尽量抠出一个 JSON 对象。

    模型经常加上 ```json 围栏、前后废话，或者在字符串里用错引号。
    这里先切出候选文本，再对每个候选做递进式修复，直到能解析为止。
    """
    if not text:
        return None

    stripped = _strip_fence(text)
    seeds = [text.strip(), stripped, _outermost_object(stripped)]

    seen: set[str] = set()
    for seed in seeds:
        if not seed or seed in seen:
            continue
        seen.add(seed)
        for variant in _variants(seed):
            try:
                parsed = json.loads(variant)
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

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

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
                    headers=self._headers,
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

    async def astream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.6,
        max_tokens: int = 1024,
        json_mode: bool = False,
        vision: bool = False,
        retries: int = 1,
    ) -> AsyncIterator[LlmStreamDelta]:
        """流式调用，逐片吐出增量文本，最后一片带 `usage`。

        设计取舍与 `complete` 一致，但有两点不同：

        1. **不做 HTTP 重试。** 首片之前的失败确实可以重试，可一旦已经有
           内容推给客户端，重试就会让用户看到重复的半句话。为了行为可预期，
           这里统一不重试，失败直接抛 `LlmUnavailable`。
        2. **超时按"单次读取间隔"算。** httpx 的 read timeout 作用于两次
           数据到达之间，不是整个流的总时长，所以长回答不会被总时长卡断。
        """
        if not self.configured:
            raise LlmUnavailable("LLM 未配置或已强制 Mock 模式")

        target_model = model or self.default_model(vision=vision)
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            # 让 provider 在最后一片补上 usage；不支持的端点会忽略它。
            "stream_options": {"include_usage": True},
        }
        if json_mode and self.settings.llm_json_mode:
            payload["response_format"] = {"type": "json_object"}

        client = await self._get_client()
        # 连接阶段用短超时；两次数据之间的间隔用配置的模型超时。
        timeout = httpx.Timeout(self.settings.llm_timeout_seconds, connect=15.0)

        try:
            async with client.stream(
                "POST", url, headers=self._headers, json=payload, timeout=timeout
            ) as response:
                if response.status_code in (401, 403):
                    raise LlmUnavailable(
                        f"模型鉴权失败 (HTTP {response.status_code})",
                        status_code=response.status_code,
                    )
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise LlmUnavailable(
                        f"模型调用失败 HTTP {response.status_code}: {body[:200]}",
                        status_code=response.status_code,
                    )

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue  # 个别 provider 会插入非 JSON 的心跳行

                    usage = chunk.get("usage")
                    choices = chunk.get("choices") or []
                    if not choices:
                        # 只有 usage 的收尾片
                        if usage:
                            yield LlmStreamDelta(usage=usage)
                        continue

                    delta = choices[0].get("delta") or {}
                    content = delta.get("content") or ""
                    if content:
                        yield LlmStreamDelta(content=content)
                    if usage:
                        yield LlmStreamDelta(usage=usage)
        except LlmUnavailable:
            raise
        except httpx.TimeoutException as exc:
            raise LlmUnavailable(f"模型流式调用超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LlmUnavailable(f"模型流式调用网络错误: {exc}") from exc

    async def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        vision: bool = False,
        retries: int = 0,
        attempts: int = 1,
    ) -> tuple[dict[str, Any], LlmReply]:
        """要求模型返回 JSON，解析失败则重试。

        `attempts` 是"拿到合法 JSON 为止"的总尝试次数，不是 HTTP 重试次数。
        （HTTP 层的重试由 `retries` 控制，二者独立。）

        第 2 次起会在对话里追加一句更强硬的格式约束 —— 模型看到自己上一条
        坏输出和具体错因，比单纯重发同一个请求成功率高得多。
        """
        attempts = max(1, attempts)
        request_messages = list(messages)
        last_text = ""
        budget = max_tokens
        truncated_ever = False

        for attempt in range(attempts):
            reply = await self.complete(
                request_messages,
                model=model,
                temperature=temperature,
                max_tokens=budget,
                json_mode=True,
                vision=vision,
                retries=retries,
            )
            parsed = extract_json(reply.text)
            if parsed is not None:
                return parsed, reply

            last_text = reply.text

            # 被 max_tokens 截断 → 原样重试毫无意义（同样的输入会得到同样被切断
            # 的输出，纯烧时间）。放大预算重发才有用。
            if _finish_reason(reply) == "length":
                truncated_ever = True
                if budget < MAX_OUTPUT_TOKENS:
                    budget = min(budget * 2, MAX_OUTPUT_TOKENS)
                    continue

            if attempt + 1 < attempts:
                request_messages = [
                    *messages,
                    {"role": "assistant", "content": reply.text[:800]},
                    {"role": "user", "content": JSON_RETRY_HINT},
                ]

        if truncated_ever:
            raise LlmUnavailable(
                f"模型输出被 max_tokens 截断（已放大到 {budget} 仍不完整）。"
                f"这次请求要的 JSON 太长，应提高 max_tokens 或减少一次识别的题目数。"
                f"最后一次输出: {last_text[:200]}"
            )
        raise LlmUnavailable(
            f"连续 {attempts} 次未返回合法 JSON，最后一次输出: {last_text[:200]}"
        )


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
