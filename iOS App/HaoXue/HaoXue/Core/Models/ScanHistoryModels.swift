import Foundation

/// Client-facing state of one upload batch. The server collapses its internal
/// states into exactly these three; an unknown value degrades instead of
/// breaking the list.
enum ScanBatchState: Equatable {
    case processing, success, failed
    case unknown(String)

    init(rawValue: String) {
        switch rawValue {
        case "processing": self = .processing
        case "success": self = .success
        case "failed": self = .failed
        default: self = .unknown(rawValue)
        }
    }

    var isProcessing: Bool { self == .processing }
}

/// One row of `GET /api/v1/homework/batches`. Everything shown here — batch
/// number, state, duration, counters — is server-owned; the app persists no
/// upload history of its own.
struct ScanBatch: Equatable, Identifiable {
    let analysisID: String
    let batchNumber: Int?
    let state: ScanBatchState
    let stateLabel: String
    let sourceName: String?
    let imageCount: Int
    let createdAt: Date?
    let finishedAt: Date?
    let durationSeconds: Double?
    let questionCount: Int?
    let correctCount: Int?
    let wrongCount: Int?
    let progress: AnalysisProgress?
    let errorCode: String?
    let errorMessage: String?

    var id: String { analysisID }
    var isProcessing: Bool { state.isProcessing }

    var title: String {
        guard let batchNumber else { return "本次扫描" }
        return "第 \(batchNumber) 次扫描"
    }
}

/// Page of batches plus the totals the server keeps over **all** batches (they
/// do not change with `limit`, so they can drive the badge).
struct ScanHistoryPage: Equatable {
    let batches: [ScanBatch]
    let total: Int
    let processingCount: Int
    let successCount: Int
    let failedCount: Int

    var hasProcessing: Bool { processingCount > 0 || batches.contains { $0.isProcessing } }
}
