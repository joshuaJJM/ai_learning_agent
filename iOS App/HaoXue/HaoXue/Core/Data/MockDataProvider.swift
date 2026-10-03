import Foundation

@MainActor
struct MockDataProvider: HomeDataProviding, AnalysisDataProviding, TutorDataProviding, PracticeDataProviding {
    private let home: HomeState

    init() {
        self.init(home: GoldenDemoFixtures.homeBefore)
    }

    init(home: HomeState) {
        self.home = home
    }

    func fetchHome() async throws -> HomeState { home }

    func fetchAnalysis(id: String) async throws -> UploadAnalysis {
        let snapshots = [GoldenDemoFixtures.analysisQueued, GoldenDemoFixtures.analysisProcessing,
                         GoldenDemoFixtures.analysisCompleted, GoldenDemoFixtures.analysisFailed]
        guard let result = snapshots.first(where: { $0.id == id }) else {
            throw ProviderError.unknownFixtureID(id)
        }
        return result
    }

    func fetchTutorSession(id: String) async throws -> TutorSession {
        let snapshots = [GoldenDemoFixtures.tutorDiagnose, GoldenDemoFixtures.tutorTeach,
                         GoldenDemoFixtures.tutorCompleted]
        guard let result = snapshots.first(where: { $0.id == id }) else {
            throw ProviderError.unknownFixtureID(id)
        }
        return result
    }

    func createPracticeSession(knowledgePointID: String?, difficulty: Double?, count: Int,
                               key: IdempotencyKey) async throws -> PracticeSessionState {
        knowledgePointID == nil ? GoldenDemoFixtures.practiceTagSession
                                : GoldenDemoFixtures.practiceKnowledgePointSession
    }

    func fetchPracticeSession(id: String) async throws -> PracticeSessionState {
        let snapshots = [GoldenDemoFixtures.practiceTagSession,
                         GoldenDemoFixtures.practiceKnowledgePointSession,
                         GoldenDemoFixtures.practiceCompletedSession]
        guard let result = snapshots.first(where: { $0.id == id }) else {
            throw ProviderError.unknownFixtureID(id)
        }
        return result
    }

    func fetchNextPracticeQuestion(sessionID: String) async throws -> PracticeQuestion {
        let session = try await fetchPracticeSession(id: sessionID)
        guard let question = session.nextQuestion else {
            // 与后端一致：题做完了返回 NO_QUESTIONS_AVAILABLE。
            throw PracticeServiceError.backend(.noQuestionsAvailable)
        }
        return question
    }

    // Mock never judges an answer: the outcome is a fixed server-shaped snapshot.
    func submitPracticeAnswer(sessionID: String, questionID: String, selectedKey: String?,
                              key: IdempotencyKey) async throws -> PracticeAnswerOutcome {
        if questionID == GoldenDemoFixtures.practiceAnswerOutcome.questionID {
            return GoldenDemoFixtures.practiceAnswerOutcome
        }
        if questionID == GoldenDemoFixtures.practiceCompletedOutcome.questionID {
            return GoldenDemoFixtures.practiceCompletedOutcome
        }
        throw ProviderError.unknownFixtureID(questionID)
    }
}
