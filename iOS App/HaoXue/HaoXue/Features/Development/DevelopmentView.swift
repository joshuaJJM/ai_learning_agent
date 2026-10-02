import SwiftUI

struct DevelopmentView: View {
    let model: DevelopmentViewModel

    var body: some View {
        VStack(spacing: 12) {
            Text("好学")
            Text("Development Build")
            switch model.state {
            case .loading: Text("Loading…")
            case .ready: Text("Mock Data Ready")
            case .error: Text("加载失败")
            }
        }
        .padding()
        .task { await model.load() }
    }
}

#Preview {
    DevelopmentView(model: DevelopmentViewModel(provider: MockDataProvider()))
}
