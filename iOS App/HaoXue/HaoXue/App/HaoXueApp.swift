import SwiftUI

@main
struct HaoXueApp: App {
    @State private var demo = DemoScenarioStore()

    var body: some Scene {
        WindowGroup { AppShellView(store: demo) }
    }
}
