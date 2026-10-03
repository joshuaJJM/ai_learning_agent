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
from ..question_bank import BankQuestion, get_bank, stem_fingerprint
from . import knowledge_service, recommendation_service, tag_service, vlm_service
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

# 正式题答错后进入补救（remedial），最多允许这么深。
# 第 4 层仍答错就停止继续生成问题，改为揭示答案并允许进入下一题 ——
# 不允许出现第 5 层。
MAX_REMEDIAL_DEPTH = 4


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

    # 2) 降级/补救问题不再写进计划 —— 它由答题结果动态触发，
    #    而且要支持最多 MAX_REMEDIAL_DEPTH 层。见 _next_remedial_step()。

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


# ---------------------------------------------------------------------------
# 补救（remedial）状态
# ---------------------------------------------------------------------------
#
# 正式题答错 → 进入补救，最多 4 层：
#   第 1 层优先用教学脚本里手写的 remedial（更贴合这个知识点）
#   第 2–4 层从题库里挑更简单的、没用过的题
#
# 任意一层答对 → 结束补救，继续正常流程
# 第 4 层仍答错 → 不再出题，揭示答案并允许进入下一题
# 补救期间**绝不**下发正式题的正确答案。

def _remedial_used_texts(session: dict[str, Any]) -> set[str]:
    history = session.get("remedial_history") or []
    return {str(item.get("text") or "") for item in history}


def _next_remedial_step(
    session: dict[str, Any], *, depth: int, origin_index: int
) -> dict[str, Any] | None:
    """为第 depth 层挑一道补救题。挑不到就返回 None（调用方改为揭示答案）。"""
    used = _remedial_used_texts(session)
    # 正式题本身也不该被当成补救题重复出
    for step in session.get("plan", []):
        text = step.get("content", {}).get("text")
        if text:
            used.add(str(text))

    kp_id = session["knowledge_point_id"]
    script = _script_for(kp_id) or {}

    # 第 1 层：手写的 remedial 最好用
    if depth == 1:
        remedial = script.get("remedial")
        if remedial and str(remedial.get("text") or "") not in used:
            return _step(
                "remedial",
                {
                    "text": remedial["text"],
                    "choices": remedial.get("choices", {}),
                    "answer": remedial.get("answer"),
                    "explanation": remedial.get("explanation", ""),
                    "difficulty": 0.3,
                },
                counts_toward=False,
            )

    # 其余层（以及脚本里没有 remedial 时）：从题库挑更简单的题
    candidates = _pick_bank(
        session["user_id"],
        kp_id,
        target_difficulty=min(0.45, max(0.15, 0.45 - 0.08 * (depth - 1))),
        count=8,
    )
    for question in candidates:
        if question.stem in used:
            continue
        return _step(
            "remedial",
            {
                "text": question.stem,
                "choices": dict(question.options),
                "answer": question.answer,
                "explanation": question.explanation,
                "question_id": question.id,
                "difficulty": question.difficulty,
            },
            counts_toward=False,
        )
    return None


def _start_remedial(
    session: dict[str, Any], *, origin_index: int, origin_step: dict[str, Any]
) -> bool:
    """进入补救第 1 层。返回 False 表示没有可用的补救题。"""
    step = _next_remedial_step(session, depth=1, origin_index=origin_index)
    if step is None:
        return False
    session["remedial"] = {
        "depth": 1,
        "origin_index": origin_index,
        "origin_content": dict(origin_step.get("content") or {}),
        "step": step,
    }
    session.setdefault("remedial_history", []).append(
        {"depth": 1, "text": step["content"]["text"]}
    )
    return True


def _deeper_remedial(session: dict[str, Any]) -> bool:
    """补救答错 → 进入下一层。返回 False 表示已到上限或没题了。"""
    remedial = session.get("remedial") or {}
    depth = int(remedial.get("depth", 0)) + 1
    if depth > MAX_REMEDIAL_DEPTH:
        return False
    step = _next_remedial_step(
        session, depth=depth, origin_index=int(remedial.get("origin_index", 0))
    )
    if step is None:
        return False
    remedial["depth"] = depth
    remedial["step"] = step
    session["remedial"] = remedial
    session.setdefault("remedial_history", []).append(
        {"depth": depth, "text": step["content"]["text"]}
    )
    return True


