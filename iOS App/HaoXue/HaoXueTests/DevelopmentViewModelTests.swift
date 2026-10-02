import Testing
@testable import HaoXue

@MainActor private struct FailingHomeProvider: HomeDataProviding {
    func fetchHome() async throws -> HomeState { throw ProviderError.contractNotConfigured }
}
@MainActor private struct CancelledHomeProvider: HomeDataProviding {
    func fetchHome() async throws -> HomeState { throw CancellationError() }
}

@MainActor
struct DevelopmentViewModelTests {
    @Test func successfulHomeLoadsReady() async {
        let model = DevelopmentViewModel(provider: MockDataProvider())
        #expect(model.state == .loading)
        await model.load()
        #expect(model.state == .ready)
    }
    @Test func failedHomeLoadsError() async {
        let model = DevelopmentViewModel(provider: FailingHomeProvider())
        await model.load()
        #expect(model.state == .error)
    }
    @Test func cancelledLoadDoesNotBecomeReady() async {
        let model = DevelopmentViewModel(provider: CancelledHomeProvider())
        await model.load()
        #expect(model.state != .ready)
    }
}
