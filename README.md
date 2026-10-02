# 好学 · Personal Learning Agent — Backend

> 好（hǎo）学 + 好（hào）学 = 学好。

参加「Echo｜未来·回响」48H 教育黑客松的项目 **好学** 的**后端分支**。

前端（iOS / SwiftUI）在 [`frontend`](../../tree/frontend) 分支，本分支只放后端。

---

## 它解决什么问题

传统考试结束后，学生只知道「我第 17 题错了」。好学要回答的是：

> **「我为什么错？」** 以及 **「我下一步到底该学什么？」**

后端是整个系统的 **Source of Truth**：

```
Observe → Understand → Decide → Teach → Practice → Evaluate → Update → Re-plan
```

学生可能并不是「不会导数」，而是会求导、会解不等式，但**无法把导数符号转化为函数性质**。
这种细粒度判断必须来自持续积累的 Evidence，而不是模型的即兴发挥。

**iOS 不自行计算掌握度。** `43% → 51%` 这个变化只能由服务器算出来并返回，客户端只负责动画。

---

## 线上服务

| 项 | 地址 |
|---|---|
| API Base | `http://121.43.137.176:17283` |
| 交互式文档（推荐先看） | <http://121.43.137.176:17283/docs> |
| 健康检查 | <http://121.43.137.176:17283/health> |
| OpenAPI JSON | `http://121.43.137.176:17283/openapi.json` |

**前端联调阶段可以完全不传鉴权头** —— 不带 `Authorization` 时后端自动落到固定的 Demo 用户。

```bash
curl http://121.43.137.176:17283/api/v1/home
curl -X POST http://121.43.137.176:17283/api/v1/demo/seed   # 演示前铺开历史数据
```

---

## 快速开始

```bash
cd backend
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt      # Windows: .venv\Scripts\python.exe

cp .env.example .env      # 填入 LLM_API_KEY
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 17283
```

打开 <http://127.0.0.1:17283/docs> 直接点着调所有接口。

测试（29 个，约 3 秒，不依赖网络与模型）：

```bash
cd backend && .venv/bin/python -m pytest
```

---

## 关键设计

这几条是本项目最关键的技术判断，也是踩过坑之后定下来的。

### 1. Knowledge Engine 是全系统唯一的掌握度入口

契约要求「不要让作业、Tutor、练习各写一套 Mastery 算法」。所以：

```
作业分析 ┐
Tutor 回答 ├→ Evidence → knowledge_service.apply_evidence() → Mastery
独立练习 ┘
```

任何地方都不允许自己算掌握度，否则同一份数据会算出两个数字。

### 2. 掌握度是算出来的，不是模型生成的

**难度加权 + 时间衰减的 Beta-Binomial 后验均值**：

| 因子 | 取值 | 理由 |
|---|---|---|
| 观测值 | `correct 1.0` / `partial 0.5` / `uncertain 0.3` / `wrong 0.0` | — |
| 来源权重 | `exam 1.0` / `practice 0.9` / `tutor 0.6` | 考试比课堂口头回答可信 |
| 时间衰减 | `exp(-age/30天)`，下限 0.25 | 有遗忘曲线 |
| 难度权重 | `0.5 + difficulty` | 做对难题更能说明掌握 |
| 相关度 | 题目对知识点的关联强度 | 「顺带涉及」不该等价于「专门考」 |

后验 `Beta(1 + Σw·s, 1 + Σw·(1−s))`，掌握度取均值，置信度 `1 − exp(−Σw/5)`。

选它的理由：**可解释、可测试、小样本稳定、不会漂**。
每个百分比都能反查是哪几条 Evidence 撑起来的 —— 这是产品「查看证据」功能的地基。

### 3. 教错答案是比功能缺失严重得多的失败

实测中视觉模型确实会把 `f'(x) = 3x(x−2) > 0` 的解判成 `(0, 2)`（正确是 `x < 0 或 x > 2`）。
对教育产品来说，这不可接受。所以图片分析有**双重校验**：

