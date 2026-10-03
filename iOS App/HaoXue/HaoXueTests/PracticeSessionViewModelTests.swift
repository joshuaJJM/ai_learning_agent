import Foundation
import Testing
@testable import HaoXue

@MainActor
struct PracticeSessionViewModelTests {
    private func choice(_ key: String, _ text: String = "选项") -> PracticeChoice {
        PracticeChoice(key: key, text: text)
    }

    private func question(_ id: String = "math.derivative.abc", index: Int = 1, total: Int = 5,
                          choices: [PracticeChoice]? = nil) -> PracticeQuestion {
        PracticeQuestion(id: id, number: "072", stem: "已知 f(x) = x²，求 f′(1)。",
                         choices: choices ?? [choice("A"), choice("B"), choice("C"), choice("D")],
                         difficulty: 0.75,
                         knowledgePoints: [PracticeQuestion.KnowledgePoint(
                             id: "math.derivative.monotonicity", name: "导数与单调性", weight: 1)],
                         tags: ["利用导数判断函数单调性与单调区间"],
                         index: index, total: total)
    }

    private func session(id: String = "prac_1", question: PracticeQuestion?,
                         mode: PracticeSelectionMode = .tag,
                         targetTag: String? = "函数关系式与导数的综合应用",
                         knowledgePointName: String? = "利用导数判断函数单调性与单调区间",
                         answered: Int = 0, correct: Int = 0, total: Int = 5) -> PracticeSessionState {
        PracticeSessionState(id: id, userID: "user_1",
                             knowledgePointID: "math.derivative.monotonicity",
                             knowledgePointName: knowledgePointName,
                             status: .active, total: total, answered: answered, correct: correct,
                             nextQuestion: question, selectionMode: mode, targetTag: targetTag,
                             targetTagScore: mode == .tag ? -3 : nil,
                             pickedTags: mode == .tag ? ["函数关系式与导数的综合应用"] : [],
                             createdAt: Date(timeIntervalSince1970: 1_790_899_200))
    }

    private func change(_ id: String, _ name: String, _ before: Double, _ after: Double)
        -> KnowledgeChange {
        KnowledgeChange(knowledgePointID: id, beforeMastery: before, afterMastery: after,
                        summary: name, delta: after - before, evidenceCount: 3)
    }

    private func outcome(questionID: String = "math.derivative.abc", correctness: String = "correct",
                         isCorrect: Bool = true, correctAnswer: String = "B",
                         explanation: String? = "f′(x) = 2x，所以 f′(1) = 2。",
                         changes: [KnowledgeChange] = [], tag: PracticeTagChange? = nil,
                         replayed: Bool = false, next: PracticeQuestion? = nil,
                         completed: Bool = false, answered: Int = 1, correct: Int = 1,
                         total: Int = 5,
                         nextAction: NextLearningAction? = nil) -> PracticeAnswerOutcome {
        PracticeAnswerOutcome(sessionID: "prac_1", questionID: questionID,
                              correctness: correctness, isCorrect: isCorrect,
                              correctAnswer: correctAnswer, explanation: explanation,
                              knowledgeChanges: changes, tagChange: tag, replayed: replayed,
                              nextQuestion: next, sessionCompleted: completed, answered: answered,
                              correct: correct, total: total, nextAction: nextAction)
    }

    private func loadedModel(_ provider: FakePracticeProvider,
                             question: PracticeQuestion? = nil) async -> PracticeSessionViewModel {
        provider.sessionToReturn = session(question: question ?? self.question())
        let model = PracticeSessionViewModel(provider: provider)
        await model.load()
        return model
    }

    // MARK: - Session loading

    @Test func initialStateIsIdleWithoutQuestion() {
        let model = PracticeSessionViewModel(provider: FakePracticeProvider())
        #expect(model.phase == .idle)
        #expect(model.session == nil)
        #expect(model.question == nil)
        #expect(model.outcome == nil)
        #expect(!model.canSubmit)
        #expect(!model.canContinue)
        #expect(model.makeSubmission() == nil)
    }

    @Test func liveCreateExposesBackendQuestionAndKeepsItsIdentifiers() async {
        let provider = FakePracticeProvider()
        let key = IdempotencyKey("0f2b7c1e-2f4b-4a1d-9f0e-000000000009")
        provider.sessionToReturn = session(question: question())
        let model = PracticeSessionViewModel(provider: provider, createKey: key)

        await model.load()

        #expect(model.phase == .answering)
        #expect(model.session?.id == "prac_1")
        #expect(model.question?.id == "math.derivative.abc")
        #expect(model.question?.number == "072")
        #expect(model.question?.choices.map(\.key) == ["A", "B", "C", "D"])
        #expect(model.progressText == "1 / 5")
        #expect(model.contextTitle == "函数关系式与导数的综合应用")
        #expect(provider.createdKeys == [key])
        #expect(provider.submitCount == 0)
    }

