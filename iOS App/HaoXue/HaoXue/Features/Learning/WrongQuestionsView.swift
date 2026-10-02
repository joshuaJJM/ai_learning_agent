import SwiftUI

struct WrongQuestionsView: View {
    let model: WrongQuestionsListViewModel
    let onOpen: (String) -> Void
    let onOpenKnowledgeOverview: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                DemoPageHeader(title: "学习", subtitle: "从已有的学习证据找到下一步。")
                Button(action: onOpenKnowledgeOverview) {
                    DemoCard {
                        HStack {
                            VStack(alignment: .leading, spacing: 5) {
                                Text("知识状态").font(.headline).foregroundStyle(.primary)
                                Text("查看掌握度与学习证据")
                                    .font(.subheadline).foregroundStyle(DemoStyle.secondary)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                        }
                    }
                }
                .buttonStyle(.plain)
                DemoSectionTitle(title: "错题")
                switch model.phase {
                case .idle, .loading:
                    ProgressView("正在获取错题")
                        .frame(maxWidth: .infinity)
                        .padding(.top, 90)
                case .failed:
                    VStack(spacing: 15) {
                        Text(model.errorMessage ?? "暂时无法获取错题")
                            .foregroundStyle(DemoStyle.secondary)
                        Button("重新加载") { Task { await model.refresh() } }
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.top, 90)
                case .loaded:
                    if model.items.isEmpty {
                        DemoCard {
                            VStack(alignment: .leading, spacing: 10) {
                                Text("暂无错题").font(.headline)
                                Text("完成作业分析后，需要关注的题目会出现在这里。")
                                    .foregroundStyle(DemoStyle.secondary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    } else {
                        ForEach(model.items, id: \.id) { question in
                            Button { onOpen(question.id) } label: { row(question) }
                                .buttonStyle(.plain)
                        }
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 26)
            .padding(.bottom, 36)
        }
        .background(DemoStyle.background)
        .refreshable { await model.refresh() }
        .task { await model.loadIfNeeded() }
    }

    private func row(_ question: WrongQuestionSummary) -> some View {
        DemoCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text("第 \(question.questionNumber) 题").font(.headline)
                    Spacer(minLength: 10)
                    Text(WrongQuestionStatus.label(question.status))
                        .font(.caption.weight(.medium))
                        .foregroundStyle(DemoStyle.secondary)
                }
                Text(question.content)
                    .font(.body)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
                if let name = question.knowledgePointName {
                    Text(name).font(.subheadline).foregroundStyle(DemoStyle.secondary)
                        .multilineTextAlignment(.leading)
                }
                HStack {
                    if let label = question.errorLabel {
                        Text(label).font(.caption.weight(.medium))
                            .foregroundStyle(.orange)
                    }
                    Spacer()
                    Text(question.createdAt, format: .dateTime.year().month().day())
                        .font(.caption)
                        .foregroundStyle(DemoStyle.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct WrongQuestionDetailView: View {
    @Environment(\.dismiss) private var dismiss
    let onStartTutor: (String) -> Void
    let onOpenKnowledge: (String) -> Void
    let onChanged: () -> Void
    @State private var model: WrongQuestionDetailViewModel

    init(id: String, provider: any WrongQuestionDataProviding,
         onStartTutor: @escaping (String) -> Void,
         onOpenKnowledge: @escaping (String) -> Void,
         onChanged: @escaping () -> Void) {
        _model = State(initialValue: WrongQuestionDetailViewModel(id: id, provider: provider))
        self.onStartTutor = onStartTutor
        self.onOpenKnowledge = onOpenKnowledge
        self.onChanged = onChanged
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                switch model.phase {
                case .idle, .loading:
                    ProgressView("正在获取错题详情")
                        .frame(maxWidth: .infinity)
                        .padding(.top, 90)
                case .failed:
                    VStack(spacing: 15) {
                        Text(model.errorMessage ?? "暂时无法获取错题详情")
                            .foregroundStyle(DemoStyle.secondary)
                        Button("重新加载") { Task { await model.refresh() } }
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.top, 90)
                case .loaded:
                    if let detail = model.detail { content(detail) }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 24)
            .padding(.bottom, 36)
        }
        .background(DemoStyle.background)
        .navigationTitle("错题详情")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("关闭") { dismiss() }
            }
        }
        .task { await model.loadIfNeeded() }
        .refreshable { await model.refresh() }
        .alert("更新失败", isPresented: Binding(get: { model.updateError != nil },
                                             set: { if !$0 { model.clearUpdateError() } })) {
            Button("好") { model.clearUpdateError() }
        } message: {
            Text(model.updateError ?? "请稍后重试")
        }
    }

    private func content(_ detail: WrongQuestionDetail) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text("第 \(detail.summary.questionNumber) 题").font(.title2.bold())
                Spacer()
                Text(WrongQuestionStatus.label(detail.summary.status))
                    .font(.subheadline)
                    .foregroundStyle(DemoStyle.secondary)
            }
            DemoCard {
                VStack(alignment: .leading, spacing: 16) {
                    Text(detail.summary.content).font(.body)
                        .fixedSize(horizontal: false, vertical: true)
                    if !detail.choices.isEmpty {
                        Divider()
                        ForEach(detail.choices.keys.sorted(), id: \.self) { key in
                            HStack(alignment: .top, spacing: 9) {
                                Text("\(key). ").fontWeight(.semibold)
                                Text(detail.choices[key] ?? "")
                            }
                            .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            DemoCard {
                VStack(alignment: .leading, spacing: 15) {
                    answer("你的答案", detail.studentAnswer ?? "未提供")
                    Divider()
                    answer("正确答案", detail.correctAnswer ?? "尚未提供")
                }
            }
            DemoSectionTitle(title: "问题在哪里")
            DemoCard {
                VStack(alignment: .leading, spacing: 12) {
                    if let label = detail.summary.errorLabel {
                        Text(label).font(.subheadline.weight(.semibold)).foregroundStyle(.orange)
                    }
                    Text(detail.diagnosis.isEmpty ? "暂无诊断" : detail.diagnosis)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if let explanation = detail.explanation, !explanation.isEmpty {
                DemoSectionTitle(title: "解题说明")
                DemoCard {
                    Text(explanation).frame(maxWidth: .infinity, alignment: .leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if let name = detail.summary.knowledgePointName {
                DemoSectionTitle(title: "相关知识点")
                DemoCard {
                    if let id = detail.summary.knowledgePointID {
                        Button {
                            onOpenKnowledge(id)
                        } label: {
                            HStack {
                                Text(name).multilineTextAlignment(.leading)
                                Spacer(minLength: 8)
                                Image(systemName: "chevron.right")
                            }
                        }
                    } else {
                        Text(name)
                    }
                }
            }
            HStack {
                if let source = detail.sourceName, !source.isEmpty {
                    Text("来源：\(source)")
                } else if detail.sourceType == "homework" {
                    Text("来源：作业分析")
                }
                Spacer()
                Text(detail.summary.createdAt, format: .dateTime.year().month().day())
            }
            .font(.caption)
            .foregroundStyle(DemoStyle.secondary)
            if detail.canStartTutor {
                Button("针对这个问题学习") { onStartTutor(detail.summary.id) }
                    .buttonStyle(.borderedProminent)
                    .frame(maxWidth: .infinity)
            }
            if detail.summary.status == "open" {
                Button("标记为已解决") { Task { await changeStatus("resolved") } }
                    .disabled(model.isUpdating)
                    .frame(maxWidth: .infinity)
            } else if detail.summary.status == "resolved" {
                Button("继续关注") { Task { await changeStatus("open") } }
                    .disabled(model.isUpdating)
                    .frame(maxWidth: .infinity)
            }
        }
    }

    private func answer(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.caption).foregroundStyle(DemoStyle.secondary)
            Text(value).font(.body).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func changeStatus(_ status: String) async {
        await model.updateStatus(status)
        if model.lastStatusUpdateSucceeded { onChanged() }
    }
}
