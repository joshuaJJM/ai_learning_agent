import Foundation
import PencilKit
import Testing
@testable import HaoXue

// The transport stub keeps shared static state, so these tests must not interleave.
@Suite(.serialized)
struct TutorBackendTests {
    @Test func parserHandlesFragmentedChineseAndMultipleEvents() throws {
        var parser = TutorSSEParser()
        let payload = Data("event: meta\r\ndata: {\"seq\":2}\r\n\r\nevent: delta\ndata: {\"content\":\"还是不对\"}\n\nevent: turn\ndata: {\"turn_id\":\"turn_2\"}\n\nevent: done\ndata: {\"seq\":2}\n\nevent: error\ndata: {\"error_code\":\"INTERNAL_ERROR\"}\n\n".utf8)
        var events: [TutorSSEFrame] = []
        for byte in payload {
            events += try parser.append(Data([byte]))
        }
        #expect(events.map(\.event) == ["meta", "delta", "turn", "done", "error"])
        #expect(String(data: events[1].data, encoding: .utf8) == "{\"content\":\"还是不对\"}")
    }

    @Test @MainActor func backendErrorUsesMachineCode() throws {
        let json = Data("{\"error_code\":\"SESSION_NOT_FOUND\",\"message\":\"会话不存在\",\"request_id\":\"req_1\"}".utf8)
        let error = try TutorJSON.decoder.decode(TutorBackendErrorDTO.self, from: json)
        #expect(ServiceErrorCode(rawValue: error.errorCode) == .sessionNotFound)
        #expect(error.requestId == "req_1")
    }

    @Test @MainActor func turnDecodesStructuredRemedialWithoutAnswerLeak() throws {
        let json = """
        {"turn_id":"turn_2","seq":2,"turn_type":"simpler_question","text":"换个角度",
         "choices":[{"key":"A","text":"增"},{"key":"B","text":"减"}],
         "allow_free_text":false,"phase":"diagnose",
         "progress":{"step":1,"total_steps":5,"percent":0.2},"completed":false,
         "question_id":"opaque.abc123","strategy":"simplify","remedial_depth":1,
         "answer_reveal":null,"created_at":"2026-10-02T12:00:00+00:00"}
        """
        let turn = try TutorJSON.decoder.decode(TutorTurnDTO.self, from: Data(json.utf8))
        #expect(turn.remedialDepth == 1)
        #expect(turn.choices.map(\.key) == ["A", "B"])
        #expect(turn.answerReveal == nil)
        #expect(turn.questionId == "opaque.abc123")
    }

    @Test @MainActor func turnRequestReusesLogicalIdempotencyKey() throws {
        let service = TutorRemoteService(baseURL: URL(string: "http://localhost:17283")!)
        let key = "7D39E712-6E6C-48CE-A904-3104DA94CC12"
        let stream = try service.makeTurnRequest(sessionId: "tut_1", selectedKey: "B", key: key, stream: true)
        let replay = try service.makeTurnRequest(sessionId: "tut_1", selectedKey: "B", key: key, stream: false)
        #expect(stream.value(forHTTPHeaderField: "Idempotency-Key") == key)
        #expect(replay.value(forHTTPHeaderField: "Idempotency-Key") == key)
        #expect(stream.url == replay.url)
        #expect(stream.httpBody != replay.httpBody)
        let payload = try #require(stream.httpBody)
        let object = try #require(JSONSerialization.jsonObject(with: payload) as? [String: Any])
        #expect(object["client_request_id"] as? String == key)
        #expect(object["stream"] as? Bool == true)
    }

