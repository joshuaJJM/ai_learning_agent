# Phase 0 — Frontend Bootstrap 设计规格咩

日期：2026-10-02，当前阶段为设计审阅，尚未批准实施咩

## 1. 目标与依据咩

为好学的 iOS Frontend 建立可独立使用 Mock 开发、未来可嫁接 Backend 的最小工程基础，完成后严格停在 Phase 0 咩

依据为 Docs 中的 AGENTS、README、PROJECT_CONTEXT、REQUIREMENTS、DESIGN、ARCHITECTURE、DEVELOPMENT_PLAN、PHASES、API_CONTRACT、GIT_WORKFLOW、LOCAL_COORDINATION、DEMO_PLAN，以及人类本轮确认的十项原则咩

Backend 是学习数据的 Source of Truth，Frontend 展示后端提供的掌握度、诊断、正确性与教学结果，不计算这些权威数据咩

本次规格提交只包含本文件与根目录忽略规则，产品代码保持原样，规格获批准后才进入 writing-plans 阶段咩

## 2. 已确认的工程基线咩

- 工作区没有发现已有 `.git`，可按项目规则初始化 Git，origin 使用 `https://github.com/joshuaJJM/ai_learning_agent` 咩
- 工程为 `iOS App/HaoXue/HaoXue.xcodeproj`，Scheme 为 `HaoXue`，包含 App、HaoXueTests、HaoXueUITests 三个 target 咩
- 源文件使用 Xcode 文件系统同步组，现有 App 使用 SwiftData 的 Item 示例，测试为模板咩
- 保留现有 bundle identifier、签名、deployment target、target 与工程配置，不重建 project 咩
- 已通过 Xcode MCP 的 `build_run_sim` 在 iPhone 18 Pro / iOS 27.2 上完成修改前 Build / Launch，返回 SUCCEEDED，耗时约 66.6 秒咩
- UI 快照因模拟器自动化 session 超时失败，此项不构成当前 blocker，也不代表完成了界面内容验证咩

## 3. 方案选择咩

采用现有 App target 内的 Swift 源文件、值类型 Domain 模型、小型 Provider 协议与 Swift fixtures，保持无需第三方依赖的开发路径咩

另建 Swift Package 会增加 target 和并发隔离配置成本，JSON fixtures 会引入额外 fixture schema 与解码维护，本阶段均不采用咩

## 4. 目录与职责咩

所有产品实现放在现有 `iOS App/HaoXue/HaoXue` 同步组中，目录按实际文件需求建立咩

| 位置 | 职责 |
| --- | --- |
| App | App 入口、配置和 Provider 注入咩 |
| Core/Models | 纯业务 Domain 值类型与语义状态咩 |
| Core/Data | 小型 Provider 协议、Mock、Live 骨架咩 |
| Core/Networking | 请求、URLSession transport、解码与类型化错误咩 |
| Core/Networking/Adapters | DTO 到 Domain 的转换接口咩 |
| Features/Development | 极小占位 View 与 presentation model 咩 |
| Resources/GoldenDemo | Swift Domain fixtures 咩 |
| Components | 用简短 README 说明后续可复用 UI 所属，不创建无用 Swift 组件咩 |

把现有 App 入口移入 App，移除 SwiftData Item、ModelContainer 和示例列表，将其替换为开发占位页，不创建本地学习数据库咩

## 5. 数据流与注入咩

```text
未来 Backend JSON → Codable DTO → Mapper → Domain → Provider → ViewModel → View
当前 Swift fixtures → Mock Provider → Domain → ViewModel → Development View
```

占位 View 只消费 presentation state，显示「好学」「Development Build」和加载成功后的「Mock Data Ready」，不直接读取 fixture 或调用 APIClient 咩

App composition root 负责选择 Mock 或 Live 并注入依赖，默认使用 Mock，配置与学习业务数据分离咩

占位页仅实现 loading、ready、error 三种启动验证状态，加载异步调用小型 Home Provider，不增加正式 Home 内容或 Tab 导航咩

## 6. Domain 语义边界咩

以下名称和字段表示 Frontend 业务语义，不是 Backend 最终 JSON key，也不要求 Domain 遵循 Codable 咩

