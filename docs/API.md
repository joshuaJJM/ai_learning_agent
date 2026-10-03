# 好学 Backend API Contract v1.0

> 后端是整个系统的 **Source of Truth**。iOS **不自行计算掌握度**——`43% → 51%` 这个变化
> 只能由服务器算出来并返回，客户端只负责动画展示。
>
> 本文档与 `backend/app/schemas.py` 一一对应。改 schema 必须同步改这里。

---

## 0. 基本信息

| 项 | 值 |
|---|---|
| Base URL | `http://121.43.137.176:17283` |
| API 前缀 | `/api/v1` |
| 交互式文档 | `http://121.43.137.176:17283/docs`（Swagger，可直接点着试） |
| OpenAPI JSON | `http://121.43.137.176:17283/openapi.json` |
| 健康检查 | `http://121.43.137.176:17283/health` |
| 传输 | 明文 HTTP（比赛环境未配证书）。**上生产必须换 HTTPS。** |

> **Base URL 就是 `http://121.43.137.176:17283`，不要把它写成某个具体接口的地址。**
> 完整请求地址 = Base URL + 接口路径，例如 `http://121.43.137.176:17283/api/v1/home`。
> 如果把 `.../api/v1/demo/seed` 这类完整接口地址错当成 Base URL，
> 会拼出 `/api/v1/demo/seed/v1/models` 这种不存在的路径（服务端返回 404）。

### 鉴权（刻意从简）

**单用户 Demo，前端联调阶段可以完全不传鉴权头。**

| 情况 | 行为 |
|---|---|
| 不带 `Authorization` 头 | 自动落到固定的 Demo 用户 |
| `Authorization: Bearer <有效 token>` | 使用该用户 |
| `Authorization: Bearer <无效 token>` | `401 UNAUTHORIZED`（**不会静默降级**，避免拼错 token 却拿到看起来正常的数据） |

需要显式拿 token 时，两个入口：

```http
GET /api/v1/auth/demo-user
→ { "user_id": "user_ab12...", "access_token": "tok_9f3c...", "token_type": "Bearer", "is_demo": true, "created_at": "..." }
```

```http
POST /api/v1/auth/guest
{ "device_id": "可选，同一个 device_id 会复用已注册的游客", "display_name": "可选" }
→ { "user_id": "user_ab12...", "access_token": "tok_9f3c...", "token_type": "Bearer", "is_demo": false, "created_at": "..." }
```

`/auth/demo-user` 永远返回同一个固定用户，适合联调；`/auth/guest` 按 `device_id`
区分用户，适合在真机上让每个设备有自己的学习档案。Demo 阶段用哪个都行。

### 元接口

```http
GET /                    # 服务名、版本、文档地址
GET /health              # 健康检查
GET /api/v1/health       # 同上（等价别名）
```

```json
{
  "status": "ok",                       // ok | degraded
  "version": "…",
  "llm_mode": "live",                   // live | mock
  "llm_model": "deepseek-ai/DeepSeek-V3.2",
  "vlm_model": "Qwen/Qwen3-VL-32B-Instruct",
  "database": "mysql://hackathon@127.0.0.1:3306/hackathon",
  "bank_count": 1,
  "question_count": 73,
  "uptime_seconds": 1234.5,
  "backup_llm_model": "deepseek-flash",
  "backup_llm_configured": true
}
```

`backup_llm_*` 是**备用 provider**（另一个厂商）。主厂商整体不可用时靠它顶上，
同时也用作二次求解校验的模型。`backup_llm_configured: false` 表示没配 key，
此时兜底能力会弱一档 —— 排查线上问题时先看这两个字段。

### 模型与容错策略

| 顺序 | 角色 | 模型 | 厂商 |
|---|---|---|---|
| 1 | 图片识别 | `deepseek-flash` | DeepSeek |
| 2 | 图片识别 | `Qwen/Qwen3-VL-32B-Instruct` | SiliconFlow |
| 3 | 图片识别 | `Qwen/Qwen3-VL-8B-Instruct` | SiliconFlow |
| — | 二次求解校验 | 与识别模型**不同**的那个（优先 DeepSeek） | — |

- **识别按质量优先降级**：DeepSeek → Qwen3-VL-32B → Qwen3-VL-8B。
  DeepSeek 的识别质量最高（只是慢一些），所以排在最前。
  全部失败才算失败，降级过程会在 `progress` 里以 `retrying` 状态暴露出来。
- **校验模型绝不会是刚做识别的那个**（见 §2.3）。识别是视觉模型、
  校验是文本模型，两边异构，独立性更好；识别降级后校验会自动换一个模型，
  避免"自己复核自己"。
- `deepseek-flash` 是**推理模型**（思维链放在 `reasoning_content`，
  且思考 token 计入 `max_tokens`）。开启 JSON 模式后它的推理量会大幅下降，
  实测同一张图从 10.2s 降到 1.9s。

> 降级到后面几个模型时会明显变慢（每个模型最多试 5 次）。
> 如果某个分析任务耗时异常长，先看 `warnings` 里有没有
> 「…未成功，已降级到 …」。

> 上传大图时若一次要识别十几道题，模型输出可能很长。
> 后端会检查 `finish_reason`：一旦是被 `max_tokens` 截断，
> 会**自动放大预算重发**，而不是原样重试（原样重试只会得到同样被截断的结果）。

### 请求耗时

每个响应都带这两个头，**不用额外请求**：

```http
X-Request-ID: 3f9a1c2b4d5e6f70
X-Response-Time-Ms: 42
```

服务端日志里每次请求也会记一行带耗时的记录，超过 3 秒标 `SLOW`：

```
INFO haoxue: POST /api/v1/homework/analyses -> 202 156ms rid=3f9a1c2b4d5e6f70
INFO haoxue: GET /api/v1/knowledge/mastery-overview -> 200 4213ms SLOW rid=…
```

排查"这次为什么这么慢"时，直接 `grep SLOW` 或按 `rid` 串起同一次请求的所有日志。

### 契约常量（请从这里拉，不要手抄文档）

```http
GET /api/v1/meta/error-codes        # 全部错误码 + 默认 HTTP 状态 + 含义
GET /api/v1/meta/knowledge-points   # 全部知识点（id + 名称 + 描述）
```

两个都是纯常量、不需要鉴权。客户端应当**在构建/启动时拉一次**，
据此生成错误文案映射表，而不是照着文档硬编码 —— 文档会过期，接口不会。

```json
// GET /api/v1/meta/error-codes
{
  "count": 18,
  "codes": ["INVALID_IMAGE", "UNAUTHORIZED", "..."],
  "items": [
    { "error_code": "INVALID_IMAGE", "http_status": 400,
      "description": "图片为空 / 过大 / 不是图片" }
  ]
}
```

另外，`error_code` 在 **OpenAPI schema 里也是 enum**：

```
GET /openapi.json
  → components.schemas.ErrorCode.enum   # 18 个取值
  → components.schemas.ErrorInfo.properties.error_code.$ref → ErrorCode
```

所以用 OpenAPI 生成客户端的团队可以直接拿到类型安全的枚举，不用手写。

> 错误码只有**一个事实来源**（`app/errors.py` 的 `_CODES`），
> 它同时派生枚举、HTTP 状态映射、本文档的表格与上面那个接口 ——
> 所以「文档写了但后端不抛」这种漂移在结构上不可能发生。
> 表是 `python tools/sync_error_codes.py` 生成的，别手改。

### 题目 ID：当成不透明字符串用

**请把 `question_id` 当作不透明标识，不要解析、不要拼、不要假设它长什么样。**

它有可能是两种形态：

| 来源 | 形态 | 例子 |
|---|---|---|
| 题库题 | `math.<主题>.<分组>.<内容指纹>` | `math.derivative.comprehensive.2d662514ec` |
| OCR 上传的题 | `q_<随机>` | `q_6942b7319a1249579f5b` |

**为什么是内容指纹**：题库文件原来的 id 是「第001题」这种按位置编的序号。
题库一旦重新生成、题目顺序变了，序号就会指向另一道题，
历史作答记录（Evidence）就挂错了。所以后端改用**题干内容指纹**做 id：

- 题目内容没变 → id 不变 → 历史记录继续有效
- 题目内容真的改了 → id 变 → 视为另一道题（这正是我们想要的语义）

**要显示题号就用 `question_number`**（`"036"` 这种），不要从 `question_id` 里截取 ——
指纹 id 末尾是一串十六进制，截出来没有意义。

**要追溯「这几次作答是不是同一道题」**用 Evidence 里的 `question_stem_hash`
（见 §3.2），它和题目 id 一样只跟内容走。

### 统一错误格式

所有错误响应体固定为：

```json
{
  "error_code": "INVALID_IMAGE",
  "message": "图片过大：15 MB，上限 12 MB",
  "request_id": "927af55804b54db5",
  "details": {}
}
```

**客户端只根据 `error_code` 做分支，不要解析 `message` 文案。**

| error_code | HTTP | 含义 |
|---|---|---|
| `INVALID_ANSWER` | 400 | 选项不是这道题的合法选项（单选题只能填 A/B/C/D 之一） |
| `INVALID_IMAGE` | 400 | 图片为空 / 过大 / 不是图片 |
| `INVALID_SERIAL_NUMBER` | 400 | 序列号无效、格式不对，或已用于兑换其他书 |
| `QUESTION_NOT_IN_SESSION` | 400 | 提交的题不是当前练习的当前这一题 |
| `UNAUTHORIZED` | 401 | 未认证，或 token 无效 |
| `ANALYSIS_NOT_FOUND` | 404 | 分析任务不存在 |
| `BOOK_NOT_FOUND` | 404 | 图书不存在 |
| `KNOWLEDGE_POINT_NOT_FOUND` | 404 | 知识点 id 不存在 |
| `NOT_FOUND` | 404 | 目标资源不存在 |
| `NO_QUESTIONS_AVAILABLE` | 404 | 这一组题已经做完了 |
| `QUESTION_NOT_FOUND` | 404 | 这道题不在该分析里 |
| `SESSION_NOT_FOUND` | 404 | Tutor / 练习 Session 不存在 |
| `WRONG_QUESTION_NOT_FOUND` | 404 | 错题不存在 |
| `IDEMPOTENCY_CONFLICT` | 409 | 同一个幂等键的请求正在处理中，稍后重试 |
| `QUESTION_ALREADY_RESOLVED` | 409 | 这道题的标准答案已经确认过，且这次给的答案不一样；重复提交同一答案会直接回放原结果 |
| `QUESTION_NOT_CONFIRMABLE` | 409 | 这道题不能人工确认标准答案（学生未作答，没有可判定的作答） |
| `SESSION_COMPLETED` | 409 | Session 已结束，不能再作答 |
| `QUESTION_NOT_RECOGNIZED` | 422 | 没有从图片中识别出题目 |
| `VALIDATION_ERROR` | 422 | 请求参数不合法 |
| `INTERNAL_ERROR` | 500 | 服务端内部错误 |
| `SERVICE_UNAVAILABLE` | 503 | 依赖的服务暂时不可用 |
| `VLM_TIMEOUT` | 504 | 视觉模型超时或不可用 |

