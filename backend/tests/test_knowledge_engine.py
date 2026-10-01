"""Knowledge Engine 单元测试。

掌握度必须是**可解释、可复现**的——这是整个产品的立身之本
（规划 §25 ①：Evidence before judgement）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.mastery import (
    EvidenceRecord,
    compute_mastery,
    error_patterns,
    evidence_weight,
    normalize_outcome,
)
from app import db


def _record(
    result: str,
    *,
    kp_id: str = "kp",
    difficulty: float = 0.5,
    days_ago: float = 1.0,
    source: str = "exam",
    error_type: str | None = None,
    created_at: datetime | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        id=db.new_id("ev"),
        user_id="u_test",
        kp_id=kp_id,
        outcome=result,
        difficulty=difficulty,
        source=source,
        created_at=created_at or (db.utcnow() - timedelta(days=days_ago)),
        error_type=error_type,
    )


def test_empty_evidence_returns_prior() -> None:
    estimate = compute_mastery("math.derivative.basic", [])
    assert estimate.mastery == 0.5
    assert estimate.evidence_count == 0
    assert estimate.confidence == 0.0
    assert estimate.trend == "unknown"


def test_correct_answers_raise_mastery() -> None:
    records = [_record("correct", days_ago=index + 1) for index in range(6)]
    estimate = compute_mastery("kp", records)
    assert estimate.mastery > 0.75
    assert estimate.evidence_count == 6
    assert estimate.correct_count == 6


def test_wrong_answers_lower_mastery() -> None:
    records = [_record("wrong", days_ago=index + 1) for index in range(6)]
    estimate = compute_mastery("kp", records)
    assert estimate.mastery < 0.25
    assert estimate.incorrect_count == 6


def test_harder_correct_answers_count_more() -> None:
    easy = compute_mastery("kp", [_record("correct", difficulty=0.0) for _ in range(4)])
    hard = compute_mastery("kp", [_record("correct", difficulty=1.0) for _ in range(4)])
    assert hard.mastery > easy.mastery


def test_recent_evidence_weighs_more_than_old() -> None:
    recent = _record("correct", days_ago=0)
    old = _record("correct", days_ago=200)
    now = db.utcnow()
    assert evidence_weight(recent, now) > evidence_weight(old, now)


def test_contract_result_names_are_normalized() -> None:
    """契约里叫 wrong，内部叫 incorrect——必须能对上。"""
    assert normalize_outcome("wrong") == "incorrect"
    assert normalize_outcome("correct") == "correct"
    assert normalize_outcome("unknown") == "uncertain"

    # 用完全相同的时间锚点，否则两条记录的 recency 权重会有微小差异，
    # 浮点结果就不可能严格相等（这个测试之前就是这么偶发失败的）。
    base = db.utcnow()
    shared = [base - timedelta(days=index + 1) for index in range(4)]

    via_contract = compute_mastery(
        "kp",
        [_record("wrong", created_at=stamp) for stamp in shared],
        now=base,
    )
    via_internal = compute_mastery(
        "kp",
        [_record("incorrect", created_at=stamp) for stamp in shared],
        now=base,
    )
    assert via_contract.mastery == via_internal.mastery
    assert via_contract.evidence_count == 4


def test_error_patterns_are_counted_and_sorted() -> None:
    records = [
        _record("wrong", error_type="case_analysis"),
        _record("wrong", error_type="case_analysis"),
        _record("partial", error_type="case_analysis"),
        _record("wrong", error_type="domain_omission"),
        _record("correct", error_type=None),
    ]
    patterns = error_patterns(records)
    assert patterns[0].error_type == "case_analysis"
    assert patterns[0].count == 3
    assert patterns[0].label == "分类讨论错误"
    assert patterns[1].error_type == "domain_omission"
    assert abs(patterns[0].share - 0.75) < 1e-9


def test_trend_detects_improvement() -> None:
    old_failures = [_record("wrong", days_ago=30 - index) for index in range(5)]
    recent_success = [_record("correct", days_ago=4 - index) for index in range(5)]
    estimate = compute_mastery("kp", old_failures + recent_success)
    assert estimate.trend == "improving"


def test_confidence_grows_with_evidence() -> None:
    few = compute_mastery("kp", [_record("correct")])
    many = compute_mastery("kp", [_record("correct", days_ago=index) for index in range(12)])
    assert many.confidence > few.confidence


def test_parent_mastery_aggregates_children() -> None:
    """父节点掌握度必须由子节点聚合，而不是凭空算。"""
    from app.mastery import aggregate_mastery

    child_a = compute_mastery("a", [_record("correct", kp_id="a") for _ in range(6)])
    child_b = compute_mastery("b", [_record("wrong", kp_id="b") for _ in range(6)])
    parent = aggregate_mastery("parent", [child_a, child_b])
    assert child_b.mastery < parent.mastery < child_a.mastery
    assert parent.evidence_count == 12
