import SwiftUI

enum DemoStyle {
    static let background = Color(uiColor: .systemGroupedBackground)
    static let secondary = Color(uiColor: .secondaryLabel)
    static let accent = Color.blue
}

/// One spacing rhythm for the whole app. Pages share the same horizontal
/// margin, section gap and card padding so the demo never looks stitched
/// together from different phases.
enum DemoMetrics {
    /// 页面左右边距
    static let pagePadding: CGFloat = 20
    /// 内容区（导航栏 / 安全区之后）顶部留白
    static let pageTopPadding: CGFloat = 24
    /// ScrollView 底部留白
    static let pageBottomPadding: CGFloat = 36
    /// 两个区块之间的距离
    static let sectionGap: CGFloat = 24
    /// 区块标题与内容之间的距离
    static let sectionTitleGap: CGFloat = 12
    /// 卡片内边距
    static let cardPadding: CGFloat = 20
    /// 卡片圆角
    static let cardCornerRadius: CGFloat = 26
    /// 次级容器（选项、输入框、内嵌信息块）圆角
    static let controlCornerRadius: CGFloat = 12
    /// 可点击控件的最小高度
    static let controlMinHeight: CGFloat = 44
    /// 主按钮高度
    static let primaryButtonMinHeight: CGFloat = 50
    /// Tutor / Practice 沉浸页左右边距
    static let sessionPadding: CGFloat = 22
    /// Tutor / Practice 正文起点
    static let sessionContentTop: CGFloat = 32
    /// Toolbar / 顶栏图标按钮命中区
    static let iconButtonSize: CGFloat = 44
    /// 空状态插图
    static let emptyStateSymbol = Font.system(size: 52, weight: .light)
}

/// The app is typography-first: a handful of semantic roles, never scattered
/// fixed point sizes. Everything here scales with Dynamic Type.
enum DemoType {
    /// 页面主标题（首页 / 扫描 / 学习 / 设置）
    static let pageTitle = Font.largeTitle.bold()
    /// 页面副标题
    static let pageSubtitle = Font.body
    /// 区块标题
    static let sectionTitle = Font.headline
    /// 卡片内主标题
    static let cardTitle = Font.title3.bold()
    /// 主数值（掌握度 / 额度 / 掌握度变化）
    static let metric = Font.largeTitle.bold().monospacedDigit()
    /// 行内数值
    static let inlineMetric = Font.subheadline.weight(.semibold).monospacedDigit()
    /// 正文
    static let body = Font.body
    /// 次要说明
    static let secondary = Font.subheadline
    /// 元数据
    static let meta = Font.caption
}

struct DemoPageHeader: View {
    let title: String
    var subtitle: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(DemoType.pageTitle)
            if let subtitle {
                Text(subtitle)
                    .font(DemoType.pageSubtitle)
                    .foregroundStyle(DemoStyle.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct DemoSectionTitle: View {
    let title: String
    var body: some View {
        Text(title)
            .font(DemoType.sectionTitle)
            .foregroundStyle(DemoStyle.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Section = title + content with one shared gap, so every page uses the same
/// vertical rhythm instead of hand-tuned `.padding(.top, …)` values.
struct DemoSection<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: DemoMetrics.sectionTitleGap) {
            DemoSectionTitle(title: title)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct DemoCard<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(DemoMetrics.cardPadding)
            .background(.background, in: RoundedRectangle(cornerRadius: DemoMetrics.cardCornerRadius))
    }
}

/// Primary CTA: one filled capsule used by every page (scan, tutor, practice,
/// product surfaces) so “继续” always looks the same.
struct DemoPrimaryButtonStyle: ButtonStyle {
    var tint: Color = DemoStyle.accent

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .frame(minHeight: DemoMetrics.primaryButtonMinHeight)
            .background(tint, in: Capsule())
            .opacity(configuration.isPressed ? 0.75 : 1)
            .contentShape(Capsule())
    }
}

/// Secondary CTA: quiet, same geometry as the primary button.
struct DemoSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(DemoStyle.accent)
            .frame(maxWidth: .infinity)
            .frame(minHeight: DemoMetrics.primaryButtonMinHeight)
            .background(DemoStyle.background, in: Capsule())
            .opacity(configuration.isPressed ? 0.7 : 1)
            .contentShape(Capsule())
    }
}

/// The single A-D choice row shared by Tutor and Practice. Both surfaces must
/// read as one learning system, so selection, colour and geometry live here.
struct DemoChoiceRow: View {
    enum Emphasis: Equatable {
        case idle, selected, correct, wrong

        var tint: Color {
            switch self {
            case .idle: DemoStyle.accent
            case .selected: DemoStyle.accent
            case .correct: .green
            case .wrong: .orange
            }
        }

        var border: Color {
            switch self {
            case .idle: Color(uiColor: .systemGray4)
            default: tint
            }
        }

        var fill: Color {
            switch self {
            case .idle: .clear
            case .selected, .correct, .wrong: tint.opacity(0.09)
            }
        }

        var label: String? {
            switch self {
            case .correct: "正确答案"
            case .wrong: "选择错误"
            case .idle, .selected: nil
            }
        }

        var symbol: String? {
            switch self {
            case .correct: "checkmark.circle.fill"
            case .wrong: "xmark.circle.fill"
            case .selected: "checkmark"
            case .idle: nil
            }
        }
    }

    let key: String
    let text: String
    var emphasis: Emphasis = .idle
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 15) {
                Text(key)
                    .font(.headline)
                    .frame(width: 32, height: 32)
                    .background(DemoStyle.background, in: Circle())
                SafeMathText(text)
                    .font(.body.weight(.medium))
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 8)
                trailing
            }
            .padding(12)
            .foregroundStyle(.primary)
            .background(emphasis.fill,
                        in: RoundedRectangle(cornerRadius: DemoMetrics.controlCornerRadius))
            .overlay(RoundedRectangle(cornerRadius: DemoMetrics.controlCornerRadius)
                .stroke(emphasis.border))
            .contentShape(RoundedRectangle(cornerRadius: DemoMetrics.controlCornerRadius))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("choice-\(key)")
        .accessibilityLabel(accessibilityLabel)
    }

    @ViewBuilder
    private var trailing: some View {
        if let label = emphasis.label, let symbol = emphasis.symbol {
            Label(label, systemImage: symbol).font(.caption)
        } else if let symbol = emphasis.symbol {
            Image(systemName: symbol).accessibilityHidden(true)
        }
    }

    private var accessibilityLabel: String {
        var value = "选项 \(key)，\(text)"
        if let label = emphasis.label { value += "，\(label)" }
        else if emphasis == .selected { value += "，已选择" }
        return value
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
        .accessibilityLabel("掌握度 \(value.demoPercent)")
    }
}

extension Double {
    var demoPercent: String { "\(Int((self * 100).rounded()))%" }
}
