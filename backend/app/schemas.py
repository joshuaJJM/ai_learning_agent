"""对外 API 契约（Pydantic 模型）。

**前端只依赖这一层。** VLM 用哪个模型、Mastery 怎么算、Prompt 怎么写，
全部隐藏在 Service 层后面。改这里等于改契约，请同步更新 docs/API.md。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 字面量类型（= 契约里的枚举）
# ---------------------------------------------------------------------------

Correctness = Literal["correct", "wrong", "partial", "unknown"]
SourceType = Literal["homework", "tutor", "practice", "exam"]
AnalysisStatus = Literal["queued", "processing", "completed", "failed"]
Trend = Literal["improving", "stable", "declining", "unknown"]
StageState = Literal["done", "active", "pending"]

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


class ErrorInfo(BaseModel):
    error_code: str
    message: str


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
    percent: float
    current_stage: str
    current_stage_key: str | None = None
    current_stage_label_zh: str | None = None
    stages: list[AnalysisStage]


class AnalysisCreateResponse(BaseModel):
    analysis_id: str
    status: AnalysisStatus
    created_at: datetime


class AnalysisDetailResponse(BaseModel):
    analysis_id: str
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


# ---------------------------------------------------------------------------
# 6/7. Knowledge State
# ---------------------------------------------------------------------------

class KnowledgeNode(BaseModel):
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
    evidence_id: str
    knowledge_point_id: str
    source_type: SourceType
    source_id: str | None = None
    question_id: str | None = None
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


class TutorProgress(BaseModel):
    step: int
    total_steps: int
    percent: float


class TutorTurn(BaseModel):
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
    knowledge_point_id: str | None = None
    difficulty: float | None = Field(default=None, ge=0.0, le=1.0)
    book_id: str | None = None
    count: int = Field(default=5, ge=1, le=20)


class PracticeQuestion(BaseModel):
    """下发给客户端的题目——**绝不包含 answer / explanation**。"""

    question_id: str
    question_number: str
    stem: str
    choices: list[Choice]
    difficulty: float
    knowledge_points: list[KnowledgePointRef] = Field(default_factory=list)
    index: int
    total: int


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
    created_at: datetime


class PracticeAnswerRequest(BaseModel):
    question_id: str
    selected_key: str | None = None
    answer_text: str | None = None
    client_request_id: str | None = None


class PracticeAnswerResponse(BaseModel):
    practice_session_id: str
    question_id: str
    correctness: Correctness
    is_correct: bool
    correct_answer: str
    explanation: str
    knowledge_changes: list[KnowledgeChange] = Field(default_factory=list)
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


class AiChatResponse(BaseModel):
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
