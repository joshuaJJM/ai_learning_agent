"""作业 / 试卷上传与分析。

异步：POST 立刻返回 analysis_id（202），客户端轮询 GET。

幂等：支持 `Idempotency-Key`（以及 `X-Idempotency-Key`）请求头，
以及表单里的 `client_request_id`。手机网络不稳时 iOS 重试不会把
Mastery 更新两次。

**注意**：幂等键统一走 `dependencies.idempotency_key_header`，
不要在这里自己写 `Header(alias=...)` —— 之前这个接口就是自己写的，
只认标准头，导致文档承诺的 `X-Idempotency-Key` 别名在这里失效。
tests/test_idempotency_headers.py 有一条结构性测试盯着这件事。
"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    UploadFile,
    status,
)

from .. import repositories
from ..dependencies import (
    current_user,
    idempotency_key_header,
    resolve_idempotency_key,
)
from ..errors import (
    ANALYSIS_NOT_FOUND,
    IDEMPOTENCY_CONFLICT,
    INVALID_IMAGE,
    ApiError,
)
from ..schemas import (
    AnalysisCreateResponse,
    AnalysisDetailResponse,
    BatchListResponse,
    ConfirmAnswerRequest,
    ConfirmAnswerResponse,
)
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
    header_key: str | None = Depends(idempotency_key_header),
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
        client_request_id=resolve_idempotency_key(header_key, client_request_id),
    )

    # 已经跑完（幂等命中缓存）就不再排任务
    if doc.get("status") == "queued":
        background.add_task(homework_service.run_analysis, doc["analysis_id"])

    return AnalysisCreateResponse(
        analysis_id=doc["analysis_id"],
        batch_number=doc.get("batch_number"),
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


@router.post(
    "/analyses/{analysis_id}/questions/{question_id}/confirm-answer",
    response_model=ConfirmAnswerResponse,
    summary="人工确认/纠正一道题的标准答案（重跑下游，不调 AI）",
)
async def confirm_answer(
    analysis_id: str,
    question_id: str,
    payload: ConfirmAnswerRequest,
    user: dict[str, Any] = Depends(current_user),
    header_key: str | None = Depends(idempotency_key_header),
) -> ConfirmAnswerResponse:
    """模型读错答案、或判成 `unknown` 时，由学生人工补上标准答案。

    **重跑的边界**：只换标准答案，题干 / 选项 / 知识点 / 标签 / 讲解全部
    沿用模型已给的；然后重新判定对错，并走一遍
    Evidence → 掌握度 / 标签 / 错题 / 统计。**不调 AI**。

    旧的 Evidence 会被**删掉再写新的**（不是追加），否则掌握度会同时算上
    "旧判定的错"和"新判定的对"。

    | 情况 | 结果 |
    |---|---|
    | 学生未作答（`unanswered`） | `409 QUESTION_NOT_CONFIRMABLE` —— 补答案也判不出来 |
    | 分析还没跑完 | `409 QUESTION_NOT_CONFIRMABLE` |
    | 选项不在该题的 choices 里 | `400 INVALID_ANSWER` |
    | 这道题不属于该分析 | `404 QUESTION_NOT_FOUND` |
    | 已确认过、这次答案**相同** | `200`，`replayed: true`，**不重复写 Evidence** |
    | 已确认过、这次答案**不同** | `409 QUESTION_ALREADY_RESOLVED` —— 不允许静默覆盖 |
    """
    endpoint = "POST /api/v1/homework/analyses/{id}/questions/{id}/confirm-answer"
    raw_key = resolve_idempotency_key(header_key, payload.client_request_id)
    idem_key = (
        f"confirm-answer:{user['user_id']}:{analysis_id}:{question_id}:{raw_key}"
        if raw_key
        else None
    )

    if idem_key and not repositories.reserve_idempotency(
        idem_key, user["user_id"], endpoint
    ):
        cached = repositories.get_idempotent_response(idem_key)
        if cached:
            return ConfirmAnswerResponse(**cached)
        raise ApiError(IDEMPOTENCY_CONFLICT, "同一个请求正在处理中，请稍后重试")

    try:
        body = homework_service.confirm_answer(
            user["user_id"], analysis_id, question_id, payload.correct_answer
        )
    except ApiError:
        # 业务失败要释放幂等占位，否则客户端改答案重试会被卡住
        if idem_key:
            repositories.release_idempotency(idem_key)
        raise

    if idem_key:
        repositories.put_idempotent_response(idem_key, user["user_id"], endpoint, body)
    return ConfirmAnswerResponse(**body)


@router.get(
    "/batches",
    response_model=BatchListResponse,
    summary="最近的上传批次（默认 50，最新的在前）",
)
async def list_batches(
    limit: int = 50,
    user: dict[str, Any] = Depends(current_user),
) -> BatchListResponse:
    """前端「上传记录」列表用。

    每批带一个该用户内递增的 `batch_number`：
      - `state="processing"`：带 `progress`（与详情接口完全一样，可直接渲染进度卡片）
      - `state="success"`   ：带 `finished_at` / `duration_seconds` 与对错统计
      - `state="failed"`    ：带 `finished_at` / `duration_seconds` 与 `error`
    """
    return BatchListResponse(**homework_service.list_batches(user["user_id"], limit=limit))


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
                "batch_number": d.get("batch_number"),
                "status": d["status"],
                "source_name": d.get("source_name"),
                "correct_count": d.get("counts", {}).get("correct", 0),
                "wrong_count": d.get("counts", {}).get("wrong", 0),
                "created_at": d["created_at"],
            }
            for d in docs
        ],
    }
