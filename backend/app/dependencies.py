"""鉴权依赖。

**本版刻意从简（单用户 Demo）——这一点必须写进给前端的说明里：**

  1. 带 `Authorization: Bearer <token>` 且 token 有效 → 使用该用户。
  2. **完全不带 Authorization 头** → 自动落到一个固定的 Demo 用户。
     这样前端在联调阶段可以完全不管鉴权，直接调接口。
  3. 带了头但 token 无效 → 401 UNAUTHORIZED（不静默降级，
     否则前端把拼错的 token 带上去会得到"看起来正常"的错误数据）。

如果比赛后要接真实账号体系，只需替换 `current_user`，业务代码不用动。
"""

from __future__ import annotations

from typing import Any

from fastapi import Header

from . import repositories
from .errors import UNAUTHORIZED, ApiError
from .services import book_service

DEMO_DEVICE_ID = "demo-device"


def ensure_demo_user() -> dict[str, Any]:
    user = repositories.find_user_by_device(DEMO_DEVICE_ID)
    if user is None:
        user = repositories.create_user(
            device_id=DEMO_DEVICE_ID, display_name="同学", is_demo=True
        )
        book_service.ensure_default_entitlements(user["user_id"])
    return user


async def current_user(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    if not authorization:
        return ensure_demo_user()

    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise ApiError(UNAUTHORIZED, "Authorization 头格式应为 'Bearer <token>'")

    user_id = repositories.resolve_token(token)
    if not user_id:
        raise ApiError(UNAUTHORIZED, "token 无效或已过期")

    user = repositories.get_user(user_id)
    if user is None:
        raise ApiError(UNAUTHORIZED, "用户不存在")
    return user


# ---------------------------------------------------------------------------
# 幂等键
# ---------------------------------------------------------------------------
#
# 契约说「**推荐**带 `Idempotency-Key` 请求头，或在请求体里带 `client_request_id`」。
# 但一开始只有 homework 真的读了这个头，practice / tutor 只看请求体 ——
# 客户端照文档只发请求头的话，这两个接口的重试**拿不到承诺的幂等保护**。
#
# 所以把读取收敛成一个依赖，所有写接口统一声明它，别再各写各的。

async def idempotency_key_header(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> str | None:
    """从请求头取幂等键。两种常见写法都认。"""
    return (idempotency_key or x_idempotency_key or "").strip() or None


def resolve_idempotency_key(header_key: str | None, body_key: str | None) -> str | None:
    """请求头优先，其次请求体。两者都认，避免客户端二选一时踩空。"""
    return (header_key or body_key or "").strip() or None
