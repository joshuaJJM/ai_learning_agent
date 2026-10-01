"""首页聚合接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..dependencies import current_user
from ..schemas import HomeResponse
from ..services import home_service

router = APIRouter(prefix="/api/v1/home", tags=["home"])


@router.get("", response_model=HomeResponse)
async def get_home(user: dict[str, Any] = Depends(current_user)) -> HomeResponse:
    return HomeResponse(**home_service.build_home(user))
