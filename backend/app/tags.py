"""标签体系。

标签（tag）与知识点（knowledge point）是**两套独立的东西**：

  - 知识点：用来算掌握度，是 Knowledge Engine 的核心，ID 是 `math.derivative.xxx`
  - 标签：用来做**练习推荐**。每道题带若干个标签，用户答对则这些标签 +1、
    答错则 -1。推荐时挑「分数最低的标签」，返回带这个标签的题。

标签表放在 `app/seed/tags.json`，是**可替换的配置**。
标签宇宙 = 配置表里的标签 ∪ 题库里实际出现的标签 ——
这样即使配置表还没补全，题库里的标签也一定能被计分，不会丢。

标签用中文字面量本身作为 key（题库和模型输出里就是中文），不做额外映射表。
"""

from __future__ import annotations

import json
from pathlib import Path

TAGS_FILE = Path(__file__).resolve().parent / "seed" / "tags.json"

# 标签 key 的列宽上限。索引里 user_id(64) + tag 加起来要小于
# MySQL 5.7 utf8mb4 的 767 字节上限，所以 96*4 + 64*4 = 640 是安全的。
TAG_MAX_LENGTH = 96


def load_declared_tags() -> tuple[str, ...]:
    """读取配置的标签表。文件缺失或损坏时返回空（不影响启动）。"""
    try:
        payload = json.loads(TAGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    raw = payload.get("tags")
    if not isinstance(raw, list):
        return ()
    result: list[str] = []
    for item in raw:
        # 允许写成 {"tag": "...", "description": "..."} 或纯字符串
        text = item.get("tag") if isinstance(item, dict) else item
        text = str(text or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def normalize(tag: str) -> str:
    """统一标签写法，避免「空格/全角」造成的重复计分。"""
    return str(tag or "").strip()


def is_valid(tag: str) -> bool:
    return bool(tag) and len(tag) <= TAG_MAX_LENGTH


def order_key(tag: str) -> str:
    """同分标签的稳定排序键，保证推荐结果可复现。"""
    return tag


_cached_declared: tuple[str, ...] | None = None


def declared_tags() -> tuple[str, ...]:
    global _cached_declared
    if _cached_declared is None:
        _cached_declared = load_declared_tags()
    return _cached_declared


def reset_cache() -> None:
    global _cached_declared
    _cached_declared = None
