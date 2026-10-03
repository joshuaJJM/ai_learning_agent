import Foundation
import Testing
@testable import HaoXue

@MainActor
struct ScanHistoryTests {
    /// The exact shape of `GET /api/v1/homework/batches?limit=50` kept in the
    /// docs: one processing, one success, one failed batch.
    private func batchesData() -> Data {
        Data("""
        {"total":3,"processing_count":1,"success_count":1,"failed_count":1,"limit":50,
         "items":[
          {"batch_number":24,"analysis_id":"ana_processing","state":"processing",
           "state_label":"正在处理","status":"processing","image_count":2,
           "source_name":"数学下册第 32 页","created_at":"2026-10-03T06:48:30.986124Z",
           "finished_at":null,
           "progress":{"percent":0.25,"current_stage":"Image received",
             "current_stage_key":"image_received","current_stage_label_zh":"已接收图片",
             "retrying":true,
             "retry_note":"第 1 张：deepseek-flash 未成功，正在用 Qwen/Qwen3-VL-32B-Instruct 重试（2/3）",
             "stages":[{"key":"image_received","label_zh":"已接收图片","state":"retrying"},
                       {"key":"questions_detected","label_zh":"已识别题目","state":"pending"},
                       {"key":"answers_understood","label_zh":"已理解作答","state":"pending"},
                       {"key":"error_patterns","label_zh":"正在分析错误模式","state":"pending"},
                       {"key":"knowledge_updated","label_zh":"正在更新知识状态","state":"pending"}]},
           "duration_seconds":null,"question_count":null,"correct_count":null,
           "wrong_count":null,"error":null},
          {"batch_number":23,"analysis_id":"ana_success","state":"success","state_label":"成功",
           "status":"completed","image_count":1,"source_name":"数学下册第 31 页",
           "created_at":"2026-10-03T05:48:30.986124Z","finished_at":"2026-10-03T05:48:59.286124Z",
           "progress":null,"duration_seconds":28.3,"question_count":9,"correct_count":5,
           "wrong_count":1,"error":null},
          {"batch_number":22,"analysis_id":"ana_failed","state":"failed","state_label":"失败",
           "status":"failed","image_count":1,"source_name":null,
           "created_at":"2026-10-03T04:48:30.986124Z","finished_at":"2026-10-03T04:48:33.986124Z",
           "progress":null,"duration_seconds":3,"question_count":null,"correct_count":null,
           "wrong_count":null,
           "error":{"error_code":"QUESTION_NOT_RECOGNIZED","message":"没有从图片中识别出题目"}}
         ]}
        """.utf8)
    }

    private func page(_ data: Data) throws -> ScanHistoryPage {
        try ScanHistoryMapper().page(BackendJSON.decoder.decode(BatchListDTO.self, from: data))
    }

    private func completedResult() throws -> HomeworkAnalysisResult {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/AnalysisCompleted.json")
        return try #require(AnalysisResponse.decodeBackend(try Data(contentsOf: url)).result)
    }

    @Test func batchListDecodesServerStatesTimesAndCounters() throws {
        let page = try page(batchesData())

        #expect(page.total == 3 && page.processingCount == 1 && page.successCount == 1)
        #expect(page.hasProcessing)
        #expect(page.batches.map(\.analysisID) == ["ana_processing", "ana_success", "ana_failed"])
        // Newest first, and the number is the server's, not a local counter.
        #expect(page.batches.map(\.title) == ["第 24 次扫描", "第 23 次扫描", "第 22 次扫描"])

        let processing = page.batches[0]
        #expect(processing.isProcessing)
        #expect(processing.progress?.percent == 0.25)
        // `retrying` must survive as "still running", never as a failure.
        #expect(processing.progress?.isRetrying == true)
        #expect(processing.progress?.retryNote?.contains("重试") == true)
        #expect(processing.sourceName == "数学下册第 32 页")
        #expect(processing.finishedAt == nil && processing.durationSeconds == nil)

        let success = page.batches[1]
        #expect(success.state == .success)
        #expect(success.questionCount == 9 && success.correctCount == 5 && success.wrongCount == 1)
        #expect(success.durationSeconds == 28.3)
        #expect(success.createdAt != nil && success.finishedAt != nil)

        let failed = page.batches[2]
        #expect(failed.state == .failed)
        #expect(failed.errorCode == "QUESTION_NOT_RECOGNIZED")
        #expect(failed.errorMessage == "没有从图片中识别出题目")
    }

