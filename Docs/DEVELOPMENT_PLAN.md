# 好学 — DEVELOPMENT PLAN

## 总原则

48H 开发采用 Phase 制。

**每个 Phase 完成后必须 commit。**

如果某个 Phase 没有达到 Definition of Done，不应为了赶进度把未完成内容假装归入下一 Phase。

---

## Phase 0 — Repository Bootstrap & Contract Freeze

### 目标

建立可并行开发的工程基础。

### iOS

- 确认 Xcode Project；
- 建立 SwiftUI App Shell；
- 建立 Core / Features / Components 目录；
- 建立 Networking 抽象；
- 建立 Mock DataProvider。

### Backend

- FastAPI 基础工程；
- 数据库基础；
- 配置管理；
- LLM/VLM Service 抽象。

### Shared

- 锁定本文件集；
- 锁定 API Contract 语义；
- 明确 Demo Scope。

### Done

- 两端可独立启动；
- Git remote 正确；
- 文档齐全；
- 不包含 Secret。

### Commit

```text
phase-0: bootstrap project and freeze contracts
```

---

## Phase 1 — iOS Shell & Mock Product Flow

### 目标

不依赖后端，用 Mock Data 把完整 UI 骨架跑通。

### 内容

- 4 TabView；
- Home；
- Scan；
- Learn；
- Settings；
- Tutor Session 基础页；
- Navigation；
- Mock Knowledge / Wrong Questions / Credits。

### Done

- 用户可以在 App 中走完主要页面；
- 页面结构与 Figma 基本一致；
- 无真实 API 也可演示静态流程。

### Commit

```text
phase-1: build ios shell and mock learning flow
```

---

## Phase 2 — Scan & Image Preparation

### 目标

完成前端真实扫描流程。

### 内容

- Camera / document import；
- Perspective correction；
- 多图片预览；
- 追加“上传更多”；
- 图片删除 / 基础排序（如时间允许）；
- 压缩与上传前准备；
- Analysis Progress UI。

### Done

- 可一次上传多张；
- 可在已有图片后继续追加；
- 图片可被矫正为正视纸张效果；
- Mock 上传状态正常展示。

### Commit

```text
phase-2: implement scan and image preparation flow
```

---

## Phase 3 — Tutor, Practice & Scratchpad

### 目标

完成核心学习体验。

### 内容

- Tutor Session；
- A-D 选项选择；
- 选择后点击继续；
- 自由输入 UI 保留但不上传；
- Practice 选择题；(Note: Practice UI was not completed in Phase 3 and has been explicitly moved to Phase 6. Do not treat it as a Phase 3 blocker.)
- Mastery 展示；
- PencilKit 草稿本；
- 清空确认。

### Done

- Mock 数据下 Tutor 可以多轮推进；
- 至少存在“答错 → 更简单引导”的分支演示；
- 草稿本可稳定使用。

### Commit

```text
phase-3: implement tutor practice and scratchpad
```

---

## Phase 4 — Backend Core & AI Pipeline

**Status: ✅ Complete — live verified**

### 目标

后端完成真实 Demo 所需核心能力。

### 内容

- 统一图片上传；
- VLM 分析；
- 题目 / 学生答案识别；
- Knowledge Point mapping；
- Error diagnosis；
- Evidence；
- Knowledge State；
- Wrong Questions；
- Tutor Session；
- Practice；
- 数据库持久化。

### Done

- 一套真实导数选择题样本可稳定分析；
- Tutor 可以根据 A-D 回答生成下一步；
- Knowledge State 可以产生前后变化；
- 后端测试通过，真实线上 VLM / LLM E2E 已验证。

> Note: Phase 4 的后端能力已经完成；尚未被 iOS 展示的能力统一放入后续前端集成 Phase，不重复修改后端核心架构。

### Commit

```text
phase-4: implement backend learning agent pipeline
```

---

## Phase 5 — Core Frontend Integration

### 目标

把已经完成的后端学习能力接到用户真正看得见的核心页面。

### 内容

- Home 接入 `GET /api/v1/home`，移除生产路径对固定 Home fixture 的依赖；
- 扫描结果页完整消费 `question_results`、`knowledge_changes`、`new_wrong_questions`、`next_action`；
- Wrong Questions 列表 / 详情与 Tutor 入口；
- Knowledge Detail 与 mastery explanation；
- Tutor contract cleanup：补齐 `answering_turn_id` 等已知边界；
- Tutor 入口保留后端来源上下文，当前进程内重入时从服务端恢复会话；
- 保留 Mock / fixture 仅用于 Preview、UI Test 与开发调试。

### 不做

