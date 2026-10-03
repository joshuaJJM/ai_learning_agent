import Foundation

struct ScanHistoryMapper {
    func batch(_ dto: BatchSummaryDTO) -> ScanBatch {
        ScanBatch(analysisID: dto.analysisId, batchNumber: dto.batchNumber,
                  state: ScanBatchState(rawValue: dto.state), stateLabel: dto.stateLabel,
                  sourceName: dto.sourceName, imageCount: dto.imageCount,
                  createdAt: dto.createdAt, finishedAt: dto.finishedAt,
                  durationSeconds: dto.durationSeconds, questionCount: dto.questionCount,
                  correctCount: dto.correctCount, wrongCount: dto.wrongCount,
                  progress: dto.progress,
                  errorCode: dto.error?.errorCode, errorMessage: dto.error?.message)
    }

    func page(_ dto: BatchListDTO) -> ScanHistoryPage {
        ScanHistoryPage(batches: dto.items.map(batch), total: dto.total,
                        processingCount: dto.processingCount, successCount: dto.successCount,
                        failedCount: dto.failedCount)
    }
}
