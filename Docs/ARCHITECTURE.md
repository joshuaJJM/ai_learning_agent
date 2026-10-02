# 好学 — ARCHITECTURE

## 1. 架构总览

```text
┌──────────────────────────────┐
│          iOS App             │
│ SwiftUI / VisionKit / Pencil │
└──────────────┬───────────────┘
               │ HTTPS
               ▼
┌──────────────────────────────┐
│        FastAPI Backend       │
│                              │
│ Upload / Analysis            │
│ Knowledge State              │
│ Wrong Questions              │
│ Tutor / Practice             │
│ Library / Entitlement        │
└──────────────┬───────────────┘
               │
      ┌────────┴─────────┐
      ▼                  ▼
┌────────────┐     ┌─────────────┐
│ Database   │     │ VLM / LLM   │
└────────────┘     └─────────────┘
```

## 2. Source of Truth

比赛版采用：

> **Backend = Source of Truth**

服务器维护长期学习状态。

iOS 仅保留：

- 当前页面 UI 状态；
- 临时图片；
- 必要网络缓存；
- PencilKit 当前草稿；
- 本地系统能力配置。

前端不得自行修改服务器权威掌握度。

---

## 3. iOS 模块建议

```text
ios/
├── App/
├── Core/
│   ├── Networking/
│   ├── Models/
│   ├── State/
│   └── Utilities/
├── Features/
│   ├── Home/
│   ├── Scan/
│   ├── Learning/
│   ├── Tutor/
│   ├── Practice/
│   ├── WrongQuestions/
│   ├── Knowledge/
│   └── Settings/
├── Components/
└── Resources/
```

推荐统一：

```text
APIClient
  ↓
Repository / Service
  ↓
ViewModel
  ↓
SwiftUI View
```

不要在 View 中直接拼 URL 或解析后端 JSON。

---

## 4. 扫描架构

前端职责：

```text
Camera / Document Scan
        ↓
Perspective Correction
        ↓
Preview / Reorder / Add More
        ↓
Compression
        ↓
Upload
```

前端 **不负责**：

- OCR；
- 分题；
- 知识点识别；
- 错误分析。

这些交由 Backend + VLM。

---

## 5. Tutor 架构

Tutor 是有状态 Session，而不是 stateless chat。

```text
Knowledge State
      ↓
Tutor Session
      ↓
Current Phase
      ↓
Question / Explanation / Hint
      ↓
Student A-D Answer
      ↓
Evaluate
      ↓
Choose Next Action
      ↓
Update Evidence / Mastery when appropriate
```

可能的 phase：

- diagnose
- teach
- concept_check
- guided_practice
- independent_practice
- completed

前端只展示服务器返回的结构化 turn。

---

## 6. Knowledge Engine

所有学习行为尽量统一形成 Evidence：

```text
Homework Analysis
Tutor Answer
Practice Answer
       ↓
    Evidence
       ↓
Knowledge Engine
       ↓
Mastery Update
```

不要分别维护三套互不一致的掌握度算法。

比赛阶段可以使用简单权重规则，不要求训练额外模型。

---

## 7. Mock / Fallback 架构

iOS 应保留：

```text
DataProvider Protocol
├── LiveDataProvider
└── MockDataProvider
```

如果后端：

- 网络断开；
- LLM 超时；
- VLM 失败；

现场仍然可以切换到预先验证的 Demo Flow。

---

## 8. 商业功能架构

Hackathon 中商业模块只做 View + Demo State。

不实现：

- StoreKit 完整购买；
- 服务端票据验证；
- 精确额度扣费算法。

预留模型：

```text
CreditBalance
SubscriptionStatus
BookEntitlement
```

即可。
