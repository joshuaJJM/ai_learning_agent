# HaoXue Project Audit Report

> 本报告为**只读审计**结论。审计期间没有修改任何受版本控制的源码，没有提交、没有修复 bug、没有把 mock 改成 live。
> 唯一的写操作是：创建了 gitignored 的本地 `backend/.venv`（跑测试用）、临时目录 `.audit_data/`（本地起服务用）、`audit/screenshots/`（截图证据）以及本报告文件。

---

## 1. Executive Summary

**一句话结论：后端已经是一个真实、可运行、经过线上验证的学习引擎；iOS 前端只把其中三条接口真正接上，产品闭环的最后两环（练习、首页回写）和扫描结果的展示仍然是空的。**

| 维度 | 成熟度 | 依据 |
|---|---|---|
| 后端成熟度 | **高** | 199 个测试全绿；`tools/e2e_live.py` 打真模型 **24/24 通过**；线上 MySQL + 真 VLM/LLM 已部署运行 |
| 前端 UI 成熟度 | **中高** | 4 Tab + 扫描 + Tutor + 草稿本视觉完成度高，构建 0 warning；但设置/练习/结果页是占位 |
| 前后端集成成熟度 | **低-中** | 只调用 5 个接口中的 3 个能力域（上传、Tutor、综合掌握度）；后端 40+ 个接口里绝大多数前端从未调用 |
| Phase 4 是否完成 | **后端：是（已线上验证）** | 见 §10 |
| 最大剩余阻塞 | **Home 不是后端驱动的** | 演示脚本 Scene 8「回到首页 → 43% → 51% → Next Step 变化」目前**永远不会发生**，首页是写死的 43% |

补充一个容易被文档误导的点：`PHASES.md` 里 Phase 4 全是未勾选的 `[ ]`，但代码 Reality 是 Phase 4 已经基本做完，而 Phase 5/6 的部分工作（Tutor 真实接入）被提前做掉了。**不要用 checkbox 判断进度。**

---

## 2. Audit Environment

| 项 | 值 |
|---|---|
| 审计日期 | 2026-10-02（Asia/Shanghai） |
| 前端仓库 | `/Users/huyajun/开发/2026.10.1学军黑客松`，分支 `frontend` |
| 前端 HEAD | `05f6b0f fix(phase-3b): restore mastery and safe math display` |
| 前端 git status | `?? ai_learning_agent-backend/`、`?? iOS App/ReferenceUIs/`（两个未跟踪目录，无已跟踪文件被改动） |
| 后端代码位置 | 同目录下 `ai_learning_agent-backend/`（**本地不是 git 仓库**，无 `.git`；README 声明它对应同一 GitHub 仓库的 `backend` 分支） |
| Xcode | 27.0（Build 27A266a） |
| 模拟器 | iPhone 18 Pro，iOS 27.0，UDID `0E05F898-9CA6-481E-9164-0715A4940017` |
| App 部署目标 | iOS 27.0；Bundle ID `com.TNTstudio.personalLearningAgent.HaoXue` |
| Python | 3.12（系统 framework python），本地 `backend/.venv` 按 `requirements.txt` 安装 |
| 后端测试环境 | SQLite（`DATABASE_PATH=.pytest_tmp/test.db`），`FORCE_MOCK_LLM=true` |
| 后端本地运行 | `uvicorn app.main:app --port 18080`，`FORCE_MOCK_LLM=true`（用于接口行为核对） |
| 后端线上运行 | `http://121.43.137.176:17283`，`llm_mode=live`，MySQL 5.7，`deepseek-ai/DeepSeek-V3.2` + `Qwen/Qwen3-VL-32B-Instruct` |
| 审计限制 | ① 本机 sandbox 不允许绑定端口/访问 CoreSimulatorService，本地起服务与 simctl 均用提权执行；② **照片选择器（PHPicker）运行在独立进程**，XcodeBuildMCP 的 rs/1 快照看不到它的元素，Computer Use 对 Device Hub 取状态超时、osascript 无辅助访问权限，因此「相册选图」这一步改用 App 自带的演示页在**真实后端模式**下走完了上传，见 §3.2；③ 报告中的百分比是工程估计，不是测量值 |

> 未在报告中出现任何 API Key、数据库口令或 token。

---

## 3. Build & Test Results

### 3.1 Backend

```bash
cd ai_learning_agent-backend/backend
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest
```

```
199 passed in 4.67s
```

- **failed 0 / skipped 0**；仅 2 条 `DeprecationWarning`（`starlette.testclient` 不建议配 httpx；`HTTP_422_UNPROCESSABLE_ENTITY` 常量改名）。
- `backend/README.md` 里写的「29 passed」已是过期数字（实际 199）。
- **这套测试证明什么、不证明什么**（审计要求明确区分）：
  - ✅ unit tested：`test_knowledge_engine.py`、`test_mastery_overview.py`、`test_llm_json.py`、`test_llm_truncation.py`、`test_question_identity.py` 等。
  - ✅ integration tested（进程内 HTTP + 真 SQLite）：`test_flow.py`（23）、`test_review_fixes.py`（22）、`test_batches.py`、`test_tags.py`。
  - ✅ mocked AI tested：`conftest.py` 里 `FORCE_MOCK_LLM=true`，并用 `monkeypatch.setattr(vlm_service, "analyze_images", _analyze)` 把 VLM 换成**确定性假实现**（固定返回一道「学生选 A / 正确 C」的导数题）。所有涉及图象识别的用例都属于这一类。
  - ✅ live AI/VLM tested：不在 pytest 内，见 `tools/e2e_live.py`。
  - ✅ true end-to-end tested：`tools/e2e_live.py --base http://121.43.137.176:17283` → **24 PASS / 0 FAIL**，包含真实图片上传、真实 VLM 识别（9.3 s，`generated_by=vlm`）、真实轮询、真实 Tutor 降级、真实练习推荐、真实 LLM。

