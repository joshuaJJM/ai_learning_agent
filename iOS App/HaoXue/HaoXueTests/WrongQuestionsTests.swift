import Foundation
import Testing
@testable import HaoXue

@MainActor
struct WrongQuestionsTests {
    private func fixture(_ name: String) throws -> Data {
        let directory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        return try Data(contentsOf: directory.appendingPathComponent("Fixtures/\(name).json"))
    }

    @Test func backendListAndDetailPreserveLearningEvidence() throws {
        let list = try BackendJSON.decoder.decode(WrongQuestionListDTO.self, from: fixture("WrongQuestions"))
        let items = list.items.map(Phase5Mapper().summary)
        #expect(items.count == list.total)
        #expect(items.first?.errorLabel == "函数性质转换错误")
        #expect(items.first?.status == "open")
        #expect(items.first?.createdAt.timeIntervalSince1970 ?? 0 > 0)
        let dto = try BackendJSON.decoder.decode(WrongQuestionDetailDTO.self, from: fixture("WrongQuestionDetail"))
        let detail = Phase5Mapper().wrongQuestion(dto)
        #expect(detail.summary.content == dto.questionContent)
        #expect(detail.studentAnswer == dto.studentAnswer)
        #expect(detail.correctAnswer == dto.correctAnswer)
        #expect(detail.diagnosis == dto.diagnosis)
        #expect(detail.summary.knowledgePointName == dto.knowledgePointName)
        #expect(detail.choices == dto.choices)
        #expect(detail.sourceType == dto.sourceType)
    }

    @Test func listLoadsEmptyAndRetriesTypedError() async {
        let provider = ScriptedWrongProvider()
        provider.listResults = [.failure(NetworkError.backend(code: "SERVICE_UNAVAILABLE", message: "internal", requestID: nil, status: 503)), .success([])]
        let model = WrongQuestionsListViewModel(provider: provider)
        await model.loadIfNeeded()
        #expect(model.phase == .failed)
        #expect(model.errorMessage != "internal")
        await model.refresh()
        #expect(model.phase == .loaded)
        #expect(model.items.isEmpty)
        #expect(provider.listCalls == 2)
    }

    @Test func multipleLongItemsAndOptionalDetailRemainBackendOwned() throws {
        var list = try #require(JSONSerialization.jsonObject(with: fixture("WrongQuestions")) as? [String: Any])
        let first = try #require((list["items"] as? [[String: Any]])?.first)
        var second = first
        second["wrong_question_id"] = "wq_second"
        second["question_content"] = String(repeating: "题干很长。", count: 80)
        second["knowledge_point_name"] = String(repeating: "综合知识点", count: 12)
        second["status"] = "archived"
        list["items"] = [first, second]
        list["total"] = 2
        let decoded = try BackendJSON.decoder.decode(WrongQuestionListDTO.self,
            from: JSONSerialization.data(withJSONObject: list))
        let mapped = decoded.items.map(Phase5Mapper().summary)
        #expect(mapped.count == 2)
        #expect(mapped[1].content.count > 300)
        #expect(mapped[1].status == "archived")
        #expect(WrongQuestionStatus.label(mapped[1].status) == "已归档")

        var rawDetail = try #require(JSONSerialization.jsonObject(with: fixture("WrongQuestionDetail")) as? [String: Any])
        rawDetail["student_answer"] = NSNull()
        rawDetail["correct_answer"] = NSNull()
        rawDetail["diagnosis"] = String(repeating: "诊断内容。", count: 100)
        rawDetail["choices"] = ["甲": "第一项", "乙": "第二项", "丙": "第三项", "丁": "第四项", "戊": "第五项"]
        let detail = Phase5Mapper().wrongQuestion(try BackendJSON.decoder.decode(
            WrongQuestionDetailDTO.self, from: JSONSerialization.data(withJSONObject: rawDetail)))
        #expect(detail.studentAnswer == nil)
        #expect(detail.correctAnswer == nil)
        #expect(detail.diagnosis.count > 300)
        #expect(detail.choices.count == 5)
    }

    @Test func detailLoadsAndStatusRefreshesFromBackend() async throws {
        let dto = try BackendJSON.decoder.decode(WrongQuestionDetailDTO.self, from: fixture("WrongQuestionDetail"))
        let provider = ScriptedWrongProvider()
        provider.detail = Phase5Mapper().wrongQuestion(dto)
        let model = WrongQuestionDetailViewModel(id: dto.wrongQuestionId, provider: provider)
        await model.loadIfNeeded()
        #expect(model.phase == .loaded)
        #expect(model.detail?.studentAnswer == "A")
        await model.updateStatus("resolved")
        #expect(provider.updatedStatus == "resolved")
        #expect(provider.detailCalls == 2)
    }

    @Test func detailErrorRetriesWithoutMockFallback() async throws {
        let dto = try BackendJSON.decoder.decode(WrongQuestionDetailDTO.self, from: fixture("WrongQuestionDetail"))
        let provider = ScriptedWrongProvider()
        provider.detail = Phase5Mapper().wrongQuestion(dto)
        provider.detailFailures = 1
        let model = WrongQuestionDetailViewModel(id: dto.wrongQuestionId, provider: provider)
        await model.loadIfNeeded()
        #expect(model.phase == .failed)
        #expect(model.detail == nil)
        await model.refresh()
        #expect(model.phase == .loaded)
        #expect(model.detail?.diagnosis == dto.diagnosis)
        #expect(provider.detailCalls == 2)
    }

    @Test func tutorRequestUsesWrongQuestionSource() throws {
        let service = TutorRemoteService(baseURL: URL(string: "http://fixture.invalid")!, wrongQuestionID: "wq_1")
        let data = try #require(service.makeCreateRequest(key: "key").httpBody)
        let body = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        #expect(body["source_type"] as? String == "wrong_question")
        #expect(body["wrong_question_id"] as? String == "wq_1")
        #expect(body["knowledge_point_id"] == nil)
    }

    @Test func typedBackendErrorsHaveReadableMessages() {
        for code in ["WRONG_QUESTION_NOT_FOUND", "UNAUTHORIZED", "SERVICE_UNAVAILABLE", "INTERNAL_ERROR"] {
            let error = NetworkError.backend(code: code, message: "raw server text", requestID: nil, status: 500)
            let message = WrongQuestionError.message(for: error)
            #expect(!message.isEmpty)
            #expect(message != "raw server text")
        }
    }
}

@MainActor
private final class ScriptedWrongProvider: WrongQuestionDataProviding {
    var listResults: [Result<[WrongQuestionSummary], Error>] = []
    var detail: WrongQuestionDetail?
    var detailFailures = 0
    var updatedStatus: String?
    var listCalls = 0
    var detailCalls = 0
    func fetchWrongQuestions() async throws -> [WrongQuestionSummary] {
        listCalls += 1
        return try listResults.removeFirst().get()
    }
    func fetchWrongQuestion(id: String) async throws -> WrongQuestionDetail {
        detailCalls += 1
        if detailFailures > 0 {
            detailFailures -= 1
            throw NetworkError.backend(code: "WRONG_QUESTION_NOT_FOUND", message: "internal", requestID: nil, status: 404)
        }
        return try #require(detail)
    }
    func updateWrongQuestion(id: String, status: String) async throws -> WrongQuestionDetail {
        updatedStatus = status
        return try #require(detail)
    }
}
