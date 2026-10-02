# 上传接口使用说明

> `POST /api/v1/homework/analyses` —— 把拍到的作业/试卷图片交给服务端分析。
>
> 这是整个系统里**唯一需要实时 AI** 的接口。题库、知识点、推荐都是预处理好的静态数据。

---

## 1. 它做什么

你上传一组图片，服务端异步完成：

```
接收图片 → VLM 识别题目与作答 → 判定对错 → 知识点映射 → 错误归因
        → 写入 Evidence → 更新掌握度 → 错题入库 → 给出下一步建议
```

**前端不需要声明"这是作业"还是"这是一道不会的题"** —— 服务端按图片内容自己判断，
一次上传里也可以混着两种。

接口是**异步**的：立刻返回一个 `analysis_id`，然后用它轮询进度和结果。
这样客户端不会卡在上传页，可以做成一张持续追踪的进度卡片。

---

## 2. 请求

```http
POST /api/v1/homework/analyses
Content-Type: multipart/form-data
Authorization: Bearer <token>      # 可省略，省略时用 Demo 用户
Idempotency-Key: <客户端生成的 uuid，强烈建议>
```

### 表单字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `images` | file | ✅ | 图片。**字段名固定为 `images`**，多张图就重复这个字段名 |
| `subject` | text | | 默认 `mathematics` |
| `topic` | text | | 如 `derivative` |
| `book_id` | text | | 来源图书 id |
| `source_name` | text | | 给人看的来源描述，如「某作业本第 32 页」 |
| `client_request_id` | text | | 幂等键的备用写法（也可以走请求头） |

### 图片要求

| 项 | 要求 |
|---|---|
| 数量 | 1 张起，可多张。**多张是并行分析的**，总耗时≈最慢的那张 |
| 大小 | 单张 ≤ 12 MB |
| 格式 | JPEG / PNG / HEIC / WebP / GIF / BMP |
| 判断依据 | **只看文件头（魔数）**，不看 `Content-Type`，也不看文件扩展名 |

关于最后一条，有两个刻意的行为：

- **`Content-Type: application/octet-stream` + `filename="photo"`（无扩展名）也能正常上传。**
  这是 `URLSession` 手工拼 multipart 时的默认样子，不该因此被拒。
- 反过来，**声明成 `image/png` 但字节不是图片的，会被拒绝**（`INVALID_IMAGE`）。

> ⚠️ **每个文件部分必须带 `filename`。**
> `Content-Disposition: form-data; name="images"; filename="page1.jpg"`
> 如果漏了 `filename=`，服务端会把它当普通文本字段解析，二进制内容会被破坏，
> 无法还原成图片。任何标准的 multipart 构造方式默认都会带上它。

---

## 3. 最小可运行示例

### curl

```bash
curl -X POST http://121.43.137.176:17283/api/v1/homework/analyses \
  -H "Idempotency-Key: $(uuidgen)" \
  -F 'images=@page1.jpg' \
  -F 'images=@page2.jpg' \
  -F 'subject=mathematics' \
  -F 'source_name=数学月考'
```

### Swift（URLSession 手工拼 multipart）

```swift
func uploadPages(_ images: [UIImage]) async throws -> AnalysisCreated {
    let boundary = "Boundary-\(UUID().uuidString)"
    var request = URLRequest(url: URL(string: "http://121.43.137.176:17283/api/v1/homework/analyses")!)
    request.httpMethod = "POST"
    request.setValue("multipart/form-data; boundary=\(boundary)",
                     forHTTPHeaderField: "Content-Type")
    // 断网重试不会把掌握度更新两次
    request.setValue(UUID().uuidString, forHTTPHeaderField: "Idempotency-Key")

    var body = Data()
    for (index, image) in images.enumerated() {
        guard let data = image.jpegData(compressionQuality: 0.8) else { continue }
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        // ⚠️ filename 必须写，扩展名写不写都可以
        body.append("Content-Disposition: form-data; name=\"images\"; filename=\"page\(index).jpg\"\r\n"
            .data(using: .utf8)!)
        body.append("Content-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n".data(using: .utf8)!)
    }
    body.append("--\(boundary)--\r\n".data(using: .utf8)!)

    let (responseData, response) = try await URLSession.shared.upload(for: request, from: body)
    guard let http = response as? HTTPURLResponse, http.statusCode == 202 else {
        throw APIError.upload(responseData)
    }
    return try JSONDecoder.api.decode(AnalysisCreated.self, from: responseData)
}
```

> `URLSession` 默认给文件部分填 `application/octet-stream`，这没关系 ——
> 服务端只看字节。