### 幂等（重要）

所有**会改变数据**的写接口都支持重复提交保护。**两种传法等价，任选其一**：

- `Idempotency-Key: <客户端生成的 uuid>` 请求头（推荐，**所有写接口都认**）
- 或请求体/表单里的 `client_request_id`

> 两者都带时**以请求头为准**。同时也接受 `X-Idempotency-Key` 这个别名。

不带幂等键时，手机断网重试会**把掌握度更新两次**。

| 接口 | 幂等键 |
|---|---|
| `POST /api/v1/homework/analyses` | 请求头 + 表单 `client_request_id` |
| `POST /api/v1/practice/sessions` | 请求头 + 请求体 `client_request_id` |
| `POST /api/v1/practice/sessions/{id}/answers` | 请求头 + 请求体 `client_request_id` |
| `POST /api/v1/tutor/sessions` | 请求头 + 请求体 `client_request_id` |
| `POST /api/v1/tutor/sessions/{id}/turns` | 请求头 + 请求体 `client_request_id` |
| `POST /api/v1/books/{book_id}/redeem` | 请求头 |
| `PATCH /api/v1/wrong-questions/{id}` | 不需要 —— 同一状态重复提交结果相同（HTTP 语义上天然幂等） |

服务端的实现是「**先原子占位，再干活，最后用真正的响应覆盖占位**」，
所以**顺序重试**和**并发重试**都不会重复计分：

| 情况 | 结果 |
|---|---|
| 首次请求 | 正常处理，响应里的 `replayed` 为 `false`（练习/辅导） |
| 同一个 key **再次**请求（已完成） | 直接回放上次响应，**不重复写 Evidence** |
| 同一个 key **同时**并发请求（还在处理） | `409 IDEMPOTENCY_CONFLICT`，客户端稍后重试即可 |
| 请求本身失败（400 / 404 / 409） | 占位会被释放，同一个 key 可以重试 |

> 并发那一条是刻意的：与其静默地把掌握度算两遍，不如明确告诉客户端
> 「这个请求已经在处理了」。客户端遇到 409 时**等 1 秒原样重发**即可。

> ⚠️ 只发请求头、请求体里不带 `client_request_id` 是**完全支持**的。
> （早期版本只有 `homework` 真的读了这个头，practice / tutor 会静默失去保护，
> 已修复并有回归测试。）

### 其它响应头

```
X-Request-ID: 927af55804b54db5
X-Response-Time-Ms: 143
```

---

## 1. 首页（聚合接口）

> 首页**只调这一个接口**，不要同时请求五六个 API。

```http
GET /api/v1/home
```

```json
{
  "user_id": "user_ab12",
  "greeting": "晚上好，同学",
  "next_action": {
    "action": "start_tutor",
    "title": "下一步：导数与函数性质综合应用",
    "reason": "最近 12 次相关作答中出现 分类讨论错误 ×3、函数性质转换错误 ×3",
    "cta_label": "开始学习",
    "knowledge_point_id": "math.derivative.monotonicity_applications",
    "knowledge_point_name": "导数与函数性质综合应用",
    "wrong_question_id": null
  },
  "knowledge_summary": [
    { "knowledge_point_id": "math.derivative.monotonicity", "name": "利用导数判断函数单调性与单调区间",
      "mastery": 0.8342, "confidence": 0.52, "evidence_count": 6, "trend": "stable", "is_weak": false },
    { "knowledge_point_id": "math.derivative.monotonicity_applications", "name": "导数与函数性质综合应用",
      "mastery": 0.4322, "confidence": 0.79, "evidence_count": 12, "trend": "declining", "is_weak": true },
    { "knowledge_point_id": "math.derivative.absolute_extrema", "name": "利用导数求函数最值",
      "mastery": 0.7194, "confidence": 0.55, "evidence_count": 6, "trend": "declining", "is_weak": false }
  ],
  "weakest": { "knowledge_point_id": "math.derivative.monotonicity_applications", "name": "导数与函数性质综合应用",
               "mastery": 0.4322, "confidence": 0.79, "evidence_count": 12,
               "trend": "declining", "is_weak": true },
  "wrong_question_count": 3,
  "recent_wrong_questions": [
    { "wrong_question_id": "wq_1a2b", "question_id": "q_9f3c", "question_number": "17",
      "question_content": "已知函数 f(x) = x^3 - 3x^2 + 2，求 f(x) 的单调递增区间。",
      "knowledge_point_id": "math.derivative.monotonicity", "knowledge_point_name": "利用导数判断函数单调性与单调区间",
      "error_type": "transformation", "error_label": "函数性质转换错误",
      "status": "open", "created_at": "2026-10-01T21:30:00+00:00" }
  ],
  "recent_activities": [
    { "activity_type": "homework", "title": "数学月考·第17题", "subtitle": "1 题 · 对 0 错 1",
      "reference_id": "hw_7c1d", "occurred_at": "2026-10-01T21:30:00+00:00" }
  ],
  "stats": { "total_evidence": 43, "homework_count": 1, "wrong_question_open": 3,
             "tutor_session_count": 0, "practice_attempt_count": 0, "streak_days": 1 },
  "updated_at": "2026-10-01T21:35:00+00:00"
}
```

`next_action.action` 的取值与对应按钮：

| action | 含义 | 建议按钮 |
|---|---|---|
| `start_tutor` | 去学这个薄弱点 | 「开始学习」→ `POST /tutor/sessions` |
| `continue_practice` | 继续刷题巩固 | 「开始练习」→ `POST /practice/sessions` |
| `review_wrong_question` | 重做错题 | 「重做错题」→ `GET /wrong-questions/{id}` |
| `increase_difficulty` | 提高难度 | 「提高难度」→ `POST /practice/sessions` |
| `review_later` / `all_good` | 都达标了 | 弱提示即可 |

---

## 2. 上传作业 / 试卷（异步）

> **只有这一步需要实时 AI。** 题库是预处理好的，其余全部走算法。

### 2.1 创建分析任务

```http
POST /api/v1/homework/analyses
Content-Type: multipart/form-data
Idempotency-Key: <可选，强烈建议>
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `images` | file[] | ✅ | 一张或多张图片，字段名必须是 `images`，可重复出现 |
| `subject` | string | | 默认 `mathematics` |
| `topic` | string | | 如 `derivative` |
| `book_id` | string | | 来源图书 |
| `source_name` | string | | 如「某作业本第 32 页」 |
| `client_request_id` | string | | 幂等备用字段 |

**两张图片的 multipart 长这样**（注意每个文件部分都要有 `filename`）：

```text
Content-Disposition: form-data; name="images"; filename="page1.jpg"
Content-Type: image/jpeg
<binary>

Content-Disposition: form-data; name="images"; filename="page2.jpg"
Content-Type: image/jpeg
<binary>
```

关于图片格式校验，有两点是刻意这么做的：

- **服务端只认文件头（魔数），不信你声明的 `Content-Type` 和文件名。**
  所以 `application/octet-stream` + 不带扩展名的 `filename="photo"` 也能正常上传 ——
  这是 `URLSession` 手工拼 multipart 时的默认行为，不该因此被拒。
- 反过来，**声明成 `image/png` 但字节不是图片的，会被拒**（`INVALID_IMAGE`）。

> ⚠️ 文件部分**必须带 `filename`**。如果 `Content-Disposition` 里没有
> `filename=`，服务端会把它当作普通文本字段解析，二进制内容会被破坏，
> 无法还原成图片，只能返回参数错误。任何标准 multipart 构造方式默认都会带上它。

**立刻返回 202，不等 AI 跑完：**

```json
{ "analysis_id": "ana_9b16554e", "status": "queued", "created_at": "2026-10-01T21:30:00+00:00" }
```

### 2.2 轮询进度（可持续追踪的卡片就用这个）

```http
GET /api/v1/homework/analyses/{analysis_id}
```

**处理中：**

```json
{
  "analysis_id": "ana_9b16554e",
  "status": "processing",
  "progress": {
    "percent": 0.62,
    "current_stage": "Finding error patterns",
    "current_stage_key": "error_patterns",
    "current_stage_label_zh": "正在分析错误模式",
    "stages": [
      { "key": "image_received",     "label": "Image received",           "label_zh": "已接收图片",       "state": "done" },
      { "key": "questions_detected", "label": "Questions detected",       "label_zh": "已识别题目",       "state": "done" },
      { "key": "answers_understood", "label": "Answers understood",       "label_zh": "已理解作答",       "state": "done" },
      { "key": "error_patterns",     "label": "Finding error patterns",   "label_zh": "正在分析错误模式", "state": "active" },
      { "key": "knowledge_updated",  "label": "Updating knowledge state", "label_zh": "正在更新知识状态", "state": "pending" }
    ]
  },
  "created_at": "...", "updated_at": "..."
}
```

- `state`: `done` | `active` | `retrying` | `pending` | `failed`
  - 分析失败时，**出错的那一步是 `failed`（不是 `active`）**，前端可以据此在卡片上
    标出「就是这一步失败的」。例如图里识别不出题目时：
    `image_received: done` / `questions_detected: failed` / 其余 `pending`，
    同时 `error.error_code = "QUESTION_NOT_RECOGNIZED"`。
  - 模型不可用（`VLM_TIMEOUT`）失败点同样落在 `questions_detected`。
  - **`retrying` 是第三种状态，不是失败。** 识别模型降级重试时当前阶段标成
    `retrying`，同时 `progress` 里多出两个字段：
    ```json
    "retrying": true,
    "retry_note": "第 1 张：deepseek-flash 未成功，正在用 Qwen/Qwen3-VL-32B-Instruct 重试（2/3）"
    ```
    前端应当显示成「正在用备用模型重试」而不是看起来卡住或失败。
    重试成功后状态会回到正常流程。
- **多张图片是并行识别的**，所以耗时取决于最慢的那一张，不是页数之和。
  实测 1 张约 21 秒、3 张同样约 21 秒。并发上限 4（打满模型配额反而会被限流）。
- 建议轮询间隔 1 秒；`status` 变为 `completed` / `failed` 即停止
- 模型偶尔会返回不合法的 JSON（最常见的是在中文正文里把引号打成了 ASCII 的 `"`，
  导致字符串提前闭合）。服务端会自动修复，修不好就重试，
  **识别链上每个模型各 5 次**。若输出是被 `max_tokens` 截断，服务端会**放大预算**
  重发而不是原样重试（原样重试必然得到同样被截断的结果）。

