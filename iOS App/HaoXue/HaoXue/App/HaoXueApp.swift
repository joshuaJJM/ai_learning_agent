import SwiftUI

@main
struct HaoXueApp: App {
    @State private var model: DevelopmentViewModel

    init() {
        let configuration = AppConfiguration()
        let provider: any HomeDataProviding
        switch configuration.mode {
        case .mock:
            provider = MockDataProvider()
        case .live:
            provider = LiveDataProvider(
                client: APIClient(timeout: configuration.timeout), configuration: configuration)
        }
        _model = State(initialValue: DevelopmentViewModel(provider: provider))
    }

    var body: some Scene {
        WindowGroup { DevelopmentView(model: model) }
    }
}