本地 mock 模式服务行为核对（`FORCE_MOCK_LLM=true`）：

```
GET /health → {"status":"degraded","llm_mode":"mock",... "bank_count":1,"question_count":73}
```

`degraded` 是 mock 模式的预期结果（`main.py` 里 `degraded = bool(bank.report.errors) or not llm.configured`）。

### 3.2 Frontend

```bash
# XcodeBuildMCP: test_sim（scheme HaoXue, iPhone 18 Pro / iOS 27.0）
→ SUCCEEDED, passed 73, failed 0, skipped 0, 293s
# 其中 HaoXueUITests 6 个 UI 用例真实驱动了模拟器
```

```bash
# XcodeBuildMCP: build_run_sim
→ SUCCEEDED, warnings [], errors []
```

构建日志中 `warning:` 出现次数为 **0**。

模拟器手工走查（全部在 **live 模式**，即 App 默认指向 `http://121.43.137.176:17283`）：

1. 启动 → 4 Tab 正常，首页渲染正常。
2. 首页「继续学习」→ **真实创建 Tutor Session**，首轮返回服务端概念题「已知 f(x)=x³-3x²+2 …」，进度 1/6。
3. 故意选 **B（错）** → 服务端返回 `strategy=simplify / remedial_depth=1`，界面切到「换个角度 · 第 1 / 4 层」，并给出更简单的问题；页脚掌握度出现服务端值 `40%`。
4. 补救题选 A（对）→「回答正确」+ 完整解析 + `answer_reveal`，掌握度 `41%`。
5. 连续走完引导练习 2 题与独立练习 1 题 → **「学习完成」总结页显示 `41% → 46%`，「全部知识点综合掌握度 60%」**（全部服务端值）。
6. 点「完成学习」回首页 → **首页纹丝未动：仍是数学 78% / 化学 69% / 物理 84%、「导数与函数单调性」、「最近 3 次相关作答…」**。这是本次审计最关键的观察。
7. 扫描页：切到演示模式 → 「添加演示页面」→ 切回**真实后端** → 「开始分析」→ 出现真实 5 阶段进度（已接收图片/已识别题目/已理解作答/正在分析错误模式/正在更新知识状态）→ **25% → 100%「分析完成」**；点「查看分析结果」只得到占位文案。
8. 对照线上 `GET /api/v1/home`：`next_action.title = "下一步：根据极值或最值条件求参数"`，`stats.total_evidence=109`、`homework_count=2`、`wrong_question_open=1`。**服务端状态确实变了，只是 App 首页不读它。**

截图见 `audit/screenshots/`。

---

## 4. Functional Coverage Matrix

图例：✅ 完整；🟡 部分；❌ 缺失；⚪ mock/占位；❓ 未验证

| 能力 | Backend | Frontend | Integration | Runtime 验证 | 备注 |
|---|---|---|---|---|---|
| 多图上传（multipart + 魔数校验） | ✅ | ✅ | ✅ | ✅ 真机验证 | `POST /api/v1/homework/analyses` |
| 异步分析 + 5 阶段进度轮询 | ✅ | ✅ | ✅ | ✅ 真机验证 | 1 s 轮询，`queued/processing/completed/failed` |
| VLM 题目/选项/作答识别 | ✅ | — | 🟡 | ✅ 线上验证 | 上传成功但结果未被 UI 消费 |
| 正确答案二次校验（题库优先 + 第二模型交叉） | ✅ | — | — | ✅ 线上验证 | 不一致→`unknown`，不计入掌握度 |
| 错误诊断 / 错因分类 / 知识点映射 | ✅ | ❌ | ❌ | ✅ 线上验证 | App 不解码这些字段 |
| Evidence 统一写入 | ✅ | — | — | ✅ 线上验证 | 唯一入口 `knowledge_service.apply_evidence()` |
| 掌握度计算（难度+时间衰减 Beta-Binomial） | ✅ | — | ✅ | ✅ 线上验证 | 客户端不重算 |
| 综合掌握度 `mastery-overview` | ✅ | ✅ | ✅ | ✅ 真机验证 | Tutor 结束时显示「60%」 |
| 首页聚合 `GET /home` | ✅ | ⚪ | ❌ | ✅ 线上验证接口有数据 | App 首页用本地 fixture |
| 知识树 / 知识详情 | ✅ | ❌ | ❌ | ✅ 线上验证接口 | 无任何界面 |
| 错题库（列表/详情/状态） | ✅ | ❌ | ❌ | ✅ 线上验证（1 条） | 首页有两条**假**错题文本 |
| Tutor 有状态 Session | ✅ | ✅ | ✅ | ✅ 真机验证 | 6 步：概念→讲解→引导×2→独立→总结 |
| Tutor A-D + 补救 4 层 | ✅ | ✅ | ✅ | ✅ 真机验证 | 第 4 层仍错 → `answer_reveal` |
| Tutor SSE 打字机 + 同键 JSON 回放 | ✅ | ✅ | ✅ | ✅ 真机验证 | `meta→delta*→turn→done` |
| Tutor 幂等（`Idempotency-Key` + `answering_turn_id`） | ✅ | 🟡 | 🟡 | ❓ | App 传幂等键；**未传 `answering_turn_id`** |
| 掌握度变化展示（Tutor） | ✅ | ✅ | ✅ | ✅ 真机验证 | `41% → 46%` |
| Practice 练习（选题/判分/解析/Evidence） | ✅ | ❌ | ❌ | ✅ 线上验证接口 | App 里点「开始练习」弹「练习即将开放」 |
| 标签系统 / 标签推荐 | ✅ | ❌ | ❌ | ✅ 线上验证 | 客户端不可见 |
| 图书 / 额度 / 序列号 | ✅ | ⚪ | ❌ | ✅ 线上验证接口 | 设置页只有「1,000,000 演示额度」文案 |
| AI 直连接口 `/ai/chat` | ✅ | ❌ | ❌ | ✅ 线上验证 | App 未使用 |
| 草稿本（PencilKit + 清空确认） | — | ✅ | — | ✅ 真机 + UI 测试 | 达标 |
| 离线 fallback | 🟡 | ⚪ | ❌ | ❌ | `demo_cache` 目录不存在（见 §8） |
| 鉴权 | 🟡（Demo 用户回退，刻意） | ❌ | ❌ | ✅ | App 完全不带 token |

