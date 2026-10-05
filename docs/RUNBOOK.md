# 运维与排查手册

给"线上出问题了，现在怎么办"用。架构与设计见 [README.md](../README.md)，
接口契约见 [API.md](API.md)，上传链路见 [UPLOAD.md](UPLOAD.md)。

远端：`121.43.137.176:22`（用户 `hackathon`），应用目录 `~/haoxue-backend`，
监听 `17283`，MySQL 只允许服务器内连接。远端账号**不在 sudoers 里**，
所以用不了 systemd —— 是 `setsid nohup` + pidfile，外加用户级 crontab 兜底。

---

## 0. 先看这三件事

```bash
cd backend

# ① 服务活着吗
.venv/bin/python tools/remote.py service status        # RUNNING / NOT_RUNNING
curl -s http://121.43.137.176:17283/health             # status / uptime_seconds

# ② 有没有卡住的任务
.venv/bin/python tools/remote.py exec \
  "mysql ... -e \"SELECT analysis_id, status, updated_at FROM analyses \
   WHERE status IN ('queued','processing')\""

# ③ 最近有没有报错
.venv/bin/python tools/remote.py service logs | grep -aE 'ERROR|Traceback|WARNING' | tail -30
```

`/health` 里的 `uptime_seconds` 是判断**有没有重启过**的关键：
两次观测之间它变小了，就说明进程重启过。

---

## 1. ⚠️ 部署会杀掉正在跑的分析

**这是最容易踩、后果最明显的一个。**

`tools/remote.py deploy --restart` 会停掉 uvicorn。而分析跑在**进程内的后台任务**里
（FastAPI `BackgroundTasks`），跟着一起死 —— 记录停在 `processing`，前端只能转圈。

线上真实事故：演示前改一版代码部署，正好打断了一次在跑的作业分析。
前端看到的现象是「任务卡死 + 服务像崩溃重启 + uptime 清零」，
而日志里**没有任何 Traceback**（因为进程是被正常 kill 的，不是崩的）。

### 规则：部署前先确认没有分析在跑

```bash
# 有输出就等它结束再部署
.venv/bin/python tools/remote.py exec \
  "mysql ... -e \"SELECT analysis_id, status FROM analyses \
   WHERE status IN ('queued','processing')\""
```

或者看接口：`GET /api/v1/homework/batches` 里有没有 `state=processing`。

### 已经打断了怎么办

不用手工修。**下一次启动对账**会把它收成 `failed`：

```
WARNING haoxue: 启动对账：1 个分析因服务重启中断，已标记为 failed（可重试）
```

如果不想等下次重启，重启一次服务即可。用户看到的是
`error_code = ANALYSIS_INTERRUPTED`，可以**直接重传**。

---

## 2. 任务卡在 `processing`

分析**一定**会进终态，靠两道防线（见 README「分析一定会进入终态」）：

| 机制 | 触发 | error_code |
|---|---|---|
| 启动对账 | 服务启动 | `ANALYSIS_INTERRUPTED` |
| 看门狗 | 每 60 秒扫，`updated_at` 超 15 分钟 | `ANALYSIS_TIMEOUT` |

### 排查顺序

```bash
# ① 看它的最后心跳与卡在哪一步
.venv/bin/python tools/remote.py exec \
  "mysql ... -e \"SELECT analysis_id, status, updated_at, \
   JSON_UNQUOTE(JSON_EXTRACT(doc,'\$.progress.current_stage_label_zh')) AS stage, \
   JSON_UNQUOTE(JSON_EXTRACT(doc,'\$.progress.retry_note')) AS note \
   FROM analyses WHERE analysis_id='ana_xxx'\""

# ② 对照日志看那一刻在干什么
.venv/bin/python tools/remote.py service logs | grep -a 'ana_xxx'
```

- **`updated_at` 在动** → 任务是活的，只是慢。识别一页 60~105 秒是正常的。
- **`updated_at` 不动，stage 停在「已识别题目」** → 卡在 VLM 调用。等看门狗，或重启收掉。
- **日志里有一段莫名其妙的空白** → 很可能是**超时**的请求。
  httpx 只记录**完成**的请求，超时不会留下 `200 OK` 那一行。

---

## 3. 分析降级了（`retrying` / `warnings` 里有「降级」）

降级本身不是错误，但**要知道为什么**。`warnings` 里现在会带具体原因：

```
第 1 张：Qwen/Qwen3-VL-32B-Instruct 未成功
（模型端错误 HTTP 500: {"code":50507,"message":"Request failed: Unknown error."}），
已降级到 Qwen/Qwen3-VL-8B-Instruct
```

