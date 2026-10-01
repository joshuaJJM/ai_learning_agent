"""AI Tutor —— 受控 Agent（状态机 + LLM）。

契约 §22 明确要求 Tutor 必须**有状态**，不能每次请求重新 Prompt。
所以这里维护一个持久化的 session，状态机在 Python 里，模型只负责语言。

刻意的取舍：
  - **状态转移是确定性的**（`_decide`），不看模型脸色。
  - **反馈话术用模板**，因为交互式教学里每轮等 8 秒模型响应会毁掉体验；
    只有当某个知识点没有教学脚本、需要现场生成讲解时才调用 LLM。
  - 引导式练习（guided_practice）里答对**不产生 Evidence**——有人扶着做对，
    说明不了真实掌握程度。只有概念诊断和独立练习才算数。

流程：
    diagnose           概念诊断题
      ├── 答错 → remedial（更简单的问题）→ 再解释
      └── 答对 → 解释
    teach              讲解
    guided_practice    分步引导（无 Evidence）
    independent_practice 独立完成（有 Evidence）
    completed          总结 + Mastery 变化 + 下一步
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from .. import db, knowledge, repositories
from ..question_bank import BankQuestion, get_bank
from . import knowledge_service, recommendation_service, vlm_service
from .knowledge_service import EvidenceInput
from .llm import LlmUnavailable, build_user_message, get_llm

SCRIPTS_PATH = Path(__file__).resolve().parent.parent / "seed" / "tutor_scripts.json"

PHASE_ORDER = (
    "diagnose",
    "teach",
    "guided_practice",
    "independent_practice",
    "completed",
)

MAX_HINTS = 2


# ---------------------------------------------------------------------------
# 教学脚本
# ---------------------------------------------------------------------------

_scripts_cache: dict[str, Any] | None = None


def _scripts() -> dict[str, Any]:
    global _scripts_cache
    if _scripts_cache is None:
        try:
            payload = json.loads(SCRIPTS_PATH.read_text(encoding="utf-8"))
            _scripts_cache = payload.get("scripts", {})
        except (OSError, json.JSONDecodeError):
            _scripts_cache = {}
    return _scripts_cache


def _script_for(kp_id: str) -> dict[str, Any] | None:
    return _scripts().get(kp_id)


# ---------------------------------------------------------------------------
# 选题
# ---------------------------------------------------------------------------

def _pick_bank(
    user_id: str,
    kp_id: str,
    *,
    target_difficulty: float,
    exclude: set[str] | None = None,
    count: int = 1,
) -> list[BankQuestion]:
    """复用练习模块的推荐算法，避免跨会话反复出同一道题。"""
    from . import practice_service

    exclude = exclude or set()
    picked = practice_service.recommend_questions(
        user_id,
        kp_id,
        count + len(exclude) + 4,
        target_difficulty=target_difficulty,
    )
    result = [q for q in picked if q.id not in exclude]
    return result[:count]


# ---------------------------------------------------------------------------
# 步骤构造
# ---------------------------------------------------------------------------

def _step(
    kind: str,
    content: dict[str, Any],
    *,
    counts_toward: bool = True,
) -> dict[str, Any]:
    return {"kind": kind, "content": content, "counts_toward": counts_toward}


def _build_plan(user_id: str, kp_id: str, difficulty: float) -> list[dict[str, Any]]:
    point = knowledge.get_point(kp_id)
    script = _script_for(kp_id) or {}
    plan: list[dict[str, Any]] = []
    used: set[str] = set()

    # 1) 概念诊断
    concept = script.get("concept")
    if concept:
        plan.append(
            _step(
                "concept",
                {
                    "text": concept["text"],
                    "choices": concept.get("choices", {}),
                    "answer": concept.get("answer"),
                    "explanation": concept.get("explanation", ""),
                    "question_id": None,
                },
            )
        )
    else:
        candidates = _pick_bank(
            user_id, kp_id, target_difficulty=min(0.55, difficulty), count=1
        )
        if candidates:
            question = candidates[0]
            used.add(question.id)
            plan.append(
                _step(
                    "concept",
                    {
                        "text": question.stem,
                        "choices": dict(question.options),
                        "answer": question.answer,
                        "explanation": question.explanation,
                        "question_id": question.id,
                        "difficulty": question.difficulty,
                    },
                )
            )

    # 2) 降级问题（答错时才插入，不计入进度）
    remedial = script.get("remedial")
    if remedial:
        plan.append(
            _step(
                "remedial",
                {
                    "text": remedial["text"],
                    "choices": remedial.get("choices", {}),
                    "answer": remedial.get("answer"),
                    "explanation": remedial.get("explanation", ""),
                },
                counts_toward=False,
            )
        )

    # 3) 讲解
    teach_text = script.get("teach") or (
        f"我们来把「{point.name}」拆开看。{point.description}。"
        if point
        else "我们一步步来。"
    )
    plan.append(_step("explain", {"text": teach_text}))

    # 4) 引导练习（扶着手做，不计 Evidence）
    for question in _pick_bank(
        user_id, kp_id, target_difficulty=min(0.6, difficulty), exclude=used, count=2
    ):
        used.add(question.id)
        plan.append(
            _step(
                "guided",
                {
                    "text": question.stem,
                    "choices": dict(question.options),
                    "answer": question.answer,
                    "explanation": question.explanation,
                    "question_id": question.id,
                    "difficulty": question.difficulty,
                },
            )
        )

    # 5) 独立练习（必须自己完成，产生 Evidence）
    for question in _pick_bank(
        user_id, kp_id, target_difficulty=max(0.6, difficulty), exclude=used, count=1
    ):
        used.add(question.id)
        plan.append(
            _step(
                "independent",
                {
                    "text": question.stem,
                    "choices": dict(question.options),
                    "answer": question.answer,
                    "explanation": question.explanation,
                    "question_id": question.id,
                    "difficulty": question.difficulty,
                },
            )
        )

    # 6) 总结
    plan.append(_step("summary", {"text": ""}))
    return plan


def _total_steps(plan: Sequence[dict[str, Any]]) -> int:
    return max(1, sum(1 for s in plan if s["counts_toward"]))


def _progress_of(session: dict[str, Any]) -> dict[str, Any]:
    plan = session["plan"]
    index = session["step_index"]
    total = _total_steps(plan)
    done = sum(
        1 for s in plan[: index + 1] if s.get("counts_toward")
    )
    if session.get("completed"):
        done = total
    return {
        "step": done,
        "total_steps": total,
        "percent": round(min(1.0, done / total), 3),
    }


def _phase_of(session: dict[str, Any]) -> str:
    plan = session["plan"]
    index = session["step_index"]
    if session.get("completed") or index >= len(plan):
        return "completed"
    kind = plan[index]["kind"]
    return {
        "concept": "diagnose",
        "remedial": "diagnose",
        "explain": "teach",
        "guided": "guided_practice",
        "independent": "independent_practice",
        "summary": "completed",
    }.get(kind, "diagnose")


def _turn_type_of(kind: str, *, after_wrong: bool) -> str:
    if kind == "concept":
        return "concept_question"
    if kind == "remedial":
        return "simpler_question"
    if kind == "explain":
        return "explanation"
    if kind == "guided":
        return "hint" if after_wrong else "guided_practice"
    if kind == "independent":
        return "independent_practice"
    return "summary"


# ---------------------------------------------------------------------------
# 轮次生成
# ---------------------------------------------------------------------------

def _evaluation_feedback(
    *, correct: bool, content: dict[str, Any], kind: str, hint_count: int
) -> str:
    if correct:
        if kind == "independent":
            return "完全正确。这次没有提示，是你自己独立做出来的。"
        if kind == "concept":
            return "对。这个概念你抓准了，我们往下走。"
        return "很好，继续。"
    if hint_count == 0:
        return "先别急着看答案。再读一遍题目，想想关键的那一步是什么。"
    return "还是不对。我们换一个角度看这个问题。"


def _render_turn(
    session: dict[str, Any],
    *,
    after_wrong: bool = False,
    feedback: str | None = None,
) -> dict[str, Any]:
    plan = session["plan"]
    index = session["step_index"]
    completed = session.get("completed", False)

    if completed or index >= len(plan):
        return _summary_turn(session)

    step = plan[index]
    kind = step["kind"]
    content = step["content"]
    kp_id = session["knowledge_point_id"]
    point = knowledge.get_point(kp_id)

    if kind == "explain":
        return {
            "turn_type": "explanation",
            "text": feedback + "\n\n" + content["text"] if feedback else content["text"],
            "choices": {},
            "allow_free_text": False,
            "question_id": None,
        }

    if kind == "summary":
        return _summary_turn(session)

    text = content["text"]
    if feedback:
        text = f"{feedback}\n\n{text}"

    choices = content.get("choices") or {}
    return {
        "turn_type": _turn_type_of(kind, after_wrong=after_wrong),
        "text": text,
        "choices": choices,
        "allow_free_text": not choices,
        "question_id": content.get("question_id"),
    }


def _summary_turn(session: dict[str, Any]) -> dict[str, Any]:
    point = knowledge.get_point(session["knowledge_point_id"])
    name = point.name if point else "这个知识点"
    changes = session.get("knowledge_changes") or []
    lines = [f"🎉 这一轮「{name}」的学习完成了。", ""]
    lines.append("你刚才完整走完了：")
    lines.append("理解概念 → 跟着做一遍 → 独立完成一道题")
    if changes:
        lines.append("")
        for change in changes:
            before = change["before"] * 100
            after = change["after"] * 100
            arrow = "↑" if change["delta"] >= 0 else "↓"
            lines.append(
                f"{change['name']}  {before:.0f}%  {arrow}  {after:.0f}%"
            )
    return {
        "turn_type": "summary",
        "text": "\n".join(lines),
        "choices": {},
        "allow_free_text": False,
        "question_id": None,
    }


def _choices_list(choices: Any) -> list[dict[str, str]]:
    """内部用 dict 存选项，对外契约要求 list[{key,text}]，统一在这里转换。"""
    if not choices:
        return []
    if isinstance(choices, list):
        return choices
    return [{"key": key, "text": text} for key, text in sorted(choices.items())]


def _persist_turn(session: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
    seq = session.get("seq", 0) + 1
    session["seq"] = seq
    record = {
        "turn_id": db.new_id("turn"),
        "seq": seq,
        "turn_type": turn["turn_type"],
        "text": turn["text"],
        "choices": _choices_list(turn.get("choices")),
        "allow_free_text": turn.get("allow_free_text", True),
        "phase": _phase_of(session),
        "progress": _progress_of(session),
        "completed": session.get("completed", False),
        "question_id": turn.get("question_id"),
        "created_at": db.to_iso(db.utcnow()),
    }
    session.setdefault("history", []).append(record)
    repositories.append_tutor_turn(session["tutor_session_id"], seq, record)
    return record


def _save(session: dict[str, Any]) -> None:
    session["phase"] = _phase_of(session)
    session["updated_at"] = db.to_iso(db.utcnow())
    repositories.save_tutor_session(session)


# ---------------------------------------------------------------------------
# 创建 session
# ---------------------------------------------------------------------------

async def create_session(
    user_id: str,
    *,
    source_type: str = "knowledge_point",
    knowledge_point_id: str | None = None,
    wrong_question_id: str | None = None,
    question_text: str | None = None,
    image: tuple[bytes, str] | None = None,
) -> dict[str, Any]:
    upload_note: str | None = None
    source_id: str | None = None

    if source_type == "wrong_question":
        item = repositories.get_wrong_question(wrong_question_id or "")
        if item is None:
            raise LookupError("wrong_question")
        knowledge_point_id = item.get("knowledge_point_id") or "math.derivative"
        source_id = item["wrong_question_id"]
        upload_note = f"我们来重新搞懂这道题（第 {item.get('question_number', '')} 题）。"
    elif source_type == "uploaded_question":
        analysis = await _analyze_upload(question_text, image)
        if analysis is None:
            raise ValueError("question_not_recognized")
        knowledge_point_id = analysis["knowledge_point_ids"][0]
        source_id = None
        upload_note = (
            f"我看了你拍的这道题，它主要考「"
            f"{knowledge.get_point(knowledge_point_id).name if knowledge.get_point(knowledge_point_id) else '导数'}」。"
            f"我们先把它背后的概念弄清楚。"
        )

    kp_id = knowledge_point_id or "math.derivative"
    if not knowledge.is_known(kp_id):
        kp_id = "math.derivative"

    estimate = knowledge_service.mastery_of(user_id, kp_id)
    difficulty = estimate.mastery

    session: dict[str, Any] = {
        "tutor_session_id": db.new_id("tut"),
        "user_id": user_id,
        "source_type": source_type,
        "source_id": source_id,
        "knowledge_point_id": kp_id,
        "knowledge_point_name": knowledge.get_point(kp_id).name
        if knowledge.get_point(kp_id)
        else kp_id,
        "phase": "diagnose",
        "difficulty": round(difficulty, 3),
        "attempt_count": 0,
        "hint_count": 0,
        "student_understanding": round(estimate.mastery, 3),
        "completed": False,
        "seq": 0,
        "step_index": 0,
        "plan": _build_plan(user_id, kp_id, difficulty),
        "history": [],
        "knowledge_changes": [],
        "next_action": None,
        "upload_note": upload_note,
        "created_at": db.to_iso(db.utcnow()),
        "updated_at": db.to_iso(db.utcnow()),
    }

    turn = _render_turn(session)
    if upload_note and turn["turn_type"] == "concept_question":
        turn = {**turn, "text": f"{upload_note}\n\n{turn['text']}"}
    record = _persist_turn(session, turn)
    _save(session)
    session["_turn"] = record
    return session


async def _analyze_upload(
    question_text: str | None, image: tuple[bytes, str] | None
) -> dict[str, Any] | None:
    """理解用户上传的题目：优先用 VLM 看图，其次题库文本匹配。"""
    if image is not None:
        try:
            outcome = await vlm_service.analyze_images([image])
            if outcome.questions:
                first = outcome.questions[0]
                return {
                    "stem": first.stem,
                    "options": first.options,
                    "answer": first.correct_answer,
                    "knowledge_point_ids": first.knowledge_point_ids
                    or ["math.derivative"],
                }
        except LlmUnavailable:
            pass

    if question_text:
        bank_question, _ = vlm_service.match_bank_question(question_text)
        if bank_question is not None:
            return {
                "stem": bank_question.stem,
                "options": dict(bank_question.options),
                "answer": bank_question.answer,
                "knowledge_point_ids": list(bank_question.knowledge_point_ids),
            }
        return {
            "stem": question_text,
            "options": {},
            "answer": None,
            "knowledge_point_ids": vlm_service.infer_knowledge_points(question_text, {}),
        }
    return None


# ---------------------------------------------------------------------------
# 提交作答
# ---------------------------------------------------------------------------

def submit_answer(
    user_id: str,
    session_id: str,
    *,
    selected_key: str | None = None,
    text: str | None = None,
    self_reported_confidence: str | None = None,
) -> dict[str, Any]:
    session = repositories.get_tutor_session(session_id)
    if session is None or session.get("user_id") != user_id:
        raise LookupError("session")
    if session.get("completed"):
        raise RuntimeError("completed")

    plan = session["plan"]
    index = session["step_index"]
    if index >= len(plan):
        raise RuntimeError("completed")
    step = plan[index]
    content = step["content"]
    kind = step["kind"]

    expected = (content.get("answer") or "").upper() or None
    chosen = (selected_key or "").strip().upper() or None
    is_correct = bool(expected and chosen and chosen == expected)

    if expected is None:
        # 开放题（例如讲解步骤）——没有标准答案，视为通过
        is_correct = True

    session["attempt_count"] = session.get("attempt_count", 0) + 1

    # 理解度：指数滑动平均
    understanding = session.get("student_understanding", 0.5)
    target = 1.0 if is_correct else 0.0
    session["student_understanding"] = round(0.65 * understanding + 0.35 * target, 4)

    evidence_changes: list[Any] = []
    if kind in ("concept", "remedial", "independent") and expected is not None:
        result = "correct" if is_correct else "wrong"
        evidence_changes = knowledge_service.apply_evidence(
            user_id,
            [
                EvidenceInput(
                    knowledge_point_id=session["knowledge_point_id"],
                    result=result,
                    difficulty=float(content.get("difficulty", 0.5)),
                    source_type="tutor",
                    source_id=session_id,
                    question_id=content.get("question_id"),
                    error_type=None if is_correct else "conceptual",
                    confidence=1.0 if kind != "remedial" else 0.7,
                    detail=None
                    if is_correct
                    else "在 AI Tutor 的概念诊断中作答错误",
                    answer_excerpt=chosen,
                )
            ],
        )

    strategy: str
    if kind == "concept" and not is_correct:
        # 答错 → 插入降级问题（若还没有被用过）
        remedial_index = next(
            (i for i, s in enumerate(plan) if s["kind"] == "remedial"), None
        )
        hint_count = session.get("hint_count", 0)
        if remedial_index is not None and remedial_index >= index:
            session["step_index"] = remedial_index
            strategy = "simplify"
        else:
            session["hint_count"] = hint_count + 1
            strategy = "hint"
    elif not is_correct and session.get("hint_count", 0) < MAX_HINTS:
        session["hint_count"] = session.get("hint_count", 0) + 1
        strategy = "hint"
    else:
        session["step_index"] = index + 1
        strategy = "advance" if is_correct else "re_explain"

    # 跳过不需要学生作答的步骤：
    #   - explain（讲解卡片）不是问题，不该等作答，其文字并入下一轮
    #   - 概念题答对了就不必再问降级题
    preamble: list[str] = []
    while session["step_index"] < len(plan):
        upcoming = plan[session["step_index"]]
        if upcoming["kind"] == "explain":
            preamble.append(upcoming["content"]["text"])
            session["step_index"] += 1
            continue
        if upcoming["kind"] == "remedial" and is_correct:
            session["step_index"] += 1
            continue
        break

    # 走到总结步骤即视为完成，并在同一轮里把总结发给学生
    at_end = session["step_index"] >= len(plan) or (
        plan[session["step_index"]]["kind"] == "summary"
    )
    if at_end:
        session["step_index"] = max(0, len(plan) - 1)
        session["completed"] = True
        session["knowledge_changes"] = [
            c.model_dump(mode="json") for c in evidence_changes
        ]
        session["next_action"] = recommendation_service.next_action(
            user_id
        ).model_dump(mode="json")

    feedback = _evaluation_feedback(
        correct=is_correct,
        content=content,
        kind=kind,
        hint_count=session.get("hint_count", 0),
    )

    # 答对且当前步骤带解析 → 立刻把解析给出来
    explanation = (
        content["explanation"] if (is_correct and content.get("explanation")) else None
    )

    if preamble:
        feedback = "\n\n".join([feedback, *preamble])
    turn = _render_turn(session, after_wrong=not is_correct, feedback=feedback)
    record = _persist_turn(session, turn)
    _save(session)

    return {
        "session": session,
        "turn": record,
        "evaluation": {
            "correctness": "correct" if is_correct else "wrong",
            "is_correct": is_correct,
            "chosen_key": chosen,
            "expected_key": expected,
            "feedback": feedback,
            "explanation": explanation,
            "strategy": strategy,
        },
        "knowledge_changes": [
            c.model_dump(mode="json") for c in evidence_changes
        ],
    }


def session_response(session: dict[str, Any]) -> dict[str, Any]:
    history = session.get("history", [])
    return {
        "tutor_session_id": session["tutor_session_id"],
        "user_id": session["user_id"],
        "source_type": session["source_type"],
        "source_id": session.get("source_id"),
        "knowledge_point_id": session.get("knowledge_point_id"),
        "knowledge_point_name": session.get("knowledge_point_name"),
        "phase": session.get("phase", "diagnose"),
        "difficulty": session.get("difficulty", 0.5),
        "attempt_count": session.get("attempt_count", 0),
        "hint_count": session.get("hint_count", 0),
        "student_understanding": session.get("student_understanding", 0.5),
        "completed": session.get("completed", False),
        "turn": history[-1] if history else None,
        "history": history,
        "knowledge_changes": session.get("knowledge_changes", []),
        "next_action": session.get("next_action"),
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
    }