---

## 5. Backend Audit

后端分层干净：`Router（只校验/序列化）→ Service → LLM/DB`。`app/routers/*.py` 里没有 SQL 也没有 prompt。

### 5.1 Homework / Scan

- 创建：`app/routers/homework.py` + `app/services/homework_service.py`。`POST /analyses` 立即 202，后台 `BackgroundTasks` 跑 `run_analysis()`；多图**并行**识别（并发上限 4）。
- 校验：只认文件头魔数，不信任 `Content-Type`/扩展名（`INVALID_IMAGE`）。
- 进度：`_progress()` 生成 5 阶段，失败时**失败的那一步是 `failed` 而不是 `active`**，`error_code` 同步下发。
- VLM：`app/services/vlm_service.py`。职责边界清晰——VLM 只「看」，服务端负责「判」：题干命中题库 → 用人工验算答案；未命中 → 第二模型独立求解，两个答案一致才采信，否则 `correctness=unknown`、`correct_answer=null`、不计入掌握度。
- 结果持久化：题目、错题、Evidence、标签计分全部落库。

实测（线上）：`demo_question_17.png` → 9.3 s 完成，`学生选 A / 正确 C / correctness=wrong / error_type=transformation / 知识点 monotonicity / knowledge_changes 83.4%→73.7% / 错题入库`。

### 5.2 Evidence & Knowledge State

- **掌握度确实是算出来的，不是 LLM 生成的。** `app/mastery.py` 是难度加权 + 时间衰减的 Beta-Binomial 后验均值：观测值 `correct 1.0 / partial 0.5 / uncertain 0.3 / incorrect 0.0`；来源权重 `exam 1.0 / practice 0.9 / tutor 0.6`；时间衰减 `exp(-age/30)` 下限 0.25；难度权重 `0.5 + difficulty`。
- 只有一个写入入口：`app/services/knowledge_service.py::apply_evidence()`（作业 / Tutor / 练习三条链路全部经它）。
- 有趋势（`improving/declining/stable/unknown`）、有证据反查（`GET /knowledge/{id}` 的 `evidence[]` + `mastery_explanation`）、有 `recommended_action`。
- 幂等：写接口支持 `Idempotency-Key` / `client_request_id`，实现是「先原子占位 → 干活 → 覆盖」，并发重复请求返回 `409 IDEMPOTENCY_CONFLICT`。

### 5.3 Tutor

`app/services/tutor_service.py`（982 行）是**确定性 Python 状态机**，不是 prompt 拼接：

```
diagnose ──答错→ remedial（最多 4 层）→ 讲解
   └──答对→ 讲解 → guided_practice ×2 → independent_practice → summary
```

- Session 持久化（`GET /sessions/{id}` 可断线恢复）、Turn 持久化、`history` 完整。
- 结构化 `turn_type`（`concept_question / simpler_question / hint / explanation / guided_practice / independent_practice / remedial_exhausted / summary`）+ `strategy` + `remedial_depth`。
- 补救期间**绝不下发正式题答案**；答对当前题或第 4 层仍错时才 `answer_reveal`。
- 引导练习**不产生 Evidence**（有人扶着做对不算掌握）；独立练习产生 Evidence。
- SSE：`meta → delta* → turn → done`，`delta` 只作打字机用，权威数据在 `turn`。
- 状态是**真状态**：本次审计从同一 session 第 1 步走到第 6 步，答错 2 次分别进入第 1 层补救，且补救用了不同的题库题（第 031 题），进度 `1/6 → 3/6 → 4/6 → 5/6 → 完成`。**不是 stateless chatbot。**

### 5.4 Practice

`app/services/practice_service.py` + `app/services/tag_service.py`：推荐**纯算法、不调模型**——硬规则「必须包含分数最低的标签」，二级排序用该题所有标签分数之和升序，5 天内做过的题降权，题号兜底保证可复现。`next_question` 里**没有** `answer`/`explanation`（防泄漏，有测试钉住）。作答后 `tag_changes` 一并返回。

