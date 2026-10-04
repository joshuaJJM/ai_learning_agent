"""针对性练习（Practice Engine）。

契约 §14 的硬性要求：**不能把正确答案提前返回给客户端**。
所以 PracticeQuestion 里没有 answer / explanation，
答案只在提交后随判定结果一起下发。
"""

from __future__ import annotations

from typing import Any

from .. import db, knowledge, repositories
from ..mastery import error_patterns
from ..question_bank import BankQuestion, get_bank, stem_fingerprint
from . import knowledge_service, recommendation_service, tag_service
from .knowledge_service import EvidenceInput

# 错误类型 → 题库 tags/题干里的关键词，用于"针对错误模式出题"
ERROR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "case_analysis": ("参数", "分类", "讨论", "取值范围", "恒成立"),
    "domain_omission": ("定义域", "区间"),
    "transformation": ("单调", "符号", "性质", "图象", "递增", "递减"),
    "procedural": ("计算", "求导", "公式"),
    "conceptual": ("概念", "意义", "判断"),
    "incomplete": ("完整", "讨论"),
}

# 推荐算法的权重。集中在这里，方便对照推荐结果调参。
W_DIFFICULTY_MATCH = 2.0  # 难度契合度（负分，越小越远）
W_SPACED_REDO = 0.9  # 做错过、还没做对的题：优先重做
W_RECENT_CORRECT = 1.6  # 刚做对的题：压下去，避免重复刷
W_ERROR_TARGET = 0.6  # 命中学生主要错误模式的题：加权
SPACED_REDO_COOLDOWN_DAYS = 0.5  # 错题冷却：刚做错别马上再出同一道
RECENT_CORRECT_DAYS = 5.0  # 做对后多少天内不再优先出


def _target_difficulty(mastery: float) -> float:
    """掌握度低就给简单题，掌握度高就给难题。"""
    return round(min(0.95, max(0.1, 1.0 - mastery * 0.85)), 3)


def _candidate_pool(kp_id: str) -> list[BankQuestion]:
    pool = get_bank().by_knowledge_point(kp_id)
    if pool:
        return pool
    # 该知识点没有专属题目时，退到子 / 父 / 前置知识点
    point = knowledge.get_point(kp_id)
    related: list[BankQuestion] = []
    if point is not None:
        for child in knowledge.children_of(kp_id):
            related.extend(get_bank().by_knowledge_point(child.id))
        if point.parent_id:
            related.extend(get_bank().by_knowledge_point(point.parent_id))
        for prerequisite in knowledge.prerequisites(kp_id):
            related.extend(get_bank().by_knowledge_point(prerequisite.id))
    return related or get_bank().all()


def _dominant_error_types(user_id: str, kp_id: str, limit: int = 2) -> list[str]:
    records = repositories.evidence_records(user_id, kp_id)
    return [p.error_type for p in error_patterns(records, limit=limit)]


def score_question(
    question: BankQuestion,
    *,
    target: float,
    history: dict[str, dict[str, Any]],
    error_types: list[str],
    now: Any,
) -> tuple[float, list[str]]:
    """给一道题打分。分数越高越该出。返回 (分数, 推荐理由)。"""
    score = -abs(question.difficulty - target) * W_DIFFICULTY_MATCH
    reasons: list[str] = []

    record = history.get(question.id)
    if record:
        last_at = db.from_iso(record.get("last_at"))
        age_days = (
            (now - last_at).total_seconds() / 86400.0 if last_at is not None else 999.0
        )
        if record["wrong_count"] > 0 and record.get("last_result") != "correct":
            if age_days >= SPACED_REDO_COOLDOWN_DAYS:
                score += W_SPACED_REDO
                reasons.append("之前做错过，适合重做巩固")
        if record.get("last_result") == "correct" and age_days < RECENT_CORRECT_DAYS:
            score -= W_RECENT_CORRECT
            reasons.append("近期已做对")

    haystack = " ".join([question.stem, *question.tags])
    hits = [
        etype
        for etype in error_types
        if any(keyword in haystack for keyword in ERROR_KEYWORDS.get(etype, ()))
    ]
    if hits:
        score += W_ERROR_TARGET * len(hits)
        reasons.append("针对你的主要错误模式")

    return score, reasons


