import SwiftUI

@MainActor
struct AppShellView: View {
    let store: DemoScenarioStore
    @State private var tutorPresentation: TutorPresentation?
    @State private var selectedTab = 0
    @State private var tutorSessionIDs: [TutorEntryContext: String] = [:]
    @State private var tutorCreateKeys: [TutorEntryContext: String] = [:]
    @State private var pendingTutorWrongQuestionID: String?
    @State private var pendingTutorKnowledgePointID: String?
    @State private var selectedRecord: LearningRecordRoute?
    @State private var recordPath: [LearningRecordRoute] = []
    @State private var tutorReturnRecord: LearningRecordRoute?
    @State private var tutorReturnPath: [LearningRecordRoute] = []
    @State private var practicePresentation: PracticePresentation?
    @State private var practiceSessionIDs: [PracticeEntryContext: String] = [:]
    @State private var practiceCreateKeys: [PracticeEntryContext: IdempotencyKey] = [:]
    @State private var pendingPracticeAfterTutor: PracticeEntryContext?
    @State private var completionCoordinator: PracticeCompletionCoordinator?
    @State private var homeModel = HomeViewModel(provider: LiveDataProvider(
        client: APIClient(), configuration: AppConfiguration(mode: .live)))
    @State private var wrongQuestionsModel = WrongQuestionsListViewModel(provider: LiveDataProvider(
        client: APIClient(), configuration: AppConfiguration(mode: .live)))
    @State private var knowledgeOverviewModel = KnowledgeOverviewViewModel(provider: LiveDataProvider(
        client: APIClient(), configuration: AppConfiguration(mode: .live)))
    private var usesMockTutor: Bool { ProcessInfo.processInfo.arguments.contains("-useMockTutor") }

    private func openTutor(knowledgePointID: String? = nil, wrongQuestionID: String? = nil) {
        if usesMockTutor {
            store.startLesson()
            tutorPresentation = .mock
        } else if let wrongQuestionID, !wrongQuestionID.isEmpty {
            presentTutor(.wrongQuestion(wrongQuestionID))
        } else if let knowledgePointID, !knowledgePointID.isEmpty {
            presentTutor(.knowledgePoint(knowledgePointID))
        }
    }

    private func presentTutor(_ context: TutorEntryContext) {
        if tutorCreateKeys[context] == nil {
            tutorCreateKeys[context] = UUID().uuidString
        }
        tutorPresentation = .live(context)
    }

    /// One logical create per entry context: the key survives retries and re-entry,
    /// so a slow first request is replayed instead of scored twice. A backend
    /// knowledge point is forwarded as-is; without one the server recommends.
    private func presentPractice(knowledgePointID: String? = nil) {
        presentPractice(context: knowledgePointID.map { .knowledgePoint($0) } ?? .recommended)
    }

    private func presentPractice(context: PracticeEntryContext) {
        if practiceCreateKeys[context] == nil {
            practiceCreateKeys[context] = IdempotencyKey.generate()
        }
        practicePresentation = usesMockTutor ? .mock(context) : .live(context)
    }

    private func closePractice() {
        practicePresentation = nil
    }

    /// Tutor finished with a structured `continue_practice` action: the practice
    /// only opens after the lesson cover is gone.
    private func requestPracticeFromTutor(_ knowledgePointID: String?) {
        pendingPracticeAfterTutor = knowledgePointID.map { .knowledgePoint($0) } ?? .recommended
        tutorPresentation = nil
    }

    private func handleTutorDismiss() {
        if let context = pendingPracticeAfterTutor {
            pendingPracticeAfterTutor = nil
            presentPractice(context: context)
            return
        }
        restoreRecordAfterTutor()
    }

    /// Practice finished: the cover closes immediately, then the authoritative
    /// learning state is re-fetched from the backend (never patched locally).
    private func finishPractice(_ outcome: PracticeAnswerOutcome) {
        let context = practicePresentation?.context
        practicePresentation = nil
        if let context {
            practiceSessionIDs[context] = nil
            practiceCreateKeys[context] = nil
        }
        let coordinator = learningCompletionCoordinator()
        Task { await coordinator.practiceCompleted(outcome) }
    }

    private func learningCompletionCoordinator() -> PracticeCompletionCoordinator {
        if let completionCoordinator { return completionCoordinator }
        let home = homeModel
        let knowledge = knowledgeOverviewModel
        let mock = usesMockTutor
        let coordinator = PracticeCompletionCoordinator(
            refreshHome: {
                // Mock/Development configuration has no live backend to re-GET.
                if mock { return true }
                await home.refresh()
                return home.phase == .loaded
            },
            refreshKnowledge: {
                if mock { return true }
                await knowledge.refresh()
                return knowledge.phase == .loaded
            })
        completionCoordinator = coordinator
        return coordinator
    }

    private func openWrongQuestion(_ id: String) {
        recordPath = []
        selectedRecord = .wrongQuestion(id)
    }

    private func openKnowledge(_ id: String) {
        recordPath = []
        selectedRecord = .knowledge(id)
    }