### 5.5 Database

- 本地/测试 SQLite，线上 MySQL 5.7（`storage_label()` 实测返回 `mysql://hackathon@127.0.0.1:3306/hackathon`）。
- 方言差异全部收敛在 `app/db.py`（占位符、upsert、索引写法），业务层无感。
- 启动时 `db.init_db()` 建表 + 迁移（日志实测：「已建立批次号唯一约束 uk_analyses_batch（回填 0 行历史数据）」）。
- 关系、事务、重启持久化均有测试覆盖。

---

## 6. Frontend Audit

工程结构按架构文档落地（`Core/Networking`、`Core/Data`、`Core/Models`、`Features/*`、`Components`），DTO → Mapper → Domain → ViewModel → View 的分层在 Tutor 与 MasteryOverview 上执行得很干净。

### 逐屏结论

| 屏幕 | 存在 | 渲染 | 导航 | 交互 | 数据来源 | 结论 |
|---|---|---|---|---|---|---|
| 首页 Home | ✅ | ✅ | ✅ | ✅ | `GoldenDemoFixtures.homeBefore/homeAfter` | ⚪ **纯 mock** |
| 扫描 Scan | ✅ | ✅ | ✅ | ✅ | **真实后端** | 🟡 上传/轮询真，结果不消费 |
| 学习 Study | ✅ | ✅ | ✅ | 🟡 | mock | 🟡 练习入口弹窗占位 |
| 设置 Settings | ✅ | ✅ | ✅ | ⚪ | 硬编码数组 | ⚪ 全部是「后续阶段加入」弹窗 |
| Tutor（live） | ✅ | ✅ | ✅ | ✅ | **真实后端** | ✅ 功能完整 |
| Tutor（mock，`-useMockTutor`） | ✅ | ✅ | ✅ | ✅ | `MockQuestionProvider` | ⚪ 仅离线/UI 测试 |
| 草稿本 | ✅ | ✅ | ✅ | ✅ | 本机 PencilKit | ✅ |
| 错题列表/详情 | ❌ | — | — | — | — | 🔴 不存在 |
| 知识详情 | ❌ | ❌ | — | — | — | 🔴 不存在 |
| Practice | ❌ | — | — | — | — | 🔴 不存在 |

### 关键源码证据

- `HaoXue/Core/State/DemoScenarioStore.swift`：`var home: HomeState { stage == .lessonCompleted ? GoldenDemoFixtures.homeAfter : GoldenDemoFixtures.homeBefore }`；`subjects` 是写死的数学 0.78 / 化学 0.69 / 物理 0.84。
- `HaoXue/Core/Data/LiveDataProvider.swift`：`fetchHome/fetchAnalysis/fetchTutorSession/fetchPracticeSession` **四个方法全部 `throw ProviderError.contractNotConfigured`**——这是唯一一个「Live」命名的 provider，实际是空壳，且没有任何地方使用它。
- `HaoXue/Core/Models/AnalysisResponse.swift`：只解码 `analysis_id / status / progress / error`，**没有 `question_results` / `knowledge_changes` / `new_wrong_questions` / `next_action` / `warnings` 字段**。这正是「后端有、前端看不到」的根因。
- `HaoXue/Features/Learning/StudyView.swift`：`Button("开始练习") { showingPracticeInfo = true }` → `.alert("练习即将开放", ...)`。
- `HaoXue/Features/Scan/ScanView.swift`：`scanResult` 视图文案 = 「分析结果预览 / 完整题目结果将在后续集成阶段接入」。
- `HaoXue/App/AppShellView.swift`：`store.startLesson()` 只在 `-useMockTutor` 时调用；`store.finishLesson()` **只被 `TutorView.swift`（mock tutor）第 210 行调用**——所以 live 模式下首页的「最近变化」永远不会出现。
- `HaoXue/Features/Tutor/TutorRemoteService.swift`：`TutorCreateRequestDTO(sourceType: "knowledge_point", knowledgePointId: nil, ...)` —— 前端**从不指定知识点**，完全由服务端推荐决定。这一点在运行中被证实：同一台设备两次进入 Tutor，服务端分别给出「导数与函数性质综合应用」和「根据极值或最值条件求参数」，与线上 `/home` 的 `next_action` 一致。

---

## 7. Frontend ↔ Backend Integration Gaps

**App 一共只调用了 5 个 endpoint**（grep `api/v1` 全量结果）：

| 已接 | 位置 |
|---|---|
| `POST /api/v1/homework/analyses` | `Core/Services/AnalysisService.swift` |
| `GET /api/v1/homework/analyses/{id}` | `Core/Services/AnalysisService.swift` |
| `POST /api/v1/tutor/sessions` | `Features/Tutor/TutorRemoteService.swift` |
| `POST /api/v1/tutor/sessions/{id}/turns` | `Features/Tutor/TutorRemoteService.swift` |
| `GET /api/v1/knowledge/mastery-overview` | `Core/Services/MasteryOverviewService.swift` |

**后端已实现但前端从未调用的**（部分列举）：`GET /home`、`GET /knowledge`、`GET /knowledge/{id}`、`GET/PATCH /wrong-questions*`、`POST /practice/sessions`、`POST /practice/sessions/{id}/answers`、`GET /tags`、`GET /books`、`POST /books/{id}/redeem`、`POST /ai/chat`、`GET /meta/error-codes`、`GET /meta/knowledge-points`、`GET /homework/batches`、`GET /homework/analyses`（历史列表）。

