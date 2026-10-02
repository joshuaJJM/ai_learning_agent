"""作业 / 试卷上传与分析。

异步：POST 立刻返回 analysis_id（202），客户端轮询 GET。

幂等（契约 §22）：支持 `Idempotency-Key` 请求头，以及表单里的
`client_request_id`。手机网络不稳时 iOS 重试不会把 Mastery 更新两次。
"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    UploadFile,
    status,
)

from .. import repositories
from ..dependencies import current_user
from ..errors import ANALYSIS_NOT_FOUND, INVALID_IMAGE, ApiError
from ..schemas import AnalysisCreateResponse, AnalysisDetailResponse
from ..services import homework_service

router = APIRouter(prefix="/api/v1/homework", tags=["homework"])

MAX_IMAGE_BYTES = 12 * 1024 * 1024  # 12 MB / 张


@router.post(
    "/analyses",
    response_model=AnalysisCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="上传作业图片并创建异步分析任务",
)
async def create_analysis(
    background: BackgroundTasks,
    images: list[UploadFile] | None = File(
        default=None, description="一张或多张题目/试卷图片（字段名 images，可重复）"
    ),
    subject: str = Form(default="mathematics"),
    topic: str | None = Form(default=None),
    book_id: str | None = Form(default=None),
    source_name: str | None = Form(default=None, description="例如：某作业本第 32 页"),
    client_request_id: str | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: dict[str, Any] = Depends(current_user),
) -> AnalysisCreateResponse:
    if not images:
        raise ApiError(INVALID_IMAGE, "没有收到任何图片（表单字段名应为 images）")

    payloads: list[homework_service.UploadedImage] = []
    for upload in images:
        data = await upload.read()
        if not data:
            continue
        if len(data) > MAX_IMAGE_BYTES:
            raise ApiError(
                INVALID_IMAGE,
                f"图片过大：{len(data) // 1024 // 1024} MB，上限 "
                f"{MAX_IMAGE_BYTES // 1024 // 1024} MB",
            )

        # 只认文件头，不信客户端声明的 content-type / 文件名
        mime = homework_service.sniff_image_mime(data)
        if mime is None:
            declared = upload.content_type or "未知"
            raise ApiError(
                INVALID_IMAGE,
                f"这个文件不像是图片（声明的类型是 {declared}，"
                f"但文件头既不是 JPEG/PNG/HEIC 也不是 WebP）",
            )
        payloads.append(
            homework_service.UploadedImage(
                data=data, mime_type=mime, filename=upload.filename or ""
            )
        )

    if not payloads:
        raise ApiError(INVALID_IMAGE, "上传的图片都是空文件")

    doc = homework_service.create_analysis(
        user["user_id"],
        payloads,
        subject=subject,
        topic=topic,
        book_id=book_id,
        source_name=source_name,
        client_request_id=idempotency_key or client_request_id,
    )

    # 已经跑完（幂等命中缓存）就不再排任务
    if doc.get("status") == "queued":
        background.add_task(homework_service.run_analysis, doc["analysis_id"])

    return AnalysisCreateResponse(
        analysis_id=doc["analysis_id"],
        status=doc["status"],
        created_at=doc["created_at"],
    )


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisDetailResponse,
    summary="轮询分析进度与结果",
)
async def get_analysis(
    analysis_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> AnalysisDetailResponse:
    doc = repositories.get_analysis(analysis_id)
    if doc is None or doc.get("user_id") != user["user_id"]:
        raise ApiError(ANALYSIS_NOT_FOUND, "分析任务不存在")
    return AnalysisDetailResponse(**homework_service.build_detail(doc))


@router.get("/analyses", summary="最近的分析记录")
async def list_analyses(
    limit: int = 20,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    docs = repositories.list_analyses(user["user_id"], limit=limit)
    return {
        "user_id": user["user_id"],
        "total": len(docs),
        "items": [
            {
                "analysis_id": d["analysis_id"],
                "status": d["status"],
                "source_name": d.get("source_name"),
                "correct_count": d.get("counts", {}).get("correct", 0),
                "wrong_count": d.get("counts", {}).get("wrong", 0),
                "created_at": d["created_at"],
            }
            for d in docs
        ],
    }