    @Test func knowledgePointModeUsesBackendNameAndMissingContextDoesNotCrash() async {
        let provider = FakePracticeProvider()
        provider.sessionToReturn = session(question: question(), mode: .knowledgePoint,
                                           targetTag: nil)
        let model = PracticeSessionViewModel(provider: provider)
        await model.load()
        #expect(model.phase == .answering)
        #expect(model.contextTitle == "利用导数判断函数单调性与单调区间")

        provider.sessionToReturn = session(question: question(), mode: .knowledgePoint,
                                           targetTag: nil, knowledgePointName: nil)
        let bare = PracticeSessionViewModel(provider: provider)
        await bare.load()
        #expect(bare.contextTitle == nil)
        #expect(bare.question != nil)
    }

    @Test func restoreUsesTheKnownSessionInsteadOfCreatingAnother() async {
        let provider = FakePracticeProvider()
        provider.sessionToReturn = session(id: "prac_restored", question: question(index: 2))
        let model = PracticeSessionViewModel(provider: provider, existingSessionID: "prac_restored")

        await model.load()

        #expect(provider.fetchedIDs == ["prac_restored"])
        #expect(provider.createCount == 0)
        #expect(model.progressText == "2 / 5")
    }

    @Test func createFailureStaysRecoverableAndRetryReusesTheSameKey() async {
        let provider = FakePracticeProvider()
        provider.sessionToReturn = session(question: question())
        provider.failFirstCreate = true
        let key = IdempotencyKey("phase6c-retry")
        let model = PracticeSessionViewModel(provider: provider, createKey: key)

        await model.load()

        #expect(model.loadErrorMessage != nil)
        #expect(model.session == nil)

        await model.retry()
        #expect(model.phase == .answering)
        #expect(provider.createdKeys == [key, key])
    }

    // MARK: - Selection

    @Test func selectionIsSingleAndOnlyAcceptsBackendChoices() async {
        let model = await loadedModel(FakePracticeProvider())
        #expect(model.selectedChoiceKey == nil)
        model.select("A")
        #expect(model.selectedChoiceKey == "A")
        model.select("C")
        #expect(model.selectedChoiceKey == "C")
        model.select("Z")
        #expect(model.selectedChoiceKey == "C")
    }

