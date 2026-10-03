import SwiftUI
import PhotosUI
import VisionKit

struct ScanView: View {
    let store: DemoScenarioStore
    let onStart: (String?) -> Void
    let onOpenWrongQuestion: (String) -> Void
    let onOpenKnowledge: (String) -> Void
    let onStartPractice: (String?) -> Void
    let onReturnHome: () -> Void
    @State private var model = ScanViewModel()
    @State private var selectedID: UUID?
    @State private var selectedPhotos: [PhotosPickerItem] = []
    @State private var showingPhotoPicker = false
    @State private var showingScanner = false
    @State private var showingCameraAlert = false
    @State private var importError = false
    @State private var showingResult = false
    @State private var showingHistory = false
    @State private var resultModel: AnalysisResultModel?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DemoMetrics.sectionGap) {
                header
                if model.pages.isEmpty { emptyState } else {
                    pageCarousel
                    if model.canEdit { reviewControls } else {
                        AnalysisProgressView(model: model, onResult: {
                            if model.isMock { store.showScanResult() }
                            else if model.completedResult != nil { showingResult = true }
                        },
                                             onNewScan: store.resetScanResult)
                    }
                }
                if model.isMock && model.state == .completed && store.scanAnalysisCompleted { scanResult }
            }
            .padding(.horizontal, DemoMetrics.pagePadding)
            .padding(.top, DemoMetrics.pageTopPadding)
            .padding(.bottom, DemoMetrics.pageBottomPadding)
        }
        .background(DemoStyle.background)
        .photosPicker(isPresented: $showingPhotoPicker, selection: $selectedPhotos,
                      maxSelectionCount: 20, matching: .images)
        .onChange(of: showingPhotoPicker) { _, presented in
            ScanDiagnostics.log(presented ? "photoPickerPresented" : "photoPickerDismissed")
        }
        .sheet(isPresented: $showingScanner, onDismiss: {
            ScanDiagnostics.log("scannerDismissed")
        }) {
            DocumentScanner(onScan: { images in
                ScanDiagnostics.log("scannerFinished pages=\(images.count)")
                showingScanner = false
                append(images, source: .camera)
            }, onCancel: {
                ScanDiagnostics.log("scannerCancelled")
                showingScanner = false
            })
            .onAppear { ScanDiagnostics.log("scannerPresented") }
        }
        .alert("无法打开扫描器", isPresented: $showingCameraAlert) {
            Button("好的", role: .cancel) {}
        } message: {
            Text("请在支持相机的 iPhone 上扫描，或从照片选择页面。")
        }
        .alert("照片导入失败", isPresented: $importError) {
            Button("好的", role: .cancel) {}
        } message: {
            Text("请重新选择清晰的作业照片。")
        }
        .onChange(of: selectedPhotos) { _, newItems in
            guard !newItems.isEmpty else { return }
            ScanDiagnostics.log("photoPicked items=\(newItems.count)")
            Task {
                var importedPages: [ScanPage] = []
                for item in newItems {
                    if let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) {
                        ScanDiagnostics.log("[PhotoImport] original size=\(image.size) orientation=\(image.imageOrientation.rawValue) bytes=\(data.count)")
                        let processed = await Task.detached(priority: .userInitiated) {
                            DocumentImageProcessor().processWithMetadata(image)
                        }.value
                        importedPages.append(ScanPage(image: processed.image, source: .photos,
                                                      wasDocumentCorrected: processed.wasDocumentCorrected,
                                                      originalSize: image.size))
                    }
                }
                selectedPhotos = []
                ScanDiagnostics.log("photoLoaded count=\(importedPages.count)")
                if importedPages.isEmpty { importError = true } else {
                    model.append(importedPages)
                    selectedID = model.pages.last?.id
                }
            }
        }
        .onAppear { model.resume() }
        .onDisappear { model.stop() }
        .onChange(of: model.state) { _, state in
            if state == .completed, !model.isMock, model.completedResult != nil {
                presentResult()
                showingResult = true
            }
        }
        .navigationDestination(isPresented: $showingResult) {
            if let resultModel {
                AnalysisResultView(model: resultModel, onStartTutor: onStart,
                                   onStartPractice: onStartPractice,
                                   onOpenWrongQuestion: onOpenWrongQuestion,
                                   onOpenKnowledge: onOpenKnowledge) {
                    showingResult = false
                    onReturnHome()
                }
            }
        }
        .navigationDestination(isPresented: $showingHistory) {
            ScanHistoryView(onStartTutor: onStart, onStartPractice: onStartPractice,
                            onOpenWrongQuestion: onOpenWrongQuestion,
                            onOpenKnowledge: onOpenKnowledge,
                            onReturnHome: onReturnHome)
        }
    }

    /// Builds the result screen for the batch that just finished. Manual answer
    /// confirmation is only attached for a real backend result.
    private func presentResult() {
        guard let result = model.completedResult else { return }
        resultModel = model.isMock ? AnalysisResultModel(result: result)
                                   : AnalysisResultModel(liveResult: result)
    }

    private var header: some View {
        HStack(alignment: .top) {
            DemoPageHeader(title: "扫描", subtitle: "作业、试卷，或者一道你不会的题，都可以直接交给好学。")
            Spacer(minLength: 8)
            Button { showingHistory = true } label: {
                Image(systemName: "clock.arrow.circlepath")
                    .font(.title3)
                    .frame(width: DemoMetrics.iconButtonSize, height: DemoMetrics.iconButtonSize)
            }
            .accessibilityLabel("历史记录")
            .accessibilityIdentifier("scan-history-button")
            Menu {
                Button(model.isMock ? "使用真实后端" : "切换演示模式") { model.setMock(!model.isMock) }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.title3)
                    .frame(width: DemoMetrics.iconButtonSize, height: DemoMetrics.iconButtonSize)
            }
            .disabled(!model.canEdit)
            .accessibilityLabel("扫描设置")
        }
    }

    private var emptyState: some View {
        DemoCard {
            VStack(spacing: 20) {
                Image(systemName: "doc.viewfinder")
                    .font(DemoMetrics.emptyStateSymbol)
                    .foregroundStyle(.blue)
                Text("从一页作业开始").font(.title2.bold())
                Text("可以连续扫描多页，也可以从相册选择。开始分析前，还能继续添加和删除页面。")
                    .font(DemoType.secondary)
                    .foregroundStyle(DemoStyle.secondary)
                    .multilineTextAlignment(.center)
                scanButton
                photoButton
                if model.isMock {
                    Button("添加演示页面") { append([demoPage()], source: .photos) }
                        .font(.subheadline)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 24)
        }
    }

    private var pageCarousel: some View {
        VStack(spacing: DemoMetrics.sectionTitleGap) {
            Text("已扫描 \(model.pages.count) 页")
                .font(DemoType.sectionTitle)
                .foregroundStyle(DemoStyle.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
            GeometryReader { geometry in
                ScrollView(.horizontal) {
                    LazyHStack(spacing: 14) {
                        ForEach(Array(model.pages.enumerated()), id: \.element.id) { index, page in
                            let isCentered = selectedID == page.id
                            let step = Double(min(max(index - currentIndex, -1), 1))
                            DemoCard {
                                VStack(alignment: .leading, spacing: 12) {
                                    Text("第 \(index + 1) 页")
                                        .font(.subheadline.bold())
                                        .foregroundStyle(DemoStyle.secondary)
                                    Image(uiImage: page.image)
                                        .resizable()
                                        .scaledToFit()
                                        .frame(maxWidth: .infinity)
                                        .frame(height: 350)
                                        .background(Color(uiColor: .secondarySystemBackground),
                                                    in: RoundedRectangle(cornerRadius: DemoMetrics.controlCornerRadius))
                                }
                            }
                            .frame(width: max(geometry.size.width - 64, 220))
                            // Light Cover Flow: the neighbours step back, never a 3D carousel.
                            .scaleEffect(isCentered ? 1 : 0.95)
                            .opacity(isCentered ? 1 : 0.78)
                            .rotation3DEffect(.degrees(reduceMotion ? 0 : -step * 2.5),
                                              axis: (x: 0, y: 1, z: 0))
                            .id(page.id)
                            .accessibilityLabel("扫描页面 \(index + 1)，共 \(model.pages.count) 页")
                        }
                    }
                    .scrollTargetLayout()
                }
                .scrollIndicators(.hidden)
                .scrollTargetBehavior(.viewAligned)
                .scrollPosition(id: $selectedID)
            }
            .frame(height: 430)
            Text("\(currentIndex + 1) / \(model.pages.count)")
                .font(DemoType.secondary.monospacedDigit())
                .foregroundStyle(DemoStyle.secondary)
                .frame(maxWidth: .infinity)
                .accessibilityLabel("第 \(currentIndex + 1) 页，共 \(model.pages.count) 页")
        }
        .animation(DemoMotion.resolved(reduceMotion, Animation.interactiveSpring()), value: selectedID)
    }

    private var currentIndex: Int {
        model.pages.firstIndex(where: { $0.id == selectedID }) ?? 0
    }

    private var reviewControls: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                Button(role: .destructive) {
                    let index = currentIndex
                    model.delete(at: index)
                    selectedID = model.pages.isEmpty ? nil : model.pages[min(index, model.pages.count - 1)].id
                } label: { Label("删除当前页", systemImage: "trash") }
                .frame(maxWidth: .infinity)
                Menu {
                    Button("再次扫描", systemImage: "doc.viewfinder") {
                        ScanDiagnostics.log("tapScanAgain")
                        openScanner()
                    }
                    Button("从照片选择", systemImage: "photo.on.rectangle", action: openPhotoPicker)
                    if model.isMock {
                        Button("添加演示页面") { append([demoPage()], source: .photos) }
                    }
                } label: { Label("上传更多", systemImage: "plus") }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            Button("开始分析") {
                store.resetScanResult()
                model.start()
            }
                .buttonStyle(DemoPrimaryButtonStyle())
        }
    }

    private var scanButton: some View {
        Button(action: openScanner) { Label("扫描文档", systemImage: "doc.viewfinder") }
            .buttonStyle(DemoPrimaryButtonStyle())
    }

    private var photoButton: some View {
        Button(action: openPhotoPicker) {
            Label("从照片选择", systemImage: "photo.on.rectangle")
                .font(.headline)
                .frame(maxWidth: .infinity)
                .frame(minHeight: DemoMetrics.controlMinHeight)
        }
        .buttonStyle(.bordered)
    }

    private func openScanner() {
        ScanDiagnostics.log("requestScannerPresentation supported=\(VNDocumentCameraViewController.isSupported) showingScanner=\(showingScanner) selectedPhotos=\(selectedPhotos.count)")
        if VNDocumentCameraViewController.isSupported { showingScanner = true }
        else { showingCameraAlert = true }
    }

    private func openPhotoPicker() {
        ScanDiagnostics.log("openPhotoPicker")
        showingPhotoPicker = true
    }

    private func append(_ images: [UIImage], source: ScanSource) {
        model.append(images, source: source)
        selectedID = model.pages.last?.id
    }

    private func demoPage() -> UIImage {
        let size = CGSize(width: 900, height: 1200)
        return UIGraphicsImageRenderer(size: size).image { context in
            UIColor.white.setFill()
            context.fill(CGRect(origin: .zero, size: size))
            let text = "高中数学 · 导数练习\n\n1. 求函数 f(x) = x² 的导数。\n\nA. x    B. 2x    C. x²    D. 2"
            text.draw(in: CGRect(x: 80, y: 100, width: 740, height: 800),
                      withAttributes: [.font: UIFont.systemFont(ofSize: 40), .foregroundColor: UIColor.black])
        }
    }

    private var scanResult: some View {
        DemoCard {
            VStack(alignment: .leading, spacing: 13) {
                Text("分析结果预览").font(.headline)
                Text("完整题目结果将在后续集成阶段接入。你可以继续体验现有学习演示。")
                    .font(.subheadline).foregroundStyle(DemoStyle.secondary)
                Button("开始学习") { onStart(nil) }
                    .buttonStyle(DemoPrimaryButtonStyle())
            }
        }
    }
}