    @Test @MainActor func streamCompletionReplaysJSONWithSameIdempotencyKey() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [TutorTransportStub.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        TutorTransportStub.reset()
        let service = TutorRemoteService(baseURL: URL(string: "http://fixture.invalid")!, session: session)
        let key = "tutor-test-request"
        var eventNames: [String] = []

        let response = try await service.submit(sessionId: "tut_1", selectedKey: "B", text: nil, key: key) { event in
            switch event {
            case .meta: eventNames.append("meta")
            case .delta: eventNames.append("delta")
            case .turn: eventNames.append("turn")
            case .done: eventNames.append("done")
            }
        }

        #expect(eventNames == ["meta", "delta", "turn", "done"])
        #expect(response.turn.turnId == "turn_2")
        #expect(response.evaluation?.strategy == "simplify")
        let requests = TutorTransportStub.requests()
        #expect(requests.count == 2)
        #expect(requests.map(\.idempotencyKey) == [key, key])
        #expect(requests.map(\.stream) == [true, false])
        #expect(requests.map(\.clientRequestId) == [key, key])
    }

    @Test @MainActor func restoredTurnIDIsSentForStreamingAndReplay() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [TutorTransportStub.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        TutorTransportStub.reset()
        let service = TutorRemoteService(baseURL: URL(string: "http://fixture.invalid")!, session: session)
        let restored = try await service.fetchSession(id: "tut_1")
        #expect(restored.turn?.turnId == "turn_restored")
        _ = try await service.submit(sessionId: "tut_1", selectedKey: "B", text: nil,
                                     key: "restore-answer") { _ in }
        let requests = TutorTransportStub.requests()
        #expect(requests.map(\.method) == ["GET", "POST", "POST"])
        #expect(requests.dropFirst().map(\.answeringTurnID) == ["turn_restored", "turn_restored"])
    }

    @Test @MainActor func remoteModelKeepsScratchpadDuringRemedialAndResetsForNextFormalTurn() async throws {
        let service = FakeTutorService()
        let model = RemoteTutorViewModel(service: service)
        await model.load()
        let point = PKStrokePoint(location: .init(x: 10, y: 10), timeOffset: 0,
                                  size: .init(width: 3, height: 3), opacity: 1,
                                  force: 1, azimuth: 0, altitude: .pi / 2)
        model.drawing = PKDrawing(strokes: [PKStroke(ink: PKInk(.pen, color: .black),
                                                    path: PKStrokePath(controlPoints: [point], creationDate: .now))])
        model.select("B")
        await model.submit()
        #expect(model.turn?.remedialDepth == 1)
        #expect(model.drawing.strokes.count == 1)
        model.select("A")
        await model.submit()
        #expect(model.pendingNextTurn != nil)
        #expect(model.drawing.strokes.count == 1)
        model.continueToNext()
        #expect(model.turn?.remedialDepth == 0)
        #expect(model.drawing.strokes.isEmpty)
    }

    @Test @MainActor func remoteModelDisplaysFourServerDepthsThenReveals() async throws {
        let model = RemoteTutorViewModel(service: LadderTutorService())
        await model.load()
        for depth in 1...4 {
            model.select("B")
            await model.submit()
            #expect(model.turn?.remedialDepth == depth)
            #expect(model.answerReveal == nil)
        }
        model.select("B")
        await model.submit()
        #expect(model.pendingNextTurn?.turnType == "remedial_exhausted")
        #expect(model.pendingNextTurn?.remedialDepth == 0)
        #expect(model.answerReveal?.origin?.correctKey == "A")
    }

    @Test @MainActor func retryReusesOriginalAnswerKey() async throws {
        let service = FakeTutorService()
        service.failFirst = true
        let model = RemoteTutorViewModel(service: service)
        await model.load()
        model.select("B")
        await model.submit()
        #expect(model.errorMessage != nil)
        model.select("A")
        #expect(model.selectedKey == "B")
        await model.retry()
        #expect(service.seenKeys.count == 1)
        #expect(service.fetchCount == 1)
        #expect(model.turn?.turnId == "turn_1")
        #expect(model.errorMessage == nil)
    }

    @Test @MainActor func restoredSessionUsesBackendCurrentTurnWithoutCreatingAnother() async throws {
        let service = FakeTutorService()
        service.restoredTurnID = "turn_restored"
        let model = RemoteTutorViewModel(service: service, existingSessionID: "tut_1")
        await model.load()
        await model.load()
        #expect(service.createCount == 0)
        #expect(service.fetchCount == 1)
        #expect(model.sessionId == "tut_1")
        #expect(model.turn?.turnId == "turn_restored")
        #expect(model.turn?.choices.map(\.key) == ["A", "B"])
        model.select("A")
        await model.submit()
        #expect(service.seenKeys.count == 1)
    }

