"""元信息接口。

存在的理由：错误码、能力清单这类「契约常量」如果只写在文档里，
前端就只能手抄 —— 抄错或过期都不会有人发现。让它们能被**运行时拉取**，
前端可以生成映射表，也能在 CI 里比对。

这些接口是纯常量，不需要鉴权、不读写数据库。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..errors import all_error_codes, error_code_catalog
from ..schemas import (
    ErrorCodeCatalogResponse,
    ErrorCodeEntry,
)
from .. import knowledge

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])


@router.get(
    "/error-codes",
    response_model=ErrorCodeCatalogResponse,
    summary="全部错误码（含默认 HTTP 状态与含义）",
)
async def list_error_codes() -> ErrorCodeCatalogResponse:
    """客户端应据此生成错误文案映射表，而不是手抄文档。

    同一个清单也渲染进了 OpenAPI（`ErrorInfo.error_code` 是 enum），
    所以 `GET /openapi.json` 里也能拿到。
    """
    items = [ErrorCodeEntry(**entry) for entry in error_code_catalog()]
    return ErrorCodeCatalogResponse(
        count=len(items), codes=all_error_codes(), items=items
    )


@router.get("/knowledge-points", summary="全部知识点（id + 名称）")
async def list_knowledge_points() -> dict[str, object]:
    """知识点清单。前端不要写死，一律以这里（或 /api/v1/knowledge）为准。"""
    return {
        "count": len(knowledge.all_points()),
        "items": [
            {"id": point.id, "name": point.name, "description": point.description}
            for point in knowledge.all_points()
        ],
    }
