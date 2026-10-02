import SwiftUI

struct TutorView: View {
    let store: DemoScenarioStore
    let onClose: () -> Void
    @State private var showingScratchpadInfo = false

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button(action: onClose) { Image(systemName: "xmark") }
                    .accessibilityLabel("关闭课程")
                Spacer()
                Text(store.lessonTitle).font(.headline)
                Spacer()
                Button("草稿本") { showingScratchpadInfo = true }
            }
            .padding(.horizontal, 22)
            .padding(.vertical, 19)

            ScrollView {
                if store.tutorStep == .completion {
                    completionContent
                } else {
                    questionContent
                }
            }
            .safeAreaInset(edge: .bottom) {
                VStack(spacing: 17) {
                    Button(action: primaryAction) {
                        Text(primaryTitle)
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                    }
                    .foregroundStyle(.white)
                    .background(.blue, in: Capsule())
                    .disabled(store.tutorStep == .question && store.selectedChoice == nil)
                    .opacity(store.tutorStep == .question && store.selectedChoice == nil ? 0.5 : 1)
                    .accessibilityLabel(primaryTitle)
                    if store.tutorStep != .completion {
                        HStack {
                            Text(store.lessonTitle)
                            Spacer()
                            Text(store.mastery.demoPercent).font(.headline)
                        }
                        .font(.subheadline)
                        .foregroundStyle(DemoStyle.secondary)
                        MasteryBar(value: store.mastery)
                        Text("课程进度 · \(store.tutorStep == .question ? "1 / 2" : "2 / 2")")
                            .font(.caption).foregroundStyle(DemoStyle.secondary)
                    }
                }
                .padding(.horizontal, 22)
                .padding(.top, 16)
                .padding(.bottom, 10)
                .background(.background)
            }
        }
        .background(.background)
        .alert("草稿本即将开放", isPresented: $showingScratchpadInfo) {
            Button("好") { }
        } message: {
            Text("当前阶段保留草稿本入口，书写功能将在后续阶段加入。")
        }
    }

    private var questionContent: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text("理解检查")
                .font(.subheadline.bold()).foregroundStyle(DemoStyle.secondary)
            Text(store.tutorQuestionLead).font(.title2.bold())
            Text(store.tutorExpression)
                .font(.system(size: 34, weight: .semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 24)
                .background(DemoStyle.background, in: RoundedRectangle(cornerRadius: 18))
            Text(store.tutorQuestionEnd)
                .font(.title3.bold())
            ForEach(store.tutorChoices, id: \.id) { choice in
                Button {
                    store.selectChoice(choice.id)
                } label: {
                    HStack(spacing: 15) {
                        Text(choice.id.rawValue)
                            .font(.headline)
                            .frame(width: 34, height: 34)
                            .background(DemoStyle.background, in: Circle())
                        Text(choice.text).font(.body.weight(.medium))
                        Spacer()
                    }
                    .padding(12)
                    .foregroundStyle(.primary)
                    .background(store.selectedChoice == choice.id ? Color.blue.opacity(0.09) : .clear,
                                in: RoundedRectangle(cornerRadius: 17))
                    .overlay(RoundedRectangle(cornerRadius: 17)
                        .stroke(store.selectedChoice == choice.id ? Color.blue : Color(uiColor: .systemGray4)))
                }
                .disabled(store.tutorStep == .feedback)
                .accessibilityLabel("选项 \(choice.id.rawValue)")
            }
            Text("或者")
                .font(.subheadline).foregroundStyle(DemoStyle.secondary)
                .frame(maxWidth: .infinity)
            Text("写下你的想法……")
                .foregroundStyle(DemoStyle.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(17)
                .background(DemoStyle.background, in: RoundedRectangle(cornerRadius: 16))
            Text("Demo 中此输入暂不上传")
                .font(.caption).foregroundStyle(DemoStyle.secondary)
            if store.tutorStep == .feedback {
                Text(store.feedbackIsCorrect ? store.correctFeedback : store.incorrectFeedback)
                    .font(.body.weight(.medium))
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.blue.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
            }
        }
        .padding(.horizontal, 22)
        .padding(.top, 42)
        .padding(.bottom, 24)
    }

    private var completionContent: some View {
        VStack(alignment: .leading, spacing: 22) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 45)).foregroundStyle(.green)
            Text("学习完成").font(.largeTitle.bold())
            Text(store.lessonTitle).font(.title2)
            Text("43% → 51%")
                .font(.system(size: 34, weight: .bold))
                .foregroundStyle(.green)
            Text("你已经改善了：")
                .foregroundStyle(DemoStyle.secondary)
            Text(store.knowledgeLink).font(.title3.bold())
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 24)
        .padding(.top, 85)
    }

    private var primaryTitle: String {
        switch store.tutorStep {
        case .question: "提交答案"
        case .feedback: "继续学习"
        case .completion: "完成学习"
        }
    }

    private func primaryAction() {
        switch store.tutorStep {
        case .question: store.submitChoice()
        case .feedback: store.continueLesson()
        case .completion: onClose()
        }
    }
}
