import SwiftUI

struct AnalysisResultView: View {
    let result: HomeworkAnalysisResult
    let onStartTutor: (String?) -> Void
    let onOpenWrongQuestion: (String) -> Void
    let onReturnHome: () -> Void

    @State private var showsCorrectQuestions = false
    @State private var notice: Notice?

    private var presentation: AnalysisResultPresentation { AnalysisResultPresentation(result: result) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 17) {
                DemoPageHeader(title: "分析完成", subtitle: "这次作答与学习状态已整理好。")
                summarySection

                if !presentation.attentionQuestions.isEmpty {
                    DemoSectionTitle(title: "需要关注").padding(.top, 15)
                    ForEach(presentation.attentionQuestions, id: \.id) { question in
                        questionCard(question)
                    }
                }

                if !presentation.correctQuestions.isEmpty {
                    correctQuestionsSection
                }

                if !result.knowledgeChanges.isEmpty {
                    DemoSectionTitle(title: "知识状态变化").padding(.top, 15)
                    DemoCard {
                        VStack(alignment: .leading, spacing: 17) {
                            ForEach(Array(result.knowledgeChanges.enumerated()), id: \.offset) { index, change in
                                if index > 0 { Divider() }
                                knowledgeChangeRow(change)
                            }
                        }
                    }
                }

                if !result.newWrongQuestions.isEmpty {
                    DemoSectionTitle(title: "已加入错题").padding(.top, 15)
                    DemoCard {
                        VStack(alignment: .leading, spacing: 15) {
                            Text("\(result.newWrongQuestions.count) 道题已留待复习")
                                .foregroundStyle(DemoStyle.secondary)
                            ForEach(Array(result.newWrongQuestions.enumerated()), id: \.offset) { index, wrong in
                                if index > 0 { Divider() }
                                Button { onOpenWrongQuestion(wrong.id) } label: {
                                    VStack(alignment: .leading, spacing: 5) {
                                        Text("第 \(wrong.questionNumber) 题 · \(wrong.content)")
                                            .foregroundStyle(.primary)
                                            .multilineTextAlignment(.leading)
                                        if let label = wrong.errorLabel {
                                            Text(label).font(.subheadline).foregroundStyle(DemoStyle.secondary)
                                        }
                                    }
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                }
                            }
                        }
                    }
                }

                if let action = result.nextAction {
                    DemoSectionTitle(title: "接下来").padding(.top, 15)
                    DemoCard {
                        VStack(alignment: .leading, spacing: 13) {
                            Text(action.title).font(.title3.bold())
                            Text(action.reason).foregroundStyle(DemoStyle.secondary)
                            if HomeActionRoute(action) != .none {
                                Button(action.buttonTitle) { perform(action) }
                                    .font(.headline)
                                    .padding(.top, 5)
                            }
                        }
                    }
                }

                Button("返回首页", action: onReturnHome)
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .padding(.top, 8)
            }
            .padding(.horizontal, 20)
            .padding(.top, 26)
            .padding(.bottom, 40)
        }
        .background(DemoStyle.background)
        .navigationTitle("本次分析")
        .navigationBarTitleDisplayMode(.inline)
        .alert(notice?.title ?? "", isPresented: Binding(
            get: { notice != nil }, set: { if !$0 { notice = nil } }
        )) {
            Button("好") { notice = nil }
        } message: {
            Text(notice?.message ?? "")
        }
    }

    private var summarySection: some View {
        DemoCard {
            VStack(alignment: .leading, spacing: 16) {
                Text("本次分析").font(.headline).foregroundStyle(DemoStyle.secondary)
                Text("\(presentation.totalCount) 道题").font(.largeTitle.bold())
                HStack(spacing: 16) {
                    countLabel(result.correctCount, title: "正确")
                    countLabel(result.wrongCount, title: "需关注")
                    countLabel(result.partialCount, title: "部分正确")
                    countLabel(result.unknownCount, title: "待确认")
                }
                if presentation.attentionQuestions.isEmpty {
                    Text("本次没有需要关注的题目")
                        .font(.subheadline)
                        .foregroundStyle(DemoStyle.secondary)
                }
            }
        }
    }

    private func countLabel(_ count: Int, title: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("\(count)").font(.title3.bold()).monospacedDigit()
            Text(title).font(.caption).foregroundStyle(DemoStyle.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(count) 道\(title)")
    }

    private func questionCard(_ question: HomeworkAnalysisResult.Question) -> some View {
        DemoCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    Text("第 \(question.number) 题").font(.headline)
                    Spacer()
                    Text(presentation.label(for: question))
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(question.correctness == "unknown" ? DemoStyle.secondary : .orange)
                }
                Text(question.content).font(.body).fixedSize(horizontal: false, vertical: true)

                if !question.choices.isEmpty {
                    VStack(alignment: .leading, spacing: 9) {
                        ForEach(question.choices.keys.sorted(), id: \.self) { key in
                            HStack(alignment: .firstTextBaseline, spacing: 7) {
                                Text("\(key).")
                                    .fontWeight(.semibold)
                                Text(question.choices[key] ?? "")
                                Spacer(minLength: 3)
                                if key == question.studentAnswer {
                                    Text("你的选择").font(.caption).foregroundStyle(.blue)
                                }
                                if key == question.correctAnswer {
                                    Text("参考答案").font(.caption).foregroundStyle(.green)
                                }
                            }
                            .font(.subheadline)
                            .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(.vertical, 3)
                }

                answerRow("你的答案", value: question.studentAnswer ?? "未提供")
                answerRow("参考答案", value: question.correctAnswer ?? "尚未确认")

                if !question.diagnosis.isEmpty {
                    Divider()
                    Text(question.diagnosis)
                        .font(.body)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !question.knowledgePoints.isEmpty {
                    VStack(alignment: .leading, spacing: 7) {
                        Text("相关知识点").font(.caption).foregroundStyle(DemoStyle.secondary)
                        ForEach(Array(question.knowledgePoints.enumerated()), id: \.offset) { _, point in
                            Button(point.name) { notice = .knowledgePoint(point.id) }
                                .multilineTextAlignment(.leading)
                        }
                    }
                }
            }
        }
    }

    private func answerRow(_ title: String, value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            Text(title).foregroundStyle(DemoStyle.secondary)
                .frame(width: 72, alignment: .leading)
            Text(value).frame(maxWidth: .infinity, alignment: .leading)
        }
        .font(.subheadline)
    }

    private var correctQuestionsSection: some View {
        DemoCard {
            DisclosureGroup("回答正确 · \(presentation.correctQuestions.count) 道题", isExpanded: $showsCorrectQuestions) {
                VStack(alignment: .leading, spacing: 13) {
                    ForEach(presentation.correctQuestions, id: \.id) { question in
                        Divider()
                        Text("第 \(question.number) 题 · \(question.content)")
                            .font(.subheadline)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.top, 10)
            }
        }
    }

    private func knowledgeChangeRow(_ change: KnowledgeChange) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Button(change.summary) { notice = .knowledgePoint(change.knowledgePointID) }
                .font(.headline)
                .multilineTextAlignment(.leading)
            HStack(spacing: 11) {
                if let before = change.beforeMastery, let after = change.afterMastery {
                    Text("\(before.demoPercent) → \(after.demoPercent)")
                        .font(.title3.weight(.semibold))
                        .monospacedDigit()
                }
                if let delta = presentation.changeLabel(change) {
                    Text(delta)
                        .font(.subheadline)
                        .foregroundStyle(DemoStyle.secondary)
                }
            }
        }
    }

    private func perform(_ action: NextLearningAction) {
        switch HomeActionRoute(action) {
        case .tutor(let id): onStartTutor(id)
        case .wrongQuestion(let id): onOpenWrongQuestion(id)
        case .practice: notice = .practice
        case .none: break
        }
    }

    private enum Notice {
        case knowledgePoint(String), practice

        var title: String {
            switch self {
            case .knowledgePoint: "知识点详情即将开放"
            case .practice: "针对练习即将开放"
            }
        }

        var message: String {
            switch self {
            case .knowledgePoint: "知识点详情将在后续阶段接入。"
            case .practice: "练习功能将在后续阶段接入。"
            }
        }
    }
}
