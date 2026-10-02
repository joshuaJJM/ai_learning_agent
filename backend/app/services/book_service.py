"""图书 / 题库权限。

黑客松阶段用假数据展示，不接真实支付。但数据结构是真的：
Book + Entitlement，后面接 StoreKit 服务端校验时不用改结构。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import db, repositories

BOOKS_PATH = Path(__file__).resolve().parent.parent / "seed" / "books.json"

_books_cache: list[dict[str, Any]] | None = None
_subscription_cache: dict[str, Any] | None = None


def _load() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    global _books_cache, _subscription_cache
    if _books_cache is None:
        try:
            payload = json.loads(BOOKS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        _books_cache = payload.get("books", [])
        _subscription_cache = payload.get("subscription", {})
    return _books_cache, _subscription_cache or {}


def seed_books() -> int:
    books, _ = _load()
    for book in books:
        repositories.save_book(
            {
                "book_id": book["book_id"],
                "title": book["title"],
                "publisher": book.get("publisher", ""),
                "cover_url": book.get("cover_url"),
                "price_cents": book.get("price_cents", 0),
                "question_count": book.get("question_count", 0),
                "description": book.get("description", ""),
                "subject": book.get("subject", "mathematics"),
                "bank_ids": book.get("bank_ids", []),
                "knowledge_point_ids": book.get("knowledge_point_ids", []),
                "demo_serial": book.get("demo_serial"),
                "owned_by_default": book.get("owned_by_default", False),
            }
        )
    return len(books)


def ensure_default_entitlements(user_id: str) -> None:
    """Demo 用：默认赠送第一本，让首页立刻有内容可看。"""
    books, _ = _load()
    for book in books:
        if book.get("owned_by_default") and not repositories.owns_book(
            user_id, book["book_id"]
        ):
            repositories.grant_entitlement(user_id, book["book_id"], source="demo_default")


def _summary(book: dict[str, Any], owned: bool) -> dict[str, Any]:
    return {
        "book_id": book["book_id"],
        "title": book.get("title", ""),
        "publisher": book.get("publisher", ""),
        "cover_url": book.get("cover_url"),
        "price_cents": book.get("price_cents", 0),
        "question_count": book.get("question_count", 0),
        "owned": owned,
    }


def _detail(book: dict[str, Any], owned: bool) -> dict[str, Any]:
    payload = _summary(book, owned)
    payload.update(
        {
            "description": book.get("description", ""),
            "subject": book.get("subject", "mathematics"),
            "bank_ids": book.get("bank_ids", []),
            "knowledge_point_ids": book.get("knowledge_point_ids", []),
        }
    )
    return payload


def list_books(user_id: str) -> list[dict[str, Any]]:
    books, _ = _load()
    owned_ids = {e["book_id"] for e in repositories.list_entitlements(user_id)}
    return [_summary(book, book["book_id"] in owned_ids) for book in books]


def get_book(user_id: str, book_id: str) -> dict[str, Any] | None:
    books, _ = _load()
    for book in books:
        if book["book_id"] == book_id:
            return _detail(book, repositories.owns_book(user_id, book_id))
    stored = repositories.get_book(book_id)
    if stored is None:
        return None
    return _detail(stored, repositories.owns_book(user_id, book_id))


def redeem(user_id: str, book_id: str, serial_number: str) -> dict[str, Any]:
    """序列号兑换。

    Demo 规则：序列号必须与某本书登记的一致（或符合通用格式），
    且不能被其他用户占用过。真实产品这里要接出版社的发号系统。
    """
    serial = (serial_number or "").strip().upper()
    books, _ = _load()

    target = next((b for b in books if b["book_id"] == book_id), None)
    if target is None:
        return {
            "ok": False,
            "error_code": "BOOK_NOT_FOUND",
            "message": "没有这本书",
        }

    expected = (target.get("demo_serial") or "").upper()
    valid = bool(serial) and (
        serial == expected
        or (serial.startswith("HAOXUE-") and len(serial) >= 12)
    )
    if not valid:
        return {
            "ok": False,
            "error_code": "INVALID_SERIAL_NUMBER",
            "message": "序列号无效或格式不正确",
        }

    existing = repositories.find_entitlement_by_serial(serial)
    if existing is not None and existing["user_id"] != user_id:
        return {
            "ok": False,
            "error_code": "INVALID_SERIAL_NUMBER",
            "message": "这个序列号已经被其他账号使用过了",
        }
    if existing is not None and existing["user_id"] == user_id:
        return {
            "ok": True,
            "entitlement_id": existing["entitlement_id"],
            "message": "你之前已经兑换过这本书了",
        }

    entitlement_id = repositories.grant_entitlement(
        user_id, book_id, source="serial", serial=serial
    )
    return {
        "ok": True,
        "entitlement_id": entitlement_id,
        "message": f"兑换成功：《{target.get('title', book_id)}》已加入你的题库",
    }


def entitlements(user_id: str) -> dict[str, Any]:
    _, subscription = _load()
    books = list_books(user_id)
    owned = [b for b in books if b["owned"]]
    return {
        "user_id": user_id,
        "owned_books": owned,
        "owned_book_ids": [b["book_id"] for b in owned],
        "subscription_status": "active" if owned else "none",
        "subscription": {
            "status": "trial" if owned else "none",
            "plan_name": subscription.get("plan_name"),
            "price_cents": subscription.get("price_cents", 0),
            "renews_at": None,
        },
    }
