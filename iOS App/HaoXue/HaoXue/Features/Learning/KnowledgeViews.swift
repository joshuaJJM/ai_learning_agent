import SwiftUI

struct KnowledgeOverviewView: View {
    @Environment(\.dismiss) private var dismiss
    let model: KnowledgeOverviewViewModel
    let onOpenKnowledge: (String) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DemoMetrics.sectionGap) {
                DemoPageHeader(title: "知识状态", subtitle: "看看每个知识点的理解与学习证据。")
                switch model.phase {
                case .idle, .loading:
                    ProgressView("正在获取知识状态")
                        .frame(maxWidth: .infinity).padding(.top, 90)
                case .failed:
                    failure
                case .loaded:
                    if let overview = model.overview {
                        if overview.nodes.isEmpty {
                            Text("暂无知识状态")
                                .foregroundStyle(DemoStyle.secondary)
                        } else {
                            DemoCard {
                                VStack(spacing: 17) {
                                    ForEach(Array(overview.nodes.enumerated()), id: \.element.id) { index, node in
                                        if index > 0 { Divider() }
                                        KnowledgeNodeRow(node: node, depth: 0,
                                                         weakestIDs: overview.weakestIDs,
                                                         onOpen: onOpenKnowledge)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .padding(.horizontal, DemoMetrics.pagePadding)
            .padding(.top, DemoMetrics.pageTopPadding)
            .padding(.bottom, DemoMetrics.pageBottomPadding)
        }
        .background(DemoStyle.background)
        .navigationTitle("知识状态")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("关闭") { dismiss() } } }
        .task { await model.loadIfNeeded() }
        .refreshable { await model.refresh() }
    }

    private var failure: some View {
        VStack(spacing: 14) {
            Text(model.errorMessage ?? "暂时无法获取知识状态")
                .foregroundStyle(DemoStyle.secondary)
            Button("重新加载") { Task { await model.refresh() } }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 90)
    }
}

private struct KnowledgeNodeRow: View {
    let node: KnowledgeOverview.Node
    let depth: Int
    let weakestIDs: Set<String>
    let onOpen: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Button { onOpen(node.id) } label: {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(node.name).font(.headline).multilineTextAlignment(.leading)
                        Spacer(minLength: 8)
                        Text(node.mastery.demoPercent).font(DemoType.inlineMetric)
                    }
                    .foregroundStyle(.primary)
                    MasteryBar(value: node.mastery,
                               color: weakestIDs.contains(node.id) ? .orange : .blue)
                    HStack {
                        if weakestIDs.contains(node.id) {
                            Text("当前重点")
                        } else if let trend = KnowledgeEvidencePresentation.trendLabel(node.trend) {
                            Text(trend)
                        }
                        Spacer()
                        Text("\(node.evidenceCount) 条学习证据")
                    }
                    .font(DemoType.meta)
                    .foregroundStyle(DemoStyle.secondary)
                }
            }
            .buttonStyle(.plain)
            ForEach(node.children, id: \.id) { child in
                KnowledgeNodeRow(node: child, depth: depth + 1,
                                 weakestIDs: weakestIDs, onOpen: onOpen)
                    .padding(.leading, CGFloat(min(depth + 1, 3) * 14))
            }
        }
    }
}

