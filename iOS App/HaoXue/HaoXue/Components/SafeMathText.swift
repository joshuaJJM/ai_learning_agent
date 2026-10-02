import SwiftUI

/// Renders backend plain text with safe math typography.
///
/// Only unambiguous exponents are lifted; everything else is shown verbatim.
/// The accessibility label always uses the original backend string, so VoiceOver
/// never reads a typography-only rendering.
struct SafeMathText: View {
    private let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(MathTextNormalizer.normalize(text))
            .accessibilityLabel(text)
    }
}
