import Foundation
import Observation

/// Boundary for the manual "confirm the standard answer" flow.
///
/// The client submits exactly one thing — *the student confirmed the answer
/// book says C* — and the server decides the resulting correctness, Evidence
/// and mastery. The client never sends a verdict.
///
/// The concrete live implementation (endpoint, JSON, headers) is intentionally
/// **not** written yet: the backend contract for this feature is still being
/// agreed. Until it lands, nothing in the app is wired to this protocol, so the
/// demo never pretends the feature works.
@MainActor
protocol AnswerConfirming {
    /// One *logical* confirmation. Every transport retry of the same logical
    /// confirmation must reuse the same `Idempotency-Key`, so a timeout cannot
    /// produce two Evidence rows.
    func confirm(questionID: String, correctAnswer: String) async throws
}

/// Selection + submission state for one `correctness == unknown` question.
///
/// Selecting a choice never talks to the server; the student must tap
/// 「确认答案」 explicitly.
@MainActor @Observable
final class AnswerConfirmationModel {
    enum Phase: Equatable {
        case idle
        case submitting
        case failed(String)
    }

    let questionID: String
    let choices: [String]
    private(set) var selected: String?
    private(set) var phase: Phase = .idle
    /// Set once the server accepted the confirmation; the caller refreshes the
    /// analysis result and the section disappears with it.
    private(set) var isConfirmed = false

    private let submitter: any AnswerConfirming

    init(questionID: String, choices: [String], submitter: any AnswerConfirming) {
        self.questionID = questionID
        self.choices = choices
        self.submitter = submitter
    }

    var isSubmitting: Bool { phase == .submitting }
    var canConfirm: Bool { selected != nil && !isSubmitting && !isConfirmed }
    var errorMessage: String? {
        if case .failed(let message) = phase { return message }
        return nil
    }

    /// Single tap only selects. It never writes to the server.
    func select(_ choice: String) {
        guard !isSubmitting, choices.contains(choice) else { return }
        selected = choice
        phase = .idle
    }

    /// Returns true when the server accepted the confirmation. Re-entrant calls
    /// while a request is in flight are ignored, so double-tapping cannot send
    /// two logical confirmations.
    @discardableResult
    func confirm() async -> Bool {
        guard let selected, canConfirm else { return false }
        phase = .submitting
        do {
            try await submitter.confirm(questionID: questionID, correctAnswer: selected)
            phase = .idle
            isConfirmed = true
            return true
        } catch {
            // Keep the selection so「重试」resends the same logical confirmation
            // (and, in the live implementation, the same idempotency key).
            phase = .failed(Self.message(for: error))
            return false
        }
    }

    static func message(for error: Error) -> String {
        if let network = error as? NetworkError {
            switch network {
            case .backend(let code, _, _, _):
                switch ServiceErrorCode(rawValue: code) {
                case .questionNotConfirmable:
                    return "这道题现在无法确认（学生未作答，或分析还没完成）。"
                case .questionAlreadyResolved:
                    return "这道题已经确认过了，正在刷新最新结果。"
                case .invalidAnswer:
                    return "这个选项不在本题的选项中，请重新选择。"
                default:
                    return ScanFailurePresentation(code: code).message
                }
            case .timeout, .transport, .invalidResponse:
                return "确认没有提交成功，请重试。"
            case .cancelled, .decoding, .httpStatus:
                return "确认没有提交成功，请重试。"
            }
        }
        return "确认没有提交成功，请重试。"
    }
}
