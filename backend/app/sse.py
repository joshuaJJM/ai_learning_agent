"""SSE（Server-Sent Events）帧编码。

`/api/v1/ai/chat` 与 Tutor 的流式作答共用同一套帧格式，
避免两边各写一份再慢慢长歪。
"""

from __future__ import annotations

import json
from typing import Any

#: 流式响应必须带的头。
#:
#: `X-Accel-Buffering: no` 是关键：前面若有 nginx，默认会把响应攒起来
#: 一次性发出，流式就白做了。
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_frame(event: str, payload: dict[str, Any]) -> str:
    """把一个事件编码成 SSE 帧。

    `ensure_ascii=False` 保证中文按 UTF-8 原样下发，而不是被转义成 \\uXXXX。
    """
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n"


def chunk_text(text: str, size: int) -> list[str]:
    """把一段文字切成若干片，用于 `delta` 事件。"""
    if size <= 0:
        return [text]
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]
