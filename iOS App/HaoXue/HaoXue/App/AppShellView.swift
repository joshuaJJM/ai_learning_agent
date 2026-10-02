import SwiftUI

struct AppShellView: View {
    let store: DemoScenarioStore
    @State private var showingTutor = false

    private func openTutor() {
        store.startLesson()
        showingTutor = true
    }

    var body: some View {
        TabView {
            HomeView(store: store, onStart: openTutor)
                .tabItem { Label("首页", systemImage: "house") }
            ScanView(store: store, onStart: openTutor)
                .tabItem { Label("扫描", systemImage: "viewfinder") }
            StudyView(store: store, onStart: openTutor)
                .tabItem { Label("学习", systemImage: "book.closed") }
            SettingsView(store: store)
                .tabItem { Label("设置", systemImage: "gearshape") }
        }
        .tint(.blue)
        .fullScreenCover(isPresented: $showingTutor) {
            TutorView(store: store, provider: MockQuestionProvider()) { showingTutor = false }
        }
    }
}