- 不重写后端算法；
- 不提前进行大规模视觉 Polish；
- 不为了接入数据引入新的状态管理框架。

### Done

- Home 的学习状态与 Next Step 来自真实后端；
- 扫描完成后可看到题目、诊断、知识点和掌握度变化；
- 错题或知识点可进入对应详情，并能从合适入口启动 Tutor。
- Tutor 使用服务端结构化回合，能恢复当前进度并显示服务端总结与知识状态变化。

### Commit

```text
phase-5: integrate core learning data into ios
```

---

## Phase 6 — Practice & Closed Learning Loop

### 目标

补齐 Practice 前端，让完整学习闭环真正成立。

### 内容

- `POST /api/v1/practice/sessions`；
- Practice DTO / API Client / ViewModel / UI；
- 个性化题目展示；
- A-D 作答；
- 判分与解析；
- `knowledge_changes` / `tag_changes` 展示；
- 下一题 / 完成态；
- Practice 完成后刷新 Home；
- 修复闭环中的数据边界、retry 与幂等问题。

### 必须验证的真实 Flow

```text
Home
↓
Scan images
↓
Upload / AI analysis
↓
Wrong question / Knowledge State
↓
Tutor
↓
A-D answer
↓
Agent changes strategy
↓
Practice
↓
Mastery update
↓
Home changed
```

### Done

- 上述闭环至少连续成功 3 次；
- 不需要开发者手动改数据库或请求；
- Demo 设备可独立完成完整联网流程。

### Commit

```text
phase-6: complete live learning loop
```

---

## Phase 7 — Product Surface & Commercial Demo

### 目标

补齐比赛展示需要的产品化页面，让 App 看起来像一个完整产品，而不是只有核心学习闭环的技术 Demo。

### 内容

- 图书商店 / 题库商店 UI；
- 图书详情与解锁状态展示；
- 订阅展示，例如 ¥20 解锁商店内全部作业本题目；
- 学习额度展示与购买入口 Demo；
- Settings 页面补全；
- About This App / Version；
- 数据与隐私、Screen Time / 专注模式等展示项；
- 必要的 Empty State / 占位内容整理。

### 实现原则

- 商业内容仅用于 Hackathon 产品展示；
- 可以完全使用 iOS 本地 Demo State / fixture；
- 不要求后端接口；
- 不实现 StoreKit、真实支付、票据校验、真实订阅或复杂额度结算；
- 不允许商业展示工作影响核心学习闭环。

### Done

- Settings 中不再出现统一的“后续阶段加入”占位弹窗；
- 图书商店、订阅、额度和 About 均存在可正常演示的完整页面；
- 所有商业价格 / 状态明确属于 Demo presentation，不伪装成真实购买系统。

### Commit

```text
phase-7: complete product and commercial demo surfaces
```

---

## Phase 8 — Online Demo Reliability & QA

### 目标

针对比赛现场的联网演示路径做稳定性检查，不额外实现离线模式。

### 内容

- 固定并验证比赛使用的测试图片与测试题；
- 验证线上 Backend / VLM / LLM 地址与配置；
- 网络错误、AI timeout、Session 失效的明确错误提示与 retry；
- 重复提交 / 重试不得重复写 Evidence 或重复计分；
- 连续多次完整 Demo Flow 测试；
- 清理会阻断演示的 P0 / P1 bug；
- 更新过期测试数量或明显漂移的开发文档。

### 不做

- 不要求断网演示；
- 不要求 Cached / Mock 自动接管真实分析；
- 不新增产品功能。

### Done

- 在比赛预期联网环境中连续完整走 Demo 无 crash；
- 可恢复的网络 / AI 错误都有清晰提示与重试入口；
- 重试不造成重复 Evidence / mastery 更新。

### Commit

```text
phase-8: harden online demo reliability
```

---

## Phase 9 — Final UI Polish & Motion

> 最终 Phase，仅在功能和联网 Demo 稳定后进行。

### 目标

把已经能跑的产品变成舞台上“看起来完成度很高”的产品。

### 内容

- 视觉 spacing / typography QA；
- Figma 对齐；
- SF Symbols；
- Spring transitions；
- Scan page paging motion；
- Loading / analysis progress transition；
- Tutor / Practice turn transitions；
- Mastery number animation；
- Scratchpad transition；
- Haptics（可选）；
- Accessibility / Dynamic Type 基础检查；
- 最终舞台 Demo 手感测试。

### 原则

如果剩余时间不足：

> **删动画，不删闭环。**

### Done

- 无明显 UI clipping；
- 关键动画不卡顿；
- 现场设备连续走 Demo 无 crash；
- 最终 commit 完成。

### Commit

```text
phase-9: polish final ui and motion
```
