import Observation
import Foundation

enum DevelopmentState: Equatable { case loading, ready, error }

@MainActor @Observable
final class DevelopmentViewModel {
    private let provider: any HomeDataProviding
    private(set) var state: DevelopmentState = .loading

    init(provider: any HomeDataProviding) { self.provider = provider }

    func load() async {
        state = .loading
        do {
            try Task.checkCancellation()
            _ = try await provider.fetchHome()
            try Task.checkCancellation()
            state = .ready
        } catch is CancellationError {
            state = .loading
        } catch {
            state = .error
        }
    }
}
