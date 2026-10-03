import SwiftUI

/// Manual answer confirmation UI for a question the AI could not verify.
///
/// Only ever shown for `correctness == .unknown` — `unanswered` means the
/// student left the page blank, which is a different conversation.
///
/// This view is deliberately **not** attached to the live analysis result yet:
/// the backend contract for the confirmation endpoint is still being agreed, so
/// wiring it now would either guess the wire format or show a button that
/// cannot work. It becomes a one-line addition once the server side lands.
struct AnswerConfirmationSection: View {
    let model: AnswerConfirmationModel
    let studentAnswer: String?
    let possibleAnswer: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("确认标准答案").font(.headline)

            VStack(alignment: .leading, spacing: 7) {
                row("你的答案", studentAnswer ?? "未提供")
                row("参考答案", "尚未确认")
            }

            Text(hint)
                .font(.subheadline)
                .foregroundStyle(DemoStyle.secondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 10) {
                ForEach(model.choices, id: \.self) { choice in
                    choiceButton(choice)
                }
            }

            Button {
                Task { await model.confirm() }
            } label: {
                HStack(spacing: 8) {
                    if model.isSubmitting { ProgressView().controlSize(.small) }
                    Text(model.isSubmitting ? "提交中" : "确认答案")
                }
                .frame(maxWidth: .infinity, minHeight: 44)
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

    private var hint: String {
        var text = "AI 未能可靠确认本题答案，请选择答案册中的标准答案。"
        if let possibleAnswer, !possibleAnswer.isEmpty {
            text += "（AI 推测可能是 \(possibleAnswer)，仅供参考）"
        }
        return text
    }

    private func choiceButton(_ choice: String) -> some View {
        let selected = model.selected == choice
        return Button {
            model.select(choice)
        } label: {
            Text(choice)
                .font(.headline)
                .frame(minWidth: 44, minHeight: 40)
                .background(selected ? Color.blue : DemoStyle.background,
                            in: RoundedRectangle(cornerRadius: 10))
                .foregroundStyle(selected ? .white : .primary)
        }
        .disabled(model.isSubmitting || model.isConfirmed)
        .accessibilityIdentifier("confirm-answer-choice-\(choice)")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func row(_ title: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            Text(title).foregroundStyle(DemoStyle.secondary)
                .frame(width: 72, alignment: .leading)
            Text(value).frame(maxWidth: .infinity, alignment: .leading)
        }
        .font(.subheadline)
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
                submitter: AnswerConfirmationPreviewSubmitter()),
            studentAnswer: "D",
            possibleAnswer: "D")
    }
    .padding()
    .background(DemoStyle.background)
}
