import SwiftUI

struct StudyView: View {
    let store: DemoScenarioStore
    let onStart: () -> Void
    let onStartPractice: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DemoMetrics.sectionGap) {
                DemoPageHeader(title: "学习", subtitle: "不是固定课程表，而是根据你的状态决定下一步。")
                DemoSection(title: "继续学习") {
                    DemoCard {
                        VStack(alignment: .leading, spacing: 18) {
                            Text(store.lessonTitle).font(.title2.bold())
                            HStack(alignment: .firstTextBaseline) {
                                Text("当前掌握度").foregroundStyle(DemoStyle.secondary)
                                Spacer()
                                Text(store.mastery.demoPercent).font(DemoType.metric)
                            }
                            MasteryBar(value: store.mastery)
                            Text("从「\(store.knowledgeLink)」继续")
                                .foregroundStyle(DemoStyle.secondary)
                                .fixedSize(horizontal: false, vertical: true)
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
                }
                DemoSection(title: "练习") {
                    DemoCard {
                        VStack(alignment: .leading, spacing: 13) {
                            Text("针对薄弱点练习").font(.title3.bold())
                            Text(store.practiceSummary)
                                .foregroundStyle(DemoStyle.secondary)
                            Button("开始练习") { onStartPractice() }
                                .buttonStyle(DemoPrimaryButtonStyle(tint: DemoStyle.accent))
                                .accessibilityIdentifier("start-practice")
                                .padding(.top, 4)
                        }
                    }
                }
                if let change = store.home.recentChanges.first {
                    DemoSection(title: "最近变化") {
                        DemoCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text(store.lessonTitle).font(.headline)
                                Text("\((change.beforeMastery ?? 0).demoPercent) → \((change.afterMastery ?? 0).demoPercent)")
                                    .font(.title.bold()).foregroundStyle(.green)
                                Text("刚刚 · 模拟课程完成")
                                    .font(DemoType.secondary).foregroundStyle(DemoStyle.secondary)
                            }
                        }
                    }
                }
            }
            .padding(.horizontal, DemoMetrics.pagePadding)
            .padding(.top, DemoMetrics.pageTopPadding)
            .padding(.bottom, DemoMetrics.pageBottomPadding)
        }
        .background(DemoStyle.background)
    }
}