### 逐条 gap（按影响排序）

1. **首页数据源**：后端 `GET /api/v1/home` 返回真实的 `next_action` / `knowledge_summary` / `weakest` / `stats`；线上实测 `next_action` 指向「根据极值或最值条件求参数」。iOS 首页读的是 `GoldenDemoFixtures`。→ 演示脚本的最后一幕无法发生。
2. **扫描结果的 90% 被丢掉**：后端 `question_results`（题干/选项/学生答案/正确答案/正确性/知识点/错误类型/诊断/解析/置信度/图片 URL）、`knowledge_changes`、`new_wrong_questions`、`next_action`、`warnings` 全部下发；iOS DTO 不解码，UI 只有一句「完整题目结果将在后续集成阶段接入」。
3. **错题本无入口**：后端有 `wq_*` 记录（线上 `wrong_question_count=1`，且详情含 `can_start_tutor`）。App 首页「错题」卡片的两条内容是 `DemoScenarioStore.recentWrongQuestions` 硬编码文本，且不可点击。
4. **知识详情无入口**：`/knowledge/{id}` 已经能回答「为什么是 43%」（`evidence[]` + `error_patterns` + `mastery_explanation`）。App 无任何界面。
5. **Practice 完全没有前端**：后端选题/判分/解析/Evidence/`tag_changes` 全部就绪且线上验证过。App 侧**连 DTO 和 API 客户端都不存在**（`Core/Data/DataProviders.swift` 里的 `PracticeDataProviding` 协议是死的）。
6. **Tutor 会话起点掌握度不可见**：`POST /tutor/sessions` 的 `knowledge_changes` 为空数组，所以 `RemoteTutorViewModel.currentMastery` 在首轮为 `nil`，页脚掌握度条**第一次回答前不显示**；要等到第一次作答返回 `knowledge_changes` 才出现。（`PHASES.md` 里「掌握度展示：等待后端后续开发」这一条，实际影响范围比文档描述小——它只影响会话第一屏。）
7. **`answering_turn_id` 未传**：契约强烈建议回传正在作答的 `turn.turn_id` 以区分「网络重试」和「真的答下一题」。iOS 只用了 `Idempotency-Key`，少了第二层保护。
8. **无鉴权**：后端无 token 会落到 Demo 用户（刻意设计），App 也就完全不带 token——单机演示没问题，但 `/auth/guest` 的多设备能力浪费了。
9. **错误码映射不全**：`ServiceErrorCode` 只映射 8 个码，后端实际有 18 个（`GET /meta/error-codes` 可运行时拉取，未使用）。`ANALYSIS_FAILED` 在 iOS 里被当成一个码，但后端并不抛这个码（后端抛 `VLM_TIMEOUT` / `QUESTION_NOT_RECOGNIZED` / `INVALID_IMAGE`）。

---

## 8. Mock / Placeholder Inventory

只列**影响产品路径**的：

| 位置 | 类型 | 是否影响 demo 路径 |
|---|---|---|
| `Core/State/DemoScenarioStore.swift` 全部字段（subjects 78/69/84、nextStepDetail、recentWrongQuestions、learningSettings…） | hardcoded demo | ✅ **影响**：首页/学习/设置全部来自这里 |
| `Resources/GoldenDemo/GoldenDemoFixtures.swift` | fixture | ✅ 影响：首页 `homeBefore/homeAfter` 的唯一来源 |
| `Core/Data/LiveDataProvider.swift` 4 个 `throw .contractNotConfigured` | stub | ✅ 影响：真实的「Live provider」并不存在 |
| `Core/Data/MockDataProvider.swift` | 测试用 | ⚪ 不直接影响（未被生产路径调用） |
| `Features/Scan/ScanView.swift::scanResult` 占位卡片 | placeholder | ✅ 影响：Scene 4 Evidence 无法展示 |
| `Features/Scan/ScanView.swift::demoPage()`（演示模式合成页） | debug helper | ⚪ 仅演示模式可见 |
| `Features/Learning/StudyView.swift` 练习 alert | placeholder | ✅ 影响：Scene 7 完全缺失 |
| `Features/Settings/SettingsView.swift` 统一弹窗 | placeholder | ⚪ 影响面子，不影响闭环 |
| `Features/Tutor/TutorView.swift` + `MockQuestionProvider` | 离线 tutor | ⚪ 需 `-useMockTutor` 才启用（设计正确） |
| `AppConfiguration.demoBackendURL` 硬编码 IP | hardcoded | ⚪ 演示可接受，但换网络环境即失效 |
| 后端 `app/seed/demo_cache/` **目录不存在** | 缺失的 fallback | ✅ 影响：`DEMO_CACHE_ENABLED=true` 默认开启，但没有任何缓存文件，`_load_demo_cache()` 永远返回 `None`（`save_demo_cache()` 全项目**无调用者**）。即「AI 挂了也能离线演示」这条保险目前**是不存在的**（本地 mock 模式上传实测直接 `failed / VLM_TIMEOUT`）。 |
| 后端 `app/seed/demo.py`（`POST /api/v1/demo/seed`） | 有意的演示种子 | ⚪ 这是设计而非缺陷 |
| 后端题库 73 道题 id 不合规范 → 启动告警并改用题干指纹 | 设计取舍 | ⚪ 功能安全 |

