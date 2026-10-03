# 好学 · Personal Learning Agent — Backend

> 好（hǎo）学 + 好（hào）学 = 学好。

「Echo｜未来·回响」48H 教育黑客松项目 **好学** 的后端分支。iOS 在 [`frontend`](../../tree/frontend) 分支。

后端负责理解学生的作答、维护他的 Knowledge State、并决定下一步该学什么：

```
Observe → Understand → Decide → Teach → Practice → Evaluate → Update → Re-plan
```

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
去尾逗号），修不好就重试，**识别链上每个模型各 5 次**。
重试时会把它自己上一条坏输出连同具体要求一起回灌，比单纯重发同一个请求有效得多。
如果输出是被 `max_tokens` 截断，则**放大预算**重发而不是原样重试 ——
原样重试必然得到同样被截断的结果（实测一张 9 题的试卷曾白等 9 分钟）。

识别链是 **DeepSeek → Qwen3-VL-32B → Qwen3-VL-8B**（质量优先）。
降级过程会以 `retrying` 阶段状态暴露给前端，不会看起来像卡住。

判定结果分五档，其中两档**不计入掌握度**：

| correctness | 含义 | 计分 |
|---|---|---|
| `correct` / `wrong` / `partial` | 正常判定 | ✅ |
| `unanswered` | 学生没作答 | ❌ |
| `unknown` | 复核没通过（附 `possible_answer` 供参考） | ❌ |

`unanswered` 与 `unknown` 对用户含义完全不同（"你没做" vs "我没算准"），不要合并显示。

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
math.derivative.monotonicity                          利用导数判断函数单调性与单调区间
math.derivative.monotonicity_parameter                利用单调性或导数恒成立求参数
math.derivative.monotonicity_applications             导数与函数性质综合应用
math.derivative.extrema                               利用导数判断与求解极值
math.derivative.extrema_parameter                     根据极值或最值条件求参数
math.derivative.absolute_extrema                      利用导数求函数最值
math.function.parity_and_monotonicity                 函数奇偶性与单调性综合判断

（以下 10 个来自 2026-10-02 的新版题库，官方的 knowledge_points.json 仍是
 version 1 只含上面 7 个，待官方更新到 version 2 后对齐）

