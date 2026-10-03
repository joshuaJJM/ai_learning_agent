import Foundation

/// The server owns upload history; this boundary only reads it and hands back
/// the same analysis result the scan flow already uses.
@MainActor
protocol ScanHistoryServing {
    func fetchBatches(limit: Int) async throws -> ScanHistoryPage
    func fetchAnalysisResult(id: String) async throws -> HomeworkAnalysisResult
}

enum ScanHistoryError: Error, Equatable {
    /// The batch exists but its result payload is missing (mirrors the scan
    /// flow's `RESULT_UNAVAILABLE`).
    case resultUnavailable
}

@MainActor
struct LiveScanHistoryService: ScanHistoryServing {
    let baseURL: URL
    let client: APIClient
    /// The detail endpoint is shared with the scan flow — one poll path, one
    /// decoder, one result model.
    let analysis: any AnalysisServing
    private let mapper = ScanHistoryMapper()

    func fetchBatches(limit: Int) async throws -> ScanHistoryPage {
        var components = URLComponents(url: baseURL.appendingPathComponent("api/v1/homework/batches"),
                                       resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "limit", value: String(limit))]
        guard let url = components?.url else { throw NetworkError.invalidResponse }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        let dto = try await client.send(request, as: BatchListDTO.self)
        return mapper.page(dto)
    }

    func fetchAnalysisResult(id: String) async throws -> HomeworkAnalysisResult {
        let response = try await analysis.get(id: id)
        guard let result = response.result else { throw ScanHistoryError.resultUnavailable }
        return result
    }
}

/// Preview / UI-test / development only. The live demo always reads the server.
@MainActor
final class MockScanHistoryService: ScanHistoryServing {
    private let page: ScanHistoryPage
    private let results: [String: HomeworkAnalysisResult]
    private(set) var fetchCount = 0

    init(page: ScanHistoryPage = MockScanHistoryService.demoPage(),
         results: [String: HomeworkAnalysisResult] = [:]) {
        self.page = page
        self.results = results
    }

    func fetchBatches(limit: Int) async throws -> ScanHistoryPage {
        fetchCount += 1
        return page
    }

    func fetchAnalysisResult(id: String) async throws -> HomeworkAnalysisResult {
        guard let result = results[id] else { throw ScanHistoryError.resultUnavailable }
        return result
    }

    nonisolated static func demoPage() -> ScanHistoryPage {
        let stages = ["image_received", "questions_detected", "answers_understood",
                      "error_patterns", "knowledge_updated"]
        let labels = ["已接收图片", "已识别题目", "已理解作答", "正在分析错误模式", "正在更新知识状态"]
        let progress = AnalysisProgress(
            percent: 0.62, currentStageKey: "error_patterns", currentStageLabelZH: "正在分析错误模式",
            stages: zip(stages, labels).enumerated().map { index, pair in
                AnalysisStage(key: pair.0, labelZH: pair.1,
                              state: index < 3 ? .done : index == 3 ? .active : .pending)
            })
        let batches = [
            ScanBatch(analysisID: "ana_demo_processing", batchNumber: 24, state: .processing,
                      stateLabel: "正在处理", sourceName: "数学下册第 32 页", imageCount: 2,
                      createdAt: Date(), finishedAt: nil, durationSeconds: nil,
                      questionCount: nil, correctCount: nil, wrongCount: nil,
                      progress: progress, errorCode: nil, errorMessage: nil),
            ScanBatch(analysisID: "ana_demo_success", batchNumber: 23, state: .success,
                      stateLabel: "成功", sourceName: "数学下册第 31 页", imageCount: 1,
                      createdAt: Date().addingTimeInterval(-3600),
                      finishedAt: Date().addingTimeInterval(-3570), durationSeconds: 28.3,
                      questionCount: 9, correctCount: 5, wrongCount: 1,
                      progress: nil, errorCode: nil, errorMessage: nil),
            ScanBatch(analysisID: "ana_demo_failed", batchNumber: 22, state: .failed,
                      stateLabel: "失败", sourceName: nil, imageCount: 1,
                      createdAt: Date().addingTimeInterval(-7200),
                      finishedAt: Date().addingTimeInterval(-7197), durationSeconds: 3,
                      questionCount: nil, correctCount: nil, wrongCount: nil,
                      progress: nil, errorCode: "QUESTION_NOT_RECOGNIZED",
                      errorMessage: "没有从图片中识别出题目")
        ]
        return ScanHistoryPage(batches: batches, total: batches.count, processingCount: 1,
                               successCount: 1, failedCount: 1)
    }
}