| 模型 | 最小语义 |
| --- | --- |
| HomeState | 下一步建议、学科摘要、知识点摘要、最近错题、最近变化咩 |
| SubjectSummary | ID、学科名称、后端给出的知识摘要咩 |
| KnowledgePoint | ID、名称、可缺省的掌握度、趋势、证据摘要、建议动作咩 |
| KnowledgeChange | 知识点 ID、前后掌握度、变化说明咩 |
| WrongQuestion | ID、题干、来源、学生答案、正确答案、知识点 ID、诊断、时间咩 |
| UploadAnalysis | ID、状态、可缺省的阶段说明、题目结果、知识变化、建议、可缺省的机器错误码咩 |
| QuestionResult | ID、题干、选项、学生答案、正确答案、正确性、知识点 ID、诊断咩 |
| TutorSession | ID、来源、关联知识点 ID、当前 turn 咩 |
| TutorTurn | ID、turn 类型、正文、可缺省选项、phase、可缺省进度、完成标记、可缺省知识变化咩 |
| TutorChoice | A/B/C/D 标识与文字，用于 Tutor 与 Practice 的选择项咩 |
| PracticeSession | ID、当前题、可缺省进度、完成标记、可缺省提交结果咩 |
| PracticeQuestion | ID、题干、A-D 选项、知识点 ID 咩 |
| PracticeResult | 服务器给出的正确性、解释、可缺省知识变化与下一步建议咩 |

掌握度和进度在 Domain 中按 0 到 1 表达，未提供时为 nil，绝不把缺失数据当作 0%，未来 Mapper 负责转换已确认的后端单位咩

Upload 状态明确表达 queued、processing、completed、failed，另保留 unknown 原始状态以应对未来新增值，不能把未知状态映射为成功咩

Tutor phase 表达 diagnose、teach、concept_check、guided_practice、independent_practice、completed，并保留 unknown 原始值，不在 Frontend 自动推进教学阶段咩

Tutor 来源表达 knowledge point、wrong question、uploaded question 与 next-step recommendation 的引用，自由文本不进入提交接口咩

## 7. Provider 边界咩

按消费场景划分 Home、Analysis、Tutor、Practice 四个小型异步读取协议，分别提供 Home 快照、指定 analysis 快照、指定 Tutor session、指定 Practice session 咩

MockDataProvider 与 LiveDataProvider 可同时遵循这些小协议，各 ViewModel 只依赖实际需要的协议，不定义包揽所有能力的 God Protocol 咩

Phase 0 的 Mock 返回预定义快照，对未知 fixture ID 返回类型化错误，不构建真实 Tutor 决策器或 Practice 判题逻辑咩

Tutor / Practice 的提交、图片上传与轮询在后续阶段补充协议，届时 A-D 作为结构化选择提交，Phase 0 不创建无消费方的完整交互 API 咩

LiveDataProvider 接受 networking 依赖，但其业务读取方法明确抛出 contractNotConfigured，不猜测 endpoint，不发出业务请求，也不静默回退为 Mock 咩

## 8. Golden Demo fixtures 咩

fixtures 是 Frontend Mock Domain Data，由固定 ID、固定时间和不可变 Swift 值组成，不能称为真实 Backend response 咩

提供初始 Home、四种 analysis 状态、完成分析、Tutor 诊断与教学调整及完成快照、Practice 题目与成功结果、学习后的 Home 快照咩

故事为「导数与单调性 43% → 识别 6 题、5 对 1 错 → 导数符号到函数性质薄弱 → Tutor 错答后更简单的引导 → 完成引导 → Practice 答对 → 51% 与新的下一步建议」咩

正确性、诊断、教学调整与 43% / 51% 都是直接写入 fixture 的模拟服务器结果，不通过用户作答、题数或权重计算咩

Tutor 调整快照供 Phase 1/3 消费，Phase 0 不实现回答驱动的分支控制器，后续 fallback 可复用相同 fixtures 咩

## 9. Networking 与 Adapter 咩

提供可注入 URLSession 的最小 APIClient，使用 async/await 和泛型 Decodable 接收结果，支持配置 base URL、HTTP method、相对路径、headers、可选 body、timeout 与可选 client request ID 咩

