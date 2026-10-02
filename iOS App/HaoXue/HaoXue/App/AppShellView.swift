import SwiftUI

@MainActor
struct AppShellView: View {
    let store: DemoScenarioStore
    @State private var showingTutor = false
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
        TabView {
            Group {
                if usesMockTutor {
                    DemoHomeView(store: store) { openTutor() }
                } else {
                    HomeView(model: homeModel, onStartTutor: { openTutor(knowledgePointID: $0) })
                }
            }
            .tabItem { Label("首页", systemImage: "house") }
            ScanView(store: store, onStart: { openTutor() })
                .tabItem { Label("扫描", systemImage: "viewfinder") }
            StudyView(store: store, onStart: { openTutor() })
                .tabItem { Label("学习", systemImage: "book.closed") }
            SettingsView(store: store)
                .tabItem { Label("设置", systemImage: "gearshape") }
        }
        .tint(.blue)
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
