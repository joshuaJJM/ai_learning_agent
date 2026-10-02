import SwiftUI

@MainActor
struct AppShellView: View {
    let store: DemoScenarioStore
    @State private var showingTutor = false
    @State private var selectedTab = 0
    @State private var tutorKnowledgePointID: String?
    @State private var tutorWrongQuestionID: String?
    @State private var pendingTutorWrongQuestionID: String?
    @State private var pendingTutorKnowledgePointID: String?
    @State private var selectedRecord: LearningRecordRoute?
    @State private var recordPath: [LearningRecordRoute] = []
    @State private var homeModel = HomeViewModel(provider: LiveDataProvider(
        client: APIClient(), configuration: AppConfiguration(mode: .live)))
    @State private var wrongQuestionsModel = WrongQuestionsListViewModel(provider: LiveDataProvider(
        client: APIClient(), configuration: AppConfiguration(mode: .live)))
    @State private var knowledgeOverviewModel = KnowledgeOverviewViewModel(provider: LiveDataProvider(
        client: APIClient(), configuration: AppConfiguration(mode: .live)))
    private var usesMockTutor: Bool { ProcessInfo.processInfo.arguments.contains("-useMockTutor") }

    private func openTutor(knowledgePointID: String? = nil, wrongQuestionID: String? = nil) {
        if usesMockTutor { store.startLesson() }
        tutorKnowledgePointID = knowledgePointID
        tutorWrongQuestionID = wrongQuestionID
        showingTutor = true
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

    private func closeTutor() {
        showingTutor = false
        if !usesMockTutor {
            Task {
                await homeModel.refresh()
                if knowledgeOverviewModel.phase == .loaded { await knowledgeOverviewModel.refresh() }
            }
        }
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
                    StudyView(store: store, onStart: { openTutor() })
                } else {
                    WrongQuestionsView(model: wrongQuestionsModel, onOpen: openWrongQuestion,
                                       onOpenKnowledgeOverview: openKnowledgeOverview)
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
        .fullScreenCover(isPresented: $showingTutor) {
            if usesMockTutor {
                TutorView(store: store, provider: MockQuestionProvider()) { closeTutor() }
            } else {
                RemoteTutorView(
                    service: TutorRemoteService(baseURL: AppConfiguration.demoBackendURL,
                                                knowledgePointID: tutorKnowledgePointID,
                                                wrongQuestionID: tutorWrongQuestionID),
                    masteryService: MasteryOverviewService(baseURL: AppConfiguration.demoBackendURL)
                ) {
                    closeTutor()
                }
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
                    pendingTutorWrongQuestionID = id
                    selectedRecord = nil
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
                    pendingTutorKnowledgePointID = id
                    selectedRecord = nil
                })
        case .overview:
            KnowledgeOverviewView(model: knowledgeOverviewModel,
                                  onOpenKnowledge: { recordPath.append(.knowledge($0)) })
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
