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

当前 Hackathon Demo：

- A-D 会真实上送；
- “写下你的想法……”只保留 UI，不要求上送；
- 自由输入可以暂时传 `none` / 不触发网络请求。

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

后端最好统一返回机器可读错误码，例如：

```text
INVALID_IMAGE
ANALYSIS_FAILED
VLM_TIMEOUT
QUESTION_NOT_RECOGNIZED
SESSION_EXPIRED
SERVER_ERROR
```

前端不应通过匹配中文错误文案来判断逻辑。

---

## 5. Retry / Idempotency

会改变数据的请求最好支持 client request id 或 idempotency key。

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
