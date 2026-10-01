"""模型连通性探针。

用途：确认 key 可用、找出当前账号真正能调通的模型 ID。
这是踩过的坑——硅基流动 /v1/models 列出了 97 个模型，
但其中一部分对本账号并不可用（调用会连接被关闭或超时）。

用法：
    .venv\\Scripts\\python.exe tools\\probe_models.py            # 只测文本
    .venv\\Scripts\\python.exe tools\\probe_models.py --vision   # 连图片一起测
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import httpx

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402

FIXTURE = BACKEND_ROOT / "tests" / "fixtures" / "demo_question_17.png"

TEXT_CANDIDATES = [
    "deepseek-ai/DeepSeek-V3.2",
    "deepseek-ai/DeepSeek-V3.1-Terminus",
    "Qwen/Qwen3.5-27B",
    "Qwen/Qwen2.5-72B-Instruct",
]

VISION_CANDIDATES = [
    "Qwen/Qwen3-VL-32B-Instruct",
    "Qwen/Qwen3-VL-8B-Instruct",
    "Qwen/Qwen3-VL-30B-A3B-Instruct",
]


def _post(settings, model: str, messages: list, timeout: float) -> tuple[bool, str, float]:
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": 256,
        "temperature": 0,
    }
    started = time.time()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        elapsed = (time.time() - started) * 1000
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}", elapsed
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return True, text.strip()[:180], elapsed
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}", (time.time() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vision", action="store_true", help="同时测试 VLM")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    settings = get_settings()
    print(f"base_url = {settings.llm_base_url}")
    print(f"key      = {'已配置 (' + settings.llm_api_key[:8] + '...)' if settings.llm_api_key else '缺失'}")
    print()

    print("=== 文本模型 ===")
    for model in TEXT_CANDIDATES:
        ok, detail, ms = _post(
            settings, model, [{"role": "user", "content": "只回答两个字：收到"}], args.timeout
        )
        print(f"{'OK  ' if ok else 'FAIL'} {model:<38} {ms:8.0f}ms  {detail}")

    if args.vision:
        print()
        print("=== 视觉模型 ===")
        if not FIXTURE.exists():
            print(f"缺少测试图片: {FIXTURE}")
            return 1
        b64 = base64.b64encode(FIXTURE.read_bytes()).decode()
        prompt = (
            "这是一张数学题照片。请只输出 JSON，不要任何解释文字：\n"
            '{"stem":"题干","options":{"A":"","B":"","C":"","D":""},'
            '"student_answer":"学生作答的选项字母或null","answer":"正确选项字母"}'
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ]
        for model in VISION_CANDIDATES:
            ok, detail, ms = _post(settings, model, messages, args.timeout)
            print(f"{'OK  ' if ok else 'FAIL'} {model:<38} {ms:8.0f}ms")
            print(f"     {detail}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