    private func openKnowledgeOverview() {
        recordPath = []
        selectedRecord = .overview
    }

    private func closeTutor(completed: Bool = false) {
        if completed, case .live(let context) = tutorPresentation {
            tutorSessionIDs[context] = nil
            tutorCreateKeys[context] = nil
        }
        tutorPresentation = nil
        if !usesMockTutor {
            Task {
                await homeModel.refresh()
                if knowledgeOverviewModel.phase == .loaded { await knowledgeOverviewModel.refresh() }
            }
        }
    }

    private func startTutorFromRecord(knowledgePointID: String? = nil, wrongQuestionID: String? = nil) {
        tutorReturnRecord = selectedRecord
        tutorReturnPath = recordPath
        pendingTutorKnowledgePointID = knowledgePointID
        pendingTutorWrongQuestionID = wrongQuestionID
        selectedRecord = nil
    }

    private func restoreRecordAfterTutor() {
        guard let route = tutorReturnRecord else { return }
        tutorReturnRecord = nil
        recordPath = tutorReturnPath
        tutorReturnPath = []
        selectedRecord = route
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            Group {
                if usesMockTutor {
                    DemoHomeView(store: store) { openTutor() }
                } else {
                    HomeView(model: homeModel, onStartTutor: { openTutor(knowledgePointID: $0) },
                             onStartPractice: { presentPractice(knowledgePointID: $0) },
                             onOpenWrongQuestion: openWrongQuestion,
                             onOpenKnowledge: openKnowledge)
                }
            }
            .tabItem { Label("首页", systemImage: "house") }
            .tag(0)
            NavigationStack {
                ScanView(store: store, onStart: { openTutor(knowledgePointID: $0) },
                         onOpenWrongQuestion: openWrongQuestion,
                         onOpenKnowledge: openKnowledge,
                         onStartPractice: { presentPractice(knowledgePointID: $0) },
                         onReturnHome: { selectedTab = 0 })
            }
                .tabItem { Label("扫描", systemImage: "viewfinder") }
                .tag(1)
            Group {
                if usesMockTutor {
                    StudyView(store: store, onStart: { openTutor() },
                              onStartPractice: { presentPractice() })
                } else {
                    WrongQuestionsView(model: wrongQuestionsModel, onOpen: openWrongQuestion,
                                       onOpenKnowledgeOverview: openKnowledgeOverview,
                                       onStartPractice: { presentPractice() })
                }
            }
                .tabItem { Label("学习", systemImage: "book.closed") }
                .tag(2)
            SettingsView(store: store)
                .tabItem { Label("设置", systemImage: "gearshape") }
                .tag(3)
        }
        .tint(.blue)
        .onChange(of: selectedTab) { _, tab in
            if tab == 0, !usesMockTutor { Task { await homeModel.refresh() } }
            if tab == 2, !usesMockTutor { Task { await wrongQuestionsModel.refresh() } }
        }
        .sheet(item: $selectedRecord, onDismiss: {
            if let id = pendingTutorKnowledgePointID {
                pendingTutorKnowledgePointID = nil
                openTutor(knowledgePointID: id)
            } else if let id = pendingTutorWrongQuestionID {
                pendingTutorWrongQuestionID = nil
                openTutor(wrongQuestionID: id)
            }
        }) { route in
            NavigationStack(path: $recordPath) {
                recordView(route)
                    .navigationDestination(for: LearningRecordRoute.self) { destination in
                        recordView(destination)
                    }
            }
        }
        .fullScreenCover(item: $tutorPresentation, onDismiss: handleTutorDismiss) { presentation in
            switch presentation {
            case .mock:
                TutorView(store: store, provider: MockQuestionProvider()) { closeTutor() }
            case .live(let context):
                RemoteTutorView(
                    service: TutorRemoteService(baseURL: AppConfiguration.demoBackendURL,
                                                knowledgePointID: context.knowledgePointID,
                                                wrongQuestionID: context.wrongQuestionID),
                    masteryService: MasteryOverviewService(baseURL: AppConfiguration.demoBackendURL),
                    existingSessionID: tutorSessionIDs[context],
                    createKey: tutorCreateKeys[context] ?? UUID().uuidString,
                    onSessionReady: { tutorSessionIDs[context] = $0 },
                    onStartPractice: requestPracticeFromTutor,
                    onClose: { closeTutor(completed: $0) })
            }
        }
        .fullScreenCover(item: $practicePresentation) { presentation in
            let context = presentation.context
            switch presentation {
            case .mock:
                PracticeSessionView(provider: MockDataProvider(),
                                    onSessionReady: { practiceSessionIDs[context] = $0 },
                                    onFinish: finishPractice,
                                    onClose: closePractice)
            case .live:
                PracticeSessionView(
                    provider: LiveDataProvider(client: APIClient(),
                                               configuration: AppConfiguration(mode: .live)),
                    existingSessionID: practiceSessionIDs[context],
                    knowledgePointID: context.knowledgePointID,
                    createKey: practiceCreateKeys[context] ?? IdempotencyKey.generate(),
                    onSessionReady: { practiceSessionIDs[context] = $0 },
                    // Phase 6D: use the completed outcome to refresh Home / Knowledge
                    // and to run `next_action`.
                    onFinish: finishPractice,
                    onClose: closePractice)
            }
        }
        .overlay(alignment: .top) {
            if let coordinator = completionCoordinator, let notice = coordinator.notice {
                PracticeCompletionBanner(
                    notice: notice,
                    onRetry: { Task { await coordinator.refreshLearningState() } },
                    onDismiss: { coordinator.dismissNotice() })
                    .padding(.horizontal, 16)
                    .padding(.top, 6)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .task(id: notice) {
                        guard notice == .refreshed else { return }
                        try? await Task.sleep(for: .seconds(6))
                        if coordinator.notice == notice { coordinator.dismissNotice() }
                    }
            }
        }
        .animation(.easeInOut(duration: 0.2), value: completionCoordinator?.notice)
    }

    @ViewBuilder
    private func recordView(_ route: LearningRecordRoute) -> some View {
        switch route {
        case .wrongQuestion(let id):
            WrongQuestionDetailView(
                id: id, provider: LiveDataProvider(client: APIClient(),
                    configuration: AppConfiguration(mode: .live)),
                onStartTutor: { id in
                    startTutorFromRecord(wrongQuestionID: id)
                },
                onOpenKnowledge: { recordPath.append(.knowledge($0)) },
                onChanged: {
                    Task {
                        await wrongQuestionsModel.refresh()
                        await homeModel.refresh()
                    }
                })
        case .knowledge(let id):
            KnowledgeDetailView(
                id: id, provider: LiveDataProvider(client: APIClient(),
                    configuration: AppConfiguration(mode: .live)),
                onOpenWrongQuestion: { recordPath.append(.wrongQuestion($0)) },
                onStartTutor: { id in
                    startTutorFromRecord(knowledgePointID: id)
                })
        case .overview:
            KnowledgeOverviewView(model: knowledgeOverviewModel,
                                  onOpenKnowledge: { recordPath.append(.knowledge($0)) })
        }
    }
}