---

## 4. 拿结果：先 202，再轮询

### 4.1 创建成功 → `202 Accepted`

```json
{
  "analysis_id": "ana_9b16554eaa3e40f7b959",
  "status": "queued",
  "created_at": "2026-10-02T11:30:00+00:00"
}
```

| status | 含义 |
|---|---|
| `queued` | 已入队，还没开始 |
| `processing` | 正在跑 |
| `completed` | 完成 |
| `failed` | 失败，看 `error` |

### 4.2 轮询进度 → `GET /api/v1/homework/analyses/{analysis_id}`

**建议 1 秒一次**，`status` 变成 `completed` / `failed` 就停。实测单张约 21 秒，
3 张并行也是约 21 秒。

```json
{
  "analysis_id": "ana_9b16554eaa3e40f7b959",
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
  "created_at": "...",
  "updated_at": "..."
}
```

进度卡片直接渲染 `stages` 就够了：`state` 是 `done` / `active` / `pending` / `failed`，
`percent` 驱动进度条，`current_stage_label_zh` 是当前阶段的中文文案。

> 分析失败时，**出错的那一步会是 `failed`（不是 `active`）**，
> 前端可以据此在卡片上标出「就是这一步失败的」。
> 比如图里没有题目时：`image_received: done`、`questions_detected: failed`、其余 `pending`，
> 同时 `error.error_code = "QUESTION_NOT_RECOGNIZED"`。
> 模型不可用（`VLM_TIMEOUT`）时失败点同样在 `questions_detected`。

### 4.3 完成

同一个 URL，`status: "completed"`，并追加结果字段：

```json
{
  "status": "completed",
  "progress": { "percent": 1.0, "stages": ["……5 个阶段全部 done……"] },

  "homework_id": "hw_7c1d",
  "image_count": 2,

  "correct_count": 1,
  "wrong_count": 1,
  "partial_count": 0,
  "unknown_count": 0,

  "questions": ["q_6942b731", "q_7a11c9e0"],
  "question_results": [
    {
      "question_id": "q_6942b731",
      "question_number": "17",
      "question_type": "single_choice",
      "question_content": "已知函数 f(x) = x^3 - 3x^2 + 2，求 f(x) 的单调递增区间。",
      "choices": { "A": "(-inf, 0)", "B": "(0, 2)", "C": "(-inf, 0) 和 (2, +inf)", "D": "(2, +inf)" },
      "student_answer": "A",
      "correct_answer": "C",
      "correctness": "wrong",
      "knowledge_points": [
        { "knowledge_point_id": "math.derivative.monotonicity", "name": "利用导数判断函数单调性与单调区间", "weight": 1.0 }
      ],
      "error_type": "transformation",
      "error_label": "函数性质转换错误",
      "diagnosis": "学生能正确求导，但把导数符号与单调性的对应关系弄反了。",
      "explanation": "f'(x) = 3x^2 - 6x = 3x(x-2)，令 f'(x) > 0 得 x < 0 或 x > 2……",
      "confidence": 0.97,
      "difficulty": 0.5,
      "image_url": "http://121.43.137.176:17283/media/ana_9b16554e/0.png"
    }
  ],

  "knowledge_changes": [
    { "knowledge_point_id": "math.derivative.monotonicity", "name": "利用导数判断函数单调性与单调区间",
      "before": 0.618, "after": 0.5744, "delta": -0.0436, "evidence_count": 8 }
  ],
  "new_wrong_questions": [
    { "wrong_question_id": "wq_1a2b", "question_id": "q_6942b731", "question_number": "17",
      "question_content": "……", "knowledge_point_id": "…", "knowledge_point_name": "…",
      "error_type": "transformation", "error_label": "函数性质转换错误",
      "status": "open", "created_at": "…" }
  ],
  "next_action": { "action": "start_tutor", "title": "下一步：导数与函数性质综合应用", "cta_label": "开始学习", "…": "…" },
  "warnings": [],
  "generated_by": "vlm",
  "error": null
}
```

字段要点：

- `questions` 只是题目 id 列表；完整对象在 `question_results` 里，**别混淆**。
- `correctness` 取值：`correct` / `wrong` / `partial` / `unknown`。
- `knowledge_points[].weight` 是这道题对该知识点的相关度，不必展示，但决定了它对掌握度的影响。
- `explanation` 是完整解析，`diagnosis` 是"学生错在哪"的一句话。
- `image_url` 是可直接加载的绝对地址，错题详情页可以用。
- `new_wrong_questions` 可以直接拿去刷错题列表，不用再请求一次。
- `next_action` 与首页的 `next_action` 同构，可以顺势刷新首页。

