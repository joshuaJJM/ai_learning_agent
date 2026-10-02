import SwiftUI

struct SettingsView: View {
    let store: DemoScenarioStore
    @State private var selectedSetting: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                DemoPageHeader(title: "设置")
                DemoSectionTitle(title: "学习")
                settingsCard(store.learningSettings)
                DemoSectionTitle(title: "好学").padding(.top, 22)
                settingsCard(store.productSettings)
                DemoSectionTitle(title: "About").padding(.top, 22)
                settingsCard(store.aboutSettings)
            }
            .padding(.horizontal, 20)
            .padding(.top, 26)
            .padding(.bottom, 35)
        }
        .background(DemoStyle.background)
        .alert(selectedSetting ?? "", isPresented: Binding(
            get: { selectedSetting != nil },
            set: { if !$0 { selectedSetting = nil } }
        )) {
            Button("好") { selectedSetting = nil }
        } message: {
            Text("此项目目前显示演示信息，功能将在后续阶段加入。")
        }
    }

    private func settingsCard(_ rows: [(String, String)]) -> some View {
        DemoCard {
            VStack(spacing: 0) {
                ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                    if index > 0 { Divider().padding(.vertical, 13) }
                    Button {
                        selectedSetting = row.0
                    } label: {
                        HStack(spacing: 10) {
                            VStack(alignment: .leading, spacing: 5) {
                                Text(row.0).font(.headline).foregroundStyle(.primary)
                                Text(row.1).font(.subheadline).foregroundStyle(DemoStyle.secondary)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.subheadline.bold())
                                .foregroundStyle(DemoStyle.secondary)
                        }
                    }
                }
            }
        }
    }
}