private enum TutorEntryContext: Hashable {
    case knowledgePoint(String), wrongQuestion(String)

    var knowledgePointID: String? {
        if case .knowledgePoint(let id) = self { return id }
        return nil
    }

    var wrongQuestionID: String? {
        if case .wrongQuestion(let id) = self { return id }
        return nil
    }
}

private enum TutorPresentation: Identifiable {
    case mock, live(TutorEntryContext)

    var id: String {
        switch self {
        case .mock: "mock"
        case .live(.knowledgePoint(let id)): "knowledge:\(id)"
        case .live(.wrongQuestion(let id)): "wrong:\(id)"
        }
    }
}

/// Quiet, native acknowledgement that practice finished and the learning state
/// was re-read. Refresh failures keep the completion and offer a GET-only retry.
private struct PracticeCompletionBanner: View {
    let notice: PracticeCompletionCoordinator.Notice
    let onRetry: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .foregroundStyle(tint)
            Text(notice.text)
                .font(.subheadline.weight(.medium))
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("practice-completion-notice")
            Spacer(minLength: 8)
            if case .refreshFailed = notice {
                Button("重试", action: onRetry)
                    .font(.subheadline.bold())
                    .accessibilityIdentifier("practice-refresh-retry")
            }
            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(DemoStyle.secondary)
            }
            .accessibilityLabel("关闭提示")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(.regularMaterial, in: Capsule())
        .overlay(Capsule().stroke(Color(uiColor: .systemGray5)))
        .shadow(color: .black.opacity(0.06), radius: 12, y: 4)
    }

    private var icon: String {
        switch notice {
        case .refreshed: "checkmark.circle.fill"
        case .refreshFailed: "exclamationmark.circle"
        }
    }

    private var tint: Color {
        switch notice {
        case .refreshed: .green
        case .refreshFailed: .orange
        }
    }
}

private enum PracticeEntryContext: Hashable, Identifiable {
    case recommended
    case knowledgePoint(String)

    var id: String {
        switch self {
        case .recommended: "recommended"
        case .knowledgePoint(let id): "knowledge:\(id)"
        }
    }

    var knowledgePointID: String? {
        if case .knowledgePoint(let id) = self { return id }
        return nil
    }
}

private enum PracticePresentation: Identifiable {
    case mock(PracticeEntryContext)
    case live(PracticeEntryContext)

    var id: String {
        switch self {
        case .mock(let context): "mock:\(context.id)"
        case .live(let context): "live:\(context.id)"
        }
    }

    var context: PracticeEntryContext {
        switch self {
        case .mock(let context), .live(let context): context
        }
    }
}

private enum LearningRecordRoute: Hashable, Identifiable {
    case wrongQuestion(String), knowledge(String), overview

    var id: String {
        switch self {
        case .wrongQuestion(let id): "wrong:\(id)"
        case .knowledge(let id): "knowledge:\(id)"
        case .overview: "overview"
        }
    }
}