base URL 由 App 配置外部注入，默认 Mock 不需要 base URL，不写入协调服务地址，也不硬编码未确认的业务服务地址咩

错误类型区分配置无效、transport、取消、timeout、HTTP 非成功状态、decoding、未接入 contract 与机器业务错误码，保留未知机器错误码，不按中文文案匹配咩

已知业务错误码表达 INVALID_IMAGE、ANALYSIS_FAILED、VLM_TIMEOUT、QUESTION_NOT_RECOGNIZED、SESSION_EXPIRED、SERVER_ERROR，网络层不猜测服务端错误 envelope，未来 Adapter 解析正式错误 DTO 咩

定义最小 DTO→Domain 映射协议，DTO 仅在后端最终 schema 确认后实现，Phase 0 不编造生产 DTO、endpoint 或 JSON sample 咩

以测试专用 Codable payload 验证 transport 解码和 Mapper seam，明确其属于测试数据，不能作为正式 API_CONTRACT 咩

不实现自动重试、幂等行为、认证系统、上传协议或 integration flow，client request ID 仅预留传递能力咩

## 10. Git 与私密文件咩

初始化 Git 前再次确认没有已有历史，设置 canonical origin，仅进行本地提交，不 push 或 force push 咩

根目录忽略规则覆盖 `.env`、`.env.*`、LOCAL_COORDINATION.md、Xcode 用户状态、构建产物、私密图片与演示数据目录、常见私钥文件，`.env.example` 只允许安全 placeholder 咩

ignore 不能识别任意源码内的 token，因此每次提交还必须检查 staged diff 与文件清单，协调 URL 和真实 secret 不进入 tracked file 咩

当前规格提交不纳入既有 Swift、图片或其余项目文档，后续 Phase 0 收尾提交再审查应纳入的工程与公开文档咩

## 11. Backend 协调与未冻结项咩

当前业务语义足以建立边界，尚未与 Backend AI 沟通，当前没有需要阻塞本规格的字段问题咩

最终 endpoint、JSON key、response schema、error envelope、服务端单位与提交幂等约定保持未冻结，Live 骨架明确反映这一状态咩

后续如出现语义或 ownership 疑问，使用本地忽略文件或环境变量中的协调入口发送简洁机器可读消息，稳定结论同步到 API_CONTRACT，不公开协调凭证咩

## 12. 验证与验收咩

实施后通过 Xcode MCP 核对 session defaults 和 Scheme，以实际 simulator 执行 build_run_sim，必须真实构建并启动成功咩

使用现有 Tests target 验证 Mock 读取与未知 ID 错误、Demo 快照一致性、Live 未接入错误、网络成功解码及 HTTP/解码/超时错误、DTO→Domain 测试 seam 咩

网络测试注入 URLProtocol 或等价 stub，不请求真实 Backend，启动 UI test 验证占位页出现 Mock Data Ready，不进行性能基准或视觉 polish 咩

运行相关 `test_sim` 并记录实际结果，单独的 UI snapshot 超时不作为 blocker，但 build 或相关 tests 失败必须报告并修复，不能把未运行测试标为通过咩

Git 验收包括 origin 正确、LOCAL_COORDINATION 未 tracked、私密文件忽略有效、staged diff 已检查，以及最终 Phase 0 commit 成功咩

Frontend 验收包括 Domain 与状态语义、四类小接口、Mock fixtures、Live skeleton、networking 和 Mapper seam 都编译可用，启动数据路径可验证，且未实施后端或 Phase 1 UI 咩

本规格审阅通过后先编写实施计划并确认执行方式，再进入代码实现，最终使用 `phase-0: bootstrap project and freeze contracts` 提交并停止咩

## 13. 明确延后咩

完整 4 Tab、正式 Home/Scan/Learn/Settings/Tutor/Practice、错题和知识 UI、扫描与图片预处理、PencilKit、动画、视觉 polish、商业展示与支付均留给对应后续 Phase 咩

Backend、数据库、Agent、VLM、LLM、OCR、掌握度算法、学习诊断、判题和教学决策由另一位队友及 Backend AI 负责，不属于本次或后续 Frontend 的实施内容咩

真正 Frontend / Backend integration 保留到 Phase 6，最终视觉与 motion 保留到 Phase 7 咩