    @Test func aProcessingBatchKeepsTheListPolling() async throws {
        let service = ScriptedHistoryService(pages: [.success(try page(batchesData()))])
        let model = ScanHistoryViewModel(service: service, pollInterval: .milliseconds(20))

        model.start()
        try await waitUntil { model.state == .loaded }
        #expect(model.hasProcessing)
        try await waitUntil { service.fetchCount >= 2 }
        model.stop()
    }

    @Test func processingBatchPollsUntilItSettles() async throws {
        let processingPage = try page(batchesData())
        // Same batch, now finished: the list must update itself without the user
        // leaving the screen.
        let settled = ScanHistoryPage(
            batches: processingPage.batches.map { batch in
                batch.analysisID == "ana_processing"
                    ? ScanBatch(analysisID: batch.analysisID, batchNumber: batch.batchNumber,
                                state: .success, stateLabel: "成功", sourceName: batch.sourceName,
                                imageCount: batch.imageCount, createdAt: batch.createdAt,
                                finishedAt: Date(), durationSeconds: 21,
                                questionCount: 9, correctCount: 5, wrongCount: 1,
                                progress: nil, errorCode: nil, errorMessage: nil)
                    : batch
            },
            total: processingPage.total, processingCount: 0, successCount: 2, failedCount: 1)

        let service = ScriptedHistoryService(pages: [.success(processingPage), .success(settled)])
        let model = ScanHistoryViewModel(service: service, pollInterval: .milliseconds(20))
        model.start()

        try await waitUntil { !model.hasProcessing && model.state == .loaded }
        let pollsWhenSettled = service.fetchCount
        #expect(model.batches[0].state == .success)
        #expect(model.batches[0].title == "第 24 次扫描")

        // Once nothing is processing the loop stops instead of polling forever.
        try await Task.sleep(for: .milliseconds(120))
        #expect(service.fetchCount == pollsWhenSettled)
    }

    @Test func emptyHistoryFailureBecomesRetryableNotAnInfiniteSpinner() async throws {
        let service = ScriptedHistoryService(pages: [.failure(NetworkError.timeout)])
        let model = ScanHistoryViewModel(service: service)

        model.start()
        try await waitUntil {
            if case .failed = model.state { return true }
            return false
        }
        #expect(model.state == .failed("连接暂时中断，稍后会自动重试。"))
        #expect(model.isEmpty)
    }

    @Test func pollFailureKeepsTheLastGoodList() async throws {
        let good = try page(batchesData())
        let service = ScriptedHistoryService(pages: [.success(good), .failure(NetworkError.timeout)])
        let model = ScanHistoryViewModel(service: service, pollInterval: .milliseconds(20))

        model.start()
        try await waitUntil { model.refreshFailed }
        #expect(model.state == .loaded)
        #expect(model.batches.count == 3)
        model.stop()
    }

    @Test func tappingAFinishedBatchOpensTheSharedAnalysisResult() async throws {
        let result = try completedResult()
        let service = ScriptedHistoryService(pages: [.success(try page(batchesData()))],
                                             results: ["ana_success": result])
        let model = ScanHistoryViewModel(service: service)

        await model.openResult(id: "ana_success")
        #expect(model.openedResult?.id == result.id)
        #expect(model.openError == nil)

        // A batch whose payload is gone surfaces an error instead of a blank screen.
        await model.openResult(id: "ana_failed")
        #expect(model.openError == ScanFailurePresentation(code: "RESULT_UNAVAILABLE").message)
    }

    private func waitUntil(_ condition: () -> Bool) async throws {
        for _ in 0..<200 {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        Issue.record("条件未在预期时间内满足")
    }
}

@MainActor
private final class ScriptedHistoryService: ScanHistoryServing {
    private var pages: [Result<ScanHistoryPage, Error>]
    private let results: [String: HomeworkAnalysisResult]
    private(set) var fetchCount = 0

    init(pages: [Result<ScanHistoryPage, Error>],
         results: [String: HomeworkAnalysisResult] = [:]) {
        self.pages = pages
        self.results = results
    }

    func fetchBatches(limit: Int) async throws -> ScanHistoryPage {
        fetchCount += 1
        guard pages.count > 1 else { return try pages[pages.count - 1].get() }
        return try pages.removeFirst().get()
    }

    func fetchAnalysisResult(id: String) async throws -> HomeworkAnalysisResult {
        guard let result = results[id] else { throw ScanHistoryError.resultUnavailable }
        return result
    }
}
