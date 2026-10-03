import Foundation
import Observation
import PencilKit

enum PracticeSessionPhase: Equatable {
    case idle
    case loading
    case answering
    case submitting
    case result(PracticeAnswerOutcome)
    case submitFailed(String)
    case failed(String)
}

/// What Phase 6C hands to `PracticeService.submitAnswer(...)`.
struct PracticeAnswerDraft: Equatable {
    let questionID: String
    let selectedKey: String
}

/// One logical write: the draft is frozen and the key never changes across retries.
struct PracticeSubmission: Equatable {
    let draft: PracticeAnswerDraft
    let key: IdempotencyKey
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

    private(set) var phase: PracticeSessionPhase = .idle
    private(set) var session: PracticeSessionState?
    private(set) var submission: PracticeSubmission?
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

    var outcome: PracticeAnswerOutcome? {
        if case .result(let outcome) = phase { return outcome }
        return nil
    }

    var submitErrorMessage: String? {
        if case .submitFailed(let message) = phase { return message }
        return nil
    }

    var loadErrorMessage: String? {
        if case .failed(let message) = phase { return message }
        return nil
    }

    var completedOutcome: PracticeAnswerOutcome? {
        guard let outcome, outcome.sessionCompleted else { return nil }
        return outcome
    }

    var canSubmit: Bool {
        guard phase == .answering, let question, let selectedChoiceKey else { return false }
        return question.choices.contains { $0.key == selectedChoiceKey }
    }

    var canContinue: Bool {
        guard let outcome else { return false }
        return !outcome.sessionCompleted && outcome.nextQuestion != nil
    }

    func loadIfNeeded() async {
        guard phase == .idle else { return }
        await load()
    }

    /// Creates a session, or restores the one the app already owns. A retry keeps
    /// the same logical request identity, so a slow first attempt cannot double-score.
    func load() async {
        guard phase != .loading, phase != .submitting else { return }
        requestGeneration += 1
        let generation = requestGeneration
        phase = .loading
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
            submission = nil
            phase = .answering
        } catch is CancellationError {
            guard generation == requestGeneration else { return }
            phase = session == nil ? .idle : .answering
        } catch {
            guard generation == requestGeneration, !Task.isCancelled else { return }
            // A refresh failure never discards the question already on screen.
            phase = session == nil ? .failed(PracticeError.message(for: error)) : .answering
        }
    }

    func select(_ key: String) {
        // Selection stays mutable only until the first submit freezes the draft.
        guard phase == .answering, submission == nil, let question,
              question.choices.contains(where: { $0.key == key }) else { return }
        selectedChoiceKey = key
    }

    func makeSubmission() -> PracticeAnswerDraft? {
        guard canSubmit, let question, let selectedChoiceKey else { return nil }
        return PracticeAnswerDraft(questionID: question.id, selectedKey: selectedChoiceKey)
    }

    /// Freezes the draft on the first tap; every later retry reuses the same
    /// answer and the same idempotency key.
    func submit() async {
        guard phase == .answering, submission == nil else { return }
        guard let draft = makeSubmission() else { return }
        submission = PracticeSubmission(draft: draft, key: IdempotencyKey.generate())
        await send()
    }

    func retrySubmit() async {
        guard case .submitFailed = phase, submission != nil else { return }
        await send()
    }

    private func send() async {
        guard let submission, let sessionID else { return }
        requestGeneration += 1
        let generation = requestGeneration
        phase = .submitting
        do {
            let outcome = try await provider.submitPracticeAnswer(
                sessionID: sessionID, questionID: submission.draft.questionID,
                selectedKey: submission.draft.selectedKey, key: submission.key)
            guard generation == requestGeneration, !Task.isCancelled else { return }
            phase = .result(outcome)
        } catch is CancellationError {
            guard generation == requestGeneration else { return }
            phase = .submitFailed("提交已暂停，请重试")
        } catch {
            guard generation == requestGeneration, !Task.isCancelled else { return }
            phase = .submitFailed(PracticeError.submitMessage(for: error))
        }
    }

    /// The next question is the server-provided one; counters come straight from
    /// the response, never from local arithmetic.
    func continueToNext() {
        guard let outcome, let next = outcome.nextQuestion, !outcome.sessionCompleted,
              let session else { return }
        self.session = PracticeMapper().session(session, applying: outcome, nextQuestion: next)
        selectedChoiceKey = nil
        submission = nil
        phase = .answering
    }

    func retry() async {
        await load()
    }

    func cancel() {
        requestGeneration += 1
        if phase == .loading || phase == .submitting {
            phase = session == nil ? .idle : .answering
        }
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

    /// Submit errors keep the frozen answer; the copy stays recoverable.
    static func submitMessage(for error: Error) -> String {
        switch error {
        case PracticeServiceError.backend(let code):
            switch code {
            case .questionNotInSession: return "这道题的状态已变化，请退出后重新开始练习"
            case .sessionNotFound: return "练习记录不存在，请退出后重新开始"
            case .sessionCompleted: return "这次练习已经结束了"
            case .idempotencyConflict: return "上一次请求仍在处理中，请稍后重试"
            case .validationError: return "答案未能提交，请重试"
            case .unauthorized: return "登录状态已失效，请稍后重试"
            case .serviceUnavailable, .internalError: return "练习服务暂时不可用，请稍后重试"
            default: return "答案暂时无法提交，请重试"
            }
        case PracticeServiceError.network(let network):
            return networkMessage(for: network)
        case let network as NetworkError:
            return networkMessage(for: network)
        default:
            return "答案暂时无法提交，请重试"
        }
    }

    private static func networkMessage(for error: NetworkError) -> String {
        switch error {
        case .timeout, .transport: "网络连接中断，请重试"
        case .decoding: "提交结果暂时无法显示，请重试"
        default: "答案暂时无法提交，请重试"
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
