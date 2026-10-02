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
                         # 返回 status / llm_mode / 题库题数 / 运行时长
```

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
| `INVALID_IMAGE` | 400 | 图片为空 / 过大 / 不是图片 |
| `INVALID_SERIAL_NUMBER` | 400 | 序列号无效、格式不对，或已用于兑换其他书 |
| `QUESTION_NOT_IN_SESSION` | 400 | 提交的题不是当前练习的当前这一题 |
| `UNAUTHORIZED` | 401 | 未认证，或 token 无效 |
| `ANALYSIS_NOT_FOUND` | 404 | 分析任务不存在 |
| `BOOK_NOT_FOUND` | 404 | 图书不存在 |
| `KNOWLEDGE_POINT_NOT_FOUND` | 404 | 知识点 id 不存在 |
| `NOT_FOUND` | 404 | 目标资源不存在 |
| `NO_QUESTIONS_AVAILABLE` | 404 | 这一组题已经做完了 |
| `SESSION_NOT_FOUND` | 404 | Tutor / 练习 Session 不存在 |
| `WRONG_QUESTION_NOT_FOUND` | 404 | 错题不存在 |
| `IDEMPOTENCY_CONFLICT` | 409 | 同一个幂等键的请求正在处理中，稍后重试 |
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

- `state`: `done` | `active` | `pending` | `failed`
  - 分析失败时，**出错的那一步是 `failed`（不是 `active`）**，前端可以据此在卡片上
    标出「就是这一步失败的」。例如图里识别不出题目时：
    `image_received: done` / `questions_detected: failed` / 其余 `pending`，
    同时 `error.error_code = "QUESTION_NOT_RECOGNIZED"`。
  - 模型不可用（`VLM_TIMEOUT`）失败点同样落在 `questions_detected`。
- **多张图片是并行识别的**，所以耗时取决于最慢的那一张，不是页数之和。
  实测 1 张约 21 秒、3 张同样约 21 秒。并发上限 4（打满模型配额反而会被限流）。
- 建议轮询间隔 1 秒；`status` 变为 `completed` / `failed` 即停止
- 模型偶尔会返回不合法的 JSON（最常见的是在中文正文里把引号打成了 ASCII 的 `"`，
  导致字符串提前闭合）。服务端会自动修复，修不好就重试，
  **主模型 5 次、备选模型 5 次**，所以偶发的坏输出不会让整单失败。

**完成后**（同结构，追加结果字段）：

```json
{
  "status": "completed",
  "progress": { "percent": 1.0, "current_stage": "Completed", "stages": [ "…全部 done…" ] },
  "homework_id": "hw_7c1d",
  "correct_count": 0, "wrong_count": 1, "partial_count": 0, "unknown_count": 0,

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

### 2.3 关于「AI 会不会教错」

服务端有一套**二次校验**机制，你可以放心展示：

- 题干能匹配到题库 → 直接采用**题库里经过人工验算的答案**；
- 匹配不到 → 再用另一个模型独立求解一遍，**两次答案一致才采信**；
- 两次不一致 → 该题 `correctness` 返回 `"unknown"`，`correct_answer` 为 `null`，
  并在 `warnings` 里说明，**且不计入掌握度统计**。

所以学生可能看到极少数 `unknown` 的题，UI 建议显示成「AI 无法确认本题答案，未计入统计」。
这是刻意设计的保守行为，不是 bug。

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
      "status": "open", "created_at": "2026-10-01T21:30:00+00:00" }
  ]
}
```

```http
GET /api/v1/wrong-questions/{wrong_question_id}
```

在列表字段基础上追加：`question_type`、`choices`、`student_answer`、`correct_answer`、
`explanation`、`correctness`、`diagnosis`、`image_url`、`source_type`、`source_id`、
`source_name`、`favorite`、`updated_at`、`can_start_tutor`。

> 详情页的 **Start Learning** 按钮：
> `POST /api/v1/tutor/sessions` + `{"source_type": "wrong_question", "wrong_question_id": "wq_1a2b"}`

```http
PATCH /api/v1/wrong-questions/{wrong_question_id}
{ "status": "resolved", "favorite": true }
```

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
  "client_request_id": "<可选幂等键>", "stream": false }
```

- 选择题传 `selected_key`（`"A"`~`"D"`）
- 开放题传 `text`
- 「我不确定」传 `self_reported_confidence: "unsure"`
- `stream: true` → 返回 SSE（见 §5.2.2）；缺省或 `false` → 维持下面的 JSON 契约

返回 `TutorTurnResponse`：`evaluation` + 下一轮 `turn` + `phase` + `completed` +
`knowledge_changes` + `next_action`。

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
| **第 4 层仍答错** | 停止继续出题 → `turn_type: "remedial_exhausted"`、`strategy: "reveal_answer"`，`answer_reveal` 给出答案与解析，并允许进入下一题 |

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
| `done` | `seq` / `phase` / `completed` / `progress` / `student_understanding` | 收尾 |
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
| `remedial_exhausted` | **补救到上限**：展示 `answer_reveal` 的解析卡片 + 「下一题」按钮 |
| `summary` | 总结卡片 + 掌握度变化动画 |


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

规则：

1. 每个用户的每个标签初始为 **0**。
2. 每答一道题：**答对 → 该题所有标签 +1；答错 → −1**。
   `correctness=unknown`（两个模型对答案有分歧）时**不动标签**。
3. 推荐时把所有标签**从小到大排序**，返回**包含分数最低那个标签**的题目。

计分覆盖三条链路：作业批改（上传）、练习作答、AI Tutor。

### 6.5.1 `GET /api/v1/tags`

该用户全部标签的分数，**按分数升序**（最弱的在前）。首次访问会把全部标签以 0 分建档。

```json
{
  "user_id": "user_ab12",
  "tag_count": 17,
  "weakest":  { "tag": "函数关系式与导数的综合应用", "score": -3 },
  "strongest": { "tag": "利用导数判断函数单调性与单调区间", "score": 4 },
  "tags": [
    { "tag": "函数关系式与导数的综合应用", "score": -3 },
    { "tag": "切线条数与公切线", "score": -1 },
    { "tag": "利用导数求函数最值", "score": 0 },
    { "tag": "利用导数判断函数单调性与单调区间", "score": 4 }
  ]
}
```

### 6.5.2 `GET /api/v1/tags/recommend?count=5`

按标签推荐题目。**客户端不需要自己实现推荐逻辑。**

```json
{
  "user_id": "user_ab12",
  "weakest": { "tag": "函数关系式与导数的综合应用", "score": -3 },
  "recommendations": [
    {
      "tag": "函数关系式与导数的综合应用",
      "tag_score": -3,
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
| 2 | 该题**所有标签分数之和**升序 | 一题覆盖两个都很弱的标签（−3、−3 → −6）比只覆盖一个（−3）优先；若另一标签已很强（+10），和变大自然靠后 |
| 3 | 最近 5 天做过的题降权 | 不是排除，保证一定有题 |
| 4 | 题号 | 结果可复现 |

纯算术 + 排序，**不调用模型**，微秒级。冷启动（全 0）也能出题。

### 6.5.4 练习作答的 `tag_changes`

提交答案（`POST /api/v1/practice/sessions/{id}/answers`）的响应多了一个字段：

```json
"tag_changes": {
  "question_id": "math.derivative.comprehensive.2d662514ec",
  "is_correct": false,
  "delta": -1,
  "tags": ["基本求导公式与运算法则", "函数关系式与导数的综合应用"]
},
"replayed": false
```

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