private struct AnalysisProgressView: View {
    let model: ScanViewModel
    let onResult: () -> Void
    let onNewScan: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        DemoCard {
            VStack(alignment: .leading, spacing: 15) {
                Text(title).font(.title3.bold())
                if let progress = model.analysis?.progress {
                    ProgressView(value: progress.percent)
                        .tint(.blue)
                        .animation(DemoMotion.standard, value: progress.percent)
                    Text("\(Int((progress.percent * 100).rounded()))%")
                        .font(.subheadline.monospacedDigit())
                        .demoNumberTransition(progress.percent, reduceMotion: reduceMotion)
                    if progress.isRetrying {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            ProgressView().controlSize(.small)
                            Text(progress.retryNote ?? "模型暂时不可用，正在使用备用模型重试")
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .font(.subheadline)
                        .foregroundStyle(.orange)
                        .accessibilityIdentifier("analysis-retrying-note")
                    }
                    ForEach(progress.stages) { stage in
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Image(systemName: symbol(for: stage.state))
                                .contentTransition(.symbolEffect(.replace))
                            Text(stage.labelZH)
                        }
                            .font(DemoType.secondary)
                            .foregroundStyle(tint(for: stage.state))
                            .animation(DemoMotion.standard, value: stage.state)
                            .accessibilityElement(children: .combine)
                            .accessibilityLabel("\(stage.labelZH)，\(stateLabel(for: stage.state))")
                    }
                } else if model.isBusy {
                    ProgressView().controlSize(.large)
                }
                if model.state == .failed {
                    Text(errorMessage).font(.subheadline).foregroundStyle(DemoStyle.secondary)
                    Button(ScanFailurePresentation(code: model.errorCode).requiresNewScan ? "重新扫描" : "重新尝试") {
                        if ScanFailurePresentation(code: model.errorCode).requiresNewScan { model.newScan() }
                        else { model.retry() }
                    }
                    .buttonStyle(DemoPrimaryButtonStyle())
                }
                if model.state == .completed {
                    Text("本次分析结果已准备好")
                        .font(.subheadline).foregroundStyle(DemoStyle.secondary)
                    Button("查看分析结果", action: onResult)
                        .buttonStyle(DemoPrimaryButtonStyle())
                    Button("新建一次扫描") {
                        model.newScan()
                        onNewScan()
                    }
                    .buttonStyle(DemoSecondaryButtonStyle())
                }
            }
        }
    }

    private var title: String {
        switch model.state {
        case .preparing: "正在准备图片"
        case .uploading: "正在上传页面"
        case .queued: "正在等待分析"
        case .processing: model.analysis?.progress?.currentStageLabelZH ?? "正在理解你的作业"
        case .completed: "分析完成"
        case .failed: "分析暂时没有完成"
        case .review: "准备分析"
        }
    }

    private var errorMessage: String {
        ScanFailurePresentation(code: model.errorCode).message
    }

    private func tint(for state: AnalysisStageState) -> Color {
        switch state {
        case .failed: .red
        case .retrying: .orange
        case .active: model.state == .failed ? .red : .blue
        case .done, .pending, .unknown(_): DemoStyle.secondary
        }
    }

    private func symbol(for state: AnalysisStageState) -> String {
        switch state {
        case .done: "checkmark.circle.fill"
        case .active: model.state == .failed ? "xmark.circle.fill" : "circle.dotted.circle"
        case .retrying: "arrow.triangle.2.circlepath"
        case .pending: "circle"
        case .failed: "xmark.circle.fill"
        case .unknown: "circle"
        }
    }

    private func stateLabel(for state: AnalysisStageState) -> String {
        switch state {
        case .done: "已完成"
        case .active: model.state == .failed ? "未完成" : "进行中"
        case .retrying: "正在使用备用模型重试"
        case .pending: "等待中"
        case .failed: "未完成"
        case .unknown: "进行中"
        }
    }
}
