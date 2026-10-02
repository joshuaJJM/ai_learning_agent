# 好学 — DEMO PLAN

## 1. Demo Story

建议控制在 3–5 分钟。

### Scene 1 — Home

展示：

```text
导数与单调性
当前薄弱
43%
```

讲解：

> 一张试卷只能告诉学生哪一道题错了，但我们希望系统知道“为什么错，以及下一步应该学什么”。

### Scene 2 — Scan

- 扫描一页导数选择题；
- 展示透视矫正；
- 如有多页，点击“上传更多”；
- 开始上传。

### Scene 3 — AI Analysis

展示进度：

- 图片已上传；
- 检测题目；
- 分析作答；
- 更新知识状态。

结果：

```text
6 题
5 对
1 题需要关注
```

### Scene 4 — Evidence

展示：

> 学生会基础求导，但在“导数符号 → 函数性质”上反复出错。

错题自动进入错题库。

### Scene 5 — Tutor

进入 Tutor：

```text
f'(x) > 0 意味着什么？
```

现场故意选错。

展示 Agent 改变教学策略：

- 换一种解释；
- 给更简单的问题；
- 再次确认理解。

### Scene 6 — Scratchpad

打开草稿本，现场写几步，清空时弹出确认。

### Scene 7 — Practice

完成一题独立练习。

### Scene 8 — Knowledge Update

```text
43% → 51%
```

回到首页，Next Step 改变。

---

## 2. Closing

推荐收尾：

> **It remembers how you learn.**
> **So it knows what you need next.**

或者中文：

> **每一次学习，都应该在下一次教育中留下回响。**

---

## 3. Demo Reliability

必须准备：

- 固定测试图片；
- 固定测试题；
- 已验证的真实后端结果；
- 本地 Mock / Cached fallback；
- 断网或模型故障时的降级路径。

不要在台上临时拍未知试卷验证模型泛化能力。