def recommend_questions(
    user_id: str,
    knowledge_point_id: str,
    count: int,
    *,
    target_difficulty: float | None = None,
    allow_repeat_when_exhausted: bool = True,
) -> list[BankQuestion]:
    """**题目推荐算法**（不依赖 LLM）。

    综合考虑四件事：
      1. 难度契合度——掌握度低出简单题，掌握度高出难题；
      2. 错题重做——做错过且尚未做对的题优先，但设冷却时间；
      3. 避免重复——刚做对的题压下去，不要反复刷同一道；
      4. 错误模式针对性——学生的"分类讨论错误"就多出分类讨论题。

    题库是预处理好的、带知识点与标签的静态资源，
    所以整套推荐是纯算法，随时可复现、可解释。
    """
    if target_difficulty is None:
        estimate = knowledge_service.mastery_of(user_id, knowledge_point_id)
        target_difficulty = _target_difficulty(estimate.mastery)

    pool = _candidate_pool(knowledge_point_id)
    history = repositories.question_history(user_id)
    error_types = _dominant_error_types(user_id, knowledge_point_id)
    now = db.utcnow()

    scored = [
        (score_question(
            question,
            target=target_difficulty,
            history=history,
            error_types=error_types,
            now=now,
        )[0], question)
        for question in pool
    ]
    scored.sort(key=lambda item: item[0], reverse=True)

    picked: list[BankQuestion] = []
    seen: set[str] = set()
    for _, question in scored:
        if question.id in seen:
            continue
        seen.add(question.id)
        picked.append(question)
        if len(picked) >= count:
            return picked

    # 题库不够时，允许把"刚做对"的题重新拿出来补位
    if allow_repeat_when_exhausted and len(picked) < count:
        for question in pool:
            if question.id not in seen:
                picked.append(question)
                seen.add(question.id)
                if len(picked) >= count:
                    break
    return picked


def _select_questions(kp_id: str, count: int, target: float, user_id: str) -> list[BankQuestion]:
    return recommend_questions(
        user_id, kp_id, count, target_difficulty=target
    )


def create_session(
    user_id: str,
    *,
    knowledge_point_id: str | None = None,
    difficulty: float | None = None,
    book_id: str | None = None,
    count: int = 5,
) -> dict[str, Any]:
    if not knowledge_point_id:
        weak = knowledge_service.weakest_points(user_id, limit=1)
        knowledge_point_id = (
            weak[0].knowledge_point_id if weak else "math.derivative.monotonicity"
        )
    if not knowledge.is_known(knowledge_point_id):
        knowledge_point_id = "math.derivative.monotonicity"

    estimate = knowledge_service.mastery_of(user_id, knowledge_point_id)
    target = difficulty if difficulty is not None else _target_difficulty(estimate.mastery)
    questions = _select_questions(knowledge_point_id, count, target, user_id)
    point = knowledge.get_point(knowledge_point_id)
    now = db.to_iso(db.utcnow())

    session: dict[str, Any] = {
        "practice_session_id": db.new_id("prac"),
        "user_id": user_id,
        "knowledge_point_id": knowledge_point_id,
        "knowledge_point_name": point.name if point else knowledge_point_id,
        "book_id": book_id,
        "status": "active",
        "total": len(questions),
        "target_difficulty": target,
        "mastery_at_start": round(estimate.mastery, 4),
        "question_ids": [q.id for q in questions],
        "served_index": 0,
        "attempts": [],
        "created_at": now,
        "updated_at": now,
    }
    repositories.save_practice_session(session)
    return session


def create_tag_session(user_id: str, *, count: int = 5, book_id: str | None = None) -> dict[str, Any]:
    """按**标签分数**选题（默认的推荐方式）。

    规则：把所有标签从小到大排序，返回包含分数最低那个标签的题目。
    多对多的部分由 tag_service.pick_questions 处理（见那里的注释）。
    """
    tag_service.initialize_scores(user_id)
    picks = tag_service.pick_questions(user_id, limit=max(1, count))
    bank = get_bank()
    questions = [bank.get(p["question_id"]) for p in picks]
    questions = [q for q in questions if q is not None]

    now = db.to_iso(db.utcnow())
    lead = picks[0] if picks else None

    # 兼容既有会话结构：knowledge_point_id 取第一道题的主知识点。
    # 但真正驱动选择的是 target_tag。
    primary_kp = None
    if questions:
        for kp_id in questions[0].knowledge_point_ids:
            if knowledge.is_known(kp_id):
                primary_kp = kp_id
                break

    session: dict[str, Any] = {
        "practice_session_id": db.new_id("prac"),
        "user_id": user_id,
        "selection_mode": "tag",
        "target_tag": lead["tag"] if lead else None,
        "target_tag_score": lead["tag_score"] if lead else None,
        "picked_tags": [p["tag"] for p in picks],
        "knowledge_point_id": primary_kp,
        "knowledge_point_name": (
            knowledge.get_point(primary_kp).name if primary_kp else None
        ),
        "book_id": book_id,
        "status": "active",
        "total": len(questions),
        "target_difficulty": None,
        "mastery_at_start": None,
        "question_ids": [q.id for q in questions],
        "served_index": 0,
        "attempts": [],
        "created_at": now,
        "updated_at": now,
    }
    repositories.save_practice_session(session)
    return session


