"""对外 API 契约（Pydantic 模型）。

**前端只依赖这一层。** VLM 用哪个模型、Mastery 怎么算、Prompt 怎么写，
全部隐藏在 Service 层后面。

改这里就等于改契约。Swagger（`/docs`）由这些模型自动生成，
但 **docs/API.md 是手写的详细说明，改字段时请一并更新** ——
那份是给人/agent 直接读的（不必翻代码），Swagger 负责交互式调试。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .errors import ErrorCode

# ---------------------------------------------------------------------------
# 字面量类型（= 契约里的枚举）
# ---------------------------------------------------------------------------

Correctness = Literal["correct", "wrong", "partial", "unanswered", "unknown"]
SourceType = Literal["homework", "tutor", "practice", "exam"]
AnalysisStatus = Literal["queued", "processing", "completed", "failed"]
Trend = Literal["improving", "stable", "declining", "unknown"]
StageState = Literal["done", "active", "retrying", "pending", "failed"]

TutorPhase = Literal[
    "diagnose", "teach", "guided_practice", "independent_practice", "completed"
]
TutorTurnType = Literal[
    "concept_question",
    "hint",
    "explanation",
    "simpler_question",
    "guided_practice",
    "independent_practice",
    "summary",
]
TutorSource = Literal["knowledge_point", "wrong_question", "uploaded_question"]

#: 服务端对「下一步怎么教」的决定。客户端只呈现，不要自己推断。
TutorStrategy = Literal[
    "advance",  # 答对了，进入下一步
    "simplify",  # 答错 → 换更简单的问题（进入/继续补救）
    "hint",  # 同一步再试一次
    "re_explain",  # 连续错且没得再降级，重新讲
    "reveal_answer",  # 补救已到上限 → 揭示答案 + 解析，允许进入下一题
    "finish",  # 结束
]

#: 补救最多 4 层，不存在第 5 层。
MAX_REMEDIAL_DEPTH = 4

NextActionKind = Literal[
    "start_tutor",
    "continue_practice",
    "review_wrong_question",
    "increase_difficulty",
    "next_knowledge_point",
    "review_later",
    "all_good",
]


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """所有接口的统一错误体。

    客户端只根据 `error_code` 做分支，不要解析 `message` 文案。
    可能出现的 error_code 见 app/errors.py。
    """

    error_code: str
    message: str
    request_id: str
    details: dict[str, Any] | None = None


class RejectResponse(BaseModel):
    """占位，避免 OpenAPI 把 ErrorResponse 误当作成功响应。"""

    error_code: str


# ---------------------------------------------------------------------------
# 1. 用户初始化
# ---------------------------------------------------------------------------

class GuestAuthRequest(BaseModel):
    device_id: str | None = Field(default=None, description="设备标识，用于复用已注册的游客")
    display_name: str | None = None


class GuestAuthResponse(BaseModel):
    """匿名用户与访问令牌。之后请求带 `Authorization: Bearer <access_token>`。"""

    user_id: str
    access_token: str
    token_type: str = "Bearer"
    is_demo: bool = False
    created_at: datetime


# ---------------------------------------------------------------------------
# 共享子对象
# ---------------------------------------------------------------------------

class KnowledgePointRef(BaseModel):
    knowledge_point_id: str
    name: str
    weight: float = 1.0


class Choice(BaseModel):
    key: str
    text: str


class NextAction(BaseModel):
    """Agent 决定的下一步行动。

    `action` 取值：
      - `start_tutor`           去学这个薄弱点 → POST /tutor/sessions
      - `continue_practice`     继续刷题巩固   → POST /practice/sessions
      - `review_wrong_question` 重做错题       → 用 wrong_question_id
      - `increase_difficulty`   提高难度       → POST /practice/sessions 并指定更高 difficulty
      - `review_later` / `all_good`  当前没有紧急项
    `cta_label` 是建议的按钮文案，可直接用。
    """

    action: NextActionKind
    title: str
    reason: str
    cta_label: str
    knowledge_point_id: str | None = None
    knowledge_point_name: str | None = None
    wrong_question_id: str | None = None


class KnowledgeChange(BaseModel):
    knowledge_point_id: str
    name: str
    before: float
    after: float
    delta: float
    evidence_count: int


# ---------------------------------------------------------------------------
# 标签系统
# ---------------------------------------------------------------------------

class TagChange(BaseModel):
    """一次答题对相关标签的影响。

    **v2 起标签统计从 Evidence 现算**（Beta 后验 + 悲观下界），
    不再是 ±1 计数器，所以这里给的是「变化后的分数」与「相对作答前的变化量」，
    而不是一个固定的 ±1。

    `correctness=unknown` / `unanswered` 的题不会产生 Evidence，也就不会影响标签。
    """

    question_id: str
    is_correct: bool
    tags: list[str] = Field(default_factory=list)
    tag_scores: dict[str, int] = Field(
        default_factory=dict, description="这些标签**变化后**的分数（0–100）"
    )
    tag_deltas: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "相对本次作答前的分数变化（0–100 单位）。"
            "调用方没提供作答前快照时为空"
        ),
    )


class TagScore(BaseModel):
    """一个标签的统计。

    `score` 是**悲观下界**（后验均值 − 一个标准差）×100，升序 = 最弱在前。
    它同时表达"掌握得怎么样"和"有多确定"：

        2 对 8 错    → 13   最该练
        从没练过     → 21   次之（探索）
        5 对 5 错    → 36   不急
        9 对 1 错    → 73   最后

    ⚠️ 没练过的标签**不是 0**，而是 21 —— 那是先验 Beta(1,1) 的悲观下界。
    0 意味着"确信完全不会"，而我们其实只是"还不知道"。
    """

    tag: str
    score: int
    mastery: float = Field(default=0.0, description="后验均值（0..1）")
    confidence: float = Field(default=0.0, description="对当前估计有多确定（0..1）")
    attempts: int = Field(default=0, description="累计作答次数")


class TagScoresResponse(BaseModel):
    """该用户全部标签的分数，按分数升序（最弱的在前）。"""

    user_id: str
    tag_count: int
    weakest: TagScore | None = None
    strongest: TagScore | None = None
    tags: list[TagScore] = Field(default_factory=list)


class ErrorInfo(BaseModel):
    """统一错误体。

    `error_code` 的类型是 `ErrorCode` 枚举，所以 OpenAPI schema 里会渲染成
    **enum** —— 前端可以直接从 `/openapi.json` 或 `GET /api/v1/meta/error-codes`
    生成映射表，不用手抄文档。
    """

    error_code: ErrorCode
    message: str


class ErrorCodeEntry(BaseModel):
    error_code: ErrorCode
    http_status: int
    description: str


class ErrorCodeCatalogResponse(BaseModel):
    """全部错误码。前端的错误文案映射表可以直接由它生成。"""

    count: int
    codes: list[ErrorCode] = Field(default_factory=list)
    items: list[ErrorCodeEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 2. 首页
# ---------------------------------------------------------------------------

class KnowledgeSummaryNode(BaseModel):
    knowledge_point_id: str
    name: str
    mastery: float
    confidence: float
    evidence_count: int
    trend: Trend
    is_weak: bool


class WrongQuestionAttempt(BaseModel):
    """一次「做错」的明细。

    同一道题多次做错会累积成多条 —— 历史本身有价值，不该被合并掉。
    """

    question_id: str | None = None
    homework_id: str | None = None
    student_answer: str | None = None
    correctness: str | None = None
    created_at: datetime | None = None


class WrongQuestionSummary(BaseModel):
    """**一道当前待复习的规范题目**（不是"某次作业里的某道题"）。

    同一道题在不同作业里做错多次，这里只出现**一条** ——
    列表的语义就是「我现在有哪些题需要复习」。
    每次作答的历史保留在 `attempt_count` / `attempts` 与后端的 Evidence 里。

    `wrong_question_id` 从第一次做错起就固定不变，可以安全地长期引用。
    """

    wrong_question_id: str
    question_id: str
    question_number: str
    question_content: str
    knowledge_point_id: str | None = None
    knowledge_point_name: str | None = None
    error_type: str | None = None
    error_label: str | None = None
    status: str = "open"
    question_stem_hash: str | None = Field(
        default=None,
        description=(
            "规范题目身份。同一道题的多次做错共享同一个值。"
            "客户端**不需要**用它去重（列表已经去过重），"
            "但可以用作本地缓存键。"
        ),
    )
    attempt_count: int = Field(
        default=1, description="这道题累计做错几次，UI 可显示「做错 3 次」"
    )
    first_wrong_at: datetime | None = None
    last_wrong_at: datetime | None = None
    created_at: datetime


class RecentActivityItem(BaseModel):
    activity_type: Literal["homework", "tutor", "practice"]
    title: str
    subtitle: str
    reference_id: str | None = None
    occurred_at: datetime


class HomeStats(BaseModel):
    total_evidence: int
    homework_count: int
    wrong_question_open: int
    tutor_session_count: int
    practice_attempt_count: int
    streak_days: int


class HomeResponse(BaseModel):
    """首页聚合结果 —— 首页只需要请求这一个接口。"""

    user_id: str
    greeting: str
    next_action: NextAction
    knowledge_summary: list[KnowledgeSummaryNode]
    weakest: KnowledgeSummaryNode | None = None
    wrong_question_count: int
    recent_wrong_questions: list[WrongQuestionSummary]
    recent_activities: list[RecentActivityItem]
    stats: HomeStats
    updated_at: datetime


# ---------------------------------------------------------------------------
# 3/4/5. 作业分析与单题结果
# ---------------------------------------------------------------------------

class QuestionResult(BaseModel):
    """单题的识别与判定结果。

    `correctness` 取值与含义：

    | 值 | 含义 | 计入掌握度 |
    |---|---|---|
    | `correct` | 答对 | ✅ |
    | `wrong` | 答错 | ✅ |
    | `partial` | 部分正确 | ✅ |
    | `unanswered` | **学生没作答**（或字迹读不出来） | ❌ |
    | `unknown` | **复核没通过**（两个模型分歧 / 独立求解失败） | ❌ |

    `unanswered` 与 `unknown` 的区别是**对用户的含义不同**：
    前者是「你没做」，后者是「我没算准」。两者都不计分。

    `unknown` 时 `correct_answer` 为 null（服务端拒绝采信未复核的答案），
    但会给出 `possible_answer` 作为**参考**——它绝不参与算分。
    """

    question_id: str
    question_number: str
    question_type: str = "single_choice"
    question_content: str
    choices: dict[str, str] = Field(default_factory=dict)
    student_answer: str | None = None
    correct_answer: str | None = None
    correctness: Correctness = "unknown"
    possible_answer: str | None = Field(
        default=None,
        description=(
            "仅当 correctness=unknown 时有值：复核没通过时保留的「可能答案」，"
            "**仅供参考，不计入掌握度**。优先取独立求解模型的答案"
            "（它没参与识别，不受视觉误读影响）。"
        ),
    )
    possible_answer_source: str | None = Field(
        default=None, description="可能答案来自哪个模型，用于排查"
    )
    knowledge_points: list[KnowledgePointRef] = Field(default_factory=list)
    error_type: str | None = None
    error_label: str | None = None
    diagnosis: str = ""
    explanation: str | None = None
    confidence: float = 0.0
    difficulty: float = 0.5
    image_url: str | None = None


class AnalysisStage(BaseModel):
    key: str
    label: str
    label_zh: str | None = None
    state: StageState


class AnalysisProgress(BaseModel):
    """分析进度，用于「可持续追踪的进度卡片」。

    `stages` 是固定 5 段，每段带 `state`，直接渲染成勾选列表即可；
    `percent` 可驱动进度条。实测整条流水线约 20–30 秒，建议 1 秒轮询一次。

    **`state` 有 5 种，不是 4 种**：

    | state | 含义 |
    |---|---|
    | `done` | 这一步已完成 |
    | `active` | 正在做这一步 |
    | `retrying` | 正在做，但当前模型没成功、**正在换模型重试**（不是失败！） |
    | `pending` | 还没轮到 |
    | `failed` | 这一步失败了（此时 `failed` 优先于 `retrying`） |

    > ⚠️ `retrying` 必须当成"进行中"渲染。把它当成 `failed`，学生就会在
    > 模型降级的那几十秒里看到"分析失败"，而其实任务还在正常推进。

    模型降级时 `retrying` 为 true，`retry_note` 给出可直接显示的中文说明。
    **识别期间 `retry_note` 一直都有**（即使还在用第一个模型），例如
    「第 1 张：正在用 Qwen/Qwen3-VL-32B-Instruct 识别（模型 1/3）」——
    一页大试卷识别要几分钟，没有这句话进度卡片会看起来卡死。
    `retrying` 只在**真的换过模型**之后才为 true。
    """

    percent: float
    current_stage: str
    current_stage_key: str | None = None
    current_stage_label_zh: str | None = None
    stages: list[AnalysisStage]
    retrying: bool = Field(
        default=False,
        description="是否正在换模型重试（true 时按「进行中」渲染，不要当成失败）",
    )
    retry_note: str | None = Field(
        default=None,
        description=(
            "可直接显示的中文说明。**识别期间一直有**，不只是重试时 —— "
            "例如「正在用 Qwen3-VL-32B 识别（模型 1/3）」。"
        ),
    )


class ConfirmAnswerRequest(BaseModel):
    """人工确认/纠正一道题的标准答案。

    模型读错答案、或者它自己也不确定被复核判成 `unknown` 时，
    学生对着答案册给的答案是最可靠的信号源。

    前端**只提交标准答案** —— `correctness`、Evidence、掌握度、错题
    全部由服务端算，客户端不参与判定。
    """

    correct_answer: str = Field(
        ...,
        min_length=1,
        max_length=1,
        description="单选题的正确选项，A/B/C/D 之一（暂不支持多选）",
        examples=["C"],
    )
    client_request_id: str | None = Field(
        default=None,
        description=(
            "客户端生成的 UUID。没带 `Idempotency-Key` 请求头时用它当幂等键。"
            "手机网络不稳时重试不会重复写 Evidence。"
        ),
    )


class AnswerConfirmation(BaseModel):
    """这次确认的来源与痕迹。

    `original_correct_answer` 是 **AI 原来的说法**（`unknown` 的题则取自
    `possible_answer` 的猜测），留着是为了让模型的问题可被追溯 ——
    这个接口本身就是"报错接口"，只看到"结果变了"是查不出模型哪里错的。
    """

    source: Literal["user"] = "user"
    confirmed_at: str | None = None
    original_correct_answer: str | None = None
    correction_count: int = 0


class AnalysisSummaryCounts(BaseModel):
    """确认之后**重算过**的对错统计。"""

    question_count: int
    correct_count: int
    wrong_count: int
    partial_count: int
    unanswered_count: int
    unknown_count: int


class ConfirmAnswerResponse(BaseModel):
    """确认标准答案的结果。

    这个接口会**在本地重跑这道题的下游流程（不调 AI）**：
    旧 Evidence 作废 → 按新判定重写 → 掌握度 / 标签 / 错题 / counts 全部更新。
    所以响应里带回更新后的统计与错题项。
    """

    analysis_id: str
    question_id: str
    student_answer: str | None = None
    correct_answer: str | None = None
    correctness: Correctness = "unknown"
    confirmation: AnswerConfirmation
    analysis_summary: AnalysisSummaryCounts
    wrong_question: dict[str, Any] | None = Field(
        default=None,
        description=(
            "这道题**当前**的待复习项（`status: open`）。"
            "判对、或已被收掉时为 null —— 也就是「这道题现在不用复习了」。"
        ),
    )
    next_action: dict[str, Any] | None = None
    replayed: bool = Field(
        default=False,
        description="同一个答案重复提交时为 true，此时**没有**重复写 Evidence",
    )


class AnalysisCreateResponse(BaseModel):
    analysis_id: str
    # 该用户内递增的上传批次号（第几批），前端可用它显示「第 7 批」
    batch_number: int | None = None
    status: AnalysisStatus
    created_at: datetime


class AnalysisDetailResponse(BaseModel):
    analysis_id: str
    # 该用户内递增的上传批次号（第几批），展示与排序用；稳定标识仍是 analysis_id
    batch_number: int | None = None
    status: AnalysisStatus
    progress: AnalysisProgress
    homework_id: str | None = None
    user_id: str
    subject: str = "mathematics"
    topic: str | None = None
    source_name: str | None = None
    book_id: str | None = None
    image_count: int = 0

    # `questions` 是题目 id 列表；`question_results` 是完整的单题结果对象。
    questions: list[str] = Field(default_factory=list)
    question_results: list[QuestionResult] = Field(default_factory=list)

    correct_count: int = 0
    wrong_count: int = 0
    partial_count: int = 0
    #: 学生没作答的题数。**不计入掌握度**，但要能单独提示"这题你没做"。
    unanswered_count: int = 0
    #: 复核没通过的题数（判定不可信）。同样不计入掌握度。
    unknown_count: int = 0

    knowledge_changes: list[KnowledgeChange] = Field(default_factory=list)
    new_wrong_questions: list[WrongQuestionSummary] = Field(default_factory=list)
    next_action: NextAction | None = None
    error: ErrorInfo | None = None
    warnings: list[str] = Field(default_factory=list)
    generated_by: str | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


# ---------------------------------------------------------------------------
# 上传批次列表（前端的「近 50 批」）
# ---------------------------------------------------------------------------

# 内部状态对外归一到三态：正在 / 成功 / 失败
BatchState = Literal["processing", "success", "failed"]


class BatchSummary(BaseModel):
    """一批上传的摘要。

    - `state="processing"`：带 `progress`（与详情接口完全一样的结构）
    - `state="success"`：带 `finished_at` / `duration_seconds` 与题目统计
    - `state="failed"`：带 `finished_at` / `duration_seconds` 与 `error`
    """

    batch_number: int | None = None
    analysis_id: str
    state: BatchState
    state_label: str
    status: AnalysisStatus | None = None
    image_count: int = 0
    source_name: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None
    progress: AnalysisProgress | None = None
    duration_seconds: float | None = None
    question_count: int | None = None
    correct_count: int | None = None
    wrong_count: int | None = None
    error: ErrorInfo | None = None


class BatchListResponse(BaseModel):
    """最近的上传批次，最新的在前。"""

    total: int
    processing_count: int
    success_count: int
    failed_count: int
    limit: int
    items: list[BatchSummary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 6/7. Knowledge State
# ---------------------------------------------------------------------------

class KnowledgeNode(BaseModel):
    """知识树的一个节点。父节点的 mastery 由子节点按证据量加权聚合而来，不是独立存的数字。"""

    knowledge_point_id: str
    name: str
    description: str = ""
    mastery: float
    confidence: float
    evidence_count: int
    trend: Trend
    children: list["KnowledgeNode"] = Field(default_factory=list)


KnowledgeNode.model_rebuild()


class WeakPoint(BaseModel):
    knowledge_point_id: str
    name: str
    mastery: float
    confidence: float
    priority: float
    reason: str


class KnowledgeResponse(BaseModel):
    user_id: str
    subject: str = "mathematics"
    updated_at: datetime
    tree: list[KnowledgeNode]
    weakest: list[WeakPoint]
    next_action: NextAction | None = None
    total_evidence: int


class WeakestPointRef(BaseModel):
    knowledge_point_id: str
    name: str
    mastery: float


class MasteryOverviewResponse(BaseModel):
    """综合掌握度 —— 一个给首页用的大数字。

    `score` 是两位整数百分比（0–99），**直接显示即可**，不用再换算。
    """

    score: int = Field(
        ge=0, le=99, description="两位数百分比，直接显示"
    )
    percent: float = Field(
        description="精确值（0..1），需要更细的展示时用"
    )
    weighted_mastery: float = Field(
        description="已练知识点的置信度加权平均掌握度，未折算覆盖率"
    )
    coverage: float = Field(description="已练知识点占全部的比例")
    covered_count: int = Field(description="有证据的知识点数")
    point_count: int = Field(description="知识点总数（= 标签总数）")
    evidence_count: int = Field(description="参与统计的证据条数")
    weakest: list[WeakestPointRef] = Field(
        default_factory=list, description="掌握度最低的 3 个，可直接做「该练什么」"
    )


class EvidenceItem(BaseModel):
    """一条学习证据。

    `result` 取值：`correct` | `partial` | `incorrect` | `unknown`。
    这是 Knowledge State 的唯一事实来源 —— 每个百分比都能反查到撑起它的证据。
    """

    evidence_id: str
    knowledge_point_id: str
    source_type: SourceType
    source_id: str | None = None
    question_id: str | None = None
    #: 题干内容指纹。题库重新生成后 question_id 可能指向别的题，
    #: 靠它才能确认「这几次作答是同一道题」。
    question_stem_hash: str | None = None
    result: str
    confidence: float
    error_type: str | None = None
    error_label: str | None = None
    answer_excerpt: str | None = None
    detail: str | None = None
    created_at: datetime


class ErrorPatternOut(BaseModel):
    error_type: str
    label: str
    count: int
    share: float


class RecentPerformancePoint(BaseModel):
    occurred_at: datetime
    result: str
    source_type: str
    question_id: str | None = None


class KnowledgeDetailResponse(BaseModel):
    """Knowledge Detail 页面的全部数据。

    `mastery_explanation` 是给用户看的一句话解释（「为什么是 43%」），
    直接展示即可；`error_patterns` + `evidence` 支撑可点击的「查看证据」。
    """

    knowledge_point_id: str
    name: str
    description: str
    subject: str = "mathematics"
    mastery: float
    confidence: float
    trend: Trend
    evidence_count: int
    correct_count: int
    partial_count: int
    wrong_count: int
    recent_performance: list[RecentPerformancePoint]
    error_patterns: list[ErrorPatternOut]
    evidence: list[EvidenceItem]
    prerequisites: list[KnowledgePointRef]
    mastery_explanation: str
    recommended_action: NextAction | None = None
    updated_at: datetime


# ---------------------------------------------------------------------------
# 8/9/10. 错题库
# ---------------------------------------------------------------------------

class WrongQuestionDetail(BaseModel):
    """错题详情。`can_start_tutor` 对应详情页的 Start Learning 按钮。

    `attempts` 是这道题的**逐次作答明细**（最早的在前，最多 20 条）——
    想展示「这道题我错过哪几次」就用它。更早的记录仍可在后端
    Evidence 里查到，只是不再随详情下发。
    """

    wrong_question_id: str
    question_id: str
    question_number: str
    question_type: str = "single_choice"
    question_content: str
    choices: dict[str, str] = Field(default_factory=dict)
    student_answer: str | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    correctness: Correctness = "wrong"
    knowledge_point_id: str | None = None
    knowledge_point_name: str | None = None
    error_type: str | None = None
    error_label: str | None = None
    diagnosis: str = ""
    image_url: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    source_name: str | None = None
    status: str = "open"
    favorite: bool = False
    question_stem_hash: str | None = None
    attempt_count: int = 1
    first_wrong_at: datetime | None = None
    last_wrong_at: datetime | None = None
    attempts: list[WrongQuestionAttempt] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    can_start_tutor: bool = True


class WrongQuestionListResponse(BaseModel):
    user_id: str
    total: int
    items: list[WrongQuestionSummary]


class WrongQuestionPatchRequest(BaseModel):
    status: Literal["open", "resolved", "archived"] | None = None
    favorite: bool | None = None


# ---------------------------------------------------------------------------
# 11/12/13. AI Tutor
# ---------------------------------------------------------------------------

class TutorSessionCreateRequest(BaseModel):
    source_type: TutorSource = "knowledge_point"
    knowledge_point_id: str | None = Field(
        default=None, description="source_type=knowledge_point 时必填"
    )
    wrong_question_id: str | None = Field(
        default=None, description="source_type=wrong_question 时必填"
    )
    question_text: str | None = Field(
        default=None, description="source_type=uploaded_question 时的题干文本"
    )
    image_base64: str | None = Field(
        default=None, description="source_type=uploaded_question 时的题目图片"
    )
    mime_type: str = "image/jpeg"
    difficulty: float | None = None
    # 幂等：也可以直接用 Idempotency-Key 请求头
    client_request_id: str | None = None


class TutorProgress(BaseModel):
    step: int
    total_steps: int
    percent: float


class TutorRevealedAnswer(BaseModel):
    """一道题的答案与解析。"""

    question_id: str | None = None
    question_text: str | None = None
    correct_key: str
    explanation: str | None = None


class TutorAnswerReveal(BaseModel):
    """揭示答案。

    **补救进行中 `TutorTurn.answer_reveal` 恒为 `null`** —— 绝不提前泄漏
    正式题的正确答案。它只在两种时刻出现：

      1. 学生**答对**了当前这道题（`current` = 这道题的答案与解析）
      2. 补救到达第 4 层仍答错（`current` = 最后一道补救题，
         `origin` = 触发补救的那道正式题）
    """

    current: TutorRevealedAnswer | None = None
    origin: TutorRevealedAnswer | None = None


class TutorTurn(BaseModel):
    """Tutor 的一轮输出。按 `turn_type` 选择渲染方式，不要把 `text` 当成整段 Markdown。

      - `concept_question`      概念选择题（配 choices）
      - `simpler_question`      学生答错后换的更简单的问题（补救中，见 `remedial_depth`）
      - `hint`                  提示条，同一题再试
      - `explanation`           讲解卡片，`allow_free_text=false`，**不需要作答**
      - `guided_practice`       分步引导
      - `independent_practice`  独立练习（没有提示，产生的 Evidence 才算数）
      - `remedial_exhausted`    补救 4 层仍错，已揭示答案，可进入下一题
      - `summary`               总结卡片，此时 session 已 completed

    `remedial_depth`：0 表示不在补救中；1–4 表示当前是第几层补救题。
    `answer_reveal`：见 `TutorAnswerReveal`，补救进行中恒为 `null`。
    """

    turn_id: str
    seq: int
    turn_type: TutorTurnType
    text: str
    choices: list[Choice] = Field(default_factory=list)
    allow_free_text: bool = True
    phase: TutorPhase
    progress: TutorProgress
    completed: bool = False
    question_id: str | None = None
    strategy: TutorStrategy | None = Field(
        default=None, description="产生这一轮的教学策略，由服务端决定"
    )
    remedial_depth: int = Field(
        default=0, ge=0, le=MAX_REMEDIAL_DEPTH, description="0=不在补救；1..4=第几层"
    )
    remedial_exhausted: bool = Field(
        default=False,
        description=(
            "补救已到上限，这一轮给出了答案揭示（`answer_reveal` 非 null）。"
            "**不要用它决定渲染什么** —— `turn_type` 才是内容的类型："
            "补救耗尽时会话已经推进，所以这一轮很可能同时带着下一题，"
            "甚至已经走完（`turn_type: summary`）。"
            "正确做法是：照 `turn_type` 渲染主内容，"
            "再按 `answer_reveal` 额外叠一张解析卡。"
        ),
    )
    answer_reveal: TutorAnswerReveal | None = None
    created_at: datetime


class TutorEvaluation(BaseModel):
    """对学生这次作答的判定，以及服务端因此选择的策略。

    `strategy` 取值见 `TutorStrategy`。
    """

    correctness: Correctness
    is_correct: bool
    chosen_key: str | None = None
    expected_key: str | None = None
    feedback: str
    explanation: str | None = None
    strategy: TutorStrategy
    remedial_depth: int = Field(
        default=0, ge=0, le=MAX_REMEDIAL_DEPTH, description="作答后所处的补救层级"
    )
    remedial_exhausted: bool = Field(
        default=False, description="补救是否已到上限（此时已揭示答案）"
    )


class TutorSessionResponse(BaseModel):
    tutor_session_id: str
    user_id: str
    source_type: TutorSource
    source_id: str | None = None
    knowledge_point_id: str | None = None
    knowledge_point_name: str | None = None
    phase: TutorPhase
    difficulty: float
    attempt_count: int
    hint_count: int
    student_understanding: float
    completed: bool
    turn: TutorTurn | None = None
    history: list[TutorTurn] = Field(default_factory=list)
    knowledge_changes: list[KnowledgeChange] = Field(default_factory=list)
    next_action: NextAction | None = None
    created_at: datetime
    updated_at: datetime


class TutorAnswerRequest(BaseModel):
    selected_key: str | None = Field(default=None, description="选择题作答，例如 'B'")
    text: str | None = Field(default=None, description="自由输入作答")
    self_reported_confidence: Literal["sure", "guess", "unsure"] | None = None
    client_request_id: str | None = None
    answering_turn_id: str | None = Field(
        default=None,
        description=(
            "**强烈建议传**：你正在回答的那一轮的 `turn.turn_id`。"
            "服务端据此识别重复提交（网络重试 / 手抖连点）并原样回放，"
            "不再推进教学流程、不再重复写 Evidence。不传则没有这层保护。"
        ),
    )
    stream: bool = Field(
        default=False,
        description=(
            "true → 返回 SSE（text/event-stream）；"
            "false/缺省 → 维持原有 JSON 契约"
        ),
    )


class TutorTurnResponse(BaseModel):
    tutor_session_id: str
    evaluation: TutorEvaluation | None = None
    turn: TutorTurn
    phase: TutorPhase
    completed: bool
    progress: TutorProgress
    student_understanding: float
    knowledge_changes: list[KnowledgeChange] = Field(default_factory=list)
    next_action: NextAction | None = None
    replayed: bool = Field(
        default=False,
        description=(
            "true = 这一轮之前已经答过（重复提交被识别），返回的是当时的原样结果，"
            "教学流程没有推进、也没有重复写 Evidence"
        ),
    )


# ---------------------------------------------------------------------------
# 14. Practice
# ---------------------------------------------------------------------------

class PracticeSessionCreateRequest(BaseModel):
    """创建练习。

    **不填 `knowledge_point_id` 时走标签推荐**：服务端把所有标签按分数
    从小到大排序，返回包含分数最低那个标签的题目。

    幂等：可以带 `Idempotency-Key` 请求头，或在这里填 `client_request_id`。
    """

    knowledge_point_id: str | None = None
    difficulty: float | None = Field(default=None, ge=0.0, le=1.0)
    book_id: str | None = None
    count: int = Field(default=5, ge=1, le=20)
    client_request_id: str | None = None


class PracticeQuestion(BaseModel):
    """下发给客户端的题目——**绝不包含 answer / explanation**。"""

    question_id: str
    question_number: str
    stem: str
    choices: list[Choice]
    difficulty: float
    knowledge_points: list[KnowledgePointRef] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    index: int
    total: int


class TagRecommendation(BaseModel):
    """按标签推荐出来的一道题。

    `tag` 是被选中的那个「分数最低的标签」，`question` 是包含它的题目。
    """

    tag: str
    tag_score: int
    question_id: str
    question_tags: list[str] = Field(default_factory=list)
    question: PracticeQuestion | None = None


class TagRecommendResponse(BaseModel):
    user_id: str
    weakest: TagScore | None = None
    recommendations: list[TagRecommendation] = Field(default_factory=list)


class PracticeSessionResponse(BaseModel):
    practice_session_id: str
    user_id: str
    knowledge_point_id: str | None = None
    knowledge_point_name: str | None = None
    status: Literal["active", "completed", "abandoned"]
    total: int
    answered: int
    correct: int
    next_question: PracticeQuestion | None = None
    # ---- 标签推荐（selection_mode="tag" 时）----
    selection_mode: Literal["tag", "knowledge_point"] = "knowledge_point"
    target_tag: str | None = None
    target_tag_score: int | None = None
    picked_tags: list[str] = Field(default_factory=list)
    created_at: datetime


class PracticeAnswerRequest(BaseModel):
    """练习作答。

    题库全是单选题，所以只接受选项字母。**没有自由文本作答** ——
    以前这里有个 `answer_text` 字段，但它从签名一路传到 service 之后
    被**静默丢弃**：客户端可以传，服务端收下什么也不做。
    契约里留一个什么都不做的字段比没有更糟（前端会以为它生效了），
    所以直接删掉。需要自由文本作答的是 Tutor，见 §5。
    """

    question_id: str
    selected_key: str | None = None
    client_request_id: str | None = None


class PracticeAnswerResponse(BaseModel):
    """练习作答的判定结果。

    注意 `explanation` 可能为 null —— 官方题库规范里没有解析字段，
    只有 OCR 上传的题目才会带解析。
    """

    practice_session_id: str
    question_id: str
    correctness: Correctness
    is_correct: bool
    correct_answer: str
    explanation: str | None = None
    knowledge_changes: list[KnowledgeChange] = Field(default_factory=list)
    tag_changes: TagChange | None = None
    # 同一题重复提交（网络重试）时服务端回放上次结果，不重复计分
    replayed: bool = False
    next_question: PracticeQuestion | None = None
    session_completed: bool = False
    answered: int = 0
    correct: int = 0
    total: int = 0
    next_action: NextAction | None = None


# ---------------------------------------------------------------------------
# 15/16. Book / Entitlement
# ---------------------------------------------------------------------------

class BookSummary(BaseModel):
    book_id: str
    title: str
    publisher: str
    cover_url: str | None = None
    price_cents: int = 0
    question_count: int = 0
    owned: bool = False


class BookDetail(BookSummary):
    description: str = ""
    subject: str = "mathematics"
    bank_ids: list[str] = Field(default_factory=list)
    knowledge_point_ids: list[str] = Field(default_factory=list)


class BookListResponse(BaseModel):
    total: int
    items: list[BookSummary]


class RedeemRequest(BaseModel):
    serial_number: str


class RedeemResponse(BaseModel):
    book_id: str
    entitled: bool
    entitlement_id: str | None = None
    message: str


class SubscriptionInfo(BaseModel):
    status: Literal["none", "active", "trial"] = "none"
    plan_name: str | None = None
    price_cents: int = 0
    renews_at: datetime | None = None


class EntitlementsResponse(BaseModel):
    user_id: str
    owned_books: list[BookSummary]
    owned_book_ids: list[str]
    subscription_status: str = "none"
    subscription: SubscriptionInfo


# ---------------------------------------------------------------------------
# 标准 AI 直连接口（前端"跟踪训练"用）
# ---------------------------------------------------------------------------

class AiChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class AiChatRequest(BaseModel):
    """最简用法：只填 prompt。多轮时填 messages。"""

    prompt: str | None = Field(default=None, description="单轮直接提问，最简单的用法")
    messages: list[AiChatMessage] | None = Field(
        default=None, description="多轮对话；与 prompt 二选一，同时存在时 messages 优先"
    )
    system: str | None = Field(default=None, description="系统提示词")
    temperature: float = Field(default=0.6, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=1024, ge=1, le=8192)
    model: str | None = Field(default=None, description="不填则用服务端默认模型")
    json_mode: bool = Field(default=False, description="要求模型输出 JSON 对象")
    stream: bool = Field(
        default=False,
        description="true 时改返回 SSE 流（text/event-stream）；不填则维持一次性 JSON 响应",
    )


class AiChatResponse(BaseModel):
    """标准 AI 直连的回答。`provider` 为 `mock` 说明未连上真实模型（回复是兜底文案）。"""

    reply: str
    model: str
    provider: str
    latency_ms: int
    request_id: str
    usage: dict[str, Any] | None = None


class AiModelInfo(BaseModel):
    id: str
    label: str
    kind: Literal["text", "vision"]
    is_default: bool = False


class AiModelsResponse(BaseModel):
    default_model: str
    default_vision_model: str
    models: list[AiModelInfo]


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    llm_mode: Literal["live", "mock"]
    llm_model: str
    vlm_model: str
    database: str
    bank_count: int
    question_count: int
    uptime_seconds: float
    #: 备用 provider（另一个厂商）。主厂商整体挂掉时靠它顶上，
    #: 同时用作二次求解校验的模型。
    backup_llm_model: str = ""
    backup_llm_configured: bool = False
