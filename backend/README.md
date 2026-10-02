# backend/ — 开发者速查

> 项目总览、架构说明、部署步骤请见 **[根目录 README.md](../README.md)**。

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
.venv/bin/python -m pytest                              # 29 passed，不依赖网络
.venv/bin/python tools/e2e_live.py --base http://127.0.0.1:17283   # 打真模型
```

---

## 我要改 X，该动哪个文件

| 需求 | 文件 |
|---|---|
| 加 / 改接口字段 | `app/schemas.py`，并同步 `docs/API.md`（`/docs` 会自动跟进） |
| 确认文档没漏接口 | `tools/check_docs.py`（核对 `docs/API.md` 是否覆盖全部真实接口） |
| 加新接口 | `app/routers/` + `app/services/`，并在 `app/routers/__init__.py` 注册 |
| 加错误码 | `app/errors.py` |
| 调掌握度算法 / 权重 | `app/mastery.py` 顶部的常量 |
| 加知识点 / 错误类型 | `app/knowledge.py`（**只追加，不要改已有 id**） |
| 加题目 | `app/seed/banks/*.json`（改完跑一次测试确认加载无 warning） |
| 改 Tutor 教学路径 | `app/seed/tutor_scripts.json`（内容）+ `app/services/tutor_service.py`（状态机） |
| 调题目推荐算法 | `app/services/practice_service.py` 顶部的 `W_*` 权重 |
| 换模型 / 加降级模型 | `backend/.env`（不用改代码） |
| 改 Demo 初始掌握度 | `app/seed/demo.py` 的 `DEMO_PLAN` |
| 加数据库表 | `app/db.py` 的 `SCHEMA_STATEMENTS`（已有库需要迁移） |

---

## 两条必须守住的规则

1. **掌握度只能从 `knowledge_service.apply_evidence()` 更新。**
   作业、Tutor、练习都必须走这一个入口，否则同一份数据会算出两个数字。

2. **Router 不写 Prompt、不写 SQL。**
   分层是 `Router → Service → LLM/DB`。Prompt 在 `services/` 里，
   SQL 在 `repositories.py` 里。

---

## 目录速览

```
app/
├── main.py            FastAPI 入口、中间件、/health、/media 静态资源
├── config.py          环境变量（代码里不出现密钥）
├── schemas.py         ★ API 契约
├── errors.py          统一错误格式 + error_code
├── dependencies.py    Bearer 鉴权（无头则回落 Demo 用户）
├── db.py              SQLite 基础设施
├── repositories.py    所有 SQL 都在这里
├── knowledge.py       知识点树 + 错误类型分类法
├── mastery.py         ★ Evidence-based 掌握度算法
├── question_bank.py   题库加载器（宽容：坏题只丢不崩）
├── routers/           HTTP 层
├── services/          业务层（llm / knowledge / vlm / homework / tutor / practice / …）
└── seed/              题库、教学脚本、图书、Demo 种子
tools/                 probe_models / e2e_live / remote / check_docs
tests/                 29 个测试
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