struct KnowledgeDetailView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var model: KnowledgeDetailViewModel
    let onOpenWrongQuestion: (String) -> Void
    let onStartTutor: (String) -> Void

    init(id: String, provider: any KnowledgeDataProviding,
         onOpenWrongQuestion: @escaping (String) -> Void,
         onStartTutor: @escaping (String) -> Void) {
        _model = State(initialValue: KnowledgeDetailViewModel(id: id, provider: provider))
        self.onOpenWrongQuestion = onOpenWrongQuestion
        self.onStartTutor = onStartTutor
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DemoMetrics.sectionGap) {
                switch model.phase {
                case .idle, .loading:
                    ProgressView("正在获取知识点详情")
                        .frame(maxWidth: .infinity).padding(.top, 90)
                case .failed:
                    failure
                case .loaded:
                    if let detail = model.detail { content(detail) }
                }
            }
            .padding(.horizontal, DemoMetrics.pagePadding)
            .padding(.top, DemoMetrics.pageTopPadding)
            .padding(.bottom, DemoMetrics.pageBottomPadding)
        }
        .background(DemoStyle.background)
        .navigationTitle("知识点详情")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("关闭") { dismiss() } } }
        .task { await model.loadIfNeeded() }
        .refreshable { await model.refresh() }
    }

    private var failure: some View {
        VStack(spacing: 14) {
            Text(model.errorMessage ?? "暂时无法获取知识点详情")
                .foregroundStyle(DemoStyle.secondary)
            Button("重新加载") { Task { await model.refresh() } }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 90)
    }

    private func content(_ detail: KnowledgePointDetail) -> some View {
        VStack(alignment: .leading, spacing: DemoMetrics.sectionGap) {
            VStack(alignment: .leading, spacing: 11) {
                Text(detail.name).font(DemoType.pageTitle)
                    .fixedSize(horizontal: false, vertical: true)
                if !detail.description.isEmpty {
                    Text(detail.description).foregroundStyle(DemoStyle.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(detail.mastery.demoPercent).font(DemoType.metric)
                    Text("当前掌握度").font(DemoType.secondary).foregroundStyle(DemoStyle.secondary)
                    Spacer()
                }
                MasteryBar(value: detail.mastery,
                           color: detail.trend == "declining" ? .orange : .blue)
                if let trend = KnowledgeEvidencePresentation.trendLabel(detail.trend) {
                    Text(trend).font(DemoType.secondary).foregroundStyle(DemoStyle.secondary)
                }
            }
            DemoSection(title: "为什么是 \(detail.mastery.demoPercent)？") {
                if detail.masteryExplanation.isEmpty {
                    Text("学习证据还比较少，暂时没有更详细的说明。")
                        .foregroundStyle(DemoStyle.secondary)
                } else {
                    Text(detail.masteryExplanation)
                        .font(.body)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            evidenceSection(detail)
            relatedSection
            if let action = detail.recommendedAction,
               case .tutor = HomeActionRoute(action) {
                DemoSection(title: "接下来") {
                    Text(action.reason).foregroundStyle(DemoStyle.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Button(action.buttonTitle) { onStartTutor(detail.id) }
                        .buttonStyle(DemoPrimaryButtonStyle())
                        .padding(.top, 4)
                }
            }
        }
    }

    private func evidenceSection(_ detail: KnowledgePointDetail) -> some View {
        DemoSection(title: "学习证据") {
            if detail.evidence.isEmpty {
                Text("学习证据还比较少，完成更多学习后，这里会形成更完整的记录。")
                    .foregroundStyle(DemoStyle.secondary)
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(detail.evidence.enumerated()), id: \.offset) { index, evidence in
                        if index > 0 { Divider().padding(.vertical, 12) }
                        evidenceRow(evidence)
                    }
                }
            }
        }
    }

    private func evidenceRow(_ evidence: KnowledgePointDetail.Evidence) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .firstTextBaseline) {
                Text(KnowledgeEvidencePresentation.sourceLabel(evidence.sourceType))
                    .font(DemoType.secondary.weight(.semibold))
                Spacer(minLength: 8)
                Text(evidence.createdAt, format: .dateTime.month().day())
                    .font(DemoType.meta).foregroundStyle(DemoStyle.secondary)
            }
            Text(KnowledgeEvidencePresentation.resultLabel(evidence.result))
                .font(DemoType.secondary)
                .foregroundStyle(evidence.result == "incorrect" ? .orange : DemoStyle.secondary)
            if evidence.result == "incorrect" || evidence.result == "partial" {
                if let label = evidence.errorLabel, !label.isEmpty {
                    Text(label).font(DemoType.secondary).foregroundStyle(DemoStyle.secondary)
                }
            }
            if let detail = evidence.detail, !detail.isEmpty {
                Text(detail).font(DemoType.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let answer = evidence.answerExcerpt, !answer.isEmpty {
                Text("当时的答案：\(answer)").font(DemoType.meta)
                    .foregroundStyle(DemoStyle.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var relatedSection: some View {
        DemoSection(title: "相关错题") {
            if model.isLoadingRelated {
                ProgressView("正在获取相关错题")
            } else if let error = model.relatedError {
                Text(error).foregroundStyle(DemoStyle.secondary)
            } else if model.relatedWrongQuestions.isEmpty {
                Text("暂无相关错题").foregroundStyle(DemoStyle.secondary)
            } else {
                ForEach(model.relatedWrongQuestions, id: \.id) { wrong in
                    Button { onOpenWrongQuestion(wrong.id) } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 5) {
                                Text("第 \(wrong.questionNumber) 题 · \(wrong.content)")
                                    .foregroundStyle(.primary).lineLimit(2)
                                    .multilineTextAlignment(.leading)
                                if let label = wrong.errorLabel {
                                    Text(label).font(DemoType.meta).foregroundStyle(DemoStyle.secondary)
                                }
                            }
                            Spacer(minLength: 8)
                            Image(systemName: "chevron.right")
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(DemoStyle.secondary)
                        }
                    }
                    .buttonStyle(.plain)
                    if wrong.id != model.relatedWrongQuestions.last?.id { Divider() }
                }
            }
        }
    }
}
