import Foundation
import Observation

/// State for one analysis result screen, shared by the scan flow and history.
///
/// The result itself always comes from the backend. Confirming a standard
/// answer never mutates the verdict locally: the server re-judges the question
/// and the screen reloads the authoritative result.
@MainActor @Observable
final class AnalysisResultModel {
    /// Re-reads the authoritative result (same endpoint the scan flow uses).
    typealias Reload = (String) async throws -> HomeworkAnalysisResult

    private(set) var result: HomeworkAnalysisResult
    private(set) var isReloading = false
    private(set) var reloadError: String?

    private let confirmer: (any AnswerConfirming)?
    private let reload: Reload?
    private var confirmations: [String: AnswerConfirmationModel] = [:]

    init(result: HomeworkAnalysisResult,
         confirmer: (any AnswerConfirming)? = nil,
         reload: Reload? = nil) {
        self.result = result
        self.confirmer = confirmer
        self.reload = reload
        rebuildConfirmations()
    }

    /// Live result screen: manual confirmation is available.
    convenience init(liveResult: HomeworkAnalysisResult) {
        let baseURL = AppConfiguration.demoBackendURL
        let client = APIClient(timeout: 60)
        let analysis = LiveAnalysisService(baseURL: baseURL, client: client)
        self.init(
            result: liveResult,
            confirmer: LiveAnswerConfirmationService(baseURL: baseURL, client: client,
                                                     analysisID: liveResult.id),
            reload: { id in
                let response = try await analysis.get(id: id)
                guard let result = response.result else { throw ScanHistoryError.resultUnavailable }
                return result
            })
    }

    var canConfirmAnswers: Bool { confirmer != nil }

    /// Present only for questions the AI could not verify. `unanswered` is
    /// deliberately excluded: the student left the page blank, and the backend
    /// rejects that case too (`QUESTION_NOT_CONFIRMABLE`).
    func confirmation(for question: HomeworkAnalysisResult.Question) -> AnswerConfirmationModel? {
        guard question.correctness == .unknown else { return nil }
        return confirmations[question.id]
    }

    /// After a successful confirmation the server has already re-run the
    /// question's downstream work, so we reload instead of patching the verdict
    /// in place (that keeps counts, knowledge changes and wrong questions
    /// consistent with the backend in one step).
    func refreshAfterConfirmation() async {
        guard let reload else { return }
        isReloading = true
        defer { isReloading = false }
        do {
            result = try await reload(result.id)
            reloadError = nil
            rebuildConfirmations()
        } catch {
            reloadError = ScanHistoryViewModel.message(for: error)
        }
    }

    private func rebuildConfirmations() {
        guard let confirmer else {
            confirmations = [:]
            return
        }
        var rebuilt: [String: AnswerConfirmationModel] = [:]
        for question in result.questions where question.correctness == .unknown {
            if let existing = confirmations[question.id] {
                rebuilt[question.id] = existing
                continue
            }
            let choices = question.choices.keys.sorted()
            guard !choices.isEmpty else { continue }
            rebuilt[question.id] = AnswerConfirmationModel(questionID: question.id,
                                                           choices: choices, submitter: confirmer)
        }
        confirmations = rebuilt
    }
}
