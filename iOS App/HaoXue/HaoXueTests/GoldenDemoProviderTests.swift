import Foundation
import Testing
@testable import HaoXue

@MainActor
struct GoldenDemoProviderTests {
    @Test func goldenStoryIsConsistent() async throws {
        let before = try await MockDataProvider().fetchHome()
        let after = try await MockDataProvider(home: GoldenDemoFixtures.homeAfter).fetchHome()
        #expect(before.knowledgePoints.first?.mastery == 0.43)
        #expect(after.knowledgePoints.first?.mastery == 0.51)
        #expect(before.nextStep != after.nextStep)
        let provider = MockDataProvider()
        let analysis = try await provider.fetchAnalysis(id: "analysis-completed")
        #expect(analysis.questions.count == 6)
        #expect(analysis.questions.filter { $0.isCorrect == true }.count == 5)
        #expect(analysis.questions.filter { $0.isCorrect == false }.count == 1)
        let wrong = try #require(before.recentWrongQuestions.first)
        #expect(wrong.knowledgePointIDs == ["derivative-monotonicity"])
        #expect(wrong.timestamp == ISO8601DateFormatter().date(from: "2026-10-02T00:00:00Z"))
        #expect(analysis.questions.last?.diagnosis == "导数符号 → 函数性质理解薄弱")
    }

    @Test func snapshotsRemainExplicitAndReusable() async throws {
        let provider = MockDataProvider()
        for (id, status) in [("analysis-queued", AnalysisStatus.queued),
                             ("analysis-processing", .processing),
                             ("analysis-completed", .completed), ("analysis-failed", .failed)] {
            #expect(try await provider.fetchAnalysis(id: id).status == status)
        }
        let diagnose = try await provider.fetchTutorSession(id: "tutor-diagnose")
        let teach = try await provider.fetchTutorSession(id: "tutor-teach")
        let done = try await provider.fetchTutorSession(id: "tutor-completed")
        #expect(diagnose.currentTurn.phase == .diagnose)
        #expect(diagnose.currentTurn.choices?.map(\.id) == [.A, .B, .C, .D])
        #expect(teach.currentTurn.phase == .teach)
        #expect(teach.currentTurn.text.contains("换一种解释"))
        #expect(done.currentTurn.completed)
        let practice = try await provider.fetchPracticeSession(id: "practice-question")
        #expect(practice.currentQuestion?.choices.map(\.id) == [.A, .B, .C, .D])
        #expect(practice.result == nil)
        let result = try await provider.fetchPracticeSession(id: "practice-completed")
        #expect(result.completed)
        #expect(result.result?.isCorrect == true)
        #expect(result.result?.knowledgeChange?.beforeMastery == 0.43)
        #expect(result.result?.knowledgeChange?.afterMastery == 0.51)
        #expect(try await provider.fetchHome().knowledgePoints.first?.mastery == 0.43)
    }

    @Test func unknownFixtureFails() async {
        let provider = MockDataProvider()
        await #expect(throws: ProviderError.unknownFixtureID("missing")) {
            try await provider.fetchAnalysis(id: "missing")
        }
        await #expect(throws: ProviderError.unknownFixtureID("missing")) {
            try await provider.fetchTutorSession(id: "missing")
        }
        await #expect(throws: ProviderError.unknownFixtureID("missing")) {
            try await provider.fetchPracticeSession(id: "missing")
        }
    }
}
