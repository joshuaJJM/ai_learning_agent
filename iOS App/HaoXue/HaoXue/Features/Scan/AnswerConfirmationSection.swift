import SwiftUI

/// Manual answer confirmation UI for a question the AI could not verify.
///
/// Only ever shown for `correctness == .unknown` — `unanswered` means the
/// student left the page blank, which is a different conversation.
///
/// The question's own rows (「你的答案 / 参考答案 / AI 无法确认…」) already sit
/// directly above this section, so it only carries the action: a short
/// instruction, the choices and the confirm button.
struct AnswerConfirmationSection: View {
    let model: AnswerConfirmationModel
    /// Called after the server accepted the confirmation so the screen can
    /// reload the authoritative result.
    var onConfirmed: () async -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("确认标准答案").font(.headline)

            Text("请根据答案册选择本题的标准答案。")
                .font(DemoType.secondary)
                .foregroundStyle(DemoStyle.secondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 10) {
                ForEach(model.choices, id: \.self) { choice in
                    choiceButton(choice)
                }
            }

            Button {
                Task {
                    if await model.confirm() { await onConfirmed() }
                }
            } label: {
                HStack(spacing: 8) {
                    if model.isSubmitting { ProgressView().controlSize(.small) }
                    Text(model.isSubmitting ? "提交中" : "确认答案")
                }
                .frame(maxWidth: .infinity, minHeight: DemoMetrics.controlMinHeight)
            }
            .disabled(!model.canConfirm)
            .accessibilityIdentifier("confirm-answer-submit")

            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle")
                    .font(.subheadline)
                    .foregroundStyle(.orange)
            }
        }
        .padding(.top, 4)
    }

    private func choiceButton(_ choice: String) -> some View {
        let selected = model.selected == choice
        return Button {
            model.select(choice)
        } label: {
            Text(choice)
                .font(.headline)
                .frame(minWidth: DemoMetrics.controlMinHeight, minHeight: 40)
                .background(selected ? Color.blue : DemoStyle.background,
                            in: RoundedRectangle(cornerRadius: 10))
                .foregroundStyle(selected ? .white : .primary)
        }
        .disabled(model.isSubmitting || model.isConfirmed)
        .accessibilityIdentifier("confirm-answer-choice-\(choice)")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// Preview-only host: lets the section be inspected without a backend.
private struct AnswerConfirmationPreviewSubmitter: AnswerConfirming {
    func confirm(questionID: String, correctAnswer: String) async throws {}
}

#Preview {
    DemoCard {
        AnswerConfirmationSection(
            model: AnswerConfirmationModel(
                questionID: "q_preview",
                choices: ["A", "B", "C", "D"],
                submitter: AnswerConfirmationPreviewSubmitter()))
    }
    .padding()
    .background(DemoStyle.background)
}
