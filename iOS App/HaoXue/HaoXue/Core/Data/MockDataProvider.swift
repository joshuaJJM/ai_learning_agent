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

    func fetchPracticeSession(id: String) async throws -> PracticeSession {
        let snapshots = [GoldenDemoFixtures.practiceQuestion, GoldenDemoFixtures.practiceCompleted]
        guard let result = snapshots.first(where: { $0.id == id }) else {
            throw ProviderError.unknownFixtureID(id)
        }
        return result
    }
}
