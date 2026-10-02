# Phase 0 Frontend Bootstrap Implementation Plan 咩

> **For agentic workers:** REQUIRED SUB-SKILL：实施时使用 superpowers:executing-plans 或经人类选择的 superpowers:subagent-driven-development，逐任务执行，checkbox 用于记录实际结果，本计划尚待审阅与执行方式选择咩

**Goal：** 保留 HaoXue 工程，在 Phase 0 内建立可验证的 Mock→Domain→presentation 启动路径和未来 Live adapter seam 咩

**Architecture：** View 只消费 ViewModel 的 presentation state，ViewModel 依赖小型 Provider protocol，Provider 向上返回 Domain 咩
Mock 使用 Swift fixtures，Live 暂时抛出 contractNotConfigured，未来在内部组合 APIClient、DTO 与 Mapper 咩

**Tech Stack：** 现有 Swift / SwiftUI、Observation、Foundation URLSession、async/await、Swift Testing、XCTest、Xcode MCP，无新增第三方依赖咩

**Spec：** `Docs/superpowers/specs/2026-10-02-phase-0-frontend-design.md`，修订 commit 为 `fd7ca49` 咩

## Global Constraints 咩

- 保留 `iOS App/HaoXue/HaoXue.xcodeproj`、Scheme `HaoXue` 与三个现有 target，不重建 project 咩
- 保留现有 deployment target `27.0`、Swift version `5.0`、`SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`、签名与 bundle identifier `com.TNTstudio.personalLearningAgent.HaoXue` 咩
- Backend 是 Source of Truth，不实现 Backend、Agent、LLM、VLM、数据库、OCR、判题、学习诊断、掌握度或教学策略算法咩
- 43% 与 51% 是 fixtures 中固定的 Mock server-like result，不计算变化值或学习权重咩
- Domain 字段是 Frontend 语义，不冻结最终 endpoint、JSON key、response schema 或 error envelope，不编造生产 DTO 咩
- Phase 0 不建设通用 networking framework，只实现证明 Live seam 所需的最小 transport，client request ID 无 consumer 时仅留设计说明咩
- Tutor 自由文本不进入提交接口，提交、上传、轮询、重试、认证与幂等实现均延后咩
- 不实现正式 4 Tab 或 Phase 1 UI，真实 integration 留到 Phase 6，视觉与 motion 留到 Phase 7 咩
- timeout 测试直接 stub `URLError(.timedOut)`，不得真实等待、sleep 或依赖外部网络咩
- 只本地提交，不 push，不提交协调 URL、secret、私密图像、LOCAL_COORDINATION 或 Xcode 用户状态咩

## Review Focus 咩

1. 未知 Upload 状态或 Tutor phase 必须保留原始值，不能误判为 completed，任务 1 测试覆盖咩
2. 掌握度未提供必须保持 nil，不能显示为 0%，任务 1 测试覆盖咩
3. 未知 Mock ID 与 Live 未配置不得静默返回成功或 Mock，任务 2/3 测试覆盖咩
4. transport 超时、取消、非 HTTP response、HTTP 失败与坏 JSON 要分开表达，任务 3 测试覆盖咩
5. 启动加载失败或取消不能显示 Mock Data Ready，View 不直接访问数据层，任务 4 测试与代码审阅覆盖咩

## 文件安排与测试调用咩

以下路径均相对于仓库根目录，产品源码基目录为 `iOS App/HaoXue/HaoXue`，测试基目录为 `iOS App/HaoXue/HaoXueTests`，UI 测试目录为 `iOS App/HaoXue/HaoXueUITests` 咩

