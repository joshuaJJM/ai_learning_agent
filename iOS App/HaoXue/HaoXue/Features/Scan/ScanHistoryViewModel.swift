import Foundation
import Observation

/// Drives the scan history list. The list is always the server's
/// `GET /api/v1/homework/batches`; the app keeps no upload history of its own.
/// Polling runs only while a batch is still processing (2–3s), and stops by
/// itself as soon as nothing is running.
@MainActor @Observable
final class ScanHistoryViewModel {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failed(String)
    }

    private(set) var state: LoadState = .idle
    private(set) var batches: [ScanBatch] = []
    private(set) var total = 0
    private(set) var processingCount = 0
    private(set) var isRefreshing = false
    private(set) var refreshFailed = false
    private(set) var openedResult: HomeworkAnalysisResult?
    private(set) var isOpeningResult = false
    private(set) var openError: String?

    private let service: any ScanHistoryServing
    private let limit: Int
    private let pollInterval: Duration
    private var loop: Task<Void, Never>?
    private var generation = 0

    init(service: (any ScanHistoryServing)? = nil, limit: Int = 50,
         pollInterval: Duration = .seconds(2.5)) {
        if let service {
            self.service = service
        } else {
            let baseURL = AppConfiguration.demoBackendURL
            let client = APIClient(timeout: 60)
            self.service = LiveScanHistoryService(
                baseURL: baseURL, client: client,
                analysis: LiveAnalysisService(baseURL: baseURL, client: client))
        }
        self.limit = limit
        self.pollInterval = pollInterval
    }

    var isEmpty: Bool { batches.isEmpty }
    var hasProcessing: Bool { processingCount > 0 || batches.contains { $0.isProcessing } }

    /// Starts (or resumes) the list refresh loop. Safe to call on every appear:
    /// only one loop runs at a time.
    func start() {
        guard loop == nil else { return }
        generation += 1
        let generation = self.generation
        loop = Task { [weak self] in
            guard let self else { return }
            defer { if self.generation == generation { self.loop = nil } }
            while !Task.isCancelled {
                await self.load()
                guard !Task.isCancelled, self.generation == generation else { return }
                // Nothing is running any more: stop polling instead of keeping
                // a timer alive in the background.
                guard self.hasProcessing else { return }
                try? await Task.sleep(for: self.pollInterval)
            }
        }
    }

    func stop() {
        generation += 1
        loop?.cancel()
        loop = nil
    }

    /// Manual refresh (pull to refresh / retry button). Restarts the loop so a
    /// stopped list starts polling again if something is processing.
    func refresh() {
        stop()
        start()
    }

    private func load() async {
        if batches.isEmpty { state = .loading } else { isRefreshing = true }
        defer { isRefreshing = false }
        do {
            let page = try await service.fetchBatches(limit: limit)
            batches = page.batches
            total = page.total
            processingCount = page.processingCount
            refreshFailed = false
            state = .loaded
        } catch {
            refreshFailed = true
            // Keep the last good list on a poll failure; only an empty list
            // becomes a full-page error (never an infinite spinner).
            if batches.isEmpty { state = .failed(Self.message(for: error)) }
        }
    }

    /// Opens a batch by loading the same analysis result the scan flow uses,
    /// so history and "just finished" share one detail screen.
    func openResult(id: String) async {
        isOpeningResult = true
        openError = nil
        defer { isOpeningResult = false }
        do {
            openedResult = try await service.fetchAnalysisResult(id: id)
        } catch {
            openError = Self.message(for: error)
        }
    }

    func clearOpenedResult() { openedResult = nil }

    static func message(for error: Error) -> String {
        if let network = error as? NetworkError {
            switch network {
            case .backend(let code, _, _, _):
                return ScanFailurePresentation(code: code).message
            case .timeout, .transport, .invalidResponse:
                return "连接暂时中断，稍后会自动重试。"
            case .decoding:
                return "记录暂时无法显示，请重试。"
            case .cancelled:
                return "已取消。"
            case .httpStatus:
                return "记录暂时无法显示，请重试。"
            }
        }
        if error is ScanHistoryError { return ScanFailurePresentation(code: "RESULT_UNAVAILABLE").message }
        return "记录暂时无法显示，请重试。"
    }
}
