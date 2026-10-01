"""用户初始化。

比赛 Demo 不需要完整登录体系，但保留 guest → token 的形态，
以后接真实账号时客户端不用改。
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import repositories
from ..dependencies import DEMO_DEVICE_ID, ensure_demo_user
from ..schemas import GuestAuthRequest, GuestAuthResponse
from ..services import book_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/guest", response_model=GuestAuthResponse)
async def guest(payload: GuestAuthRequest) -> GuestAuthResponse:
    device_id = (payload.device_id or "").strip() or DEMO_DEVICE_ID
    user = repositories.find_user_by_device(device_id)
    if user is None:
        user = repositories.create_user(
            device_id=device_id, display_name=payload.display_name or "同学"
        )
        book_service.ensure_default_entitlements(user["user_id"])
    token = repositories.issue_token(user["user_id"])
    return GuestAuthResponse(
        user_id=user["user_id"],
        access_token=token,
        is_demo=bool(user.get("is_demo")),
        created_at=user["created_at"],
    )


@router.get("/demo-user", response_model=GuestAuthResponse)
async def demo_user() -> GuestAuthResponse:
    """便捷入口：直接拿到固定的 Demo 用户与 token。

    前端联调时甚至可以不调用它——不带 Authorization 头时后端会自动
    落到同一个 Demo 用户上。
    """
    user = ensure_demo_user()
    token = repositories.issue_token(user["user_id"])
    return GuestAuthResponse(
        user_id=user["user_id"],
        access_token=token,
        is_demo=True,
        created_at=user["created_at"],
    )