    @Test func submitEligibilityFollowsTheLocalSelection() async {
        let model = await loadedModel(FakePracticeProvider())
        #expect(!model.canSubmit)
        #expect(model.makeSubmission() == nil)
        model.select("B")
        #expect(model.canSubmit)
        #expect(model.makeSubmission() == PracticeAnswerDraft(questionID: "math.derivative.abc",
                                                              selectedKey: "B"))
    }

    @Test func aQuestionWithoutChoicesIsNeverSubmittable() async {
        let provider = FakePracticeProvider()
        let model = await loadedModel(provider, question: question(choices: []))
        model.select("A")
        #expect(model.selectedChoiceKey == nil)
        #expect(!model.canSubmit)

        provider.sessionToReturn = session(question: nil)
        let finished = PracticeSessionViewModel(provider: provider)
        await finished.load()
        #expect(finished.question == nil)
        #expect(!finished.canSubmit)
        #expect(finished.progressText.isEmpty)
    }

    @Test func selectingAnAnswerNeverMutatesServerStateOrInventsAVerdict() async throws {
        let provider = FakePracticeProvider()
        provider.sessionToReturn = session(question: question(), answered: 1, correct: 1)
        let model = PracticeSessionViewModel(provider: provider)
        await model.load()
        let sessionBefore = try #require(model.session)
        let questionBefore = try #require(model.question)

        model.select("D")

        #expect(model.session == sessionBefore)
        #expect(model.question == questionBefore)
        #expect(model.session?.answered == 1)
        #expect(model.outcome == nil)
        #expect(provider.submitCount == 0)
    }

    // MARK: - Submission

    @Test func submitFreezesTheDraftAndCallsTheProviderOnce() async {
        let provider = FakePracticeProvider()
        provider.outcomeToReturn = outcome()
        let model = await loadedModel(provider)
        model.select("B")

        await model.submit()

        #expect(provider.submitCount == 1)
        #expect(provider.submissions == [PracticeAnswerDraft(questionID: "math.derivative.abc",
                                                             selectedKey: "B")])
        #expect(provider.submissionKeys.count == 1)
        #expect(model.phase == .result(outcome()))
        #expect(model.outcome?.isCorrect == true)
        #expect(model.outcome?.correctAnswer == "B")
        #expect(model.outcome?.explanation == "f′(x) = 2x，所以 f′(1) = 2。")
    }

    @Test func doubleTapWhileSubmittingSendsOnlyOneRequest() async {
        let provider = FakePracticeProvider()
        provider.outcomeToReturn = outcome()
        provider.submitDelay = .milliseconds(60)
        let model = await loadedModel(provider)
        model.select("A")

        let first = Task { await model.submit() }
        var spins = 0
        while model.phase != .submitting && spins < 2_000 {
            spins += 1
            await Task.yield()
        }
        #expect(model.phase == .submitting)
        await model.submit()          // second tap: must be ignored
        model.select("C")             // selection is frozen too
        #expect(model.selectedChoiceKey == "A")
        await first.value

        #expect(provider.submitCount == 1)
        #expect(provider.submissions.first?.selectedKey == "A")
        #expect(model.outcome != nil)
    }

    @Test func submitFailureFreezesTheAnswerAndRetryReusesTheSameKey() async {
        let provider = FakePracticeProvider()
        provider.outcomeToReturn = outcome()
        provider.failFirstSubmit = true
        let model = await loadedModel(provider)
        model.select("C")

        await model.submit()

        #expect(model.submitErrorMessage != nil)
        #expect(model.outcome == nil)
        model.select("A")             // mutation after submit is refused
        #expect(model.selectedChoiceKey == "C")

        await model.retrySubmit()

        #expect(provider.submitCount == 2)
        #expect(provider.submissionKeys.count == 2)
        #expect(provider.submissionKeys[0] == provider.submissionKeys[1])
        #expect(provider.submissions.allSatisfy { $0.selectedKey == "C" })
        #expect(model.outcome != nil)
    }

    @Test func backendSubmitErrorsKeepTheirOwnCopy() async {
        let provider = FakePracticeProvider()
        provider.submitError = PracticeServiceError.backend(.questionNotInSession)
        let model = await loadedModel(provider)
        model.select("A")
        await model.submit()
        #expect(model.submitErrorMessage == "这道题的状态已变化，请退出后重新开始练习")

        provider.submitError = PracticeServiceError.backend(.sessionCompleted)
        let other = await loadedModel(provider)
        other.select("A")
        await other.submit()
        #expect(other.submitErrorMessage == "这次练习已经结束了")
    }

    // MARK: - Server-driven results

    @Test func correctAndIncorrectResultsComeFromTheServer() async throws {
        let provider = FakePracticeProvider()
        provider.outcomeToReturn = outcome(correctness: "wrong", isCorrect: false,
                                           correctAnswer: "C", explanation: nil,
                                           answered: 3, correct: 1, total: 5)
        let model = await loadedModel(provider)
        model.select("A")
        await model.submit()

        let result = try #require(model.outcome)
        #expect(result.correctness == "wrong")
        #expect(result.isCorrect == false)
        #expect(result.correctAnswer == "C")
        #expect(result.explanation == nil)
        #expect(result.answered == 3)
        #expect(result.correct == 1)
    }

    @Test func everyKnowledgeChangeIsKept() async {
        let provider = FakePracticeProvider()
        let changes = [change("kp_1", "函数关系式与导数", 0.43, 0.47),
                       change("kp_2", "导数与单调性", 0.62, 0.64)]
        provider.outcomeToReturn = outcome(changes: changes)
        let model = await loadedModel(provider)
        model.select("B")
        await model.submit()
        #expect(model.outcome?.knowledgeChanges == changes)

        provider.outcomeToReturn = outcome(changes: [])
        let single = await loadedModel(provider)
        single.select("B")
        await single.submit()
        #expect(single.outcome?.knowledgeChanges.isEmpty == true)

        provider.outcomeToReturn = outcome(changes: [changes[0]])
        let one = await loadedModel(provider)
        one.select("B")
        await one.submit()
        #expect(one.outcome?.knowledgeChanges == [changes[0]])
    }

    @Test func tagChangeAndExplanationAreOptional() async {
        let provider = FakePracticeProvider()
        provider.outcomeToReturn = outcome(explanation: nil, tag: nil)
        let model = await loadedModel(provider)
        model.select("B")
        await model.submit()
        #expect(model.outcome?.explanation == nil)
        #expect(model.outcome?.tagChange == nil)

        let tag = PracticeTagChange(questionID: "math.derivative.abc", isCorrect: false,
                                    tags: ["函数关系式与导数的综合应用"],
                                    scores: ["函数关系式与导数的综合应用": 12],
                                    deltas: ["函数关系式与导数的综合应用": -3])
        provider.outcomeToReturn = outcome(correctness: "wrong", isCorrect: false,
                                           correctAnswer: "A", tag: tag)
        let tagged = await loadedModel(provider)
        tagged.select("B")
        await tagged.submit()
        #expect(tagged.outcome?.tagChange == tag)
    }

    @Test func replayedResponseIsAValidSuccessWithoutLocalCounting() async {
        let provider = FakePracticeProvider()
        provider.outcomeToReturn = outcome(replayed: true, answered: 2, correct: 1)
        let model = await loadedModel(provider)
        model.select("B")
        await model.submit()

        #expect(model.outcome?.replayed == true)
        #expect(model.outcome?.answered == 2)
        #expect(model.outcome?.correct == 1)
        #expect(model.session?.answered == 0)   // nothing was optimistically mutated
    }

    // MARK: - Next question / completion

    @Test func continueToNextUsesTheServerNextQuestionAndCounters() async {
        let provider = FakePracticeProvider()
        let next = question("math.derivative.def", index: 2)
        provider.outcomeToReturn = outcome(next: next, answered: 3, correct: 2)
        let model = await loadedModel(provider)
        model.select("B")
        await model.submit()

        #expect(model.canContinue)
        model.continueToNext()

        #expect(model.phase == .answering)
        #expect(model.question == next)
        #expect(model.selectedChoiceKey == nil)
        #expect(model.outcome == nil)
        #expect(model.session?.answered == 3)
        #expect(model.session?.correct == 2)
        #expect(model.session?.nextQuestion == next)
    }

    @Test func completedResultExposesFinishAndNeverGuessesNextQuestion() async {
        let provider = FakePracticeProvider()
        let action = NextLearningAction(kind: "start_tutor", title: "下一步：继续学习",
                                        reason: "本题暴露了薄弱点", buttonTitle: "开始学习",
                                        knowledgePointID: "kp_1", knowledgePointName: "导数与单调性",
                                        wrongQuestionID: nil)
        provider.outcomeToReturn = outcome(next: nil, completed: true, answered: 5, correct: 4,
                                           total: 5, nextAction: action)
        let model = await loadedModel(provider)
        model.select("B")
        await model.submit()

        #expect(model.completedOutcome != nil)
        #expect(!model.canContinue)
        #expect(model.completedOutcome?.nextAction?.kind == "start_tutor")
        #expect(model.session?.answered == 0)   // server state applied only via continueToNext
    }
}

