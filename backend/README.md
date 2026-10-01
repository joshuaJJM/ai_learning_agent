# 知迹 · Personal Learning Agent — Backend

后端是整个系统的 **Source of Truth**：用户、Knowledge State、Mastery、Evidence、
错题库、Tutor Session、练习记录全部在服务端。iOS 不自行计算掌握度。

```
Observe → Understand → Decide → Teach → Practice → Evaluate → Update → Re-plan
```

- 对外 API 契约见 **[docs/API.md](../docs/API.md)**（前端只需要看这一份）
- 在线试接口：`http://121.43.137.176:17283/docs`

---

## 快速开始

```powershell
cd backend

# 1. 建虚拟环境
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 配置模型（复制模板后填 key）
Copy-Item .env.example .env
#    编辑 .env，填入 LLM_API_KEY

# 3. 起服务
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 17283
```

打开 <http://127.0.0.1:17283/docs> 可以直接点着调所有接口。

**不带 `Authorization` 头时会自动使用 Demo 用户**，所以联调阶段可以完全不管鉴权。

### 演示前准备

```powershell
# 铺开学习历史（把「导数综合应用」压到 43% 附近）
curl -X POST http://127.0.0.1:17283/api/v1/demo/seed
```

---

## 目录结构

```
backend/
├── app/
│   ├── main.py               FastAPI 入口、中间件、健康检查、/media 静态资源
│   ├── config.py             环境变量配置（不出现任何密钥）
│   ├── schemas.py            ★ 对外 API 契约（Pydantic），前端唯一依赖
│   ├── errors.py             统一错误格式 + error_code 常量
│   ├── dependencies.py       Bearer 鉴权（带 Demo 用户回退）
│   ├── db.py                 SQLite 基础设施（文档表 + 关系表）
│   ├── repositories.py       数据访问层，SQL 只出现在这里
│   ├── knowledge.py          知识点树 + 错误类型分类法
│   ├── mastery.py            ★ Evidence-based 掌握度算法
│   ├── question_bank.py      题库加载器（约定的 bank JSON 规范）
│   ├── routers/              HTTP 层：只做参数校验与序列化
│   ├── services/             业务层
│   │   ├── llm.py                LLM/VLM 统一接入（OpenAI 兼容）
│   │   ├── knowledge_service.py  ★ Knowledge Engine（唯一掌握度入口）
│   │   ├── recommendation_service.py  下一步行动决策
│   │   ├── homework_service.py   试卷分析流水线（异步）
│   │   ├── vlm_service.py        图片 → 结构化题目 + 二次校验
│   │   ├── tutor_service.py      ★ Tutor 受控状态机
│   │   ├── practice_service.py   ★ 题目推荐算法
│   │   ├── wrong_question_service.py
│   │   ├── book_service.py       图书 / 权限 / 订阅
│   │   └── home_service.py       首页聚合
│   └── seed/
│       ├── banks/*.json          题库（6 个 bank / 44 题）
│       ├── tutor_scripts.json    Tutor 教学脚本
│       ├── books.json            图书假数据
│       └── demo.py               Demo 状态种子
├── tools/
│   ├── probe_models.py       模型连通性探针
│   ├── e2e_live.py           真实端到端联调（打真模型）
│   └── remote.py             远程部署工具（paramiko）
└── tests/                    29 个测试，覆盖完整 Demo 闭环
```

分层原则：**Router 不写 Prompt、不写 SQL**。`Router → Service → LLM/DB`。

---

## 核心设计

### 1. Knowledge Engine 是唯一入口

契约要求「不要让作业、Tutor、练习各写一套 Mastery 算法」。所以：

```
作业分析 ┐
Tutor 回答 ├→ Evidence → knowledge_service.apply_evidence() → Mastery
独立练习 ┘
```

任何地方都不允许自己算掌握度，否则同一份数据会算出两个数字。

### 2. 掌握度算法（Evidence-based，非 LLM 生成）

**难度加权 + 时间衰减的 Beta-Binomial 后验均值**：

- 观测值：`correct=1.0` / `partial=0.5` / `uncertain=0.3` / `wrong=0.0`
- 权重 `w = 来源权重 × 时间衰减 × 难度权重 × 相关度`
  - 来源：`exam 1.0` / `practice 0.9` / `tutor 0.6`（考试最可信）
  - 衰减：`exp(-age/30天)`，下限 0.25（有遗忘曲线）
  - 难度：`0.5 + difficulty`（做对难题更能说明问题）
- 后验 `Beta(1 + Σw·s, 1 + Σw·(1-s))`，掌握度 = 均值
- 置信度 `1 - exp(-Σw/5)`，小样本自动保守

选它的理由：**可解释、可测试、小样本稳定、不会漂**。
每个百分比都能反查是哪几条 Evidence 撑起来的。

### 3. 教错答案是比功能缺失更严重的失败

