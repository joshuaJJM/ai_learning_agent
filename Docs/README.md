# 好学 · Personal Learning Agent

> 好（hǎo）学 + 好（hào）学 = 学好。

**好学** 是为「Echo｜未来·回响」48H 教育黑客松设计的个人学习 Agent。它不只回答题目，而是从真实作业、错题、教学过程和练习结果中持续理解学生的学习状态，并决定“下一步最应该学什么”。

## 1. 核心理念

传统学习工具通常只能告诉学生：

- 哪一道题错了；
- 得了多少分；
- 正确答案是什么。

好学希望进一步回答：

- **为什么错？**
- **错误对应哪个知识点？**
- **这个问题是否反复出现？**
- **下一步最值得学习什么？**
- **教学策略应该如何根据学生的回答实时调整？**

核心闭环：

```text
真实作业 / 单题
      ↓
扫描与上传
      ↓
VLM / LLM 理解题目与作答
      ↓
错误诊断与知识点映射
      ↓
Knowledge State / Evidence
      ↓
Agent 决定下一步学习行为
      ↓
Tutor / Practice
      ↓
新的 Evidence
      ↓
更新掌握度并重新规划
      ↺
```

## 2. 黑客松 Scope

### Demo 范围

- 单用户；
- 高中数学；
- 仅聚焦 **导数基础**；
- 拍照题型与练习题型以 **选择题** 为主；
- 一页可包含多道题；
- 多模态模型负责后端题目理解、作答判断、错因分析和知识点归因；
- UI 中可以展示数学、化学、物理等多学科假数据，用于表达产品未来形态。

### 48H 原则

**完整可运行闭环 > 功能数量 > 技术复杂度。**

不在比赛阶段追求：

- 多学科真实支持；
- 复杂 Multi-Agent；
- 全自动长期规划器；
- 手写草稿语义识别；
- 完整支付系统；
- 大规模题库和出版授权系统。

## 3. 技术栈

### iOS

- Swift / SwiftUI
- Vision / VisionKit
- PencilKit
- async/await
- URLSession / Codable
- Screen Time 相关能力（可选，不作为 P0）

### Backend

- FastAPI
- 数据库（后端为 Source of Truth）
- VLM / LLM
- Knowledge State / Evidence Engine
- Tutor / Practice Controller

## 4. 数据原则

比赛版调整为：

> **服务器是学习数据的唯一 Source of Truth。**

服务器保存：

- Knowledge State
- Evidence
- Wrong Questions
- Tutor / Practice Session
- 学习历史
- 题库与权限数据

App 本地只保留必要的临时 UI 状态与缓存。

## 5. iOS 信息架构

主界面采用 4 个 Tab：

1. **首页** — 当前学习状态、Next Step、知识摘要、错题入口；
2. **扫描** — 扫描/上传作业、试卷或不会做的题，可继续“上传更多”；
3. **学习** — Tutor 与 Practice；
4. **设置** — 题库、商业展示、Screen Time、About 等。

Tutor Session 隐藏 Tab Bar，进入沉浸式学习界面。

## 6. 设计原则

- Apple-like / Native / Quiet / Minimal
- Typography first
- 大量留白
- 少量蓝色强调
- SF Pro / SF Symbols
- 少卡片，不做传统教育 Dashboard
- AI 不作为视觉主角，**学习状态**才是主角

Figma：

https://www.figma.com/design/2XhgXMGH4C7YFSSPs4RlQi

## 7. 商业展示（Hackathon Concept）

比赛 Demo 中只表达产品化思路，不实现真实支付：

- 新用户赠送 **1,000,000 学习额度**；
- 额度用完后可购买；
- 图书/题库可单独解锁或通过订阅获得；
- 学习额度的最终计费规则仍属于产品实验，不应在 48H 内实现复杂结算逻辑。

> 注意：UI 中的额度、价格、订阅、图书购买均可使用 Demo 数据。

## 8. Repository

GitHub：

https://github.com/joshuaJJM/ai_learning_agent

建议目录：

```text
ai_learning_agent/
├── ios/
├── backend/
├── shared/
├── docs/
├── README.md
├── REQUIREMENTS.md
├── ARCHITECTURE.md
├── API_CONTRACT.md
├── DESIGN.md
├── DEVELOPMENT_PLAN.md
├── DEMO_PLAN.md
├── PHASES.md
└── AGENTS.md
```

## 9. 开发纪律

- 每完成一个 Phase 必须产生至少一次可识别的 Git commit；
- 不要把多个 Phase 混成一个巨大提交；
- 不提交 API Key、模型 Key、Token 或私密协作地址；
- 前后端通过稳定的 API Contract 解耦；
- 未经确认不要扩大 Scope；
- Demo reliability > technical ambition。

详细规则见 `AGENTS.md` 与 `PHASES.md`。
