import Foundation

// Wire schema for the server-owned upload history.
// Source of truth: backend `docs/API.md` §2.5, `GET /api/v1/homework/batches`.

struct BatchSummaryDTO: Decodable {
    let batchNumber: Int?
    let analysisId: String
    /// Client-facing state: `processing` | `success` | `failed`.
    let state: String
    let stateLabel: String
    /// Internal status (`queued` / `processing` / `completed` / `failed`).
    let status: String?
    let imageCount: Int
    let sourceName: String?
    let createdAt: Date?
    let finishedAt: Date?
    /// Present only while the batch is still running.
    let progress: AnalysisProgress?
    let durationSeconds: Double?
    let questionCount: Int?
    let correctCount: Int?
    let wrongCount: Int?
    /// Present only for failed batches.
    let error: AnalysisFailure?
}

struct BatchListDTO: Decodable {
    let total: Int
    let processingCount: Int
    let successCount: Int
    let failedCount: Int
    let limit: Int
    let items: [BatchSummaryDTO]
}