| 文件 | 职责 |
| --- | --- |
| HaoXue/Core/Models/LearningModels.swift | Home、知识摘要、变化、错题咩 |
| HaoXue/Core/Models/AnalysisModels.swift | 分析状态与题目结果咩 |
| HaoXue/Core/Models/SessionModels.swift | Tutor、Practice 与结构化选项咩 |
| HaoXue/Core/Data/DataProviders.swift | 四个小型读取协议和 ProviderError 咩 |
| HaoXue/Core/Data/MockDataProvider.swift | 固定 Domain 快照读取咩 |
| HaoXue/Core/Data/LiveDataProvider.swift | 未接入的可注入骨架咩 |
| HaoXue/Resources/GoldenDemo/GoldenDemoFixtures.swift | 统一 Demo 故事咩 |
| HaoXue/Core/Networking/APIClient.swift | 最小 transport、解码、网络错误咩 |
| HaoXue/Core/Networking/Adapters/DomainMapper.swift | 泛型 DTO→Domain seam 咩 |
| HaoXue/App/AppConfiguration.swift | Mock 默认模式与可选 base URL、timeout 配置咩 |
| HaoXue/App/HaoXueApp.swift | 从当前入口移动并替换示例，注入依赖咩 |
| HaoXue/Features/Development/DevelopmentViewModel.swift | 启动 loading/ready/error 咩 |
| HaoXue/Features/Development/DevelopmentView.swift | 三行最小占位 UI 咩 |
| HaoXue/Components/README.md | 后续组件归属说明咩 |
| HaoXueTests/DomainBoundaryTests.swift、GoldenDemoProviderTests.swift | Domain 与 Mock 验证咩 |
| HaoXueTests/NetworkingBoundaryTests.swift、DevelopmentViewModelTests.swift | transport 与 presentation 验证咩 |

表中以 HaoXue 或 HaoXueTests 开头的路径实际加上 `iOS App/HaoXue/` 前缀，例如首项为 `iOS App/HaoXue/HaoXue/Core/Models/LearningModels.swift` 咩

实施前调用 Xcode MCP `session_show_defaults({})`，缺失或错误时按已发现工程设置 projectPath、scheme、simulator 与临时 derivedDataPath，不能把机器配置提交到仓库咩

每次红/绿测试使用 `test_sim({extraArgs:["-only-testing:HaoXueTests/<测试套件>"]})`，尚未实现类型时预计编译失败并记录未定义符号，实现后必须显示测试成功，不能把编译失败当成运行中的 assertion failure 咩

若 session defaults 完整，遵循 MCP 的首次运行要求执行 `build_run_sim({})`，后续任务不重复基线，最终修改后再做完整验证咩

## Task 1：Domain 与前向兼容语义咩

**Files：** 创建上述三个 Core/Models 文件与 `iOS App/HaoXue/HaoXueTests/DomainBoundaryTests.swift` 咩

**Interfaces：** 值类型遵循 Equatable，数组型字段默认空数组，ID 使用 String，mastery/progress 使用 Double?，时间使用 Date，字段以 spec 第 6 节为准咩

- `HomeState(nextStep: String, subjects: [SubjectSummary], knowledgePoints: [KnowledgePoint], recentWrongQuestions: [WrongQuestion], recentChanges: [KnowledgeChange])` 咩
- `SubjectSummary(id: String, name: String, summary: String)`，`KnowledgePoint(id: String, name: String, mastery: Double?, trend: String?, evidenceSummary: String?, recommendedAction: String?)`，`KnowledgeChange(knowledgePointID: String, beforeMastery: Double?, afterMastery: Double?, summary: String)` 咩
- `WrongQuestion(id: String, content: String, source: String, studentAnswer: String?, correctAnswer: String?, knowledgePointIDs: [String], diagnosis: String?, timestamp: Date)` 咩
- `UploadAnalysis(id: String, status: AnalysisStatus, stageDescription: String?, questions: [QuestionResult], knowledgeChanges: [KnowledgeChange], recommendation: String?, errorCode: String?)` 咩
- `QuestionResult(id: String, content: String, choices: [TutorChoice], studentAnswer: ChoiceID?, correctAnswer: ChoiceID?, isCorrect: Bool?, knowledgePointIDs: [String], diagnosis: String?)` 咩
- `ChoiceID` 仅 A/B/C/D，`TutorChoice(id: ChoiceID, text: String)`，`TutorSource` 为 knowledgePoint(String)、wrongQuestion(String)、uploadedQuestion(String)、recommendation(String) 咩
- `TutorSession(id: String, source: TutorSource, knowledgePointID: String, currentTurn: TutorTurn)`，`TutorTurn(id: String, type: String, text: String, choices: [TutorChoice]?, phase: TutorPhase, progress: Double?, completed: Bool, knowledgeChange: KnowledgeChange?)` 咩
- `PracticeQuestion(id: String, content: String, choices: [TutorChoice], knowledgePointIDs: [String])`，`PracticeResult(isCorrect: Bool, explanation: String, knowledgeChange: KnowledgeChange?, nextAction: String?)`，`PracticeSession(id: String, currentQuestion: PracticeQuestion?, progress: Double?, completed: Bool, result: PracticeResult?)` 咩
- `AnalysisStatus` 和 `TutorPhase` 提供 spec 中已知 cases、`unknown(String)` 与 `init(rawValue: String)`，仅解释内部语义，不代表 Backend 字段解析已定咩

