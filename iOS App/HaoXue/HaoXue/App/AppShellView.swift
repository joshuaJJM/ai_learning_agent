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
    @State private var practiceSessionID: String?
    @State private var practiceCreateKey: IdempotencyKey?
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

    /// One logical create per practice entry: the key survives retries and re-entry,
    /// so a slow first request is replayed instead of scored twice.
    private func presentPractice() {
        if practiceCreateKey == nil { practiceCreateKey = IdempotencyKey.generate() }
        practicePresentation = usesMockTutor ? .mock : .live
    }

    private func closePractice() {
        practicePresentation = nil
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
                         onReturnHome: { selectedTab = 0 })
            }
                .tabItem { Label("扫描", systemImage: "viewfinder") }
                .tag(1)
            Group {
                if usesMockTutor {
                    StudyView(store: store, onStart: { openTutor() },
                              onStartPractice: presentPractice)
                } else {
                    WrongQuestionsView(model: wrongQuestionsModel, onOpen: openWrongQuestion,
                                       onOpenKnowledgeOverview: openKnowledgeOverview,
                                       onStartPractice: presentPractice)
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
        .fullScreenCover(item: $tutorPresentation, onDismiss: restoreRecordAfterTutor) { presentation in
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
                    onClose: { closeTutor(completed: $0) })
            }
        }
        .fullScreenCover(item: $practicePresentation) { presentation in
            switch presentation {
            case .mock:
                PracticeSessionView(provider: MockDataProvider(),
                                    onSessionReady: { practiceSessionID = $0 },
                                    onClose: closePractice)
            case .live:
                PracticeSessionView(
                    provider: LiveDataProvider(client: APIClient(),
                                               configuration: AppConfiguration(mode: .live)),
                    existingSessionID: practiceSessionID,
                    createKey: practiceCreateKey ?? IdempotencyKey.generate(),
                    onSessionReady: { practiceSessionID = $0 },
                    // Phase 6C: hand the draft to PracticeService.submitAnswer(...).
                    onSubmit: { _ in },
                    onClose: closePractice)
            }
        }
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

private enum PracticePresentation: Identifiable {
    case mock, live

    var id: String {
        switch self {
        case .mock: "mock"
        case .live: "live"
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
