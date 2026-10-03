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
    var body: some View {
        ScrollView {
            VStack(spacing: 25) {
                Text("好（hǎo）学\n＋\n好（hào）学\n↓\n学好")
                    .font(.system(size: 32, weight: .semibold))
                    .multilineTextAlignment(.center)
                Text("Personal Learning Agent")
                    .font(.subheadline).foregroundStyle(.secondary)
                Text("我们相信，\n\n真正个性化的教育，\n不应该只知道你答错了什么，\n而应该记得你如何学习。")
                    .font(.title3).multilineTextAlignment(.center)
                Text("It remembers how you learn.\nSo it knows what you need next.")
                    .font(.subheadline).multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
                Text("Version \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")\nEcho · 48H Hackathon")
                    .font(.caption).multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity)
            .padding(32)
        }
        .navigationTitle("About 好学")
    }
}
