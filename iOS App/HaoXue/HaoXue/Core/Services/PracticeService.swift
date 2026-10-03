import Foundation

/// Identity of one *logical* write. The caller owns it and reuses it for every
/// transport retry, so the server can replay instead of scoring twice.
struct IdempotencyKey: Equatable, Hashable {
    let value: String

    init(_ value: String) { self.value = value }

    static func generate() -> IdempotencyKey { IdempotencyKey(UUID().uuidString) }
}

enum PracticeServiceError: Error, Equatable {
    case backend(ServiceErrorCode)
    case network(NetworkError)

    init(_ error: NetworkError) {
        if case .backend(let code, _, _, _) = error {
            self = .backend(ServiceErrorCode(rawValue: code))
        } else {
            self = .network(error)
        }
    }

    var code: ServiceErrorCode? {
        if case .backend(let code) = self { return code }
        return nil
    }
}

@MainActor
final class PracticeService {
    let baseURL: URL
    private let client: APIClient
    private let mapper = PracticeMapper()
    private let retryDelay: Duration

    init(baseURL: URL, client: APIClient? = nil, retryDelay: Duration = .seconds(1)) {
        self.baseURL = baseURL
        self.client = client ?? APIClient()
        self.retryDelay = retryDelay
    }

    // MARK: - Requests

    func makeCreateSessionRequest(knowledgePointID: String?, difficulty: Double?,
                                  bookID: String? = nil, count: Int,
                                  key: IdempotencyKey) throws -> URLRequest {
        var request = URLRequest(url: url("practice/sessions"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(key.value, forHTTPHeaderField: "Idempotency-Key")
        request.httpBody = try BackendJSON.encoder.encode(
            PracticeSessionCreateRequestDTO(knowledgePointId: knowledgePointID,
                                            difficulty: difficulty, bookId: bookID,
                                            count: count, clientRequestId: key.value))
        return request
    }

    func makeSessionRequest(id: String) -> URLRequest {
        var request = URLRequest(url: url("practice/sessions/\(id)"))
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    func makeNextQuestionRequest(sessionID: String) -> URLRequest {
        var request = URLRequest(url: url("practice/sessions/\(sessionID)/next"))
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    func makeAnswerRequest(sessionID: String, questionID: String, selectedKey: String?,
                           answerText: String?, key: IdempotencyKey) throws -> URLRequest {
        var request = URLRequest(url: url("practice/sessions/\(sessionID)/answers"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(key.value, forHTTPHeaderField: "Idempotency-Key")
        request.httpBody = try BackendJSON.encoder.encode(
            PracticeAnswerRequestDTO(questionId: questionID, selectedKey: selectedKey,
                                     answerText: answerText, clientRequestId: key.value))
        return request
    }

    // MARK: - Endpoints

    func createSession(knowledgePointID: String?, difficulty: Double?, bookID: String? = nil,
                       count: Int, key: IdempotencyKey) async throws -> PracticeSessionState {
        let request = try makeCreateSessionRequest(knowledgePointID: knowledgePointID,
                                                   difficulty: difficulty, bookID: bookID,
                                                   count: count, key: key)
        return mapper.session(try await send(request, as: PracticeSessionDTO.self))
    }

    func fetchSession(id: String) async throws -> PracticeSessionState {
        mapper.session(try await send(makeSessionRequest(id: id), as: PracticeSessionDTO.self))
    }

    func fetchNextQuestion(sessionID: String) async throws -> PracticeQuestion {
        mapper.question(try await send(makeNextQuestionRequest(sessionID: sessionID),
                                       as: PracticeQuestionDTO.self))
    }

    func submitAnswer(sessionID: String, questionID: String, selectedKey: String? = nil,
                      answerText: String? = nil,
                      key: IdempotencyKey) async throws -> PracticeAnswerOutcome {
        let request = try makeAnswerRequest(sessionID: sessionID, questionID: questionID,
                                            selectedKey: selectedKey, answerText: answerText,
                                            key: key)
        return mapper.answer(try await send(request, as: PracticeAnswerResponseDTO.self))
    }

    // MARK: - Transport

    /// The same logical request is resent with the same idempotency key while the
    /// server is still processing it; the key is never regenerated here.
    private func send<DTO: Decodable>(_ request: URLRequest, as type: DTO.Type) async throws -> DTO {
        var attempt = 0
        while true {
            do {
                return try await client.send(request, as: DTO.self)
            } catch let error as NetworkError {
                let failure = PracticeServiceError(error)
                guard failure.code == .idempotencyConflict, attempt < 2 else { throw failure }
                attempt += 1
                try await Task.sleep(for: retryDelay)
            }
        }
    }

    private func url(_ path: String) -> URL {
        var url = baseURL.appendingPathComponent("api/v1")
        for segment in path.split(separator: "/") {
            url.appendPathComponent(String(segment))
        }
        return url
    }
}