**完成后**（同结构，追加结果字段）：

```json
{
  "status": "completed",
  "progress": { "percent": 1.0, "current_stage": "Completed", "stages": [ "…全部 done…" ] },
  "homework_id": "hw_7c1d",
  "correct_count": 0, "wrong_count": 1, "partial_count": 0,
  "unanswered_count": 0, "unknown_count": 0,

  "questions": ["q_6942b7319a1249579f5b"],
  "question_results": [
    {
      "question_id": "q_6942b7319a1249579f5b",
      "question_number": "17",
      "question_type": "single_choice",
      "question_content": "已知函数 f(x) = x^3 - 3x^2 + 2，求 f(x) 的单调递增区间。",
      "choices": { "A": "(-inf, 0)", "B": "(0, 2)", "C": "(-inf, 0) 和 (2, +inf)", "D": "(2, +inf)" },
      "student_answer": "A",
      "correct_answer": "C",
      "correctness": "wrong",
      "possible_answer": null,
      "possible_answer_source": null,
      "knowledge_points": [
        { "knowledge_point_id": "math.derivative.monotonicity", "name": "利用导数判断函数单调性与单调区间", "weight": 1.0 },
        { "knowledge_point_id": "math.derivative.monotonicity_parameter",  "name": "利用单调性或导数恒成立求参数", "weight": 0.75 }
      ],
      "error_type": "transformation",
      "error_label": "函数性质转换错误",
      "diagnosis": "学生能正确求导，但把导数符号与单调性的对应关系弄反了。",
      "explanation": "f'(x) = 3x^2 - 6x = 3x(x-2)，令 f'(x) > 0 得 x<0 或 x>2……",
      "confidence": 0.97,
      "difficulty": 0.5,
      "image_url": "http://121.43.137.176:17283/media/ana_9b16554e/0.png"
    }
  ],

  "knowledge_changes": [
    { "knowledge_point_id": "math.derivative.monotonicity", "name": "利用导数判断函数单调性与单调区间",
      "before": 0.618, "after": 0.5744, "delta": -0.0436, "evidence_count": 8 }
  ],
  "new_wrong_questions": [ { "wrong_question_id": "wq_1a2b", "…": "…" } ],
  "next_action": { "action": "start_tutor", "title": "下一步：导数与函数性质综合应用", "…": "…" },
  "warnings": [],
  "generated_by": "vlm",
  "error": null
}
```

> `questions` 是题目 id 列表；`question_results` 是完整对象。两者都在，不要混淆。

**失败时：**

```json
{ "status": "failed", "error": { "error_code": "VLM_TIMEOUT", "message": "视觉模型不可用" } }
```

### 2.2.1 `correctness` 的五个取值

| 值 | 含义 | 计入掌握度 |
|---|---|---|
| `correct` | 答对 | ✅ |
| `wrong` | 答错 | ✅ |
| `partial` | 部分正确 | ✅ |
| **`unanswered`** | **学生没作答**（或字迹读不出来） | ❌ |
| **`unknown`** | **复核没通过**（两个模型分歧 / 独立求解失败） | ❌ |

`unanswered` 与 `unknown` **都对掌握度零影响**，但**对用户的含义完全不同**：

- `unanswered` → 「这题你没做」
- `unknown` → 「这题我没算准」

**请不要把它们合并显示**，否则学生会以为 AI 出了故障，其实是他自己没写。

### 2.2.2 `possible_answer`：判不准的时候也别把信息丢掉

`correctness == "unknown"` 时 `correct_answer` 是 `null`（服务端**拒绝拿一个
没复核过的答案去算分**），但会额外给一个 `possible_answer` 作参考：

```json
{
  "correctness": "unknown",
  "correct_answer": null,
  "possible_answer": "D",
  "possible_answer_source": "deepseek-flash"
}
```

- 两个模型**分歧**时 → 取**独立求解模型**的答案（它没参与识别，不受视觉误读影响）
- **独立求解失败**时 → 取识别模型读到的答案

⚠️ **`possible_answer` 绝不参与算分**，只是一个「可能是 X」的提示。
UI 建议显示成「AI 无法确认本题答案（可能是 D），未计入统计」。

### 2.2.3 人工确认 / 纠正标准答案

模型读错答案、或者它自己也不确定被复核判成 `unknown` 时，学生对着**答案册**
给的答案是最可靠的信号源。这个接口就是「报错并改正」按钮的后端。

```http
POST /api/v1/homework/analyses/{analysis_id}/questions/{question_id}/confirm-answer
Content-Type: application/json
Idempotency-Key: <UUID>            # 可选；也可用 body 里的 client_request_id

{ "correct_answer": "C", "client_request_id": "<UUID>" }
```

#### 服务端做什么（**不调 AI**）

只换掉标准答案，**题干 / 选项 / 知识点 / 标签 / 讲解 / 难度全部沿用模型的产出**，
然后重新判定对错，并在本地重跑这道题的下游：

```
旧 Evidence 作废（删掉）
    → 按新判定写入新 Evidence
        → 掌握度自动更新
        → 标签统计自动更新（它从 Evidence 现算）
        → 错题投影重算
        → 分析里的 counts 重算
```

> ⚠️ **为什么是"删掉再写"而不是"追加"**：原来的 Evidence 建立在那个错答案的前提上。
> 追加的话掌握度会同时算上"旧判定的错"和"新判定的对"，既双重计数、
> 又永远留着一条错的。所以这道题在这次分析里的旧 Evidence 会被替换。

`correctness` 由服务端用 **已保存的 `student_answer`** + 你提交的答案算出来。
**客户端不提交 `correctness`，也不能改 `student_answer`。**

#### 响应

```json
{
  "analysis_id": "ana_xxx",
  "question_id": "q_xxx",
  "student_answer": "D",
  "correct_answer": "C",
  "correctness": "wrong",

  "confirmation": {
    "source": "user",
    "confirmed_at": "2026-10-03T13:20:00+00:00",
    "original_correct_answer": "C",
    "correction_count": 1
  },

  "analysis_summary": {
    "question_count": 9,
    "correct_count": 5,
    "wrong_count": 1,
    "partial_count": 0,
    "unanswered_count": 0,
    "unknown_count": 3
  },

  "wrong_question": { "wrong_question_id": "wq_xxx", "status": "open", "attempt_count": 1 },
  "next_action": { "action": "start_tutor", "title": "…", "cta_label": "开始学习" },
  "replayed": false
}
```

| 字段 | 说明 |
|---|---|
| `original_correct_answer` | **AI 原来的说法**（`unknown` 的题取自 `possible_answer` 的猜测）。留着是为了让模型的问题可追溯 —— 只看到"结果变了"是查不出模型哪里错的 |
| `wrong_question` | 这道题**当前**的待复习项；判对、或已被收掉时为 `null` |
| `replayed` | 同一答案重复提交时为 `true`，此时**没有**重复写 Evidence |

#### 允许范围与错误

**任何有学生作答的题**都可以人工改判 —— 不只 `unknown`。
「AI 判错了，学生指出真正的答案」正是这个接口的主要用途。

| 情况 | 结果 |
|---|---|
| 学生未作答（`unanswered`） | `409 QUESTION_NOT_CONFIRMABLE` —— 补答案也判不出对错 |
| 分析还没跑完 | `409 QUESTION_NOT_CONFIRMABLE` |
| 选项不在该题的 `choices` 里 | `400 INVALID_ANSWER` |
| 这道题不属于该分析 | `404 QUESTION_NOT_FOUND` |
| 分析不存在 / 不是本人的 | `404 ANALYSIS_NOT_FOUND` |
| 已确认过、这次答案**相同** | `200`，`replayed: true`，**不重复写 Evidence** |
| 已确认过、这次答案**不同** | `409 QUESTION_ALREADY_RESOLVED` —— 不允许静默覆盖 |

> `unanswered` 与 `unknown` **语义不同，不能合并**：
> 前者是"学生没作答"，后者是"AI 确认不了标准答案"。
> 只有后者（以及任何已有作答的题）能通过这个接口改判。

同一道题**可以反复改判**（`wrong` → `correct` → `wrong` 都行），
每次会替换掉上一次的 Evidence，`correction_count` 累加。
但**已确认过再提交一个不同的答案会被拒绝** —— 想改必须先明确覆盖的语义，
现阶段宁可让前端提示用户"这道题已经确认过了"。

### 2.3 关于「AI 会不会教错」

服务端有一套**二次校验**机制，你可以放心展示：

