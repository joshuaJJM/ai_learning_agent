import Foundation

struct AnalysisResultPresentation {
    let result: HomeworkAnalysisResult

    var totalCount: Int {
        max(result.correctCount + result.wrongCount + result.partialCount + result.unknownCount,
            result.questions.count)
    }

    var attentionQuestions: [HomeworkAnalysisResult.Question] {
        result.questions.filter { $0.correctness != "correct" }
    }

    var correctQuestions: [HomeworkAnalysisResult.Question] {
        result.questions.filter { $0.correctness == "correct" }
    }

    func label(for question: HomeworkAnalysisResult.Question) -> String {
        switch question.correctness {
        case "wrong": "需要关注"
        case "partial": "部分正确"
        case "correct": "回答正确"
        default: "需要确认"
        }
    }

    func changeLabel(_ change: KnowledgeChange) -> String? {
        guard let delta = change.delta else { return nil }
        return String(format: "%+.1f 个百分点", delta * 100)
    }
}
