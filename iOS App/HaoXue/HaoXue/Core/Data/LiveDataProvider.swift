import Foundation

@MainActor
struct LiveDataProvider: HomeDataProviding, AnalysisDataProviding, TutorDataProviding, PracticeDataProviding {
    // Reserved for future APIClient → DTO → Mapper composition inside this provider.
    private let client: APIClient
    private let configuration: AppConfiguration

    init(client: APIClient, configuration: AppConfiguration) {
        self.client = client
        self.configuration = configuration
    }

    func fetchHome() async throws -> HomeState {
        throw ProviderError.contractNotConfigured
    }
    func fetchAnalysis(id: String) async throws -> UploadAnalysis {
        throw ProviderError.contractNotConfigured
    }
    func fetchTutorSession(id: String) async throws -> TutorSession {
        throw ProviderError.contractNotConfigured
    }
    func fetchPracticeSession(id: String) async throws -> PracticeSession {
        throw ProviderError.contractNotConfigured
    }
}
