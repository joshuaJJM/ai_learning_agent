import Foundation

protocol QuestionProvider {
    var totalQuestions: Int { get }
    var startingMastery: Double { get }
    func question(at index: Int) async throws -> TutorQuestion
}

enum QuestionProviderError: Error {
    case questionUnavailable
}

struct MockQuestionProvider: QuestionProvider {
    let totalQuestions = 3
    let startingMastery = 0.43

    private let questions = [
        TutorQuestion(id: "derivative-sign", lead: "如果在某个区间内：", expression: "f′(x) > 0",
                      prompt: "这说明函数 f(x) 在这个区间内……",
                      choices: [TutorChoice(id: .A, text: "单调递增"), TutorChoice(id: .B, text: "单调递减"),
                                TutorChoice(id: .C, text: "一定存在最大值"), TutorChoice(id: .D, text: "无法判断")],
                      correctAnswer: .A,
                      explanation: "当 f′(x) > 0 时，函数在该区间内单调递增。", masteryAfterQuestion: 0.46),
        TutorQuestion(id: "negative-sign", lead: "若函数在某个区间内满足：", expression: "f′(x) < 0",
                      prompt: "函数 f(x) 在这个区间内是……",
                      choices: [TutorChoice(id: .A, text: "单调递增"), TutorChoice(id: .B, text: "单调递减"),
                                TutorChoice(id: .C, text: "保持不变"), TutorChoice(id: .D, text: "一定有极小值")],
                      correctAnswer: .B,
                      explanation: "导数为负表示 x 增加时函数值减小，所以函数单调递减。", masteryAfterQuestion: 0.49),
        TutorQuestion(id: "parabola-interval", lead: "已知函数：", expression: "f(x) = x² − 2x",
                      prompt: "它在哪个区间单调递增？",
                      choices: [TutorChoice(id: .A, text: "(−∞, 0)"), TutorChoice(id: .B, text: "(−∞, 1)"),
                                TutorChoice(id: .C, text: "(1, +∞)"), TutorChoice(id: .D, text: "(0, +∞)")],
                      correctAnswer: .C,
                      explanation: "f′(x) = 2x − 2，x > 1 时导数为正，因此在 (1, +∞) 单调递增。",
                      masteryAfterQuestion: 0.51)
    ]

    func question(at index: Int) async throws -> TutorQuestion {
        guard questions.indices.contains(index) else { throw QuestionProviderError.questionUnavailable }
        return questions[index]
    }
}
