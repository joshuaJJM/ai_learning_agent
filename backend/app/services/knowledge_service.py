"""Knowledge Engine —— 全系统**唯一**的掌握度更新入口。

契约 §19 的要求：

    Activity → Evidence → Knowledge Engine → Update Mastery

作业分析、Tutor 回答、独立练习，全部只能调用 `apply_evidence()`。
任何地方都不允许自己算一遍掌握度，否则同一份数据会算出两个数字。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .. import db, knowledge, repositories
from ..mastery import (
    ErrorPattern,
    EvidenceRecord,
    MasteryEstimate,
    aggregate_mastery,
    compute_mastery,
    error_patterns,
    normalize_outcome,
)
from ..schemas import (
    EvidenceItem,
    ErrorPatternOut,
    KnowledgeChange,
    KnowledgeNode,
    KnowledgePointRef,
    RecentPerformancePoint,
    WeakPoint,
)

# 前置知识点低于这个掌握度，才认为"没过关"，会拦住后续知识点。
PREREQUISITE_BLOCK = 0.45


@dataclass(frozen=True)
class EvidenceInput:
    """一次学习行为产生的证据（尚未落库）。"""

    knowledge_point_id: str
    result: str  # correct | wrong | partial | unknown
    difficulty: float
    source_type: str  # homework | tutor | practice | exam
    source_id: str | None = None
    question_id: str | None = None
    #: 题干内容指纹（可选）。让作答历史独立于题库版本被追溯。
    question_stem_hash: str | None = None
    error_type: str | None = None
    confidence: float = 1.0
    detail: str | None = None
    answer_excerpt: str | None = None


# ---------------------------------------------------------------------------
# 掌握度读取
# ---------------------------------------------------------------------------

def _records_by_point(user_id: str) -> dict[str, list[EvidenceRecord]]:
    grouped: dict[str, list[EvidenceRecord]] = {}
    for record in repositories.evidence_records(user_id):
        grouped.setdefault(record.kp_id, []).append(record)
    return grouped


def mastery_map(user_id: str) -> dict[str, MasteryEstimate]:
    """返回**所有**知识点的掌握度估计，父节点由子节点聚合而来。"""
    grouped = _records_by_point(user_id)
    leaf: dict[str, MasteryEstimate] = {
        point.id: compute_mastery(point.id, grouped.get(point.id, []))
        for point in knowledge.all_points()
    }
    memo: dict[str, MasteryEstimate] = {}

    def aggregate(kp_id: str) -> MasteryEstimate:
        if kp_id in memo:
            return memo[kp_id]
        children = knowledge.children_of(kp_id)
        if not children:
            result = leaf[kp_id]
        else:
            child_estimates = [aggregate(child.id) for child in children]
            # 该知识点自己直接命中的 Evidence 也参与加权
            own = leaf.get(kp_id)
            if own is not None and own.total_weight > 0:
                child_estimates = [*child_estimates, own]
            result = aggregate_mastery(kp_id, child_estimates)
        memo[kp_id] = result
        return result

    for point in knowledge.all_points():
        aggregate(point.id)
    return memo


def mastery_of(user_id: str, kp_id: str) -> MasteryEstimate:
    return mastery_map(user_id).get(kp_id) or compute_mastery(kp_id, [])


# ---------------------------------------------------------------------------
# 综合掌握度（一个大数字，给首页用）
# ---------------------------------------------------------------------------

def overall_mastery(user_id: str) -> dict[str, Any]:
    """对所有知识点的综合掌握度，返回一个 0–99 的整数百分比。

    本项目里 17 个标签与 17 个知识点**一一对应**（标签名就是知识点名），
    所以「所有标签的掌握度平均」等价于「所有知识点的掌握度平均」。

    算法（两步，刻意做得能一句话讲清）：

      1. **置信度加权平均**：只统计有证据的知识点，但证据少的点发言权小。
             raw = Σ(mastery_i × confidence_i) / Σ(confidence_i)
         用 confidence 而不是简单平均，是因为一个只有 1 条证据的知识点
         给出的掌握度本来就不可信，不该和练了 20 次的一样重。

      2. **覆盖率折算**：光看平均值会误导 —— 只练了 1 个知识点、恰好答对，
         平均值能到 65%，但那显然不代表「掌握了 65% 的知识体系」。
             score = raw × (已练知识点数 / 总知识点数)

    于是：
        什么都没做            → 0
        练了 5/17，平均 60%   → 60% × 5/17 ≈ 18
        17 个全练，平均 60%   → 60

    宁可偏低也不虚高 —— 这个数字是要给学生看的，虚高比偏低有害得多。
    """
    estimates = mastery_map(user_id)
    total_points = len(estimates)
    covered = [item for item in estimates.values() if item.total_weight > 0]

    evidence_count = sum(item.evidence_count for item in covered)
    if not covered or total_points == 0:
        return {
            "score": 0,
            "percent": 0.0,
            "weighted_mastery": 0.0,
            "coverage": 0.0,
            "covered_count": 0,
            "point_count": total_points,
            "evidence_count": 0,
            "weakest": [],
        }

    weight_sum = sum(item.confidence for item in covered)
    if weight_sum > 0:
        raw = sum(item.mastery * item.confidence for item in covered) / weight_sum
    else:
        # 置信度全为 0 的极端情况（证据权重被时间衰减压到极低），退回简单平均
        raw = sum(item.mastery for item in covered) / len(covered)

    coverage = len(covered) / total_points
    score = int(round(raw * coverage * 100))
    score = max(0, min(99, score))  # 契约：两位数

    weakest = sorted(covered, key=lambda item: item.mastery)[:3]
    return {
        "score": score,
        "percent": round(raw * coverage, 4),
        "weighted_mastery": round(raw, 4),
        "coverage": round(coverage, 4),
        "covered_count": len(covered),
        "point_count": total_points,
        "evidence_count": evidence_count,
        "weakest": [
            {
                "knowledge_point_id": item.kp_id,
                "name": (knowledge.get_point(item.kp_id).name
                         if knowledge.get_point(item.kp_id) else item.kp_id),
                "mastery": round(item.mastery, 4),
            }
            for item in weakest
        ],
    }


# ---------------------------------------------------------------------------
# 掌握度写入（唯一入口）
# ---------------------------------------------------------------------------

def apply_evidence(
    user_id: str, entries: Sequence[EvidenceInput]
) -> list[KnowledgeChange]:
    """写入 Evidence 并返回掌握度变化。

    这是契约 §19 要求的统一函数：所有活动最后都走这里。
    """
    if not entries:
        return []

    affected = {
        e.knowledge_point_id
        for e in entries
        if knowledge.is_known(e.knowledge_point_id)
    }
    if not affected:
        return []

    before = {kp_id: mastery_of(user_id, kp_id).mastery for kp_id in affected}

    for entry in entries:
        if not knowledge.is_known(entry.knowledge_point_id):
            continue
        repositories.add_evidence(
            user_id=user_id,
            knowledge_point_id=entry.knowledge_point_id,
            result=entry.result,
            difficulty=entry.difficulty,
            source_type=entry.source_type,
            source_id=entry.source_id,
            question_id=entry.question_id,
            question_stem_hash=entry.question_stem_hash,
            error_type=entry.error_type,
            confidence=entry.confidence,
            detail=entry.detail,
            answer_excerpt=entry.answer_excerpt,
        )

    after_map = mastery_map(user_id)
    changes: list[KnowledgeChange] = []
    for kp_id in sorted(affected):
        point = knowledge.get_point(kp_id)
        if point is None:
            continue
        after_estimate = after_map.get(kp_id)
        after_value = after_estimate.mastery if after_estimate else before[kp_id]
        changes.append(
            KnowledgeChange(
                knowledge_point_id=kp_id,
                name=point.name,
                before=round(before[kp_id], 4),
                after=round(after_value, 4),
                delta=round(after_value - before[kp_id], 4),
                evidence_count=after_estimate.evidence_count if after_estimate else 0,
            )
        )
    return changes


# ---------------------------------------------------------------------------
# 知识树 / 薄弱点
# ---------------------------------------------------------------------------

def build_tree(user_id: str) -> list[KnowledgeNode]:
    estimates = mastery_map(user_id)

    def node(kp_id: str) -> KnowledgeNode:
        point = knowledge.get_point(kp_id)
        estimate = estimates[kp_id] if kp_id in estimates else compute_mastery(kp_id, [])
        children = [node(child.id) for child in knowledge.children_of(kp_id)]
        return KnowledgeNode(
            knowledge_point_id=kp_id,
            name=point.name if point else kp_id,
            description=point.description if point else "",
            mastery=round(estimate.mastery, 4),
            confidence=round(estimate.confidence, 4),
            evidence_count=estimate.evidence_count,
            trend=estimate.trend,  # type: ignore[arg-type]
            children=children,
        )

    return [node(point.id) for point in knowledge.top_level_points()]


def _is_actionable(kp_id: str) -> bool:
    """叶子知识点才是可教学的；父节点只是汇总。"""
    return not knowledge.children_of(kp_id)


def _priority(kp_id: str, estimate: MasteryEstimate, estimates: dict[str, MasteryEstimate]) -> tuple[float, str]:
    confidence_factor = 0.35 + 0.65 * estimate.confidence
    score = (1.0 - estimate.mastery) * confidence_factor

    notes: list[str] = []
    blockers = [
        pre
        for pre in knowledge.prerequisites(kp_id)
        if estimates.get(pre.id, compute_mastery(pre.id, [])).mastery < PREREQUISITE_BLOCK
    ]
    if blockers:
        # 前置知识真的没过关，先补前置，这个点往后排。
        # 阈值刻意定得低：前置只是"中等"（比如 50%）时不该拦住学生去攻更难的点，
        # 那样会导致 Agent 永远在补最基础的东西。
        score *= 0.55
        names = "、".join(b.name for b in blockers[:2])
        notes.append(f"前置知识「{names}」尚未牢固，建议先补前置")

    if estimate.trend == "declining":
        score *= 1.25
        notes.append("近期呈下降趋势")
    elif estimate.trend == "improving":
        score *= 0.85
        notes.append("近期正在好转")

    if estimate.evidence_count == 0:
        score *= 0.5
        notes.append("暂无作答证据")
    elif estimate.evidence_count < 3:
        notes.append("证据较少，估计还不够稳定")

    return score, "；".join(notes)


def weakest_points(
    user_id: str, limit: int = 5, include_unseen: bool = False
) -> list[WeakPoint]:
    estimates = mastery_map(user_id)
    scored: list[tuple[float, WeakPoint]] = []

    for point in knowledge.all_points():
        if not _is_actionable(point.id):
            continue
        estimate = estimates.get(point.id)
        if estimate is None:
            continue
        if estimate.evidence_count == 0 and not include_unseen:
            continue
        score, note = _priority(point.id, estimate, estimates)
        reason = (
            f"当前掌握度 {estimate.mastery * 100:.0f}%，"
            f"共 {estimate.evidence_count} 条作答证据"
        )
        if note:
            reason += f"；{note}"
        scored.append(
            (
                score,
                WeakPoint(
                    knowledge_point_id=point.id,
                    name=point.name,
                    mastery=round(estimate.mastery, 4),
                    confidence=round(estimate.confidence, 4),
                    priority=round(score, 4),
                    reason=reason,
                ),
            )
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:limit]]


# ---------------------------------------------------------------------------
# 详情页
# ---------------------------------------------------------------------------

def explain_mastery(estimate: MasteryEstimate, records: Sequence[EvidenceRecord]) -> str:
    """把 43% 这个数字翻译成人话——契约 §7 的"为什么是 43%"。"""
    if not records:
        return (
            "还没有与该知识点相关的作答记录，当前显示的是初始估计值，"
            "完成一次作业分析或练习后这里会出现真实数据。"
        )

    parts: list[str] = []
    parts.append(
        f"最近 {len(records)} 次相关作答：正确 {estimate.correct_count} 次、"
        f"部分正确 {estimate.partial_count} 次、错误 {estimate.incorrect_count} 次"
    )
    if estimate.uncertain_count:
        parts.append(f"不确定 {estimate.uncertain_count} 次")

    patterns = error_patterns(records, limit=3)
    if patterns:
        detail = "、".join(f"{p.label} ×{p.count}" for p in patterns)
        parts.append(f"主要错误模式：{detail}")

    parts.append(
        f"按题目难度与时间衰减加权后，掌握度为 {estimate.mastery * 100:.0f}%"
        f"（置信度 {estimate.confidence * 100:.0f}%）"
    )
    if estimate.trend == "improving":
        parts.append("近期表现好于之前，趋势向上")
    elif estimate.trend == "declining":
        parts.append("近期表现不如之前，需要留意")
    return "。".join(parts) + "。"


def _evidence_item(record: EvidenceRecord) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=record.id,
        knowledge_point_id=record.kp_id,
        source_type=record.source,  # type: ignore[arg-type]
        source_id=None,
        question_id=record.question_id,
        question_stem_hash=record.question_stem_hash,
        result=normalize_outcome(record.outcome),
        confidence=1.0,
        error_type=record.error_type,
        error_label=knowledge.error_label(record.error_type),
        answer_excerpt=record.answer_excerpt,
        detail=record.reason,
        created_at=record.created_at,
    )


def knowledge_detail(user_id: str, kp_id: str) -> dict:
    point = knowledge.get_point(kp_id)
    if point is None:
        return {}

    records = repositories.evidence_records(user_id, kp_id)
    estimate = mastery_of(user_id, kp_id)
    patterns: list[ErrorPattern] = error_patterns(records, limit=5)

    ordered = sorted(records, key=lambda r: r.created_at, reverse=True)
    recent = [
        RecentPerformancePoint(
            occurred_at=r.created_at,
            result=normalize_outcome(r.outcome),
            source_type=r.source,
            question_id=r.question_id,
        )
        for r in ordered[:20]
    ]

    prerequisites = [
        KnowledgePointRef(
            knowledge_point_id=pre.id,
            name=pre.name,
            weight=round(mastery_of(user_id, pre.id).mastery, 4),
        )
        for pre in knowledge.prerequisites(kp_id)
    ]

    return {
        "knowledge_point_id": kp_id,
        "name": point.name,
        "description": point.description,
        "subject": point.id.split(".")[0],
        "mastery": round(estimate.mastery, 4),
        "confidence": round(estimate.confidence, 4),
        "trend": estimate.trend,
        "evidence_count": estimate.evidence_count,
        "correct_count": estimate.correct_count,
        "partial_count": estimate.partial_count,
        "wrong_count": estimate.incorrect_count,
        "recent_performance": recent,
        "error_patterns": [
            ErrorPatternOut(
                error_type=p.error_type, label=p.label, count=p.count, share=round(p.share, 4)
            )
            for p in patterns
        ],
        "evidence": [_evidence_item(r) for r in ordered[:50]],
        "prerequisites": prerequisites,
        "mastery_explanation": explain_mastery(estimate, records),
        "updated_at": db.utcnow(),
    }


def summary_nodes(user_id: str) -> list[KnowledgeNode]:
    """首页用：顶层知识点概览。"""
    return build_tree(user_id)


def total_evidence(user_id: str) -> int:
    return repositories.evidence_count(user_id)
