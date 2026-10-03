# 好学 — PHASE CHECKLIST

## Phase 0 — Bootstrap & Contract Freeze ✅

- [x] Git / remote 检查
- [x] iOS 工程骨架
- [x] Backend 工程骨架
- [x] API 边界确定
- [x] 文档落库
- [x] Commit

## Phase 1 — iOS Shell & Mock Flow ✅

- [x] 4 Tab
- [x] Home
- [x] Scan
- [x] Learn
- [x] Settings
- [x] Tutor 基础 UI
- [x] Mock Data
- [x] Commit

## Phase 2 — Scan & Image Preparation ✅

- [x] Camera / Document Scan
- [x] Perspective Correction
- [x] 多图预览
- [x] 上传更多
- [x] 图片压缩
- [x] Analysis Progress UI
- [x] Commit

## Phase 3 — Tutor / Practice / Scratchpad 🟡

- [x] Tutor A-D
- [x] Free Text UI only
- [ ] Practice UI（移至 Phase 6 完成）
- [x] Mastery UI
- [x] PencilKit
- [x] Clear Confirmation
- [x] Commit

## Phase 4 — Backend Core & AI ✅

- [x] Upload
- [x] VLM
- [x] Question Recognition
- [x] Diagnosis
- [x] Evidence
- [x] Knowledge State
- [x] Wrong Question
- [x] Tutor Session
- [x] Practice
- [x] DB
- [x] Live VLM / LLM E2E verification
- [x] Commit

> 后端 Phase 4 已完成；尚未被 iOS 展示的能力由 Phase 5 / 6 负责接入，不重复实现后端核心。

## Phase 5 — Core Frontend Integration

- [x] Live Home / Next Step
- [x] Full Analysis Result DTO
- [x] Scan Result UI
- [x] Knowledge Change display
- [x] Wrong Questions list / detail
- [x] Knowledge Detail
- [x] Tutor `answering_turn_id` cleanup and session restore
- [x] Remove production Home fixture dependency
- [x] Commit

Tutor 会话 ID 按后端来源上下文保存在当前 App 进程内；重新进入同一来源时通过 `GET /api/v1/tutor/sessions/{id}` 恢复当前结构化回合。跨 App 冷启动恢复不属于当前实现范围。

## Phase 6 — Practice & Closed Learning Loop ✅

- [x] Practice DTO / API Client（phase-6a）
- [x] Practice Session UI（phase-6b）
- [x] Answer / Explanation（phase-6c）
- [x] Knowledge / Tag Changes（phase-6c）
- [x] Next Question / Completion（phase-6c）
- [x] Refresh Home after learning（phase-6d）
- [x] 3 consecutive successful end-to-end runs（phase-6e，隔离 guest）
- [x] Commit

## Phase 7 — Product Surface & Commercial Demo

- [ ] Book / Question Bank Store
- [ ] Book Detail / Unlock Demo
- [ ] Subscription Demo (e.g. ¥20 all workbook questions)
- [ ] Learning Credits Demo
- [ ] Settings completion
- [ ] About This App / Version
- [ ] Privacy / Focus / Screen Time display entries
- [ ] Remove generic placeholder alerts
- [ ] Commit

> Phase 7 允许完全使用 iOS 本地 Demo State，不要求后端商业接口、StoreKit 或真实支付。

## Phase 8 — Online Demo Reliability & QA

> Phase 8 拆成 8A（契约同步 + 缺失 Demo 功能）与 8B（联网稳定性 QA）。

### Phase 8A — Backend Contract Sync & Missing Demo Features ✅

- [x] Analysis 契约同步：`stages[].state` 支持 `retrying`，`progress.retrying` /
      `retry_note` 已接入进度卡片（`retrying` 不等于失败）
- [x] `correctness` 五值（correct / wrong / partial / unanswered / unknown）
      在 DTO → Domain → Presentation 全程区分，`unanswered` 不再与 `unknown` 合并
