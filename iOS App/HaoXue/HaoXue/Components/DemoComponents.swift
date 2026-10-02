import SwiftUI

enum DemoStyle {
    static let background = Color(uiColor: .systemGroupedBackground)
    static let secondary = Color(uiColor: .secondaryLabel)
}

struct DemoPageHeader: View {
    let title: String
    var subtitle: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 38, weight: .bold))
            if let subtitle {
                Text(subtitle).font(.body).foregroundStyle(DemoStyle.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.bottom, 24)
    }
}

struct DemoSectionTitle: View {
    let title: String
    var body: some View {
        Text(title)
            .font(.headline)
            .foregroundStyle(DemoStyle.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct DemoCard<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
            .background(.background, in: RoundedRectangle(cornerRadius: 26))
    }
}

struct MasteryBar: View {
    let value: Double
    var color: Color = .blue

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Capsule().fill(Color(uiColor: .systemGray5))
                Capsule().fill(color).frame(width: geometry.size.width * min(max(value, 0), 1))
            }
        }
        .frame(height: 7)
        .accessibilityLabel("掌握度 \(Int(value * 100))%")
    }
}

extension Double {
    var demoPercent: String { "\(Int((self * 100).rounded()))%" }
}
