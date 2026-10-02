import SwiftUI

struct ScanView: View {
    let store: DemoScenarioStore
    let onStart: () -> Void
    @State private var selectedPage: Int? = 1

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 17) {
                DemoPageHeader(title: "扫描", subtitle: "作业、试卷，或者一道你不会的题，都可以直接交给好学。")
                Text("已扫描 \(store.scanPageCount) 页")
                    .font(.headline).foregroundStyle(DemoStyle.secondary)

                GeometryReader { geometry in
                    ScrollView(.horizontal) {
                        LazyHStack(spacing: 14) {
                            ForEach(1...store.scanPageCount, id: \.self) { page in
                                DemoCard {
                                    VStack(alignment: .leading, spacing: 22) {
                                        Text(store.scanPageHeading)
                                            .font(.subheadline.bold())
                                            .foregroundStyle(DemoStyle.secondary)
                                        Text(page == 1 ? store.scanQuestion : "导数基础 · 第 \(page) 页")
                                            .font(.title3.bold())
                                        ZStack {
                                            RoundedRectangle(cornerRadius: 20)
                                                .fill(Color(uiColor: .secondarySystemBackground))
                                            VStack(spacing: 10) {
                                                Text("f′(x)").font(.title2).foregroundStyle(DemoStyle.secondary)
                                                Text("↘︎  ───  ↗︎    → x")
                                                    .font(.title2.monospaced())
                                            }
                                        }
                                        .frame(height: 145)
                                        Text(store.scanChoices)
                                            .font(.body)
                                            .lineSpacing(9)
                                    }
                                }
                                .frame(width: max(geometry.size.width - 64, 220))
                                .shadow(color: .black.opacity(0.035), radius: 4, y: 2)
                                .id(page)
                            }
                        }
                        .scrollTargetLayout()
                    }
                    .scrollIndicators(.hidden)
                    .scrollTargetBehavior(.viewAligned)
                    .scrollPosition(id: $selectedPage)
                }
                .frame(height: 445)
                Text("\(selectedPage ?? 1) / \(store.scanPageCount)")
                    .font(.subheadline)
                    .foregroundStyle(DemoStyle.secondary)
                    .frame(maxWidth: .infinity)

                DemoCard {
                    VStack(alignment: .leading, spacing: 15) {
                        Text(store.scanAnalysisCompleted ? "分析完成" : "正在理解你的作业")
                            .font(.title3.bold())
                        MasteryBar(value: store.scanAnalysisCompleted ? 1 : 0.68)
                        Text("✓ 图片已上传  ✓ 检测到题目")
                            .font(.subheadline).foregroundStyle(DemoStyle.secondary)
                        if !store.scanAnalysisCompleted {
                            Text("● 正在分析作答与知识点")
                                .font(.subheadline).foregroundStyle(.blue)
                            Button("查看模拟分析结果") { store.showScanResult() }
                                .font(.subheadline.bold())
                        }
                    }
                }
                if store.scanAnalysisCompleted {
                    scanResult
                }
                Button("上传更多") {
                    store.uploadMoreDemoPage()
                    selectedPage = store.scanPageCount
                }
                .font(.headline)
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(.blue, in: Capsule())
                .accessibilityLabel("上传更多模拟页面")
            }
            .padding(.horizontal, 20)
            .padding(.top, 26)
            .padding(.bottom, 30)
        }
        .background(DemoStyle.background)
    }

    private var scanResult: some View {
        DemoCard {
            VStack(alignment: .leading, spacing: 13) {
                Text("识别到 \(GoldenDemoFixtures.analysisCompleted.questions.count) 道题")
                    .font(.headline)
                Text("值得关注").foregroundStyle(DemoStyle.secondary)
                ForEach(Array(store.scanFocusPoints.enumerated()), id: \.offset) { _, point in
                    HStack {
                        Text(point.title)
                        Spacer()
                        Text("\(point.mastery.demoPercent) · 错误 \(point.wrongCount) 次")
                    }
                }
                Text("好学建议你先处理：\(store.lessonTitle)")
                    .font(.subheadline)
                    .padding(.top, 6)
                Button("开始学习", action: onStart)
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .foregroundStyle(.white)
                    .background(.blue, in: Capsule())
            }
        }
    }
}
