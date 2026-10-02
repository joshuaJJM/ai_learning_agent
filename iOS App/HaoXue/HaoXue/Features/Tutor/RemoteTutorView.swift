import SwiftUI

struct RemoteTutorView: View {
    let onClose: () -> Void
    @State private var model: RemoteTutorViewModel
    @State private var showingScratchpad = false
    @State private var actionTask: Task<Void, Never>?
    @Environment(\.scenePhase) private var scenePhase

    init(service: any TutorRemoteServing, onClose: @escaping () -> Void) {
        self.onClose = onClose
        _model = State(initialValue: RemoteTutorViewModel(service: service))
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button {
                    actionTask?.cancel()
                    model.cancel()
                    onClose()
                } label: { Image(systemName: "xmark") }
                    .accessibilityLabel("关闭课程")
                Spacer()
                Text(model.knowledgePointName).font(.headline).lineLimit(1)
                Spacer()
                Button("草稿本") { showingScratchpad = true }
            }
            .padding(.horizontal, 22)
            .padding(.vertical, 19)
            .background(DemoStyle.background)
            .overlay(alignment: .bottom) { Divider().opacity(0.3) }

            ScrollView {
                if model.isLoading && model.turn == nil {
                    ProgressView("正在加载题目")
                        .frame(maxWidth: .infinity).padding(.top, 100)
                } else if model.completed {
                    completionContent
                } else if let turn = model.turn {
                    turnContent(turn)
                } else {
                    errorContent
                }
            }
            .background(Color(uiColor: .systemBackground))
            .safeAreaInset(edge: .bottom) {
                if model.turn != nil { footer }
            }
        }
        .onAppear {
            if model.sessionId == nil {
                actionTask = Task { await model.load() }
            }
        }
        .onDisappear {
            actionTask?.cancel()
            model.cancel()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background {
                actionTask?.cancel()
                model.cancel()
            } else if phase == .active && model.sessionId == nil {
                actionTask = Task { await model.load() }
            }
        }
        .sheet(isPresented: $showingScratchpad) {
            ScratchpadView(drawing: $model.drawing)
                .presentationDetents([.large])
        }
    }

    private func turnContent(_ turn: TutorTurnDTO) -> some View {
        VStack(alignment: .leading, spacing: 22) {
            Text(turn.remedialDepth > 0 ? "换个角度 · 第 \(turn.remedialDepth) / 4 层" : "理解检查")
                .font(.subheadline.bold()).foregroundStyle(DemoStyle.secondary)
            Text(turn.text)
                .font(.title3.weight(.semibold))
                .frame(maxWidth: .infinity, alignment: .leading)
            if model.pendingNextTurn == nil, !model.isSubmitting,
               let feedback = model.feedback, !turn.text.hasPrefix(feedback) {
                Text(feedback).font(.subheadline)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.blue.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
            }
            if model.isSubmitting {
                VStack(alignment: .leading, spacing: 12) {
                    ProgressView("正在分析你的思路…")
                    if !model.streamedText.isEmpty {
                        Text(model.streamedText).font(.body)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(16)
                .background(DemoStyle.background, in: RoundedRectangle(cornerRadius: 8))
            }
            if model.pendingNextTurn == nil && !model.isSubmitting {
                ForEach(turn.choices) { choice in choiceButton(choice) }
                if turn.choices.isEmpty && turn.allowFreeText {
                    TextField("写下你的想法", text: $model.freeText, axis: .vertical)
                        .lineLimit(3...6)
                        .padding(14)
                        .background(DemoStyle.background, in: RoundedRectangle(cornerRadius: 8))
                }
            }
            if model.pendingNextTurn != nil { feedbackContent }
            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle")
                    .font(.subheadline).foregroundStyle(.red)
            }
        }
        .padding(.horizontal, 22)
        .padding(.top, 42)
        .padding(.bottom, 24)
        .animation(.easeInOut(duration: 0.2), value: model.turn?.turnId)
    }

    private func choiceButton(_ choice: TutorChoiceDTO) -> some View {
        let selected = model.selectedKey == choice.key
        return Button { model.select(choice.key) } label: {
            HStack(spacing: 15) {
                Text(choice.key)
                    .font(.headline)
                    .frame(width: 34, height: 34)
                    .background(DemoStyle.background, in: Circle())
                Text(choice.text).font(.body.weight(.medium))
                Spacer()
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

    private var feedbackContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let correct = model.answeredCorrectly {
                Label(correct ? "回答正确" : "回答错误",
                      systemImage: correct ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .font(.headline)
            }
            if let feedback = model.feedback { Text(feedback) }
            if let reveal = model.answerReveal {
                if let origin = reveal.origin {
                    if let current = reveal.current {
                        Text("补救题正确答案：\(current.correctKey)").font(.subheadline.bold())
                        if let explanation = current.explanation, !explanation.isEmpty { Text(explanation) }
                    }
                    Text("原题正确答案：\(origin.correctKey)").font(.subheadline.bold())
                    if let explanation = origin.explanation, !explanation.isEmpty { Text(explanation) }
                } else if let current = reveal.current {
                    Text("正确答案：\(current.correctKey)").font(.subheadline.bold())
                    if let explanation = current.explanation, !explanation.isEmpty { Text(explanation) }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.blue.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
    }

    private var footer: some View {
        VStack(spacing: 14) {
            Button(action: primaryAction) {
                HStack {
                    if model.isSubmitting { ProgressView().tint(.white) }
                    Text(primaryTitle).font(.headline)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
            }
            .foregroundStyle(.white)
            .background(.blue, in: Capsule())
            .disabled(!primaryEnabled)
            .opacity(primaryEnabled ? 1 : 0.5)
            .accessibilityLabel(primaryTitle)
            if !model.completed {
                Text("课程进度 · \(model.progressText)")
                    .font(.caption).foregroundStyle(DemoStyle.secondary)
            }
        }
        .padding(.horizontal, 22)
        .padding(.top, 16)
        .padding(.bottom, 10)
        .background(DemoStyle.background)
        .overlay(alignment: .top) { Divider().opacity(0.3) }
    }

    private var primaryTitle: String {
        if model.completed { return "完成学习" }
        if model.isSubmitting { return "提交中" }
        if model.errorMessage != nil { return "重试" }
        if model.pendingNextTurn != nil {
            return model.pendingNextTurn?.completed == true ? "查看总结" : "下一题"
        }
        return "提交答案"
    }

    private var primaryEnabled: Bool {
        if model.completed { return true }
        if model.isSubmitting { return false }
        if model.errorMessage != nil || model.pendingNextTurn != nil { return true }
        return model.canSubmit
    }

    private func primaryAction() {
        if model.completed { onClose(); return }
        if model.errorMessage != nil { actionTask = Task { await model.retry() }; return }
        if model.pendingNextTurn != nil { model.continueToNext(); return }
        actionTask = Task { await model.submit() }
    }

    private var completionContent: some View {
        VStack(alignment: .leading, spacing: 22) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 45)).foregroundStyle(.green)
            Text("学习完成").font(.largeTitle.bold())
            Text(model.knowledgePointName).font(.title2)
            Text("本轮学习已完成").font(.body)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 24)
        .padding(.top, 85)
    }

    private var errorContent: some View {
        VStack(spacing: 16) {
            Text(model.errorMessage ?? "加载失败").font(.title3.bold())
            Button("重试") { actionTask = Task { await model.retry() } }
        }
        .frame(maxWidth: .infinity).padding(.top, 100)
    }
}