---

## 9. Phase Audit

| Phase | 计划内容 | 实际完成 | 剩余 | Verdict |
|---|---|---|---|---|
| 0 Bootstrap & Contract Freeze | 双端骨架、契约冻结 | 双端可独立启动、文档齐全、无 secret | — | ✅ COMPLETE |
| 1 iOS Shell & Mock Flow | 4 Tab + 各页 mock | 全部存在且渲染正常 | — | ✅ COMPLETE |
| 2 Scan & Image Preparation | 相机/相册、矫正、多图、上传更多、压缩、进度 UI | 全部实现；矫正算法有单测（`testClippedPageAgainstDarkBackgroundIsCorrected` 等） | 真机相机权限体验未在设备上验证 | ✅ COMPLETE |
| 3A Tutor Foundation | Mock 题、状态机、草稿本 | 完成 | — | ✅ COMPLETE |
| 3B Adaptive Tutor Backend | 真实 Session、SSE、4 层补救、同键回放 | 全部实现且**真机走通 6 步到总结** | `answering_turn_id` 未传；首屏掌握度不显示 | 🟡 **PARTIAL（很接近完整）** |
| 3（整体，含 Practice） | Tutor + Practice + 草稿本 | Tutor ✅ / 草稿本 ✅ / **Practice 只有弹窗** | 整个 Practice | 🟡 PARTIAL |
| 4 Backend Core & AI | 上传、VLM、识别、诊断、Evidence、Knowledge State、错题、Tutor、Practice、DB | 全部实现且线上真模型验证 24/24 | — | ✅ **COMPLETE（后端）** |
| 5 Product Completion & Demo Hardening | 错题 UI、知识详情、Home 聚合、设置演示、额度、错误/空态、缓存 fallback、固定样本 | ⚪ 只有部分空态/错误态（扫描失败文案、Tutor 重试） | 错题 UI、知识详情、Home 聚合、离线缓存 | 🔴 基本未做 |
| 6 Frontend/Backend Integration | DTO、Upload、Analysis、Home、Knowledge、Tutor、Practice、掌握度、连续 3 次闭环 | 上传 + Analysis 进度 + Tutor + 综合掌握度已提前完成 | Home、Knowledge、错题、Practice；**连续 3 次闭环 0/3** | 🟡 PARTIAL（约 40%） |
| 7 Final UI Polish & Motion | 间距、动效、Haptics、无障碍 | 已有一些动效（Scan 分页 spring、Turn 切换、进度动画、掌握度条），但**§7 的验收条件都没做**（未做 Figma QA、未做 Dynamic Type/无障碍检查、未做连续无 crash 测试） | 全部 | 🔵 未开始（有零星实现） |

---

## 10. Phase 4 Verdict

```text
Phase 4 verdict: COMPLETE
```

理由：

1. 规划要求的每一项（统一上传、VLM、题目/作答识别、知识点映射、错误诊断、Evidence、Knowledge State、Wrong Questions、Tutor Session、Practice、数据库持久化）在后端都能在代码里找到明确实现，并且**不是 mock 实现**。
2. 线上环境（MySQL + 真 VLM `Qwen/Qwen3-VL-32B-Instruct` + 真 LLM `DeepSeek-V3.2`）实跑 `tools/e2e_live.py`：**24 项检查 0 失败**，其中包含真实图片识别、真实知识状态变化、真实错题入库。
3. Definition of Done 三条全部满足：「一套真实导数选择题样本可稳定分析」✅（9.3 s，答案 C 正确）、「Tutor 可根据 A-D 回答生成下一步」✅（真机实测 `simplify/1 层`）、「Knowledge State 可产生前后变化」✅（`83.4% → 73.7%`、`41% → 46%`）。

需要分开写清的两件事：

- **Backend Phase 4 completeness：COMPLETE。**
- **User-visible product completeness：明显落后。** Phase 4 交付的能力里，只有 Tutor 与「综合掌握度」到达了用户；上传分析到达了用户但结果被丢弃；知识树、错题、练习、首页聚合 100% 停留在 API 层。
- 哪些 Phase 4 能力「因为前端没消费而变成 backend-only」：错题详情、知识点详情 / mastery 解释、练习全链路、首页 `next_action` / `weakest` / 趋势、AI 直连、图书额度。
- 提前完成的 Phase 5/6 内容：Tutor 真实接入（原属 Phase 6）、扫描上传与轮询（原属 Phase 6）、`mastery-overview`（原属 Phase 5/6）、扫描失败态与 Tutor 重试态（原属 Phase 5）、部分动效（原属 Phase 7）。
- 因此 **可以**在 `PHASES.md` 里把 Phase 4 标记为完成（并在 note 里注明「后端完成、前端未消费」），但**不应**顺手把 Phase 5/6 的框也勾上。

---

## 11. Demo Flow Verification

对照 `DEMO_PLAN.md` 的 15 步叙事逐箭头判定（全部基于本次真机 + 线上实测）：

