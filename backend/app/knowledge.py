"""知识点清单与错误类型分类法。

**知识点 ID 与名称严格取自团队给定的 `knowledge_points.json`（version 1），
不要自行增删或改写。** 前端、题库录入标准、后端三边都依赖这同一份清单，
改这里等于改契约。

清单是**扁平**的（官方没有层级），所以这里全部是顶层节点、没有父子关系。
`default_difficulty` 与 `prerequisites` 是**服务端自己的元数据**，不写进题库 ——
题库规范明确禁止 `difficulty` 之类的自定义字段，所以题目难度在这里兜底。
"""

from __future__ import annotations

from dataclasses import dataclass

SUBJECT_MATH = "math"


@dataclass(frozen=True)
class KnowledgePoint:
    id: str
    name: str
    description: str
    # 服务端兜底用的难度 0..1（题库里不写 difficulty）
    default_difficulty: float
    parent_id: str | None = None
    prerequisites: tuple[str, ...] = ()


# 与 knowledge_points.json (version 1) 逐字一致 —— 只允许追加，不要改名。
_RAW: tuple[KnowledgePoint, ...] = (
    KnowledgePoint(
        id="math.derivative.monotonicity",
        name="利用导数判断函数单调性与单调区间",
        description="由 f'(x) 的符号判断函数的单调性，并求出单调区间",
        default_difficulty=0.45,
    ),
    KnowledgePoint(
        id="math.derivative.monotonicity_parameter",
        name="利用单调性或导数恒成立求参数",
        description="已知函数在某区间上的单调性，反过来求参数的取值范围",
        default_difficulty=0.65,
        prerequisites=("math.derivative.monotonicity",),
    ),
    KnowledgePoint(
        id="math.derivative.monotonicity_applications",
        name="导数与函数性质综合应用",
        description="把单调性、极值、最值串起来解决综合问题，含参数讨论与方程根的分布",
        default_difficulty=0.80,
        prerequisites=("math.derivative.monotonicity", "math.derivative.extrema"),
    ),
    KnowledgePoint(
        id="math.derivative.extrema",
        name="利用导数判断与求解极值",
        description="由 f'(x) 的变号判断极值点并求出极值",
        default_difficulty=0.50,
        prerequisites=("math.derivative.monotonicity",),
    ),
    KnowledgePoint(
        id="math.derivative.extrema_parameter",
        name="根据极值或最值条件求参数",
        description="已知在某点取得极值（或取到最值）反求参数",
        default_difficulty=0.70,
        prerequisites=("math.derivative.extrema",),
    ),
    KnowledgePoint(
        id="math.derivative.absolute_extrema",
        name="利用导数求函数最值",
        description="求闭区间上的最大值与最小值，注意端点与驻点都要比较",
        default_difficulty=0.55,
        prerequisites=("math.derivative.extrema",),
    ),
    KnowledgePoint(
        id="math.function.parity_and_monotonicity",
        name="函数奇偶性与单调性综合判断",
        description="同时判断函数的奇偶性与单调性",
        default_difficulty=0.60,
    ),
)

_BY_ID: dict[str, KnowledgePoint] = {kp.id: kp for kp in _RAW}


# 错误类型分类法：Evidence 里的 error_type 必须取自这里。
ERROR_TYPES: dict[str, str] = {
    "conceptual": "概念理解错误",
    "transformation": "函数性质转换错误",
    "case_analysis": "分类讨论错误",
    "domain_omission": "定义域遗漏",
    "procedural": "计算/步骤错误",
    "careless": "粗心失误",
    "incomplete": "解答不完整",
    "unknown": "未归类错误",
}


def error_label(error_type: str | None) -> str:
    if not error_type:
        return ERROR_TYPES["unknown"]
    return ERROR_TYPES.get(error_type, ERROR_TYPES["unknown"])


def get_point(kp_id: str) -> KnowledgePoint | None:
    return _BY_ID.get(kp_id)


def all_points() -> tuple[KnowledgePoint, ...]:
    return _RAW


def children_of(kp_id: str) -> tuple[KnowledgePoint, ...]:
    return tuple(kp for kp in _RAW if kp.parent_id == kp_id)


def top_level_points() -> tuple[KnowledgePoint, ...]:
    """清单是扁平的，所以全部知识点都是顶层节点。"""
    return _RAW


def ancestors(kp_id: str) -> tuple[KnowledgePoint, ...]:
    chain: list[KnowledgePoint] = []
    current = _BY_ID.get(kp_id)
    while current is not None and current.parent_id is not None:
        parent = _BY_ID.get(current.parent_id)
        if parent is None:
            break
        chain.append(parent)
        current = parent
    return tuple(chain)


def ancestor_ids(kp_id: str) -> tuple[str, ...]:
    return tuple(kp.id for kp in ancestors(kp_id))


def prerequisites(kp_id: str) -> tuple[KnowledgePoint, ...]:
    kp = _BY_ID.get(kp_id)
    if kp is None:
        return ()
    return tuple(_BY_ID[p] for p in kp.prerequisites if p in _BY_ID)


def default_difficulty(kp_id: str) -> float:
    kp = _BY_ID.get(kp_id)
    return kp.default_difficulty if kp else 0.5


def is_known(kp_id: str) -> bool:
    return kp_id in _BY_ID
