import Foundation
import Testing
@testable import HaoXue

@MainActor
struct PracticeContractTests {
    private func fixture(_ name: String) throws -> Data {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/\(name).json")
        return try Data(contentsOf: url)
    }

    private func object(_ data: Data) throws -> [String: Any] {
        try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private func session(_ stub: AnyClass) -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [stub]
        return URLSession(configuration: configuration)
    }

    private let baseURL = URL(string: "http://fixture.invalid")!

    // MARK: - DTO decoding (captured from the live backend)

    @Test func liveTagSessionKeepsServerSelectionMetadata() throws {
        let dto = try BackendJSON.decoder.decode(PracticeSessionDTO.self,
                                                 from: fixture("PracticeSessionTag"))
        let state = PracticeMapper().session(dto)
        #expect(state.id == dto.practiceSessionId)
        #expect(state.status == .active)
        #expect(state.selectionMode == .tag)
        #expect(state.targetTag == dto.targetTag)
        #expect(state.targetTag == "函数关系式与导数的综合应用")
        #expect(state.targetTagScore == dto.targetTagScore)
        #expect(state.pickedTags == (dto.pickedTags ?? []))
        #expect(state.answered == 0 && state.correct == 0 && state.total == 5)
        #expect(state.nextQuestion?.index == 1)
        #expect(state.nextQuestion?.total == 5)
    }

    @Test func liveKnowledgePointSessionKeepsEmptyTagMetadata() throws {
        let dto = try BackendJSON.decoder.decode(PracticeSessionDTO.self,
                                                 from: fixture("PracticeSessionKnowledgePoint"))
        let state = PracticeMapper().session(dto)
        #expect(state.selectionMode == .knowledgePoint)
        #expect(state.knowledgePointID == "math.derivative.monotonicity")
        #expect(state.targetTag == nil)
        #expect(state.targetTagScore == nil)
        #expect(state.pickedTags.isEmpty)
    }

    @Test func liveQuestionPayloadNeverCarriesTheAnswer() throws {
        let data = try fixture("PracticeQuestion")
        let dto = try BackendJSON.decoder.decode(PracticeQuestionDTO.self, from: data)
        let question = PracticeMapper().question(dto)

        let raw = try object(data)
        #expect(raw["answer"] == nil)
        #expect(raw["correct_answer"] == nil)
        #expect(raw["explanation"] == nil)

        #expect(question.id == dto.questionId)
        #expect(question.number == dto.questionNumber)
        #expect(question.choices.map(\.key) == dto.choices.map(\.key))
        #expect(question.choices.map(\.key) == ["A", "B", "C", "D"])
        #expect(question.difficulty == dto.difficulty)
        #expect(question.knowledgePoints.map(\.id) == (dto.knowledgePoints ?? []).map(\.knowledgePointId))
        #expect(question.tags == (dto.tags ?? []))
        #expect(question.index == dto.index && question.total == dto.total)
    }

    @Test func liveAnswerKeepsEveryServerVerdict() throws {
        let dto = try BackendJSON.decoder.decode(PracticeAnswerResponseDTO.self,
                                                from: fixture("PracticeAnswer"))
        let outcome = PracticeMapper().answer(dto)
        #expect(outcome.sessionID == dto.practiceSessionId)
        #expect(outcome.questionID == dto.questionId)
        #expect(outcome.correctness == dto.correctness)
        #expect(outcome.isCorrect == dto.isCorrect)
        #expect(outcome.correctAnswer == dto.correctAnswer)
        #expect(outcome.explanation == dto.explanation)
        #expect(outcome.replayed == false)
        #expect(outcome.sessionCompleted)
        #expect(outcome.nextQuestion == nil)
        #expect(outcome.answered == 1 && outcome.total == 1 && outcome.correct == 0)
        #expect(outcome.nextAction?.kind == dto.nextAction?.action)
    }

