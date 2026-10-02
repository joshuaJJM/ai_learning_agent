import Foundation

// Auxiliary information only. A failure here must never block the Tutor session,
// so every caller treats an error as "no overview available" instead of failing.
@MainActor
protocol MasteryOverviewServing {
    func fetchOverview() async throws -> MasteryOverview
}

@MainActor
final class MasteryOverviewService: MasteryOverviewServing {
    let baseURL: URL
    private let client: APIClient
    private let mapper = MasteryOverviewMapper()

    init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        // The overview is small and non-blocking; keep its timeout well below the Tutor's.
        client = APIClient(session: session, timeout: 12)
    }

    func makeOverviewRequest() -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/v1/knowledge/mastery-overview"))
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    func fetchOverview() async throws -> MasteryOverview {
        let (data, response) = try await client.sendData(makeOverviewRequest())
        guard (200...299).contains(response.statusCode) else {
            throw NetworkError.httpStatus(response.statusCode)
        }
        let dto = try MasteryOverviewJSON.decoder.decode(MasteryOverviewDTO.self, from: data)
        return mapper.map(dto)
    }
}

enum MasteryOverviewJSON {
    static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}
