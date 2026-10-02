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
from pathlib import Path

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
    # ---- 以下 10 个来自 2026-10-02 的新版题库（导数综合题库 3）----
    # 官方的 knowledge_points.json 目前仍是 version 1（只有上面 7 个），
    # 新版题库实际用到了 17 个。这里按题库里的 tags 逐字补齐，
    # 否则 73 道题里有 46 道会因为没有有效知识点映射而被丢弃。
    # 待官方清单更新到 version 2 后，应与那边对齐。
    KnowledgePoint(
        id="math.derivative.definition",
        name="导数定义与极限",
        description="用极限定义理解导数，求平均变化率的极限",
        default_difficulty=0.35,
    ),
    KnowledgePoint(
        id="math.derivative.meaning",
        name="导数的几何意义与瞬时变化率",
        description="导数就是切线斜率，表示瞬时变化率",
        default_difficulty=0.35,
        prerequisites=("math.derivative.definition",),
    ),
    KnowledgePoint(
        id="math.derivative.rules",
        name="基本求导公式与运算法则",
        description="基本初等函数求导、四则运算与复合函数求导",
        default_difficulty=0.40,
        prerequisites=("math.derivative.definition",),
    ),
    KnowledgePoint(
        id="math.derivative.tangent_slope",
        name="切线斜率与倾斜角",
        description="由导数求切线斜率，进而求倾斜角",
        default_difficulty=0.45,
        prerequisites=("math.derivative.meaning", "math.derivative.rules"),
    ),
    KnowledgePoint(
        id="math.derivative.tangent_equation",
        name="曲线切线方程",
        description="求曲线在某点（或过某点）处的切线方程",
        default_difficulty=0.55,
        prerequisites=("math.derivative.tangent_slope",),
    ),
    KnowledgePoint(
        id="math.derivative.tangent_relations",
        name="切线的平行与垂直关系",
        description="两切线平行或垂直时反求参数",
        default_difficulty=0.60,
        prerequisites=("math.derivative.tangent_slope",),
    ),
    KnowledgePoint(
        id="math.derivative.tangent_count",
        name="切线条数与公切线",
        description="过一点能作几条切线、两曲线的公切线问题",
        default_difficulty=0.75,
        prerequisites=("math.derivative.tangent_equation",),
    ),
    KnowledgePoint(
        id="math.derivative.tangent_optimization",
        name="切线相关的最值问题",
        description="切线与坐标轴围成图形、切点距离等最值问题",
        default_difficulty=0.80,
        prerequisites=("math.derivative.tangent_equation",),
    ),
    KnowledgePoint(
        id="math.derivative.function_relations",
        name="函数关系式与导数的综合应用",
        description="由函数关系式（含 f(x) 与 f'(x) 的混合式）推导性质",
        default_difficulty=0.70,
        prerequisites=("math.derivative.rules",),
    ),
    KnowledgePoint(
        id="math.function.symmetry_periodicity_derivative",
        name="奇偶性、对称性与周期性中的导数关系",
        description="利用对称性与周期性推导导函数的性质",
        default_difficulty=0.75,
        prerequisites=("math.derivative.rules",),
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


_BY_NAME: dict[str, KnowledgePoint] = {kp.name: kp for kp in _RAW}


def get_point_by_name(name: str) -> KnowledgePoint | None:
    """按知识点名称反查。

    题库的 tags 目前与知识点名称一致，所以当模型没给出知识点、
    但给出了标签时，可以用标签名反推出知识点。
    """
    return _BY_NAME.get(str(name or "").strip())


# ---------------------------------------------------------------------------
# 与 seed/knowledge_points.json 的一致性校验
# ---------------------------------------------------------------------------
#
# 这份清单被三个地方同时依赖：后端代码、题库、前端。任何一边改了另一边没跟上，
# 都会静默出错（题库换代时就吃过这个亏：题库给了 17 个，代码里只有 7 个，
# 46 道题直接挂不上知识点）。所以启动时对一遍。

def seed_file_path() -> Path:
    return Path(__file__).resolve().parent / "seed" / "knowledge_points.json"


def validate_against_seed_file() -> list[str]:
    """比对代码里的清单与 seed/knowledge_points.json。返回差异描述（空 = 一致）。"""
    import json

    path = seed_file_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"读不到或解析不了 {path.name}"]

    entries = payload.get("knowledge_points")
    if not isinstance(entries, list):
        return [f"{path.name} 缺少 knowledge_points 数组"]

    declared = {
        str(item.get("id")): str(item.get("name"))
        for item in entries
        if isinstance(item, dict) and item.get("id")
    }
    code = {kp.id: kp.name for kp in _RAW}

    problems: list[str] = []
    for kp_id, name in code.items():
        if kp_id not in declared:
            problems.append(f"{path.name} 里缺少知识点 {kp_id}")
        elif declared[kp_id] != name:
            problems.append(
                f"{kp_id} 名称不一致：代码={name!r} / {path.name}={declared[kp_id]!r}"
            )
    for kp_id in declared:
        if kp_id not in code:
            problems.append(f"代码里缺少知识点 {kp_id}（{path.name} 里有）")
    return problems