---

## 5. 关于 `unknown`：这是刻意的，不是 bug

视觉模型**会在数学上出错**。实测中它把 `f'(x) = 3x(x−2) > 0` 的解判成了 `(0, 2)`，
而正确答案是 `x < 0 或 x > 2`。对教育产品来说，教错答案比功能缺失严重得多。

所以服务端对每个答案都做二次确认：

1. 题干能匹配题库 → 直接用**题库里人工验算过的答案**；
2. 匹配不到 → 用**另一个模型独立求解一遍**，两次一致才采信；
3. 两次不一致 → 该题 `correctness` 返回 `"unknown"`、`correct_answer` 为 `null`，
   **并且不计入掌握度统计**，同时在 `warnings` 里说明原因。

客户端遇到 `unknown` 建议显示成「AI 无法确认本题答案，未计入统计」。
这是保守但正确的行为。

---

## 6. 错误处理

统一错误格式：

```json
{
  "error_code": "INVALID_IMAGE",
  "message": "图片过大：15 MB，上限 12 MB",
  "request_id": "927af55804b54db5"
}
```

**只根据 `error_code` 做分支，不要解析 `message` 文案。** 上传相关的错误码：

| error_code | HTTP | 含义 | 客户端怎么办 |
|---|---|---|---|
| `INVALID_IMAGE` | 400 | 图片为空 / 过大 / 不是图片 / 缺 `images` 字段 | 提示用户重新选择 |
| `ANALYSIS_NOT_FOUND` | 404 | `analysis_id` 不存在 | 回到上传页重来 |
| `UNAUTHORIZED` | 401 | token 无效 | 重新取 token |
| `VLM_TIMEOUT` | 504（在 `analysis.error` 里） | 模型不可用 | 提示稍后重试 |
| `QUESTION_NOT_RECOGNIZED` | 422（在 `analysis.error` 里） | 图里没识别出题目 | 提示换张更清晰的照片 |
| `VALIDATION_ERROR` | 422 | 请求参数不合法 | 检查 multipart 格式 |

注意后两个不是 HTTP 请求的错误，而是**分析任务失败** —— 它们出现在轮询结果的
`status: "failed"` 时的 `error` 字段里。

### 常见坑

| 现象 | 原因 |
|---|---|
| 404，路径变成 `/api/v1/demo/seed/v1/models` 之类 | **Base URL 写错了。** Base URL 只能是 `http://121.43.137.176:17283`，不要填成某个具体接口的地址 |
| 422 `VALIDATION_ERROR` | multipart 文件部分漏了 `filename=` |
| 400 `INVALID_IMAGE` | 上传的确实不是图片（服务端按文件头判断） |
| 轮询一直 `failed` + `VLM_TIMEOUT` | 模型侧问题，可让后端看日志 |

---

## 7. 客户端实现建议

1. **不要把上传做成阻塞式。** 立刻拿到 `analysis_id` 就返回上一页，
   用一张卡片显示 5 个阶段的进度，完成后再跳转结果页。
2. **轮询 1 秒一次**足够；不必用 WebSocket。请求很轻（就是读一条本地记录）。
3. **每张图控制在 2 MB 以内**。12 MB 是硬上限，但压缩后上传更快、识别也更稳。
   用 `UIImage.jpegData(compressionQuality: 0.8)` 通常够。
4. **带 `Idempotency-Key`。** 手机网络不稳，重试很常见；不带的话一次重试会让
   掌握度被更新两次。
5. 上传前可以本地做页面检测/透视矫正/裁剪 —— 这些端侧做更快，服务端也能得到更干净的输入。
   但**不需要在端侧做 OCR 或题目理解**，那是服务端的事。
6. 支持「上传更多」而不是「重新扫描」：多张图属于同一次分析，一起提交。

---

## 8. 相关接口

| 用途 | 接口 |
|---|---|
| 拿 `analysis_id` | `POST /api/v1/homework/analyses` |
| 轮询进度与结果 | `GET /api/v1/homework/analyses/{analysis_id}` |
| 历史分析列表 | `GET /api/v1/homework/analyses` |
| 错题详情 | `GET /api/v1/wrong-questions/{wrong_question_id}` |
| 错题列表 | `GET /api/v1/wrong-questions` |
| 知识点详情（「为什么是 43%」） | `GET /api/v1/knowledge/{knowledge_point_id}` |
| 从错题开始学习 | `POST /api/v1/tutor/sessions` |

完整契约见 [API.md](API.md)，交互式调试见 <http://121.43.137.176:17283/docs>。