def _question_payload(
    question: BankQuestion, index: int, total: int
) -> dict[str, Any]:
    refs = []
    for kp_id in question.knowledge_point_ids[:3]:
        point = knowledge.get_point(kp_id)
        if point:
            refs.append(
                {"knowledge_point_id": kp_id, "name": point.name, "weight": 1.0}
            )
    return {
        "question_id": question.id,
        # 用题库里的题号（「第017题」→ 017），不要从 id 里截 ——
        # id 现在是内容指纹，截出来会是一串十六进制。
        "question_number": question.question_number,
        # 标签会下发给客户端：「本题考察 XXX」
        "tags": list(question.tags),
        "stem": question.stem,
        "choices": [{"key": k, "text": v} for k, v in sorted(question.options.items())],
        "difficulty": question.difficulty,
        "knowledge_points": refs,
        "index": index,
        "total": total,
    }


def current_question(session: dict[str, Any]) -> dict[str, Any] | None:
    ids = session.get("question_ids", [])
    index = session.get("served_index", 0)
    if index >= len(ids):
        return None
    question = get_bank().get(ids[index])
    if question is None:
        return None
    return _question_payload(question, index + 1, len(ids))


def session_response(session: dict[str, Any]) -> dict[str, Any]:
    attempts = session.get("attempts", [])
    return {
        "practice_session_id": session["practice_session_id"],
        "user_id": session["user_id"],
        "knowledge_point_id": session.get("knowledge_point_id"),
        "knowledge_point_name": session.get("knowledge_point_name"),
        "status": session.get("status", "active"),
        "total": session.get("total", 0),
        "answered": len(attempts),
        "correct": sum(1 for a in attempts if a.get("correctness") == "correct"),
        "next_question": current_question(session),
        # 标签选题的元信息：客户端可以显示「本次专练：XXX」
        "selection_mode": session.get("selection_mode", "knowledge_point"),
        "target_tag": session.get("target_tag"),
        "target_tag_score": session.get("target_tag_score"),
        "picked_tags": session.get("picked_tags", []),
        "created_at": session["created_at"],
    }


def _attempt_response(
    session: dict[str, Any],
    attempt: dict[str, Any],
    question: BankQuestion,
    *,
    replayed: bool,
) -> dict[str, Any]:
    """从一条已存在的作答记录拼响应。重复提交时用它回放，不再重复计分。"""
    ids = session.get("question_ids", [])
    attempts = session.get("attempts", [])
    finished = session.get("status") == "completed"
    is_correct = attempt.get("correctness") == "correct"
    return {
        "practice_session_id": session["practice_session_id"],
        "question_id": question.id,
        "correctness": attempt.get("correctness", "wrong"),
        "is_correct": is_correct,
        "correct_answer": question.answer,
        "explanation": question.explanation or None,
        "knowledge_changes": attempt.get("knowledge_changes", []),
        "tag_changes": attempt.get("tag_changes"),
        "next_question": None if finished else current_question(session),
        "session_completed": finished,
        "answered": len(attempts),
        "correct": sum(1 for a in attempts if a.get("correctness") == "correct"),
        "total": len(ids),
        "replayed": replayed,
        "next_action": recommendation_service.next_action(
            session["user_id"], preferred_kp_id=session.get("knowledge_point_id")
        ).model_dump(mode="json")
        if finished
        else None,
    }


