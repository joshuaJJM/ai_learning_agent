import SwiftUI
import PhotosUI
import VisionKit

struct ScanView: View {
    let store: DemoScenarioStore
    let onStart: (String?) -> Void
    let onOpenWrongQuestion: (String) -> Void
    let onReturnHome: () -> Void
    @State private var model = ScanViewModel()
    @State private var selectedID: UUID?
    @State private var selectedPhotos: [PhotosPickerItem] = []
    @State private var showingPhotoPicker = false
    @State private var showingScanner = false
    @State private var showingCameraAlert = false
    @State private var importError = false
    @State private var showingResult = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
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
            .padding(.horizontal, 20)
            .padding(.top, 26)
            .padding(.bottom, 36)
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
                showingResult = true
            }
        }
        .navigationDestination(isPresented: $showingResult) {
            if let result = model.completedResult {
                AnalysisResultView(result: result, onStartTutor: onStart,
                                   onOpenWrongQuestion: onOpenWrongQuestion) {
                    showingResult = false
                    onReturnHome()
                }
            }
        }
    }

    private var header: some View {
        HStack(alignment: .top) {
            DemoPageHeader(title: "扫描", subtitle: "作业、试卷，或者一道你不会的题，都可以直接交给好学。")
            Spacer(minLength: 8)
            Menu {
                Button(model.isMock ? "使用真实后端" : "切换演示模式") { model.setMock(!model.isMock) }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.title3)
                    .frame(width: 44, height: 44)
            }
            .disabled(!model.canEdit)
            .accessibilityLabel("扫描设置")
        }
    }

    private var emptyState: some View {
        DemoCard {
            VStack(spacing: 20) {
                Image(systemName: "doc.viewfinder")
                    .font(.system(size: 58, weight: .ultraLight))
                    .foregroundStyle(.blue)
                Text("从一页作业开始").font(.title2.bold())
                Text("可以连续扫描多页，也可以从相册选择。开始分析前，还能继续添加和删除页面。")
                    .font(.subheadline)
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
        VStack(spacing: 10) {
            Text("已扫描 \(model.pages.count) 页")
                .font(.headline)
                .foregroundStyle(DemoStyle.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
            GeometryReader { geometry in
                ScrollView(.horizontal) {
                    LazyHStack(spacing: 14) {
                        ForEach(Array(model.pages.enumerated()), id: \.element.id) { index, page in
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
                                        .background(Color(uiColor: .secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
                                }
                            }
                            .frame(width: max(geometry.size.width - 64, 220))
                            .scaleEffect(selectedID == page.id ? 1 : 0.94)
                            .opacity(selectedID == page.id ? 1 : 0.72)
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
                .font(.subheadline)
                .foregroundStyle(DemoStyle.secondary)
                .frame(maxWidth: .infinity)
                .accessibilityLabel("第 \(currentIndex + 1) 页，共 \(model.pages.count) 页")
        }
        .animation(.interactiveSpring(), value: selectedID)
    }

    private var currentIndex: Int {
        model.pages.firstIndex(where: { $0.id == selectedID }) ?? 0
    }

    private var reviewControls: some View {
        VStack(spacing: 14) {
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
                .buttonStyle(PrimaryScanButtonStyle())
        }
    }

    private var scanButton: some View {
        Button(action: openScanner) { Label("扫描文档", systemImage: "doc.viewfinder") }
            .buttonStyle(PrimaryScanButtonStyle())
    }

    private var photoButton: some View {
        Button(action: openPhotoPicker) {
            Label("从照片选择", systemImage: "photo.on.rectangle")
                .font(.headline)
                .frame(maxWidth: .infinity)
                .frame(minHeight: 44)
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
                    .buttonStyle(PrimaryScanButtonStyle())
            }
        }
    }
}

private struct PrimaryScanButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .frame(minHeight: 50)
            .background(.blue, in: Capsule())
            .opacity(configuration.isPressed ? 0.75 : 1)
    }
}

private struct AnalysisProgressView: View {
    let model: ScanViewModel
    let onResult: () -> Void
    let onNewScan: () -> Void

    var body: some View {
        DemoCard {
            VStack(alignment: .leading, spacing: 15) {
                Text(title).font(.title3.bold())
                if let progress = model.analysis?.progress {
                    ProgressView(value: progress.percent)
                        .tint(.blue)
                        .animation(.easeInOut, value: progress.percent)
                    Text("\(Int((progress.percent * 100).rounded()))%")
                        .font(.subheadline.monospacedDigit())
                    ForEach(progress.stages) { stage in
                        Label(stage.labelZH, systemImage: symbol(for: stage.state))
                            .foregroundStyle(stage.state == .failed || (stage.state == .active && model.state == .failed) ? .red :
                                             stage.state == .active ? .blue : DemoStyle.secondary)
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
                    .buttonStyle(PrimaryScanButtonStyle())
                }
                if model.state == .completed {
                    Text("本次分析结果已准备好")
                        .font(.subheadline).foregroundStyle(DemoStyle.secondary)
                    Button("查看分析结果", action: onResult)
                        .buttonStyle(PrimaryScanButtonStyle())
                    Button("新建一次扫描") {
                        model.newScan()
                        onNewScan()
                    }
                        .frame(maxWidth: .infinity, minHeight: 44)
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

    private func symbol(for state: AnalysisStageState) -> String {
        switch state {
        case .done: "checkmark.circle.fill"
        case .active: model.state == .failed ? "xmark.circle.fill" : "circle.dotted.circle"
        case .pending: "circle"
        case .failed: "xmark.circle.fill"
        }
    }

    private func stateLabel(for state: AnalysisStageState) -> String {
        switch state {
        case .done: "已完成"
        case .active: model.state == .failed ? "未完成" : "进行中"
        case .pending: "等待中"
        case .failed: "未完成"
        }
    }
}
