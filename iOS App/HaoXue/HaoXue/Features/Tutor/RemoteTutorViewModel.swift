import Foundation
import Observation
import PencilKit

@MainActor @Observable
final class RemoteTutorViewModel {
    private let service: any TutorRemoteServing
    private let masteryService: (any MasteryOverviewServing)?
    private let createKey = UUID().uuidString
    private var requestGeneration = 0
    private var pendingAnswer: (selectedKey: String?, text: String?, key: String)?
    private var finishAfterReveal = false
    private var knowledgePointId: String?
    private(set) var sessionId: String?
    private(set) var knowledgePointName = "学习"
    private(set) var turn: TutorTurnDTO?
    private(set) var pendingNextTurn: TutorTurnDTO?
    private(set) var answerReveal: TutorAnswerRevealDTO?
    private(set) var feedback: String?
    private(set) var answeredCorrectly: Bool?
    private(set) var streamedText = ""
    private(set) var isLoading = false
    private(set) var isSubmitting = false
    private(set) var completed = false
    private(set) var errorMessage: String?
    // Server-owned mastery for the knowledge point of this session. `nil` means
    // "the backend has not reported a change yet" — never zero, never recomputed.
    private(set) var sessionStartMastery: Double?
    private(set) var currentMastery: Double?
    // Global cross-knowledge-point score from /knowledge/mastery-overview.
    private(set) var overallMasteryScore: Int?
    var selectedKey: String?
    var freeText = ""
    var drawing = PKDrawing()

    init(service: any TutorRemoteServing, masteryService: (any MasteryOverviewServing)? = nil) {
        self.service = service
        self.masteryService = masteryService
    }

    var progressText: String {
        guard let progress = turn?.progress else { return "" }
        return "\(progress.step) / \(progress.totalSteps)"
    }

    var canShowMastery: Bool { currentMastery != nil }

    var hasMasteryChange: Bool { sessionStartMastery != nil && currentMastery != nil }

    var canSubmit: Bool {
        guard let turn, !isSubmitting, !isLoading, pendingAnswer == nil,
              pendingNextTurn == nil else { return false }
        if !turn.choices.isEmpty { return selectedKey != nil }
        return turn.allowFreeText && !freeText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func load() async {
        guard sessionId == nil, !isLoading else { return }
        requestGeneration += 1
        let generation = requestGeneration
        isLoading = true
        errorMessage = nil
        do {
            let session = try await service.createSession(key: createKey)
            guard generation == requestGeneration, !Task.isCancelled else { return }
            sessionId = session.tutorSessionId
            knowledgePointName = session.knowledgePointName ?? "学习"
            knowledgePointId = session.knowledgePointId
            turn = session.turn
            completed = session.completed
            isLoading = false
            apply(knowledgeChanges: session.knowledgeChanges)
            // Session state is already published; the overview request never gates the Tutor.
            await refreshOverallMastery(generation: generation)
        } catch {
            guard generation == requestGeneration, !Task.isCancelled else { return }
            isLoading = false
            errorMessage = "题目加载失败，请重试"
        }
    }

    func select(_ key: String) {
        guard !isSubmitting, pendingAnswer == nil, pendingNextTurn == nil else { return }
        selectedKey = key
    }

    func submit() async {
        guard let sessionId, !isSubmitting, !isLoading else { return }
        guard canSubmit || pendingAnswer != nil else { return }
        let answer = pendingAnswer ?? (selectedKey, freeText.isEmpty ? nil : freeText, UUID().uuidString)
        pendingAnswer = answer
        requestGeneration += 1
        let generation = requestGeneration
        isSubmitting = true
        streamedText = ""
        errorMessage = nil
        do {
            let result = try await service.submit(
                sessionId: sessionId, selectedKey: answer.selectedKey, text: answer.text, key: answer.key
            ) { [weak self] event in
                guard let self, generation == self.requestGeneration else { return }
                switch event {
                case .delta(let content): self.streamedText += content
                case .turn(let turn): self.streamedText = turn.text
                case .meta, .done: break
                }
            }
            guard generation == requestGeneration, !Task.isCancelled else { return }
            pendingAnswer = nil
            isSubmitting = false
            feedback = result.evaluation?.feedback
            answeredCorrectly = result.evaluation?.isCorrect
            answerReveal = result.turn.answerReveal
            finishAfterReveal = result.completed && result.turn.strategy == "reveal_answer"
            completed = result.completed && !finishAfterReveal
            apply(knowledgeChanges: result.knowledgeChanges)
            selectedKey = nil
            freeText = ""
            if finishAfterReveal {
                pendingNextTurn = result.turn
            } else if result.completed {
                turn = result.turn
            } else if result.turn.remedialDepth > 0 || result.turn.strategy == "hint" {
                turn = result.turn
            } else {
                pendingNextTurn = result.turn
            }
            if result.completed { await refreshOverallMastery(generation: generation) }
        } catch {
            guard generation == requestGeneration, !Task.isCancelled else { return }
            isSubmitting = false
            errorMessage = "提交失败，请重试；本次答案不会重复计分"
        }
    }

    /// Server sends `knowledge_changes` for the knowledge point of this session.
    /// An empty list must keep the previously shown value: the backend omits the
    /// change on turns that did not move mastery, which is not a reset to zero.
    private func apply(knowledgeChanges changes: [TutorKnowledgeChangeDTO]) {
        let change = changes.first { $0.knowledgePointId == knowledgePointId } ?? changes.first
        guard let change else { return }
        if sessionStartMastery == nil { sessionStartMastery = change.before }
        currentMastery = change.after
    }

    /// Mastery overview is auxiliary: failure only hides the number.
    private func refreshOverallMastery(generation: Int) async {
        guard let masteryService else { return }
        guard let overview = try? await masteryService.fetchOverview() else { return }
        guard generation == requestGeneration, !Task.isCancelled else { return }
        overallMasteryScore = overview.score
    }

    func continueToNext() {
        guard let next = pendingNextTurn else { return }
        turn = next
        pendingNextTurn = nil
        completed = finishAfterReveal
        finishAfterReveal = false
        feedback = nil
        answeredCorrectly = nil
        answerReveal = nil
        streamedText = ""
        selectedKey = nil
        freeText = ""
        drawing = PKDrawing()
    }

    func retry() async {
        if pendingAnswer != nil { await submit() }
        else if sessionId == nil { await load() }
    }

    func cancel() {
        requestGeneration += 1
        isLoading = false
        isSubmitting = false
        if pendingAnswer != nil { errorMessage = "请求已暂停，请重试原答案" }
    }
}
