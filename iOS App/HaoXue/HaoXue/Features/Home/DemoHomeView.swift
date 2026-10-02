import SwiftUI

// Fixed presentation used by the mock Tutor UI tests.
struct DemoHomeView: View {
    let store: DemoScenarioStore
    let onStart: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                DemoPageHeader(title: "好学", subtitle: "这里是今天最值得关注的学习状态。")
                DemoSectionTitle(title: "下一步")
                DemoCard {
                    VStack(alignment: .leading, spacing: 15) {
                        Text(store.home.nextStep).font(.title2.bold())
                        Text(store.nextStepDetail).foregroundStyle(DemoStyle.secondary)
                        Button(action: onStart) {
                            HStack {
                                Text("继续学习")
                                Spacer()
                                Image(systemName: "chevron.right")
                            }
                            .font(.headline)
                        }
                        .accessibilityLabel("开始下一步学习")
                        .padding(.top, 8)
                    }
                }
                DemoSectionTitle(title: "知识状态").padding(.top, 18)
                DemoCard {
                    VStack(spacing: 19) {
                        ForEach(store.subjects, id: \.name) { subject in
                            VStack(spacing: 9) {
                                HStack {
                                    Text(subject.name).font(.headline)
                                    Spacer()
                                    Text(subject.mastery.demoPercent).foregroundStyle(DemoStyle.secondary)
                                }
                                MasteryBar(value: subject.mastery, color: color(for: subject.colorName))
                            }
                        }
                    }
                }
                Text("其他学科为演示数据")
                    .font(.caption)
                    .foregroundStyle(DemoStyle.secondary)
                DemoSectionTitle(title: "错题").padding(.top, 14)
                DemoCard {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(store.recentWrongQuestions.enumerated()), id: \.offset) { index, question in
                            if index > 0 { Divider().padding(.vertical, 14) }
                            Text(question.title).font(.headline)
                            Text(question.detail).font(.subheadline).foregroundStyle(DemoStyle.secondary)
                                .padding(.top, 5)
                        }
                    }
                }
                if let change = store.home.recentChanges.first {
                    DemoSectionTitle(title: "最近变化").padding(.top, 14)
                    DemoCard {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(store.lessonTitle).font(.headline)
                            Text("\((change.beforeMastery ?? 0).demoPercent) → \((change.afterMastery ?? 0).demoPercent)")
                                .font(.title2.bold()).foregroundStyle(.green)
                        }
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 26)
            .padding(.bottom, 32)
        }
        .background(DemoStyle.background)
    }

    private func color(for name: String) -> Color {
        switch name {
        case "green": .green
        case "orange": .orange
        default: .blue
        }
    }
}
