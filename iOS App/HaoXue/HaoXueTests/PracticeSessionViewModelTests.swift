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

    @Test func initialStateIsIdleWithoutQuestion() {
        let model = PracticeSessionViewModel(provider: FakePracticeProvider())
        #expect(model.phase == .idle)
        #expect(model.session == nil)
        #expect(model.question == nil)
        #expect(model.progressText.isEmpty)
        #expect(model.contextTitle == nil)
        #expect(!model.canSubmit)
        #expect(model.makeSubmission() == nil)
    }

    @Test func liveCreateExposesBackendQuestionAndKeepsItsIdentifiers() async {
        let provider = FakePracticeProvider()
        let key = IdempotencyKey("0f2b7c1e-2f4b-4a1d-9f0e-000000000009")
        provider.sessionToReturn = session(question: question())
        let model = PracticeSessionViewModel(provider: provider, createKey: key)

        await model.load()

        #expect(model.phase == .loaded)
        #expect(model.session?.id == "prac_1")
        #expect(model.question?.id == "math.derivative.abc")
        #expect(model.question?.number == "072")
        #expect(model.question?.choices.map(\.key) == ["A", "B", "C", "D"])
        #expect(model.progressText == "1 / 5")
        #expect(model.contextTitle == "函数关系式与导数的综合应用")
        #expect(provider.createdKeys == [key])
        #expect(provider.createCount == 1)
        #expect(provider.submitCount == 0)
    }

    @Test func knowledgePointModeUsesBackendNameAndMissingContextDoesNotCrash() async {
        let provider = FakePracticeProvider()
        provider.sessionToReturn = session(question: question(), mode: .knowledgePoint,
                                           targetTag: nil)
        let model = PracticeSessionViewModel(provider: provider)
        await model.load()
        #expect(model.phase == .loaded)
        #expect(model.contextTitle == "利用导数判断函数单调性与单调区间")

        provider.sessionToReturn = session(question: question(), mode: .knowledgePoint,
                                           targetTag: nil, knowledgePointName: nil)
        let bare = PracticeSessionViewModel(provider: provider)
        await bare.load()
        #expect(bare.contextTitle == nil)
        #expect(bare.question != nil)
        #expect(bare.phase == .loaded)
    }

    @Test func selectionIsSingleAndOnlyAcceptsBackendChoices() async {
        let provider = FakePracticeProvider()
        provider.sessionToReturn = session(question: question())
        let model = PracticeSessionViewModel(provider: provider)
        await model.load()

        #expect(model.selectedChoiceKey == nil)
        model.select("A")
        #expect(model.selectedChoiceKey == "A")
        model.select("C")
        #expect(model.selectedChoiceKey == "C")
        model.select("Z")
        #expect(model.selectedChoiceKey == "C")
    }

    @Test func submitEligibilityFollowsTheLocalSelection() async {
        let provider = FakePracticeProvider()
        provider.sessionToReturn = session(question: question())
        let model = PracticeSessionViewModel(provider: provider)
        await model.load()

        #expect(!model.canSubmit)
        #expect(model.makeSubmission() == nil)
        model.select("B")
        #expect(model.canSubmit)
        #expect(model.makeSubmission() == PracticeAnswerDraft(questionID: "math.derivative.abc",
                                                              selectedKey: "B"))

        await model.retry()
        #expect(model.selectedChoiceKey == nil)
        #expect(!model.canSubmit)
    }

    @Test func restoreUsesTheKnownSessionInsteadOfCreatingAnother() async {
        let provider = FakePracticeProvider()
        provider.sessionToReturn = session(id: "prac_restored", question: question(index: 2))
        let model = PracticeSessionViewModel(provider: provider, existingSessionID: "prac_restored")

        await model.load()

        #expect(provider.fetchedIDs == ["prac_restored"])
        #expect(provider.createCount == 0)
        #expect(model.session?.id == "prac_restored")
        #expect(model.progressText == "2 / 5")
    }

    @Test func createFailureStaysRecoverableAndRetryReusesTheSameKey() async {
        let provider = FakePracticeProvider()
        provider.sessionToReturn = session(question: question())
        provider.failFirstCreate = true
        let key = IdempotencyKey("phase6b-retry")
        let model = PracticeSessionViewModel(provider: provider, createKey: key)

        await model.load()

        #expect(model.phase == .failed)
        #expect(model.session == nil)
        #expect(model.errorMessage != nil)

        await model.retry()
        #expect(model.phase == .loaded)
        #expect(provider.createdKeys == [key, key])
        #expect(provider.submitCount == 0)
    }

    @Test func backendErrorsKeepTheirOwnCopy() {
        #expect(PracticeError.message(for: PracticeServiceError.backend(.noQuestionsAvailable))
                == "这一组题已经做完了")
        #expect(PracticeError.message(for: PracticeServiceError.backend(.sessionNotFound))
                == "练习记录不存在，请退出后重新开始")
        #expect(PracticeError.message(for: PracticeServiceError.network(.timeout))
                == "网络连接中断，请重试")
    }

    @Test func selectingAnAnswerNeverMutatesServerStateOrInventsAVerdict() async throws {
        let provider = FakePracticeProvider()
        let loaded = session(question: question(), answered: 1, correct: 1, total: 5)
        provider.sessionToReturn = loaded
        let model = PracticeSessionViewModel(provider: provider)
        await model.load()
        let sessionBefore = try #require(model.session)
        let questionBefore = try #require(model.question)

        model.select("D")

        #expect(model.session == sessionBefore)
        #expect(model.question == questionBefore)
        #expect(model.session?.answered == 1)
        #expect(model.session?.correct == 1)
        #expect(model.session?.status == .active)
        #expect(provider.submitCount == 0)
        // 选择后仍只有 draft：没有 correctness / explanation / 下一题。
        #expect(model.makeSubmission() == PracticeAnswerDraft(questionID: "math.derivative.abc",
                                                              selectedKey: "D"))
    }

    @Test func aQuestionWithoutChoicesIsNeverSubmittable() async {
        let provider = FakePracticeProvider()
        provider.sessionToReturn = session(question: question(choices: []))
        let model = PracticeSessionViewModel(provider: provider)
        await model.load()

        model.select("A")
        #expect(model.selectedChoiceKey == nil)
        #expect(!model.canSubmit)

        provider.sessionToReturn = session(question: nil)
        let finished = PracticeSessionViewModel(provider: provider)
        await finished.load()
        #expect(finished.phase == .loaded)
        #expect(finished.question == nil)
        #expect(!finished.canSubmit)
        #expect(finished.progressText.isEmpty)
    }
}

@MainActor
private final class FakePracticeProvider: PracticeDataProviding {
    var sessionToReturn: PracticeSessionState?
    var failFirstCreate = false
    private(set) var createdKeys: [IdempotencyKey] = []
    private(set) var fetchedIDs: [String] = []
    private(set) var createCount = 0
    private(set) var submitCount = 0

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
        throw PracticeServiceError.backend(.questionNotInSession)
    }
}
