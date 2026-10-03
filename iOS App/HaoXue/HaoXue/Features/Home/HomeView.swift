import SwiftUI

struct HomeView: View {
    let model: HomeViewModel
    let onStartTutor: (String?) -> Void
    let onStartPractice: (String?) -> Void
    let onOpenWrongQuestion: (String) -> Void
    let onOpenKnowledge: (String) -> Void
    @State private var showsAllKnowledge = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DemoMetrics.sectionGap) {
                switch model.phase {
                case .idle, .loading:
                    ProgressView("正在获取学习状态")
                        .frame(maxWidth: .infinity)
                        .padding(.top, 100)
                case .failed:
                    errorContent
                        .frame(maxWidth: .infinity)
                        .padding(.top, 100)
                case .loaded:
                    if let home = model.snapshot { homeContent(home) }
                }
            }
            .padding(.horizontal, DemoMetrics.pagePadding)
            .padding(.top, DemoMetrics.pageTopPadding)
            .padding(.bottom, DemoMetrics.pageBottomPadding)
        }
        .background(DemoStyle.background)
        .refreshable { await model.refresh() }
        .task { await model.loadIfNeeded() }
    }

    private var errorContent: some View {
        VStack(spacing: 16) {
            Image(systemName: "wifi.exclamationmark")
                .font(.largeTitle)
                .foregroundStyle(DemoStyle.secondary)
            Text(model.errorMessage ?? "暂时无法获取学习状态")
                .foregroundStyle(DemoStyle.secondary)
                .multilineTextAlignment(.center)
            Button("重新加载") { Task { await model.refresh() } }
                .font(.headline)
        }
    }

    private func homeContent(_ home: HomeSnapshot) -> some View {
        VStack(alignment: .leading, spacing: DemoMetrics.sectionGap) {
            DemoPageHeader(title: "好学", subtitle: home.greeting)

            // Next Step owns the highest visual priority on Home.
            DemoSection(title: "下一步") {
                DemoCard {
                    VStack(alignment: .leading, spacing: 15) {
                        Text(home.nextAction.title).font(.title2.bold())
                        Text(home.nextAction.reason)
                            .foregroundStyle(DemoStyle.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        if HomeActionRoute(home.nextAction) != .none {
                            Button { perform(home.nextAction) } label: {
                                HStack {
                                    Text(home.nextAction.buttonTitle)
                                    Spacer()
                                    Image(systemName: "chevron.right")
                                }
                                .font(.headline)
                            }
                            .accessibilityLabel(home.nextAction.buttonTitle)
                            .padding(.top, 8)
                        }
                    }
                }
            }

            DemoSection(title: "知识状态") {
                DemoCard {
                    if home.knowledgeSummary.isEmpty && home.weakest == nil {
                        emptyText("暂无知识状态")
                    } else {
                        VStack(spacing: 19) {
                            ForEach(visibleKnowledge(home), id: \.id) { point in
                                knowledgeRow(point, weakestID: home.weakest?.id)
                            }
                            if allKnowledge(home).count > 3 {
                                Button(showsAllKnowledge ? "收起" : "查看全部知识点") {
                                    showsAllKnowledge.toggle()
                                }
                                .font(.subheadline.weight(.semibold))
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }
            }

            DemoSection(title: "最近错题") {
                DemoCard {
                    if home.recentWrongQuestions.isEmpty {
                        emptyText("最近没有错题")
                    } else {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(Array(home.recentWrongQuestions.enumerated()), id: \.element.id) { index, question in
                                if index > 0 { Divider().padding(.vertical, 14) }
                                Button { onOpenWrongQuestion(question.id) } label: {
                                    VStack(alignment: .leading, spacing: 6) {
                                        Text("第 \(question.questionNumber) 题 · \(question.content)")
                                            .font(.headline)
                                            .foregroundStyle(.primary)
                                            .multilineTextAlignment(.leading)
                                            .fixedSize(horizontal: false, vertical: true)
                                        Text(question.errorLabel ?? question.knowledgePointName ?? "待复习")
                                            .font(DemoType.secondary)
                                            .foregroundStyle(DemoStyle.secondary)
                                    }
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }
            }

            // Recent learning stays quiet: it never competes with Next Step.
            DemoSection(title: "最近学习") {
                DemoCard {
                    if home.recentActivities.isEmpty {
                        emptyText("暂无最近学习记录")
                    } else {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(Array(home.recentActivities.enumerated()), id: \.offset) { index, activity in
                                if index > 0 { Divider().padding(.vertical, 14) }
                                HStack(alignment: .top, spacing: 12) {
                                    VStack(alignment: .leading, spacing: 5) {
                                        Text(activity.title).font(.headline)
                                        Text(activity.subtitle)
                                            .font(DemoType.secondary)
                                            .foregroundStyle(DemoStyle.secondary)
                                    }
                                    Spacer(minLength: 8)
                                    Text(activity.occurredAt, format: .dateTime.month().day())
                                        .font(DemoType.meta)
                                        .foregroundStyle(DemoStyle.secondary)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private func visibleKnowledge(_ home: HomeSnapshot) -> [HomeSnapshot.KnowledgeSummary] {
        let knowledge = allKnowledge(home)
        return showsAllKnowledge ? knowledge : Array(knowledge.prefix(3))
    }

    private func allKnowledge(_ home: HomeSnapshot) -> [HomeSnapshot.KnowledgeSummary] {
        guard let weakest = home.weakest else { return home.knowledgeSummary }
        return [weakest] + home.knowledgeSummary.filter { $0.id != weakest.id }
    }

    private func knowledgeRow(_ point: HomeSnapshot.KnowledgeSummary, weakestID: String?) -> some View {
        Button { onOpenKnowledge(point.id) } label: {
            VStack(spacing: 9) {
                HStack(alignment: .firstTextBaseline) {
                    Text(point.name).font(.headline)
                    Spacer(minLength: 8)
                    Text(point.mastery.demoPercent)
                        .font(DemoType.inlineMetric)
                        .foregroundStyle(DemoStyle.secondary)
                }
                MasteryBar(value: point.mastery, color: point.isWeak ? .orange : .blue)
                if point.id == weakestID {
                    Text("当前重点 · \(trendLabel(point.trend))")
                        .font(DemoType.meta)
                        .foregroundStyle(DemoStyle.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .buttonStyle(.plain)
    }

    private func trendLabel(_ trend: String) -> String {
        switch trend {
        case "improving": "正在提升"
        case "declining": "近期回落"
        case "stable": "保持稳定"
        default: "持续关注"
        }
    }

    private func emptyText(_ message: String) -> some View {
        Text(message).font(DemoType.secondary).foregroundStyle(DemoStyle.secondary)
    }

    private func perform(_ action: NextLearningAction) {
        switch HomeActionRoute(action) {
        case .tutor(let knowledgePointID): onStartTutor(knowledgePointID)
        case .wrongQuestion(let id): onOpenWrongQuestion(id)
        case .practice(let knowledgePointID): onStartPractice(knowledgePointID)
        case .knowledge(let id): onOpenKnowledge(id)
        case .none: break
        }
    }
}