    @Test func liveAnswerKeepsMultipleKnowledgeChangesAndTagChange() throws {
        let dto = try BackendJSON.decoder.decode(PracticeAnswerResponseDTO.self,
                                                from: fixture("PracticeAnswer"))
        let outcome = PracticeMapper().answer(dto)
        let changes = try #require(dto.knowledgeChanges)
        #expect(changes.count == 2)
        #expect(outcome.knowledgeChanges.count == changes.count)
        #expect(outcome.knowledgeChanges.map(\.knowledgePointID) == changes.map(\.knowledgePointId))
        #expect(outcome.knowledgeChanges.map(\.beforeMastery) == changes.map { $0.before })
        #expect(outcome.knowledgeChanges.map(\.afterMastery) == changes.map { $0.after })
        #expect(outcome.knowledgeChanges.map(\.delta) == changes.map { $0.delta })
        let tag = try #require(dto.tagChanges)
        #expect(outcome.tagChange?.questionID == tag.questionId)
        #expect(outcome.tagChange?.delta == tag.delta)
        #expect(outcome.tagChange?.tags == (tag.tags ?? []))
    }

    @Test func liveCompletedSessionHasNoNextQuestion() throws {
        let dto = try BackendJSON.decoder.decode(PracticeSessionDTO.self,
                                                 from: fixture("PracticeSessionCompleted"))
        let state = PracticeMapper().session(dto)
        #expect(state.status == .completed)
        #expect(state.nextQuestion == nil)
        #expect(state.answered == state.total)
        #expect(state.total == 1 && state.correct == 0)
    }

    @Test func optionalAnswerFieldsStayOptional() throws {
        let json = """
        {"practice_session_id":"prac_edge","question_id":"q_edge","correctness":"unknown",
         "is_correct":false,"correct_answer":"C","explanation":null,"knowledge_changes":[],
         "tag_changes":null,"replayed":true,
         "next_question":{"question_id":"q_next","question_number":"073","stem":"题干",
           "choices":[{"key":"A","text":"甲"},{"key":"B","text":"乙"}],"difficulty":0.5,
           "index":2,"total":5},
         "session_completed":false,"answered":1,"correct":0,"total":5,"next_action":null}
        """
        let dto = try BackendJSON.decoder.decode(PracticeAnswerResponseDTO.self,
                                                from: Data(json.utf8))
        let outcome = PracticeMapper().answer(dto)
        // 判定、进度、完成度全部照抄服务端，客户端不做任何推导。
        #expect(outcome.correctness == "unknown")
        #expect(outcome.isCorrect == false)
        #expect(outcome.explanation == nil)
        #expect(outcome.knowledgeChanges.isEmpty)
        #expect(outcome.tagChange == nil)
        #expect(outcome.replayed)
        #expect(outcome.sessionCompleted == false)
        #expect(outcome.nextQuestion?.id == "q_next")
        #expect(outcome.nextQuestion?.choices.map(\.key) == ["A", "B"])
        #expect(outcome.nextAction == nil)
        #expect(outcome.answered == 1 && outcome.correct == 0 && outcome.total == 5)
    }

    @Test func unknownStatesPreserveRawValues() {
        #expect(PracticeSessionStatus(rawValue: "future_status") == .unknown("future_status"))
        #expect(PracticeSelectionMode(rawValue: "future_mode") == .unknown("future_mode"))
        #expect(PracticeSessionStatus(rawValue: "abandoned") == .abandoned)
    }

    // MARK: - Networking

