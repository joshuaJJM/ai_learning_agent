import Foundation
import Testing
import UIKit
@testable import HaoXue

@MainActor
struct AnalysisResultTests {
    private func fixtureData() throws -> Data {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/AnalysisCompleted.json")
        return try Data(contentsOf: url)
    }

    private func completedResponse() throws -> AnalysisResponse {
        try AnalysisResponse.decodeBackend(fixtureData())
    }

    @Test func completedPollPreservesAuthoritativeResult() throws {
        let poll = try completedResponse()
        let result = try #require(poll.result)

        #expect(result.status == .completed)
        #expect(result.progress?.stages.count == 5)
        #expect(result.progress?.stages[0].labelZH == "已接收图片")
        #expect(result.correctCount == 1 && result.wrongCount == 1)
        #expect(result.partialCount == 1 && result.unknownCount == 1)
        #expect(result.questions.map(\.number) == ["17", "18", "19", "20"])
        #expect(result.questions[0].studentAnswer == "A")
        #expect(result.questions[0].correctAnswer == "C")
        #expect(result.questions[0].diagnosis == "导数符号与单调性对应关系弄反了。")
        #expect(result.knowledgeChanges[0].beforeMastery == 0.618)
        #expect(result.knowledgeChanges[0].afterMastery == 0.5744)
        #expect(result.knowledgeChanges[0].delta == -0.0436)
        #expect(result.knowledgeChanges[0].evidenceCount == 8)
        #expect(result.newWrongQuestions.map(\.questionNumber) == ["17"])
        #expect(result.nextAction?.knowledgePointID == "kp_monotonicity")
        #expect(HomeActionRoute(try #require(result.nextAction)) == .tutor("kp_monotonicity"))
        #expect(result.warnings == ["技术诊断，默认不展示"])
    }

    @Test func presentationKeepsWrongPartialAndUnknownDistinct() throws {
        let result = try #require(completedResponse().result)
        let model = AnalysisResultPresentation(result: result)

        #expect(model.totalCount == 4)
        #expect(model.attentionQuestions.map(\.number) == ["17", "18", "19"])
        #expect(model.correctQuestions.map(\.number) == ["20"])
        #expect(model.label(for: result.questions[0]) == "需要关注")
        #expect(model.label(for: result.questions[1]) == "部分正确")
        #expect(model.label(for: result.questions[2]) == "需要确认")
        #expect(model.label(for: result.questions[3]) == "回答正确")
        #expect(model.changeLabel(result.knowledgeChanges[0]) == "-4.4 个百分点")
        #expect(model.changeLabel(result.knowledgeChanges[1]) == "+7.4 个百分点")
    }

    @Test func allCorrectAndMissingOptionalSectionsStayEmpty() throws {
        var json = try #require(JSONSerialization.jsonObject(with: fixtureData()) as? [String: Any])
        let questions = try #require(json["question_results"] as? [[String: Any]])
        json["question_results"] = [questions[3]]
        json["questions"] = ["opaque_correct"]
        json["correct_count"] = 1
        json["wrong_count"] = 0
        json["partial_count"] = 0
        json["unknown_count"] = 0
        json["knowledge_changes"] = []
        json["new_wrong_questions"] = []
        json["next_action"] = NSNull()
        let data = try JSONSerialization.data(withJSONObject: json)
        let poll = try AnalysisResponse.decodeBackend(data)
        let result = try #require(poll.result)
        let model = AnalysisResultPresentation(result: result)

        #expect(model.attentionQuestions.isEmpty)
        #expect(model.correctQuestions.count == 1)
        #expect(result.knowledgeChanges.isEmpty)
        #expect(result.newWrongQuestions.isEmpty)
        #expect(result.nextAction == nil)
    }

    @Test func longQuestionAndDiagnosisArePreserved() throws {
        var json = try #require(JSONSerialization.jsonObject(with: fixtureData()) as? [String: Any])
        var questions = try #require(json["question_results"] as? [[String: Any]])
        let longText = String(repeating: "函数的单调性需要逐段判断。", count: 30)
        questions[0]["question_content"] = longText
        questions[0]["diagnosis"] = longText
        json["question_results"] = questions
        let data = try JSONSerialization.data(withJSONObject: json)
        let result = try #require(AnalysisResponse.decodeBackend(data).result)
        #expect(result.questions[0].content == longText)
        #expect(result.questions[0].diagnosis == longText)
    }

