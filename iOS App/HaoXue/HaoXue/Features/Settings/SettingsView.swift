import SwiftUI

struct SettingsView: View {
    let store: DemoScenarioStore
    @State private var commercial = CommercialDemoStore()

    var body: some View {
        NavigationStack {
            List {
                Section("学习") {
                    NavigationLink("专注模式") { FocusPreviewView() }
                    NavigationLink("图书与题库") {
                        BookStoreView(commercial: commercial)
                    }
                }
                Section("账户与学习") {
                    NavigationLink {
                        LearningPlanView(commercial: commercial)
                    } label: {
                        SettingsValueRow(title: "好学计划", value: commercial.isPlanActive ? "已加入" : "未加入")
                    }
                    NavigationLink {
                        CreditView(commercial: commercial)
                    } label: {
                        SettingsValueRow(title: "学习额度", value: commercial.creditBalance.formatted())
                    }
                    NavigationLink("邀请同学") { InviteView(commercial: commercial) }
                }
                Section("隐私") {
                    NavigationLink("数据与隐私") { PrivacyView() }
                }
                Section("关于") {
                    NavigationLink("关于好学") { AboutHaoXueView() }
                    SettingsValueRow(title: "Version", value: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")
                }
            }
            .navigationTitle("设置")
        }
    }
}

private struct SettingsValueRow: View {
    let title: String
    let value: String
    var body: some View {
        HStack {
            Text(title)
            Spacer()
            Text(value).foregroundStyle(.secondary)
        }
    }
}
