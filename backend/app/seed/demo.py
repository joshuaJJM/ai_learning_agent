"""Demo 状态种子。

现场演示需要学生**一开始就有历史**——否则首页空空如也，
Knowledge 页面显示的全是 50% 先验值，讲不出故事。

这个种子把「导数综合应用」压到 43% 附近，其余知识点铺开成有层次的分布，
这样 Demo 的开场就是：

    首页 → 「下一步：综合应用」→ 点进去 → 43% → 开始学习 → 43% → 51%

注意：证据的 days_ago 是相对**播种时刻**计算的，所以演示前
重新调一次 POST /api/v1/demo/seed 就能把时间轴刷新到"最近"。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .. import db, knowledge, repositories
from ..services import book_service


@dataclass(frozen=True)
class SeedRecord:
    result: str  # correct | wrong | partial
    difficulty: float  # 0..1
    days_ago: int
    error_type: str | None = None
    detail: str | None = None


# 时间从远到近排列，这样 trend 的升降是有意义的。
# 知识点 ID 取自官方 knowledge_points.json（version 1）。
DEMO_PLAN: dict[str, tuple[SeedRecord, ...]] = {
    # 判断单调性与单调区间：最基础，很稳
    "math.derivative.monotonicity": (
        SeedRecord("correct", 0.40, 22),
        SeedRecord("correct", 0.40, 17),
        SeedRecord("correct", 0.45, 12),
        SeedRecord("correct", 0.40, 8),
        SeedRecord("correct", 0.50, 4),
        SeedRecord("correct", 0.45, 2),
    ),
    # 恒成立求参数：基本掌握，偶有失手
    "math.derivative.monotonicity_parameter": (
        SeedRecord("correct", 0.55, 19),
        SeedRecord("correct", 0.55, 14),
        SeedRecord("correct", 0.60, 10),
        SeedRecord("correct", 0.55, 7),
        SeedRecord("wrong", 0.60, 5, "procedural", "求参数范围时漏掉了端点 a=0"),
        SeedRecord("partial", 0.60, 3, "procedural", "不等号方向对，但漏了一侧情况"),
        SeedRecord("correct", 0.60, 1),
    ),
    # 判断与求解极值：概念清楚但会漏情况
    "math.derivative.extrema": (
        SeedRecord("correct", 0.60, 20),
        SeedRecord("correct", 0.60, 16),
        SeedRecord("correct", 0.65, 12),
        SeedRecord("partial", 0.65, 9, "transformation", "求出了驻点但没判断变号"),
        SeedRecord("partial", 0.65, 6, "transformation", "把极值点与极值混为一谈"),
        SeedRecord("correct", 0.65, 4),
        SeedRecord("wrong", 0.70, 2, "domain_omission", "忽略了定义域限制"),
    ),
    # 求函数最值：还可以，偶尔漏端点
    "math.derivative.absolute_extrema": (
        SeedRecord("correct", 0.55, 16),
        SeedRecord("correct", 0.55, 12),
        SeedRecord("correct", 0.60, 8),
        SeedRecord("correct", 0.55, 5),
        SeedRecord("wrong", 0.60, 3, "procedural", "只比较了驻点，漏掉了区间端点"),
        SeedRecord("correct", 0.60, 1),
    ),
    # 根据极值条件求参数：会做但漏情况
    "math.derivative.extrema_parameter": (
        SeedRecord("correct", 0.75, 15),
        SeedRecord("correct", 0.75, 11),
        SeedRecord("correct", 0.80, 8),
        SeedRecord("partial", 0.80, 5, "case_analysis", "只讨论了极大值，漏掉极小值"),
        SeedRecord("wrong", 0.80, 3, "case_analysis", "含参讨论时漏了一种情况"),
        SeedRecord("wrong", 0.85, 1, "transformation", "把 f'(x)=0 直接当成极值点"),
    ),
    # ★ 核心薄弱点，目标 ≈ 43%，且近期在退步
    # 4 正确 / 3 部分正确 / 5 错误 —— 与规划文档 §5 的示例一致
    "math.derivative.monotonicity_applications": (
        SeedRecord("correct", 0.90, 25),
        SeedRecord("wrong", 0.90, 23, "case_analysis", "分类讨论时漏了 a<0 的情况"),
        SeedRecord("correct", 0.90, 21),
        SeedRecord("wrong", 0.90, 19, "domain_omission", "没有先确定定义域"),
        SeedRecord("partial", 0.90, 17, "transformation", "把导数符号与函数性质对应反了"),
        SeedRecord("correct", 0.90, 15),
        SeedRecord("wrong", 0.90, 13, "transformation", "由 f'(x) 符号推单调区间时出错"),
        SeedRecord("partial", 0.90, 11, "case_analysis", "参数范围只写了一部分"),
        SeedRecord("correct", 0.95, 9),
        SeedRecord("partial", 0.95, 6, "domain_omission", "端点是否可取没有讨论"),
        SeedRecord("wrong", 0.95, 3, "case_analysis", "分类讨论标准不统一"),
        SeedRecord("wrong", 0.95, 1, "transformation", "图象交点个数判断错误"),
    ),
    # 奇偶性与单调性综合判断：还可以
    "math.function.parity_and_monotonicity": (
        SeedRecord("correct", 0.50, 14),
        SeedRecord("correct", 0.50, 10),
        SeedRecord("correct", 0.55, 6),
        SeedRecord("wrong", 0.55, 3, "conceptual", "用特殊值代替了任意性判断"),
        SeedRecord("correct", 0.55, 1),
    ),
    # ---- 新版题库带来的 10 个知识点，也铺一层证据，避免半棵树停在 50% ----
    # 基本求导法则：很扎实
    "math.derivative.rules": (
        SeedRecord("correct", 0.40, 21),
        SeedRecord("correct", 0.40, 16),
        SeedRecord("correct", 0.45, 11),
        SeedRecord("correct", 0.40, 7),
        SeedRecord("partial", 0.45, 4, "procedural", "复合函数内层导数漏乘"),
        SeedRecord("correct", 0.45, 2),
    ),
    # 导数定义与极限：掌握
    "math.derivative.definition": (
        SeedRecord("correct", 0.35, 18),
        SeedRecord("correct", 0.35, 13),
        SeedRecord("correct", 0.40, 9),
        SeedRecord("wrong", 0.40, 5, "conceptual", "极限式变形时符号弄错"),
        SeedRecord("correct", 0.40, 2),
    ),
    # 几何意义与瞬时变化率：掌握
    "math.derivative.meaning": (
        SeedRecord("correct", 0.35, 17),
        SeedRecord("correct", 0.35, 12),
        SeedRecord("correct", 0.40, 8),
        SeedRecord("partial", 0.40, 4, "conceptual", "把平均变化率当成瞬时变化率"),
        SeedRecord("correct", 0.40, 1),
    ),
    # 切线斜率与倾斜角：中等
    "math.derivative.tangent_slope": (
        SeedRecord("correct", 0.45, 19),
        SeedRecord("correct", 0.45, 14),
        SeedRecord("correct", 0.50, 10),
        SeedRecord("partial", 0.50, 6, "procedural", "倾斜角范围没取对"),
        SeedRecord("wrong", 0.50, 3, "domain_omission", "忽略了倾斜角 [0,π) 的限制"),
        SeedRecord("correct", 0.50, 1),
    ),
    # 曲线切线方程：中等偏弱
    "math.derivative.tangent_equation": (
        SeedRecord("correct", 0.55, 20),
        SeedRecord("correct", 0.55, 15),
        SeedRecord("partial", 0.60, 11, "procedural", "切点坐标代错"),
        SeedRecord("wrong", 0.60, 7, "conceptual", "过点作切线时没设切点"),
        SeedRecord("wrong", 0.60, 4, "case_analysis", "漏了另一条切线"),
        SeedRecord("correct", 0.60, 1),
    ),
    # 切线平行与垂直关系：中等
    "math.derivative.tangent_relations": (
        SeedRecord("correct", 0.60, 16),
        SeedRecord("correct", 0.60, 11),
        SeedRecord("partial", 0.60, 7, "procedural", "垂直条件用成了平行"),
        SeedRecord("wrong", 0.65, 3, "procedural", "斜率乘积算错"),
        SeedRecord("correct", 0.60, 1),
    ),
    # 切线条数与公切线：偏弱但不至于最弱
    "math.derivative.tangent_count": (
        SeedRecord("correct", 0.75, 18),
        SeedRecord("correct", 0.75, 13),
        SeedRecord("correct", 0.75, 10),
        SeedRecord("partial", 0.75, 9, "case_analysis", "只算了一种情况"),
        SeedRecord("wrong", 0.80, 5, "case_analysis", "没讨论切点是否在曲线上"),
        SeedRecord("wrong", 0.80, 2, "conceptual", "把公切线条数当成 1"),
    ),
    # 切线相关最值：偏弱，但要明显高于 Demo 主线（否则树里"最弱"和推荐目标对不上）
    "math.derivative.tangent_optimization": (
        SeedRecord("correct", 0.80, 17),
        SeedRecord("correct", 0.80, 13),
        SeedRecord("partial", 0.80, 12, "procedural", "目标函数列错"),
        SeedRecord("wrong", 0.85, 8, "transformation", "没把几何条件转成函数"),
        SeedRecord("wrong", 0.85, 1, "case_analysis", "漏掉端点情形"),
    ),
    # 函数关系式与导数综合：中等偏弱
    "math.derivative.function_relations": (
        SeedRecord("correct", 0.70, 19),
        SeedRecord("correct", 0.70, 14),
        SeedRecord("partial", 0.70, 10, "transformation", "对 f'(x) 的不等式方向判断反"),
        SeedRecord("wrong", 0.75, 6, "conceptual", "没有构造函数就套结论"),
        SeedRecord("correct", 0.70, 2),
    ),
    # 对称性与周期性的导数关系：偏弱
    "math.function.symmetry_periodicity_derivative": (
        SeedRecord("correct", 0.75, 17),
        SeedRecord("correct", 0.75, 12),
        SeedRecord("partial", 0.75, 8, "transformation", "周期性推对了但对称性推错"),
        SeedRecord("wrong", 0.80, 5, "conceptual", "认为导函数一定也是周期函数"),
        SeedRecord("wrong", 0.80, 1, "case_analysis", "奇偶性判断反了"),
    ),
}


def reset_user_data(user_id: str) -> dict[str, int]:
    """清空该用户的学习数据（保留用户本身）。"""
    counts: dict[str, int] = {}
    for table, column in (
        ("evidence", "user_id"),
        ("homeworks", "user_id"),
        ("questions", "user_id"),
        ("wrong_questions", "user_id"),
        ("analyses", "user_id"),
        ("tutor_sessions", "user_id"),
        ("practice_sessions", "user_id"),
        ("entitlements", "user_id"),
        # 标签分数也要清掉，否则 Demo 的标签不是从 0 开始
        ("tag_scores", "user_id"),
    ):
        cursor = db.execute(f"DELETE FROM {table} WHERE {column} = ?", [user_id])
        counts[table] = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
    return counts


def seed_demo(user_id: str, *, reset: bool = True) -> dict[str, Any]:
    """写入 Demo 证据。返回播种结果与各知识点掌握度（便于核对）。"""
    from ..services import knowledge_service

    if reset:
        reset_user_data(user_id)

    now = db.utcnow()
    created = 0
    for kp_id, records in DEMO_PLAN.items():
        for record in records:
            repositories.add_evidence(
                user_id=user_id,
                knowledge_point_id=kp_id,
                result=record.result,
                difficulty=record.difficulty,
                source_type="exam",
                source_id="demo-seed",
                error_type=record.error_type,
                confidence=1.0,
                detail=record.detail,
                created_at=now - timedelta(days=record.days_ago),
            )
            created += 1

    book_service.ensure_default_entitlements(user_id)

    estimates = knowledge_service.mastery_map(user_id)
    summary = {}
    for kp_id in DEMO_PLAN:
        point = knowledge.get_point(kp_id)
        estimate = estimates[kp_id]
        summary[kp_id] = {
            "name": point.name if point else kp_id,
            "mastery": round(estimate.mastery, 4),
            "evidence_count": estimate.evidence_count,
            "trend": estimate.trend,
        }

    return {
        "user_id": user_id,
        "evidence_created": created,
        "reset": reset,
        "mastery": summary,
        "weakest": [
            {
                "knowledge_point_id": w.knowledge_point_id,
                "name": w.name,
                "mastery": w.mastery,
                "reason": w.reason,
            }
            for w in knowledge_service.weakest_points(user_id, limit=3)
        ],
    }
