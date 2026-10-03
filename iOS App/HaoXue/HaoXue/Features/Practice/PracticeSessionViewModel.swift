import Foundation
import Observation
import PencilKit

enum PracticeLoadPhase: Equatable { case idle, loading, loaded, failed }

/// What Phase 6C will hand to `PracticeService.submitAnswer(...)`.
/// Phase 6B only produces it locally; it is never sent.
struct PracticeAnswerDraft: Equatable {
    let questionID: String
    let selectedKey: String
}

@MainActor @Observable
final class PracticeSessionViewModel {
    private let provider: any PracticeDataProviding
    private let existingSessionID: String?
    private let knowledgePointID: String?
    private let createKey: IdempotencyKey
    private let questionCount: Int
    private var requestGeneration = 0
    private var sessionID: String?

    private(set) var phase: PracticeLoadPhase = .idle
    private(set) var session: PracticeSessionState?
    private(set) var errorMessage: String?
    /// Presentation-only selection. Never an authoritative verdict.
    var selectedChoiceKey: String?
    var drawing = PKDrawing()

    init(provider: any PracticeDataProviding, existingSessionID: String? = nil,
         knowledgePointID: String? = nil, createKey: IdempotencyKey? = nil,
         questionCount: Int = 5) {
        self.provider = provider
        self.existingSessionID = existingSessionID
        self.knowledgePointID = knowledgePointID
        self.createKey = createKey ?? IdempotencyKey.generate()
        self.questionCount = questionCount
        self.sessionID = existingSessionID
    }

    /// Backend-owned question, answer-free by contract.
    var question: PracticeQuestion? { session?.nextQuestion }

    /// `target_tag` first (tag mode), otherwise the knowledge point name.
    /// Both may be absent: the context block is simply hidden.
    var contextTitle: String? {
        session?.targetTag ?? session?.knowledgePointName
    }

    var progressText: String {
        guard let question else { return "" }
        return "\(question.index) / \(question.total)"
    }

    var canSubmit: Bool {
        guard phase == .loaded, errorMessage == nil, let question, let selectedChoiceKey else {
            return false
        }
        return question.choices.contains { $0.key == selectedChoiceKey }
    }

    func loadIfNeeded() async {
        guard phase == .idle else { return }
        await load()
    }

    /// Creates a session, or restores the one the app already owns. A retry keeps
    /// the same logical request identity, so a slow first attempt cannot double-score.
    func load() async {
        guard phase != .loading else { return }
        requestGeneration += 1
        let generation = requestGeneration
        phase = .loading
        errorMessage = nil
        do {
            let loaded: PracticeSessionState
            if let sessionID {
                loaded = try await provider.fetchPracticeSession(id: sessionID)
            } else {
                loaded = try await provider.createPracticeSession(
                    knowledgePointID: knowledgePointID, difficulty: nil,
                    count: questionCount, key: createKey)
            }
            guard generation == requestGeneration, !Task.isCancelled else { return }
            sessionID = loaded.id
            session = loaded
            selectedChoiceKey = nil
            phase = .loaded
        } catch is CancellationError {
            guard generation == requestGeneration else { return }
            phase = session == nil ? .idle : .loaded
        } catch {
            guard generation == requestGeneration, !Task.isCancelled else { return }
            errorMessage = PracticeError.message(for: error)
            // A refresh failure never discards the question already on screen.
            phase = session == nil ? .failed : .loaded
        }
    }

    func select(_ key: String) {
        guard phase == .loaded, let question,
              question.choices.contains(where: { $0.key == key }) else { return }
        selectedChoiceKey = key
    }

    func makeSubmission() -> PracticeAnswerDraft? {
        guard canSubmit, let question, let selectedChoiceKey else { return nil }
        return PracticeAnswerDraft(questionID: question.id, selectedKey: selectedChoiceKey)
    }

    func retry() async {
        await load()
    }

    func cancel() {
        requestGeneration += 1
        if phase == .loading { phase = session == nil ? .idle : .loaded }
    }
}

enum PracticeError {
    static func message(for error: Error) -> String {
        switch error {
        case PracticeServiceError.backend(let code):
            return message(for: code)
        case PracticeServiceError.network(let network):
            return message(for: network)
        case let network as NetworkError:
            return message(for: network)
        default:
            return "练习暂时无法加载，请重试"
        }
    }

    private static func message(for code: ServiceErrorCode) -> String {
        switch code {
        case .noQuestionsAvailable: "这一组题已经做完了"
        case .sessionNotFound: "练习记录不存在，请退出后重新开始"
        case .unauthorized: "登录状态已失效，请稍后重试"
        case .serviceUnavailable, .internalError: "练习服务暂时不可用，请稍后重试"
        case .idempotencyConflict: "上一次请求仍在处理中，请稍后重试"
        default: "练习暂时无法加载，请重试"
        }
    }

    private static func message(for error: NetworkError) -> String {
        switch error {
        case .timeout, .transport: "网络连接中断，请重试"
        case .decoding: "练习数据暂时无法显示，请重试"
        default: "练习暂时无法加载，请重试"
        }
    }
}