- 题干能匹配到题库 → 直接采用**题库里经过人工验算的答案**；
- 匹配不到 → 再用**另一个模型**独立求解一遍，**两次答案一致才采信**；
- 两次不一致或复核失败 → 该题 `correctness` 返回 `"unknown"`、
  `correct_answer` 为 `null`，给出 `possible_answer` 作参考，
  并在 `warnings` 里说明，**且不计入掌握度统计**。

> **「另一个模型」是硬性要求。** 校验模型绝不会是刚做识别的那个 ——
> 否则等于让同一个模型自己复核自己：它要么复述自己的答案（等于没校验），
> 要么在同一次故障里一起失败。之前踩过这个坑：识别降级到某个模型后，
> 校验也用同一个模型，于是校验整批失败、题目全被记成 `unknown`，
> 而正确答案其实就在手里。

所以学生可能看到极少数 `unknown` 的题，UI 建议显示成
「AI 无法确认本题答案（可能是 X），未计入统计」。这是刻意设计的保守行为，不是 bug。

### 2.4 历史分析列表

```http
GET /api/v1/homework/analyses?limit=20
```

---

### 2.5 上传批次列表（近 50 批）

```http
GET /api/v1/homework/batches?limit=50
```

每次上传都算**一批**，服务端给它分配一个该用户内**递增的批次号**
`batch_number`（从 1 开始，唯一、不复用）。稳定机器标识仍然是 `analysis_id`，
`batch_number` 是给人看的编号。

这个接口就是给「上传记录」列表用的，一次拿齐状态、编号、时间与进度。

```json
{
  "total": 23,
  "processing_count": 1,
  "success_count": 20,
  "failed_count": 2,
  "limit": 50,
  "items": [
    {
      "batch_number": 23,
      "analysis_id": "ana_9f3c…",
      "state": "processing",
      "state_label": "正在处理",
      "status": "processing",
      "image_count": 2,
      "source_name": "数学下册第17题",
      "created_at": "2026-10-02T14:50:00+00:00",
      "finished_at": null,
      "progress": { "…": "与 2.2 完全一样的结构" },
      "duration_seconds": null,
      "question_count": null,
      "correct_count": null,
      "wrong_count": null,
      "error": null
    },
    {
      "batch_number": 22,
      "analysis_id": "ana_7a11…",
      "state": "success",
      "state_label": "成功",
      "status": "completed",
      "image_count": 1,
      "source_name": "数学下册第17题",
      "created_at": "2026-10-02T14:40:00+00:00",
      "finished_at": "2026-10-02T14:40:28+00:00",
      "progress": null,
      "duration_seconds": 28.3,
      "question_count": 1,
      "correct_count": 0,
      "wrong_count": 1,
      "error": null
    },
    {
      "batch_number": 21,
      "analysis_id": "ana_5b02…",
      "state": "failed",
      "state_label": "失败",
      "status": "failed",
      "image_count": 1,
      "source_name": null,
      "created_at": "2026-10-02T14:30:00+00:00",
      "finished_at": "2026-10-02T14:30:03+00:00",
      "progress": null,
      "duration_seconds": 3.0,
      "question_count": null,
      "correct_count": null,
      "wrong_count": null,
      "error": { "error_code": "QUESTION_NOT_RECOGNIZED",
                 "message": "没有从图片中识别出题目" }
    }
  ]
}
```

**字段说明**

| 字段 | 说明 |
|---|---|
| `batch_number` | 批次编号，该用户内从 1 递增 |
| `state` | **对外只有三态**：`processing` / `success` / `failed` |
| `state_label` | 中文标签：`正在处理` / `成功` / `失败`，可直接显示 |
| `status` | 内部原始状态（`queued` / `processing` / `completed` / `failed`），排查用 |
| `created_at` | 上传时间（都有） |
| `finished_at` | **成功 / 失败才有**，完成或失败的时刻 |
| `duration_seconds` | **成功 / 失败才有**，从上传到结束的秒数 |
| `progress` | **进行中才有**，结构与 2.2 完全一样，可直接渲染进度卡片 |
| `question_count` / `correct_count` / `wrong_count` | **成功才有** |
| `error` | **失败才有**，`{error_code, message}` |

**三个状态各自有什么**（客户端可以照着做条件渲染）：

```
processing → progress（5 阶段）
success    → finished_at + duration_seconds + 题目统计
failed     → finished_at + duration_seconds + error
```

**其它**

- 列表**最新的在前**（按 `batch_number` 倒序）。
- `limit` 上限 **50**，传更大也只返回 50。
- `total` 与三个计数是对**全部**批次统计的，不随 `limit` 变化，可以用来显示角标
  （例如「处理中 1」）。
- 轮询建议：列表页 2–3 秒一次即可；只在有 `processing` 时才需要轮询。
- 单批的详细进度仍然用 `GET /api/v1/homework/analyses/{analysis_id}`（2.2）。

---

## 3. Knowledge State

### 3.0 综合掌握度（首页那个大数字）

```http
GET /api/v1/knowledge/mastery-overview
```

无参数。返回一个**两位整数百分比**，直接显示即可：

```json
{
  "score": 60,
  "percent": 0.6045,
  "weighted_mastery": 0.6045,
  "coverage": 1.0,
  "covered_count": 17,
  "point_count": 17,
  "evidence_count": 103,
  "weakest": [
    { "knowledge_point_id": "math.derivative.monotonicity_applications",
      "name": "导数与函数性质综合应用", "mastery": 0.432 },
    { "knowledge_point_id": "math.derivative.parity_symmetry",
      "name": "奇偶性、对称性与周期性中的导数关系", "mastery": 0.441 },
    { "knowledge_point_id": "math.derivative.tangent_extrema",
      "name": "切线相关的最值问题", "mastery": 0.444 }
  ]
}
```

| 字段 | 含义 |
|---|---|
| `score` | **要显示的就是它**，0–99 的整数 |
| `percent` | 精确值（0..1），需要更细的展示时用 |
| `weighted_mastery` | 已练知识点的置信度加权平均，**未**折算覆盖率 |
| `coverage` | 已练知识点占全部的比例 |
| `covered_count` / `point_count` | 有证据的点数 / 总点数 |
| `evidence_count` | 参与统计的证据条数 |
| `weakest` | 掌握度最低的 3 个，可直接拿来做「该练什么」 |

**算法**（两步，刻意做得能一句话讲清）：

```
1. 置信度加权平均：raw = Σ(mastery_i × confidence_i) / Σ(confidence_i)
     只统计有证据的知识点；证据少的点发言权小
2. 覆盖率折算：    score = round(raw × 已练点数 / 总点数 × 100)
```

为什么要有第 2 步 —— 光看平均值会误导：

| 情形 | 只看平均 | 加覆盖率折算 |
|---|---|---|
| 什么都没做 | 50%（先验） | **0** |
| 只练了 1 个知识点、恰好答对 | 65%（虚高） | **8** |
| 练满 17 个、平均 60% | 60% | **60** |

**宁可偏低也不虚高** —— 这个数字是给学生看的，虚高比偏低有害得多。

> 本项目里 **17 个标签与 17 个知识点一一对应**（标签名就是知识点名），
> 所以「所有标签的掌握度平均」等价于「所有知识点的掌握度平均」。

### 3.1 整棵树

```http
GET /api/v1/knowledge
```

```json
{
  "user_id": "user_ab12",
  "subject": "mathematics",
  "updated_at": "...",
  "tree": [
    { "knowledge_point_id": "math.derivative.monotonicity", "name": "利用导数判断函数单调性与单调区间",
      "description": "由 f'(x) 的符号判断函数的单调性，并求出单调区间",
      "mastery": 0.8342, "confidence": 0.52, "evidence_count": 6, "trend": "stable", "children": [] },
    { "knowledge_point_id": "math.derivative.absolute_extrema", "name": "利用导数求函数最值",
      "mastery": 0.7194, "confidence": 0.55, "evidence_count": 6, "trend": "declining", "children": [] },
    { "knowledge_point_id": "math.derivative.monotonicity_parameter", "name": "利用单调性或导数恒成立求参数",
      "mastery": 0.6896, "confidence": 0.58, "evidence_count": 7, "trend": "declining", "children": [] },
    { "knowledge_point_id": "math.function.parity_and_monotonicity", "name": "函数奇偶性与单调性综合判断",
      "mastery": 0.6839, "confidence": 0.52, "evidence_count": 5, "trend": "unknown", "children": [] },
    { "knowledge_point_id": "math.derivative.extrema", "name": "利用导数判断与求解极值",
      "mastery": 0.6180, "confidence": 0.58, "evidence_count": 7, "trend": "declining", "children": [] },
    { "knowledge_point_id": "math.derivative.extrema_parameter", "name": "根据极值或最值条件求参数",
      "mastery": 0.5084, "confidence": 0.55, "evidence_count": 6, "trend": "declining", "children": [] },
    { "knowledge_point_id": "math.derivative.monotonicity_applications", "name": "导数与函数性质综合应用",
      "mastery": 0.4322, "confidence": 0.79, "evidence_count": 12, "trend": "declining", "children": [] }
  ],
  "weakest": [
    { "knowledge_point_id": "math.derivative.monotonicity_applications", "name": "导数与函数性质综合应用",
      "mastery": 0.4322, "confidence": 0.79, "priority": 0.2295,
      "reason": "当前掌握度 43%，共 12 条作答证据；近期呈下降趋势" }
  ],
  "next_action": { "…": "…" },
  "total_evidence": 49
}
```

> 官方知识点清单是**扁平**的 7 个（`knowledge_points.json` version 1），没有父子层级，
> 所以 `tree` 里每个节点的 `children` 都是空数组。

> **服务端直接返回树形结构，iOS 不要自己拼。**
> 父节点掌握度由子节点按证据量加权聚合而来，不是独立存储的数字。

### 3.2 知识点详情（"为什么是 43%？"）

```http
GET /api/v1/knowledge/{knowledge_point_id}
```