def _end_remedial(session: dict[str, Any]) -> dict[str, Any] | None:
    """结束补救，返回触发它的那道正式题的内容（用于揭示答案）。"""
    remedial = session.pop("remedial", None)
    if not remedial:
        return None
    origin_index = int(remedial.get("origin_index", 0))
    # 补救结束 → 那道正式题就算过了，直接推进到它后面
    session["step_index"] = max(session.get("step_index", 0), origin_index + 1)
    return dict(remedial.get("origin_content") or {})


def _active_step(session: dict[str, Any]) -> dict[str, Any] | None:
    """当前正在作答的步骤：补救优先，否则取计划里的当前步。"""
    remedial = session.get("remedial")
    if remedial:
        return remedial["step"]
    plan = session["plan"]
    index = session.get("step_index", 0)
    if index >= len(plan):
        return None
    return plan[index]


def _revealed(content: dict[str, Any]) -> dict[str, Any] | None:
    """把一道题的答案+解析整理成可下发的形状。没有答案就返回 None。"""
    answer = (content.get("answer") or "").upper()
    if not answer:
        return None
    return {
        "question_id": content.get("question_id"),
        "question_text": content.get("text"),
        "correct_key": answer,
        "explanation": content.get("explanation") or None,
    }


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
    if session.get("completed"):
        return "completed"
    step = _active_step(session)
    if step is None:
        return "completed"
    kind = step["kind"]
    return {
        "concept": "diagnose",
        # 补救仍然发生在诊断/讲解阶段，前端按 turn_type 区分即可
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


def _remedial_depth(session: dict[str, Any]) -> int:
    remedial = session.get("remedial") or {}
    return int(remedial.get("depth", 0) or 0)


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
    strategy: str | None = None,
    answer_reveal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step = _active_step(session)
    completed = session.get("completed", False)

    if completed or step is None:
        return _summary_turn(
            session, strategy=strategy, answer_reveal=answer_reveal
        )

    kind = step["kind"]
    content = step["content"]

    if kind == "explain":
        return {
            "turn_type": "explanation",
            "text": feedback + "\n\n" + content["text"] if feedback else content["text"],
            "choices": {},
            "allow_free_text": False,
            "question_id": None,
            "strategy": strategy,
            "remedial_depth": _remedial_depth(session),
            "answer_reveal": answer_reveal,
        }

    if kind == "summary":
        return _summary_turn(
            session, strategy=strategy, answer_reveal=answer_reveal
        )

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
        "strategy": strategy,
        "remedial_depth": _remedial_depth(session),
        # 补救进行中永远是 None —— 绝不提前泄漏正式题答案
        "answer_reveal": answer_reveal,
    }


