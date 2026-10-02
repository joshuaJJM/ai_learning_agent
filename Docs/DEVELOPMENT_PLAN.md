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
- Practice 选择题；
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
- Knowledge State 可以产生前后变化。

### Commit

```text
phase-4: implement backend learning agent pipeline
```

---

## Phase 5 — Product Completion & Demo Hardening

### 目标

把前后端各自尚未连接的产品面补完整，并准备 fallback。

### 内容

- Wrong Question UI；
- Knowledge Detail；
- Home 聚合数据；
- Settings Demo 数据；
- 学习额度商业展示；
- 题库 / 图书展示；
- 失败状态；
- Empty State；
- Cached / Mock Demo Flow；
- 固定现场演示样本。

### Done

- 无论 AI 是否在线，至少有一条可完成的 Demo Flow；
- 所有 P0 页面存在合理 loading / error / empty 状态。

### Commit

```text
phase-5: complete product states and harden demo fallback
```

---

# Phase 6 — Frontend / Backend Integration

> 倒数第二个 Phase。此阶段前不得提前进行大规模视觉 Polish。

### 目标

把真实后端嫁接到完成的 iOS UI。

### 内容

- 对齐最终 JSON；
- 建立 DTO / Codable；
- 接真实 Home 数据；
- 接图片上传；
- 接 Analysis Status；
- 接 Knowledge / Wrong Questions；
- 接 Tutor Session；
- 接 Practice；
- 修复数据边界问题；
- 网络超时 / retry；
- 最终真实闭环联调。

### 必须验证的真实 Flow

```text
Home
↓
Scan images
↓
Upload
↓
AI analysis
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
- Demo 设备可独立完成流程。

### Commit

```text
phase-6: integrate ios with live backend
```

---

# Phase 7 — Final UI Polish & Motion

> 最终 Phase，仅在功能稳定后进行。

### 目标

把已经能跑的产品变成舞台上“看起来完成度很高”的产品。

### 内容

- 视觉 spacing / typography QA；
- Figma 对齐；
- SF Symbols；
- Spring transitions；
- Scan page paging motion；
- Loading / analysis progress transition；
- Tutor turn transitions；
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
phase-7: polish final ui and motion
```
