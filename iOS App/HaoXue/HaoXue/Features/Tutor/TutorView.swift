import SwiftUI

struct TutorView: View {
    let store: DemoScenarioStore
    let onClose: () -> Void
    @State private var model: TutorViewModel
    @State private var showingScratchpad = false

    init(store: DemoScenarioStore, provider: any QuestionProvider, onClose: @escaping () -> Void) {
        self.store = store
        self.onClose = onClose
        _model = State(initialValue: TutorViewModel(provider: provider))
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button(action: onClose) { Image(systemName: "xmark") }
                    .frame(width: DemoMetrics.iconButtonSize, height: DemoMetrics.iconButtonSize, alignment: .leading)
                    .accessibilityLabel("关闭课程")
                Spacer()
                Text(store.lessonTitle).font(.headline).lineLimit(1)
                Spacer()
                Button("草稿本") { showingScratchpad = true }
                    .frame(height: DemoMetrics.iconButtonSize)
                    .accessibilityLabel("草稿本")
            }
            .padding(.horizontal, DemoMetrics.sessionPadding)
            .padding(.vertical, 8)
            .background(DemoStyle.background)
            .overlay(alignment: .bottom) { Divider().opacity(0.3) }

            ScrollView {
                switch model.session.state {
                case .completed: completionContent
                case .loading: ProgressView("正在加载题目")
                        .frame(maxWidth: .infinity).padding(.top, 100)
                case .error: errorContent
                default: questionContent
                }
            }
            .background(Color(uiColor: .systemBackground))
            .safeAreaInset(edge: .bottom) {
                if model.session.state != .loading && model.session.state != .error {
                    footer
                }
            }
        }
        .background(.background)
        .task { await model.loadQuestion() }
        .sheet(isPresented: $showingScratchpad) {
            ScratchpadView(drawing: $model.drawing)
                .presentationDetents([.large])
        }
    }

    private var footer: some View {
        VStack(spacing: 17) {
            Button(action: primaryAction) {
                Text(primaryTitle)
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
            }
            .foregroundStyle(.white)
            .background(.blue, in: Capsule())
            .disabled(model.session.state == .answering && model.session.selectedAnswer == nil)
            .opacity(model.session.state == .answering && model.session.selectedAnswer == nil ? 0.5 : 1)
            .accessibilityLabel(primaryTitle)
            if model.session.state != .completed {
                HStack {
                    Text(store.lessonTitle)
                    Spacer()
                    Text(model.session.displayedMastery.demoPercent).font(.headline)
                }
                .font(.subheadline)
                .foregroundStyle(DemoStyle.secondary)
                MasteryBar(value: model.session.displayedMastery)
                Text("课程进度 · \(model.session.progressText)")
                    .font(.caption).foregroundStyle(DemoStyle.secondary)
            }
        }
        .padding(.horizontal, 22)
        .padding(.top, 16)
        .padding(.bottom, 10)
        .background(DemoStyle.background)
        .overlay(alignment: .top) { Divider().opacity(0.3) }
    }

    private var questionContent: some View {
        VStack(alignment: .leading, spacing: 20) {
            if let question = model.session.currentQuestion {
                Text("理解检查")
                    .font(DemoType.secondary.weight(.bold)).foregroundStyle(DemoStyle.secondary)
                Text(question.lead).font(.title2.bold())
                    .fixedSize(horizontal: false, vertical: true)
                Text(question.expression)
                    .font(.title.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 24)
                    .background(DemoStyle.background,
                                in: RoundedRectangle(cornerRadius: DemoMetrics.controlCornerRadius))
                Text(question.prompt).font(.title3.bold())
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(question.choices, id: \.id) { choice in
                    choiceButton(choice, question: question)
                }
                Text("或者")
                    .font(.subheadline).foregroundStyle(DemoStyle.secondary)
                    .frame(maxWidth: .infinity)
                Text("写下你的想法……")
                    .foregroundStyle(DemoStyle.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(17)
                    .background(DemoStyle.background,
                                in: RoundedRectangle(cornerRadius: DemoMetrics.controlCornerRadius))
                if model.session.hasSubmitted { feedbackContent(question) }
            }
        }
        .padding(.horizontal, DemoMetrics.sessionPadding)
        .padding(.top, DemoMetrics.sessionContentTop)
        .padding(.bottom, 24)
    }

    private func choiceButton(_ choice: TutorChoice, question: TutorQuestion) -> some View {
        let submitted = model.session.hasSubmitted
        let isCorrect = submitted && choice.id == question.correctAnswer
        let isWrong = submitted && choice.id == model.session.selectedAnswer && !isCorrect
        let isSelected = !submitted && choice.id == model.session.selectedAnswer
        let emphasis: DemoChoiceRow.Emphasis = isCorrect ? .correct
            : (isWrong ? .wrong : (isSelected ? .selected : .idle))
        return DemoChoiceRow(key: choice.id.rawValue, text: choice.text, emphasis: emphasis) {
            model.select(choice.id)
        }
        .disabled(submitted)
    }

    private func feedbackContent(_ question: TutorQuestion) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(model.session.selectedAnswer == question.correctAnswer ? "回答正确" : "回答错误",
                  systemImage: model.session.selectedAnswer == question.correctAnswer
                    ? "checkmark.circle.fill" : "xmark.circle.fill")
                .font(.headline)
            if model.session.state == .submittedWrong || model.session.state == .showingExplanation {
                Text(question.explanation)
            }
            if model.session.state == .submittedCorrect {
                Button("查看解析") { model.showExplanation() }
                    .font(.subheadline.weight(.semibold))
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.blue.opacity(0.08),
                    in: RoundedRectangle(cornerRadius: DemoMetrics.controlCornerRadius))
    }

    private var completionContent: some View {
        VStack(alignment: .leading, spacing: 22) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(.largeTitle, design: .default)).foregroundStyle(.green)
            Text("学习完成").font(.largeTitle.bold())
            Text(store.lessonTitle).font(.title2)
            Text("\(model.session.startingMastery.demoPercent) → \(model.session.displayedMastery.demoPercent)")
                .font(DemoType.metric)
                .foregroundStyle(.green)
            Text("本次重点提升").foregroundStyle(DemoStyle.secondary)
            Text("导数符号与函数单调性的关系").font(.title3.bold())
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, DemoMetrics.sessionPadding)
        .padding(.top, 85)
    }

    private var errorContent: some View {
        VStack(spacing: 16) {
            Text("加载失败").font(.title3.bold())
            Button("重试") { Task { await model.retry() } }
        }
        .frame(maxWidth: .infinity).padding(.top, 100)
    }

    private var primaryTitle: String {
        switch model.session.state {
        case .answering: "提交答案"
        case .submittedCorrect, .submittedWrong, .showingExplanation: "下一题"
        case .completed: "完成学习"
        case .loading, .error: ""
        }
    }

    private func primaryAction() {
        switch model.session.state {
        case .answering: model.submit()
        case .submittedCorrect, .submittedWrong, .showingExplanation:
            Task { await model.advance() }
        case .completed:
            store.finishLesson()
            onClose()
        case .loading, .error: break
        }
    }
}
