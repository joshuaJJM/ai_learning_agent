import Foundation
import Testing
@testable import HaoXue

/// Contract tests for the deployed `confirm-answer` endpoint (contract
/// `8A-final`, commit 629f99e) plus the result-screen behaviour around it.
@MainActor
@Suite(.serialized)   // the URLProtocol stub keeps global state
struct AnswerConfirmationContractTests {
    private let baseURL = URL(string: "http://fixture.invalid")!

    private func session() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ConfirmationStubProtocol.self]
        return URLSession(configuration: configuration)
    }

    private func service(_ session: URLSession,
                         retryDelay: Duration = .milliseconds(1)) -> LiveAnswerConfirmationService {
        LiveAnswerConfirmationService(baseURL: baseURL, client: APIClient(session: session),
                                      analysisID: "ana_1", retryDelay: retryDelay)
    }

    private func request(_ service: LiveAnswerConfirmationService,
                         questionID: String = "q_1", answer: String = "C",
                         key: String = "key-1") throws -> URLRequest {
        try service.makeRequest(questionID: questionID, correctAnswer: answer, key: key)
    }

    // MARK: - Request shape

    @Test func requestTargetsTheContractEndpointWithOnlyTheConfirmedAnswer() throws {
        let request = try request(service(session()))

        #expect(request.httpMethod == "POST")
        #expect(request.url?.path == "/api/v1/homework/analyses/ana_1/questions/q_1/confirm-answer")
        #expect(request.value(forHTTPHeaderField: "Content-Type") == "application/json")
        #expect(request.value(forHTTPHeaderField: "Idempotency-Key") == "key-1")

        let body = try #require(request.httpBody)
        let json = try #require(JSONSerialization.jsonObject(with: body) as? [String: Any])
        // The client submits the answer book's answer and nothing else — no
        // correctness, no student answer, no Evidence.
        #expect(json.keys.sorted() == ["client_request_id", "correct_answer"])
        #expect(json["correct_answer"] as? String == "C")
        #expect(json["client_request_id"] as? String == "key-1")
    }

    @Test func retryingTheSameConfirmationReusesOneKeyAndANewAnswerUsesANewOne() throws {
        let service = service(session())
        let store = AnswerConfirmationKeyStore()

        let first = store.key(questionID: "q_1", correctAnswer: "C")
        let retry = store.key(questionID: "q_1", correctAnswer: "C")
        let changed = store.key(questionID: "q_1", correctAnswer: "D")
        let otherQuestion = store.key(questionID: "q_2", correctAnswer: "C")

        #expect(first == retry)
        #expect(first != changed)
        #expect(first != otherQuestion)
        _ = service
    }

    // MARK: - Response decoding

    @Test func replayedConfirmationDecodesWithoutWritingAnythingTwice() throws {
        let dto = try BackendJSON.decoder.decode(ConfirmAnswerResponseDTO.self,
                                                 from: Data(Self.confirmedWrong.utf8))

        #expect(dto.analysisId == "ana_1")
        #expect(dto.questionId == "q_1")
        #expect(dto.studentAnswer == "D")
        #expect(dto.correctAnswer == "C")
        #expect(dto.correctness == "wrong")
        #expect(dto.replayed)
        #expect(dto.confirmation.source == "user")
        #expect(dto.confirmation.originalCorrectAnswer == "C")
        #expect(dto.confirmation.correctionCount == 1)
        #expect(dto.confirmation.confirmedAt != nil)
        #expect(dto.analysisSummary.questionCount == 9)
        #expect(dto.analysisSummary.wrongCount == 1)
        #expect(dto.analysisSummary.unknownCount == 3)
        #expect(dto.wrongQuestion?.wrongQuestionId == "wq_1")
        #expect(dto.nextAction?.action == "start_tutor")
    }

    @Test func correctedToCorrectLeavesNoWrongQuestion() throws {
        let json = Self.confirmedWrong
            .replacingOccurrences(of: "\"correctness\":\"wrong\"", with: "\"correctness\":\"correct\"")
            .replacingOccurrences(of: "\"wrong_question\": { \"wrong_question_id\": \"wq_1\", \"status\": \"open\", \"attempt_count\": 1 }",
                                  with: "\"wrong_question\": null")
        let dto = try BackendJSON.decoder.decode(ConfirmAnswerResponseDTO.self, from: Data(json.utf8))

        #expect(dto.correctness == "correct")
        #expect(dto.wrongQuestion == nil)
    }

    // MARK: - Transport behaviour

    @Test func conflictRetryResendsTheIdenticalRequest() async throws {
        let session = session()
        ConfirmationStubProtocol.reset(responses: [.init(status: 409, body: Self.conflict),
                                                   .init(status: 200, body: Self.confirmedWrong)])
        let service = service(session)

        try await service.confirm(questionID: "q_1", correctAnswer: "C")

        let sent = ConfirmationStubProtocol.sentRequests()
        #expect(sent.count == 2)
        #expect(sent[0].value(forHTTPHeaderField: "Idempotency-Key")
                    == sent[1].value(forHTTPHeaderField: "Idempotency-Key"))
        #expect(Self.body(of: sent[0]) == Self.body(of: sent[1]))
        #expect(Self.body(of: sent[0])?.isEmpty == false)
        #expect(service.lastOutcome?.correctness == "wrong")
    }

    @Test func businessErrorIsNotRetried() async throws {
        let session = session()
        ConfirmationStubProtocol.reset(responses: [
            .init(status: 409, body: Self.alreadyResolved),
            .init(status: 200, body: Self.confirmedWrong)
        ])

        await #expect(throws: NetworkError.self) {
            try await service(session).confirm(questionID: "q_1", correctAnswer: "C")
        }
        #expect(ConfirmationStubProtocol.sentRequests().count == 1)
    }

    // MARK: - Result screen behaviour

    @Test func onlyUnknownQuestionsOfferManualConfirmation() throws {
        let result = try Self.mixedResult()
        let model = AnalysisResultModel(result: result, confirmer: ScriptedConfirmer(),
                                        reload: { _ in result })
        let unknown = try #require(result.questions.first { $0.correctness == .unknown })
        let unanswered = try #require(result.questions.first { $0.correctness == .unanswered })
        let wrong = try #require(result.questions.first { $0.correctness == .wrong })

        #expect(model.canConfirmAnswers)
        #expect(model.confirmation(for: unknown) != nil)
        #expect(model.confirmation(for: unanswered) == nil)
        #expect(model.confirmation(for: wrong) == nil)
    }

    @Test func withoutALiveBackendThereIsNoConfirmationUI() throws {
        let result = try Self.mixedResult()
        let model = AnalysisResultModel(result: result)

        #expect(model.canConfirmAnswers == false)
        #expect(model.confirmation(for: result.questions[0]) == nil)
    }

    @Test func confirmingReloadsTheAuthoritativeResultAndDropsTheSection() async throws {
        let before = try Self.mixedResult()
        let after = try Self.mixedResult(unknownBecameCorrect: true)
        let model = AnalysisResultModel(result: before, confirmer: ScriptedConfirmer(),
                                        reload: { _ in after })
        let unknown = try #require(before.questions.first { $0.correctness == .unknown })
        let confirmation = try #require(model.confirmation(for: unknown))

        confirmation.select("C")
        #expect(await confirmation.confirm())
        await model.refreshAfterConfirmation()

        #expect(model.result.unknownCount == 0)
        #expect(model.result.correctCount == 1)
        // The reloaded verdict is the server's: no section for that question.
        #expect(model.confirmation(for: try #require(model.result.questions.first)) == nil)
        #expect(model.reloadError == nil)
    }

    @Test func reloadFailureKeepsTheServerStateAndSurfacesARetryableMessage() async throws {
        let before = try Self.mixedResult()
        let model = AnalysisResultModel(result: before, confirmer: ScriptedConfirmer(),
                                        reload: { _ in throw NetworkError.timeout })

        await model.refreshAfterConfirmation()

        #expect(model.result.unknownCount == 1)
        #expect(model.reloadError == "连接暂时中断，稍后会自动重试。")
        #expect(model.isReloading == false)
    }

    // MARK: - Fixtures

    /// URLProtocol exposes an uploaded body as a stream, not `httpBody`.
    private static func body(of request: URLRequest) -> Data? {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 1024)
        while stream.hasBytesAvailable {
            let read = stream.read(&buffer, maxLength: buffer.count)
            guard read > 0 else { break }
            data.append(buffer, count: read)
        }
        return data
    }

    private static let confirmedWrong = """
    {"analysis_id":"ana_1","question_id":"q_1","student_answer":"D","correct_answer":"C",
     "correctness":"wrong",
     "confirmation":{"source":"user","confirmed_at":"2026-10-03T13:20:00+00:00",
                     "original_correct_answer":"C","correction_count":1},
     "analysis_summary":{"question_count":9,"correct_count":5,"wrong_count":1,
                         "partial_count":0,"unanswered_count":0,"unknown_count":3},
     "wrong_question": { "wrong_question_id": "wq_1", "status": "open", "attempt_count": 1 },
     "next_action":{"action":"start_tutor","title":"下一步","reason":"原因","cta_label":"开始学习"},
     "replayed":true}
    """

    private static let conflict = """
    {"error_code":"IDEMPOTENCY_CONFLICT","message":"同一个幂等键的请求正在处理中",
     "request_id":"req_1","details":{}}
    """

    private static let alreadyResolved = """
    {"error_code":"QUESTION_ALREADY_RESOLVED","message":"这道题已经确认过了",
     "request_id":"req_2","details":{}}
    """

    /// Two questions: one the AI could not verify, one the student never
    /// answered. `unknownBecameCorrect` simulates the reloaded result after a
    /// successful confirmation.
    private static func mixedResult(unknownBecameCorrect: Bool = false) throws -> HomeworkAnalysisResult {
        let correctness = unknownBecameCorrect ? "correct" : "unknown"
        let correctAnswer = unknownBecameCorrect ? "\"C\"" : "null"
        let counts = unknownBecameCorrect
            ? "\"correct_count\":1,\"wrong_count\":1,\"partial_count\":0,\"unanswered_count\":1,\"unknown_count\":0"
            : "\"correct_count\":0,\"wrong_count\":2,\"partial_count\":0,\"unanswered_count\":1,\"unknown_count\":1"
        let json = """
        {"analysis_id":"ana_1","status":"completed",
         "progress":{"percent":1,"current_stage":"Completed","stages":[]},
         "user_id":"demo","subject":"mathematics","image_count":1,
         "questions":["q_1","q_2","q_3"],
         "question_results":[
           {"question_id":"q_1","question_number":"17","question_type":"single_choice",
            "question_content":"题干一","choices":{"A":"甲","B":"乙","C":"丙","D":"丁"},
            "student_answer":"D","correct_answer":\(correctAnswer),"correctness":"\(correctness)",
            "possible_answer":"D","possible_answer_source":"deepseek-flash",
            "knowledge_points":[],"diagnosis":"","confidence":0.4,"difficulty":0.5},
           {"question_id":"q_2","question_number":"18","question_type":"single_choice",
            "question_content":"题干二","choices":{"A":"甲","B":"乙"},
            "student_answer":null,"correct_answer":"B","correctness":"unanswered",
            "knowledge_points":[],"diagnosis":"","confidence":0.9,"difficulty":0.5},
           {"question_id":"q_3","question_number":"19","question_type":"single_choice",
            "question_content":"题干三","choices":{"A":"甲","B":"乙"},
            "student_answer":"A","correct_answer":"B","correctness":"wrong",
            "knowledge_points":[],"diagnosis":"","confidence":0.9,"difficulty":0.5}],
         \(counts),"knowledge_changes":[],"new_wrong_questions":[],"warnings":[],
         "created_at":"2026-10-03T06:48:30Z","updated_at":"2026-10-03T06:49:00Z"}
        """
        return try #require(AnalysisResponse.decodeBackend(Data(json.utf8)).result)
    }
}

@MainActor
private final class ScriptedConfirmer: AnswerConfirming {
    private(set) var calls: [(questionID: String, correctAnswer: String)] = []
    func confirm(questionID: String, correctAnswer: String) async throws {
        calls.append((questionID, correctAnswer))
    }
}

private final class ConfirmationStubProtocol: URLProtocol, @unchecked Sendable {
    struct Stub: Sendable { let status: Int; let body: String }

    private static let lock = NSLock()
    nonisolated(unsafe) private static var responses: [Stub] = []
    nonisolated(unsafe) private static var sent: [URLRequest] = []

    static func reset(responses: [Stub]) {
        lock.lock(); defer { lock.unlock() }
        self.responses = responses
        sent = []
    }

    static func sentRequests() -> [URLRequest] {
        lock.lock(); defer { lock.unlock() }
        return sent
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lock.lock()
        Self.sent.append(request)
        let stub = Self.responses.isEmpty ? nil : Self.responses.removeFirst()
        Self.lock.unlock()

        let status = stub?.status ?? 500
        let response = HTTPURLResponse(url: request.url!, statusCode: status,
                                       httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data((stub?.body ?? "{}").utf8))
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
