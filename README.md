# 好学 · Personal Learning Agent — Backend

> 好（hǎo）学 + 好（hào）学 = 学好。

「Echo｜未来·回响」48H 教育黑客松项目 **好学** 的后端分支。iOS 在 [`frontend`](../../tree/frontend) 分支。

后端负责理解学生的作答、维护他的 Knowledge State、并决定下一步该学什么：

```
Observe → Understand → Decide → Teach → Practice → Evaluate → Update → Re-plan
```

掌握度（`43% → 51%`）是这条链路的输出，由服务端计算并作为唯一事实来源下发 ——
所以 iOS 拿到的永远是一个已经算好的数字，不需要、也不应该自己复现算法。

---

## 线上服务

| 项 | 地址 |
|---|---|
| API Base | `http://121.43.137.176:17283` |
| 交互式文档 | <http://121.43.137.176:17283/docs> |
| 健康检查 | <http://121.43.137.176:17283/health> |

不带 `Authorization` 头时会自动落到固定的 Demo 用户，联调阶段不用管鉴权。

---

## 快速开始

```bash
cd backend
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt      # Windows: .venv\Scripts\python.exe

cp .env.example .env      # 填入 LLM_API_KEY
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 17283
```

```bash
.venv/bin/python -m pytest                               # 29 passed，约 3 秒
.venv/bin/python tools/e2e_live.py --base http://127.0.0.1:17283   # 打真模型的端到端
```

---

## 关键设计

这几条是踩过坑之后定下来的判断，也是这个后端真正的价值所在。

### 1. 掌握度只有一个写入入口

作业分析、Tutor 回答、独立练习都会产生 Evidence，但都必须走同一个函数：

```
作业分析 ┐
Tutor 回答 ├→ Evidence → knowledge_service.apply_evidence() → Mastery
独立练习 ┘
```

否则同一份数据会被三处各算一遍，得到三个数字。

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

选它的理由：**可解释、可测试、小样本稳定、不会漂**。每个百分比都能反查是哪几条
Evidence 撑起来的 —— 这是 Knowledge Detail 页面「为什么是 43%」的地基。

### 3. 教错答案是比功能缺失严重得多的失败

实测中视觉模型确实会把 `f'(x) = 3x(x−2) > 0` 的解判成 `(0, 2)`（正确是 `x < 0 或 x > 2`）。
对教育产品来说这不可接受，所以图片分析有**双重校验**：

1. 题干能匹配题库 → 直接用**题库里人工验算过的答案**；
2. 匹配不到 → 用**另一个模型独立求解**一遍，两次一致才采信；
3. 不一致 → 该题标记为 `unknown`、不下发正确答案，**且不计入掌握度统计**，
   并在 `warnings` 里说明原因。

宁可少判一题，也不能教错。

### 4. Tutor 是受控状态机，不是 Prompt 拼接

- **状态转移是确定性的**（Python 实现），不看模型脸色
- **反馈话术用模板**：交互式教学里每轮等 8 秒模型响应会毁掉体验
- **引导练习里答对不产生 Evidence** —— 有人扶着做对，说明不了真实掌握程度

```
diagnose ──答错→ remedial（更简单的问题）→ 讲解
   └──答对→ 讲解 → guided_practice ×2 → independent_practice → summary
```

每一轮返回结构化的 `turn_type`（`concept_question` / `simpler_question` / `hint` /
`explanation` / `guided_practice` / `independent_practice` / `summary`），
而不是一段 Markdown，这样客户端才能按类型渲染不同的原生界面。

### 5. 题目推荐是纯算法

题库是预处理好的静态资源，推荐**不调任何模型**，按四项打分排序：

1. **难度契合度** —— 掌握度低出简单题，掌握度高出难题
2. **错题重做** —— 做错过且尚未做对的题优先，带冷却时间
3. **避免重复** —— 近 5 天已做对的题压到后面
4. **错误模式针对性** —— 「分类讨论错误」多的学生，多出含参数分类讨论题

结果可复现、可解释，权重集中在 `practice_service.py` 顶部便于调参。

### 6. 分析必须异步，多张图片并行

`POST` 立即返回 `analysis_id`（202），之后轮询取进度与结果。进度带 5 个阶段的状态。

多张图片**并行**识别（上限 4 并发 —— 打满模型配额反而会触发限流，比串行更慢），
所以一整套试卷的耗时取决于最慢的那一张，而不是页数之和。
实测 1 张约 21 秒、3 张同样约 **21 秒**。

