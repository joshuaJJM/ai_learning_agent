import XCTest
import UIKit
@testable import HaoXue

final class Phase2Tests: XCTestCase {
    func testProgressDecodesAllFiveStages() throws {
        let json = #"{"analysis_id":"ana_1","status":"processing","progress":{"percent":0.62,"current_stage_key":"error_patterns","current_stage_label_zh":"正在分析错误模式","stages":[{"key":"image_received","label_zh":"已接收图片","state":"done"},{"key":"questions_detected","label_zh":"已识别题目","state":"done"},{"key":"answers_understood","label_zh":"已理解作答","state":"done"},{"key":"error_patterns","label_zh":"正在分析错误模式","state":"active"},{"key":"knowledge_updated","label_zh":"正在更新知识状态","state":"pending"}]}}"#
        let result = try JSONDecoder().decode(AnalysisResponse.self, from: Data(json.utf8))
        XCTAssertEqual(result.analysisID, "ana_1")
        XCTAssertEqual(result.progress?.percent, 0.62)
        XCTAssertEqual(result.progress?.stages.map(\.state), [.done, .done, .done, .active, .pending])
    }

    func testAllAnalysisStatusesAndFailureCodeDecode() throws {
        for status in [AnalysisPhase.queued, .processing, .completed, .failed] {
            let json = #"{"analysis_id":"ana_1","status":"\#(status.rawValue)"}"#
            XCTAssertEqual(try JSONDecoder().decode(AnalysisResponse.self, from: Data(json.utf8)).status, status)
        }
        let failure = #"{"analysis_id":"ana_1","status":"failed","error":{"error_code":"VLM_TIMEOUT","message":"timeout"}}"#
        XCTAssertEqual(try JSONDecoder().decode(AnalysisResponse.self, from: Data(failure.utf8)).error?.errorCode, "VLM_TIMEOUT")
    }

    func testPreparationResizesAndProducesBoundedJPEG() throws {
        let image = UIGraphicsImageRenderer(size: CGSize(width: 4000, height: 3000)).image { context in
            UIColor.white.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 4000, height: 3000))
        }
        let output = try ImagePreparationService().prepare(image)
        let decoded = try XCTUnwrap(UIImage(data: output))
        XCTAssertLessThanOrEqual(max(decoded.size.width, decoded.size.height), 2500)
        XCTAssertLessThan(output.count, 12 * 1024 * 1024)
        XCTAssertEqual(Array(output.prefix(2)), [0xFF, 0xD8])
    }

    @MainActor func testCreateRequestReusesIdempotencyKey() throws {
        let service = LiveAnalysisService(baseURL: URL(string: "http://localhost:17283")!, client: APIClient())
        let key = UUID()
        let first = service.makeCreateRequest(images: [Data([0xFF, 0xD8])], key: key)
        let retry = service.makeCreateRequest(images: [Data([0xFF, 0xD8])], key: key)
        XCTAssertEqual(first.value(forHTTPHeaderField: "Idempotency-Key"), retry.value(forHTTPHeaderField: "Idempotency-Key"))
        XCTAssertEqual(first.value(forHTTPHeaderField: "Idempotency-Key"), key.uuidString)
    }

    @MainActor func testMockAnalysisReachesCompletedThroughFiveStages() async throws {
        let service = MockAnalysisService()
        let created = try await service.create(images: [Data([1])], key: UUID())
        XCTAssertEqual(created.status, .queued)
        for _ in 0..<5 {
            let state = try await service.get(id: created.analysisID)
            XCTAssertEqual(state.status, .processing)
            XCTAssertEqual(state.progress?.stages.count, 5)
        }
        let completed = try await service.get(id: created.analysisID)
        XCTAssertEqual(completed.status, .completed)
        XCTAssertEqual(completed.progress?.percent, 1)
        XCTAssertTrue(completed.progress?.stages.allSatisfy { $0.state == .done } == true)
    }
}