    @Test func completedScanPublishesResultOnceAndStopsPolling() async throws {
        let service = ScriptedAnalysisService([try completedResponse()])
        let model = ScanViewModel(liveService: service)
        model.append([sampleImage()], source: .photos)
        model.start()
        try await waitUntil { model.state == .completed }

        #expect(model.completedResult?.questions.count == 4)
        #expect(service.getCount == 1)
        model.resume()
        try await Task.sleep(for: .milliseconds(100))
        #expect(service.getCount == 1)
    }

    @Test func failedScanNeverPublishesCompletedResult() async throws {
        let failed = try AnalysisResponse.decodeBackend(Data("""
        {"analysis_id":"ana_failed","status":"failed","error":{"error_code":"VLM_TIMEOUT"}}
        """.utf8))
        let service = ScriptedAnalysisService([failed])
        let model = ScanViewModel(liveService: service)
        model.append([sampleImage()], source: .photos)
        model.start()
        try await waitUntil { model.state == .failed }

        #expect(model.completedResult == nil)
        #expect(model.errorCode == "VLM_TIMEOUT")
        #expect(service.getCount == 1)
    }

    @Test func completedPayloadFailureHasReadableRetryMessage() {
        #expect(ScanFailurePresentation(code: "RESULT_UNAVAILABLE").message ==
                "分析结果暂时无法显示，请重试。")
    }

    @Test func decodeFailureRetriesSameCompletedAnalysis() async throws {
        let service = ScriptedAnalysisService([
            .failure(NetworkError.decoding), .success(try completedResponse())
        ])
        let model = ScanViewModel(liveService: service)
        model.append([sampleImage()], source: .photos)
        model.start()
        try await waitUntil { model.state == .failed }
        #expect(model.errorCode == "RESULT_UNAVAILABLE")
        #expect(model.completedResult == nil)

        model.retry()
        try await waitUntil { model.state == .completed }
        #expect(model.completedResult?.id == "ana_fixture")
        #expect(service.createCount == 1)
        #expect(service.getCount == 2)
    }

    private func mixedFixture() throws -> HomeworkAnalysisResult {
        let data = Data("""
        {"analysis_id":"ana_mixed","status":"completed","progress":{"percent":1,"current_stage":"Completed","stages":[]},
         "user_id":"demo","subject":"mathematics","image_count":1,
         "questions":["q_unknown","q_unanswered"],
         "question_results":[
           {"question_id":"q_unknown","question_number":"17","question_type":"single_choice",
            "question_content":"题干一","choices":{"A":"甲","B":"乙","C":"丙","D":"丁"},
            "student_answer":"D","correct_answer":null,"correctness":"unknown",
            "possible_answer":"D","possible_answer_source":"deepseek-flash",
            "knowledge_points":[],"diagnosis":"","confidence":0.4,"difficulty":0.5},
           {"question_id":"q_unanswered","question_number":"18","question_type":"single_choice",
            "question_content":"题干二","choices":{"A":"甲","B":"乙"},
            "student_answer":null,"correct_answer":"B","correctness":"unanswered",
            "possible_answer":null,"possible_answer_source":null,
            "knowledge_points":[],"diagnosis":"","confidence":0.9,"difficulty":0.5}],
         "correct_count":0,"wrong_count":0,"partial_count":0,"unanswered_count":1,"unknown_count":1,
         "knowledge_changes":[],"new_wrong_questions":[],"warnings":[],"generated_by":"vlm",
         "created_at":"2026-10-03T06:48:30Z","updated_at":"2026-10-03T06:49:00Z"}
        """.utf8)
        return try #require(AnalysisResponse.decodeBackend(data).result)
    }

    @Test func unansweredAndUnknownStayDistinctAndNeitherCountsTowardMastery() throws {
        let result = try mixedFixture()
        let model = AnalysisResultPresentation(result: result)

        #expect(result.unansweredCount == 1 && result.unknownCount == 1)
        #expect(model.totalCount == 2)
        #expect(result.questions[0].correctness == .unknown)
        #expect(result.questions[1].correctness == .unanswered)
        #expect(result.questions[0].correctness.countsTowardMastery == false)
        #expect(result.questions[1].correctness.countsTowardMastery == false)
        #expect(model.label(for: result.questions[0]) == "需要确认")
        #expect(model.label(for: result.questions[1]) == "未作答")
        // Only the unknown question is eligible for manual answer confirmation.
        #expect(model.confirmableQuestions.map(\.id) == ["q_unknown"])
    }

    @Test func possibleAnswerIsOnlyAHintAndNeverBecomesTheCorrectAnswer() throws {
        let result = try mixedFixture()
        let model = AnalysisResultPresentation(result: result)
        let unknown = result.questions[0]

        #expect(unknown.possibleAnswer == "D")
        #expect(unknown.possibleAnswerSource == "deepseek-flash")
        // The unverified question still has no authoritative answer.
        #expect(unknown.correctAnswer == nil)
        #expect(model.unverifiedHint(for: unknown) == "AI 无法确认本题答案（可能是 D），未计入统计")
        #expect(model.studentAnswerLabel(for: unknown) == "D")
        #expect(model.studentAnswerLabel(for: result.questions[1]) == "未作答")
    }

    @Test func retryingStageIsNotAFailure() throws {
        let data = Data("""
        {"analysis_id":"ana_retry","status":"processing","progress":{"percent":0.25,
         "current_stage":"Image received","current_stage_key":"image_received",
         "current_stage_label_zh":"已接收图片","retrying":true,
         "retry_note":"第 1 张：deepseek-flash 未成功，正在用 Qwen/Qwen3-VL-32B-Instruct 重试（2/3）",
         "stages":[{"key":"image_received","label_zh":"已接收图片","state":"retrying"},
                   {"key":"questions_detected","label_zh":"已识别题目","state":"pending"}]}}
        """.utf8)
        let response = try AnalysisResponse.decodeBackend(data)

        #expect(response.status == .processing)
        #expect(response.progress?.isRetrying == true)
        #expect(response.progress?.stages[0].state == .retrying)
        // The note is display-ready server text; the client never rebuilds it.
        #expect(response.progress?.retryNote?.contains("正在用 Qwen/Qwen3-VL-32B-Instruct 重试") == true)
    }

    @Test func unknownStatusAndStageDoNotBreakDecoding() throws {
        let data = Data("""
        {"analysis_id":"ana_future","status":"paused",
         "progress":{"percent":0.1,"current_stage":"x","stages":[
           {"key":"image_received","label_zh":"已接收图片","state":"sleeping"}]}}
        """.utf8)
        let response = try AnalysisResponse.decodeBackend(data)

        #expect(response.status == .unknown("paused"))
        #expect(response.progress?.stages[0].state == .unknown("sleeping"))
    }

    private func sampleImage() -> UIImage {
        UIGraphicsImageRenderer(size: CGSize(width: 100, height: 100)).image { context in
            UIColor.white.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 100, height: 100))
        }
    }

    private func waitUntil(_ condition: () -> Bool) async throws {
        for _ in 0..<100 {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(20))
        }
        Issue.record("扫描状态没有在预期时间内完成")
    }
}

@MainActor
private final class ScriptedAnalysisService: AnalysisServing {
    private var polls: [Result<AnalysisResponse, Error>]
    private(set) var createCount = 0
    private(set) var getCount = 0

    init(_ polls: [AnalysisResponse]) { self.polls = polls.map { .success($0) } }
    init(_ polls: [Result<AnalysisResponse, Error>]) { self.polls = polls }

    func create(images: [Data], key: UUID) async throws -> CreateAnalysisResponse {
        createCount += 1
        return CreateAnalysisResponse(analysisID: "ana_fixture", status: .queued)
    }

    func get(id: String) async throws -> AnalysisResponse {
        getCount += 1
        return try polls.removeFirst().get()
    }
}
