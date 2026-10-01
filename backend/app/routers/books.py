"""图书 / 题库权限 / 订阅。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..dependencies import current_user
from ..errors import BOOK_NOT_FOUND, BOOK_NOT_OWNED, ApiError
from ..schemas import (
    BookDetail,
    BookListResponse,
    EntitlementsResponse,
    RedeemRequest,
    RedeemResponse,
)
from ..services import book_service

router = APIRouter(prefix="/api/v1/books", tags=["books"])
entitlements_router = APIRouter(prefix="/api/v1/entitlements", tags=["books"])


@router.get("", response_model=BookListResponse)
async def list_books(
    user: dict[str, Any] = Depends(current_user),
) -> BookListResponse:
    items = book_service.list_books(user["user_id"])
    return BookListResponse(total=len(items), items=items)


@router.get("/{book_id}", response_model=BookDetail)
async def get_book(
    book_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> BookDetail:
    payload = book_service.get_book(user["user_id"], book_id)
    if payload is None:
        raise ApiError(BOOK_NOT_FOUND, "没有这本书")
    return BookDetail(**payload)


@router.post("/{book_id}/redeem", response_model=RedeemResponse)
async def redeem(
    book_id: str,
    payload: RedeemRequest,
    user: dict[str, Any] = Depends(current_user),
) -> RedeemResponse:
    result = book_service.redeem(user["user_id"], book_id, payload.serial_number)
    if not result["ok"]:
        code = result.get("error_code", BOOK_NOT_FOUND)
        raise ApiError(code, result.get("message", "兑换失败"))
    return RedeemResponse(
        book_id=book_id,
        entitled=True,
        entitlement_id=result.get("entitlement_id"),
        message=result.get("message", "兑换成功"),
    )


@entitlements_router.get("", response_model=EntitlementsResponse)
async def get_entitlements(
    user: dict[str, Any] = Depends(current_user),
) -> EntitlementsResponse:
    return EntitlementsResponse(**book_service.entitlements(user["user_id"]))
