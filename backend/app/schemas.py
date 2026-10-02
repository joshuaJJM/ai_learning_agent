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

Correctness = Literal["correct", "wrong", "partial", "unknown"]
SourceType = Literal["homework", "tutor", "practice", "exam"]
AnalysisStatus = Literal["queued", "processing", "completed", "failed"]
Trend = Literal["improving", "stable", "declining", "unknown"]
StageState = Literal["done", "active", "pending", "failed"]

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
    """一次答题导致的标签分数变动。

    规则：答对 → 该题所有标签 +1；答错 → -1。
    `correctness=unknown`（两个模型对答案有分歧）时不改动标签。
    """

    question_id: str
    is_correct: bool
    delta: int
    tags: list[str] = Field(default_factory=list)


class TagScore(BaseModel):
    tag: str
    score: int


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


class WrongQuestionSummary(BaseModel):
    wrong_question_id: str
    question_id: str
    question_number: str
    question_content: str
    knowledge_point_id: str | None = None
    knowledge_point_name: str | None = None
    error_type: str | None = None
    error_label: str | None = None
    status: str = "open"
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

    注意 `correctness == "unknown"` 时 `correct_answer` 为 null：
    这说明两个模型对答案有分歧，服务端拒绝采信，该题也未计入掌握度统计。
    详见 warnings。
    """

    question_id: str
    question_number: str
    question_type: str = "single_choice"
    question_content: str
    choices: dict[str, str] = Field(default_factory=dict)
    student_answer: str | None = None
    correct_answer: str | None = None
    correctness: Correctness = "unknown"
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

    `stages` 是固定 5 段，每段带 `state`（done / active / pending / failed），
    直接渲染成勾选列表即可；`percent` 可驱动进度条。
    分析失败时，出错的那一步是 `failed` 而不是 `active`。
    实测整条流水线约 20–30 秒，建议 1 秒轮询一次。
    """

    percent: float
    current_stage: str
    current_stage_key: str | None = None
    current_stage_label_zh: str | None = None
    stages: list[AnalysisStage]


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
    """错题详情。`can_start_tutor` 对应详情页的 Start Learning 按钮。"""

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


class TutorTurn(BaseModel):
    """Tutor 的一轮输出。按 `turn_type` 选择渲染方式，不要把 `text` 当成整段 Markdown。

      - `concept_question`      概念选择题（配 choices）
      - `simpler_question`      学生答错后换的更简单的问题
      - `hint`                  提示条，同一题再试
      - `explanation`           讲解卡片，`allow_free_text=false`，**不需要作答**
      - `guided_practice`       分步引导
      - `independent_practice`  独立练习（没有提示，产生的 Evidence 才算数）
      - `summary`               总结卡片，此时 session 已 completed
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
    created_at: datetime


class TutorEvaluation(BaseModel):
    """对学生这次作答的判定，以及 Agent 因此选择的策略。

    `strategy` 取值：
      - `advance`     答对了，进入下一步
      - `simplify`    **答错 → 换成更简单的问题**（Agent 改变教学策略）
      - `hint`        同一步再试一次，给提示
      - `re_explain`  连续错，重新讲
      - `finish`      结束
    """

    correctness: Correctness
    is_correct: bool
    chosen_key: str | None = None
    expected_key: str | None = None
    feedback: str
    explanation: str | None = None
    strategy: Literal["advance", "simplify", "re_explain", "hint", "finish"]


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
    question_id: str
    selected_key: str | None = None
    answer_text: str | None = None
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
