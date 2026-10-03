import Foundation

/// One *logical* confirmation keeps one key for its whole life, so a timeout
/// followed by「重试」replays instead of writing a second Evidence row.
/// A different answer is a different logical operation and gets its own key.
@MainActor
final class AnswerConfirmationKeyStore {
    private var keys: [String: String] = [:]

    func key(questionID: String, correctAnswer: String) -> String {
        let identity = "\(questionID)|\(correctAnswer)"
        if let existing = keys[identity] { return existing }
        let created = UUID().uuidString
        keys[identity] = created
        return created
    }
}

/// Live manual answer confirmation (`POST …/confirm-answer`, contract 8A-final).
///
/// The client only ever sends *the standard answer the student read from the
/// answer book*; correctness / Evidence / mastery are computed server-side.
@MainActor
final class LiveAnswerConfirmationService: AnswerConfirming {
    let baseURL: URL
    let client: APIClient
    let analysisID: String
    private let keys = AnswerConfirmationKeyStore()
    private let retryDelay: Duration
    private(set) var lastOutcome: ConfirmAnswerResponseDTO?

    init(baseURL: URL, client: APIClient, analysisID: String,
         retryDelay: Duration = .seconds(1)) {
        self.baseURL = baseURL
        self.client = client
        self.analysisID = analysisID
        self.retryDelay = retryDelay
    }

    func makeRequest(questionID: String, correctAnswer: String,
                     key: String) throws -> URLRequest {
        var url = baseURL.appendingPathComponent("api/v1/homework/analyses")
        url.appendPathComponent(analysisID)
        url.appendPathComponent("questions")
        url.appendPathComponent(questionID)
        url.appendPathComponent("confirm-answer")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(key, forHTTPHeaderField: "Idempotency-Key")
        request.httpBody = try BackendJSON.encoder.encode(
            ConfirmAnswerRequestDTO(correctAnswer: correctAnswer, clientRequestId: key))
        return request
    }

    func confirm(questionID: String, correctAnswer: String) async throws {
        let key = keys.key(questionID: questionID, correctAnswer: correctAnswer)
        let request = try makeRequest(questionID: questionID, correctAnswer: correctAnswer, key: key)
        var attempt = 0
        while true {
            do {
                lastOutcome = try await client.send(request, as: ConfirmAnswerResponseDTO.self)
                return
            } catch let error as NetworkError {
                // The same key is still processing on the server: wait and resend
                // the identical request (never a fresh key).
                guard case .backend(let code, _, _, _) = error,
                      ServiceErrorCode(rawValue: code) == .idempotencyConflict,
                      attempt < 2 else { throw error }
                attempt += 1
                try await Task.sleep(for: retryDelay)
            }
        }
    }
}
