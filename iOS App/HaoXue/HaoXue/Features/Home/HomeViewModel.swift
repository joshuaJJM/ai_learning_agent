import Foundation
import Observation

enum HomeActionRoute: Equatable {
    case tutor(String?)
    case wrongQuestion(String)
    case practice
    case none

    init(_ action: NextLearningAction) {
        switch action.kind {
        case "start_tutor": self = .tutor(action.knowledgePointID)
        case "review_wrong_question":
            if let id = action.wrongQuestionID, !id.isEmpty { self = .wrongQuestion(id) }
            else { self = .none }
        case "continue_practice", "increase_difficulty": self = .practice
        case "review_later", "all_good": self = .none
        default: self = .none
        }
    }
}

@MainActor @Observable
final class HomeViewModel {
    enum Phase: Equatable { case idle, loading, loaded, failed }

    private let provider: any HomeSnapshotProviding
    private(set) var phase: Phase = .idle
    private(set) var snapshot: HomeSnapshot?
    private(set) var errorMessage: String?

    init(provider: any HomeSnapshotProviding) {
        self.provider = provider
    }

    func loadIfNeeded() async {
        guard phase == .idle else { return }
        await refresh()
    }

    func refresh() async {
        guard phase != .loading else { return }
        phase = .loading
        snapshot = nil
        errorMessage = nil
        do {
            let home = try await provider.fetchHomeSnapshot()
            try Task.checkCancellation()
            snapshot = home
            phase = .loaded
        } catch is CancellationError {
            phase = .idle
        } catch NetworkError.cancelled {
            phase = .idle
        } catch {
            errorMessage = Self.message(for: error)
            phase = .failed
        }
    }

    private static func message(for error: Error) -> String {
        guard let network = error as? NetworkError else {
            return "暂时无法获取学习状态，请重试"
        }
        switch network {
        case .backend(let code, _, _, _):
            switch code {
            case "UNAUTHORIZED": return "学习状态需要重新连接，请重试"
            case "SERVICE_UNAVAILABLE": return "服务暂时不可用，请稍后重试"
            default: return "暂时无法获取学习状态，请重试"
            }
        case .timeout, .transport:
            return "网络连接中断，请重试"
        case .decoding:
            return "学习状态暂时无法显示，请稍后重试"
        case .invalidResponse, .httpStatus, .cancelled:
            return "暂时无法获取学习状态，请重试"
        }
    }
}