模型偶尔会返回不合法的 JSON —— 最常见的是在中文正文里把引号打成了 ASCII 的 `"`，
导致字符串提前闭合。服务端会先尝试自动修复（归一中文引号定界符、转义正文里的裸引号、
去尾逗号），修不好就重试，**主模型 5 次、备选模型 5 次**。
重试时会把它自己上一条坏输出连同具体要求一起回灌，比单纯重发同一个请求有效得多。

---

## 对外接口

两份，互补：

- **[docs/UPLOAD.md](docs/UPLOAD.md)** —— 上传接口的详细使用说明（含 Swift 示例、轮询、错误处理、常见坑）。
- **[docs/API.md](docs/API.md)** —— 完整契约、逐字段说明与请求/响应示例。
  纯文本，可以直接读，也可以整份喂给 agent —— 不必去翻代码。
- **<http://121.43.137.176:17283/docs>** —— 交互式 Swagger，可以直接发请求试。
  由 `app/schemas.py` 的 Pydantic 模型自动生成，永远与代码同步。

接口分八组：鉴权、首页聚合、作业分析、Knowledge State、错题库、AI Tutor、
针对性练习、图书权限，另外有一个标准 AI 直连接口（发问题拿回答）和一组演示辅助接口。

错误响应统一为 `{ error_code, message, request_id }`；写接口支持 `Idempotency-Key`
以免断网重试重复更新掌握度。详见契约文档。

---

## 知识点与题库

知识点清单取自团队给定的 `knowledge_points.json`（version 1），是**扁平的 7 个**，
没有父子层级。**ID 与名称不要自行增删或改写** —— 前端、题库录入标准、后端三边都依赖它：

```
math.derivative.monotonicity              利用导数判断函数单调性与单调区间
math.derivative.monotonicity_parameter    利用单调性或导数恒成立求参数
math.derivative.monotonicity_applications 导数与函数性质综合应用
math.derivative.extrema                   利用导数判断与求解极值
math.derivative.extrema_parameter         根据极值或最值条件求参数
math.derivative.absolute_extrema          利用导数求函数最值
math.function.parity_and_monotonicity     函数奇偶性与单调性综合判断
```

题库是预处理好的静态 JSON，放在 `app/seed/banks/`，当前 1 个 bank / 32 道单选题：

```json
{
  "schema_version": "1.0",
  "bank_id": "math.derivative.application.monotonicity_extrema",
  "bank_name": "导数的应用 单调性极值与最值选择题",
  "language": "zh-CN",
  "version": "1.0.0",
  "updated_at": "2026-10-02",
  "questions": [
    {
      "id": "math.derivative.application.a06",
      "type": "single_choice",
      "stem": "已知 f(x)=x-ln(x)，求 f(x) 的单调递减区间。",
      "options": { "A": "(-∞,1)", "B": "(0,1)", "C": "(1,+∞)", "D": "(0,+∞)" },
      "answer": "B",
      "knowledge_point_ids": ["math.derivative.monotonicity"],
      "tags": ["利用导数判断函数单调性与单调区间"]
    }
  ]
}
```

题库格式由 `题库JSON录入标准_AI说明.md` 规定，几条硬性要求：

- **只允许**上述字段。`difficulty`、`source`、`source_ref` 等自定义字段会被加载器忽略并告警。
- `tags` 必须与 `knowledge_point_ids` **一一对应、顺序相同、逐字等于知识点 name**。
  加载器会校验：不一致时以知识点名称为准重写并告警。
- 选项键从 `A` 开始**连续排列**，2–8 个，不得留空。
- 题干与选项用纯文本数学写法（`x^2`、`e^x`、`(-∞,1)`），不用 LaTeX。

> 因为规范里没有 `difficulty`，题目难度由服务端按知识点兜底
> （`knowledge.py` 里每个知识点的 `default_difficulty`）。
>
> 另外规范里也**没有解析字段**，所以题库题的 `explanation` 会是 `null`；
> 只有 OCR 上传的题目才会带解析。

---

## 目录结构