@MainActor
private final class FakePracticeProvider: PracticeDataProviding {
    var sessionToReturn: PracticeSessionState?
    var outcomeToReturn: PracticeAnswerOutcome?
    var failFirstCreate = false
    var failFirstSubmit = false
    var submitError: Error?
    var submitDelay: Duration = .zero
    private(set) var createdKeys: [IdempotencyKey] = []
    private(set) var fetchedIDs: [String] = []
    private(set) var createCount = 0
    private(set) var submitCount = 0
    private(set) var submissions: [PracticeAnswerDraft] = []
    private(set) var submissionKeys: [IdempotencyKey] = []

    func createPracticeSession(knowledgePointID: String?, difficulty: Double?, count: Int,
                               key: IdempotencyKey) async throws -> PracticeSessionState {
        createCount += 1
        createdKeys.append(key)
        if failFirstCreate && createCount == 1 { throw PracticeServiceError.network(.timeout) }
        guard let sessionToReturn else { throw ProviderError.unknownFixtureID("practice") }
        return sessionToReturn
    }

    func fetchPracticeSession(id: String) async throws -> PracticeSessionState {
        fetchedIDs.append(id)
        guard let sessionToReturn else { throw ProviderError.unknownFixtureID(id) }
        return sessionToReturn
    }

    func fetchNextPracticeQuestion(sessionID: String) async throws -> PracticeQuestion {
        guard let question = sessionToReturn?.nextQuestion else {
            throw PracticeServiceError.backend(.noQuestionsAvailable)
        }
        return question
    }

    func submitPracticeAnswer(sessionID: String, questionID: String, selectedKey: String?,
                              key: IdempotencyKey) async throws -> PracticeAnswerOutcome {
        submitCount += 1
        submissions.append(PracticeAnswerDraft(questionID: questionID,
                                               selectedKey: selectedKey ?? ""))
        submissionKeys.append(key)
        if submitDelay != .zero { try await Task.sleep(for: submitDelay) }
        if failFirstSubmit && submitCount == 1 { throw PracticeServiceError.network(.timeout) }
        if let submitError { throw submitError }
        guard let outcomeToReturn else { throw ProviderError.unknownFixtureID(questionID) }
        return outcomeToReturn
    }
}
