import Foundation
import Testing
@testable import HaoXue

@MainActor
struct PracticeCompletionCoordinatorTests {
    /// Stands in for the answer mutation lifecycle: post-completion refreshes
    /// must never reach it.
    private let answerRequests = AnswerSubmitSpy()

    private func outcome(completed: Bool = true, answered: Int = 5, correct: Int = 4,
                         total: Int = 5) -> PracticeAnswerOutcome {
        PracticeAnswerOutcome(
            sessionID: "prac_1", questionID: "math.derivative.abc", correctness: "correct",
            isCorrect: true, correctAnswer: "B", explanation: "解析",
            knowledgeChanges: [KnowledgeChange(knowledgePointID: "kp_1", beforeMastery: 0.5,
                                               afterMastery: 0.65, summary: "导数与单调性",
                                               delta: 0.15, evidenceCount: 12)],
            tagChange: PracticeTagChange(questionID: "math.derivative.abc", isCorrect: true,
                                         tags: ["导数与单调性"], scores: ["导数与单调性": 34],
                                         deltas: ["导数与单调性": 2]),
            replayed: false, nextQuestion: nil, sessionCompleted: completed, answered: answered,
            correct: correct, total: total,
            nextAction: NextLearningAction(kind: "start_tutor", title: "下一步：继续学习",
                                           reason: "薄弱点仍然存在", buttonTitle: "开始学习",
                                           knowledgePointID: "kp_1",
                                           knowledgePointName: "导数与单调性",
                                           wrongQuestionID: nil))
    }

    @Test func practiceCompletionRefreshesHomeAndKnowledgeAndKeepsTheOutcome() async {
        let spy = RefreshSpy()
        let coordinator = PracticeCompletionCoordinator(refreshHome: { await spy.home() },
                                                        refreshKnowledge: { await spy.knowledge() })
        let completed = outcome()

        await coordinator.practiceCompleted(completed)

        #expect(spy.homeCalls == 1)
        #expect(spy.knowledgeCalls == 1)
        #expect(coordinator.notice == .refreshed)
        let kept = coordinator.lastCompletion
        #expect(kept == completed)
        #expect(kept?.nextAction?.kind == "start_tutor")
        #expect(kept?.nextAction?.knowledgePointID == "kp_1")
        #expect(kept?.knowledgeChanges.count == 1)
        #expect(kept?.answered == 5 && kept?.correct == 4 && kept?.total == 5)
        #expect(answerRequests.submitCount == 0)
    }

    @Test func refreshFailureKeepsTheCompletionAndOnlyRetriesReads() async {
        let spy = RefreshSpy()
        spy.homeResult = false
        let coordinator = PracticeCompletionCoordinator(refreshHome: { await spy.home() },
                                                        refreshKnowledge: { await spy.knowledge() })
        await coordinator.practiceCompleted(outcome())

        #expect(coordinator.notice == .refreshFailed("练习已完成 · 学习状态暂时无法刷新"))
        #expect(coordinator.lastCompletion != nil)          // practice 完成仍然是事实
        #expect(answerRequests.submitCount == 0)

        spy.homeResult = true
        await coordinator.refreshLearningState()

        #expect(coordinator.notice == .refreshed)
        #expect(spy.homeCalls == 2)
        #expect(spy.knowledgeCalls == 2)
        #expect(answerRequests.submitCount == 0)            // refresh 绝不重放 mutation
    }

    @Test func refreshedBackendValueWinsOverThePracticeKnowledgeChange() async {
        let spy = RefreshSpy()
        var displayedMastery: Double? = 0.43
        let coordinator = PracticeCompletionCoordinator(
            refreshHome: {
                displayedMastery = await spy.refreshedHomeMastery()
                return true
            },
            refreshKnowledge: { await spy.knowledge() })
        let completed = outcome()                            // knowledge_changes: 0.5 → 0.65

        await coordinator.practiceCompleted(completed)

        // GET 回来的权威值才是最终展示值，绝不用 delta 本地推算。
        #expect(displayedMastery == 0.6492)
        #expect(coordinator.lastCompletion?.knowledgeChanges.first?.afterMastery == 0.65)
        #expect(answerRequests.submitCount == 0)
    }

    @Test func noticeCanBeDismissed() async {
        let spy = RefreshSpy()
        let coordinator = PracticeCompletionCoordinator(refreshHome: { await spy.home() },
                                                        refreshKnowledge: { await spy.knowledge() })
        await coordinator.practiceCompleted(outcome())
        #expect(coordinator.notice != nil)
        coordinator.dismissNotice()
        #expect(coordinator.notice == nil)
    }
}

@MainActor
private final class RefreshSpy {
    var homeCalls = 0
    var knowledgeCalls = 0
    var homeResult = true
    var knowledgeResult = true
    var backendHomeMastery = 0.6492

    func home() async -> Bool {
        homeCalls += 1
        return homeResult
    }

    func knowledge() async -> Bool {
        knowledgeCalls += 1
        return knowledgeResult
    }

    func refreshedHomeMastery() async -> Double {
        backendHomeMastery
    }
}

@MainActor
private final class AnswerSubmitSpy: PracticeDataProviding {
    private(set) var submitCount = 0

    func createPracticeSession(knowledgePointID: String?, difficulty: Double?, count: Int,
                               key: IdempotencyKey) async throws -> PracticeSessionState {
        throw ProviderError.unknownFixtureID("create")
    }

    func fetchPracticeSession(id: String) async throws -> PracticeSessionState {
        throw ProviderError.unknownFixtureID(id)
    }

    func fetchNextPracticeQuestion(sessionID: String) async throws -> PracticeQuestion {
        throw ProviderError.unknownFixtureID(sessionID)
    }

    func submitPracticeAnswer(sessionID: String, questionID: String, selectedKey: String?,
                              key: IdempotencyKey) async throws -> PracticeAnswerOutcome {
        submitCount += 1
        throw ProviderError.unknownFixtureID(questionID)
    }
}
