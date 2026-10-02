import Foundation
import Observation

enum WrongQuestionStatus {
    static func label(_ value: String) -> String {
        switch value {
        case "open": "待复习"
        case "resolved": "已解决"
        case "archived": "已归档"
        default: "状态待更新"
        }
    }
}

enum WrongQuestionLoadPhase: Equatable { case idle, loading, loaded, failed }

@MainActor @Observable
final class WrongQuestionsListViewModel {
    private let provider: any WrongQuestionDataProviding
    private(set) var phase: WrongQuestionLoadPhase = .idle
    private(set) var items: [WrongQuestionSummary] = []
    private(set) var errorMessage: String?

    init(provider: any WrongQuestionDataProviding) { self.provider = provider }

    func loadIfNeeded() async {
        guard phase == .idle else { return }
        await refresh()
    }

    func refresh() async {
        guard phase != .loading else { return }
        phase = .loading
        errorMessage = nil
        do {
            items = try await provider.fetchWrongQuestions()
            try Task.checkCancellation()
            phase = .loaded
        } catch is CancellationError {
            phase = .idle
        } catch {
            items = []
            errorMessage = WrongQuestionError.message(for: error)
            phase = .failed
        }
    }
}

@MainActor @Observable
final class WrongQuestionDetailViewModel {
    private let id: String
    private let provider: any WrongQuestionDataProviding
    private(set) var phase: WrongQuestionLoadPhase = .idle
    private(set) var detail: WrongQuestionDetail?
    private(set) var errorMessage: String?
    private(set) var isUpdating = false
    private(set) var updateError: String?
    private(set) var lastStatusUpdateSucceeded = false

    init(id: String, provider: any WrongQuestionDataProviding) {
        self.id = id
        self.provider = provider
    }

    func loadIfNeeded() async {
        guard phase == .idle else { return }
        await refresh()
    }

    func refresh() async {
        guard phase != .loading else { return }
        phase = .loading
        errorMessage = nil
        do {
            detail = try await provider.fetchWrongQuestion(id: id)
            try Task.checkCancellation()
            phase = .loaded
        } catch is CancellationError {
            phase = .idle
        } catch {
            detail = nil
            errorMessage = WrongQuestionError.message(for: error)
            phase = .failed
        }
    }

    func updateStatus(_ status: String) async {
        guard !isUpdating, detail != nil else { return }
        isUpdating = true
        updateError = nil
        lastStatusUpdateSucceeded = false
        defer { isUpdating = false }
        do {
            detail = try await provider.updateWrongQuestion(id: id, status: status)
            lastStatusUpdateSucceeded = true
            do {
                detail = try await provider.fetchWrongQuestion(id: id)
            } catch {
                updateError = "状态已更新，暂时无法刷新详情"
            }
            phase = .loaded
        } catch {
            updateError = WrongQuestionError.message(for: error)
        }
    }

    func clearUpdateError() { updateError = nil }
}

enum WrongQuestionError {
    static func message(for error: Error) -> String {
        guard let error = error as? NetworkError else { return "暂时无法获取错题，请重试" }
        return switch error {
        case .backend(let code, _, _, _):
            switch code {
            case "WRONG_QUESTION_NOT_FOUND": "这道错题已不存在"
            case "UNAUTHORIZED": "请重新连接学习档案后重试"
            case "SERVICE_UNAVAILABLE": "服务暂时不可用，请稍后重试"
            case "INTERNAL_ERROR": "错题暂时无法显示，请稍后重试"
            default: "暂时无法获取错题，请重试"
            }
        case .timeout, .transport: "网络连接中断，请重试"
        case .decoding: "错题数据暂时无法显示，请稍后重试"
        default: "暂时无法获取错题，请重试"
        }
    }
}
