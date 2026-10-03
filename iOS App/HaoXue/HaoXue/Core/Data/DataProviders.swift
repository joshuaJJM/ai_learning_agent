import Foundation

@MainActor protocol HomeDataProviding {
    func fetchHome() async throws -> HomeState
}
@MainActor protocol HomeSnapshotProviding {
    func fetchHomeSnapshot() async throws -> HomeSnapshot
}
@MainActor protocol AnalysisDataProviding {
    func fetchAnalysis(id: String) async throws -> UploadAnalysis
}
@MainActor protocol TutorDataProviding {
    func fetchTutorSession(id: String) async throws -> TutorSession
}
@MainActor protocol PracticeDataProviding {
    func createPracticeSession(knowledgePointID: String?, difficulty: Double?,
                               count: Int, key: IdempotencyKey) async throws -> PracticeSessionState
    func fetchPracticeSession(id: String) async throws -> PracticeSessionState
    func fetchNextPracticeQuestion(sessionID: String) async throws -> PracticeQuestion
    func submitPracticeAnswer(sessionID: String, questionID: String, selectedKey: String?,
                              key: IdempotencyKey) async throws -> PracticeAnswerOutcome
}
@MainActor protocol WrongQuestionDataProviding {
    func fetchWrongQuestions() async throws -> [WrongQuestionSummary]
    func fetchWrongQuestion(id: String) async throws -> WrongQuestionDetail
    func updateWrongQuestion(id: String, status: String) async throws -> WrongQuestionDetail
}
@MainActor protocol KnowledgeDataProviding {
    func fetchKnowledgeDetail(id: String) async throws -> KnowledgePointDetail
    func fetchKnowledgeOverview() async throws -> KnowledgeOverview
    func fetchRelatedWrongQuestions(knowledgePointID: String) async throws -> [WrongQuestionSummary]
}

enum ProviderError: Error, Equatable {
    case unknownFixtureID(String)
    case contractNotConfigured
}