    @Test @MainActor func refreshReplacesStaleTurnAndClearsAnswerSelection() async throws {
        let service = FakeTutorService()
        let model = RemoteTutorViewModel(service: service)
        await model.load()
        #expect(service.createCount == 1)
        model.select("B")
        service.restoredTurnID = "turn_advanced"
        await model.refresh()
        #expect(model.turn?.turnId == "turn_advanced")
        #expect(model.selectedKey == nil)
        #expect(service.createCount == 1)
    }

    @Test @MainActor func restoredCompletedSessionShowsSummaryAndCannotAnswer() async throws {
        let service = FakeTutorService()
        service.restoredCompleted = true
        let model = RemoteTutorViewModel(service: service, existingSessionID: "tut_1")
        await model.load()
        #expect(model.completed)
        #expect(model.turn?.turnType == "summary")
        #expect(model.nextAction?.action == "continue_practice")
        model.select("A")
        #expect(!model.canSubmit)
        await model.submit()
        #expect(service.seenKeys.isEmpty)
    }

    @Test @MainActor func streamFailureCanRestoreAdvancedBackendTurn() async throws {
        let service = FakeTutorService()
        service.failFirst = true
        let model = RemoteTutorViewModel(service: service)
        await model.load()
        model.select("B")
        await model.submit()
        #expect(model.errorMessage != nil)
        #expect(model.streamedText == "下一题选 A")
        #expect(model.turn?.turnId == "turn_1")
        service.restoredTurnID = "turn_after_stream"
        await model.retry()
        #expect(model.turn?.turnId == "turn_after_stream")
        #expect(model.errorMessage == nil)
        #expect(service.seenKeys.count == 1)
    }

    @Test @MainActor func rapidDuplicateSubmissionOnlySendsOnce() async throws {
        let service = SlowSubmittingTutorService()
        let model = RemoteTutorViewModel(service: service)
        await model.load()
        model.select("B")
        let first = Task { await model.submit() }
        try await Task.sleep(for: .milliseconds(10))
        let second = Task { await model.submit() }
        await first.value
        await second.value
        #expect(service.submitCount == 1)
    }

    @Test @MainActor func finalRemedialRevealPrecedesCompletion() async throws {
        let service = LadderTutorService()
        service.completeOnExhaustion = true
        let model = RemoteTutorViewModel(service: service)
        await model.load()
        for _ in 0..<5 {
            model.select("B")
            await model.submit()
        }
        #expect(!model.completed)
        #expect(model.answerReveal?.origin?.correctKey == "A")
        model.continueToNext()
        #expect(model.completed)
    }

    @Test @MainActor func cancelledLoadCannotPublishStaleSession() async throws {
        let model = RemoteTutorViewModel(service: SlowTutorService())
        let task = Task { await model.load() }
        try await Task.sleep(for: .milliseconds(20))
        model.cancel()
        await task.value
        #expect(model.sessionId == nil)
        #expect(model.turn == nil)
    }
}

private final class TutorTransportStub: URLProtocol {
    struct RequestSnapshot {
        let method: String?
        let idempotencyKey: String?
        let stream: Bool?
        let clientRequestId: String?
        let answeringTurnID: String?
    }

    private static let lock = NSLock()
    private static var recordedRequests: [RequestSnapshot] = []

    static func reset() {
        lock.lock()
        recordedRequests = []
        lock.unlock()
    }