```json
{
  "knowledge_point_id": "math.derivative.monotonicity_applications",
  "name": "导数与函数性质综合应用",
  "description": "导数与参数、方程根的分布等综合问题",
  "subject": "mathematics",
  "mastery": 0.4322,
  "confidence": 0.79,
  "trend": "declining",
  "evidence_count": 12,
  "correct_count": 4, "partial_count": 3, "wrong_count": 5,
  "recent_performance": [
    { "occurred_at": "2026-09-30T21:30:00+00:00", "result": "incorrect",
      "source_type": "practice",
      "question_id": "math.derivative.comprehensive.fdd405da9c" }
  ],
  "error_patterns": [
    { "error_type": "case_analysis",  "label": "分类讨论错误",       "count": 3, "share": 0.375 },
    { "error_type": "transformation", "label": "函数性质转换错误",   "count": 3, "share": 0.375 },
    { "error_type": "domain_omission","label": "定义域遗漏",         "count": 2, "share": 0.25 }
  ],
  "evidence": [
    { "evidence_id": "ev_1", "knowledge_point_id": "…", "source_type": "practice",
      "question_id": "math.derivative.comprehensive.fdd405da9c",
      "question_stem_hash": "fdd405da9c",
      "result": "incorrect", "confidence": 1.0,
      "error_type": "case_analysis", "error_label": "分类讨论错误",
      "answer_excerpt": null, "detail": "分类讨论时漏了 a<0 的情况",
      "created_at": "2026-09-06T21:30:00+00:00" }
  ],
  "prerequisites": [
    { "knowledge_point_id": "math.derivative.extrema", "name": "利用导数判断与求解极值", "weight": 0.5084 }
  ],
  "mastery_explanation": "最近 12 次相关作答：正确 4 次、部分正确 3 次、错误 5 次。主要错误模式：分类讨论错误 ×3、函数性质转换错误 ×3、定义域遗漏 ×2。按题目难度与时间衰减加权后，掌握度为 43%（置信度 79%）。近期表现不如之前，需要留意。",
  "recommended_action": { "…": "…" },
  "updated_at": "..."
}
```

**这个界面就是「查看证据」的落点**：`error_patterns` 说明错在哪类问题上，
`evidence` 是可点击的真实作答记录，`mastery_explanation` 是给用户看的一句话解释。

`result` 取值：`correct` | `partial` | `incorrect` | `unknown`。

---

## 4. 错题库

### 4.0 一行错题 = 一道「当前要复习的题」

**列表的语义是「我现在有哪些题需要复习」，不是「历史上有过多少次做错」。**

同一道题在不同作业里做错多次，列表里**只出现一条**：

```
canonical question（题干指纹 question_stem_hash）
    └── attempts / evidence           ← 每次作答的完整历史，永不删除
            └── 错题项（本节）         ← 去重后的「当前待复习」投影
```

- 第一次做错时创建，`wrong_question_id` **就此固定，之后不再变** ——
  可以安全地长期引用、存本地缓存、跨设备对齐
- 之后每次做错**合并进同一条**：`attempt_count` 累加、
  `attempts` 追加明细、快照刷新成**最近一次**的内容、状态拉回 `open`
- **历史不会被删**：每次作答的原始记录在 `questions` 表，
  知识点层面的证据在 `evidence` 表（都带 `question_stem_hash`）

> 所以「错题条数」和「Evidence 条数」本来就不相等，这是设计如此。
> 做过 3 次错 3 次 → 错题 1 条、Evidence 3 条。

```http
GET /api/v1/wrong-questions?knowledge_point_id=math.derivative.monotonicity&status=open&limit=100
```

支持的筛选：`knowledge_point_id`、`book_id`、`status`(`open`/`resolved`/`archived`)、
`date_from`(ISO 时间)、`limit`。

```json
{
  "user_id": "user_ab12",
  "total": 1,
  "items": [
    { "wrong_question_id": "wq_1a2b", "question_id": "q_9f3c", "question_number": "17",
      "question_content": "已知函数 f(x) = x^3 - 3x^2 + 2，求 f(x) 的单调递增区间。",
      "knowledge_point_id": "math.derivative.monotonicity", "knowledge_point_name": "利用导数判断函数单调性与单调区间",
      "error_type": "transformation", "error_label": "函数性质转换错误",
      "status": "open",
      "question_stem_hash": "25d381143d",
      "attempt_count": 3,
      "first_wrong_at": "2026-09-28T21:30:00+00:00",
      "last_wrong_at": "2026-10-01T21:30:00+00:00",
      "created_at": "2026-09-28T21:30:00+00:00" }
  ]
}
```

| 字段 | 含义 |
|---|---|
| `attempt_count` | 这道题**累计**做错几次，UI 可以显示「做错 3 次」 |
| `question_stem_hash` | 规范题目身份。**客户端不需要用它去重**（列表已去重），可用作本地缓存键 |
| `first_wrong_at` / `last_wrong_at` | 第一次 / 最近一次做错的时间 |
| `question_id` | **最近一次** attempt 的题目 id（不是固定的，别拿它当主键） |

> ⚠️ 要长期引用请用 `wrong_question_id`（稳定）。
> `question_id` 每次 attempt 都不同，它标识的是"那一次作业里的那道题"。

```http
GET /api/v1/wrong-questions/{wrong_question_id}
```

在列表字段基础上追加：`question_type`、`choices`、`student_answer`、`correct_answer`、
`explanation`、`correctness`、`diagnosis`、`image_url`、`source_type`、`source_id`、
`source_name`、`favorite`、`updated_at`、`can_start_tutor`，
以及**逐次作答明细** `attempts`：

```json
"attempts": [
  { "question_id": "q_aaa", "homework_id": "hw_111", "student_answer": "B",
    "correctness": "wrong", "created_at": "2026-09-28T21:30:00+00:00" },
  { "question_id": "q_bbb", "homework_id": "hw_222", "student_answer": "A",
    "correctness": "wrong", "created_at": "2026-10-01T21:30:00+00:00" }
]
```

最早的在前面，最多保留 20 条（更早的仍可在后端 Evidence 里查到）。
想展示「这道题我错过哪几次、每次选了什么」就用它。

> 详情页的 **Start Learning** 按钮：
> `POST /api/v1/tutor/sessions` + `{"source_type": "wrong_question", "wrong_question_id": "wq_1a2b"}`

```http
PATCH /api/v1/wrong-questions/{wrong_question_id}
{ "status": "resolved", "favorite": true }
```

> 标记成 `resolved` 之后如果**又做错了**，这条会自动变回 `open` ——
> 否则学生会看到一道"已解决"的题其实是错的。

---

## 5. AI Tutor（有状态，不是聊天框）

### 5.1 创建 Session（三个入口共用）

```http
POST /api/v1/tutor/sessions
```

**A. 从知识点进入**

```json
{ "source_type": "knowledge_point",
  "knowledge_point_id": "math.derivative.monotonicity_applications" }
```

**B. 从错题进入**

```json
{ "source_type": "wrong_question", "wrong_question_id": "wq_1a2b" }
```

**C. 拍一道不会的题**

```json
{ "source_type": "uploaded_question",
  "image_base64": "<base64，可带 data:image/jpeg;base64, 前缀>",
  "mime_type": "image/jpeg" }
```

也可以只传 `question_text` 走文本匹配。

返回 `TutorSessionResponse`：

```json
{
  "tutor_session_id": "tut_5e8f",
  "user_id": "user_ab12",
  "source_type": "knowledge_point",
  "source_id": null,
  "knowledge_point_id": "math.derivative.monotonicity_applications",
  "knowledge_point_name": "导数与函数性质综合应用",
  "phase": "diagnose",
  "difficulty": 0.4322,
  "attempt_count": 0, "hint_count": 0,
  "student_understanding": 0.4322,
  "completed": false,
  "turn": {
    "turn_id": "turn_1", "seq": 1,
    "turn_type": "concept_question",
    "text": "已知 f(x) = x^3 - 3x^2 + 2 的极大值是 2、极小值是 -2。方程 f(x) = k 有三个不同实根，从图像上看是什么意思？",
    "choices": [
      { "key": "A", "text": "水平直线 y = k 与曲线 y = f(x) 有三个交点" },
      { "key": "B", "text": "曲线与 x 轴有三个交点" },
      { "key": "C", "text": "k 必须等于 0" },
      { "key": "D", "text": "k 可以取任意实数" }
    ],
    "allow_free_text": true,
    "phase": "diagnose",
    "progress": { "step": 1, "total_steps": 5, "percent": 0.2 },
    "completed": false,
    "question_id": null,
    "created_at": "..."
  },
  "history": [ "…含上面 turn…" ],
  "knowledge_changes": [],
  "next_action": null,
  "created_at": "...", "updated_at": "..."
}
```

### 5.2 提交作答

```http
POST /api/v1/tutor/sessions/{session_id}/turns
```

```json
{ "selected_key": "B", "text": null, "self_reported_confidence": "guess",
  "client_request_id": "<可选幂等键>",
  "answering_turn_id": "<强烈建议：你正在回答的那一轮的 turn.turn_id>",
  "stream": false }
```

- 选择题传 `selected_key`（`"A"`~`"D"`）
- 开放题传 `text`
- 「我不确定」传 `self_reported_confidence: "unsure"`
- **`answering_turn_id` 强烈建议传** —— 见下面的「重复提交保护」
- `stream: true` → 返回 SSE（见 §5.2.2）；缺省或 `false` → 维持下面的 JSON 契约

#### 重复提交保护（`answering_turn_id`）

练习接口靠 `question_id` 天然能分辨「网络重试」和「真的答下一题」——
同一道题再提交一次，服务端原样回放上次结果。

**Tutor 没有这个东西**：客户端只说「我选了 A」，服务端无法区分
网络重试、手抖连点、还是用户真的在答下一题。后果是同一份作答被消费两次，
第二次还会推进教学流程 —— 学生根本没看见那道题就被记了 Evidence。

所以请把**你正在回答的那一轮的 `turn.turn_id` 回传**：

```json
// 上一轮你收到 turn.turn_id = "turn_9c1d"
// 回答它时带上：
{ "selected_key": "B", "answering_turn_id": "turn_9c1d" }
```

服务端据此判断这一轮是否已经答过：

