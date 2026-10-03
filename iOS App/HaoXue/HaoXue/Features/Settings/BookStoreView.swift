import SwiftUI

struct BookStoreView: View {
    let commercial: CommercialDemoStore
    @State private var knowledgeModel = KnowledgeOverviewViewModel(provider: LiveDataProvider(
        client: APIClient(), configuration: AppConfiguration(mode: .live)))

    private var ranked: [BookRelevance] {
        BookRecommendationEngine.rank(DemoBookCatalog.books, using: BookRecommendationEngine.points(from: knowledgeModel.overview))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DemoMetrics.sectionGap) {
                if knowledgeModel.overview == nil {
                    Text("连接学习状态后，推荐会根据你的薄弱知识点更新。")
                        .font(DemoType.secondary).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                bookSection("为你推荐", books: Array(ranked.prefix(2)))
                ForEach(["导数专项", "高中数学精选", "更多训练"], id: \.self) { category in
                    bookSection(category, books: ranked.filter { $0.book.category == category })
                }
                Text("图书与封面均为好学原创演示内容，题量为 Demo 数据。")
                    .font(DemoType.meta).foregroundStyle(.secondary)
            }
            .padding(.horizontal, DemoMetrics.pagePadding)
            .padding(.top, DemoMetrics.pageTopPadding)
            .padding(.bottom, DemoMetrics.pageBottomPadding)
        }
        .navigationTitle("图书与题库")
        .task { await knowledgeModel.loadIfNeeded() }
    }

    private func bookSection(_ title: String, books: [BookRelevance]) -> some View {
        VStack(alignment: .leading, spacing: DemoMetrics.sectionTitleGap) {
            Text(title).font(.title2.bold())
            ForEach(books, id: \.book.id) { relevance in
                NavigationLink {
                    BookDetailView(relevance: relevance, commercial: commercial)
                } label: {
                    HStack(alignment: .top, spacing: 16) {
                        Image(relevance.book.coverAssetName)
                            .resizable().scaledToFit().frame(width: 86, height: 116)
                            .clipShape(RoundedRectangle(cornerRadius: 7))
                        VStack(alignment: .leading, spacing: 7) {
                            // `Color.primary` / `DemoStyle.secondary` are concrete
                            // colours: hierarchical `.primary` / `.secondary` would
                            // inherit the NavigationLink tint and flood the row blue.
                            Text(relevance.book.title).font(.headline).foregroundStyle(Color.primary)
                            Text(relevance.book.subtitle).font(DemoType.secondary)
                                .foregroundStyle(DemoStyle.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                            Text(relevance.explanation).font(DemoType.meta)
                                .foregroundStyle(DemoStyle.accent)
                                .fixedSize(horizontal: false, vertical: true)
                            Text("\(relevance.book.questionCount) 道练习 · \(relevance.book.difficulty)")
                                .font(DemoType.meta).foregroundStyle(DemoStyle.secondary)
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.vertical, 6)
                }
                Divider()
            }
        }
    }
}

struct BookDetailView: View {
    let relevance: BookRelevance
    let commercial: CommercialDemoStore
    @State private var serial = ""
    @State private var isValidating = false
    @State private var message: String?
    @State private var showPlan = false
    @State private var showUnlocked = false
    @State private var showPracticePreview = false

    private var book: DemoBook { relevance.book }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DemoMetrics.sectionGap) {
                Image(book.coverAssetName).resizable().scaledToFit()
                    .frame(width: 172, height: 232).frame(maxWidth: .infinity)
                    .padding(.top, 10)
                VStack(alignment: .leading, spacing: 8) {
                    Text(book.title).font(.largeTitle.bold())
                    Text("高中数学 · 好学原创 Demo 题库").foregroundStyle(.secondary)
                    Text(book.description).padding(.top, 8)
                    Text("\(book.questionCount) 道练习 · \(book.difficulty)")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                VStack(alignment: .leading, spacing: 12) {
                    Text("与你的学习状态").font(.headline)
                    if relevance.matchedPoints.isEmpty {
                        Text("暂无匹配的学习状态，可先浏览这本题库。")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(relevance.matchedPoints, id: \.id) { point in
                            HStack {
                                Text(point.name)
                                Spacer()
                                Text(point.mastery.demoPercent).foregroundStyle(.secondary)
                            }
                            Divider()
                        }
                        Text(relevance.explanation).font(.subheadline).foregroundStyle(.blue)
                    }
                }
                if commercial.hasAccess(to: book.id) {
                    Label("已加入你的题库", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Button("开始练习") { showPracticePreview = true }
                        .buttonStyle(DemoPrimaryButtonStyle())
                    Text("图书题库的独立练习内容为产品预览。")
                        .font(DemoType.meta).foregroundStyle(.secondary)
                } else {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("获得完整题库").font(.headline)
                        Text("包含于「好学计划」 · ¥20 / 月")
                        Button("了解好学计划") { showPlan = true }
                            .buttonStyle(DemoPrimaryButtonStyle())
                        Divider()
                        Text("已经购买纸质图书？")
                        TextField("输入图书序列号", text: $serial)
                            .textInputAutocapitalization(.characters)
                            .textFieldStyle(.roundedBorder)
                        Button(isValidating ? "正在验证序列号…" : "检查并解锁") {
                            Task { await unlock() }
                        }
                        .buttonStyle(DemoSecondaryButtonStyle())
                        .disabled(isValidating)
                        if let message { Text(message).foregroundStyle(.red).font(.subheadline) }
                        Text("Hackathon Demo：任意非空序列号均可解锁。")
                            .font(DemoType.meta).foregroundStyle(.secondary)
                    }
                }
            }
            .padding(.horizontal, DemoMetrics.pagePadding)
            .padding(.top, DemoMetrics.pageTopPadding)
            .padding(.bottom, DemoMetrics.pageBottomPadding)
        }
        .navigationTitle("图书详情")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(isPresented: $showPlan) { LearningPlanView(commercial: commercial) }
        .alert("序列号有效", isPresented: $showUnlocked) {
            Button("开始练习") { showPracticePreview = true }
            Button("稍后") { }
        } message: {
            Text("《\(book.title)》已加入你的题库")
        }
        .alert("题库练习预览", isPresented: $showPracticePreview) {
            Button("知道了") { }
        } message: {
            Text("图书题库的独立练习尚未接入。当前可在学习 Tab 使用现有练习。")
        }
    }

    private func unlock() async {
        guard !serial.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            message = "请输入图书序列号"
            return
        }
        message = nil
        isValidating = true
        try? await Task.sleep(for: .milliseconds(700))
        commercial.unlock(book.id)
        isValidating = false
        showUnlocked = true
    }
}
