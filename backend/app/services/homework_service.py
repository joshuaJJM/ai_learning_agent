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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .. import db, knowledge, repositories
from ..config import get_settings
from . import knowledge_service, recommendation_service, tag_service, vlm_service
from .llm import LlmUnavailable
from .knowledge_service import EvidenceInput
from .vlm_service import RawQuestion, VlmOutcome

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


def _stages(active: int, failed: bool = False) -> list[dict[str, str]]:
    """active = 正在进行的阶段下标；之前的算 done，之后的算 pending。

    `failed=True` 时把当前阶段标成 `failed` —— 分析失败时，
    前端要能在进度卡片上明确指出「就是这一步失败的」，而不是让它看起来还在跑。
    """
    result: list[dict[str, str]] = []
    for index, (key, label, label_zh) in enumerate(ANALYSIS_STAGES):
        if index < active:
            state = "done"
        elif index == active:
            state = "failed" if failed else "active"
        else:
            state = "pending"
        result.append(
            {"key": key, "label": label, "label_zh": label_zh, "state": state}
        )
    return result


def _progress(active: int, percent: float, *, failed: bool = False) -> dict[str, Any]:
    stages = _stages(active, failed=failed)
    if active < len(ANALYSIS_STAGES):
        key, label, label_zh = ANALYSIS_STAGES[active]
    else:
        key, label, label_zh = "completed", "Completed", "分析完成"
    return {
        "percent": round(percent, 3),
        "current_stage": label,
        "current_stage_key": key,
        "current_stage_label_zh": label_zh,
        "stages": stages,
    }


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
        "counts": {"correct": 0, "wrong": 0, "partial": 0, "unknown": 0},
        "knowledge_changes": [],
        "new_wrong_questions": [],
        "next_action": None,
        "error": None,
        "warnings": [],
        "generated_by": None,
        "created_at": now,
        "updated_at": now,
    }
    repositories.save_analysis(doc)
    if client_request_id:
        repositories.put_idempotent_response(
            f"homework:{user_id}:{client_request_id}",
            user_id,
            "POST /api/v1/homework/analyses",
            {"analysis_id": analysis_id, "status": "queued", "created_at": now},
        )
    return doc


def _update(doc: dict[str, Any], **changes: Any) -> dict[str, Any]:
    doc.update(changes)
    doc["updated_at"] = db.to_iso(db.utcnow())
    repositories.save_analysis(doc)
    return doc


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
        try:
            outcome = await vlm_service.analyze_images(
                images, subject=doc.get("subject") or "mathematics", topic=doc.get("topic")
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
        counts = {"correct": 0, "wrong": 0, "partial": 0, "unknown": 0}

        for raw in outcome.questions:
            result = _build_question_result(raw, doc, homework_id, now)
            question_results.append(result)
            repositories.save_question(result)
            counts[result["correctness"]] = counts.get(result["correctness"], 0) + 1

            # 判定为 unknown 的题（模型之间有分歧）不进 Knowledge Engine——
            # 判不出来就不该影响掌握度。
            if result["correctness"] != "unknown":
                for ref in result["knowledge_points"]:
                    evidence_entries.append(
                        EvidenceInput(
                            knowledge_point_id=ref["knowledge_point_id"],
                            result=result["correctness"],
                            difficulty=result["difficulty"],
                            source_type="homework",
                            source_id=homework_id,
                            question_id=result["question_id"],
                            error_type=result["error_type"],
                            confidence=ref.get("weight", 1.0),
                            detail=result["diagnosis"],
                            answer_excerpt=result["student_answer"],
                        )
                    )

            if result["correctness"] in ("wrong", "partial"):
                wrong_doc = _build_wrong_question(result, doc, homework_id, now)
                repositories.save_wrong_question(wrong_doc)
                new_wrong.append(wrong_doc)

        # --- 阶段 5：更新 Knowledge State（唯一入口）---
        _update(doc, progress=_progress(4, 0.88))
        changes = knowledge_service.apply_evidence(doc["user_id"], evidence_entries)

        # --- 标签计分：答对则该题所有标签 +1，否则 -1 ---
        # correctness=unknown（两个模型对答案有分歧）时不动标签：
        # 我们并不知道学生到底对不对，不该瞎扣分。
        tag_updates = [
            tag_service.apply_answer(
                doc["user_id"], result["question_id"], result["correctness"] == "correct"
            )
            for result in question_results
            if result["correctness"] != "unknown" and result.get("tags")
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
        "choices": raw.options,
        "student_answer": raw.student_answer,
        "correct_answer": raw.correct_answer,
        "correctness": raw.correctness,
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


def _build_wrong_question(
    result: dict[str, Any], doc: dict[str, Any], homework_id: str, now: str
) -> dict[str, Any]:
    # 知识点可能为空（模型既没给出知识点、标签也反查不到）。
    # 错题本身仍然要留下来给学生看，只是不挂知识点。
    primary = result["knowledge_points"][0] if result["knowledge_points"] else None
    return {
        "wrong_question_id": db.new_id("wq"),
        "user_id": doc["user_id"],
        "question_id": result["question_id"],
        "knowledge_point_id": primary["knowledge_point_id"] if primary else None,
        "knowledge_point_name": primary["name"] if primary else None,
        "status": "open",
        "favorite": False,
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
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def build_detail(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "analysis_id": doc["analysis_id"],
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