实测中视觉模型确实会把 `f'(x)=3x(x-2)>0` 的解判成 `(0,2)`（正确是 `x<0 或 x>2`）。
所以上传分析有**双重校验**：

1. 题干能匹配题库 → 直接用**题库里人工验算过的答案**；
2. 匹配不到 → 用另一个模型**独立求解一遍**，两次一致才采信；
3. 不一致 → 该题标为 `unknown`，**不计入掌握度统计**，并在 `warnings` 说明。

宁可少判一题，也不能教错。

### 4. Tutor 是受控状态机，不是 Prompt 拼接

- **状态转移是确定性的**（Python 实现），不看模型脸色
- **反馈话术用模板**，因为交互式教学里每轮等 8 秒模型响应会毁掉体验
- 引导练习（有人扶着做对）**不产生 Evidence**；只有概念诊断与独立练习才算数

```
diagnose ──答错→ remedial（更简单的问题）→ 讲解
   └──答对→ 讲解 → guided_practice ×2 → independent_practice → summary
```

### 5. 题目推荐是纯算法

不调模型。综合难度契合、错题重做（带冷却）、避免重复（近 5 天做对的不再出）、
错误模式针对性四项打分排序。题库是预处理的静态资源，所以结果可复现可解释。

### 6. 分析必须异步

`POST` 立即返回 `analysis_id`（202），客户端轮询 `GET /analyses/{id}`。
进度返回 5 个阶段的状态，前端直接渲染成可持续追踪的进度卡片。
实测整条流水线约 **20–30 秒**（含真实 VLM）。

---

## 模型配置（硅基流动，OpenAI 兼容）

`.env`：

```ini
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_API_KEY=sk-xxxxxx
LLM_MODEL=deepseek-ai/DeepSeek-V3.2
VLM_MODEL=Qwen/Qwen3-VL-32B-Instruct
VLM_FALLBACK_MODEL=Qwen/Qwen3-VL-8B-Instruct
LLM_FALLBACK_MODEL=Qwen/Qwen2.5-72B-Instruct
FORCE_MOCK_LLM=false        # true = 完全离线，不碰网络
```

模型 ID 是**实测**过的——`/v1/models` 列出 97 个模型，但其中一部分对本账号
并不可用（调用会连接被关闭或超时）。换模型前先跑：

```powershell
.venv\Scripts\python.exe tools\probe_models.py --vision
```

> ⚠️ `.env` 已被 `.gitignore` 忽略。**不要把真实 key 提交进仓库。**

---

## 测试

```powershell
.venv\Scripts\python.exe -m pytest          # 29 个测试，约 3 秒
```

测试不依赖网络和模型（VLM 被替换成确定性假实现），覆盖：

- 掌握度算法：先验、难度、时间衰减、趋势、错误模式、父节点聚合
- 契约措辞映射（`wrong` ↔ `incorrect`）
- 完整 Demo 闭环：seed → 首页 → 上传 → 轮询 → 错题 → 知识详情 → Tutor 答错降级
  → 学完 → 掌握度上移 → 首页变化
- 幂等（重试不会把掌握度更新两次）
- 统一错误格式、鉴权、练习不泄漏答案、图书兑换

### 真实链路联调（打真模型）

```powershell
# 窗口 1
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# 窗口 2
.venv\Scripts\python.exe tools\e2e_live.py --base http://127.0.0.1:8000
```

---

## 部署

```powershell
# 1. 上传（排除 .venv / .env / data）
.venv\Scripts\python.exe tools\remote.py deploy

# 2. 看远端环境
.venv\Scripts\python.exe tools\remote.py ping

# 3. 远端执行命令
.venv\Scripts\python.exe tools\remote.py exec "ls -la ~/zhiji-backend"
```

远端：`121.43.137.176:22`（用户 `hackathon`），服务监听 `17283`。

---

## 已知限制（比赛版刻意取舍）

| 项 | 现状 | 上生产要做什么 |
|---|---|---|
| 鉴权 | 无 token 自动落到 Demo 用户 | 接真实账号体系，去掉回退 |
| 多用户 | 只考虑了单用户 Demo | 数据已按 `user_id` 分表，结构不用改 |
| 传输 | 明文 HTTP | 上 HTTPS |
| 图片留存 | 上传图片一直留盘供错题回看 | 对象存储 + 生命周期策略 + 用户可删除 |
| 数据库 | SQLite + WAL，单进程 | PostgreSQL |
| 分析任务 | FastAPI BackgroundTasks + 轮询 | 消息队列 + worker（接口契约不用变） |
| 支付 | 假数据 | StoreKit 服务端校验 |
| 学科 | 只做高中数学·函数/导数 | 扩展题库与知识点树 |
| 知识点覆盖 | 函数/导数 10 个点，数列/概率只有占位 | 补齐题库 |
