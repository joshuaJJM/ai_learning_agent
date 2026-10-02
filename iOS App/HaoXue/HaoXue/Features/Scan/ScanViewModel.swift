import Foundation
import Observation
import UIKit

enum ScanFlowState: Equatable { case review, preparing, uploading, queued, processing, completed, failed }

@MainActor @Observable
final class ScanViewModel {
    private(set) var pages: [ScanPage] = []
    private(set) var state: ScanFlowState = .review
    private(set) var analysis: AnalysisResponse?
    private(set) var completedResult: HomeworkAnalysisResult?
    private(set) var analysisID: String?
    private(set) var errorCode: String?
    private(set) var isMock = false
    private var idempotencyKey: UUID?
    private var preparedImages: [Data]?
    private var task: Task<Void, Never>?
    private var taskGeneration = 0
    private var pollCount = 0
    private let live: any AnalysisServing
    private let mock = MockAnalysisService()
    private let preparation = ImagePreparationService()

    init(baseURL: URL? = nil, liveService: (any AnalysisServing)? = nil) {
        live = liveService ?? LiveAnalysisService(baseURL: baseURL ?? AppConfiguration.demoBackendURL,
                                                  client: APIClient(timeout: 60))
        isMock = ProcessInfo.processInfo.environment["HAOXUE_MOCK_MODE"] == "1"
    }

    var canEdit: Bool { state == .review }
    var isBusy: Bool { [.preparing, .uploading, .queued, .processing].contains(state) }
    var service: any AnalysisServing { isMock ? mock : live }

    func setMock(_ value: Bool) {
        guard state == .review else { return }
        isMock = value
    }

    func append(_ images: [UIImage], source: ScanSource) {
        guard canEdit else { return }
        pages.append(contentsOf: images.map { ScanPage(image: $0, source: source) })
    }

    func append(_ importedPages: [ScanPage]) {
        guard canEdit else { return }
        pages.append(contentsOf: importedPages)
        for page in importedPages {
            ScanDiagnostics.log("[ScanPage] image source=\(page.source == .photos ? "photoLibrary" : "documentCamera") wasDocumentCorrected=\(page.wasDocumentCorrected) original size=\(page.originalSize) final size=\(page.image.size)")
        }
    }

    func delete(at index: Int) {
        guard canEdit, pages.indices.contains(index) else { return }
        pages.remove(at: index)
    }

    func start() {
        guard state == .review, !pages.isEmpty else { return }
        idempotencyKey = UUID()
        preparedImages = nil
        analysisID = nil
        analysis = nil
        completedResult = nil
        errorCode = nil
        pollCount = 0
        launch()
    }

    func retry() {
        guard state == .failed else { return }
        if analysis?.status == .failed {
            // The server has confirmed failure; a retry is a new analysis.
            idempotencyKey = UUID()
            analysisID = nil
            analysis = nil
        }
        errorCode = nil
        pollCount = 0
        launch()
    }

    func newScan() {
        stop()
        pages = []
        state = .review
        analysis = nil
        completedResult = nil
        analysisID = nil
        idempotencyKey = nil
        preparedImages = nil
        errorCode = nil
    }

    func stop() { taskGeneration += 1; task?.cancel(); task = nil }

    func resume() {
        guard task == nil, idempotencyKey != nil, isBusy else { return }
        launch()
    }

    private func launch() {
        guard task == nil else { return }
        taskGeneration += 1
        let generation = taskGeneration
        task = Task { [weak self] in
            guard let self else { return }
            defer { if self.taskGeneration == generation { self.task = nil } }
            do {
                if self.analysisID == nil {
                    if self.preparedImages == nil {
                        self.state = .preparing
                        self.preparedImages = try self.pages.map { try self.preparation.prepare($0.image) }
                    }
                    self.state = .uploading
                    let created = try await self.service.create(images: self.preparedImages!, key: self.idempotencyKey!)
                    guard !Task.isCancelled, self.taskGeneration == generation else { return }
                    self.analysisID = created.analysisID
                    self.state = .queued
                }
                guard let id = self.analysisID else { return }
                while !Task.isCancelled {
                    let response = try await self.service.get(id: id)
                    guard !Task.isCancelled, self.taskGeneration == generation else { return }
                    self.pollCount += 1
                    let progress = response.progress
                    let stages = progress?.stages.map { "\($0.key):\($0.state.rawValue)" }.joined(separator: ",") ?? "none"
                    ScanDiagnostics.log("POLL #\(self.pollCount) analysis_id=\(id) status=\(response.status.rawValue) percent=\(progress?.percent.description ?? "nil") stage=\(progress?.currentStageKey ?? "nil") label=\(progress?.currentStageLabelZH ?? "nil") stages=[\(stages)] error_code=\(response.error?.errorCode ?? "nil")")
                    self.analysis = response
                    switch response.status {
                    case .queued: self.state = .queued
                    case .processing: self.state = .processing
                    case .completed:
                        guard self.isMock || response.result != nil else {
                            self.errorCode = "RESULT_UNAVAILABLE"
                            self.state = .failed
                            return
                        }
                        self.completedResult = response.result
                        self.state = .completed
                        return
                    case .failed:
                        self.errorCode = response.error?.errorCode ?? "ANALYSIS_FAILED"
                        self.state = .failed
                        return
                    }
                    try await Task.sleep(for: .seconds(1))
                }
            } catch is CancellationError {
                ScanDiagnostics.log("POLL cancelled analysis_id=\(self.analysisID ?? "nil")")
                return
            } catch NetworkError.cancelled {
                ScanDiagnostics.log("POLL network_cancelled analysis_id=\(self.analysisID ?? "nil")")
                return
            } catch {
                ScanDiagnostics.log("FLOW error=\(error) analysis_id=\(self.analysisID ?? "nil") state=\(self.state)")
                if let network = error as? NetworkError {
                    switch network {
                    case .backend(let code, _, _, _): self.errorCode = code
                    case .decoding: self.errorCode = "RESULT_UNAVAILABLE"
                    default: self.errorCode = "NETWORK_ERROR"
                    }
                } else {
                    self.errorCode = error is DecodingError ? "RESULT_UNAVAILABLE" : "NETWORK_ERROR"
                }
                self.state = .failed
            }
        }
    }
}