def _summary_turn(
    session: dict[str, Any],
    *,
    strategy: str | None = None,
    answer_reveal: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        "strategy": strategy,
        "remedial_depth": _remedial_depth(session),
        "answer_reveal": answer_reveal,
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
        # 服务端对教学策略的决定，客户端只呈现、不推断
        "strategy": turn.get("strategy"),
        "remedial_depth": turn.get("remedial_depth", 0),
        # 补救已到上限、这一轮给出了答案揭示。
        # **不要**用它去覆盖 turn_type —— 补救耗尽时会话已经推进到下一题，
        # turn.type 描述的是 turn 里真实装的内容。
        "remedial_exhausted": bool(turn.get("remedial_exhausted", False)),
        # 仅在「答对」或「补救耗尽」时出现；补救进行中恒为 None
        "answer_reveal": turn.get("answer_reveal"),
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

def _resolve_knowledge_point(user_id: str, candidate: str | None) -> str:
    """挑一个**真实存在**的知识点。

    这里原来会回退到 "math.derivative" —— 那是旧知识树的父节点，换成扁平的
    17 个清单后已经不存在了。后果很隐蔽：Tutor 会从整个题库随便选题，
    而且提交后的 Evidence 会被 knowledge_service 静默忽略，
    学生"学完了"但掌握度一动不动。

    现在按「给定值 → 该用户最弱知识点 → 清单第一个」的顺序兜底。
    """
    if candidate and knowledge.is_known(candidate):
        return candidate
    weak = knowledge_service.weakest_points(user_id, limit=1)
    if weak:
        return weak[0].knowledge_point_id
    points = knowledge.all_points()
    if not points:
        raise LookupError("no_knowledge_points")
    return points[0].id


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
        # 必须校验归属：知道别人的错题 ID 就能拿它建自己的 Session
        if item is None or item.get("user_id") != user_id:
            raise LookupError("wrong_question")
        knowledge_point_id = item.get("knowledge_point_id")
        source_id = item["wrong_question_id"]
        upload_note = f"我们来重新搞懂这道题（第 {item.get('question_number', '')} 题）。"
    elif source_type == "uploaded_question":
        analysis = await _analyze_upload(question_text, image)
        if analysis is None:
            raise ValueError("question_not_recognized")
        knowledge_point_id = analysis["knowledge_point_ids"][0]
        source_id = None
        point = knowledge.get_point(knowledge_point_id)
        upload_note = (
            f"我看了你拍的这道题，它主要考「{point.name if point else '导数'}」。"
            f"我们先把它背后的概念弄清楚。"
        )

    kp_id = _resolve_knowledge_point(user_id, knowledge_point_id)

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

def turn_body(session: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """把内部结果组装成对外的响应体（JSON 与 SSE 共用同一份）。"""
    return {
        "tutor_session_id": session["tutor_session_id"],
        "evaluation": result["evaluation"],
        "turn": result["turn"],
        "phase": session["phase"],
        "completed": session["completed"],
        "progress": result["turn"]["progress"],
        "student_understanding": session["student_understanding"],
        "knowledge_changes": result["knowledge_changes"],
        "next_action": session.get("next_action"),
    }


def submit_answer(
    user_id: str,
    session_id: str,
    *,
    selected_key: str | None = None,
    text: str | None = None,
    self_reported_confidence: str | None = None,
    answering_turn_id: str | None = None,
) -> dict[str, Any]:
    session = repositories.get_tutor_session(session_id)
    if session is None or session.get("user_id") != user_id:
        raise LookupError("session")

    # ------------------------------------------------------------------
    # 重放保护：客户端把「我正在回答哪一轮」的 turn_id 回传过来
    # ------------------------------------------------------------------
    #
    # 练习接口靠 question_id 天然分辨重试；Tutor 没有这个东西 ——
    # 客户端只说「我选了 A」，服务端无法区分「网络重试」和「真的答下一题」。
    # 于是同一份作答连发两次会被当成两次作答，第二次还会消费掉下一轮，
    # 学生根本没看见那道题就被记了 Evidence。
    #
    # 所以让客户端回显它正在回答的那一轮的 turn_id：
    # 这一轮如果已经答过，直接原样回放，不再推进、不再写 Evidence。
    #
    # ⚠️ 顺序：必须在 completed 检查**之前**。
    # 最后一轮答完时会话已经 completed，此时的重试应当拿到上次结果，
    # 而不是被判成「会话已结束」。（练习那边踩过同样的坑。）
    answered: dict[str, Any] = session.get("answered_turns") or {}
    if answering_turn_id and answering_turn_id in answered:
        return {
            "replayed": True,
            "session": session,
            "body": answered[answering_turn_id],
        }

    if session.get("completed"):
        raise RuntimeError("completed")

    # 客户端正在回答的那一轮（用于处理完后登记「已答过」）
    answered_turn_id = (session.get("history") or [{}])[-1].get("turn_id")

    plan = session["plan"]
    index = session.get("step_index", 0)

    step = _active_step(session)
    if step is None:
        raise RuntimeError("completed")
    content = step["content"]
    kind = step["kind"]
    in_remedial = session.get("remedial") is not None

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
                    question_stem_hash=stem_fingerprint(
                        str(content.get("text") or content.get("question_id") or "")
                    ),
                    error_type=None if is_correct else "conceptual",
                    confidence=1.0 if kind != "remedial" else 0.7,
                    detail=None
                    if is_correct
                    else (
                        f"辅导中第 {_remedial_depth(session)} 层补救题仍答错"
                        if in_remedial
                        else "在 AI Tutor 的概念诊断中作答错误"
                    ),
                    answer_excerpt=chosen,
                )
            ],
        )
        # Tutor 的题来自教学脚本，没有题库题目 id，所以按知识点反查标签计分
        tag_service.apply_for_knowledge_point(user_id, session["knowledge_point_id"], is_correct)

    # ------------------------------------------------------------------
    # 教学策略：由服务端决定，客户端只负责呈现
    # ------------------------------------------------------------------
    strategy: str
    answer_reveal: dict[str, Any] | None = None

    if in_remedial:
        if is_correct:
            # 任意一层答对 → 结束补救，回到正常教学/下一正式题
            _end_remedial(session)
            session["hint_count"] = 0
            strategy = "advance"
            answer_reveal = {"current": _revealed(content), "origin": None}
        elif _deeper_remedial(session):
            # 还没到上限，继续下探一层
            strategy = "simplify"
        else:
            # 第 4 层仍答错（或没题可出了）→ 停止生成问题，揭示答案
            origin = _end_remedial(session)
            session["hint_count"] = 0
            strategy = "reveal_answer"
            answer_reveal = {
                "current": _revealed(content),
                "origin": _revealed(origin or {}),
            }
    elif is_correct:
        session["step_index"] = index + 1
        session["hint_count"] = 0
        strategy = "advance"
        answer_reveal = {"current": _revealed(content), "origin": None}
    elif _start_remedial(session, origin_index=index, origin_step=step):
        # 正式题答错 → 进入补救第 1 层
        strategy = "simplify"
    elif session.get("hint_count", 0) < MAX_HINTS:
        session["hint_count"] = session.get("hint_count", 0) + 1
        strategy = "hint"
    else:
        session["step_index"] = index + 1
        session["hint_count"] = 0
        strategy = "re_explain"
        answer_reveal = {"current": _revealed(content), "origin": None}

    # 跳过不需要学生作答的步骤：explain（讲解卡片）不是问题，不该等作答，
    # 其文字并入下一轮。
    preamble: list[str] = []
    while session["step_index"] < len(plan):
        upcoming = plan[session["step_index"]]
        if upcoming["kind"] == "explain":
            preamble.append(upcoming["content"]["text"])
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
    if strategy == "simplify":
        # 进入补救（第 1 层）与继续下探要用不同措辞：
        # 第 1 层是「刚答错」，说「还是不对」会觉得莫名其妙。
        depth = _remedial_depth(session)
        if depth <= 1:
            feedback = (
                f"这道题我们换个更简单的角度再看一次"
                f"（第 1/{MAX_REMEDIAL_DEPTH} 层）。"
            )
        else:
            feedback = (
                f"还是不对。我们把这一步再拆细一点"
                f"（第 {depth}/{MAX_REMEDIAL_DEPTH} 层）。"
            )
    if strategy == "reveal_answer":
        feedback = (
            "这道题我们换个方式讲。"
            "下面直接给你正确答案和解析 —— 看完我们就继续下一题。"
        )

    # 答对且当前步骤带解析 → 立刻把解析给出来（保持原有语义）
    explanation = (
        content["explanation"] if (is_correct and content.get("explanation")) else None
    )

    if preamble:
        feedback = "\n\n".join([feedback, *preamble])
    turn = _render_turn(
        session,
        after_wrong=not is_correct,
        feedback=feedback,
        strategy=strategy,
        answer_reveal=answer_reveal,
    )
    #: 补救耗尽用**独立字段**表达，不要覆盖 `turn_type`。
    #:
    #: 原来是把 turn_type 强行改成 remedial_exhausted，但那时候会话已经推进到
    #: 下一题（甚至已经完成），turn 里装的其实是下一题的内容。前端按文档
    #: 渲染成"解析卡 + 下一题按钮"，就会**把真正的下一题选项藏起来**；
    #: 如果这一轮正好走完，连完成总结都会被盖掉。
    #:
    #: 现在 `turn_type` 始终描述 turn 里真实装的东西，
    #: "要不要展示解析卡"由 `answer_reveal` / `remedial_exhausted` 表达。
    turn["remedial_exhausted"] = strategy == "reveal_answer"
    record = _persist_turn(session, turn)

    # 显式先把 phase 刷新到最新，再组装响应体。
    # （_save 也会做这件事，但它在下面才执行 —— 顺序反了的话
    #   响应里的 phase 会是上一轮的旧值。）
    session["phase"] = _phase_of(session)

    result = {
        "replayed": False,
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
            "remedial_depth": _remedial_depth(session),
            "remedial_exhausted": strategy == "reveal_answer",
        },
        "knowledge_changes": [
            c.model_dump(mode="json") for c in evidence_changes
        ],
    }
    body = turn_body(session, result)
    result["body"] = body

    # 登记「这一轮已经答过」——下次客户端拿同一个 turn_id 回来就直接回放
    if answered_turn_id:
        answered[answered_turn_id] = body
        session["answered_turns"] = answered

    _save(session)
    return result


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