### 按原因对症

| 日志里的原因 | 含义 | 怎么办 |
|---|---|---|
| `模型端错误 HTTP 4xx/5xx` | **provider 侧**故障或限流 | 偶发；识别调用带 1 次 HTTP 重试。频繁出现就换模型（`tools/probe_models.py --vision`） |
| `模型输出被 max_tokens 截断` | 单次请求要写的 JSON 太长 | 一类题目太多，或题目描述特别长。考虑降 `MAX_IMAGE_EDGE` 或拆分图片 |
| 请求超时（**日志里只有空白**） | 单次调用超过 `LLM_TIMEOUT_SECONDS` | 整页识别实测 60~160 秒，240 秒是留了余量的；频繁超时说明 provider 在变慢 |
| `独立求解模型 … 未给出结果` | 二次校验的求解没跑通 | 看紧跟的那行日志 —— 通常是求解模型的 `max_tokens` 不够（推理模型思维链吃预算），或它回了「无法确认」 |
| `独立求解返回的 answer 无法解析: '无法确认'` | 模型自己也不确定 | **这是正常的**，判 `unknown` 是刻意的保守行为，不是 bug |

### 一个反直觉的点

**降级到更弱的模型会让 `unknown` 变多。** 因为识别质量下降后，
它与独立求解的答案分歧率上升，而分歧时我们**宁可不判分**。

实测一次：Qwen32B 被一次 HTTP 500 换掉、降到 8B 之后，
9 道题里 6 道与独立求解分歧 → **全部记成 `unknown`**（一题都没批改出来）。
根因只是一个 1 秒就能重试掉的 500。

所以看到大量 `unknown` 时，**先去 `warnings` 里找有没有「降级」**。

---

## 3.5 ⚠️ 已完成的分析被改回 failed（已修，但值得记住）

### 症状

- `questions` / `evidence` 表里数据都在（9 道题、5 条证据）
- 但 analysis 文档是 `failed` / `ANALYSIS_TIMEOUT` / **0 题** / `homework_id = null`
- `progress.percent` 退回 0.25，`questions_detected` 标成 `failed`
- **`finished_at` 等于 `updated_at`** —— 而 `_update` 只在 `finished_at` 为空时才写它，
  说明看门狗读到的那份 doc 是**完成前的快照**

### 根因：MySQL 读事务被永久钉住

`db.py` 里 MySQL 连接是 `autocommit=False`，而：

```python
def query_all(sql, params):
    return list(get_conn().execute(...).fetchall())   # ← 从不 commit / rollback
```

MySQL 默认 **REPEATABLE READ**：连接上第一次 SELECT 就开启事务并**钉住当时的数据快照**，
只要不提交，这个连接之后读到的**永远是那份旧数据**。

看门狗正是"长期只读"的线程（`asyncio.to_thread` 的线程池，连接按线程复用）：

```
22:14  看门狗首次扫描 → 钉住快照 S1（此时分析还在 processing）
22:15  分析完成（另一个连接写入并提交）→ 库里已经是 completed
22:15+ 看门狗每次扫描仍看到 S1 → "还在 processing，而且已经 15 分钟没动"
22:29  按 S1 判超时，把 S1 整个写回去 → **覆盖掉已完成的结果**
```

**修复**：`autocommit=True`（`db.py` 的 `_connect`）。
代码本来就是"每写必提交"，没有任何跨语句原子性依赖。

### 为什么"加防护"挡不住它

第一反应是给 `_fail_orphan` 加"落笔前重新读一次"。**没用** ——
重读走的是**同一个连接、同一个快照**，看起来仍然"确实该收"。
所以那个防护留着（防真正的读-改-写竞态），但**真正的修复是连接模式**。

### 怎么认出来

- 文档和 questions/evidence 对不上 → 先怀疑**连接层**，别只看业务代码
- `finished_at == updated_at` 且题数为 0 → 写回的是**完成前的快照**
- 集中出现在"服务重启后不久创建"的分析上 → 看门狗线程的快照正好钉在它们运行期间

### 教训

**读操作不留事务**应该是数据库层的不变量，而不是靠每个调用方自觉。
一个 `autocommit=False` 加上一个忘记提交的 `query_all`，
就能让"只读线程"活在一个永远不变的世界里 —— 而且它做出的判断在它自己看来完全合理。

---

## 4. 分析很慢

先看服务端的分阶段计时日志，不要猜：

```bash
.venv/bin/python tools/remote.py service logs | grep -a '耗时分解'
```

```
耗时分解：识别 73.4s（1 张图 9 题）| 二次校验 10.2s | 解析补写 0.0s
```

