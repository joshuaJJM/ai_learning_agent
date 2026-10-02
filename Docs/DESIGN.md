# 好学 — DESIGN

## 1. Brand

产品名：**好学**

品牌含义：

> 好（hǎo）学 + 好（hào）学 = 学好

英文定位：

> Personal Learning Agent

视觉关键词：

- Native
- Quiet
- Minimal
- Apple-like
- Typography-first
- Learning-state-first

Figma：

https://www.figma.com/design/2XhgXMGH4C7YFSSPs4RlQi

---

## 2. Tab Structure

```text
首页 / 扫描 / 学习 / 设置
```

Tutor / Practice 深度 Session 中隐藏 Tab Bar。

---

## 3. Home

首页不是传统 Dashboard。

优先级：

```text
Next Step
   ↓
Knowledge Summary
   ↓
Recent Wrong Questions
   ↓
Recent Learning Changes
```

首页可以展示多学科假数据，用于表达产品未来愿景。

---

## 4. Scan

核心体验：

```text
扫描 / 选择图片
      ↓
透视矫正
      ↓
横向分页预览
      ↓
上传更多
      ↓
上传与 AI 分析
```

图片展示可带轻微 Cover Flow 感，但不要复制经典 Cover Flow 的强 3D 视觉。

“上传更多”语义：

> 保留已经选择的照片，并继续追加新照片。

不是“重新扫描”。

---

## 5. Learn

学习 Tab 分为两个入口：

- 继续课程；
- 针对薄弱点练习。

不要做成两个彼此割裂的系统。

---

## 6. Tutor Session

顶部：

```text
×        导数与单调性        草稿本
```

主体：

- LLM 教学文字；
- A-D 选择题；
- “写下你的想法……”自由输入 UI；
- 继续按钮。

当前 Demo：

> 自由输入仅保留 UI，不上传后端。

底部：

- 当前知识点；
- Mastery；
- Progress。

RPG 感来自 **回答改变下一步教学分支**，而不是 XP、等级、宝箱等游戏 UI。

---

## 7. Scratchpad

点击草稿本：

- 背景 blur / dim；
- 草稿层覆盖内容；
- PencilKit；
- 完成；
- 清空；
- 清空前 confirmation dialog。

---

## 8. Settings

建议 Section：

### 学习

- 专注模式
- 图书商店 / 题库

### 好学

- 学习额度
- 订阅
- 数据与隐私

### About

- About This App
- Version

### Hackathon 商业展示

- 图书商店、订阅、学习额度与解锁状态允许使用本地 Demo 数据；
- 可展示例如“¥20 解锁商店内全部作业本题目”的订阅方案；
- 图书详情、订阅状态和购买入口只需要完成产品展示，不要求 StoreKit 或后端商业接口；
- UI 应明确呈现为产品方案，不模拟真实支付成功流程。

---

## 9. Motion

Motion 只在最后 Phase 做。

优先级：

1. 页面进入 / 退出；
2. Tab 切换细微反馈；
3. Scan 图片分页 Spring；
4. Analysis 状态平滑推进；
5. Mastery 数字变化；
6. Tutor Answer → Next Turn transition；
7. Scratchpad overlay transition。

禁止为了动画牺牲稳定性。
