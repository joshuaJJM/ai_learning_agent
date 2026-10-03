import SwiftUI

struct AnalysisResultPresentation {
    let result: HomeworkAnalysisResult

    var totalCount: Int {
        max(result.correctCount + result.wrongCount + result.partialCount
                + result.unansweredCount + result.unknownCount,
            result.questions.count)
    }

    var attentionQuestions: [HomeworkAnalysisResult.Question] {
        result.questions.filter { $0.correctness != .correct }
    }

    var correctQuestions: [HomeworkAnalysisResult.Question] {
        result.questions.filter { $0.correctness == .correct }
    }

    /// Only these can be handed to the manual answer confirmation flow. An
    /// unanswered question is the student's blank page, not an unverified
    /// answer, so it is deliberately excluded.
    var confirmableQuestions: [HomeworkAnalysisResult.Question] {
        result.questions.filter { $0.correctness == .unknown }
    }

    func label(for question: HomeworkAnalysisResult.Question) -> String {
        switch question.correctness {
        case .wrong: "需要关注"
        case .partial: "部分正确"
        case .correct: "回答正确"
        case .unanswered: "未作答"
        case .unknown: "需要确认"
        case .other: "需要确认"
        }
    }

    /// Server phrasing for a question the AI could not verify. The optional
    /// `possible_answer` is shown as a hint and explicitly marked as not counted.
    func unverifiedHint(for question: HomeworkAnalysisResult.Question) -> String {
        if let possible = question.possibleAnswer, !possible.isEmpty {
            return "AI 无法确认本题答案（可能是 \(possible)），未计入统计"
        }
        return "AI 无法确认本题答案，未计入统计"
    }

    /// `unanswered` and `unknown` are informational, not warnings: they never
    /// count toward mastery, so they must not be painted like a mistake.
    func labelTint(for question: HomeworkAnalysisResult.Question) -> Color {
        switch question.correctness {
        case .wrong, .partial: .orange
        case .correct, .unanswered, .unknown, .other: DemoStyle.secondary
        }
    }

    func studentAnswerLabel(for question: HomeworkAnalysisResult.Question) -> String {
        if let answer = question.studentAnswer, !answer.isEmpty { return answer }
        return question.correctness == .unanswered ? "未作答" : "未提供"
    }

    func changeLabel(_ change: KnowledgeChange) -> String? {
        guard let delta = change.delta else { return nil }
        return String(format: "%+.1f 个百分点", delta * 100)
    }
}