1. 题干能匹配题库 → 直接用**题库里人工验算过的答案**；
2. 匹配不到 → 用**另一个模型独立求解**一遍，两次一致才采信；
3. 不一致 → 该题 `correctness` 返回 `"unknown"`、`correct_answer` 为 `null`，
   **且不计入掌握度统计**，并在 `warnings` 里说明。

宁可少判一题，也不能教错。

### 4. Tutor 是受控状态机，不是 Prompt 拼接

- **状态转移是确定性的**（Python 实现），不看模型脸色
- **反馈话术用模板**：交互式教学里每轮等 8 秒模型响应会毁掉体验
- **引导练习里答对不产生 Evidence** —— 有人扶着做对，说明不了真实掌握程度

```
diagnose ──答错→ remedial（更简单的问题）→ 讲解
   └──答对→ 讲解 → guided_practice ×2 → independent_practice → summary
```

Tutor 返回的是结构化的 `turn_type`（`concept_question` / `simpler_question` / `hint` /
`explanation` / `guided_practice` / `independent_practice` / `summary`），
不是一段 Markdown —— iOS 才能按类型渲染不同的 Native UI。

### 5. 题目推荐是纯算法

题库是预处理好的静态资源，推荐**不调任何模型**，按四项打分排序：

1. **难度契合度** —— 掌握度低出简单题，掌握度高出难题
2. **错题重做** —— 做错过且尚未做对的题优先，带冷却时间
3. **避免重复** —— 近 5 天已做对的题压到后面
4. **错误模式针对性** —— 「分类讨论错误」多的学生，多出含参数分类讨论题

结果可复现、可解释，权重集中在 `practice_service.py` 顶部便于调参。

### 6. 分析必须异步

`POST` 立即返回 `analysis_id`（202），客户端轮询 `GET /analyses/{id}`。
进度返回 5 个阶段的状态，前端直接渲染成可持续追踪的进度卡片。
实测整条流水线约 **20–30 秒**（含真实 VLM 调用）。

---

## 对外接口

完整契约见 **[docs/API.md](../docs/API.md)**（前端只需要看这一份）。

```
GET  /health

POST /api/v1/auth/guest              GET  /api/v1/auth/demo-user
GET  /api/v1/home                    ← 首页聚合，首页只调这一个

POST /api/v1/homework/analyses       ← 上传图片（异步）
GET  /api/v1/homework/analyses/{id}  ← 轮询进度

GET  /api/v1/knowledge               GET  /api/v1/knowledge/{id}

GET  /api/v1/wrong-questions         GET  /api/v1/wrong-questions/{id}
PATCH /api/v1/wrong-questions/{id}

POST /api/v1/tutor/sessions          GET  /api/v1/tutor/sessions/{id}
POST /api/v1/tutor/sessions/{id}/turns

POST /api/v1/practice/sessions       GET  /api/v1/practice/sessions/{id}
GET  /api/v1/practice/sessions/{id}/next
POST /api/v1/practice/sessions/{id}/answers

GET  /api/v1/books                   GET  /api/v1/books/{id}
POST /api/v1/books/{id}/redeem       GET  /api/v1/entitlements

POST /api/v1/ai/chat                 ← 标准 AI 直连，发问题拿回答
GET  /api/v1/ai/models

POST /api/v1/demo/seed               ← 演示前铺开历史数据
POST /api/v1/demo/reset              GET  /api/v1/demo/status
```

统一错误格式（客户端只根据 `error_code` 分支，不要解析文案）：

```json
{ "error_code": "INVALID_IMAGE", "message": "图片过大：15 MB，上限 12 MB", "request_id": "927af558" }
```

写接口支持 `Idempotency-Key` 头 —— 手机断网重试不会把掌握度更新两次。

---

## 题目 / 知识点

**知识点树**（`math.derivative.*`，id 是稳定契约，客户端可写死）：

```
函数                导数
└ 函数单调性        ├ 基础求导
                    ├ 解导数不等式
                    ├ 单调性
                    ├ 极值
                    └ 综合应用
```