math.derivative.definition                            导数定义与极限
math.derivative.meaning                               导数的几何意义与瞬时变化率
math.derivative.rules                                 基本求导公式与运算法则
math.derivative.tangent_slope                         切线斜率与倾斜角
math.derivative.tangent_equation                      曲线切线方程
math.derivative.tangent_relations                     切线的平行与垂直关系
math.derivative.tangent_count                         切线条数与公切线
math.derivative.tangent_optimization                  切线相关的最值问题
math.derivative.function_relations                    函数关系式与导数的综合应用
math.function.symmetry_periodicity_derivative         奇偶性、对称性与周期性中的导数关系
```

题库是预处理好的静态 JSON，放在 `app/seed/banks/`，当前 1 个 bank / 73 道单选题：

```json
{
  "schema_version": "1.0",
  "bank_id": "math.derivative.comprehensive",
  "bank_name": "高中数学导数综合题库",
  "language": "zh-CN",
  "version": "1.0.0",
  "updated_at": "2026-10-02",
  "questions": [
    {
      "id": "第001题",
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

### 题目 ID：内容指纹

团队给的题库里 `id` 是「第001题」这种**按位置编的序号**。直接拿它当身份有个隐患：
**题库一旦重新生成、题目顺序变了，同一个序号就指向另一道题**，
历史 Evidence 会挂错。

所以加载器对不合规的 id 做一层转换：改用**题干内容指纹**。

```
文件里的 id:  第001题
服务端 id:    math.derivative.comprehensive.1bd577aaf5   ← sha1(题干)[:10]
```

- 题目内容没变 → 指纹不变 → 历史记录继续有效
- 内容真改了 → 指纹变 → 视为另一道题（这正是想要的语义）
- 原始序号保留在 `source_id`，展示用的题号在 `question_number`

启动时会告警一行，提示题库生成方最好直接产出规范 id —— 但**功能上已经安全了**。
细节与测试见 `app/question_bank.py` 的 `stem_fingerprint` 与
`tests/test_question_identity.py`。

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

## 标签系统

标签与知识点是**两套独立的东西**：知识点用来算掌握度，标签用来做**练习推荐**。
按 `JSON标签与项目设计说明.txt`，题库的 `tags` 是知识点 `name` 的展示层镜像，
两者逐字一致、没有额外标签（当前各 17 个）。

### 统计模型：Beta 后验 + 悲观下界

v1 是「答对 +1 / 答错 −1」的裸计数器，有个致命缺陷：

```
一个标签 5 对 5 错 → 0
一个标签从没练过   → 0        ← 两者无法区分
```

而推荐正是取「分数最低的标签」，于是"练得稀烂"和"完全没碰过"被同等对待。
此外还有：不同标签之间不可比、没有难度加权、没有时间衰减、没有不确定度。

v2 改成 **Beta 后验 + 悲观下界**：

```
每个标签维护 Beta(α, β)，用与掌握度**完全相同**的一套权重更新
（对错得分 × 难度 × 来源可信度 × 时间衰减），从 Evidence 现算。

score = (后验均值 − 一个标准差) × 100        ← 悲观估计
```

一句话：**证据越少，压得越狠。**

| 标签状态 | 均值 | 标准差 | **score** | 排名 |
|---|---|---|---|---|
| 2 对 8 错 | 0.250 | 0.120 | **13** | 最该练 |
| 从没练过 | 0.500 | 0.289 | **21** | 次之（探索）|
| 5 对 5 错 | 0.500 | 0.139 | **36** | 不急 |
| 9 对 1 错 | 0.833 | 0.103 | **73** | 最后 |

`5 对 5 错`(36) 和 `从没练过`(21) 终于分开了，而且排序天然是经典的
explore/exploit：练得差的优先、没碰过的其次、平衡的不急、掌握好的最后。

> **没练过的标签不是 0，而是 21** —— 那是先验 Beta(1,1) 的悲观下界。
> 0 意味着"确信完全不会"，而我们其实只是"还不知道"。

统计**从 Evidence 现算，不落表**（与掌握度同源），所以不存在
「计数器与历史对不上」这类 bug。计分覆盖三条链路：作业批改、练习作答、
AI Tutor（Tutor 的题来自教学脚本，没有题目 id，按知识点反查同名标签）。

标签表在 `app/seed/tags.json`，是**可替换的配置**。
标签宇宙 = 配置表 ∪ 题库里实际出现的标签，所以表滞后也不会丢标签。

### 推荐算法

面对的是多对多关系（一题多标签、一标签多题），所以除了「必须包含最弱标签」
这条硬规则，还有一个二级排序：

| 优先级 | 规则 | 为什么 |
|---|---|---|
| 1 | 必须包含**分数最低**的标签 | 需求原文 |
| 2 | 该题**所有标签的分数之和**升序 | 一道题覆盖两个都很弱的标签比只覆盖一个排得前 —— 练一道补两个薄弱点。若它另一个标签已经很强，和会变大，自然排到后面 |
| 3 | 最近 5 天做过的题**降权**（不是排除） | 避免连着出同一道，同时保证一定有题可推荐 |
| 4 | 题号 | 保证结果可复现：同样的输入永远给同样的推荐 |

整套逻辑是纯算术 + 排序，**不调用任何模型**，单次推荐在微秒级。
冷启动（所有标签都在先验上）也能正常出题。

### 接口

```
GET  /api/v1/tags                      全部标签的分数（升序，最弱的在前）
GET  /api/v1/tags/recommend?count=5    按标签推荐题目
POST /api/v1/practice/sessions         {"count": 5}              → 走标签推荐
POST /api/v1/practice/sessions         {"knowledge_point_id": …}  → 走原来的知识点选题
```

`POST /practice/sessions` **不填 `knowledge_point_id` 时走标签推荐**，
响应里有 `selection_mode` / `target_tag` / `picked_tags`，客户端可以直接显示
「本次专练：XXX」。填了知识点则保持原有行为。
提交答案的响应里多了 `tag_changes`（本次动了哪些标签、+1 还是 −1）。

### 清单漂移防护

知识点清单被后端代码、`seed/knowledge_points.json`、题库 tags 三边同时依赖。
任何一边改了另一边没跟上都会静默出错 —— 题库换代时就吃过这个亏（题库给了 17 个、
代码里只有 7 个，46 道题直接挂不上知识点）。现在：

- 启动时比对代码清单与 `seed/knowledge_points.json`，不一致打 WARNING
- 标签如果不对应任何知识点名称，也会告警
- `tests/test_tags.py` 里有用例钉住这三者一致

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

## 存储

生产用 **MySQL 5.7**（远端 `127.0.0.1:3306`，只允许服务器内连接）；
本地开发与测试自动回落到 SQLite —— 所以本地不需要装 MySQL。

只要配了 `MYSQL_HOST` + `MYSQL_USER` 就走 MySQL：

```ini
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=hackathon
MYSQL_PASSWORD=***
MYSQL_DATABASE=hackathon
DATABASE_PATH=data/haoxue.db      # 没配 MySQL 时用这个
```

两种方言的差异**全部收敛在 `app/db.py`**：占位符（统一写 `?`，出口翻译成 `%s`）、
upsert 语法（`ON CONFLICT` / `ON DUPLICATE KEY UPDATE`）、索引写法
（MySQL 5.7 的 `CREATE INDEX` 不支持 `IF NOT EXISTS`，所以索引写在建表语句里）。
业务层和 `repositories.py` 完全不感知用的是哪个。

部署时服务器用**单独的环境文件**，别把 MySQL 配置混进本地开发用的 `.env`：

```bash
.venv/bin/python tools/remote.py deploy --prune --with-env --env-file .env.server --restart
```

> `--prune` 会删掉远端 `app/` `tools/` `tests/` 里本地已不存在的文件。
> 不加的话，本地删掉的文件会永远留在远端 —— 题库换代时踩过这个坑
> （旧的 6 个 bank 仍在，服务加载出 76 道题而不是 32 道）。

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
.venv/bin/python tools/remote.py reset --yes           # 恢复到全新环境（见下）
```

### 重置线上数据

演示或联调前想要一个**全新环境**：

```bash
.venv/bin/python tools/remote.py reset          # 只打印计划，不动数据
.venv/bin/python tools/remote.py reset --yes    # 真的执行
```

它做的是「**结构也重来**」而不是「删数据留旧表」：

1. 停服务
2. **drop 掉整个 MySQL 库再重建** —— 下次启动时服务按代码重新建表 + 跑迁移
3. 清空 `data/uploads/`（`--keep-uploads` 可保留）、删遗留 SQLite、清空 `service.log`
4. 启服务

MySQL 凭据是**在服务器上从 `.env` 现读**的，不在本地解析、也不经过命令行参数，
密钥始终留在服务器上。不带 `--yes` 时只打印计划并返回退出码 1，防误触。

> 重置完所有业务表都是 0 行。`books` 表会有 2 行 —— 那是启动时从
> `seed/books.json` 自动播种的配置数据，不是用户数据，每次启动都会有。
>
> 想铺演示数据：`POST /api/v1/demo/seed`。

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
| 数据库 | MySQL 5.7（生产）/ SQLite（本地开发与测试） | 已上 MySQL，后续补连接池与只读副本 |
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
| 基本求导公式与运算法则 | 77% |
| 导数的几何意义与瞬时变化率 | 74% |
| 利用导数求函数最值 | 72% |
| 利用单调性或导数恒成立求参数 | 69% |
| 函数奇偶性与单调性综合判断 | 68% |
| 导数定义与极限 | 67% |
| 切线斜率与倾斜角 | 64% |
| 利用导数判断与求解极值 | 62% |
| 函数关系式与导数的综合应用 | 62% |
| 切线的平行与垂直关系 | 61% |
| 曲线切线方程 | 53% |
| 根据极值或最值条件求参数 | 51% |
| 切线条数与公切线 | 50% |
| 切线相关的最值问题 | 44% |
| 奇偶性、对称性与周期性中的导数关系 | 44% |
| **导数与函数性质综合应用** | **43%** ← Demo 主线 |

证据时间戳相对播种时刻计算，所以每次演示前重新 seed，时间轴就是「最近」，
趋势判断也更符合现场叙事。

---

## 仓库约定

- 仓库：<https://github.com/joshuaJJM/ai_learning_agent>
- 本分支 `backend` 只放后端；前端在 `frontend` 分支，两边通过 API 契约解耦
- 不要 force-push，保留现有历史
- 每次提交前：跑测试 → 确认没有 `.env` / `api-key.txt` / `*.db` / 私有图片进入暂存区
