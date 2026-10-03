import SwiftUI

/// Phase 6B boundary: the student can enter a real session, read the backend
/// question and pick one choice. Judging is Phase 6C — `onSubmit` receives the
/// draft and does nothing else here.
struct PracticeSessionView: View {
    let onSessionReady: (String) -> Void
    let onSubmit: (PracticeAnswerDraft) -> Void
    let onClose: () -> Void
    @State private var model: PracticeSessionViewModel
    @State private var showingScratchpad = false
    @State private var actionTask: Task<Void, Never>?

    init(provider: any PracticeDataProviding, existingSessionID: String? = nil,
         knowledgePointID: String? = nil, createKey: IdempotencyKey? = nil,
         onSessionReady: @escaping (String) -> Void = { _ in },
         onSubmit: @escaping (PracticeAnswerDraft) -> Void = { _ in },
         onClose: @escaping () -> Void) {
        self.onSessionReady = onSessionReady
        self.onSubmit = onSubmit
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
                    .accessibilityLabel("关闭练习")
                Spacer()
                Text("针对性练习").font(.headline).lineLimit(1)
                Spacer()
                Button("草稿本") { showingScratchpad = true }
                    .accessibilityLabel("草稿本")
            }
            .padding(.horizontal, 22)
            .padding(.vertical, 19)
            .background(DemoStyle.background)
            .overlay(alignment: .bottom) { Divider().opacity(0.3) }

            ScrollView {
                switch model.phase {
                case .idle, .loading:
                    ProgressView("正在准备针对性练习…")
                        .frame(maxWidth: .infinity).padding(.top, 100)
                case .failed:
                    errorContent
                case .loaded:
                    if let question = model.question {
                        questionContent(question)
                    } else {
                        emptyContent
                    }
                }
            }
            .background(Color(uiColor: .systemBackground))
            .safeAreaInset(edge: .bottom) {
                if model.question != nil { footer }
            }
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

    private func questionContent(_ question: PracticeQuestion) -> some View {
        VStack(alignment: .leading, spacing: 22) {
            VStack(alignment: .leading, spacing: 6) {
                Text("针对性练习")
                    .font(.subheadline.bold()).foregroundStyle(DemoStyle.secondary)
                if let title = model.contextTitle {
                    Text(title).font(.title3.weight(.semibold))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
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
        .padding(.horizontal, 22)
        .padding(.top, 32)
        .padding(.bottom, 24)
    }

    /// Selection is local presentation state: no verdict, no colour, no mastery.
    private func choiceButton(_ choice: PracticeChoice) -> some View {
        let selected = model.selectedChoiceKey == choice.key
        return Button { model.select(choice.key) } label: {
            HStack(spacing: 15) {
                Text(choice.key)
                    .font(.headline)
                    .frame(width: 34, height: 34)
                    .background(DemoStyle.background, in: Circle())
                SafeMathText(choice.text).font(.body.weight(.medium))
                    .fixedSize(horizontal: false, vertical: true)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 8)
                if selected { Image(systemName: "checkmark") }
            }
            .padding(12)
            .foregroundStyle(.primary)
            .background(selected ? Color.blue.opacity(0.09) : .clear,
                        in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8)
                .stroke(selected ? .blue : Color(uiColor: .systemGray4)))
        }
        .accessibilityIdentifier("choice-\(choice.key)")
    }

    private var footer: some View {
        Button {
            guard let draft = model.makeSubmission() else { return }
            onSubmit(draft)
        } label: {
            Text("提交答案")
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
        }
        .foregroundStyle(.white)
        .background(.blue, in: Capsule())
        .disabled(!model.canSubmit)
        .opacity(model.canSubmit ? 1 : 0.5)
        .accessibilityIdentifier("practice-submit-answer")
        .padding(.horizontal, 22)
        .padding(.top, 16)
        .padding(.bottom, 10)
        .background(DemoStyle.background)
        .overlay(alignment: .top) { Divider().opacity(0.3) }
    }

    private var errorContent: some View {
        VStack(spacing: 15) {
            Text("练习暂时无法加载").font(.title3.bold())
            Text(model.errorMessage ?? "请稍后重试")
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
}
