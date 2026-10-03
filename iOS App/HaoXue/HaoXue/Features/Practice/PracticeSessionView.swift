import SwiftUI

/// Live practice: answer → backend verdict → explanation → 下一题 / 完成练习.
/// Phase 6D owns everything after “完成练习” (Home refresh, next action, closed loop).
struct PracticeSessionView: View {
    let onSessionReady: (String) -> Void
    let onFinish: (PracticeAnswerOutcome) -> Void
    let onClose: () -> Void
    @State private var model: PracticeSessionViewModel
    @State private var showingScratchpad = false
    @State private var actionTask: Task<Void, Never>?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(provider: any PracticeDataProviding, existingSessionID: String? = nil,
         knowledgePointID: String? = nil, createKey: IdempotencyKey? = nil,
         onSessionReady: @escaping (String) -> Void = { _ in },
         onFinish: @escaping (PracticeAnswerOutcome) -> Void = { _ in },
         onClose: @escaping () -> Void) {
        self.onSessionReady = onSessionReady
        self.onFinish = onFinish
        self.onClose = onClose
        _model = State(initialValue: PracticeSessionViewModel(
            provider: provider, existingSessionID: existingSessionID,
            knowledgePointID: knowledgePointID, createKey: createKey))
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button {
                    actionTask?.cancel()
                    model.cancel()
                    onClose()
                } label: { Image(systemName: "xmark") }
                    .frame(width: DemoMetrics.iconButtonSize, height: DemoMetrics.iconButtonSize, alignment: .leading)
                    .accessibilityLabel("关闭练习")
                Spacer()
                Text("针对性练习").font(.headline).lineLimit(1)
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
                switch model.phase {
                case .idle, .loading:
                    ProgressView("正在准备针对性练习…")
                        .frame(maxWidth: .infinity).padding(.top, 100)
                case .failed(let message):
                    loadErrorContent(message)
                case .answering:
                    if let question = model.question {
                        questionContent(question)
                    } else {
                        emptyContent
                    }
                case .submitting:
                    submittingContent
                case .submitFailed(let message):
                    submitErrorContent(message)
                case .result(let outcome):
                    resultContent(outcome)
                        .transition(reduceMotion ? .opacity
                                    : .offset(y: 10).combined(with: .opacity))
                }
            }
            .background(Color(uiColor: .systemBackground))
            .animation(DemoMotion.resolved(reduceMotion, DemoMotion.standard), value: model.phase)
            .safeAreaInset(edge: .bottom) { footer }
        }
        .onAppear { actionTask = Task { await model.loadIfNeeded() } }
        .onDisappear {
            actionTask?.cancel()
            model.cancel()
        }
        .onChange(of: model.session?.id) { _, id in
            if let id { onSessionReady(id) }
        }
        .sheet(isPresented: $showingScratchpad) {
            ScratchpadView(drawing: $model.drawing)
                .presentationDetents([.large])
        }
    }

    // MARK: - Question

    private func questionContent(_ question: PracticeQuestion) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            contextHeader
            Text("第 \(model.progressText) 题")
                .font(.subheadline)
                .foregroundStyle(DemoStyle.secondary)
                .accessibilityIdentifier("practice-progress")
            SafeMathText(question.stem)
                .font(.title3.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("practice-question-stem")
            VStack(spacing: 10) {
                ForEach(question.choices) { choice in choiceButton(choice) }
            }
        }
        .padding(.horizontal, DemoMetrics.sessionPadding)
        .padding(.top, DemoMetrics.sessionContentTop)
        .padding(.bottom, 24)
    }

    private var contextHeader: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("针对性练习")
                .font(.subheadline.bold()).foregroundStyle(DemoStyle.secondary)
            if let title = model.contextTitle {
                Text(title).font(.title3.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// Selection is local presentation state: no verdict, no colour, no mastery.
    private func choiceButton(_ choice: PracticeChoice) -> some View {
        let selected = model.selectedChoiceKey == choice.key
        return DemoChoiceRow(key: choice.key, text: choice.text,
                             emphasis: selected ? .selected : .idle,
                             dimmed: model.selectedChoiceKey != nil && !selected) {
            model.select(choice.key)
        }
    }

    // MARK: - Result

    private func resultContent(_ outcome: PracticeAnswerOutcome) -> some View {
        VStack(alignment: .leading, spacing: 22) {
            Label(outcome.isCorrect ? "回答正确" : "再看看这里",
                  systemImage: outcome.isCorrect ? "checkmark.circle.fill"
                                                 : "exclamationmark.circle.fill")
                .font(.title3.bold())
                .foregroundStyle(outcome.isCorrect ? Color.green : Color.orange)
                .accessibilityIdentifier("practice-result-correctness")

            VStack(alignment: .leading, spacing: 8) {
                if let selected = model.submission?.draft.selectedKey {
                    answerRow("你的答案", selected)
                }
                answerRow("正确答案", outcome.correctAnswer)
            }
            .padding(.vertical, 12)
            .padding(.horizontal, 16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(DemoStyle.background,
                        in: RoundedRectangle(cornerRadius: DemoMetrics.controlCornerRadius))

            if let explanation = outcome.explanation, !explanation.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    Text("解析").font(.headline)
                    SafeMathText(explanation)
                        .font(.body)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("practice-result-explanation")
            }

            if !outcome.knowledgeChanges.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    Text("学习状态变化").font(.headline)
                    ForEach(Array(outcome.knowledgeChanges.enumerated()), id: \.offset) { _, change in
                        HStack(alignment: .firstTextBaseline, spacing: 12) {
                            Text(change.summary)
                                .font(.subheadline)
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 8)
                            if let before = change.beforeMastery, let after = change.afterMastery {
                                Text("\(before.demoPercent) → \(after.demoPercent)")
                                    .font(.subheadline.weight(.semibold))
                                    .demoNumberTransition(after, reduceMotion: reduceMotion)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("practice-result-knowledge-changes")
            }

            if let tag = outcome.tagChange, !tag.tags.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("薄弱特征更新").font(.headline)
                    // v2: one score change per tag (no single ±1 delta any more).
                    let changes = tag.tags.compactMap { name in
                        tag.delta(for: name).map { (name: name, delta: $0) }
                    }
                    if changes.isEmpty {
                        Text(tag.tags.joined(separator: "、"))
                            .font(.subheadline)
                            .foregroundStyle(DemoStyle.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    } else {
                        ForEach(Array(changes.enumerated()), id: \.offset) { _, change in
                            Text("\(change.name) · \(change.delta > 0 ? "+" : "")\(change.delta)")
                                .font(.subheadline)
                                .foregroundStyle(DemoStyle.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            Text("已完成 \(outcome.answered) / \(outcome.total) 题 · 答对 \(outcome.correct) 题")
                .font(.subheadline)
                .foregroundStyle(DemoStyle.secondary)
                .accessibilityIdentifier("practice-result-progress")
        }
        .padding(.horizontal, DemoMetrics.sessionPadding)
        .padding(.top, DemoMetrics.sessionContentTop)
        .padding(.bottom, 24)
    }

    private func answerRow(_ title: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(title).font(.subheadline).foregroundStyle(DemoStyle.secondary)
            Spacer(minLength: 8)
            Text(value).font(.body.weight(.semibold))
        }
    }

    // MARK: - States

    private var submittingContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            ProgressView("正在提交答案…")
            if let selected = model.submission?.draft.selectedKey {
                Text("你的选择：\(selected)")
                    .font(.subheadline).foregroundStyle(DemoStyle.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, DemoMetrics.sessionPadding)
        .padding(.top, 100)
    }

    private func submitErrorContent(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("答案暂时无法提交").font(.title3.bold())
            Text(message).foregroundStyle(DemoStyle.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if let selected = model.submission?.draft.selectedKey {
                Text("已保存你的选择 \(selected)，重试会提交同一份答案。")
                    .font(.footnote).foregroundStyle(DemoStyle.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, DemoMetrics.sessionPadding)
        .padding(.top, 100)
        .accessibilityIdentifier("practice-submit-error")
    }

    private func loadErrorContent(_ message: String) -> some View {
        VStack(spacing: 15) {
            Text("练习暂时无法加载").font(.title3.bold())
            Text(message)
                .foregroundStyle(DemoStyle.secondary)
                .multilineTextAlignment(.center)
            Button("重试") { actionTask = Task { await model.retry() } }
                .buttonStyle(.borderedProminent)
            Button("退出") { onClose() }
                .foregroundStyle(DemoStyle.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 32)
        .padding(.top, 100)
    }

    private var emptyContent: some View {
        VStack(spacing: 15) {
            Text("这一组题已经做完了").font(.title3.bold())
            Button("退出") { onClose() }
                .foregroundStyle(DemoStyle.secondary)
        }
        .frame(maxWidth: .infinity).padding(.top, 100)
    }

    // MARK: - Footer

    @ViewBuilder
    private var footer: some View {
        switch model.phase {
        case .answering:
            primaryButton(title: "提交答案", identifier: "practice-submit-answer",
                          enabled: model.canSubmit, showsProgress: false) {
                actionTask = Task { await model.submit() }
            }
        case .submitting:
            primaryButton(title: "提交中", identifier: "practice-submit-answer",
                          enabled: false, showsProgress: true) { }
        case .submitFailed:
            VStack(spacing: 10) {
                primaryButton(title: "重试", identifier: "practice-retry-submit",
                              enabled: true, showsProgress: false) {
                    actionTask = Task { await model.retrySubmit() }
                }
                Button("退出") { onClose() }
                    .foregroundStyle(DemoStyle.secondary)
                    .accessibilityIdentifier("practice-submit-exit")
            }
            .padding(.horizontal, DemoMetrics.sessionPadding)
            .padding(.top, 16)
            .padding(.bottom, 10)
            .background(DemoStyle.background)
            .overlay(alignment: .top) { Divider().opacity(0.3) }
        case .result(let outcome):
            if outcome.sessionCompleted {
                primaryButton(title: "完成练习", identifier: "practice-finish",
                              enabled: true, showsProgress: false) {
                    onFinish(outcome)
                }
            } else if model.canContinue {
                primaryButton(title: "下一题", identifier: "practice-next-question",
                              enabled: true, showsProgress: false) {
                    model.continueToNext()
                }
            } else {
                Button("退出") { onClose() }
                    .foregroundStyle(DemoStyle.secondary)
                    .padding(.vertical, 16)
            }
        case .idle, .loading, .failed:
            EmptyView()
        }
    }

    private func primaryButton(title: String, identifier: String, enabled: Bool,
                               showsProgress: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 10) {
                if showsProgress { ProgressView().tint(.white) }
                Text(title).font(.headline)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
        }
        .foregroundStyle(.white)
        .background(.blue, in: Capsule())
        .disabled(!enabled)
        .opacity(enabled ? 1 : 0.5)
        .accessibilityIdentifier(identifier)
        .padding(.horizontal, DemoMetrics.sessionPadding)
        .padding(.top, 16)
        .padding(.bottom, 10)
        .background(DemoStyle.background)
        .overlay(alignment: .top) { Divider().opacity(0.3) }
    }
}
