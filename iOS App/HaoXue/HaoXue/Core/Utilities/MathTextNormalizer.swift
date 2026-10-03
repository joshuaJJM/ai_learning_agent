import Foundation
import SwiftUI

/// A run of the original backend text plus whether it is drawn as a superscript.
///
/// A token only ever carries characters copied out of the input, except for the single
/// `^` operator it consumes, and for `*` between two operands (rendered `×`).
struct MathDisplayToken: Equatable {
    let text: String
    let isSuperscript: Bool
}

/// Safe typography normalization for the plain-text math the backend sends.
///
/// The backend is not LaTeX and a wrong formula is worse than an ugly one, so this
/// parser only recognizes structures it can prove safe:
///
/// - `x^2`, `e^3`, `a^n`, `e^x` — caret preceded by one operand character and followed
///   by a single ASCII letter becomes a superscript span.
/// - `x^10`, `e^-1` — a whole digit run (optionally signed) is one exponent, so `x^10`
///   can never be rendered as `x¹0`.
/// - `e^(3/2)` — caret followed by a *flat* parenthesized group of digits, ASCII letters
///   and `+ - * / .` becomes a superscript span with its characters unchanged.
/// - `2*3`, `a*b` — `*` between two operands becomes `×`.
///
/// Everything else — nested or unbalanced parentheses, `^^`, `^(`, `e^x2`, CJK text,
/// emoji, `∞`, `≤`, `≥`, `≠`, `·`, `-` — is left exactly as received.
enum MathTextNormalizer {
    /// Characters that can carry an exponent (`x^2`, `f(x)^2`).
    private static let baseCharacters = Set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ)]}")
    /// Characters allowed inside a superscript span. Deliberately small and explicit;
    /// `(` and `)` are absent, which is what rejects nested groups.
    private static let superscriptCharacters = Set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+-*/. ")
    private static let leftOperandCharacters = Set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ)]}")
    private static let rightOperandCharacters = Set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ([{")

    /// Longest exponent we accept, so runaway input stays cheap and stays plain.
    private static let maximumExponentLength = 16

    private enum Exponentiation {
        /// Display text plus how many source characters the span consumed, so a
        /// replacement such as `^(')` → `′` cannot desynchronise the scanner.
        case superscript(String, consumed: Int)
        /// The caret starts a balanced group we will not render: keep it verbatim so the
        /// carets inside it cannot be lifted either.
        case opaqueGroup(length: Int)
        case keepLiteralCaret
    }

    // MARK: - Public API

    /// Returns the display form of `text`. Never throws and never traps on any input.
    static func normalize(_ text: String) -> AttributedString {
        var result = AttributedString()
        for token in tokens(for: text) {
            var piece = AttributedString(token.text)
            if token.isSuperscript { applySuperscript(to: &piece) }
            result.append(piece)
        }
        return result
    }

    /// The same result as `normalize`, as plain data, so the rules stay unit-testable.
    static func tokens(for text: String) -> [MathDisplayToken] {
        guard !text.isEmpty else { return [] }
        let characters = Array(text)
        var tokens: [MathDisplayToken] = []
        var plain = ""
        var index = 0

        while index < characters.count {
            let character = characters[index]
            if character == "^" {
                switch exponentiation(in: characters, after: index) {
                case .superscript(let exponent, let consumed):
                    flushPlain(&plain, into: &tokens)
                    tokens.append(MathDisplayToken(text: exponent, isSuperscript: true))
                    index += consumed
                    continue
                case .opaqueGroup(let length):
                    plain.append(contentsOf: characters[index..<(index + 1 + length)])
                    index += 1 + length
                    continue
                case .keepLiteralCaret:
                    break
                }
            }
            if character == "*", isMultiplication(in: characters, at: index) {
                flushPlain(&plain, into: &tokens)
                tokens.append(MathDisplayToken(text: "×", isSuperscript: false))
                index += 1
                continue
            }
            plain.append(character)
            index += 1
        }
        flushPlain(&plain, into: &tokens)
        return tokens
    }

    // MARK: - Internals

    private static func applySuperscript(to piece: inout AttributedString) {
        // Baseline shift only: the glyphs stay exactly the backend's characters, so no
        // digit can be lost to a Unicode substitution and no font renders a tofu box.
        piece.baselineOffset = superscriptBaselineOffset
    }

    private static let superscriptBaselineOffset: Double = 4

    private static func flushPlain(_ plain: inout String, into tokens: inout [MathDisplayToken]) {
        guard !plain.isEmpty else { return }
        tokens.append(MathDisplayToken(text: plain, isSuperscript: false))
        plain = ""
    }

    /// Decides what the caret at `caret` is worth: a provably safe exponent, an opaque
    /// parenthesized group, or a literal caret that stays in the plain text.
    private static func exponentiation(in characters: [Character], after caret: Int) -> Exponentiation {
        guard caret > 0, caret + 1 < characters.count else { return .keepLiteralCaret }
        guard baseCharacters.contains(characters[caret - 1]) else { return .keepLiteralCaret }
        let start = caret + 1

        if characters[start] == "(" {
            guard let close = matchingParenthesis(in: characters, from: start) else {
                return .keepLiteralCaret
            }
            let length = close - start + 1
            let inner = characters[(start + 1)..<close]
            // The question bank writes the derivative as `f^(')`; that is the prime sign,
            // not a parenthesised exponent, and the meaning is unambiguous.
            if inner.count == 1, inner.first == "'" {
                return .superscript("′", consumed: length + 1)
            }
            // `x^(2)` is the bank's flattened `x^{2}`: the parentheses only group a
            // single digit, so dropping them cannot change the meaning.
            if inner.count == 1, let digit = inner.first, digit.isASCII, digit.isNumber {
                return .superscript(String(digit), consumed: length + 1)
            }
            if !inner.isEmpty, inner.count <= maximumExponentLength,
               inner.allSatisfy(superscriptCharacters.contains) {
                return .superscript(String(characters[start...close]), consumed: length + 1)
            }
            return .opaqueGroup(length: length)
        }

        // Never lift only the first digit of `x^10`: a digit run is one exponent.
        var cursor = start
        var sign = ""
        if characters[cursor] == "-" {
            guard cursor + 1 < characters.count else { return .keepLiteralCaret }
            sign = "-"
            cursor += 1
        }
        let character = characters[cursor]
        guard character.isASCII else { return .keepLiteralCaret }
        if character.isNumber {
            var digits = ""
            while cursor < characters.count, characters[cursor].isASCII, characters[cursor].isNumber {
                digits.append(characters[cursor])
                cursor += 1
            }
            guard digits.count <= maximumExponentLength else { return .keepLiteralCaret }
            return .superscript(sign + digits, consumed: 1 + sign.count + digits.count)
        }
        // A bare letter exponent stays a single character: `e^x2` is ambiguous input.
        guard sign.isEmpty, character.isLetter else { return .keepLiteralCaret }
        return .superscript(String(character), consumed: 2)
    }

    private static func matchingParenthesis(in characters: [Character], from open: Int) -> Int? {
        var depth = 0
        var cursor = open
        while cursor < characters.count {
            if characters[cursor] == "(" {
                depth += 1
            } else if characters[cursor] == ")" {
                depth -= 1
                if depth == 0 { return cursor }
            }
            cursor += 1
        }
        return nil
    }

    private static func isMultiplication(in characters: [Character], at index: Int) -> Bool {
        guard index > 0, index + 1 < characters.count else { return false }
        // Never touch a run of asterisks (Markdown-style emphasis in plain text).
        guard characters[index - 1] != "*", characters[index + 1] != "*" else { return false }
        return leftOperandCharacters.contains(characters[index - 1])
            && rightOperandCharacters.contains(characters[index + 1])
    }
}