| 阶段 | 正常量级 | 变慢的原因 |
|---|---|---|
| 识别 | 60~105 秒（1 张 9 题） | **图片没压缩**（最大头）、provider 变慢、降级重试 |
| 二次校验 | 10~25 秒 | 未命中题库的题多（每道题一次独立求解，并发 4） |
| 解析补写 | 0~15 秒 | 判错的题多（每题一次纯文本调用，并发 4） |

同一张 4548×7067 / 6.4 MB 试卷的实测对比：

```
压缩前：上传 33.5s | 识别 162.6s | 校验 10.4s | 总 207s
压缩后：上传  4.3s | 识别  73.4s | 校验 10.2s | 总  90s
```

**识别占 78%，是唯一值得动的地方。** 压缩日志长这样：

```
图片压缩：4548x7067 6.4MB -> 1287x2000 0.3MB
```

**看不到这行** → 图片本来就在 2000 px 以内，或者 **Pillow 没装**：

```
WARNING haoxue: Pillow 未安装，图片不会被压缩 —— 大图识别会明显变慢。建议 `pip install Pillow`。
```

装上（注意用 `python -m pip`，远端 `.venv/bin/pip` 的 shim 是坏的）：

```bash
cd /home/hackathon/haoxue-backend
.venv/bin/python -m pip install Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

## 5. 健康检查与重启

```bash
.venv/bin/python tools/remote.py service status
.venv/bin/python tools/remote.py service logs
.venv/bin/python tools/remote.py service restart
curl -s http://121.43.137.176:17283/health
```

`/health` 里有 `question_count`（题库）、`llm_mode`、`backup_llm_configured`。
**`uptime_seconds` 突然变小 = 服务重启过**，这是排查"是不是崩了"的第一个证据。

重启是**安全**的：在跑的分析会被启动对账判成 `failed`（可重试），
不会留在 `processing`。

---

## 6. 重置线上环境

```bash
.venv/bin/python tools/remote.py reset          # 只打印计划，不动数据
.venv/bin/python tools/remote.py reset --yes    # 真的执行
```

做的是「**结构也重来**」：停服务 → drop 库重建 → 清 `data/uploads` 与
`service.log` → 启服务（按代码重新建表 + 跑迁移）。

- MySQL 凭据**在服务器上从 `.env` 现读**，不在本地解析、也不走命令行参数
- 不带 `--yes` 时只打印计划并返回退出码 1（防误触）
- 重置完所有业务表 0 行；`books` 会有 2 行 —— 启动时从 `seed/books.json` 自动播种的配置数据

想铺演示数据：`POST /api/v1/demo/seed`（103 条历史 Evidence，
把主干知识点压到 **43.2%**，`mastery-overview` 给 **60 分**）。

---

## 7. 上线前 / 演示前的验收

### 全量检查

```bash
cd backend
.venv/bin/python -m pytest                 # 307 passed
.venv/bin/python tools/check_docs.py       # 接口路径覆盖
.venv/bin/python tools/audit_docs.py       # 字段级完整度
.venv/bin/python tools/e2e_live.py --base http://121.43.137.176:17283   # 打真模型
```

### 连续跑固定样张（评审要求过 ≥3 次）

判据（**每一条都要看**）：

- 每次都进终态（`completed` / `failed`），没有 `processing`
- 中途 `/health` 一直可用
- 两次观测之间 `uptime_seconds` **单调增长**（说明没重启）
- 每次的 Evidence 条数稳定，且没有 `(question_id, knowledge_point_id)` 重复

实测一次真实 6.4 MB 试卷连跑 10 次的结果：

```
10/10 completed   最短 65s / 中位 92s / 最长 105s
降级 0 条   health 失败 0 次   uptime 5884s → 6784s（没重启）
Evidence 70 = 10 次 × 7 道判对的题，重复组 0
```

---

## 8. 排查时别做的事

| 别做 | 为什么 |
|---|---|
| **看日志猜原因** | 先去 `warnings` / 结构化字段里找。日志缺行（比如超时不留痕）会让你误判 |
| **指望 `httpx` 日志能看出超时** | 它只记完成的请求。**空白 = 超时** |
| **用 `deploy --restart` 时不管在跑的任务** | 会打断分析，制造"卡死 + 疑似崩溃"的假象 |
| **拿 demo 用户做绝对断言** | 测试与联调共用一个库，demo 用户的数据会跨用例累积 |
| **只跑 `check_docs.py` 就以为文档没问题** | 它只查路径。字段缺失要 `audit_docs.py` |
| **改完只看生产者** | 见 `backend/README.md` 的「三条必须守住的规则」第 3 条 |