- [ ] 写测试 `unknownStatesPreserveRawValue`、`missingMasteryRemainsAbsent`，核心 assertions 如下咩

```swift
#expect(AnalysisStatus(rawValue: "future_status") == .unknown("future_status"))
#expect(TutorPhase(rawValue: "future_phase") == .unknown("future_phase"))
#expect(KnowledgePoint(id: "kp", name: "导数", mastery: nil,
    trend: nil, evidenceSummary: nil, recommendedAction: nil).mastery == nil)
```

- [ ] 运行 DomainBoundaryTests，确认缺少类型导致红阶段失败咩
- [ ] 实现上述模型与状态，不添加 Codable、计算属性或权威数据算法咩
- [ ] 运行 DomainBoundaryTests，确认通过且四个 analysis cases、六个 Tutor phase 已知值可逐项表达咩
- [ ] 检查 diff，仅暂存 Task 1 的模型和测试，提交 `phase-0: define frontend domain boundaries` 咩

## Task 2：Mock Provider 与 Golden Demo 咩

**Files：** 创建 DataProviders.swift、MockDataProvider.swift、GoldenDemoFixtures.swift 与 GoldenDemoProviderTests.swift，移除现有 HaoXueTests.swift 的空模板测试咩

**Consumes：** Task 1 的 Domain 值类型咩
**Produces：** `@MainActor` 的 HomeDataProviding.fetchHome() async throws -> HomeState、AnalysisDataProviding.fetchAnalysis(id: String) async throws -> UploadAnalysis、TutorDataProviding.fetchTutorSession(id: String) async throws -> TutorSession、PracticeDataProviding.fetchPracticeSession(id: String) async throws -> PracticeSession 咩

`ProviderError` 至少含 unknownFixtureID(String)、contractNotConfigured，MockDataProvider 遵循四个协议，`init(home: HomeState = GoldenDemoFixtures.homeBefore)` 支持明确选取学习前后快照咩

GoldenDemoFixtures 提供 homeBefore、homeAfter、analysisQueued、analysisProcessing、analysisCompleted、analysisFailed、tutorDiagnose、tutorTeach、tutorCompleted、practiceQuestion、practiceCompleted，快照 ID 固定且唯一，错题与知识点引用一致，时间固定为 2026-10-02 00:00:00 UTC 咩

- [ ] 写 `goldenStoryIsConsistent` 和 `unknownFixtureFails` 测试，关键 assertions 如下咩

```swift
#expect(GoldenDemoFixtures.homeBefore.knowledgePoints.first?.mastery == 0.43)
#expect(GoldenDemoFixtures.homeAfter.knowledgePoints.first?.mastery == 0.51)
#expect(GoldenDemoFixtures.analysisCompleted.questions.count == 6)
#expect(GoldenDemoFixtures.analysisCompleted.questions.filter { $0.isCorrect == true }.count == 5)
#expect(GoldenDemoFixtures.homeBefore.nextStep != GoldenDemoFixtures.homeAfter.nextStep)
```

- [ ] 运行 GoldenDemoProviderTests，确认缺少 Provider/fixture 类型导致失败咩
- [ ] 实现协议、错误、Swift fixtures 与 Mock 读取，未知 ID 抛 unknownFixtureID，Mock 不按答案判题、不自动更新 mastery、不模拟时间推进咩
- [ ] 运行 GoldenDemoProviderTests，验证四种 analysis、Tutor 教学调整文字、完成快照、Practice 固定正确结果，以及所有 Mock 读取返回对应快照，未知 ID 必须抛错咩
- [ ] 检查 diff，按 Files 暂存并提交 `phase-0: add golden demo fixtures and mock providers` 咩

## Task 3：最小 transport、Mapper 与 Live seam 咩

**Files：** 创建 APIClient.swift、DomainMapper.swift、LiveDataProvider.swift、AppConfiguration.swift 与 NetworkingBoundaryTests.swift 咩