| 情况 | 行为 |
|---|---|
| 该 `turn_id` 没答过 | 正常处理 |
| 该 `turn_id` 已答过 | **原样回放上次结果**，`replayed: true`，不再推进、不再写 Evidence |
| 不传该字段 | 没有这层保护（会当成对下一轮的回答） |
| 传了不认识的 id | 当成没答过，正常处理 |

响应里的 `replayed` 字段告诉你这是不是回放：

```json
{ "tutor_session_id": "tut_5e8f", "replayed": true, "turn": { … }, … }
```

> 幂等键（`Idempotency-Key` / `client_request_id`）与 `answering_turn_id`
> 是**两套互补**的机制，可以同时用：
> 前者保护「同一个 HTTP 请求被重发」，后者保护「同一轮教学被重复作答」。
> 建议两个都带上。

返回 `TutorTurnResponse`：`evaluation` + 下一轮 `turn` + `phase` + `completed` +
`knowledge_changes` + `next_action` + `replayed`。

```json
{
  "tutor_session_id": "tut_5e8f",
  "evaluation": {
    "correctness": "wrong",
    "is_correct": false,
    "chosen_key": "B", "expected_key": "A",
    "feedback": "先别急着看答案。再读一遍题目，想想关键的那一步是什么。",
    "explanation": null,
    "strategy": "simplify",
    "remedial_depth": 1,
    "remedial_exhausted": false
  },
  "turn": {
    "turn_id": "turn_9c1d", "seq": 2,
    "turn_type": "simpler_question",
    "text": "…换一个更简单的问题…",
    "choices": [ { "key": "A", "text": "…" } ],
    "allow_free_text": false,
    "phase": "diagnose",
    "progress": { "step": 1, "total_steps": 5, "percent": 0.2 },
    "completed": false,
    "question_id": "math.derivative.comprehensive.1bd577aaf5",
    "strategy": "simplify",
    "remedial_depth": 1,
    "answer_reveal": null,
    "created_at": "2026-10-02T12:00:00+00:00"
  },
  "phase": "diagnose",
  "completed": false,
  "student_understanding": 0.281,
  "knowledge_changes": [
    { "knowledge_point_id": "math.derivative.monotonicity_applications", "name": "导数与函数性质综合应用",
      "before": 0.4322, "after": 0.3968, "delta": -0.0354, "evidence_count": 13 }
  ],
  "next_action": null
}
```

#### `strategy`：服务端对「下一步怎么教」的决定

客户端只呈现，**不要自己推断**。

| strategy | 含义 | 客户端建议 |
|---|---|---|
| `advance` | 答对了，进入下一步 | 正常推进 |
| `simplify` | **答错 → 换成更简单的问题**（进入或继续补救） | 换个语气，鼓励一下 |
| `hint` | 同一步再试一次，给提示 | 提示样式 |
| `re_explain` | 连续错且没得再降级，重新讲 | 讲解卡片 |
| `reveal_answer` | 补救到上限 → 揭示答案 + 解析 | 展示解析，并允许「下一题」 |
| `finish` | 结束 | 播放总结 |

#### `remedial_depth`：补救层级（0–4）

正式题答错后进入 **补救（remedial）**，最多 **4 层**：

- `0` = 不在补救中
- `1`–`4` = 当前处于第几层补救
- **不存在第 5 层**

| 情形 | 行为 |
|---|---|
| 正式题答错 | 进入补救第 1 层，`strategy: "simplify"`，`turn_type: "simpler_question"` |
| 补救第 1–3 层答错 | 下探一层，`remedial_depth` +1 |
| **任意一层答对** | 结束补救，`remedial_depth` 归 0，回到正常教学/下一正式题流程 |
| **第 4 层仍答错** | 停止继续出题 → `strategy: "reveal_answer"`、`turn.remedial_exhausted: true`，`answer_reveal` 给出答案与解析，并允许进入下一题 |

补救**不计入进度**（`progress.step` 不动）——学生不该因为被补救而显得进度落后。

#### `answer_reveal`：什么时候能看到正确答案

补救期间**绝不**提前泄漏正式题的答案。

| 时刻 | `answer_reveal` |
|---|---|
| 补救第 1–4 层进行中 | `null` |
| 学生**答对**当前题 | `{ current: {…}, origin: null }` |
| **第 4 层仍答错** | `{ current: {…最后一道补救题}, origin: {…触发补救的正式题} }` |

```json
"answer_reveal": {
  "current": { "question_id": "…", "question_text": "…",
               "correct_key": "B", "explanation": "…" },
  "origin":  { "question_id": "…", "question_text": "…",
               "correct_key": "A", "explanation": "…" }
}
```

`origin` 只在补救结束时出现一次。此前客户端**拿不到**它，所以不要在
第 1–3 层就显示「正确答案是 X」。

### 5.2.2 流式返回（打字机效果）

请求体加 `"stream": true`，接口改为返回 `text/event-stream`。

```http
POST /api/v1/tutor/sessions/{session_id}/turns
Content-Type: application/json
Accept: text/event-stream

{ "selected_key": "B", "stream": true }
```

事件顺序固定：**`meta` → `delta`×N → `turn` → `done`**

```
event: meta
data: {"request_id":"3f9a","tutor_session_id":"tut_5e8f","seq":2,
       "phase":"diagnose","turn_type":"simpler_question","remedial_depth":1}

event: delta
data: {"content":"还是不对。我们把这一步再拆细一点"}

event: delta
data: {"content":"（第 1/4 层）。\n\n…"}

event: turn
data: {"turn_id":"turn_9c1d","seq":2,"turn_type":"simpler_question",
       "choices":[{"key":"A","text":"…"}],"strategy":"simplify",
       "remedial_depth":1,"answer_reveal":null,"progress":{…},"completed":false}

event: done
data: {"request_id":"3f9a","seq":2,"phase":"diagnose","completed":false,
       "progress":{"step":1,"total_steps":5,"percent":0.2},
       "student_understanding":0.281}
```

| 事件 | 载荷 | 用途 |
|---|---|---|
| `meta` | `request_id` / `tutor_session_id` / `seq` / `phase` / `turn_type` / `remedial_depth` | 建流、埋点 |
| `delta` | `{ content }` | **只用于自然语言打字机显示** |
| `turn` | 完整的 `TutorTurn` | **权威结构化数据**，所有可交互 UI 都读它 |
| `done` | `seq` / `phase` / `completed` / `progress` / `student_understanding` / **`evaluation`** / **`knowledge_changes`** / **`next_action`** / `replayed` | 收尾。**字段与 JSON 响应完全对齐**，只用流式接口也能拿到完整判定与掌握度变化 |
| `error` | `error_code` / `message` / `request_id` | 流已经开出去之后才发生错误时收尾 |

**给客户端的四条要求：**

1. **不要从 `delta` 的自然语言里解析 `question` / `choices`。**
   所有可交互数据（题目、选项、策略、层级、答案揭示、进度）一律以
   `turn` 事件为准。
2. `delta` 只是渲染便利。以 `turn.text` 覆盖 delta 累积出来的文本。
3. **错误处理分两段**：校验（session 不存在 = 404、已完成 = 409）
   在开流**之前**完成，此时返回的是**普通 JSON 错误体**，不是 SSE。
   只有开流之后才发生的异常才会以 `error` 事件收尾。
   所以客户端要**先看 HTTP 状态码**，非 2xx 时按统一 JSON 错误体解析。
4. 响应头带 `X-Accel-Buffering: no`。若你们前面还有反代，也要关掉缓冲，
   否则流会被攒成一次性输出。

**幂等**：`stream` 与幂等键正交。同一个 `Idempotency-Key` 重放时，
`delta` 会照常重放（前端逻辑统一），但**不会**重复追 turn、也不会重复写 Evidence。
JSON 提交与流式提交共用同一个幂等缓存 —— 先用 JSON、再用同一个 key 走流式，
拿到的是同一个 `turn_id`。

### 5.3 教学轮次类型（决定用什么 Native UI）

**不要按 Markdown 渲染整段文本**，按 `turn_type` 选控件：

| turn_type | 建议 UI |
|---|---|
| `concept_question` | 概念选择题（`choices` 单选 + 「我不确定」） |
| `simpler_question` | 同样式，但语气更简单、标注「换个角度」，可显示第几层补救 |
| `hint` | 提示条 + 同一题的选项 |
| `explanation` | 讲解卡片（`allow_free_text: false`，**无需作答，不会等待提交**） |
| `guided_practice` | 分步引导题 |
| `independent_practice` | 独立练习（强调「这次没有提示」） |
| `summary` | 总结卡片 + 掌握度变化动画 |

> **`turn_type` 永远描述 turn 里真实装的内容。** 补救耗尽时**不会**有
> `remedial_exhausted` 这个类型 —— 那时候会话已经推进到下一题了，
> 所以 `turn_type` 是下一题的类型（`guided_practice` 等），
> 甚至可能直接是 `summary`。
>
> 「要不要叠一张解析卡」看 `turn.remedial_exhausted` /
> `turn.answer_reveal`，**不是**看 `turn_type`：
>
> ```
> 主内容：照 turn_type 渲染（该给选项就给选项）
> 叠加：  if turn.remedial_exhausted { 在下方叠一张 answer_reveal 解析卡 }
> ```


`phase` 取值：`diagnose` → `teach` → `guided_practice` → `independent_practice` → `completed`

**完成时：** `completed: true`，`turn.turn_type == "summary"`，
`knowledge_changes` 里就是 `43% → 51%` 这种变化，直接拿来播动画；
`next_action` 是刷新首页要用的新建议。

### 5.4 读取 Session 状态（断线重连 / 回到页面）

```http
GET /api/v1/tutor/sessions/{session_id}
```

返回与创建时同构的 `TutorSessionResponse`（含完整 `history`）。

---

## 6. 针对性练习

```http
POST /api/v1/practice/sessions
{ "knowledge_point_id": "math.derivative.monotonicity_applications", "difficulty": 0.6, "count": 5 }
```

`knowledge_point_id` 不传时，服务器自动挑最该练的薄弱点。

