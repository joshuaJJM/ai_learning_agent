# backend/ — 开发者速查

> 项目总览、架构说明、部署步骤请见 **[根目录 README.md](../README.md)**。
> 线上出问题的排查流程见 **[docs/RUNBOOK.md](../docs/RUNBOOK.md)**。

对外 API 契约：**[docs/API.md](../docs/API.md)**（完整字段与示例，纯文本好读、可直接喂给 agent），
以及线上 <http://121.43.137.176:17283/docs>（Swagger，由 `app/schemas.py` 自动生成）。

---

## 本地起服务

```bash
cd backend
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt     # Windows: .venv\Scripts\python.exe
cp .env.example .env                                    # 填 LLM_API_KEY
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 17283
```

```bash
.venv/bin/python -m pytest                              # 307 passed，不依赖网络
.venv/bin/python tools/e2e_live.py --base http://127.0.0.1:17283   # 打真模型
```

---

## 工具

| 工具 | 用途 |
|---|---|
| `tools/check_docs.py` | 每个真实接口都被 `docs/API.md` 提到过吗（快，只管路径） |
| `tools/audit_docs.py` | **字段级**深审：响应字段有没有写进文档、必填查询参数、文档里写了但代码没有的路径 |
| `tools/sync_error_codes.py` | 按 `app/errors.py` 的 `_CODES` 重写 API.md 里的错误码表 |
| `tools/e2e_live.py` | 打真模型的端到端检查（23 项） |
| `tools/probe_models.py --vision` | 探测哪些模型对本账号真的可用 |
| `tools/remote.py` | 部署 / 看日志 / 重启 / 重置线上环境 |

> **`check_docs.py` 和 `audit_docs.py` 要一起跑。**
> 只跑前者会得到假安全感 —— 它曾经在「§8 整节只有三行路径、零个字段说明」
> 的情况下报 exit 0。

---

## 我要改 X，该动哪个文件

| 需求 | 文件 |
|---|---|
| 加 / 改接口字段 | `app/schemas.py`，并同步 `docs/API.md`（`/docs` 会自动跟进） |
| 确认文档没漏接口 | `tools/check_docs.py` + `tools/audit_docs.py` |
| 加新接口 | `app/routers/` + `app/services/`，并在 `app/routers/__init__.py` 注册 |
| 加错误码 | `app/errors.py`（然后跑 `tools/sync_error_codes.py`） |
| 调掌握度算法 / 权重 | `app/mastery.py` 顶部的常量 |
| 调标签统计 / 推荐 | `app/services/tag_service.py`（`PESSIMISM_Z`、`RECENT_COOLDOWN_DAYS`） |
| 调识别链顺序 / 重试次数 | `app/services/vlm_service.py` 的 `recognition_models()`、`attempts_for_model()` |
| 调图片压缩 | `app/services/vlm_service.py` 的 `MAX_IMAGE_EDGE` / `prepare_image()` |
| 调超时（会影响降级） | `LLM_TIMEOUT_SECONDS`（`.env`），见根 README 的「超时与重试」 |
| 调看门狗 / 终止态策略 | `homework_service.py` 的 `STALE_ANALYSIS_SECONDS`、`recover_interrupted_analyses()`、`reap_stale_analyses()`；看门狗任务本身在 `app/main.py` |
| 改错题归并规则 | `app/services/wrong_question_service.py` 的 `record_attempt()` |
| 加知识点 / 错误类型 | `app/knowledge.py`（**只追加，不要改已有 id**） |
| 加题目 | `app/seed/banks/*.json`（改完跑一次测试确认加载无 warning） |
| 改 Tutor 教学路径 | `app/seed/tutor_scripts.json`（内容）+ `app/services/tutor_service.py`（状态机） |
| 调题目推荐算法 | `app/services/practice_service.py` 顶部的 `W_*` 权重 |
| 换模型 / 加降级模型 | `backend/.env`（不用改代码） |
| 改 Demo 初始掌握度 | `app/seed/demo.py` 的 `DEMO_PLAN` |
| 加数据库表 | `app/db.py` 的 `SCHEMA_STATEMENTS`（已有库需要迁移） |

---

## 三条必须守住的规则

1. **掌握度只能从 `knowledge_service.apply_evidence()` 更新。**
   作业、Tutor、练习都必须走这一个入口，否则同一份数据会算出两个数字。
   标签统计**从 Evidence 现算**，所以它自动跟着对，不需要单独维护。

2. **Router 不写 Prompt、不写 SQL。**
   分层是 `Router → Service → LLM/DB`。Prompt 在 `services/` 里，
   SQL 在 `repositories.py` 里。

3. **改一处语义，必须扫一遍上下游。**
   这个项目反复栽在同一件事上：改了"生产者"忘了"消费者"。
   真实案例（全部是同一天出现的）：
   - 加了 `retrying` 阶段状态，但 `StageState` 枚举没加 → **模型降级时接口直接 500**
   - 题库改成保留"同题干不同选项"的题，但匹配逻辑只比题干 → 挑错那道题、用错答案
   - 复核流程新增了三条"判 unknown"的路径，但没保住 `unanswered` → 学生"没作答"被改写成"没算准"
   - 幂等请求头在 A 路由支持、B 路由自己写了一份只认标准头 → 文档承诺的别名在某处失效

   **对策**：改了某个值/状态/字段之后，用 `grep` 把所有消费方列出来，
   然后**写一条测试钉住消费方**（不是只测生产者）。

---

## 目录速览

```
app/
├── main.py            FastAPI 入口、中间件、/health、/media 静态资源、看门狗
├── config.py          环境变量（代码里不出现密钥）
├── schemas.py         ★ API 契约
├── errors.py          统一错误格式 + error_code（单一事实来源）
├── dependencies.py    Bearer 鉴权、幂等请求头依赖
├── db.py              SQLite / MySQL 双方言 + 迁移
├── repositories.py    所有 SQL 都在这里
├── knowledge.py       知识点树 + 错误类型分类法
├── mastery.py         ★ Evidence-based 掌握度算法
├── question_bank.py   题库加载器（宽容：坏题只丢不崩）
├── routers/           HTTP 层
├── services/          业务层（llm / knowledge / vlm / homework / tutor /
│                      practice / tag / wrong_question / recommendation / book）
└── seed/              题库、教学脚本、图书、Demo 种子
tools/                 audit_docs / check_docs / sync_error_codes /
                       e2e_live / probe_models / remote
tests/                 307 个测试
```

---

## 排查

```bash
.venv/bin/python tools/remote.py service logs      # 线上日志
.venv/bin/python tools/remote.py service status
curl http://121.43.137.176:17283/health            # 含题库告警数、模型模式
```

- `llm_mode: "mock"` → 没配 `LLM_API_KEY` 或开了 `FORCE_MOCK_LLM`
- 题库有 warning → 看启动日志，通常是 `answer` 不在 `options` 里
- 分析一直 `failed` + `VLM_TIMEOUT` → 跑 `tools/probe_models.py --vision` 看模型是否可用
- **分析一直 `processing`** → 看门狗 15 分钟内会收掉；急的话重启服务，启动对账会立刻判 `failed`

完整排查流程见 **[docs/RUNBOOK.md](../docs/RUNBOOK.md)**。

---

## 改完提交前

```bash
.venv/bin/python -m pytest
.venv/bin/python tools/check_docs.py
.venv/bin/python tools/audit_docs.py
```

三个都 exit 0 再提交。