| # | 箭头 | 结果 | 证据 |
|---|---|---|---|
| 1 | 启动 好学 | ✅ | 4 Tab 正常 |
| 2 | 扫描作业 | ✅ | 真实上传 + 真实 5 阶段进度 → 100% |
| 3 | AI 理解题目 | ✅（后端） | 线上 VLM 正确返回题干/选 A/正确 C |
| 4 | 发现问题知识点 | ✅（后端） | `knowledge_changes` 落到 `monotonicity` |
| 5 | 知识掌握度变化 | 🟡 | 服务端变了（83.4%→73.7%），App 只显示“你的学习状态已经更新” |
| 6 | 开始个性化 Tutor | ✅ | 真机创建 Session，且知识点 = 服务端 `next_action` |
| 7 | 用户答错 | ✅ | 选 B → `is_correct=false` |
| 8 | Tutor 自适应 | ✅ | `strategy=simplify`、进入「第 1/4 层」、换更简单题目 |
| 9 | 用户学会概念 | ✅ | 补救答对 → 完整解析 + `answer_reveal` |
| 10 | 个性化练习 | ❌ | App 无 Practice；点按钮弹「练习即将开放」 |
| 11 | 答对练习 | ❌ | 同上 |
| 12 | 生成 Evidence | 🟡 | Tutor 独立练习会产生，但演示脚本指望的「练习」这一步不存在 |
| 13 | 掌握度提升 | ✅ | Tutor 总结页 `41% → 46%` + 综合 `60%` |
| 14 | 回到首页 | ✅ | 可返回 |
| 15 | 首页反映更新后的掌握度 | ❌ | 首页仍写死 43% / 78% / 69% / 84%，`finishLesson()` 在 live 模式永不调用 |

**结论：15 步中 9 步完全可用、2 步部分可用、4 步失败。断点在 Scene 7（Practice）与 Scene 8（首页回写），以及 Scene 4 的 Evidence 展示。**

---

## 12. Bugs / Risks Found

（按要求：只记录，不修复。）

### P0 — 直接阻断 demo

1. **首页与后端完全解耦** —— `DemoScenarioStore.home` 永远是本地 fixture；`finishLesson()` 在 live 路径无调用者。演示最后一幕（Next Step 改变）注定失败。
2. **Practice 完全缺失** —— `DEMO_PLAN.md` Scene 7 无法演出；后端 `POST /practice/sessions` 就绪却无人调用。
3. **扫描结果被丢弃** —— `AnalysisResponse` 未解码 `question_results` / `knowledge_changes` / `new_wrong_questions` / `next_action`，Scene 4「6 题 5 对 1 需关注」与错题入场都展示不出来。

### P1 — 重要

4. 错题本无任何界面（后端已有数据，详情接口含 `can_start_tutor`）。
5. 知识详情页缺失（无法回答「为什么是 43%」，而这正是产品叙事里最重要的一句话）。
6. Tutor 首轮不显示掌握度（`knowledge_changes` 为空 → `currentMastery=nil`）。
7. Tutor 会话不传 `answering_turn_id`，少一层重复作答保护。
8. 首页/学习页显示的掌握度（43%）与后端真实值（本次实测 41%→46%，综合 60%）**不一致**，现场若两处都展示会自相矛盾。

### P2 — 打磨

9. `demo_cache` 目录不存在且 `save_demo_cache()` 无调用者 → 配置里承诺的离线 fallback 实际不可用。
10. `backend/README.md` 声称 29 个测试（实际 199），文档漂移。
11. `ServiceErrorCode` 只映射 8/18 个错误码；`ANALYSIS_FAILED` 是前端自造码。
12. 设置页 7 个条目点进去是同一个「后续阶段加入」弹窗。
13. `HomeView` 展示化学/物理百分比，仅用小字「其他学科为演示数据」免责；`REQUIREMENTS.md` 要求「不得将其描述为已实现真实能力」——勉强合规但容易被评委误读。
14. 两个 DeprecationWarning（`starlette.testclient` / `HTTP_422` 常量）。

### P3 — 可选

15. `LiveDataProvider` 是死代码，容易让后来者误以为「Live 集成已经做了」。
16. `AppConfiguration.demoBackendURL` 硬编码公网 IP，无环境切换。
17. 后端题库 73 道题 id 不符合录入标准（启动告警，功能已兜底）。
18. App 完全不使用鉴权，Demo 用户回退在多设备场景下会串数据。

---

## 13. Recommended Revised Phase Plan

现实是：**Phase 4 已完成，而 Phase 5/6 的工作被混在一起做了一半。** 建议把剩余路线重排为「先补前端集成 → 再补练习 → 最后加固」：

### Phase 5′ — Core Frontend Integration（最高优先级）

- **目标**：把已经跑起来的后端能力接到用户看得见的地方。
- **Scope**：
  1. `HomeState` DTO + `HomeService` 接 `GET /api/v1/home`（`next_action` / `knowledge_summary` / `weakest` / `recent_wrong_questions` / `stats`）。
  2. 扫描结果页消费 `question_results` + `knowledge_changes` + `new_wrong_questions`（题干、选项、学生答案、正确答案、诊断、知识点、掌握度变化）。
  3. 错题列表 + 详情页（`GET /wrong-questions`、`GET /wrong-questions/{id}`、`PATCH` 置为 resolved），详情页接「开始学习」→ `POST /tutor/sessions {source_type: wrong_question}`。
  4. 知识点详情页（`GET /knowledge/{id}`），展示 `evidence`、`error_patterns`、`mastery_explanation`。
- **NOT do**：不做动画、不重做视觉、不引入新状态管理框架、不碰后端字段。
- **验收**：首页数字来自服务端（可用 `/home` 的返回值逐字段核对）；扫描完成后能看到题目与掌握度变化；错题点进去能看到诊断并能起 Tutor。