```json
{
  "practice_session_id": "prac_2b7c",
  "user_id": "user_ab12",
  "knowledge_point_id": "math.derivative.monotonicity_applications",
  "knowledge_point_name": "导数与函数性质综合应用",
  "status": "active",
  "total": 5, "answered": 0, "correct": 0,
  "next_question": {
    "question_id": "math.derivative.comprehensive.fdd405da9c",
    "question_number": "0004",
    "stem": "已知函数 f(x) = x^2 - a·e^x 在 [0, +∞) 上单调递增，则实数 a 的取值范围是（  ）",
    "choices": [
      { "key": "A", "text": "a ≤ 0" }, { "key": "B", "text": "a ≥ 2" },
      { "key": "C", "text": "a ≥ 0" }, { "key": "D", "text": "a ≥ 1" }
    ],
    "difficulty": 1.0,
    "knowledge_points": [ { "knowledge_point_id": "…", "name": "…", "weight": 1.0 } ],
    "index": 1, "total": 5
  },
  "created_at": "..."
}
```

> **`next_question` 里没有 `answer`，也没有 `explanation`。**
> 正确答案只在作答后下发——不要试图在客户端提前判定。

```http
GET  /api/v1/practice/sessions/{session_id}          # 读整组练习的状态与当前题
GET  /api/v1/practice/sessions/{session_id}/next     # 只取下一题
POST /api/v1/practice/sessions/{session_id}/answers
     { "question_id": "math.derivative.comprehensive.fdd405da9c", "selected_key": "C" }
```

`GET .../{session_id}` 返回与创建时同构的会话状态（含 `answered` / `correct` / `next_question`），
适合离开页面后回来时恢复；`/next` 返回单个 `PracticeQuestion`，做完全部题目时返回
`404 NO_QUESTIONS_AVAILABLE`。

作答返回：

```json
{
  "practice_session_id": "prac_2b7c",
  "question_id": "math.derivative.comprehensive.fdd405da9c",
  "correctness": "wrong",
  "is_correct": false,
  "correct_answer": "A",
  "explanation": "…完整解析…",
  "knowledge_changes": [ { "knowledge_point_id": "…", "before": 0.4, "after": 0.37,
                           "delta": -0.03, "evidence_count": 14 } ],
  "next_question": { "…下一题，或者 null…" },
  "session_completed": false,
  "answered": 1, "correct": 0, "total": 5,
  "next_action": null
}
```

### 题目推荐是纯算法

不调用任何大模型，由服务器按四件事打分排序：

1. **难度契合度** —— 掌握度低出简单题，掌握度高出难题
2. **错题重做** —— 做错过且尚未做对的题优先（带冷却时间，避免刚错就重出）
3. **避免重复** —— 近 5 天已做对的题压到后面
4. **错误模式针对性** —— 「分类讨论错误」多的学生，多出含参数分类讨论题

题库是预处理好的静态资源（带知识点与标签），所以推荐结果**可复现、可解释**。

---

## 6.5 标签系统

标签与知识点是**两套独立信号**：知识点决定 `mastery`，标签决定**练习题怎么挑**。
按 `JSON标签与项目设计说明.txt`，题库的 `tags` 是知识点 `name` 的展示层镜像
（当前各 17 个，逐字一致）。

### 6.5.0 `score` 是什么（v2 起）

v1 是「答对 +1 / 答错 −1」的裸计数器，有个致命缺陷：

```
一个标签 5 对 5 错 → 0
一个标签从没练过   → 0        ← 两者无法区分
```

而推荐正是取「分数最低的标签」，于是"练得稀烂"和"完全没碰过"被同等对待。

v2 改成 **Beta 后验 + 悲观下界**：每个标签维护 Beta(α, β)，用与掌握度
**完全相同**的权重更新（对错得分 × 难度 × 来源 × 时间衰减），**从 Evidence 现算**。

```
score = (后验均值 − 一个标准差) × 100        ← 悲观估计
```

一句话：**证据越少，压得越狠。**

| 标签状态 | 均值 | 标准差 | **score** | 排名 |
|---|---|---|---|---|
| 2 对 8 错 | 0.250 | 0.120 | **13** | 最该练 |
| 从没练过 | 0.500 | 0.289 | **21** | 次之（探索）|
| 5 对 5 错 | 0.500 | 0.139 | **36** | 不急 |
| 9 对 1 错 | 0.833 | 0.103 | **73** | 最后 |

> ⚠️ **没练过的标签不是 0，而是 21** —— 那是先验 Beta(1,1) 的悲观下界。
> 0 意味着"确信完全不会"，而我们其实只是"还不知道"。

`score` 仍然是 **0–100 的整数、升序 = 最弱在前**，与 v1 排序方向一致。
计分覆盖三条链路：作业批改（上传）、练习作答、AI Tutor。

### 6.5.1 `GET /api/v1/tags`

该用户全部标签的统计，**按分数升序**（最弱的在前）。

```json
{
  "user_id": "user_ab12",
  "tag_count": 17,
  "weakest":  { "tag": "函数关系式与导数的综合应用", "score": 13,
                "mastery": 0.25, "confidence": 0.62, "attempts": 10 },
  "strongest": { "tag": "利用导数判断函数单调性与单调区间", "score": 73,
                 "mastery": 0.833, "confidence": 0.71, "attempts": 10 },
  "tags": [
    { "tag": "函数关系式与导数的综合应用", "score": 13,
      "mastery": 0.25, "confidence": 0.62, "attempts": 10 },
    { "tag": "切线条数与公切线", "score": 21,
      "mastery": 0.50, "confidence": 0.0, "attempts": 0 },
    { "tag": "利用导数判断函数单调性与单调区间", "score": 73,
      "mastery": 0.833, "confidence": 0.71, "attempts": 10 }
  ]
}
```

| 字段 | 含义 |
|---|---|
| `score` | **推荐用**的悲观估计（0–100），越小越该练 |
| `mastery` | 后验均值（0..1）——「大概掌握到什么程度」，适合做进度条 |
| `confidence` | 对当前估计有多确定（0..1）。全新用户是 0 |
| `attempts` | 累计作答次数 |

### 6.5.2 `GET /api/v1/tags/recommend?count=5`

按标签推荐题目。**客户端不需要自己实现推荐逻辑。**

```json
{
  "user_id": "user_ab12",
  "weakest": { "tag": "函数关系式与导数的综合应用", "score": 13,
               "mastery": 0.25, "confidence": 0.62, "attempts": 10 },
  "recommendations": [
    {
      "tag": "函数关系式与导数的综合应用",
      "tag_score": 13,
      "question_id": "math.derivative.comprehensive.2d662514ec",
      "question_tags": ["基本求导公式与运算法则", "函数关系式与导数的综合应用"],
      "question": { "question_id": "math.derivative.comprehensive.2d662514ec", "question_number": "036", "stem": "…",
                    "choices": [{ "key": "A", "text": "…" }], "tags": ["…"], "index": 1, "total": 1 }
    }
  ]
}
```

- `tag` 是被选中的「分数最低的标签」，`question` 是包含它的题目。
- `question` 里**绝不含 `answer` / `explanation`**。
- 一道题在一次推荐里只会出现一次。

### 6.5.3 推荐算法（多对多的部分）

硬规则是「必须包含分数最低的标签」，但那个标签往往属于多道题，所以还有二级排序：

| 优先级 | 规则 | 说明 |
|---|---|---|
| 1 | **整组题都出自分数最低的那个标签** | 出不满（该标签题量不够）才顺延到下一个标签 —— 这样 `target_tag` 的「本次专练某一标签」才成立 |
| 2 | 该题**所有标签分数之和**升序 | 一题覆盖两个都很弱的标签比只覆盖一个优先；若另一标签已很强，和变大自然靠后 |
| 3 | 最近 5 天做过的题降权 | 不是排除，保证一定有题 |
| 4 | 题号 | 结果可复现 |

纯算术 + 排序，**不调用模型**，微秒级。冷启动（全在先验上）也能出题。

### 6.5.4 练习作答的 `tag_changes`

提交答案（`POST /api/v1/practice/sessions/{id}/answers`）的响应多了一个字段：

```json
"tag_changes": {
  "question_id": "math.derivative.comprehensive.2d662514ec",
  "is_correct": false,
  "tags": ["基本求导公式与运算法则", "函数关系式与导数的综合应用"],
  "tag_scores": { "基本求导公式与运算法则": 34, "函数关系式与导数的综合应用": 12 },
  "tag_deltas": { "基本求导公式与运算法则": -2, "函数关系式与导数的综合应用": -1 }
},
"replayed": false
```

| 字段 | 含义 |
|---|---|
| `tag_scores` | 这些标签**变化后**的分数（0–100） |
| `tag_deltas` | 相对**本次作答前**的变化量（0–100 单位） |

> v1 的 `delta: ±1` 已移除。v2 里标签统计由 Evidence 派生，
> 一次作答带来的变化量取决于该标签已有的证据量与难度，
> 不再是固定的一分 —— 所以拆成了「变化后的值」和「变化量」两个映射，
> 多个标签各自独立。

**可选性（前端 Phase 8A 问的）**：两个字段在 schema 里都是 **`object`、非 required**，
即使为空也**一定存在**（序列化成 `{}`，不会是 `null`、也不会缺席）。

- `tag_scores`：这道题没有任何有效标签时为空对象
- `tag_deltas`：**取不到作答前快照时为空对象** —— 回放（`replayed: true`）
  就是这种情况，因为那时并不发生新的计分

> 前端按 `[String: Int]` 直接解即可，不用处理 optional。
> 但**别**把空对象理解成"标签没变"：回放时它只是没算变化量。

**练习作答的三条保护**（都返回统一错误体）：

| 情况 | 结果 |
|---|---|
| 提交的题不属于本次练习 | `400 QUESTION_NOT_IN_SESSION`，**不写 Evidence** |
| 提交的是本组里还没轮到的那道题 | 同上 |
| 同一题重复提交（网络重试） | `200`，`replayed: true`，原样返回上次结果，**不重复计分** |

最后一题答完后会话即 `completed`；此时对该题的重试仍然走回放（返回 200 而不是 409）。

### 6.5.5 会话里的标签元信息