    @Test func createRequestCarriesJSONAndLogicalIdentity() throws {
        let service = PracticeService(baseURL: baseURL)
        let key = IdempotencyKey.generate()
        let request = try service.makeCreateSessionRequest(knowledgePointID: nil, difficulty: nil,
                                                           count: 5, key: key)
        #expect(request.httpMethod == "POST")
        #expect(request.url?.path == "/api/v1/practice/sessions")
        #expect(request.value(forHTTPHeaderField: "Content-Type") == "application/json")
        #expect(request.value(forHTTPHeaderField: "Idempotency-Key") == key.value)
        let body = try object(try #require(request.httpBody))
        #expect(body["count"] as? Int == 5)
        #expect(body["client_request_id"] as? String == key.value)
        // 不指定知识点时必须让服务器走 tag 推荐：缺省或 null 等价。
        #expect(body["knowledge_point_id"] == nil || body["knowledge_point_id"] is NSNull)
    }

    @Test func answerRequestCarriesQuestionSelectionAndKey() throws {
        let service = PracticeService(baseURL: baseURL)
        let key = IdempotencyKey.generate()
        let request = try service.makeAnswerRequest(sessionID: "prac_1", questionID: "q_1",
                                                    selectedKey: "C", answerText: nil, key: key)
        #expect(request.httpMethod == "POST")
        #expect(request.url?.path == "/api/v1/practice/sessions/prac_1/answers")
        #expect(request.value(forHTTPHeaderField: "Content-Type") == "application/json")
        #expect(request.value(forHTTPHeaderField: "Idempotency-Key") == key.value)
        let body = try object(try #require(request.httpBody))
        #expect(body["question_id"] as? String == "q_1")
        #expect(body["selected_key"] as? String == "C")
        #expect(body["client_request_id"] as? String == key.value)
    }

    @Test func liveProviderUsesPracticeEndpointsInsteadOfMockFallback() async throws {
        let session = session(PracticeFixtureStub.self)
        defer { session.invalidateAndCancel() }
        PracticeFixtureStub.reset(PracticeFixtureStub.self)
        let provider = LiveDataProvider(client: APIClient(session: session),
                                        configuration: AppConfiguration(mode: .live,
                                                                        baseURL: baseURL))
        let state = try await provider.fetchPracticeSession(id: "prac_live")
        // 服务端返回的 session id 是唯一权威，路径里的 id 不会覆盖它。
        #expect(state.id == "prac_22846ffc05c147c1a1c6")
        #expect(state.selectionMode == .tag)
        #expect(PracticeFixtureStub.requests(PracticeFixtureStub.self).map(\.path)
                == ["/api/v1/practice/sessions/prac_live"])
    }

    @Test func conflictRetryReusesTheSameLogicalRequestIdentity() async throws {
        let session = session(PracticeConflictThenSuccessStub.self)
        defer { session.invalidateAndCancel() }
        PracticeConflictThenSuccessStub.reset(PracticeConflictThenSuccessStub.self)
        let service = PracticeService(baseURL: baseURL, client: APIClient(session: session),
                                      retryDelay: .zero)
        let key = IdempotencyKey("0f2b7c1e-2f4b-4a1d-9f0e-000000000001")
        let outcome = try await service.submitAnswer(sessionID: "prac_live", questionID: "q_live",
                                                     selectedKey: "A", key: key)
        #expect(outcome.correctness == "wrong")
        let requests = PracticeConflictThenSuccessStub.requests(PracticeConflictThenSuccessStub.self)
        #expect(requests.count == 2)
        #expect(requests.map(\.idempotencyKey) == [key.value, key.value])
        #expect(requests.map(\.clientRequestId) == [key.value, key.value])
        #expect(requests.map(\.path)
                == ["/api/v1/practice/sessions/prac_live/answers",
                    "/api/v1/practice/sessions/prac_live/answers"])
    }

