import SwiftUI

struct PrivacyView: View {
    var body: some View {
        List {
            Section("你的学习数据") {
                Text("好学通过你的作业、错题、学习过程和练习结果建立个人知识状态。")
            }
            Section("数据的用途") {
                privacyRow("作业图片", "用于理解题目与学生作答。")
                privacyRow("错题与学习记录", "用于建立知识状态，并决定下一步最值得学习的内容。")
                privacyRow("Tutor 与 Practice", "用于根据学习表现调整下一步教学。")
                privacyRow("草稿本", "用于本地书写；Hackathon 版本不对草稿内容进行 AI 语义理解。")
            }
            Section("我们的原则") {
                Text("只收集完成学习功能所需的数据，清楚说明学习数据的用途。草稿内容不参与 AI 分析；学习状态不作为广告画像。")
            }
        }
        .navigationTitle("数据与隐私")
    }

    private func privacyRow(_ title: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.headline)
            Text(detail).font(.subheadline).foregroundStyle(.secondary)
        }.padding(.vertical, 4)
    }
}

struct FocusPreviewView: View {
    @State private var wantsFocus = false
    var body: some View {
        List {
            Section {
                Text("在 Tutor 或 Practice 开始时，好学希望帮助你减少其他 App 的干扰。")
            }
            Section("未来的设置") {
                Toggle("自动开始学习专注", isOn: $wantsFocus)
                LabeledContent("允许的学习 App", value: "预览")
            }
            Section("Hackathon Preview") {
                Text("这里展示未来产品方向。当前开关只保存页面内的演示选择，不会启用系统专注或限制其他 App。")
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("学习专注")
    }
}

struct AboutHaoXueView: View {
    private var version: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                VStack(spacing: 8) {
                    Text("好")
                        .font(.system(size: 40, weight: .semibold, design: .rounded))
                        .foregroundStyle(.white)
                        .frame(width: 82, height: 82)
                        .background(.blue, in: RoundedRectangle(cornerRadius: 19, style: .continuous))
                        .accessibilityLabel("好学图标")
                    Text("好学").font(.title2.bold())
                    Text("Personal Learning Agent")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.top, 12)

                Text("让每一次学习，\n都成为下一次学习的依据。")
                    .font(.title3.weight(.medium))
                    .frame(maxWidth: .infinity, alignment: .leading)

                Divider()
                aboutSection("名字的含义") {
                    Text("好（hǎo）学 + 好（hào）学 = 学好")
                        .font(.body.weight(.medium))
                    Text("“好学”既意味着学得更好，\n也意味着保持对学习的热爱。")
                        .foregroundStyle(.secondary)
                }

                Divider()
                aboutSection("关于这个项目") {
                    Text("好学通过作业、错题、Tutor 与练习，\n逐步理解你的知识状态，\n并据此决定下一步最值得学习的内容。")
                        .foregroundStyle(.secondary)
                }

                Divider()
                VStack(alignment: .leading, spacing: 12) {
                    Text("It remembers how you learn.\nSo it knows what you need next.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    Text("Version \(version)\nEcho · 48H Hackathon")
                        .font(.caption).foregroundStyle(.tertiary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 24)
            .padding(.bottom, 40)
        }
        .navigationTitle("关于好学")
    }

    private func aboutSection<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(.headline)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