```
backend/
├── app/
│   ├── main.py               FastAPI 入口、中间件、健康检查、/media 静态资源
│   ├── config.py             环境变量配置（代码里不出现任何密钥）
│   ├── schemas.py            对外 API 契约（Pydantic）
│   ├── errors.py             统一错误格式 + error_code 常量
│   ├── dependencies.py       Bearer 鉴权（带 Demo 用户回退）
│   ├── db.py                 SQLite 基础设施（文档表 + 关系表）
│   ├── repositories.py       数据访问层，SQL 只出现在这里
│   ├── knowledge.py          知识点树 + 错误类型分类法
│   ├── mastery.py            Evidence-based 掌握度算法
│   ├── question_bank.py      题库加载器
│   ├── routers/              HTTP 层：只做参数校验与序列化
│   ├── services/             业务层
│   │   ├── llm.py                LLM/VLM 统一接入（OpenAI 兼容）
│   │   ├── knowledge_service.py  Knowledge Engine（唯一掌握度入口）
│   │   ├── vlm_service.py        图片 → 结构化题目 + 二次求解校验
│   │   ├── homework_service.py   试卷分析流水线（异步）
│   │   ├── tutor_service.py      Tutor 受控状态机
│   │   ├── practice_service.py   题目推荐算法
│   │   ├── recommendation_service.py  下一步行动决策
│   │   └── wrong_question_service.py / book_service.py / home_service.py
│   └── seed/                 题库、教学脚本、图书数据、Demo 种子
├── tools/
│   ├── probe_models.py       模型连通性探针
│   ├── e2e_live.py           真实端到端联调（打真模型，23 项检查）
│   ├── check_docs.py         核对 docs/API.md 是否覆盖全部接口
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

不依赖网络与模型（VLM 被替换成确定性假实现），覆盖：掌握度算法（先验、难度、时间衰减、
趋势、错误模式、父节点聚合）、完整 Demo 闭环、幂等、统一错误格式、鉴权、
练习不泄漏答案、图书兑换。

真实链路（打真模型）用 `tools/e2e_live.py`，23 项检查覆盖线上环境。

---

## 部署

```bash
cd backend
.venv/bin/python tools/remote.py deploy --with-env     # 上传代码 + .env
.venv/bin/python tools/remote.py bootstrap             # 首次：建 venv、装依赖、起服务
.venv/bin/python tools/remote.py service status        # RUNNING / NOT_RUNNING
.venv/bin/python tools/remote.py service logs
.venv/bin/python tools/remote.py service restart
```

远端：`121.43.137.176:22`（用户 `hackathon`），应用目录 `~/haoxue-backend`，监听 `17283`。

远端账号不在 sudoers 里，用不了 systemd，所以是 `setsid nohup` + pidfile 托管，
并由用户级 crontab 兜底：

```
@reboot sleep 20 && ~/haoxue-backend/start.sh    # 开机自启
* * * * * ~/haoxue-backend/start.sh              # 每分钟看门狗（start.sh 幂等）
```

---

## 已知限制（比赛版刻意的取舍）

| 项 | 现状 | 上生产要做什么 |
|---|---|---|
| 鉴权 | 无 token 自动落到 Demo 用户 | 接真实账号体系，去掉回退 |
| 多用户 | 只考虑单用户 Demo | 数据已按 `user_id` 分表，结构不用改 |
| 传输 | 明文 HTTP | 上 HTTPS |
| 图片留存 | 上传图片留盘供错题回看 | 对象存储 + 生命周期策略 + 用户可删除 |
| 数据库 | SQLite + WAL，单进程 | PostgreSQL |
| 分析任务 | FastAPI BackgroundTasks + 轮询 | 消息队列 + worker（对外契约不用变） |
| 支付 | 假数据 | StoreKit 服务端校验 |
| 学科 | 只做高中数学·函数/导数 | 扩展题库与知识点树 |

---

## 演示前必做

```bash
curl -X POST http://121.43.137.176:17283/api/v1/demo/seed
```

会把「导数与函数性质综合应用」重置到 **43%** 附近并铺开其余知识点：

| 知识点 | 掌握度 |
|---|---|
| 利用导数判断函数单调性与单调区间 | 83% |
| 利用导数求函数最值 | 72% |
| 利用单调性或导数恒成立求参数 | 69% |
| 函数奇偶性与单调性综合判断 | 68% |
| 利用导数判断与求解极值 | 62% |
| 根据极值或最值条件求参数 | 51% |
| **导数与函数性质综合应用** | **43%** ← Demo 主线 |

证据时间戳相对播种时刻计算，所以每次演示前重新 seed，时间轴就是「最近」，
趋势判断也更符合现场叙事。

---

## 仓库约定

- 仓库：<https://github.com/joshuaJJM/ai_learning_agent>
- 本分支 `backend` 只放后端；前端在 `frontend` 分支，两边通过 API 契约解耦
- 不要 force-push，保留现有历史
- 每次提交前：跑测试 → 确认没有 `.env` / `api-key.txt` / `*.db` / 私有图片进入暂存区
