"""知识点树与错误类型分类法。

范围按规划 §21 刻意收窄：首版只做「高中数学 - 函数 / 导数」，
一个领域做深，而不是所有领域做浅。

知识点 id 是对外 API 契约的一部分，客户端会长期持有，**不要随意改名**。
新增知识点请只追加，不要重排。
"""

from __future__ import annotations

from dataclasses import dataclass

SUBJECT_MATH = "math"


@dataclass(frozen=True)
class KnowledgePoint:
    id: str
    name: str
    parent_id: str | None
    description: str
    # 该知识点的典型难度档位 1..5，用于日志与推荐难度起点。
    difficulty_band: int
    # 前置知识点：没掌握它们，学这个是空中楼阁。
    prerequisites: tuple[str, ...] = ()


# 仅追加，不要重排 / 改名。
_RAW: tuple[KnowledgePoint, ...] = (
    KnowledgePoint(
        id="math.function",
        name="函数",
        parent_id=None,
        description="函数的基本概念、性质与图像",
        difficulty_band=2,
    ),
    KnowledgePoint(
        id="math.function.monotonicity",
        name="函数单调性",
        parent_id="math.function",
        description="用定义或图像判断函数的单调性",
        difficulty_band=3,
    ),
    KnowledgePoint(
        id="math.derivative",
        name="导数",
        parent_id=None,
        description="导数的概念、运算与应用",
        difficulty_band=3,
    ),
    KnowledgePoint(
        id="math.derivative.basic",
        name="基础求导",
        parent_id="math.derivative",
        description="基本初等函数求导、四则运算与复合函数求导",
        difficulty_band=2,
    ),
    KnowledgePoint(
        id="math.derivative.inequality",
        name="解导数不等式",
        parent_id="math.derivative",
        description="解 f'(x) > 0 / f'(x) < 0 这类不等式",
        difficulty_band=3,
        prerequisites=("math.derivative.basic",),
    ),
    KnowledgePoint(
        id="math.derivative.monotonicity",
        name="单调性",
        parent_id="math.derivative",
        description="由导数符号判断函数的单调区间",
        difficulty_band=3,
        prerequisites=("math.derivative.inequality", "math.function.monotonicity"),
    ),
    KnowledgePoint(
        id="math.derivative.extremum",
        name="极值",
        parent_id="math.derivative",
        description="由导数变号判断极值与最值",
        difficulty_band=4,
        prerequisites=("math.derivative.monotonicity",),
    ),
    KnowledgePoint(
        id="math.derivative.comprehensive",
        name="综合应用",
        parent_id="math.derivative",
        description="导数与参数、方程根的分布等综合问题",
        difficulty_band=5,
        prerequisites=("math.derivative.extremum",),
    ),
    KnowledgePoint(
        id="math.sequence",
        name="数列",
        parent_id=None,
        description="等差、等比数列与递推",
        difficulty_band=3,
    ),
    KnowledgePoint(
        id="math.probability",
        name="概率统计",
        parent_id=None,
        description="古典概型、分布与统计量",
        difficulty_band=3,
    ),
)

_BY_ID: dict[str, KnowledgePoint] = {kp.id: kp for kp in _RAW}


# 错误类型分类法：Evidence 里 error_type 必须取自这里。
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
    return tuple(kp for kp in _RAW if kp.parent_id is None)


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


def is_known(kp_id: str) -> bool:
    return kp_id in _BY_ID
