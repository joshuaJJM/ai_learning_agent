"""下一步行动决策。

受控 Agent 的"决策"部分：不引入复杂 planner，
用一条清晰的优先级阶梯 + 真实证据来回答产品最核心的那个问题——
**"我下一步到底该学什么？"**

阶梯（从上到下，第一个命中即返回）：

  1. 调用方指定了知识点，且还没掌握      → 针对它开始 Tutor
  2. 存在掌握度很低的薄弱点              → start_tutor
  3. 有未解决的错题，且薄弱点不算掌握    → review_wrong_question
  4. 薄弱点处于中等水平                  → continue_practice
  5. 薄弱点已经比较稳但还有空间          → increase_difficulty
  6. 全部达标                            → all_good
"""

from __future__ import annotations

from .. import knowledge, repositories
from ..mastery import error_patterns
from ..schemas import NextAction, WeakPoint
from . import knowledge_service

# 决策阈值：集中在这里，方便调节 Agent 的"性格"
MASTERY_WEAK = 0.55
MASTERY_MID = 0.80
MASTERY_STRONG = 0.90


def _error_phrase(user_id: str, kp_id: str, limit: int = 2) -> str:
    records = repositories.evidence_records(user_id, kp_id)
    patterns = error_patterns(records, limit=limit)
    if not patterns:
        return ""
    inner = "、".join(f"{p.label} ×{p.count}" for p in patterns)
    return f"最近 {len(records)} 次相关作答中出现 {inner}"


def _build(
    action: str,
    title: str,
    reason: str,
    cta_label: str,
    kp_id: str | None = None,
    kp_name: str | None = None,
    wrong_question_id: str | None = None,
) -> NextAction:
    return NextAction(
        action=action,  # type: ignore[arg-type]
        title=title,
        reason=reason,
        cta_label=cta_label,
        knowledge_point_id=kp_id,
        knowledge_point_name=kp_name,
        wrong_question_id=wrong_question_id,
    )


def next_action(user_id: str, preferred_kp_id: str | None = None) -> NextAction:
    weak_points = knowledge_service.weakest_points(user_id, limit=5)
    estimates = knowledge_service.mastery_map(user_id)

    # 1. 调用方指名道姓要练某个知识点
    if preferred_kp_id:
        point = knowledge.get_point(preferred_kp_id)
        estimate = estimates.get(preferred_kp_id)
        if point and estimate and estimate.mastery < MASTERY_STRONG:
            phrase = _error_phrase(user_id, preferred_kp_id)
            reason = phrase or (
                f"当前掌握度 {estimate.mastery * 100:.0f}%，还有提升空间"
            )
            return _build(
                "start_tutor",
                f"继续攻克「{point.name}」",
                reason,
                "继续学习",
                point.id,
                point.name,
            )

    top: WeakPoint | None = weak_points[0] if weak_points else None

    # 2. 明显薄弱
    if top is not None and top.mastery < MASTERY_WEAK:
        phrase = _error_phrase(user_id, top.knowledge_point_id)
        reason = phrase or top.reason
        return _build(
            "start_tutor",
            f"下一步：{top.name}",
            reason,
            "开始学习",
            top.knowledge_point_id,
            top.name,
        )

    # 3. 有错题没消化
    open_wrong = repositories.list_wrong_questions(user_id, status="open", limit=1)
    if open_wrong:
        item = open_wrong[0]
        kp_id = item.get("knowledge_point_id")
        point = knowledge.get_point(kp_id) if kp_id else None
        estimate = estimates.get(kp_id) if kp_id else None
        if estimate is None or estimate.mastery < MASTERY_MID:
            return _build(
                "review_wrong_question",
                f"重做错题：{point.name if point else item.get('question_number', '')}",
                "这道题背后的知识点还没有真正过关，重做一遍比刷新题更有效",
                "重做错题",
                kp_id,
                point.name if point else None,
                item.get("wrong_question_id"),
            )

    # 4. 中等，继续练
    if top is not None and top.mastery < MASTERY_MID:
        return _build(
            "continue_practice",
            f"继续巩固「{top.name}」",
            f"掌握度 {top.mastery * 100:.0f}%，再用几道针对练习把它顶上去",
            "开始练习",
            top.knowledge_point_id,
            top.name,
        )

    # 5. 已经不错，加难度
    if top is not None and top.mastery < MASTERY_STRONG:
        return _build(
            "increase_difficulty",
            f"提升「{top.name}」难度",
            f"基础题已经稳定在 {top.mastery * 100:.0f}%，可以挑战更综合的题目了",
            "提高难度",
            top.knowledge_point_id,
            top.name,
        )

    # 6. 没有薄弱点：可能是还没数据，也可能是真达标了
    if not weak_points:
        return _build(
            "start_tutor",
            "先做一次作业分析",
            "还没有足够的学习证据，扫描一份作业或试卷，我就能知道你的起点在哪",
            "去扫描",
            knowledge.top_level_points()[0].id if knowledge.top_level_points() else None,
            "函数与导数",
        )

    best = weak_points[0]
    return _build(
        "all_good",
        "当前知识点都已达标",
        f"最需要关注的是「{best.name}」（{best.mastery * 100:.0f}%），可以稍后复习",
        "稍后复习",
        best.knowledge_point_id,
        best.name,
    )