    static func requests() -> [RequestSnapshot] {
        lock.lock()
        defer { lock.unlock() }
        return recordedRequests
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let body = request.httpBody ?? Self.readBodyStream(request.httpBodyStream)
        let payload = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any]
        let stream = request.value(forHTTPHeaderField: "Accept") == "text/event-stream"
        Self.lock.lock()
        Self.recordedRequests.append(RequestSnapshot(
            method: request.httpMethod,
            idempotencyKey: request.value(forHTTPHeaderField: "Idempotency-Key"),
            stream: payload?["stream"] as? Bool,
            clientRequestId: payload?["client_request_id"] as? String,
            answeringTurnID: payload?["answering_turn_id"] as? String
        ))
        Self.lock.unlock()

        let turn = """
        {"turn_id":"turn_2","seq":2,"turn_type":"simpler_question","text":"换个角度",
         "choices":[{"key":"A","text":"对"},{"key":"B","text":"错"}],"allow_free_text":false,
         "phase":"diagnose","progress":{"step":1,"total_steps":3,"percent":0.333},
         "completed":false,"question_id":"q_2","strategy":"simplify","remedial_depth":1,
         "answer_reveal":null,"created_at":"2026-10-02T12:00:00+00:00"}
        """
        let data: Data
        let contentType: String
        if request.httpMethod == "GET" {
            let json = """
            {"tutor_session_id":"tut_1","knowledge_point_id":"kp_1","knowledge_point_name":"导数",
             "difficulty":0.43,"completed":false,"knowledge_changes":[],
             "turn":{"turn_id":"turn_restored","seq":1,"turn_type":"concept_question","text":"恢复的题目",
                     "choices":[{"key":"A","text":"对"},{"key":"B","text":"错"}],"allow_free_text":false,
                     "phase":"diagnose","progress":{"step":1,"total_steps":3,"percent":0.333},
                     "completed":false,"question_id":null,"strategy":null,"remedial_depth":0,
                     "answer_reveal":null,"created_at":"2026-10-02T12:00:00+00:00"}}
            """
            data = Data(json.utf8)
            contentType = "application/json"
        } else if stream {
            let streamTurn = turn.replacingOccurrences(of: "\n", with: "")
            let events = """
            event: meta
            data: {"request_id":"req_1","tutor_session_id":"tut_1","seq":2,"phase":"diagnose","turn_type":"simpler_question","remedial_depth":1}

            event: delta
            data: {"content":"换个角度"}

            event: turn
            data: \(streamTurn)

            event: done
            data: {"request_id":"req_1","seq":2,"phase":"diagnose","completed":false,"progress":{"step":1,"total_steps":3,"percent":0.333},"student_understanding":0.4}

            """
            data = Data((events + "\n\n").utf8)
            contentType = "text/event-stream"
        } else {
            let json = """
            {"tutor_session_id":"tut_1","evaluation":{"correctness":"wrong","is_correct":false,
             "chosen_key":"B","expected_key":"A","feedback":"继续","explanation":null,
             "strategy":"simplify","remedial_depth":1,"remedial_exhausted":false},
             "turn":\(turn),"phase":"diagnose","completed":false,
             "progress":{"step":1,"total_steps":3,"percent":0.333},"student_understanding":0.4,
             "knowledge_changes":[]}
            """
            data = Data(json.utf8)
            contentType = "application/json"
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Type": contentType])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

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

@MainActor
private final class SlowTutorService: TutorRemoteServing {
    func createSession(key: String) async throws -> TutorSessionDTO {
        try await Task.sleep(for: .milliseconds(80))
        return try await FakeTutorService().createSession(key: key)
    }

    func fetchSession(id: String) async throws -> TutorSessionDTO {
        try await FakeTutorService().fetchSession(id: id)
    }

    func submit(sessionId: String, selectedKey: String?, text: String?, key: String,
                onEvent: @escaping @MainActor (TutorStreamEvent) -> Void) async throws -> TutorTurnResponseDTO {
        throw URLError(.cancelled)
    }
}

@MainActor
private final class SlowSubmittingTutorService: TutorRemoteServing {
    private(set) var submitCount = 0

    func createSession(key: String) async throws -> TutorSessionDTO {
        try await FakeTutorService().createSession(key: key)
    }

    func fetchSession(id: String) async throws -> TutorSessionDTO {
        try await FakeTutorService().fetchSession(id: id)
    }

    func submit(sessionId: String, selectedKey: String?, text: String?, key: String,
                onEvent: @escaping @MainActor (TutorStreamEvent) -> Void) async throws -> TutorTurnResponseDTO {
        submitCount += 1
        try await Task.sleep(for: .milliseconds(80))
        return try await FakeTutorService().submit(sessionId: sessionId, selectedKey: selectedKey,
                                                   text: text, key: key, onEvent: onEvent)
    }
}

@MainActor
private final class LadderTutorService: TutorRemoteServing {
    private var submissions = 0
    var completeOnExhaustion = false

    func createSession(key: String) async throws -> TutorSessionDTO {
        try await FakeTutorService().createSession(key: key)
    }

    func fetchSession(id: String) async throws -> TutorSessionDTO {
        try await FakeTutorService().fetchSession(id: id)
    }

    func submit(sessionId: String, selectedKey: String?, text: String?, key: String,
                onEvent: @escaping @MainActor (TutorStreamEvent) -> Void) async throws -> TutorTurnResponseDTO {
        submissions += 1
        let exhausted = submissions == 5
        let complete = exhausted && completeOnExhaustion
        let depth = exhausted ? 0 : submissions
        let reveal = exhausted ? """
        {"current":{"question_id":"q_5","question_text":"补救题","correct_key":"A","explanation":"解析"},
         "origin":{"question_id":"q_1","question_text":"原题","correct_key":"A","explanation":"原题解析"}}
        """ : "null"
        let json = """
        {"tutor_session_id":"tut_1","evaluation":{"correctness":"wrong","is_correct":false,
         "chosen_key":"B","expected_key":"A","feedback":"继续","explanation":null,
         "strategy":"\(exhausted ? "reveal_answer" : "simplify")","remedial_depth":\(depth),
         "remedial_exhausted":\(exhausted)},
         "turn":{"turn_id":"turn_\(submissions + 1)","seq":\(submissions + 1),
                 "turn_type":"\(exhausted ? "remedial_exhausted" : "simpler_question")","text":"引导",
                 "choices":[{"key":"A","text":"对"},{"key":"B","text":"错"}],
                 "allow_free_text":false,"phase":"diagnose","progress":{"step":1,"total_steps":3,"percent":0.333},
                 "completed":\(complete),"question_id":"q_\(submissions + 1)",
                 "strategy":"\(exhausted ? "reveal_answer" : "simplify")","remedial_depth":\(depth),
                 "answer_reveal":\(reveal),"created_at":"2026-10-02T12:00:00+00:00"},
         "phase":"diagnose","completed":\(complete),"progress":{"step":1,"total_steps":3,"percent":0.333},
         "student_understanding":0.4,"knowledge_changes":[]}
        """
        return try TutorJSON.decoder.decode(TutorTurnResponseDTO.self, from: Data(json.utf8))
    }
}

@MainActor
private final class FakeTutorService: TutorRemoteServing {
    private var answers = 0
    private(set) var createCount = 0
    private(set) var fetchCount = 0
    var failFirst = false
    var restoredTurnID: String?
    var restoredCompleted = false
    var seenKeys: [String] = []

    func createSession(key: String) async throws -> TutorSessionDTO {
        createCount += 1
        return try TutorJSON.decoder.decode(TutorSessionDTO.self, from: Data("""
        {"tutor_session_id":"tut_1","knowledge_point_id":"kp_1","knowledge_point_name":"导数",
         "difficulty":0.43,"completed":false,"knowledge_changes":[],
         "turn":{"turn_id":"turn_1","seq":1,"turn_type":"concept_question","text":"原题",
                 "choices":[{"key":"A","text":"对"},{"key":"B","text":"错"}],
                 "allow_free_text":false,"phase":"diagnose","progress":{"step":1,"total_steps":3,"percent":0.333},
                 "completed":false,"question_id":"q_1","strategy":null,"remedial_depth":0,"answer_reveal":null,
                 "created_at":"2026-10-02T12:00:00+00:00"}}
        """.utf8))
    }

    func fetchSession(id: String) async throws -> TutorSessionDTO {
        fetchCount += 1
        let turnID = restoredTurnID ?? "turn_1"
        let json = """
        {"tutor_session_id":"\(id)","knowledge_point_id":"kp_1","knowledge_point_name":"导数",
         "difficulty":0.43,"completed":\(restoredCompleted),"knowledge_changes":[],
         "next_action":\(restoredCompleted ? "{\"action\":\"continue_practice\",\"title\":\"开始练习\",\"reason\":\"继续巩固\",\"cta_label\":\"开始练习\",\"knowledge_point_id\":\"kp_1\",\"knowledge_point_name\":\"导数\",\"wrong_question_id\":null}" : "null"),
         "turn":{"turn_id":"\(turnID)","seq":2,"turn_type":"\(restoredCompleted ? "summary" : "concept_question")","text":"\(restoredCompleted ? "本轮学习总结" : "恢复后的题目")",
                 "choices":\(restoredCompleted ? "[]" : "[{\"key\":\"A\",\"text\":\"对\"},{\"key\":\"B\",\"text\":\"错\"}]"),
                 "allow_free_text":false,"phase":"\(restoredCompleted ? "completed" : "diagnose")","progress":{"step":2,"total_steps":3,"percent":0.667},
                 "completed":\(restoredCompleted),"question_id":null,"strategy":null,"remedial_depth":0,"answer_reveal":null,
                 "created_at":"2026-10-02T12:00:00+00:00"}}
        """
        return try TutorJSON.decoder.decode(TutorSessionDTO.self, from: Data(json.utf8))
    }

    func submit(sessionId: String, selectedKey: String?, text: String?, key: String,
                onEvent: @escaping @MainActor (TutorStreamEvent) -> Void) async throws -> TutorTurnResponseDTO {
        seenKeys.append(key)
        if failFirst {
            failFirst = false
            onEvent(.delta("下一题选 A"))
            throw URLError(.timedOut)
        }
        answers += 1
        let remedial = answers == 1
        let turn = remedial ? """
          {"turn_id":"turn_2","seq":2,"turn_type":"simpler_question","text":"补救题",
           "choices":[{"key":"A","text":"对"},{"key":"B","text":"错"}],
           "allow_free_text":false,"phase":"diagnose","progress":{"step":1,"total_steps":3,"percent":0.333},
           "completed":false,"question_id":"q_2","strategy":"simplify","remedial_depth":1,"answer_reveal":null,
           "created_at":"2026-10-02T12:00:00+00:00"}
        """ : """
          {"turn_id":"turn_3","seq":3,"turn_type":"guided_practice","text":"下一题",
           "choices":[{"key":"A","text":"对"},{"key":"B","text":"错"}],
           "allow_free_text":false,"phase":"guided_practice","progress":{"step":2,"total_steps":3,"percent":0.667},
           "completed":false,"question_id":"q_3","strategy":"advance","remedial_depth":0,"answer_reveal":null,
           "created_at":"2026-10-02T12:00:00+00:00"}
        """
        let json = """
        {"tutor_session_id":"tut_1","evaluation":{"correctness":"\(remedial ? "wrong" : "correct")",
         "is_correct":\(remedial ? "false" : "true"),"chosen_key":"\(selectedKey ?? "")","expected_key":"A",
         "feedback":"继续","explanation":null,"strategy":"\(remedial ? "simplify" : "advance")",
         "remedial_depth":\(remedial ? "1" : "0"),"remedial_exhausted":false},
         "turn":\(turn),"phase":"diagnose","completed":false,
         "progress":{"step":1,"total_steps":3,"percent":0.333},"student_understanding":0.4,
         "knowledge_changes":[{"knowledge_point_id":"kp_1","name":"导数","before":0.43,"after":0.38,
                               "delta":-0.05,"evidence_count":2}]}
        """
        return try TutorJSON.decoder.decode(TutorTurnResponseDTO.self, from: Data(json.utf8))
    }
}
