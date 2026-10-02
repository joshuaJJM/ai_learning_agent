import Foundation

@MainActor protocol HomeDataProviding {
    func fetchHome() async throws -> HomeState
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

enum ProviderError: Error, Equatable {
    case unknownFixtureID(String)
    case contractNotConfigured
}
