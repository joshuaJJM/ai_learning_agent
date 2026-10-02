import Observation
import PencilKit

@MainActor @Observable
final class TutorViewModel {
    private let provider: any QuestionProvider
    private(set) var session: TutorLearningSession
    var drawing = PKDrawing()

    init(provider: any QuestionProvider) {
        self.provider = provider
        session = TutorLearningSession(totalQuestions: provider.totalQuestions,
                                       startingMastery: provider.startingMastery,
                                       displayedMastery: provider.startingMastery)
    }

    func loadQuestion() async {
        guard session.state == .loading else { return }
        do {
            session.currentQuestion = try await provider.question(at: session.questionIndex)
            session.state = .answering
        } catch {
            session.state = .error
        }
    }

    func retry() async {
        guard session.state == .error else { return }
        session.state = .loading
        await loadQuestion()
    }

    func select(_ answer: ChoiceID) {
        guard session.state == .answering else { return }
        session.selectedAnswer = answer
    }

    func submit() {
        guard session.state == .answering,
              let question = session.currentQuestion,
              let answer = session.selectedAnswer else { return }
        session.state = question.isCorrect(answer) ? .submittedCorrect : .submittedWrong
        session.displayedMastery = question.masteryAfterQuestion
    }

    func showExplanation() {
        guard session.state == .submittedCorrect || session.state == .submittedWrong else { return }
        session.state = .showingExplanation
    }

    func advance() async {
        guard session.hasSubmitted else { return }
        if session.questionIndex + 1 == session.totalQuestions {
            session.state = .completed
            return
        }
        session.questionIndex += 1
        session.selectedAnswer = nil
        session.currentQuestion = nil
        drawing = PKDrawing()
        session.state = .loading
        await loadQuestion()
    }
}
