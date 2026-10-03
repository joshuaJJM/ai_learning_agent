import Foundation
import SwiftUI
import Testing
@testable import HaoXue

/// Issue 2: make the backend's plain-text math readable without ever guessing a formula.
struct MathTextNormalizerTests {
    private func plain(_ text: String) -> String {
        String(MathTextNormalizer.normalize(text).characters)
    }

    private func superscripts(_ text: String) -> [String] {
        MathTextNormalizer.tokens(for: text).filter(\.isSuperscript).map(\.text)
    }

    private func rendered(_ text: String) -> String {
        MathTextNormalizer.tokens(for: text).map(\.text).joined()
    }

    @Test func simpleExponentsBecomeOneSuperscriptSpan() {
        #expect(plain("x^2") == "x2")
        #expect(plain("x^3") == "x3")
        #expect(superscripts("x^2") == ["2"])
        #expect(superscripts("x^3") == ["3"])
        #expect(superscripts("e^x") == ["x"])
        #expect(superscripts("e^2") == ["2"])
        #expect(superscripts("e^3") == ["3"])
        #expect(superscripts("a^2") == ["2"])
        #expect(superscripts("f(x)^2") == ["2"])

        // The caret is consumed; every other character survives in order.
        #expect(plain("x^2") == String("x^2".filter { $0 != "^" }))
    }

    @Test func multiDigitAndSignedExponentsStayWhole() {
        #expect(superscripts("x^10") == ["10"])
        #expect(superscripts("e^-1") == ["-1"])
        #expect(superscripts("x^0") == ["0"])
        // `x^10` must never render as `x¹0`.
        #expect(plain("x^10") == "x10")
        #expect(MathTextNormalizer.tokens(for: "x^10").count == 2)
    }

    @Test func parenthesizedExponentKeepsItsCharacters() {
        #expect(superscripts("x^(3/2)") == ["(3/2)"])
        #expect(plain("e^(3/2)") == "e(3/2)")
        #expect(superscripts("e^(3/2)") == ["(3/2)"])
        #expect(plain("1/(2e^(3/2))") == "1/(2e(3/2))")
        #expect(superscripts("1/(2e^(3/2))") == ["(3/2)"])
    }

    /// Regression for the question-bank notation seen in the Practice explanation:
    /// `f^(')(x)=3x^(2)-a`. The prime and the redundant single-digit parentheses are
    /// safe typography; anything the bank wrote without those exact shapes stays as-is.
    @Test func bankNotationRendersSafelyWithoutRewritingMath() {
        #expect(rendered("f^(')(x)=3x^(2)-a") == "f′(x)=3x2-a")
        #expect(superscripts("f^(')(x)=3x^(2)-a") == ["′", "2"])
        #expect(rendered("f^(')") == "f′")
        // 多字符括号指数保持原样，避免 `e^(3/2)` 被读成 `e^3/2`。
        #expect(superscripts("e^(3/2)") == ["(3/2)"])
        #expect(rendered("e^(3/2)") == "e(3/2)")
        // 没有 caret 的括号、花引号 prime、sqrt 记法一律不猜。
        #expect(rendered("x(2)") == "x(2)")
        #expect(rendered("sqrt((a)/(3))") == "sqrt((a)/(3))")
        #expect(rendered("f^(\u{2019})") == "f^(\u{2019})")
        #expect(rendered("f^('')(x)") == "f^('')(x)")
    }

    @Test func screenshotExpressionsKeepTheirMeaning() {
        #expect(plain("[2/e^3,1/e^2]") == "[2/e3,1/e2]")
        #expect(superscripts("[2/e^3,1/e^2]") == ["3", "2"])
        #expect(plain("(2/e^3,1/e^2)") == "(2/e3,1/e2)")
        #expect(plain("[1/(2e^(3/2)),1/e^2)") == "[1/(2e(3/2)),1/e2)")
        #expect(plain("(2/e^3,1/(2e^(3/2)))") == "(2/e3,1/(2e(3/2)))")
        #expect(superscripts("(2/e^3,1/(2e^(3/2)))") == ["3", "(3/2)"])
    }