**题库**是预处理好的静态 JSON，放在 `app/seed/banks/`，当前 6 个 bank / 44 道单选题：

```json
{
  "schema_version": "1.0",
  "bank_id": "math.derivative.monotonicity",
  "bank_name": "由导数符号判断单调性单选题",
  "language": "zh-CN",
  "questions": [
    {
      "id": "math.derivative.monotonicity.0009",
      "type": "single_choice",
      "stem": "已知函数 f(x) = x^3 - 3x^2 + 2，求 f(x) 的单调递增区间。",
      "options": { "A": "(-inf, 0)", "B": "(0, 2)", "C": "(-inf, 0) 和 (2, +inf)", "D": "(2, +inf)" },
      "answer": "C",
      "explanation": "f'(x) = 3x^2 - 6x = 3x(x - 2)，令 f'(x) > 0 得 x < 0 或 x > 2……",
      "knowledge_point_ids": ["math.derivative.monotonicity", "math.derivative.inequality"],
      "tags": ["单调区间", "三次函数"],
      "source_ref": "example-authored",
      "difficulty": 3
    }
  ]
}
```

`difficulty`（1–5）是可选扩展字段，缺省时回退到该知识点的难度档位。
加载器很宽容：单条题目不合法只会被丢弃并记入 warnings，不会让服务起不来
（warning 会出现在启动日志与 `/health` 里）。

---

## 目录结构

```
backend/
├── app/
│   ├── main.py               FastAPI 入口、中间件、健康检查、/media 静态资源
│   ├── config.py             环境变量配置（代码里不出现任何密钥）
│   ├── schemas.py            ★ 对外 API 契约（Pydantic）
│   ├── errors.py             统一错误格式 + error_code 常量
│   ├── dependencies.py       Bearer 鉴权（带 Demo 用户回退）
│   ├── db.py                 SQLite 基础设施（文档表 + 关系表）
│   ├── repositories.py       数据访问层，SQL 只出现在这里
│   ├── knowledge.py          知识点树 + 错误类型分类法
│   ├── mastery.py            ★ Evidence-based 掌握度算法
│   ├── question_bank.py      题库加载器
│   ├── routers/              HTTP 层：只做参数校验与序列化
│   ├── services/             业务层
│   │   ├── llm.py                LLM/VLM 统一接入（OpenAI 兼容）
│   │   ├── knowledge_service.py  ★ Knowledge Engine（唯一掌握度入口）
│   │   ├── vlm_service.py        图片 → 结构化题目 + 二次求解校验
│   │   ├── homework_service.py   试卷分析流水线（异步）
│   │   ├── tutor_service.py      ★ Tutor 受控状态机
│   │   ├── practice_service.py   ★ 题目推荐算法
│   │   ├── recommendation_service.py  下一步行动决策
│   │   ├── wrong_question_service.py / book_service.py / home_service.py
│   └── seed/                 题库、教学脚本、图书数据、Demo 种子
├── tools/
│   ├── probe_models.py       模型连通性探针
│   ├── e2e_live.py           真实端到端联调（打真模型，23 项检查）
│   └── remote.py             远程部署工具（paramiko）
└── tests/                    29 个测试，覆盖完整 Demo 闭环
```

分层原则：**Router 不写 Prompt、不写 SQL**。`Router → Service → LLM/DB`。

---

## 模型配置（硅基流动，OpenAI 兼容）

```ini
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_API_KEY=sk-xxxxxx
LLM_MODEL=deepseek-ai/DeepSeek-V3.2
VLM_MODEL=Qwen/Qwen3-VL-32B-Instruct
VLM_FALLBACK_MODEL=Qwen/Qwen3-VL-8B-Instruct
LLM_FALLBACK_MODEL=Qwen/Qwen2.5-72B-Instruct
FORCE_MOCK_LLM=false        # true = 完全离线，不碰网络
```

