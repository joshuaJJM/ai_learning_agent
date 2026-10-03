import Foundation
import Testing
@testable import HaoXue

@MainActor
struct Phase5ContractTests {
    private func fixture(_ name: String) throws -> Data {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/\(name).json")
        return try Data(contentsOf: url)
    }

    @Test func capturedHomeResponseMapsServerActionAndDates() throws {
        let dto = try BackendJSON.decoder.decode(HomeResponseDTO.self, from: fixture("Home"))
        let home = Phase5Mapper().home(dto)
        #expect(!home.greeting.isEmpty)
        #expect(home.nextAction.kind == dto.nextAction.action)
        #expect(home.nextAction.knowledgePointID == dto.nextAction.knowledgePointId)
        #expect(home.wrongQuestionCount == dto.wrongQuestionCount)
        #expect(home.recentWrongQuestions.first?.questionNumber == "17")
        #expect(home.updatedAt.timeIntervalSince1970 > 0)
    }

    @Test func capturedWrongQuestionAndKnowledgeResponsesDecode() throws {
        let wrong = try BackendJSON.decoder.decode(WrongQuestionListDTO.self,
                                                    from: fixture("WrongQuestions"))
        let knowledge = try BackendJSON.decoder.decode(KnowledgeDetailDTO.self,
                                                        from: fixture("KnowledgeDetail"))
        let catalog = try BackendJSON.decoder.decode(KnowledgePointCatalogDTO.self,
                                                     from: fixture("KnowledgePoints"))
        let detail = try BackendJSON.decoder.decode(WrongQuestionDetailDTO.self,
                                                    from: fixture("WrongQuestionDetail"))
        let tree = try BackendJSON.decoder.decode(KnowledgeTreeDTO.self,
                                                  from: fixture("KnowledgeTree"))
        let errors = try BackendJSON.decoder.decode(ErrorCodeCatalogDTO.self,
                                                    from: fixture("ErrorCodes"))
        #expect(wrong.total == wrong.items.count)
        #expect(wrong.items.first?.questionNumber == "17")
        #expect(Phase5Mapper().knowledge(knowledge).evidence.count == knowledge.evidence.count)
        #expect(catalog.count == catalog.items.count)
        #expect(catalog.items.first?.id.hasPrefix("math.") == true)
        #expect(Phase5Mapper().wrongQuestion(detail).summary.questionNumber == "17")
        #expect(tree.totalEvidence >= 0)
        #expect(errors.count == errors.items.count)
    }

    @Test func asynchronousAnalysisPreservesCompletedResult() throws {
        let created = try JSONDecoder().decode(CreateAnalysisResponse.self, from: Data("""
        {"analysis_id":"ana_1","status":"queued","created_at":"2026-10-01T21:30:00.123456Z"}
        """.utf8))
        #expect(created.createdAt != nil)
        let json = """
        {"analysis_id":"ana_1","status":"completed","progress":{"percent":1,
         "current_stage":"Completed","stages":[]},"user_id":"demo","subject":"mathematics",
         "image_count":1,"questions":["opaque.id"],"question_results":[{
           "question_id":"opaque.id","question_number":"036","question_type":"single_choice",
           "question_content":"题干","choices":{"A":"选项一","B":"选项二"},
           "student_answer":"A","correct_answer":"B","correctness":"wrong",
           "knowledge_points":[{"knowledge_point_id":"kp_1","name":"知识点","weight":0.8}],
           "diagnosis":"分析","confidence":0.9,"difficulty":0.5}],
         "correct_count":0,"wrong_count":1,"partial_count":0,"unknown_count":0,
         "knowledge_changes":[{"knowledge_point_id":"kp_1","name":"知识点",
           "before":0.5,"after":0.4,"delta":-0.1,"evidence_count":2}],
         "new_wrong_questions":[],"warnings":["需复核"],"generated_by":"vlm",
         "created_at":"2026-10-01T21:30:00+00:00",
         "updated_at":"2026-10-01T21:31:00.123456Z"}
        """
        let dto = try BackendJSON.decoder.decode(AnalysisResultDTO.self, from: Data(json.utf8))
        let result = Phase5Mapper().analysis(dto)
        #expect(result.status == .completed)
        #expect(result.questionIDs == ["opaque.id"])
        #expect(result.questions.first?.number == "036")
        #expect(result.questions.first?.correctness == .wrong)
        #expect(result.knowledgeChanges.first?.afterMastery == 0.4)
        #expect(result.warnings == ["需复核"])
    }

    @Test func structuredErrorRetainsMachineCodeAndRequestID() throws {
        let json = Data("""
        {"error_code":"VALIDATION_ERROR","message":"参数有误","request_id":"req_7",
         "details":{"field":"answer","retry":false}}
        """.utf8)
        let error = try BackendJSON.decoder.decode(BackendErrorDTO.self, from: json)
        #expect(error.errorCode == "VALIDATION_ERROR")
        #expect(error.requestId == "req_7")
        #expect(error.details != nil)
    }

    @Test func tutorAnswerCarriesAnsweredTurnID() throws {
        let service = TutorRemoteService(baseURL: URL(string: "http://localhost:17283")!)
        let request = try service.makeTurnRequest(sessionId: "tut_1", selectedKey: "B",
            key: "same-logical-write", stream: true, answeringTurnId: "turn_17")
        let data = try #require(request.httpBody)
        let body = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        #expect(body["answering_turn_id"] as? String == "turn_17")
        #expect(request.value(forHTTPHeaderField: "Idempotency-Key") == "same-logical-write")
    }

    @Test func liveHomeUsesAggregationEndpoint() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [HomeFixtureProtocol.self]
        let session = URLSession(configuration: config)
        defer { session.invalidateAndCancel() }
        let provider = LiveDataProvider(client: APIClient(session: session),
            configuration: AppConfiguration(mode: .live,
                                            baseURL: URL(string: "http://fixture.invalid:17283")))
        let home = try await provider.fetchHomeSnapshot()
        #expect(!home.greeting.isEmpty)
        #expect(!home.knowledgeSummary.isEmpty)
    }
}

private final class HomeFixtureProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let isHome = request.url?.path == "/api/v1/home"
        let file = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/Home.json")
        let body = (try? Data(contentsOf: file)) ?? Data()
        let response = HTTPURLResponse(url: request.url!, statusCode: isHome ? 200 : 404,
                                       httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
