import SwiftUI

@MainActor
struct AppShellView: View {
    let store: DemoScenarioStore
    @State private var showingTutor = false
    @State private var selectedTab = 0
    @State private var tutorKnowledgePointID: String?
    @State private var homeModel = HomeViewModel(provider: LiveDataProvider(
        client: APIClient(), configuration: AppConfiguration(mode: .live)))
    private var usesMockTutor: Bool { ProcessInfo.processInfo.arguments.contains("-useMockTutor") }

    private func openTutor(knowledgePointID: String? = nil) {
        if usesMockTutor { store.startLesson() }
        tutorKnowledgePointID = knowledgePointID
        showingTutor = true
    }

    private func closeTutor() {
        showingTutor = false
        if !usesMockTutor { Task { await homeModel.refresh() } }
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            Group {
                if usesMockTutor {
                    DemoHomeView(store: store) { openTutor() }
                } else {
                    HomeView(model: homeModel, onStartTutor: { openTutor(knowledgePointID: $0) })
                }
            }
            .tabItem { Label("首页", systemImage: "house") }
            .tag(0)
            NavigationStack {
                ScanView(store: store, onStart: { openTutor(knowledgePointID: $0) },
                         onReturnHome: { selectedTab = 0 })
            }
                .tabItem { Label("扫描", systemImage: "viewfinder") }
                .tag(1)
            StudyView(store: store, onStart: { openTutor() })
                .tabItem { Label("学习", systemImage: "book.closed") }
                .tag(2)
            SettingsView(store: store)
                .tabItem { Label("设置", systemImage: "gearshape") }
                .tag(3)
        }
        .tint(.blue)
        .onChange(of: selectedTab) { _, tab in
            if tab == 0, !usesMockTutor { Task { await homeModel.refresh() } }
        }
        .fullScreenCover(isPresented: $showingTutor) {
            if usesMockTutor {
                TutorView(store: store, provider: MockQuestionProvider()) { closeTutor() }
            } else {
                RemoteTutorView(
                    service: TutorRemoteService(baseURL: AppConfiguration.demoBackendURL,
                                                knowledgePointID: tutorKnowledgePointID),
                    masteryService: MasteryOverviewService(baseURL: AppConfiguration.demoBackendURL)
                ) {
                    closeTutor()
                }
            }
        }
    }
}
