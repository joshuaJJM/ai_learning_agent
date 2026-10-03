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

- [ ] Fixed demo samples verified
- [ ] Production demo backend endpoint verified
- [ ] Network / AI timeout error UI
- [ ] Retry path verified
- [ ] Duplicate submission / Evidence safety
- [ ] Consecutive live demo crash test
- [ ] P0 / P1 bug cleanup
- [ ] Commit

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
