import Foundation

struct TutorQuestion: Equatable, Identifiable {
    let id: String
    let lead: String
    let expression: String
    let prompt: String
    let choices: [TutorChoice]
    let correctAnswer: ChoiceID
    let explanation: String
    let masteryAfterQuestion: Double

    func isCorrect(_ answer: ChoiceID) -> Bool { answer == correctAnswer }
}

enum TutorSessionState: Equatable {
    case loading
    case answering
    case submittedCorrect
    case submittedWrong
    case showingExplanation
    case completed
    case error
}

struct TutorLearningSession {
    let totalQuestions: Int
    let startingMastery: Double
    var displayedMastery: Double
    var questionIndex = 0
    var currentQuestion: TutorQuestion?
    var selectedAnswer: ChoiceID?
    var state: TutorSessionState = .loading

    var progressText: String { "\(questionIndex + 1) / \(totalQuestions)" }
    var hasSubmitted: Bool {
        state == .submittedCorrect || state == .submittedWrong || state == .showingExplanation
    }
}
