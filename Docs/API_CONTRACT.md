# 好学 — API CONTRACT

> 本文件定义 **前端依赖的语义边界**，不是最终 JSON Schema。
> 后端同学拥有具体 endpoint 路径、字段命名和 JSON 结构的最终决定权；确定后再同步更新本文件。

## 1. 原则

1. Backend 为 Source of Truth；
2. iOS 不直接依赖具体 LLM / VLM Provider；
3. iOS 不自己计算掌握度；
4. AI 输出尽量结构化；
5. Tutor 不返回纯 Markdown 大字符串作为唯一数据；
6. 所有可变字段应有稳定类型和明确 fallback。

---

## 2. Frontend 需要的核心能力

### A. Home Summary

前端需要一次请求获得：

- Next Step；
- Subject Summary；
- Knowledge Summary；
- Recent Wrong Questions；
- Recent Learning Changes。

### B. Unified Image Upload

前端统一上传一组图片。

请求语义：

```text
images[]
```

前端不声明“这是作业”还是“这是不会做的题”。

后端负责内容理解并返回：

- upload / analysis ID；
- 状态；
- 当前分析阶段；
- 最终结果类型；
- 题目结果；
- Knowledge Changes；
- 后续建议。

### C. Analysis Status

需要支持异步查询：

```text
queued
processing
completed
failed
```

前端可以展示：

- 图片已上传；
- 正在检测题目；
- 正在分析作答；
- 正在更新知识状态。

### D. Knowledge State

前端需要：

- 知识树 / 列表；
- 当前 mastery；
- trend；
- evidence summary；
- recommended action。

### E. Wrong Question

至少需要：

- id；
- title / question content；
- source；
- student answer；
- correct answer；
- knowledge points；
- diagnosis；
- timestamp。

### F. Tutor Session

创建 Session 时来源可能是：

- knowledge point；
- wrong question；
- uploaded question；
- next-step recommendation。

Tutor Turn 至少需要：

- turn type；
- main text；
- A-D choices；
- phase；
- progress；
- completed；
- optional knowledge change。

Phase 3B 已确认的 iOS 依赖（以 backend OpenAPI / `docs/API.md` 为准）：

- `POST /api/v1/tutor/sessions` 创建会话，`GET /api/v1/tutor/sessions/{id}` 恢复状态；
- `POST /api/v1/tutor/sessions/{id}/turns` 传 `selected_key` 或 `text`，`stream: true` 时返回 SSE；
- Tutor Session 是唯一教学状态权威，iOS 不调用 `/api/v1/ai/chat` 另建补救流程；
- SSE 顺序是 `meta → delta* → turn → done`，`error` 仅用于开流后的错误；HTTP 非 2xx 是普通 JSON 错误体；
- `delta.content` 仅作打字机展示，题目、选项、策略、`remedial_depth`、`answer_reveal` 均以 `turn` 为准；
- 补救层级由服务端决定，最多 4 层，题库不足时可提前返回 `remedial_exhausted`；
- 补救中 `answer_reveal` 为 `null`；结束时才显示服务端给出的正确答案和解析；
- 进度使用服务端值，题目 ID 当作不透明字符串；
- 后端目前会返回 `knowledge_changes`，但按当前开发安排，iOS 的 mastery 展示暂不接入，不能用 `difficulty` 代替；
- SSE 的 `turn` / `done` 事件未包含完整 `evaluation` 与 `knowledge_changes`，iOS 在流结束后用同一个幂等键请求 JSON 回放，取得完整结果而不重复计分；掌握度显示仍待后端后续开发确认。

### G. Practice

前端需要：

- 题目；
- A-D 选项；
- 当前进度；
- 提交答案结果；
- explanation；
- mastery change；
- next action。

---

## 3. 建议的前端模型

最终字段以 Backend JSON 为准，但 Swift 端建议保持这些业务模型：

```text
HomeState
SubjectSummary
KnowledgePoint
KnowledgeChange
WrongQuestion
UploadAnalysis
QuestionResult
TutorSession
TutorTurn
TutorChoice
PracticeSession
PracticeQuestion
```

用 DTO → Domain Model 转换，避免后端字段改名直接污染 View。

---

## 4. Error Contract

后端统一返回机器可读错误码，例如：

```text
INVALID_IMAGE
ANALYSIS_FAILED
VLM_TIMEOUT
QUESTION_NOT_RECOGNIZED
SESSION_NOT_FOUND
SESSION_COMPLETED
IDEMPOTENCY_CONFLICT
INTERNAL_ERROR
```

前端不应通过匹配中文错误文案来判断逻辑。

---

## 5. Retry / Idempotency

Tutor 的创建会话和提交作答使用稳定的 `Idempotency-Key` / `client_request_id`。
同一次逻辑提交的流式请求、JSON 回放和失败重试必须复用同一个键；
`IDEMPOTENCY_CONFLICT` 等待一秒后原键重试。

原因：

```text
请求其实成功
↓
客户端超时
↓
Retry
↓
Evidence 被重复写入
```

比赛阶段如果来不及实现，至少需要确保关键提交不会轻易重复执行。
