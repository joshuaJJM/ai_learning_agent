"""图书 / 题库权限 / 订阅。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import repositories
from ..dependencies import current_user, idempotency_key_header
from ..errors import (
    BOOK_NOT_FOUND,
    IDEMPOTENCY_CONFLICT,
    ApiError,
)
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
    header_key: str | None = Depends(idempotency_key_header),
) -> RedeemResponse:
    endpoint = f"POST /api/v1/books/{book_id}/redeem"
    idem_key = (
        f"redeem:{user['user_id']}:{header_key}" if header_key else None
    )

    # 兑换本身是幂等的（同一序列号重复兑换会回「你已经兑换过这本书」），
    # 但**并发**两个相同请求可能各发一次 entitlement，所以照样先占位。
    if idem_key and not repositories.reserve_idempotency(
        idem_key, user["user_id"], endpoint
    ):
        cached = repositories.get_idempotent_response(idem_key)
        if cached:
            return RedeemResponse(**cached)
        raise ApiError(IDEMPOTENCY_CONFLICT, "同一个请求正在处理中，请稍后重试")

    result = book_service.redeem(user["user_id"], book_id, payload.serial_number)
    if not result["ok"]:
        if idem_key:
            repositories.release_idempotency(idem_key)
        code = result.get("error_code", BOOK_NOT_FOUND)
        raise ApiError(code, result.get("message", "兑换失败"))

    body = {
        "book_id": book_id,
        "entitled": True,
        "entitlement_id": result.get("entitlement_id"),
        "message": result.get("message", "兑换成功"),
    }
    if idem_key:
        repositories.put_idempotent_response(idem_key, user["user_id"], endpoint, body)
    return RedeemResponse(**body)


@entitlements_router.get("", response_model=EntitlementsResponse)
async def get_entitlements(
    user: dict[str, Any] = Depends(current_user),
) -> EntitlementsResponse:
    return EntitlementsResponse(**book_service.entitlements(user["user_id"]))
