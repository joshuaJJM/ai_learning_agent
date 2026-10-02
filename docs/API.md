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
| `UNAUTHORIZED` | 401 | token 无效/过期 |
| `SESSION_EXPIRED` | 401 | 会话过期 |
| `BOOK_NOT_OWNED` | 403 | 未拥有该题库 |
| `ANALYSIS_NOT_FOUND` | 404 | 分析任务不存在 |
| `SESSION_NOT_FOUND` | 404 | Tutor/练习 Session 不存在 |
| `KNOWLEDGE_POINT_NOT_FOUND` | 404 | 知识点 id 不存在 |
| `WRONG_QUESTION_NOT_FOUND` | 404 | 错题不存在 |
| `BOOK_NOT_FOUND` | 404 | 图书不存在 |
| `NO_QUESTIONS_AVAILABLE` | 404 | 该组题已做完 |
| `INVALID_IMAGE` | 400 | 图片为空/过大/类型不支持 |
| `INVALID_SERIAL_NUMBER` | 400 | 序列号无效或已被使用 |
| `SESSION_COMPLETED` | 409 | Session 已结束，不能再作答 |
| `IDEMPOTENCY_CONFLICT` | 409 | 幂等键冲突 |
| `QUESTION_NOT_RECOGNIZED` | 422 | 没识别出题目 |
| `VALIDATION_ERROR` | 422 | 请求参数不合法 |
| `VLM_TIMEOUT` | 504 | 视觉模型超时 |
| `INTERNAL_ERROR` | 500 | 服务端异常 |

### 幂等（重要）

所有**会改变数据**的写接口都支持重复提交保护：

- 推荐：任意请求带 `Idempotency-Key: <客户端生成的 uuid>` 请求头
- 或：请求体/表单里带 `client_request_id`

不带幂等键时，手机断网重试会**把掌握度更新两次**。

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
      "source_type": "exam", "question_id": null }
  ],
  "error_patterns": [
    { "error_type": "case_analysis",  "label": "分类讨论错误",       "count": 3, "share": 0.375 },
    { "error_type": "transformation", "label": "函数性质转换错误",   "count": 3, "share": 0.375 },
    { "error_type": "domain_omission","label": "定义域遗漏",         "count": 2, "share": 0.25 }
  ],
  "evidence": [
    { "evidence_id": "ev_1", "knowledge_point_id": "…", "source_type": "exam",
      "question_id": null, "result": "incorrect", "confidence": 1.0,
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
  "client_request_id": "<可选幂等键>" }
```

- 选择题传 `selected_key`（`"A"`~`"D"`）
- 开放题传 `text`
- 「我不确定」传 `self_reported_confidence: "unsure"`

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
    "strategy": "simplify"
  },
  "turn": {
    "turn_type": "simpler_question",
    "text": "…换一个更简单的问题…",
    "choices": [ "…" ],
    "phase": "diagnose",
    "progress": { "step": 1, "total_steps": 5, "percent": 0.2 }
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

`strategy` 说明 Agent 为什么这样走：

| strategy | 含义 | 客户端建议 |
|---|---|---|
| `advance` | 答对了，进入下一步 | 正常推进 |
| `simplify` | **答错 → 换成更简单的问题** | 换个语气，鼓励一下 |
| `hint` | 同一步再试一次，给提示 | 提示样式 |
| `re_explain` | 连续错，重新讲 | 讲解卡片 |
| `finish` | 结束 | 播放总结 |

### 5.3 教学轮次类型（决定用什么 Native UI）

**不要按 Markdown 渲染整段文本**，按 `turn_type` 选控件：

| turn_type | 建议 UI |
|---|---|
| `concept_question` | 概念选择题（`choices` 单选 + 「我不确定」） |
| `simpler_question` | 同样式，但语气更简单、标注「换个角度」 |
| `hint` | 提示条 + 同一题的选项 |
| `explanation` | 讲解卡片（`allow_free_text: false`，**无需作答，不会等待提交**） |
| `guided_practice` | 分步引导题 |
| `independent_practice` | 独立练习（强调「这次没有提示」） |
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
    "question_id": "math.derivative.monotonicity_applications.0004",
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
     { "question_id": "math.derivative.monotonicity_applications.0004", "selected_key": "C" }
```

`GET .../{session_id}` 返回与创建时同构的会话状态（含 `answered` / `correct` / `next_question`），
适合离开页面后回来时恢复；`/next` 返回单个 `PracticeQuestion`，做完全部题目时返回
`404 NO_QUESTIONS_AVAILABLE`。

作答返回：

```json
{
  "practice_session_id": "prac_2b7c",
  "question_id": "math.derivative.monotonicity_applications.0004",
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
  "json_mode": false
}
```

> `prompt` 与 `messages` 二选一；同时存在时 `messages` 优先。
> 这个接口**不做教学状态管理**，需要状态请用 `/tutor/sessions`。

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