    @Test func chineseAndMathMixWithoutTouchingTheProse() {
        let sentence = "若 h(x)=ae^x-x^2/2+x 在 [3/2,3] 上不单调，则……"
        #expect(plain(sentence) == "若 h(x)=aex-x2/2+x 在 [3/2,3] 上不单调，则……")
        #expect(superscripts(sentence) == ["x", "2"])
        // A caret that is not preceded by an operand stays literal.
        #expect(plain("导数^2 的用法") == "导数^2 的用法")
    }

    @Test func ambiguousMathematicsIsNeverRewritten() {
        #expect(plain("e^x2") == "ex2")
        #expect(superscripts("e^x2") == ["x"])
        #expect(plain("x^^2") == "x^^2")
        #expect(plain("x^(a^(b))") == "x^(a^(b))")
        #expect(plain("x^") == "x^")
        #expect(plain("^2") == "^2")
        #expect(plain("x ^2") == "x ^2")
        #expect(plain("x^((3))") == "x^((3))")
        #expect(plain("x^(a,b)") == "x^(a,b)")
        #expect(plain("1/(2e^(3/2))") == "1/(2e(3/2))")

        // Symbols the backend already sends correctly stay untouched.
        #expect(plain("(-∞,-1) ∪ (1,+∞)") == "(-∞,-1) ∪ (1,+∞)")
        #expect(plain("a ≤ b ≥ c ≠ d · e") == "a ≤ b ≥ c ≠ d · e")
        #expect(plain("3-5") == "3-5")
        #expect(plain("a-b") == "a-b")
    }

    @Test func multiplicationOnlyBetweenTwoOperands() {
        #expect(plain("2*3") == "2×3")
        #expect(plain("a*b") == "a×b")
        // Markdown-style runs and spaced asterisks are prose, not multiplication.
        #expect(plain("**重点**") == "**重点**")
        #expect(plain("3 * 2") == "3 * 2")
        #expect(plain("*") == "*")
    }

    @Test func hostileInputNeverCrashesAndNeverLosesCharacters() {
        let inputs = [
            "", "^", "^^", "^(", "x^(abc", "1/((", "x^(((", ") ^^ ((",
            "🧮 e^🤖", "e^", "^^^^^^^", "中文", "！@#$%^&*()_+",
            "\u{0}\u{1}^\u{2}", "e\u{2028}^2", "x^(1/2^(3))",
            String(repeating: "x^2", count: 5000),
            String(repeating: "^(1/2)", count: 400),
            String(repeating: "^", count: 3000)
        ]
        for input in inputs {
            let tokens = MathTextNormalizer.tokens(for: input)
            let rendered = tokens.map(\.text).joined()
            // No token may be empty, or characters would be silently lost.
            #expect(tokens.allSatisfy { !$0.text.isEmpty })
            // The caret is the only operator we consume, and `*` may become `×`.
            // Nothing else may be added, dropped or reordered.
            let survivors = String(rendered.filter { $0 != "^" }.map { $0 == "×" ? "*" : $0 })
            #expect(survivors == String(input.filter { $0 != "^" }))
        }
    }

    @Test func emptyInputProducesEmptyOutput() {
        #expect(String(MathTextNormalizer.normalize("").characters).isEmpty)
        #expect(MathTextNormalizer.tokens(for: "").isEmpty)
    }

    @Test func displayFormKeepsTheOriginalCharacters() {
        // `SafeMathText` labels the view with this same raw string, so VoiceOver never
        // reads a typography-only rendering.
        let raw = "h(x)=ae^x-x^2/2+x"
        #expect(rendered(raw) == String(raw.filter { $0 != "^" }))
    }
}