`POST /api/v1/practice/sessions` **不填 `knowledge_point_id` 时走标签推荐**
（填了则保持原来的知识点内选题）：

```json
{
  "practice_session_id": "prac_…",
  "selection_mode": "tag",
  "target_tag": "函数关系式与导数的综合应用",
  "target_tag_score": -3,
  "picked_tags": ["函数关系式与导数的综合应用", "切线条数与公切线"],
  "next_question": { "…": "…" }
}
```

`selection_mode` 为 `"knowledge_point"` 时上面前三个字段为 `null` / 空数组，
客户端可以直接用 `target_tag` 显示「本次专练：XXX」。

---

## 7. 标准 AI 直连接口（前端「跟踪训练」用）

最简单形态：**发一个问题，拿回一个回答。**

```http
POST /api/v1/ai/chat
{ "prompt": "为什么 f'(x) > 0 说明函数单调递增？" }
```

```json
{
  "reply": "因为导数 f'(x) 表示函数在某点的瞬时变化率……",
  "model": "deepseek-ai/DeepSeek-V3.2",
  "provider": "siliconflow",
  "latency_ms": 3509,
  "request_id": "927af55804b54db5",
  "usage": { "prompt_tokens": 22, "completion_tokens": 44, "total_tokens": 66 }
}
```

多轮对话：

```json
{
  "system": "你是一位高中数学老师，用启发式提问引导学生。",
  "messages": [
    { "role": "user", "content": "什么是导数？" },
    { "role": "assistant", "content": "导数描述变化率。" },
    { "role": "user", "content": "举个例子" }
  ],
  "temperature": 0.6,
  "max_tokens": 1024,
  "model": null,
  "json_mode": false,
  "stream": false
}
```

> `prompt` 与 `messages` 二选一；同时存在时 `messages` 优先。
> 这个接口**不做教学状态管理**，需要状态请用 `/tutor/sessions`。

### 7.1 流式输出（打字机效果）

同一个接口，请求体加 `"stream": true`，响应就从一次性 JSON 变成 **SSE**
（`Content-Type: text/event-stream`）。**不传 `stream` 时行为与旧版完全一致**，
老客户端不用改。

```http
POST /api/v1/ai/chat
{ "prompt": "为什么 f'(x) > 0 说明函数单调递增？", "stream": true }
```

事件序列固定为 **`meta` → `delta`(0..n) → `done`**，中途失败则以 **`error`** 收尾：

```text
event: meta
data: {"request_id": "927af55804b54db5", "model": "deepseek-ai/DeepSeek-V3.2", "provider": "siliconflow"}

event: delta
data: {"content": "因为导数"}

event: delta
data: {"content": " f'(x) 表示"}

event: done
data: {"reply": "因为导数 f'(x) 表示……", "model": "deepseek-ai/DeepSeek-V3.2", "provider": "siliconflow",
       "latency_ms": 3509, "first_token_ms": 320, "request_id": "927af55804b54db5",
       "usage": {"prompt_tokens": 22, "completion_tokens": 44, "total_tokens": 66}}
```

| 事件 | 载荷 | 说明 |
|---|---|---|
| `meta` | `request_id` / `model` / `provider` | 开流第一帧，可先渲染模型标识 |
| `delta` | `content` | **增量**片段，直接追加到已显示文本后面 |
| `done` | `reply` / `latency_ms` / `first_token_ms` / `usage` | 收尾。`reply` 是完整文本，可用它校正拼接结果 |
| `error` | `error_code` / `message` / `request_id` | 开流之后模型才失败时发出，**这是流的最后一帧** |

客户端要点：

1. **增量是"增量"不是"全量"。** `delta.content` 只包含本次新增的片段，
   追加拼接即可；不要用它覆盖已渲染内容。
2. **`done.reply` 是权威全文。** 若担心丢帧（弱网、切后台），收尾时用
   `reply` 覆盖一次，保证与一次性接口结果一致。
3. **`error` 事件是正常的流式收尾，不是网络错误。** 收到后停止渲染、
   按 `error_code` 分支（与 §0 的统一错误码一致）。因为响应头已经以 200 发出，
   这种情况下**不会有** 4xx/5xx 状态码。
4. **参数校验失败仍返回 422 JSON**（不是 SSE）——校验发生在开流之前，
   所以 `prompt` 为空这类问题拿到的还是标准错误体。
5. `usage` 需要 provider 支持 `stream_options.include_usage`；不支持时为 `null`，
   不要据此判定失败。
6. 若前面挂了 nginx，必须关掉响应缓冲（服务端已下发 `X-Accel-Buffering: no`），
   否则流会被攒成一次性输出。

> 模型不可用时，非流式接口会按 `LLM_FALLBACK_TO_MOCK` 降级成兜底文案；
> **流式开流之后无法再降级**（响应头已发出），此时以 `error` 事件收尾。
> 若后端未配置模型，流式也会回兜底文案，但同样走 SSE，
> 前端只需维护一套渲染逻辑。

`GET /api/v1/ai/models` 返回服务端当前配置的模型 id。

---

## 8. 图书 / 题库权限 / 订阅

```http
GET /api/v1/books
```

```json
{ "total": 2, "items": [
  { "book_id": "book.derivative.basic", "title": "高中数学·导数基础训练",
    "publisher": "好学教研组", "cover_url": null, "price_cents": 0,
    "question_count": 22, "owned": true }
] }
```

```http
GET  /api/v1/books/{book_id}
POST /api/v1/books/{book_id}/redeem     { "serial_number": "HAOXUE-ADVD-0002" }
GET  /api/v1/entitlements
```

Demo 可用的兑换码（`POST /books/book.derivative.advanced/redeem`）：

| 图书 | 序列号 |
|---|---|
| 导数基础训练 | `HAOXUE-DERI-0001`（默认已拥有） |
| 导数综合应用 | `HAOXUE-ADVD-0002` |

通用序列号必须严格符合 `HAOXUE-XXXX-XXXX-XXXX`（`[A-Z0-9]{4}` × 3 段），
否则返回 `400 INVALID_SERIAL_NUMBER`。

**一个序列号只能兑换一本书**：

| 情况 | 结果 |
|---|---|
| 该序列号已被**其他用户**用过 | `400 INVALID_SERIAL_NUMBER` |
| 自己用同一个序列号**重复兑换同一本书** | `200`，`entitled: true`，回「你之前已经兑换过这本书了」 |
| 自己用同一个序列号兑换**另一本书** | `400 INVALID_SERIAL_NUMBER`，且**不会真的授予**那本书 |

最后一条是刻意的：早期实现会说「你已拥有 B」，但库里其实只有 A，
用户以为 B 到手了 —— 接口撒谎比报错严重得多。

订阅信息目前是假数据（`¥20/月`），**不接真实支付**。

---

## 9. Demo 辅助接口（演示前调一次）

```http
POST /api/v1/demo/seed        # 铺开学习历史，把「导数与函数性质综合应用」压到 43% 附近
POST /api/v1/demo/reset       # 清空该用户学习数据
GET  /api/v1/demo/status      # 当前数据概览
```

`POST /demo/seed` 会写入 103 条历史 Evidence：

| 知识点 | 掌握度 |
|---|---|
| 利用导数判断函数单调性与单调区间 | **83%** |
| 基本求导公式与运算法则 | **77%** |
| 导数的几何意义与瞬时变化率 | **74%** |
| 利用导数求函数最值 | **72%** |
| 利用单调性或导数恒成立求参数 | **69%** |
| 函数奇偶性与单调性综合判断 | **68%** |
| 导数定义与极限 | **67%** |
| 切线斜率与倾斜角 | **64%** |
| 利用导数判断与求解极值 | **62%** |
| 函数关系式与导数的综合应用 | **62%** |
| 切线的平行与垂直关系 | **61%** |
| 曲线切线方程 | **53%** |
| 根据极值或最值条件求参数 | **51%** |
| 切线条数与公切线 | **50%** |
| 切线相关的最值问题 | **44%** |
| 奇偶性、对称性与周期性中的导数关系 | **44%** |
| **导数与函数性质综合应用** | **43%** ← Demo 主线 |

> 证据时间戳是相对播种时刻计算的，所以**每次演示前重新 seed 一次**，
> 时间轴就会刷新到"最近"，趋势判断也更符合现场叙事。

---

## 10. 完整 Demo 流程（客户端调用顺序）

```
① GET  /api/v1/demo/seed                     （演示前准备）
② GET  /api/v1/home                          → 「下一步：导数与函数性质综合应用」
③ POST /api/v1/homework/analyses             （上传试卷图片）→ analysis_id
④ GET  /api/v1/homework/analyses/{id}        （轮询，卡片显示 5 步进度）
   └─ completed：错 1 题、错题入库、knowledge_changes 已产生
⑤ GET  /api/v1/wrong-questions/{wq_id}       → 原题 / 学生答案 / 正确答案 / 诊断
⑥ GET  /api/v1/knowledge/{kp_id}             → 43% + 错误模式 + Evidence
⑦ POST /api/v1/tutor/sessions                （source_type=knowledge_point）
⑧ POST /api/v1/tutor/sessions/{id}/turns     （学生故意答错）
   └─ strategy=simplify，turn_type=simpler_question   ← Agent 改变教学策略
⑨ …继续作答直到 completed=true
   └─ turn_type=summary，knowledge_changes: 43% → 51%   ← 播放动画
⑩ GET  /api/v1/home                          → Next Action 已变化，闭环完成
```

---

## 11. 工程约定（请遵守）

1. **不要自己算掌握度。** 所有百分比都从服务器拿。
2. **不要依赖 `message` 文案**，用 `error_code`。
3. **写操作带 `Idempotency-Key`。** 手机网络不稳，重试很常见。
4. **知识点 id 是稳定契约**（如 `math.derivative.monotonicity`），可以写死在客户端。
5. 图片 URL 是完整绝对地址，可直接加载。
6. 时间统一为 ISO-8601 UTC（带 `+00:00`），客户端自行转本地时区。
7. 接口版本在路径里（`/api/v1`），后续迭代不会破坏旧客户端。