模型 ID 是**实测**过的：`/v1/models` 列出 97 个模型，但其中一部分对本账号并不可用
（调用会连接被关闭或超时）。换模型前先跑：

```bash
cd backend && .venv/bin/python tools/probe_models.py --vision
```

> ⚠️ `.env` 与 `api-key.txt` 都被 `.gitignore` 忽略，**任何情况下不要提交真实 key**。

---

## 测试

```bash
cd backend && .venv/bin/python -m pytest        # 29 passed
```

不依赖网络与模型（VLM 被替换成确定性假实现），覆盖：

- 掌握度算法：先验、难度、时间衰减、趋势、错误模式、父节点聚合
- 契约措辞映射（`wrong` ↔ `incorrect`）
- 完整 Demo 闭环：seed → 首页 → 上传 → 轮询 → 错题 → 知识详情
  → Tutor 答错降级 → 学完 → 掌握度上移 → 首页变化
- 幂等（重试不会把掌握度更新两次）
- 统一错误格式、鉴权、练习不泄漏答案、图书兑换

真实链路（打真模型，验证线上环境）：

```bash
cd backend && .venv/bin/python tools/e2e_live.py --base http://121.43.137.176:17283
```

---

## 部署

```bash
cd backend
.venv/bin/python tools/remote.py ping                  # 看远端环境
.venv/bin/python tools/remote.py deploy --with-env     # 上传代码 + .env
.venv/bin/python tools/remote.py bootstrap             # 首次：建 venv、装依赖、起服务
.venv/bin/python tools/remote.py service status        # RUNNING / NOT_RUNNING
.venv/bin/python tools/remote.py service logs
.venv/bin/python tools/remote.py service restart
```

远端：`121.43.137.176:22`（用户 `hackathon`），应用目录 `~/haoxue-backend`，监听 `17283`。

> **没有用 systemd**：远端账号不在 sudoers 里，所以用 `setsid nohup` + pidfile 托管。
> 能扛住 SSH 断连，但**扛不住服务器重启** —— 重启后执行 `service start` 即可。

---

## 已知限制（比赛版刻意的取舍）

| 项 | 现状 | 上生产要做什么 |
|---|---|---|
| 鉴权 | 无 token 自动落到 Demo 用户 | 接真实账号体系，去掉回退 |
| 多用户 | 只考虑单用户 Demo | 数据已按 `user_id` 分表，结构不用改 |
| 传输 | 明文 HTTP | 上 HTTPS |
| 图片留存 | 上传图片留盘供错题回看 | 对象存储 + 生命周期策略 + 用户可删除 |
| 数据库 | SQLite + WAL，单进程 | PostgreSQL |
| 分析任务 | FastAPI BackgroundTasks + 轮询 | 消息队列 + worker（接口契约不用变） |
| 支付 | 假数据 | StoreKit 服务端校验 |
| 学科 | 只做高中数学·函数/导数 | 扩展题库与知识点树 |

---

## 仓库约定

- 仓库：<https://github.com/joshuaJJM/ai_learning_agent>
- **本分支 `backend` 只放后端**；前端在 `frontend` 分支，两边通过 API 契约解耦
- 不要 force-push，保留现有历史
- 每次提交前：跑测试 → 确认没有 `.env` / `api-key.txt` / `*.db` / 私有图片进入暂存区
- 前后端接口信息通过共享剪贴板同步（见 `notice.md`）

### 演示前必做

```bash
curl -X POST http://121.43.137.176:17283/api/v1/demo/seed
```

会把「导数综合应用」重置到 **43%** 附近并铺开其余知识点：

| 知识点 | 掌握度 |
|---|---|
| 基础求导 | 83% |
| 解导数不等式 | 69% |
| 单调性 | 62% |
| 极值 | 51% |
| **综合应用** | **43%** ← Demo 主线 |
| 函数单调性 | 68% |

证据时间戳相对播种时刻计算，所以每次演示前重新 seed，时间轴就是「最近」，
趋势判断也更符合现场叙事。
