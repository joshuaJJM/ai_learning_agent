import SwiftUI

struct StudyView: View {
    let store: DemoScenarioStore
    let onStart: () -> Void
    let onStartPractice: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                DemoPageHeader(title: "学习", subtitle: "不是固定课程表，而是根据你的状态决定下一步。")
                DemoSectionTitle(title: "继续学习")
                DemoCard {
                    VStack(alignment: .leading, spacing: 18) {
                        Text(store.lessonTitle).font(.title2.bold())
                        HStack(alignment: .firstTextBaseline) {
                            Text("当前掌握度").foregroundStyle(DemoStyle.secondary)
                            Spacer()
                            Text(store.mastery.demoPercent).font(.largeTitle.bold())
                        }
                        MasteryBar(value: store.mastery)
                        Text("从「\(store.knowledgeLink)」继续")
                            .foregroundStyle(DemoStyle.secondary)
                        Button(action: onStart) {
                            HStack {
                                Spacer()
                                Text("继续课程")
                                Image(systemName: "arrow.right")
                            }
                            .font(.headline)
                        }
                        .accessibilityLabel("继续课程")
                    }
                }
                DemoSectionTitle(title: "练习").padding(.top, 22)
                DemoCard {
                    VStack(alignment: .leading, spacing: 13) {
                        Text("针对薄弱点练习").font(.title3.bold())
                        Text(store.practiceSummary)
                            .foregroundStyle(DemoStyle.secondary)
                        Button("开始练习") { onStartPractice() }
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12)
                            .background(Color.blue.opacity(0.1), in: Capsule())
                            .accessibilityIdentifier("start-practice")
                    }
                }
                if let change = store.home.recentChanges.first {
                    DemoSectionTitle(title: "最近变化").padding(.top, 22)
                    DemoCard {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(store.lessonTitle).font(.headline)
                            Text("\((change.beforeMastery ?? 0).demoPercent) → \((change.afterMastery ?? 0).demoPercent)")
                                .font(.title.bold()).foregroundStyle(.green)
                            Text("刚刚 · 模拟课程完成")
                                .font(.subheadline).foregroundStyle(DemoStyle.secondary)
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
}