    @Test func backendErrorsSurfaceAsTypedPracticeCodes() async {
        let session = session(PracticeErrorStub.self)
        defer { session.invalidateAndCancel() }
        let service = PracticeService(baseURL: baseURL, client: APIClient(session: session))
        await #expect(throws: PracticeServiceError.backend(.noQuestionsAvailable)) {
            try await service.fetchNextQuestion(sessionID: "prac_done")
        }
        await #expect(throws: PracticeServiceError.backend(.sessionNotFound)) {
            try await service.fetchSession(id: "prac_missing")
        }
    }

    @Test func errorCodesMirrorLiveCatalog() {
        #expect(ServiceErrorCode(rawValue: "NO_QUESTIONS_AVAILABLE") == .noQuestionsAvailable)
        #expect(ServiceErrorCode(rawValue: "QUESTION_NOT_IN_SESSION") == .questionNotInSession)
        #expect(ServiceErrorCode(rawValue: "SESSION_COMPLETED") == .sessionCompleted)
        #expect(ServiceErrorCode(rawValue: "SESSION_NOT_FOUND") == .sessionNotFound)
        #expect(ServiceErrorCode(rawValue: "IDEMPOTENCY_CONFLICT") == .idempotencyConflict)
        #expect(ServiceErrorCode(rawValue: "FUTURE_CODE") == .unknown("FUTURE_CODE"))
    }
}

// MARK: - Transport stubs

private class PracticeStubBase: URLProtocol, @unchecked Sendable {
    struct Snapshot: Equatable {
        let method: String?
        let path: String?
        let idempotencyKey: String?
        let clientRequestId: String?
    }

    private static let lock = NSLock()
    private static var recorded: [String: [Snapshot]] = [:]

    private static func key(_ type: Any.Type) -> String { String(describing: type) }

    static func reset(_ type: AnyClass) {
        lock.lock()
        recorded[key(type)] = []
        lock.unlock()
    }

    static func requests(_ type: AnyClass) -> [Snapshot] {
        lock.lock()
        defer { lock.unlock() }
        return recorded[key(type)] ?? []
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() {}

    @discardableResult
    func record() -> Int {
        let body = request.httpBody ?? Self.readBodyStream(request.httpBodyStream)
        let payload = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any]
        let snapshot = Snapshot(method: request.httpMethod, path: request.url?.path,
                                idempotencyKey: request.value(forHTTPHeaderField: "Idempotency-Key"),
                                clientRequestId: payload?["client_request_id"] as? String)
        let storeKey = Self.key(type(of: self))
        Self.lock.lock()
        var items = Self.recorded[storeKey] ?? []
        items.append(snapshot)
        Self.recorded[storeKey] = items
        let count = items.count
        Self.lock.unlock()
        return count
    }

    func respond(status: Int = 200, body: Data) {
        let response = HTTPURLResponse(url: request.url!, statusCode: status,
                                       httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }

    static func fixture(_ name: String) -> Data {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/\(name).json")
        return (try? Data(contentsOf: url)) ?? Data()
    }

    private static func readBodyStream(_ stream: InputStream?) -> Data {
        guard let stream else { return Data() }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            guard count > 0 else { break }
            data.append(contentsOf: buffer.prefix(count))
        }
        return data
    }
}

private final class PracticeFixtureStub: PracticeStubBase, @unchecked Sendable {
    override func startLoading() {
        record()
        respond(body: Self.fixture("PracticeSessionTag"))
    }
}

private final class PracticeConflictThenSuccessStub: PracticeStubBase, @unchecked Sendable {
    override func startLoading() {
        let attempt = record()
        if attempt == 1 {
            let envelope = """
            {"error_code":"IDEMPOTENCY_CONFLICT","message":"同一个请求正在处理中，请稍后重试",
             "request_id":"req_conflict"}
            """
            respond(status: 409, body: Data(envelope.utf8))
        } else {
            respond(body: Self.fixture("PracticeAnswer"))
        }
    }
}

private final class PracticeErrorStub: PracticeStubBase, @unchecked Sendable {
    override func startLoading() {
        record()
        if request.url?.path.hasSuffix("/next") == true {
            let envelope = """
            {"error_code":"NO_QUESTIONS_AVAILABLE","message":"这一组题已经做完了",
             "request_id":"req_done"}
            """
            respond(status: 404, body: Data(envelope.utf8))
        } else {
            let envelope = """
            {"error_code":"SESSION_NOT_FOUND","message":"练习 Session 不存在",
             "request_id":"req_missing"}
            """
            respond(status: 404, body: Data(envelope.utf8))
        }
    }
}