### Phase 6′ — Practice & Closed Loop

- **目标**：把练习补齐，让 15 步演示闭环真正闭合，并连续跑通 3 次。
- **Scope**：`POST /practice/sessions`（不传 `knowledge_point_id` 走标签推荐）+ 作答 + 解析 + `knowledge_changes` + 下一题 + 完成态；显示 `target_tag`（「本次专练：XXX」）与 `tag_changes`。
- **NOT do**：不做自定义题目生成、不做错题本自动归档动画、不做多题型。
- **验收**：`DEV_PLAN Phase 6` 的「上述闭环至少连续成功 3 次，不需要开发者手动改数据库」达成，且每次都回到首页能看到新数字。

### Phase 7′ — Demo Hardening & Reliability

- **目标**：让现场不翻车。
- **Scope**：落地 `demo_cache`（跑一次真 VLM 后 `save_demo_cache()`，并把它接进失败路径）/ 或明确的降级到本地 fixture 的开关；固定测试图片与固定结果核对；网络异常、AI 超时、Session 过期的可演示兜底；`ServiceErrorCode` 补齐并改为从 `/meta/error-codes` 拉取。
- **NOT do**：不做新功能。
- **验收**：拔网线仍能走完演示；断点重试不重复计分。

### Phase 8′ — Visual Polish & Motion

- **目标**：舞台上看起来完成度高。
- **Scope**：Figma QA、间距/字体、Scan 分页与进度过渡、Tutor turn 过渡、掌握度数字动效、草稿本过渡、Haptics、Dynamic Type 基础检查。
- **原则**：**删动画，不删闭环。**

---

## 14. Recommended Next Phase

> **Phase 5′ — Core Frontend Integration，第一步只做一件事：把首页接到 `GET /api/v1/home`。**

为什么是它：

1. 它是**唯一一个能同时提升「演示完整性」最多的动作**——演示的最后一句台词是「回到首页，Next Step 变了」，而现在这个数字压根不会变。
2. 后端已经返回了首页需要的**全部**内容（`next_action` / `knowledge_summary` / `recent_wrong_questions` / `stats`），是纯展示层工作，不是算法工作。
3. 它顺手解决 P1-8（两处掌握度自相矛盾）。
4. 改完之后，扫描与 Tutor 产生的真实数据第一次有了「落点」，后续错题页、知识详情页也都能挂在同一个 `HomeState` 上，边际成本递减。

顺序建议：**首页 → 扫描结果 → 错题/知识详情 → Practice**。

---

## 15. Final Readiness Summary

```text
Backend Core:           95%
Frontend UI:            55%
Frontend Integration:   35%
Core Learning Loop:     45%
Demo Readiness:         45%
UI Polish:              35%
Overall P0 Readiness:   50%
```

主要依据：

- **Backend Core 95%**：199 测试全绿、线上 24/24 真模型检查通过、MySQL 已部署；扣分项是 demo cache 缺失与文档漂移。
- **Frontend UI 55%**：4 Tab、扫描、Tutor、草稿本的视觉与交互完成度高，构建 0 warning；但错题/知识/Practice 三个页面不存在，设置与结果页是占位。
- **Frontend Integration 35%**：后端 40+ 接口里前端只用了 5 个；Tutor 与上传是真实集成，其余能力域 0 集成。
- **Core Learning Loop 45%**：`扫描 → 上传 → 分析 → Tutor 自适应 → 掌握度变化` 这段**真实可跑**（本次真机全程验证）；但 `→ 练习 → Evidence → 首页回写` 这段缺失，闭环断在最后 40%。
- **Demo Readiness 45%**：15 步演示里 9 步可用、2 步部分、4 步失败；舞台上能演「AI 真的看懂了作业并因材施教」，但演不出「练完以后学习状态改变了」的收尾。
- **UI Polish 35%**：已有部分动效，Phase 7 的 QA 与无障碍检查未做。
- **Overall P0 Readiness 50%**：按 `REQUIREMENTS.md` 的 10 条 Definition of Done 逐条算：1 ✅、2 ✅（但是假数据）、3 ✅、4 ✅、5 🟡、6 ✅、7 ✅、8 ✅（Tutor 内可见）、9 ✅、10 🔴（无可靠 fallback）——约 5.5/10。

---

## 附：审计证据文件

```
audit/screenshots/01-home-mock.jpg                  首页（写死的 78/69/84 与 43%）
audit/screenshots/02-tutor-concept-live.jpg          真实后端 Tutor 首轮（服务端题目）
audit/screenshots/03-tutor-complete-mastery-live.jpg 会话完成：41% → 46%（服务端值）
audit/screenshots/04-scan-analysis-complete-live.jpg 真实扫描分析 100% 完成
audit/screenshots/05-practice-placeholder.jpg        「练习即将开放」占位
audit/screenshots/06-study-mock-mastery.jpg          学习页仍显示 mock 43%
audit/screenshots/07-settings-placeholder.jpg        设置页全为演示条目
audit/screenshots/08-scratchpad.jpg                  PencilKit 草稿本
audit/screenshots/09-tutor-second-session-live.jpg   第二次 Tutor（服务端换成另一个知识点）
```

后端测试与线上脚本原始输出：`/tmp/haoxue_e2e_live.txt`

**审计到此结束。按 §19 的要求，本次没有开始实现任何推荐阶段内容。**
