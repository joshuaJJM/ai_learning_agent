import Foundation

enum TutorRemoteError: Error {
    case backend(ServiceErrorCode)
    case invalidResponse
    case incompleteStream
}

enum TutorStreamEvent {
    case meta(TutorStreamMetaDTO)
    case delta(String)
    case turn(TutorTurnDTO)
    case done(TutorStreamDoneDTO)
}

@MainActor
protocol TutorRemoteServing {
    func createSession(key: String) async throws -> TutorSessionDTO
    func submit(sessionId: String, selectedKey: String?, text: String?, key: String,
                onEvent: @escaping @MainActor (TutorStreamEvent) -> Void) async throws -> TutorTurnResponseDTO
}

@MainActor
final class TutorRemoteService: TutorRemoteServing {
    let baseURL: URL
    let knowledgePointID: String?
    private let session: URLSession
    private let client: APIClient
    private var answeringTurnIDs: [String: String] = [:]

    init(baseURL: URL, knowledgePointID: String? = nil, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.knowledgePointID = knowledgePointID
        self.session = session
        client = APIClient(session: session, timeout: 60)
    }

    func makeCreateRequest(key: String) throws -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/v1/tutor/sessions"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(key, forHTTPHeaderField: "Idempotency-Key")
        request.httpBody = try TutorJSON.encoder.encode(
            TutorCreateRequestDTO(sourceType: "knowledge_point", knowledgePointId: knowledgePointID,
                                  clientRequestId: key)
        )
        return request
    }

    func makeTurnRequest(sessionId: String, selectedKey: String?, text: String? = nil,
                         key: String, stream: Bool, answeringTurnId: String? = nil) throws -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/v1/tutor/sessions/\(sessionId)/turns"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(stream ? "text/event-stream" : "application/json", forHTTPHeaderField: "Accept")
        request.setValue(key, forHTTPHeaderField: "Idempotency-Key")
        request.timeoutInterval = 60
        request.httpBody = try TutorJSON.encoder.encode(TutorAnswerRequestDTO(
            selectedKey: selectedKey, text: text, selfReportedConfidence: "guess",
            clientRequestId: key, answeringTurnId: answeringTurnId, stream: stream
        ))
        return request
    }

    func createSession(key: String) async throws -> TutorSessionDTO {
        let request = try makeCreateRequest(key: key)
        let dto = try await sendJSON(request, as: TutorSessionDTO.self)
        answeringTurnIDs[dto.tutorSessionId] = dto.turn?.turnId
        return dto
    }

    func fetchSession(id: String) async throws -> TutorSessionDTO {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/v1/tutor/sessions/\(id)"))
        request.httpMethod = "GET"
        let dto = try await sendJSON(request, as: TutorSessionDTO.self)
        answeringTurnIDs[id] = dto.turn?.turnId
        return dto
    }

    func submit(sessionId: String, selectedKey: String?, text: String?, key: String,
                onEvent: @escaping @MainActor (TutorStreamEvent) -> Void) async throws -> TutorTurnResponseDTO {
        let request = try makeTurnRequest(sessionId: sessionId, selectedKey: selectedKey,
                                          text: text, key: key, stream: true,
                                          answeringTurnId: answeringTurnIDs[sessionId])
        var parser = TutorSSEParser()
        var sawTurn = false
        var sawDone = false
        var bytes: URLSession.AsyncBytes?
        for attempt in 0..<3 {
            let (candidate, response) = try await session.bytes(for: request)
            guard let http = response as? HTTPURLResponse else { throw TutorRemoteError.invalidResponse }
            if (200...299).contains(http.statusCode) {
                bytes = candidate
                break
            }
            var data = Data()
            for try await byte in candidate { data.append(byte) }
            let error = decodeError(data)
            if case TutorRemoteError.backend(.idempotencyConflict) = error, attempt < 2 {
                try await Task.sleep(for: .seconds(1))
                continue
            }
            throw error
        }
        guard let bytes else { throw TutorRemoteError.invalidResponse }
        for try await byte in bytes {
            try Task.checkCancellation()
            for frame in try parser.append(Data([byte])) {
                switch frame.event {
                case "meta":
                    onEvent(.meta(try TutorJSON.decoder.decode(TutorStreamMetaDTO.self, from: frame.data)))
                case "delta":
                    onEvent(.delta(try TutorJSON.decoder.decode(TutorStreamDeltaDTO.self, from: frame.data).content))
                case "turn":
                    sawTurn = true
                    onEvent(.turn(try TutorJSON.decoder.decode(TutorTurnDTO.self, from: frame.data)))
                case "done":
                    sawDone = true
                    onEvent(.done(try TutorJSON.decoder.decode(TutorStreamDoneDTO.self, from: frame.data)))
                case "error":
                    throw decodeError(frame.data)
                default: break
                }
            }
        }
        guard sawTurn && sawDone else { throw TutorRemoteError.incompleteStream }

        // The SSE envelope omits evaluation and knowledge_changes; same-key JSON replay is read-only.
        let replay = try makeTurnRequest(sessionId: sessionId, selectedKey: selectedKey,
                                         text: text, key: key, stream: false,
                                         answeringTurnId: answeringTurnIDs[sessionId])
        let result = try await sendJSON(replay, as: TutorTurnResponseDTO.self)
        answeringTurnIDs[sessionId] = result.turn.turnId
        return result
    }

    private func sendJSON<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        for attempt in 0..<3 {
            let (data, response) = try await client.sendData(request)
            if (200...299).contains(response.statusCode) {
                return try TutorJSON.decoder.decode(type, from: data)
            }
            let error = decodeError(data)
            if case TutorRemoteError.backend(.idempotencyConflict) = error, attempt < 2 {
                try await Task.sleep(for: .seconds(1))
                continue
            }
            throw error
        }
        throw TutorRemoteError.invalidResponse
    }

    private func decodeError(_ data: Data) -> TutorRemoteError {
        guard let error = try? TutorJSON.decoder.decode(TutorBackendErrorDTO.self, from: data) else {
            return .invalidResponse
        }
        return .backend(ServiceErrorCode(rawValue: error.errorCode))
    }
}
