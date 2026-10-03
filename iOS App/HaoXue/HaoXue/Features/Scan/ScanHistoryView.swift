import SwiftUI

/// Upload history, read straight from `GET /api/v1/homework/batches`.
/// Tapping a finished batch reuses `AnalysisResultView` — history and the
/// just-finished scan share one detail screen, one view model and one model.
struct ScanHistoryView: View {
    private let onStartTutor: (String?) -> Void
    private let onStartPractice: (String?) -> Void
    private let onOpenWrongQuestion: (String) -> Void
    private let onOpenKnowledge: (String) -> Void
    private let onReturnHome: () -> Void

    @State private var model: ScanHistoryViewModel
    @State private var showingResult = false
    @State private var resultModel: AnalysisResultModel?
    /// Previews and UI tests inject a mock service; only a live list gets the
    /// live confirmation path.
    private let usesLiveBackend: Bool

    init(service: (any ScanHistoryServing)? = nil,
         onStartTutor: @escaping (String?) -> Void,
         onStartPractice: @escaping (String?) -> Void,
         onOpenWrongQuestion: @escaping (String) -> Void,
         onOpenKnowledge: @escaping (String) -> Void,
         onReturnHome: @escaping () -> Void) {
        _model = State(initialValue: ScanHistoryViewModel(service: service))
        self.usesLiveBackend = service == nil
        self.onStartTutor = onStartTutor
        self.onStartPractice = onStartPractice
        self.onOpenWrongQuestion = onOpenWrongQuestion
        self.onOpenKnowledge = onOpenKnowledge
        self.onReturnHome = onReturnHome
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DemoMetrics.sectionGap) {
                DemoPageHeader(title: "历史记录",
                               subtitle: "每一次扫描都留在服务器上，随时可以回看。")
                content
            }
            .padding(.horizontal, DemoMetrics.pagePadding)
            .padding(.top, DemoMetrics.pageTopPadding)
            .padding(.bottom, DemoMetrics.pageBottomPadding)
        }
        .background(DemoStyle.background)
        .navigationTitle("历史记录")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { model.refresh() }
        .onAppear { model.start() }
        .onDisappear { model.stop() }
        .navigationDestination(isPresented: $showingResult) {
            if let resultModel {
                AnalysisResultView(model: resultModel, onStartTutor: onStartTutor,
                                   onStartPractice: onStartPractice,
                                   onOpenWrongQuestion: onOpenWrongQuestion,
                                   onOpenKnowledge: onOpenKnowledge) {
                    showingResult = false
                    model.clearOpenedResult()
                    self.resultModel = nil
                }
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        VStack(alignment: .leading, spacing: 12) {
            switch model.state {
            case .idle, .loading:
                DemoCard {
                    VStack(alignment: .leading, spacing: 12) {
                        ProgressView().controlSize(.large)
                        Text("正在读取扫描记录").font(DemoType.secondary)
                            .foregroundStyle(DemoStyle.secondary)
                    }
                }
            case .failed(let message):
                DemoCard {
                    VStack(alignment: .leading, spacing: 14) {
                        Text(message).font(DemoType.secondary).foregroundStyle(DemoStyle.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        Button("重新尝试") { model.refresh() }
                            .buttonStyle(DemoSecondaryButtonStyle())
                    }
                }
            case .loaded:
                if model.isEmpty {
                    DemoCard {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("还没有扫描记录").font(.title3.bold())
                            Text("从扫描页上传第一份作业后，这里会记录每一次分析。")
                                .font(DemoType.secondary)
                                .foregroundStyle(DemoStyle.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                } else {
                    if model.refreshFailed {
                        Label("列表刷新失败，稍后会自动重试", systemImage: "wifi.exclamationmark")
                            .font(DemoType.meta)
                            .foregroundStyle(DemoStyle.secondary)
                    }
                    ForEach(model.batches) { batch in
                        batchRow(batch)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func batchRow(_ batch: ScanBatch) -> some View {
        Button {
            guard !batch.isProcessing else { return }
            Task {
                await model.openResult(id: batch.analysisID)
                guard let result = model.openedResult else { return }
                resultModel = usesLiveBackend ? AnalysisResultModel(liveResult: result)
                                              : AnalysisResultModel(result: result)
                showingResult = true
            }
        } label: {
            DemoCard {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text(batch.title).font(.headline)
                        Spacer(minLength: 8)
                        Text(timeLabel(batch))
                            .font(.subheadline.monospacedDigit())
                            .foregroundStyle(DemoStyle.secondary)
                    }
                    if let source = batch.sourceName, !source.isEmpty {
                        Text(source).font(.subheadline).foregroundStyle(DemoStyle.secondary)
                    }
                    statusContent(batch)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(batch.isProcessing)
        .accessibilityIdentifier("history-batch-\(batch.analysisID)")
    }

    @ViewBuilder
    private func statusContent(_ batch: ScanBatch) -> some View {
        switch batch.state {
        case .processing:
            VStack(alignment: .leading, spacing: 8) {
                Text(processingStage(batch)).font(.subheadline)
                if let percent = batch.progress?.percent {
                    ProgressView(value: percent).tint(.blue)
                }
            }
        case .success:
            Text(successSummary(batch)).font(.subheadline)
        case .failed:
            VStack(alignment: .leading, spacing: 5) {
                Text("分析失败").font(.subheadline).foregroundStyle(.orange)
                Text(batch.errorMessage ?? ScanFailurePresentation(code: batch.errorCode).message)
                    .font(.subheadline)
                    .foregroundStyle(DemoStyle.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        case .unknown(let raw):
            Text(raw).font(.subheadline).foregroundStyle(DemoStyle.secondary)
        }
    }

    private func processingStage(_ batch: ScanBatch) -> String {
        if batch.progress?.isRetrying == true {
            return batch.progress?.retryNote ?? "正在使用备用模型重试"
        }
        return batch.progress?.currentStageLabelZH ?? "正在分析"
    }

    private func successSummary(_ batch: ScanBatch) -> String {
        guard let count = batch.questionCount else { return "分析完成" }
        var parts = ["\(count) 道题"]
        if let correct = batch.correctCount { parts.append("\(correct) 正确") }
        if let wrong = batch.wrongCount, wrong > 0 { parts.append("\(wrong) 需关注") }
        return parts.joined(separator: " · ")
    }

    private func timeLabel(_ batch: ScanBatch) -> String {
        guard let date = batch.finishedAt ?? batch.createdAt else { return "" }
        if Calendar.current.isDateInToday(date) {
            return date.formatted(date: .omitted, time: .shortened)
        }
        return date.formatted(.dateTime.month(.defaultDigits).day().hour().minute())
    }
}

/// Preview / UI-test entry with the local mock history (never used by the live demo).
struct ScanHistoryPreviewHost: View {
    var body: some View {
        NavigationStack {
            ScanHistoryView(service: MockScanHistoryService(),
                            onStartTutor: { _ in }, onStartPractice: { _ in },
                            onOpenWrongQuestion: { _ in }, onOpenKnowledge: { _ in },
                            onReturnHome: {})
        }
    }
}

#Preview {
    ScanHistoryPreviewHost()
}