def submit_answer(
    user_id: str,
    session_id: str,
    *,
    question_id: str,
    selected_key: str | None = None,
) -> dict[str, Any]:
    session = repositories.get_practice_session(session_id)
    if session is None or session.get("user_id") != user_id:
        raise LookupError("session")

    question = get_bank().get(question_id)
    if question is None:
        raise LookupError("question")

    chosen = (selected_key or "").strip().upper() or None

    # 检查顺序很重要：**先回放，再校验**。
    #
    # 最后一题答完时 served_index 已经越界、会话也已 completed，
    # 此时的重试应该拿到上次结果，而不是被判成「不是当前题」或 409。
    previous = next(
        (a for a in session.get("attempts", []) if a.get("question_id") == question_id),
        None,
    )
    if previous is not None:
        # 同一题重复提交（手机网络重试很常见）直接回放，
        # 不再写 Evidence、不再动标签 —— 否则重试一次就多记一次分。
        return _attempt_response(session, previous, question, replayed=True)

    # 未提交过的题：必须是**当前这一题**。
    #
    # 只校验「属于本 Session」还不够：那仍然允许提前提交后面的题、
    # 或把整组题乱序刷掉。提交任意一道题库题目会写 Evidence、动标签、
    # 推进会话 —— 等于绕过整套推荐逻辑污染掌握度。
    ids = session.get("question_ids", [])
    current_index = session.get("served_index", 0)
    if current_index >= len(ids) or ids[current_index] != question_id:
        raise PermissionError("question_not_in_session")

    if session.get("status") == "completed":
        raise RuntimeError("completed")

    is_correct = chosen == question.answer

    # 先算增量，再落记录 —— 这样作答记录里带着本次的知识点/标签变动，
    # 回放时才能原样返回。
    #
    # 标签统计现在从 Evidence 现算，所以要在写 Evidence **之前**取快照，
    # 否则算不出「这次作答让标签变了多少」。
    tag_snapshot = tag_service.tag_stats(user_id)
    changes = knowledge_service.apply_evidence(
        user_id,
        [
            EvidenceInput(
                knowledge_point_id=kp_id,
                result="correct" if is_correct else "wrong",
                difficulty=question.difficulty,
                source_type="practice",
                source_id=session_id,
                question_id=question_id,
                question_stem_hash=stem_fingerprint(question.stem),
                error_type=None if is_correct else _guess_error_type(question),
                confidence=1.0,
                detail=None if is_correct else f"练习中答错：{question.stem[:60]}",
                answer_excerpt=chosen,
            )
            for kp_id in (question.knowledge_point_ids or ())
            if knowledge.is_known(kp_id)
        ],
    )
    # 标签统计由 Evidence 派生，这里只回显（不再直接改分数）
    tag_update = tag_service.apply_answer(
        user_id, question_id, is_correct, before=tag_snapshot
    )

    now = db.to_iso(db.utcnow())
    attempts = list(session.get("attempts", []))
    attempts.append(
        {
            "question_id": question_id,
            "selected_key": chosen,
            "correctness": "correct" if is_correct else "wrong",
            "created_at": now,
            "knowledge_changes": [c.model_dump(mode="json") for c in changes],
            "tag_changes": tag_update,
        }
    )
    session["attempts"] = attempts

    # 推进到下一题
    answered_index = ids.index(question_id)
    session["served_index"] = max(session.get("served_index", 0), answered_index + 1)

    session["updated_at"] = now
    finished = session["served_index"] >= len(ids)
    if finished:
        session["status"] = "completed"
    repositories.save_practice_session(session)

    return {
        "practice_session_id": session_id,
        "question_id": question_id,
        "correctness": "correct" if is_correct else "wrong",
        "is_correct": is_correct,
        "correct_answer": question.answer,
        # 官方题库规范不含解析字段，这里可能是 None，客户端要能处理
        "explanation": question.explanation or None,
        "knowledge_changes": [c.model_dump(mode="json") for c in changes],
        "tag_changes": tag_update,
        "next_question": None if finished else current_question(session),
        "session_completed": finished,
        "answered": len(attempts),
        "correct": sum(1 for a in attempts if a.get("correctness") == "correct"),
        "total": len(ids),
        "replayed": False,
        "next_action": recommendation_service.next_action(
            user_id, preferred_kp_id=session.get("knowledge_point_id")
        ).model_dump(mode="json")
        if finished
        else None,
    }


def _guess_error_type(question: BankQuestion) -> str:
    """从题干标签粗判错误类型，用于 Evidence 的错误模式统计。"""
    tags = " ".join(question.tags)
    stem = question.stem
    haystack = f"{tags} {stem}"
    if "定义域" in haystack:
        return "domain_omission"
    if "分类" in haystack or "参数" in haystack:
        return "case_analysis"
    if "单调" in haystack or "符号" in haystack:
        return "transformation"
    if "计算" in haystack or "求导" in haystack:
        return "procedural"
    return "conceptual"