**Consumes：** Task 1 Domain、Task 2 四个协议与 ProviderError 咩
**Produces：** `@MainActor final class APIClient`，`init(session: URLSession = .shared, timeout: TimeInterval = 30)`，`send<DTO: Decodable>(_ request: URLRequest, as: DTO.Type) async throws -> DTO` 咩

调用方提供 URLRequest，APIClient 只套用 timeout、调用 session.data(for:)、检查 HTTP response 与 200...299 状态、解码 DTO，不建设 Endpoint 类型或复杂 builder 咩

`NetworkError` 为 invalidResponse、transport(URLError.Code)、cancelled、timeout、httpStatus(Int)、decoding；业务错误码用 `ServiceErrorCode` 已知 cases 与 unknown(String) 表达，由未来 Mapper 使用，不猜 error envelope 咩

`DomainMapper` 使用 associatedtype DTO: Decodable、Domain，并暴露 `map(_ dto: DTO) throws -> Domain`，测试专用 payload/mapper 留在测试 target 咩

`AppConfiguration` 含 mode: DataMode（mock/live）、baseURL: URL?、timeout: TimeInterval，默认 mock/nil/30，base URL 外部注入，不加自动环境探测、生产地址、认证或 client request ID 代码咩

`@MainActor LiveDataProvider.init(client: APIClient, configuration: AppConfiguration)` 接受依赖、遵循四个协议，每个读取都抛 ProviderError.contractNotConfigured，当前不使用 baseURL 发请求咩

- [ ] 写 NetworkingBoundaryTests，测试专用 Decodable payload 为 `ProbeDTO(value: String)`，success stub 返回 `{"value":"probe"}`，测试 Mapper 把 probe 映射为测试用 String 咩
- [ ] timeout stub 直接调用 URLProtocol client 的 didFailWithError，使用 `URLError(.timedOut)`，断言捕获的错误为 NetworkError.timeout，不使用等待咩
- [ ] 写 HTTP 503、坏 JSON、非 HTTP response、URLError.cancelled、CancellationError、普通 URLError.notConnectedToInternet 的独立 stub，分别断言 httpStatus(503)、decoding、invalidResponse、cancelled、cancelled、transport(.notConnectedToInternet) 咩
- [ ] 写 `liveNeverRequestsOrFallsBack`，注入会在收到请求时令测试失败的 stub，调用四个 Live 读取均必须抛 contractNotConfigured，断言请求未发生咩
- [ ] 运行 NetworkingBoundaryTests，确认尚未实现类型导致失败咩
- [ ] 实现上述最小边界，测试 URLSession 使用 ephemeral 配置与独立 URLProtocol 子类，避免共享可变响应状态导致并行测试干扰，测试结束 invalidate session 咩
- [ ] 运行 NetworkingBoundaryTests，确认成功、错误映射、Mapper seam 和 Live 行为均通过，所有请求仅发给测试 stub 咩
- [ ] 检查 diff，按 Files 暂存并提交 `phase-0: add minimal transport and live provider seam` 咩

## Task 4：最小开发占位页与注入咩

**Files：** 移动并修改现有 HaoXueApp.swift 为 App/HaoXueApp.swift，删除原 ContentView.swift 与 Item.swift，创建 DevelopmentViewModel.swift、DevelopmentView.swift、Components/README.md、DevelopmentViewModelTests.swift，修改现有 HaoXueUITests.swift 咩

**Consumes：** HomeDataProviding、MockDataProvider、LiveDataProvider、AppConfiguration、APIClient 咩
**Produces：** `@MainActor @Observable final class DevelopmentViewModel`，`init(provider: any HomeDataProviding)`、`load() async`、只读 state: DevelopmentState（loading、ready、error）咩

DevelopmentView 接收 ViewModel，通过 `.task` 调用 load，只有成功获取 Home Domain 后显示 Mock Data Ready，文案为「好学」「Development Build」与状态，error 显示简短加载失败说明咩

App 在 composition root 默认组装 Mock→ViewModel→View，mode 为 live 时组装 APIClient→Live→ViewModel→View，View 不访问配置或具体 Provider，Preview 使用注入 Mock 咩

