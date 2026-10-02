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
    func fetchPracticeSession(id: String) async throws -> PracticeSession
}
@MainActor protocol WrongQuestionDataProviding {
    func fetchWrongQuestions() async throws -> [WrongQuestionSummary]
    func fetchWrongQuestion(id: String) async throws -> WrongQuestionDetail
    func updateWrongQuestion(id: String, status: String) async throws -> WrongQuestionDetail
}

enum ProviderError: Error, Equatable {
    case unknownFixtureID(String)
    case contractNotConfigured
}
