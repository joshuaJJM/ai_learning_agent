"""Evidence-based 掌握度计算。

设计原则（规划 §4 / §25 ①：Evidence before judgement）：

    掌握度不是 LLM 拍脑袋给的数字，而是从持续积累的 Evidence 里算出来的。

模型选择：**难度加权 + 时间衰减的 Beta-Binomial 后验均值**。

对某个知识点的每条 Evidence：
  - 观测值 s ∈ [0, 1]：correct=1.0 / partial=0.5 / uncertain=0.30 / incorrect=0.0
  - 权重 w = 来源权重 × 时间衰减 × 难度权重
  - 后验  Beta(α0 + Σ w·s,  β0 + Σ w·(1-s))
  - 掌握度 = α / (α + β)

这么选的理由：
  1. 可解释——每个数字都能反查是哪几条 Evidence 撑起来的；
  2. 小样本稳定——先验兜住「只做过 1 道题」的情况，不会直接跳到 100%；
  3. 难易有区分度——做对难题比做对送分题更能说明掌握；
  4. 有遗忘曲线——30 天前的一次正确不该和昨天的正确等价。

这不是一个学术上最优的 IRT 模型，但它在 48H 内**可解释、可测试、不会漂**。
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from . import knowledge

# ---- 观测值映射 ----
OUTCOME_SCORES: dict[str, float] = {
    "correct": 1.0,
    "partial": 0.5,
    "uncertain": 0.30,
    "incorrect": 0.0,
}

# 对外契约用 correct / wrong / partial / unknown，
# 内部掌握度模型用 correct / incorrect / partial / uncertain。
# 这里做一次归一化，避免契约措辞变化污染算法。
RESULT_ALIASES: dict[str, str] = {
    "correct": "correct",
    "partial": "partial",
    "wrong": "incorrect",
    "incorrect": "incorrect",
    "unknown": "uncertain",
    "uncertain": "uncertain",
}


def normalize_outcome(result: str) -> str:
    return RESULT_ALIASES.get(result, "uncertain")


# ---- 来源权重：考试最可信，Tutor 里的口头回答最不可信 ----
SOURCE_WEIGHTS: dict[str, float] = {
    "exam": 1.00,
    "practice": 0.90,
    "tutor": 0.60,
}

# 弱先验 Beta(1,1) == 均匀分布，先验均值 0.5
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0

# 时间衰减：半衰期约 21 天（exp(-t/30)，30 天衰减到 0.37）
RECENCY_TAU_DAYS = 30.0
RECENCY_FLOOR = 0.25

# 置信度：总权重达到 5.0 时约 63%
CONFIDENCE_W0 = 5.0

TREND_WINDOW = 5
TREND_THRESHOLD = 0.08


@dataclass(frozen=True)
class EvidenceRecord:
    """一条学习证据。这是 Knowledge State 的唯一事实来源。"""

    id: str
    user_id: str
    kp_id: str
    outcome: str
    difficulty: float  # 0.0 .. 1.0
    source: str  # exam | practice | tutor
    created_at: datetime
    error_type: str | None = None
    question_id: str | None = None
    #: 题干内容指纹。question_id 会随题库重新生成而指向别的题，
    #: 指纹只跟内容走 —— 追溯「学生当初做的是哪道题」要靠它。
    question_stem_hash: str | None = None
    question_no: str | None = None
    exam_id: str | None = None
    answer_excerpt: str | None = None
    reason: str | None = None
    # 该证据的可信程度（0..1）。一道题若只是"顺带涉及"某个知识点，
    # 它的相关度会调低这个值，从而少影响掌握度。
    confidence: float = 1.0


@dataclass(frozen=True)
class ErrorPattern:
    error_type: str
    label: str
    count: int
    share: float


@dataclass(frozen=True)
class MasteryEstimate:
    kp_id: str
    mastery: float
    alpha: float
    beta: float
    total_weight: float
    evidence_count: int
    confidence: float
    trend: str  # improving | stable | declining | unknown
    recent_accuracy: float | None
    correct_count: int = 0
    partial_count: int = 0
    incorrect_count: int = 0
    uncertain_count: int = 0


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def evidence_weight(record: EvidenceRecord, now: datetime) -> float:
    """单条 Evidence 的信息量权重。"""
    source_w = SOURCE_WEIGHTS.get(record.source, 0.80)
    age_days = max(0.0, (now - _as_utc(record.created_at)).total_seconds() / 86400.0)
    recency_w = max(RECENCY_FLOOR, math.exp(-age_days / RECENCY_TAU_DAYS))
    difficulty_w = 0.5 + min(1.0, max(0.0, record.difficulty))
    confidence_w = min(1.0, max(0.1, record.confidence))
    return source_w * recency_w * difficulty_w * confidence_w


def _mean_score(records: Sequence[EvidenceRecord]) -> float:
    if not records:
        return 0.0
    return sum(
        OUTCOME_SCORES.get(normalize_outcome(r.outcome), 0.5) for r in records
    ) / len(records)


def _trend(records: Sequence[EvidenceRecord]) -> tuple[str, float | None]:
    """最近一段时间相对更早一段时间，是进步还是退步。"""
    if len(records) < 4:
        return "unknown", _mean_score(records) if records else None

    ordered = sorted(records, key=lambda r: _as_utc(r.created_at))
    recent = ordered[-TREND_WINDOW:]
    prior = ordered[-2 * TREND_WINDOW : -TREND_WINDOW]
    recent_acc = _mean_score(recent)
    if not prior:
        return "unknown", recent_acc

    diff = recent_acc - _mean_score(prior)
    if diff > TREND_THRESHOLD:
        return "improving", recent_acc
    if diff < -TREND_THRESHOLD:
        return "declining", recent_acc
    return "stable", recent_acc


def compute_mastery(
    kp_id: str,
    records: Iterable[EvidenceRecord],
    now: datetime | None = None,
) -> MasteryEstimate:
    """由该知识点的全部 Evidence 计算掌握度。"""
    now = _as_utc(now or datetime.now(timezone.utc))
    items = [r for r in records if r.kp_id == kp_id]

    alpha = PRIOR_ALPHA
    beta = PRIOR_BETA
    total_weight = 0.0
    for record in items:
        s = OUTCOME_SCORES.get(normalize_outcome(record.outcome), 0.5)
        w = evidence_weight(record, now)
        alpha += w * s
        beta += w * (1.0 - s)
        total_weight += w

    mastery = alpha / (alpha + beta)
    confidence = 1.0 - math.exp(-total_weight / CONFIDENCE_W0)
    trend, recent_accuracy = _trend(items)

    counts = Counter(normalize_outcome(r.outcome) for r in items)

    return MasteryEstimate(
        kp_id=kp_id,
        mastery=mastery,
        alpha=alpha,
        beta=beta,
        total_weight=total_weight,
        evidence_count=len(items),
        confidence=confidence,
        trend=trend,
        recent_accuracy=recent_accuracy,
        correct_count=counts.get("correct", 0),
        partial_count=counts.get("partial", 0),
        incorrect_count=counts.get("incorrect", 0),
        uncertain_count=counts.get("uncertain", 0),
    )


def error_patterns(
    records: Iterable[EvidenceRecord], limit: int = 5
) -> list[ErrorPattern]:
    """从错误 / 部分正确的 Evidence 里提炼主要错误模式。"""
    counts: Counter[str] = Counter()
    for record in records:
        if normalize_outcome(record.outcome) in ("incorrect", "partial") and record.error_type:
            counts[record.error_type] += 1

    total = sum(counts.values())
    if total == 0:
        return []

    patterns = [
        ErrorPattern(
            error_type=etype,
            label=knowledge.error_label(etype),
            count=count,
            share=count / total,
        )
        for etype, count in counts.most_common(limit)
    ]
    return patterns


def aggregate_mastery(
    kp_id: str,
    child_estimates: Sequence[MasteryEstimate],
) -> MasteryEstimate:
    """父节点掌握度：按子节点的证据总量加权。

    没有任何子节点有证据时退化为子节点掌握度的等权平均，
    这样知识树不会出现空洞，但 confidence 会诚实地保持很低。
    """
    weighted = [e for e in child_estimates if e.total_weight > 0]
    if not weighted:
        pool = child_estimates
        mean = sum(e.mastery for e in pool) / len(pool) if pool else 0.5
        return MasteryEstimate(
            kp_id=kp_id,
            mastery=mean,
            alpha=PRIOR_ALPHA,
            beta=PRIOR_BETA,
            total_weight=0.0,
            evidence_count=0,
            confidence=0.0,
            trend="unknown",
            recent_accuracy=None,
        )

    total_weight = sum(e.total_weight for e in weighted)
    mastery = sum(e.mastery * e.total_weight for e in weighted) / total_weight
    evidence_count = sum(e.evidence_count for e in weighted)
    confidence = 1.0 - math.exp(-total_weight / CONFIDENCE_W0)

    trends = [e.trend for e in weighted if e.trend != "unknown"]
    trend = "unknown"
    if trends:
        trend = Counter(trends).most_common(1)[0][0]

    return MasteryEstimate(
        kp_id=kp_id,
        mastery=mastery,
        alpha=PRIOR_ALPHA + total_weight * mastery,
        beta=PRIOR_BETA + total_weight * (1.0 - mastery),
        total_weight=total_weight,
        evidence_count=evidence_count,
        confidence=confidence,
        trend=trend,
        recent_accuracy=None,
        correct_count=sum(e.correct_count for e in weighted),
        partial_count=sum(e.partial_count for e in weighted),
        incorrect_count=sum(e.incorrect_count for e in weighted),
        uncertain_count=sum(e.uncertain_count for e in weighted),
    )