- [x] `possible_answer` / `possible_answer_source` 接入（仅提示，不参与算分）
- [x] `unanswered_count` 接入分析结果统计
- [x] `tag_changes` v2（`tag_scores` / `tag_deltas`，已移除 `delta`）接入练习结果
- [x] `turn.remedial_exhausted` 改为读布尔字段，不再比较 `turn_type`
- [x] Scan 右上角「历史记录」入口 + `ScanHistoryView`，数据来自
      `GET /api/v1/homework/batches?limit=50`
- [x] 历史详情复用同一个 `AnalysisResultView` / Domain Model / 结果接口
- [x] unknown 标准答案人工确认：接入后端 `confirm-answer`（Contract `8A-final`，commit 629f99e）
      —— 选择/确认两步、提交中禁用、`Idempotency-Key` 重试、成功后重拉分析结果
- [x] 4 个新错误码（`QUESTION_NOT_FOUND` / `INVALID_ANSWER` /
      `QUESTION_NOT_CONFIRMABLE` / `QUESTION_ALREADY_RESOLVED`）进入 `ServiceErrorCode`
- [x] Commit（`phase-8: sync backend contract and add scan history` 等 4 个 commit）

### Phase 8B — Online Reliability QA

- [x] Production demo backend endpoint verified（health `status: ok` / `llm_mode: live`；
      `/home`、`/homework/batches`、`/knowledge` 读取正常）
- [x] 固定样张真实上传：`题目/示例题目1.png` + `示例题目2.png` + `示例题目3.jpg`（3 张）
      —— App 真实路径（照片选择 → 准备 → 上传 → 轮询 → 结果）完成 2 次，
      成功 1 批（batch 4：3 张图 / 11 题 / 218s），另一批（batch 5）在后端分析服务
      崩溃期间卡在 processing，未计入成功次数
- [x] Analysis 状态机：`queued / processing / retrying / completed / failed` 实测无不可恢复状态，
      历史列表里真实渲染出 `retrying` 文案（「正在用 deepseek-flash 重试（3/3）」）
- [x] Network / AI timeout error UI（失败批次真实渲染 `VLM_TIMEOUT` + 原因文案 + 重试入口）
- [x] Retry path verified（扫描失败 retry 复用同一 `Idempotency-Key`；
      `409 IDEMPOTENCY_CONFLICT` 等 1 秒原样重发，均有单测覆盖）
- [x] Duplicate submission / Evidence safety（同一答案重复确认 → `replayed: true`，
      `home.stats.total_evidence` 18 → 18 不增长）
- [x] Confirm-answer 连续 3 次真实 E2E（App UI 路径：unknown → 选答案 → 确认 →
      重拉分析结果 → summary 变化，`correct 1→3`、`unknown 10→6`、新建错题同步进 Home）
- [x] Tutor / Practice 真实路径（Tutor：答错后服务端切补救层「第 1/4 层」+ 掌握度 19%→18%；
      Practice：session → 出题 → 作答 → 判定/解析 → 下一题，v2 `tag_changes` 不再解码失败）
- [x] HaoXueUITests 与当前产品一致（3 个历史失败已修：废弃 Settings 文案断言、
      依赖线上「第 17 题」的硬编码，改为不依赖具体题号的数据断言 + 无数据时 `XCTSkip`）
- [ ] Golden Demo 连续 10 次（**未达成**：后端分析服务在测试期间崩溃，
      按人类要求停止上传，等待后端修复后重跑）
- [x] Commit

> 比赛不要求离线模式；不把 Cached / Mock 自动 fallback 作为 Phase 8 验收项。

## Phase 9 — Final UI Polish & Motion

- [ ] Figma QA
- [ ] Typography / Spacing
- [ ] Scan motion
- [ ] Tutor / Practice motion
- [ ] Mastery animation
- [ ] Scratchpad transition
- [ ] Haptics if time
- [ ] Accessibility / Dynamic Type basic check
- [ ] Demo device crash test
- [ ] Final Commit