- [ ] 写 `successfulHomeLoadsReady`、`failedHomeLoadsError`、`cancelledLoadDoesNotBecomeReady`，分别注入成功/失败/取消 Home Provider，并断言 load 后 state 为 ready/error/非 ready 咩
- [ ] 运行 DevelopmentViewModelTests，确认缺少 ViewModel 导致失败咩
- [ ] 实现 ViewModel 并在错误与取消分支中保留非 ready 状态，不缓存或计算 Home 权威数据咩
- [ ] 替换示例与 App 注入，只创建必要目录，Components README 不扩展 UI 功能，保留 assets 与 Xcode 配置咩
- [ ] 把模板 UI 测试换为 `testDevelopmentPlaceholderLoadsMock`，启动 App 并用 XCTest 的元素等待断言「好学」「Development Build」「Mock Data Ready」存在，移除模板启动性能测试咩
- [ ] 运行 DevelopmentViewModelTests 与 `test_sim({extraArgs:["-only-testing:HaoXueUITests/HaoXueUITests/testDevelopmentPlaceholderLoadsMock"]})`，确认 presentation 与启动数据路径通过咩
- [ ] 检查 View 内没有 Provider、fixtures、DTO、APIClient 调用，检查源码没有 SwiftData 或 Item 引用，暂存本任务文件并提交 `phase-0: replace sample with development placeholder` 咩

## Task 5：Phase 0 验收、公开文档与最终提交咩

**Files：** 创建 `Docs/PHASE_0_FRONTEND_REPORT.md`，审查并纳入现有公开 Docs、iOS 工程源码/资源/工程配置与测试，不纳入 ReferenceUIs 图片或私密文件咩

**Consumes：** Tasks 1–4 的编译可用基础设施与已记录结果咩
**Produces：** 实际 Build / Launch / Tests、Git 与 ownership 检查报告，最终 Phase 0 commit 咩

- [ ] 调用 Xcode MCP session_show_defaults，确认实际 HaoXue Scheme 与 simulator，再 `build_run_sim({})`，必须 SUCCEEDED 与启动成功咩
- [ ] `test_sim({extraArgs:["-only-testing:HaoXueTests","-only-testing:HaoXueUITests/HaoXueUITests/testDevelopmentPlaceholderLoadsMock"]})`，必须相关测试全部通过，记录真实结果，不用 UI snapshot 取代测试咩
- [ ] 编写简洁报告，按原请求列出 Git、Architecture、Domain/Contract、Mock、Networking、Backend Coordination、Build/Tests、Files、Deferred、Commit 与 Phase 0 状态，明确仅验收 Frontend，尚未真实 integration 咩
- [ ] 执行 `git status --short`、`git remote -v`、`git diff`、`git diff --cached`、`git diff --check`，检查公开文档与源码不含真实 secret，`git check-ignore Docs/LOCAL_COORDINATION.md` 必须命中，`git ls-files Docs/LOCAL_COORDINATION.md` 必须为空咩
- [ ] 逐文件审查既有公开 Docs 后加入 Git，逐文件暂存 App、Tests、UI Tests、pbxproj、workspace contents 与 assets，不用 `git add -A` 把未审查 ReferenceUIs 混入提交，报告说明有意保留的未跟踪参考图片咩
- [ ] 暂存后再次检查 staged diff 和清单，若有额外代码修改则重新 Build/Test，否则复用本任务已通过的结果咩
- [ ] 报告仅记录最终 commit message `phase-0: bootstrap project and freeze contracts`，无需写最终 hash，可注明「final hash reported after commit」，避免自引用咩
- [ ] 仅在验收完成后提交 `phase-0: bootstrap project and freeze contracts`，实际 hash 在提交后的终端与最终汇报中单独报告，不写回报告、不为自身 hash 创建额外 commit、不 amend 历史，不修改其他队友负责的文件，不 push，并停止于 Phase 0 咩

## 自查与执行交接咩

spec 各节对应：工程/目录/注入为任务 4，Domain 为任务 1，Provider/fixtures 为任务 2，Networking/Mapper/Live 为任务 3，Git/验收/延后边界为任务 5 咩

四个协议、Domain 名称、错误和测试断言在任务间使用相同签名，五项 Review Focus 均已绑定具体测试或审阅动作，未添加业务 endpoint 或生产 DTO 咩

本轮仅编写计划，不创建上述产品或测试 Swift 文件，执行前由人类审阅本计划并选择 Native 或 Subagent-driven 方式咩

推荐 Native：四个核心任务紧密共享 Domain 与 Provider 接口，当前变更局限于同一 App target，由本会话依次实施可减少交接成本咩
