"""作业 / 试卷分析流水线。

契约 §21：分析必须异步。POST 立刻返回 analysis_id，客户端轮询 GET。
本版用 FastAPI BackgroundTasks + 轮询，不引入 WebSocket / Celery——
48H 内够用，而且少一个会挂的组件。

流水线阶段与契约里 Analysis 页面要求显示的 5 步一一对应：
    ✓ Image received
    ✓ Questions detected
    ✓ Answers understood
    ● Finding error patterns
    ○ Updating knowledge state
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .. import db, knowledge, repositories
from ..config import get_settings
from ..errors import (
    ANALYSIS_NOT_FOUND,
    INVALID_ANSWER,
    QUESTION_ALREADY_RESOLVED,
    QUESTION_NOT_CONFIRMABLE,
    QUESTION_NOT_FOUND,
    ApiError,
)
from . import (
    knowledge_service,
    recommendation_service,
    tag_service,
    vlm_service,
    wrong_question_service,
)
from .llm import LlmUnavailable
from .knowledge_service import EvidenceInput
from .vlm_service import RawQuestion, VlmOutcome

logger = logging.getLogger("haoxue")

ANALYSIS_STAGES: tuple[tuple[str, str, str], ...] = (
    ("image_received", "Image received", "已接收图片"),
    ("questions_detected", "Questions detected", "已识别题目"),
    ("answers_understood", "Answers understood", "已理解作答"),
    ("error_patterns", "Finding error patterns", "正在分析错误模式"),
    ("knowledge_updated", "Updating knowledge state", "正在更新知识状态"),
)

DEMO_CACHE_DIR = Path(__file__).resolve().parent.parent / "seed" / "demo_cache"

MIME_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/heic": "heic",
    "image/webp": "webp",
}

# 按文件头判断真实格式。**不要信客户端声明的 content-type 和文件名** ——
# 手工拼 multipart 的客户端（例如 URLSession）默认给文件部分填
# application/octet-stream，文件名也常常没有扩展名。
_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)
_HEIC_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1")


def sniff_image_mime(data: bytes) -> str | None:
    """按魔数识别图片格式，识别不出返回 None。"""
    for signature, mime in _MAGIC_SIGNATURES:
        if data.startswith(signature):
            return mime
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # HEIC/HEIF：ISO-BMFF 容器，第 4-8 字节是 'ftyp'，接着是品牌
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return "image/heic"
    return None


def _stages(
    active: int, failed: bool = False, retrying: bool = False
) -> list[dict[str, str]]:
    """active = 正在进行的阶段下标；之前的算 done，之后的算 pending。

    `failed=True` 时把当前阶段标成 `failed` —— 分析失败时，
    前端要能在进度卡片上明确指出「就是这一步失败的」，而不是让它看起来还在跑。

    `retrying=True` 时把当前阶段标成 `retrying` —— 这是**第三种**状态，
    和 failed 完全不同：模型降级重试时任务仍在推进，只是换了个模型，
    前端应当显示「主模型不可用，正在用备用模型重试」，而不是看起来失败了。
    """
    result: list[dict[str, str]] = []
    for index, (key, label, label_zh) in enumerate(ANALYSIS_STAGES):
        if index < active:
            state = "done"
        elif index == active:
            if failed:
                state = "failed"
            elif retrying:
                state = "retrying"
            else:
                state = "active"
        else:
            state = "pending"
        result.append(
            {"key": key, "label": label, "label_zh": label_zh, "state": state}
        )
    return result


def _progress(
    active: int,
    percent: float,
    *,
    failed: bool = False,
    retrying: bool = False,
    retry_note: str | None = None,
) -> dict[str, Any]:
    stages = _stages(active, failed=failed, retrying=retrying)
    if active < len(ANALYSIS_STAGES):
        key, label, label_zh = ANALYSIS_STAGES[active]
    else:
        key, label, label_zh = "completed", "Completed", "分析完成"
    payload: dict[str, Any] = {
        "percent": round(percent, 3),
        "current_stage": label,
        "current_stage_key": key,
        "current_stage_label_zh": label_zh,
        "stages": stages,
    }
    # 给一句人话，前端可以直接显示。
    #
    # 注意 `retry_note` 不再只在重试时才有 —— 还在用第一个模型时也要告诉
    # 用户"正在用谁识别、第几个模型"，否则一页大试卷识别几分钟期间
    # 进度卡片什么变化都没有。`retrying` 仍然只在真的换过模型后为 true。
    if retry_note:
        payload["retry_note"] = retry_note
    if retrying:
        payload["retrying"] = True
        payload.setdefault("retry_note", "模型暂不可用，正在用备用模型重试")
    return payload


# ---------------------------------------------------------------------------
# Demo 缓存
# ---------------------------------------------------------------------------

def _load_demo_cache(digest: str) -> VlmOutcome | None:
    """命中预置缓存 → 离线也能完整演示。

    缓存内容不是编造的，是**真实跑通一次 VLM 之后录制下来**的结果。
    """
    if not get_settings().demo_cache_enabled:
        return None
    path = DEMO_CACHE_DIR / f"{digest}.json"
    if not path.exists():
        return None
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    outcome = VlmOutcome(generated_by="demo_cache", model="recorded")
    for item in items:
        outcome.questions.append(
            RawQuestion(
                question_number=item.get("question_number", "1"),
                stem=item.get("stem", ""),
                options=item.get("options", {}),
                student_answer=item.get("student_answer"),
                correct_answer=item.get("correct_answer"),
                correctness=item.get("correctness", "unknown"),
                knowledge_point_ids=item.get("knowledge_point_ids", []),
                error_type=item.get("error_type"),
                diagnosis=item.get("diagnosis", ""),
                explanation=item.get("explanation"),
                confidence=item.get("confidence", 0.9),
                difficulty=item.get("difficulty", 0.5),
                bank_question_id=item.get("bank_question_id"),
            )
        )
    outcome.warnings.append("使用预置 Demo 缓存（离线回放）")
    return outcome


def save_demo_cache(digest: str, outcome: VlmOutcome) -> Path:
    DEMO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = DEMO_CACHE_DIR / f"{digest}.json"
    path.write_text(vlm_service.dump_outcome(outcome), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------

@dataclass
class UploadedImage:
    data: bytes
    mime_type: str = "image/jpeg"
    filename: str = ""


def create_analysis(
    user_id: str,
    images: Sequence[UploadedImage],
    *,
    subject: str = "mathematics",
    topic: str | None = None,
    book_id: str | None = None,
    source_name: str | None = None,
    client_request_id: str | None = None,
) -> dict[str, Any]:
    if client_request_id:
        existing = repositories.get_idempotent_response(
            f"homework:{user_id}:{client_request_id}"
        )
        if existing:
            return existing

    analysis_id = db.new_id("ana")
    now = db.to_iso(db.utcnow())
    # 每上传一批就分配一个该用户内递增的批次号（前端「近 50 批」列表用）。
    # 它是展示与排序用的编号；稳定机器标识仍然是 analysis_id。
    batch_number = repositories.next_batch_number(user_id)

    saved: list[dict[str, Any]] = []
    upload_dir = db.uploads_dir() / analysis_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    for index, image in enumerate(images):
        ext = MIME_EXT.get(image.mime_type.lower(), "jpg")
        path = upload_dir / f"{index}.{ext}"
        path.write_bytes(image.data)
        saved.append(
            {
                "index": index,
                "path": str(path),
                "digest": vlm_service.image_digest(image.data),
                "mime_type": image.mime_type,
                "url": f"{get_settings().public_base_url.rstrip('/')}/media/"
                f"{analysis_id}/{index}.{ext}",
            }
        )

    doc: dict[str, Any] = {
        "analysis_id": analysis_id,
        "user_id": user_id,
        "batch_number": batch_number,
        "status": "queued",
        "progress": _progress(0, 0.02),
        "subject": subject,
        "topic": topic,
        "book_id": book_id,
        "source_name": source_name,
        "image_count": len(saved),
        "images": saved,
        "homework_id": None,
        "questions": [],
        "question_results": [],
        "counts": {
            "correct": 0,
            "wrong": 0,
            "partial": 0,
            "unanswered": 0,
            "unknown": 0,
        },
        "knowledge_changes": [],
        "new_wrong_questions": [],
        "next_action": None,
        "error": None,
        "warnings": [],
        "generated_by": None,
        "created_at": now,
        "updated_at": now,
        "finished_at": None,
    }
    # 首次插入用 insert_analysis：并发下批次号撞车会自动换号重试
    repositories.insert_analysis(doc)
    batch_number = doc["batch_number"]
    if client_request_id:
        repositories.put_idempotent_response(
            f"homework:{user_id}:{client_request_id}",
            user_id,
            "POST /api/v1/homework/analyses",
            {
                "analysis_id": analysis_id,
                "batch_number": batch_number,
                "status": "queued",
                "created_at": now,
            },
        )
    return doc


def _update(doc: dict[str, Any], **changes: Any) -> dict[str, Any]:
    doc.update(changes)
    now = db.to_iso(db.utcnow())
    doc["updated_at"] = now
    # 终态时记一次完成时间（只记第一次），前端要显示成功/失败的用时
    if doc.get("status") in ("completed", "failed") and not doc.get("finished_at"):
        doc["finished_at"] = now
    repositories.save_analysis(doc)

    # **终态写入留一条审计记录。**
    #
    # 起因：线上出现过「analysis 文档被改回完成前的快照」——
    # questions / evidence 表里数据都在，但文档变成 0 题、homework_id 为 null。
    # 只靠事后查库分不清"写入丢了"还是"被后写的覆盖了"。
    # 有了这行日志，任何一次终态写入都有迹可循，顺序一目了然。
    if doc.get("status") in ("completed", "failed"):
        logger.info(
            "分析终态写入: %s status=%s 题数=%d homework_id=%s 证据=%d %s",
            doc.get("analysis_id"),
            doc.get("status"),
            len(doc.get("question_results") or []),
            doc.get("homework_id"),
            len(doc.get("knowledge_changes") or []),
            (doc.get("error") or {}).get("error_code") or "",
        )
    return doc


# ---------------------------------------------------------------------------
# 终止态保证：不让任务永久停在 processing
# ---------------------------------------------------------------------------
#
# 线上事故：分析跑在**进程内**的后台任务里（FastAPI BackgroundTasks），
# 服务一重启它就跟着死，而 analysis 记录停在 `processing` 永远不会动 ——
# 前端只能一直转圈。实测 batch 5 就是这样卡死的（部署时杀掉了旧进程）。
#
# 两道防线，覆盖不同的死法：
#   1. **启动时对账**：服务刚起来，不可能有任务在跑，所以所有
#      非终态的分析都是上一世遗留的孤儿，直接判失败。
#   2. **看门狗**：进程活着但任务卡死（模型吊住、死锁）时，
#      靠 `updated_at` 超过阈值来判定。
#
# 两者都只保证"一定进终态"，不尝试续跑 —— 分析没法从中途恢复，
# 重试的代价远低于让学生对着转圈等。

#: 超过这么久没有任何进度更新，就认为任务已经卡死。
STALE_ANALYSIS_SECONDS = 15 * 60


def _fail_orphan(doc: dict[str, Any], code: str, message: str) -> bool:
    """把一个非终态的分析判失败。返回**是否真的写了**。

    ⚠️ **落笔前必须重新读一次。**

    看门狗跑在 `asyncio.to_thread` 的另一个线程里，它的流程是
    「读一批 → 逐个判断 → 写回」。而 `_update` 写的是**整份 doc** ——
    如果某个分析在"被读出来"和"被写回"之间完成了，写回就等于
    **把已经完成的结果覆盖成完成前的快照**：
    题目清空、`homework_id` 变 null、状态退回 failed。

    线上真实事故就长这样：两条分析明明写入了 9 道题和 5 条 Evidence
    （`questions` / `evidence` 表里都还在），但 analysis 文档被改回
    "0 题 / failed / percent 0.25"。

    重读之后如果它已经进终态，就**跳过**并留一条日志 ——
    这是 `_fail_orphan` 唯一有机会发现"自己迟到了"的地方。
    """
    fresh = repositories.get_analysis(doc["analysis_id"])
    if fresh is None:
        return False
    if fresh.get("status") not in ("queued", "processing"):
        logger.warning(
            "跳过 %s：判断时状态是 %s（updated_at=%s），重新读时已经是 %s"
            "（%d 题，homework_id=%s）—— 它在判断与写回之间完成了，不能覆盖",
            doc["analysis_id"],
            doc.get("status"),
            doc.get("updated_at"),
            fresh.get("status"),
            len(fresh.get("question_results") or []),
            fresh.get("homework_id"),
        )
        return False

    doc = fresh
    progress = doc.get("progress") or {}
    for stage in progress.get("stages") or []:
        if stage.get("state") in ("active", "retrying"):
            stage["state"] = "failed"
            break
    logger.warning(
        "判定 %s 为 %s：状态 %s，updated_at=%s，%d 题，homework_id=%s",
        doc["analysis_id"],
        code,
        doc.get("status"),
        doc.get("updated_at"),
        len(doc.get("question_results") or []),
        doc.get("homework_id"),
    )
    _update(
        doc,
        status="failed",
        progress=progress,
        error={"error_code": code, "message": message},
    )
    return True


def recover_interrupted_analyses() -> int:
    """服务启动时对账：把上一世遗留的 `queued` / `processing` 判为失败。

    进程刚起来，**不可能**有分析在跑，所以这些记录一定是孤儿。
    返回处理条数。
    """
    recovered = 0
    for doc in repositories.list_analyses_by_status(("queued", "processing")):
        if _fail_orphan(
            doc,
            "ANALYSIS_INTERRUPTED",
            "服务在分析过程中重启，任务已中断，请重新上传",
        ):
            recovered += 1
    if recovered:
        logger.warning(
            "启动对账：%d 个分析因服务重启中断，已标记为 failed（可重试）", recovered
        )
    return recovered


def reap_stale_analyses(
    max_age_seconds: int = STALE_ANALYSIS_SECONDS,
) -> int:
    """看门狗：把太久没有进度更新的分析判为失败。

    进程还活着但任务卡死时（模型吊住、死锁、忘记收尾）用这个兜底。
    没有它，`processing` 就可能是永久的。
    """
    from datetime import timedelta

    cutoff = db.to_iso(db.utcnow() - timedelta(seconds=max_age_seconds))
    reaped = 0
    for doc in repositories.list_analyses_by_status(("queued", "processing")):
        if str(doc.get("updated_at") or "") >= cutoff:
            continue
        if _fail_orphan(
            doc,
            "ANALYSIS_TIMEOUT",
            f"分析超过 {max_age_seconds // 60} 分钟没有进展，已终止，请重试",
        ):
            reaped += 1
    if reaped:
        logger.warning("看门狗：%d 个分析超时无进展，已标记为 failed", reaped)
    return reaped


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------

async def run_analysis(analysis_id: str) -> None:
    """后台执行整条流水线。异常一律吞掉并写进 doc，不能让后台任务炸掉进程。"""
    doc = repositories.get_analysis(analysis_id)
    if doc is None:
        return
    if doc.get("status") in ("completed", "processing"):
        return

    try:
        _update(doc, status="processing", progress=_progress(0, 0.10))

        # --- 阶段 2/3：VLM 识别题目与作答 ---
        _update(doc, progress=_progress(1, 0.25))
        outcome: VlmOutcome | None = None
        vlm_error: str | None = None
        images = [(Path(i["path"]).read_bytes(), i["mime_type"]) for i in doc["images"]]

        def _on_retry(info: dict[str, Any]) -> None:
            """每次**开始尝试一个模型**时更新进度。

            以前只在"降级到下一个模型"时才触发，于是第一个模型的每一次尝试
            期间回调一次都不发 —— 线上实测一页 9 题的试卷，进度卡片
            在 369 秒里一直停着 25%，只有最后失败时才跳到 failed。
            用户看到的就是一个卡死的进度条。

            现在每次尝试都发：即使还在用第一个模型，也会显示
            「正在用 Qwen3-VL-32B 识别（模型 1/3）」以及第几次尝试。
            `retrying` 只在**真的换过模型**之后才为 true ——
            用它区分"正常识别中"和"主模型不行了正在兜底"。
            """
            failed = info.get("failed_model")
            position = info["model_index"] + 1
            total = info["model_total"]
            if failed:
                note = (
                    f"第 {info['image_index'] + 1} 张：{failed} 未成功，"
                    f"正在用 {info['model']} 重试（模型 {position}/{total}）"
                )
            else:
                note = (
                    f"第 {info['image_index'] + 1} 张：正在用 {info['model']} 识别"
                    f"（模型 {position}/{total}）"
                )
            _update(
                doc,
                progress=_progress(
                    1, 0.25, retrying=bool(failed), retry_note=note
                ),
            )

        try:
            outcome = await vlm_service.analyze_images(
                images,
                subject=doc.get("subject") or "mathematics",
                topic=doc.get("topic"),
                on_retry=_on_retry,
            )
        except LlmUnavailable as exc:
            vlm_error = str(exc)
            # 兜底 1：离线 Demo 缓存
            for meta in doc["images"]:
                cached = _load_demo_cache(meta["digest"])
                if cached is not None:
                    outcome = cached
                    break

        if outcome is None:
            _update(
                doc,
                status="failed",
                progress=_progress(1, 0.25, failed=True),
                error={
                    "error_code": "VLM_TIMEOUT",
                    "message": vlm_error or "视觉模型不可用",
                },
                warnings=doc.get("warnings", []),
            )
            return

        doc["warnings"] = [*doc.get("warnings", []), *outcome.warnings]
        doc["generated_by"] = outcome.generated_by

        if not outcome.questions:
            # 模型正常返回了，但图里没有题目 —— 失败点就是「识别题目」这一步
            _update(
                doc,
                status="failed",
                progress=_progress(1, 0.62, failed=True),
                error={
                    "error_code": "QUESTION_NOT_RECOGNIZED",
                    "message": "没有从图片中识别出题目",
                },
            )
            return

        _update(doc, progress=_progress(3, 0.62))

        # --- 阶段 4：错误模式归因 ---
        _update(doc, progress=_progress(3, 0.75))

        homework_id = db.new_id("hw")
        now = db.to_iso(db.utcnow())
        question_results: list[dict[str, Any]] = []
        new_wrong: list[dict[str, Any]] = []
        evidence_entries: list[EvidenceInput] = []
        counts = {"correct": 0, "wrong": 0, "partial": 0, "unanswered": 0, "unknown": 0}

        for raw in outcome.questions:
            result = _build_question_result(raw, doc, homework_id, now)
            question_results.append(result)
            repositories.save_question(result)
            counts[result["correctness"]] = counts.get(result["correctness"], 0) + 1

            # `unknown`（复核没通过）与 `unanswered`（学生没作答）都不进
            # Knowledge Engine —— 前者是判不出来，后者是没得判，
            # 两种情况都不该影响掌握度。
            if result["correctness"] not in NO_MASTERY_IMPACT:
                for ref in result["knowledge_points"]:
                    evidence_entries.append(
                        EvidenceInput(
                            knowledge_point_id=ref["knowledge_point_id"],
                            result=result["correctness"],
                            difficulty=result["difficulty"],
                            source_type="homework",
                            source_id=homework_id,
                            question_id=result["question_id"],
                            question_stem_hash=result["question_stem_hash"],
                            error_type=result["error_type"],
                            confidence=ref.get("weight", 1.0),
                            detail=result["diagnosis"],
                            answer_excerpt=result["student_answer"],
                        )
                    )

            if result["correctness"] in ("wrong", "partial"):
                # 按**规范题目**归并：同一道题多次做错只留一条待复习项，
                # 但每一次的 attempt 明细都累积进去，历史不丢。
                wrong_doc = wrong_question_service.record_attempt(
                    doc["user_id"],
                    question_stem_hash=result["question_stem_hash"],
                    snapshot=_wrong_question_snapshot(result, doc, homework_id),
                    attempt=_wrong_question_attempt(result, homework_id, now),
                    now=now,
                )
                new_wrong.append(wrong_doc)

        # --- 阶段 5：更新 Knowledge State（唯一入口）---
        _update(doc, progress=_progress(4, 0.88))
        # 标签统计从 Evidence 派生，所以在写 Evidence 前取快照，
        # 才能算出「这次作业让标签变了多少」。
        tag_snapshot = tag_service.tag_stats(doc["user_id"])
        changes = knowledge_service.apply_evidence(doc["user_id"], evidence_entries)

        # --- 标签回显：这些标签现在是什么水平 ---
        # `unknown` / `unanswered` 的题不会产生 Evidence，也就不会影响标签：
        # 前者是"我们不知道学生对不对"，后者是"学生根本没作答"。
        tag_updates = [
            tag_service.apply_answer(
                doc["user_id"],
                result["question_id"],
                result["correctness"] == "correct",
                before=tag_snapshot,
            )
            for result in question_results
            if result["correctness"] not in NO_MASTERY_IMPACT and result.get("tags")
        ]

        homework_doc = {
            "homework_id": homework_id,
            "user_id": doc["user_id"],
            "analysis_id": analysis_id,
            "title": doc.get("source_name") or f"作业分析 {now[:10]}",
            "subtitle": f"{len(question_results)} 题 · 对 {counts['correct']} 错 {counts['wrong']}",
            "subject": doc.get("subject"),
            "topic": doc.get("topic"),
            "book_id": doc.get("book_id"),
            "source_name": doc.get("source_name"),
            "question_ids": [q["question_id"] for q in question_results],
            "created_at": now,
        }
        repositories.save_homework(homework_doc)

        next_action = recommendation_service.next_action(doc["user_id"])

        _update(
            doc,
            status="completed",
            progress=_progress(5, 1.0),
            homework_id=homework_id,
            questions=[q["question_id"] for q in question_results],
            question_results=question_results,
            counts=counts,
            knowledge_changes=[c.model_dump(mode="json") for c in changes],
            new_wrong_questions=new_wrong,
            next_action=next_action.model_dump(mode="json"),
        )
    except Exception as exc:  # noqa: BLE001
        # 未预期的异常：把当前正在进行的阶段标成 failed，方便前端定位
        progress = doc.get("progress") or {}
        stages = progress.get("stages") or []
        for stage in stages:
            if stage.get("state") == "active":
                stage["state"] = "failed"
                break
        _update(
            doc,
            status="failed",
            progress=progress,
            error={
                "error_code": "INTERNAL_ERROR",
                "message": f"分析过程出错: {type(exc).__name__}: {exc}",
            },
        )


def _build_question_result(
    raw: RawQuestion, doc: dict[str, Any], homework_id: str, now: str
) -> dict[str, Any]:
    question_id = db.new_id("q")
    image_url = None
    for meta in doc["images"]:
        if meta["index"] == raw.image_index:
            image_url = meta["url"]
            break

    refs = []
    # 第一个知识点视为主要关联，权重最高
    for position, kp_id in enumerate((raw.knowledge_point_ids or [])[:3]):
        point = knowledge.get_point(kp_id)
        if point is None:
            continue
        refs.append(
            {
                "knowledge_point_id": kp_id,
                "name": point.name,
                "weight": round(max(0.4, 1.0 - position * 0.25), 3),
            }
        )

    # 模型没给出有效知识点时，用标签名反查（题库的 tags 与知识点同名）。
    #
    # 这里原来会回退到 "math.derivative" —— 那是旧知识树里的父节点，
    # 换成扁平清单后已经不存在了，结果就是凭空造出一个幽灵知识点。
    # 现在宁可留空：没有知识点就不写 Evidence，也就不该影响掌握度。
    if not refs:
        for tag in raw.tags[:3]:
            point = knowledge.get_point_by_name(tag)
            if point is not None and point.id not in {r["knowledge_point_id"] for r in refs}:
                refs.append(
                    {"knowledge_point_id": point.id, "name": point.name, "weight": 0.6}
                )

    return {
        "question_id": question_id,
        "user_id": doc["user_id"],
        "homework_id": homework_id,
        "analysis_id": doc["analysis_id"],
        "question_number": raw.question_number,
        "question_type": "single_choice",
        "question_content": raw.stem,
        "question_stem_hash": vlm_service.stem_fingerprint(raw.stem),
        "choices": raw.options,
        "student_answer": raw.student_answer,
        "correct_answer": raw.correct_answer,
        "correctness": raw.correctness,
        # 判成 unknown 时保留下来的「可能答案」。**仅供参考，绝不参与算分**。
        "possible_answer": raw.possible_answer,
        "possible_answer_source": raw.possible_answer_source,
        "knowledge_points": refs,
        # 标签：练习推荐与标签计分用。命中题库时就是题库的标签。
        "tags": list(raw.tags),
        "error_type": raw.error_type,
        "error_label": knowledge.error_label(raw.error_type) if raw.error_type else None,
        "diagnosis": raw.diagnosis,
        "explanation": raw.explanation,
        "confidence": raw.confidence,
        "difficulty": raw.difficulty,
        "image_url": image_url,
        "bank_question_id": raw.bank_question_id,
        "created_at": now,
    }


def _wrong_question_snapshot(
    result: dict[str, Any], doc: dict[str, Any], homework_id: str
) -> dict[str, Any]:
    """错题快照（不含 `wrong_question_id` —— 那由 record_attempt 决定）。

    同一道题多次做错时，这份快照会被**最近一次**覆盖 ——
    学生想看的显然是"我这次错在哪"。
    """
    # 知识点可能为空（模型既没给出知识点、标签也反查不到）。
    # 错题本身仍然要留下来给学生看，只是不挂知识点。
    primary = result["knowledge_points"][0] if result["knowledge_points"] else None
    return {
        "question_id": result["question_id"],
        "knowledge_point_id": primary["knowledge_point_id"] if primary else None,
        "knowledge_point_name": primary["name"] if primary else None,
        "question_number": result["question_number"],
        "question_type": result["question_type"],
        "question_content": result["question_content"],
        "choices": result["choices"],
        "student_answer": result["student_answer"],
        "correct_answer": result["correct_answer"],
        "explanation": result["explanation"],
        "correctness": result["correctness"],
        "error_type": result["error_type"],
        "error_label": result["error_label"],
        "diagnosis": result["diagnosis"],
        "image_url": result["image_url"],
        "source_type": "homework",
        "source_id": homework_id,
        "source_name": doc.get("source_name"),
        "book_id": doc.get("book_id"),
    }


def _wrong_question_attempt(
    result: dict[str, Any], homework_id: str, now: str
) -> dict[str, Any]:
    """这一次作答的明细，累积在错题项里供 UI 展示「做错几次」。"""
    return {
        "question_id": result["question_id"],
        "homework_id": homework_id,
        "student_answer": result["student_answer"],
        "correctness": result["correctness"],
        "created_at": now,
    }


# ---------------------------------------------------------------------------
# 人工确认/纠正标准答案
# ---------------------------------------------------------------------------

#: 人工改判会影响判定的字段。**标准答案以外的 AI 产出全部沿用** ——
#: 题干、选项、知识点、标签、讲解、难度都不动，只换答案再重跑一遍下游。
_CONFIRM_CLEARS_ON_CORRECT = ("error_type", "error_label", "diagnosis")


def confirm_answer(
    user_id: str,
    analysis_id: str,
    question_id: str,
    correct_answer: str,
) -> dict[str, Any]:
    """人工确认标准答案，然后**在本地重跑这道题的下游流程**。

    解决的是识别准确率问题：模型读错答案、或它自己也不确定被复核判成
    `unknown`。学生对着答案册是最可靠的信号源。

    重跑的边界很清楚：

      - **不调 AI** —— 题干、选项、知识点、标签、讲解、难度全部沿用模型已给的
      - 只换掉标准答案，用它重新判定 `correctness`
      - 再走一遍 Evidence → 掌握度 / 标签 / 错题 / counts

    旧的 Evidence 是**删掉再写新的**，不是追加：旧判定的前提就是错的，
    留着会双重计数，而且那条错的永远挂在学生档案上。

    标签统计不用管 —— 它从 Evidence 现算，Evidence 一改自动就对。
    """
    doc = repositories.get_analysis(analysis_id)
    if doc is None or doc.get("user_id") != user_id:
        raise ApiError(ANALYSIS_NOT_FOUND, "分析任务不存在")

    if doc.get("status") != "completed":
        raise ApiError(
            QUESTION_NOT_CONFIRMABLE,
            f"分析还没完成（当前 {doc.get('status')}），不能确认标准答案",
        )

    results: list[dict[str, Any]] = doc.get("question_results") or []
    question = next(
        (item for item in results if item.get("question_id") == question_id), None
    )
    if question is None:
        raise ApiError(QUESTION_NOT_FOUND, "这道题不在该分析里")

    # --- 校验答案合法 ---
    answer = str(correct_answer or "").strip().upper()
    choices = question.get("choices") or {}
    legal = set(choices) if choices else {"A", "B", "C", "D"}
    if answer not in legal:
        raise ApiError(
            INVALID_ANSWER,
            f"{answer or '(空)'} 不是这道题的合法选项（可选 {sorted(legal)}）",
        )

    # --- 重复确认 ---
    already = question.get("confirmed_answer")
    if already:
        if already == answer:
            # 同一个答案再提交 → 回放，**绝不重复写 Evidence / 改掌握度**
            return _confirmation_body(doc, question, replayed=True)
        raise ApiError(
            QUESTION_ALREADY_RESOLVED,
            f"这道题的标准答案已确认为 {already}，不能再改成 {answer}",
        )

    # --- 学生没作答就没有可判定的东西 ---
    student = question.get("student_answer")
    if not student:
        raise ApiError(
            QUESTION_NOT_CONFIRMABLE,
            "学生未作答（unanswered），补充标准答案也判不出对错",
        )

    homework_id = doc.get("homework_id") or ""
    now = db.to_iso(db.utcnow())
    # AI 原来的说法（可能是 correct_answer，也可能只是 possible_answer 里的猜测）
    original = question.get("correct_answer") or question.get("possible_answer")

    new_correctness = "correct" if str(student).upper() == answer else "wrong"

    # --- ① 旧 Evidence 作废 ---
    # unknown / unanswered 本来就没有 Evidence，这里删到 0 条是正常的；
    # 而纠正一道已判定的题（wrong → correct）就必须真的删掉旧的。
    removed_evidence = repositories.delete_evidence_for_question(
        user_id, homework_id, question_id
    )

    # --- ② 按新判定重写 Evidence，掌握度随之更新 ---
    changes = []
    if new_correctness not in NO_MASTERY_IMPACT:
        changes = knowledge_service.apply_evidence(
            user_id,
            [
                EvidenceInput(
                    knowledge_point_id=ref["knowledge_point_id"],
                    result=new_correctness,
                    difficulty=question.get("difficulty") or 0.5,
                    source_type="homework",
                    source_id=homework_id,
                    question_id=question_id,
                    question_stem_hash=question.get("question_stem_hash"),
                    error_type=(
                        None
                        if new_correctness == "correct"
                        else question.get("error_type")
                    ),
                    confidence=1.0,
                    detail="学生人工确认标准答案后重新判定",
                    answer_excerpt=str(student),
                )
                for ref in (question.get("knowledge_points") or [])
            ],
        )

    # --- ③ 更新题目本身（分析文档 + questions 表两处）---
    question["correct_answer"] = answer
    question["correctness"] = new_correctness
    question["confirmed_answer"] = answer
    question["confirmed_at"] = now
    question["confirmed_source"] = "user"
    question["answer_source"] = "user"
    if question.get("original_correct_answer") is None:
        question["original_correct_answer"] = original
    question["correction_count"] = int(question.get("correction_count") or 0) + 1
    if new_correctness == "correct":
        # 判对了就不该再显示"你的错误类型是…"—— 那是基于 AI 那个错答案给的诊断。
        # 仍然判错时保留 AI 的诊断（用户要求：答案以外的 AI 产出继续用）。
        for field in _CONFIRM_CLEARS_ON_CORRECT:
            question[field] = None if field != "diagnosis" else ""
    repositories.save_question(question)

    # --- ④ 错题投影跟着重算 ---
    # 判错 → 记一次作答（新建或合并成一条待复习项）
    # 判对 → 把这道题对应的待复习项收掉
    if new_correctness in ("wrong", "partial"):
        wrong_question_service.record_attempt(
            user_id,
            question_stem_hash=question["question_stem_hash"],
            snapshot=_wrong_question_snapshot(question, doc, homework_id),
            attempt=_wrong_question_attempt(question, homework_id, now),
            now=now,
        )
    else:
        wrong_question_service.resolve_for_question(
            user_id, question.get("question_stem_hash") or "", question_id
        )

    # --- ⑤ 重算 counts 并保存分析文档 ---
    counts = {"correct": 0, "wrong": 0, "partial": 0, "unanswered": 0, "unknown": 0}
    for item in results:
        key = item.get("correctness", "unknown")
        counts[key] = counts.get(key, 0) + 1
    doc["question_results"] = results
    doc["counts"] = counts
    repositories.save_analysis(doc)

    logger.info(
        "人工确认标准答案: analysis=%s question=%s %s -> %s（%s），"
        "旧 Evidence %d 条已作废",
        analysis_id,
        question_id,
        original or "unknown",
        answer,
        new_correctness,
        removed_evidence,
    )

    return _confirmation_body(doc, question, replayed=False)


def _confirmation_body(
    doc: dict[str, Any], question: dict[str, Any], *, replayed: bool
) -> dict[str, Any]:
    """确认接口的响应体。重放时走同一段代码，保证两次返回结构一致。"""
    counts = doc.get("counts") or {}
    return {
        "analysis_id": doc["analysis_id"],
        "question_id": question["question_id"],
        "student_answer": question.get("student_answer"),
        "correct_answer": question.get("correct_answer"),
        "correctness": question.get("correctness", "unknown"),
        "confirmation": {
            "source": question.get("confirmed_source") or "user",
            "confirmed_at": question.get("confirmed_at"),
            "original_correct_answer": question.get("original_correct_answer"),
            "correction_count": int(question.get("correction_count") or 0),
        },
        "analysis_summary": {
            "question_count": len(doc.get("question_results") or []),
            "correct_count": counts.get("correct", 0),
            "wrong_count": counts.get("wrong", 0),
            "partial_count": counts.get("partial", 0),
            "unanswered_count": counts.get("unanswered", 0),
            "unknown_count": counts.get("unknown", 0),
        },
        "wrong_question": _current_wrong_question(doc["user_id"], question),
        "next_action": _safe_next_action(doc["user_id"]),
        "replayed": replayed,
    }


def _current_wrong_question(
    user_id: str, question: dict[str, Any]
) -> dict[str, Any] | None:
    """这道题**当前**的待复习项。

    只返回 `status == "open"` 的那条 —— 语义就是"这道题现在是不是还要复习"。
    改判为答对、或者别的原因已经收掉的，返回 None。
    """
    stem = question.get("question_stem_hash")
    if not stem:
        return None
    found = repositories.find_wrong_question_by_stem(user_id, stem)
    if found is None or found.get("status") != "open":
        return None
    return {
        "wrong_question_id": found["wrong_question_id"],
        "status": "open",
        "attempt_count": int(found.get("attempt_count") or 1),
    }


def _safe_next_action(user_id: str) -> dict[str, Any] | None:
    try:
        return recommendation_service.next_action(user_id).model_dump(mode="json")
    except Exception:  # noqa: BLE001 - 推荐算不出来不该让确认失败
        return None


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def build_detail(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "analysis_id": doc["analysis_id"],
        "batch_number": doc.get("batch_number"),
        "status": doc["status"],
        "progress": doc["progress"],
        "homework_id": doc.get("homework_id"),
        "user_id": doc["user_id"],
        "subject": doc.get("subject", "mathematics"),
        "topic": doc.get("topic"),
        "source_name": doc.get("source_name"),
        "book_id": doc.get("book_id"),
        "image_count": doc.get("image_count", 0),
        "questions": doc.get("questions", []),
        "question_results": doc.get("question_results", []),
        "correct_count": doc.get("counts", {}).get("correct", 0),
        "wrong_count": doc.get("counts", {}).get("wrong", 0),
        "partial_count": doc.get("counts", {}).get("partial", 0),
        # 学生没作答（**不计入掌握度**，但要让前端能单独提示"这题你没做"）
        "unanswered_count": doc.get("counts", {}).get("unanswered", 0),
        # 复核没通过 / 判定不可信（同样不计入掌握度）
        "unknown_count": doc.get("counts", {}).get("unknown", 0),
        "knowledge_changes": doc.get("knowledge_changes", []),
        "new_wrong_questions": [
            _wrong_summary(item) for item in doc.get("new_wrong_questions", [])
        ],
        "next_action": doc.get("next_action"),
        "error": doc.get("error"),
        "warnings": doc.get("warnings", []),
        "generated_by": doc.get("generated_by"),
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
        "finished_at": doc.get("finished_at"),
    }


# ---------------------------------------------------------------------------
# 上传批次列表（前端的「近 50 批」）
# ---------------------------------------------------------------------------

#: 这些判定结果**不进入 Knowledge Engine、不动标签** —— 两种都"没法算分"：
#:
#:   unknown     复核没通过，判定不可信
#:   unanswered  学生没作答，没有可判定的对象
#:
#: 它们的区别在于**对用户的含义**：前者是"我没算准"，后者是"你没做"。
#: 分开之后前端能给出不同的提示，而不是一律「本题不计入统计」。
NO_MASTERY_IMPACT = frozenset({"unknown", "unanswered"})

# 内部状态 -> 对外的三态。前端只关心「正在 / 成功 / 失败」。
BATCH_STATE = {
    "queued": "processing",
    "processing": "processing",
    "completed": "success",
    "failed": "failed",
}

BATCH_STATE_LABEL_ZH = {
    "processing": "正在处理",
    "success": "成功",
    "failed": "失败",
}


def _duration_seconds(doc: dict[str, Any]) -> float | None:
    start = db.from_iso(doc.get("created_at"))
    end = db.from_iso(doc.get("finished_at"))
    if start is None or end is None:
        return None
    return round((end - start).total_seconds(), 2)


def build_batch_summary(doc: dict[str, Any]) -> dict[str, Any]:
    """批次列表里的一项。

    按需求：成功 / 失败要带时间，进行中要带上与详情接口**完全一样**的进度结构。
    """
    state = BATCH_STATE.get(str(doc.get("status")), "processing")
    counts = doc.get("counts") or {}

    item: dict[str, Any] = {
        "batch_number": doc.get("batch_number"),
        "analysis_id": doc["analysis_id"],
        "state": state,
        "state_label": BATCH_STATE_LABEL_ZH[state],
        # 原始状态也保留，方便客户端排查（queued/processing/completed/failed）
        "status": doc.get("status"),
        "image_count": doc.get("image_count", 0),
        "source_name": doc.get("source_name"),
        "created_at": doc.get("created_at"),
        "finished_at": doc.get("finished_at"),
        "progress": None,
        "duration_seconds": None,
        "question_count": None,
        "correct_count": None,
        "wrong_count": None,
        "error": None,
    }

    if state == "processing":
        # 进行中：给和详情接口一模一样的进度对象
        item["progress"] = doc.get("progress")
    else:
        item["duration_seconds"] = _duration_seconds(doc)

    if state == "success":
        item["question_count"] = len(doc.get("question_results") or [])
        item["correct_count"] = counts.get("correct", 0)
        item["wrong_count"] = counts.get("wrong", 0)

    if state == "failed":
        item["error"] = doc.get("error")

    return item


def list_batches(user_id: str, limit: int = 50) -> dict[str, Any]:
    """最近若干批上传。最新的在前（按批次号倒序）。"""
    limit = max(1, min(int(limit), 50))
    docs = repositories.list_analysis_batches(user_id, limit=limit)
    items = [build_batch_summary(doc) for doc in docs]

    # 汇总是对**全部**批次统计的，不受 limit 影响，方便前端显示角标
    all_docs = repositories.list_analysis_batches(user_id, limit=500)
    states = [BATCH_STATE.get(str(d.get("status")), "processing") for d in all_docs]

    return {
        "total": len(all_docs),
        "processing_count": states.count("processing"),
        "success_count": states.count("success"),
        "failed_count": states.count("failed"),
        "limit": limit,
        "items": items,
    }


def _wrong_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "wrong_question_id": item["wrong_question_id"],
        "question_id": item["question_id"],
        "question_number": item.get("question_number", ""),
        "question_content": item.get("question_content", ""),
        "knowledge_point_id": item.get("knowledge_point_id"),
        "knowledge_point_name": item.get("knowledge_point_name"),
        "error_type": item.get("error_type"),
        "error_label": item.get("error_label"),
        "status": item.get("status", "open"),
        "created_at": item["created_at"],
    }
