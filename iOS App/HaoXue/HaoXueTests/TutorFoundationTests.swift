import PencilKit
import Testing
@testable import HaoXue

@MainActor
struct TutorFoundationTests {
    @Test func mockQuestionsHaveFourChoicesAndExpectedAnswers() async throws {
        let provider = MockQuestionProvider()
        #expect(provider.totalQuestions == 3)
        let expected: [ChoiceID] = [.A, .B, .C]
        for index in 0..<provider.totalQuestions {
            let question = try await provider.question(at: index)
            #expect(question.choices.map(\.id) == ChoiceID.allCases)
            #expect(question.isCorrect(expected[index]))
            #expect(!question.explanation.isEmpty)
        }
    }

    @Test func answerLocksAndProgressesThroughThreeQuestions() async {
        let model = TutorViewModel(provider: MockQuestionProvider())
        #expect(model.session.state == .loading)
        await model.loadQuestion()
        #expect(model.session.state == .answering)
        #expect(model.session.progressText == "1 / 3")
        #expect(model.session.displayedMastery == 0.43)
        model.submit()
        #expect(model.session.state == .answering)
        model.select(.B)
        model.select(.A)
        model.submit()
        #expect(model.session.state == .submittedCorrect)
        #expect(model.session.selectedAnswer == .A)
        model.select(.D)
        #expect(model.session.selectedAnswer == .A)
        #expect(model.session.displayedMastery == 0.46)
        await model.advance()
        #expect(model.session.progressText == "2 / 3")
        #expect(model.session.selectedAnswer == nil)
        model.select(.A)
        model.submit()
        #expect(model.session.state == .submittedWrong)
        #expect(model.session.currentQuestion?.correctAnswer == .B)
        model.showExplanation()
        #expect(model.session.state == .showingExplanation)
        #expect(model.session.displayedMastery == 0.49)
        await model.advance()
        #expect(model.session.progressText == "3 / 3")
        model.select(.C)
        model.submit()
        await model.advance()
        #expect(model.session.state == .completed)
        #expect(model.session.displayedMastery == 0.51)
    }

    @Test func advancingResetsDrawingButSubmittingDoesNot() async {
        let model = TutorViewModel(provider: MockQuestionProvider())
        await model.loadQuestion()
        let point = PKStrokePoint(location: .init(x: 10, y: 10), timeOffset: 0,
                                  size: .init(width: 3, height: 3), opacity: 1,
                                  force: 1, azimuth: 0, altitude: .pi / 2)
        let stroke = PKStroke(ink: PKInk(.pen, color: .black),
                              path: PKStrokePath(controlPoints: [point], creationDate: .now))
        model.drawing = PKDrawing(strokes: [stroke])
        model.select(.A)
        model.submit()
        #expect(model.drawing.strokes.count == 1)
        await model.advance()
        #expect(model.drawing.strokes.isEmpty)
    }

    @Test func completedLessonUpdatesPresentationOnlyWhenFinished() {
        let store = DemoScenarioStore()
        store.startLesson()
        #expect(store.mastery == 0.43)
        store.finishLesson()
        #expect(store.mastery == 0.51)
        #expect(store.home.nextStep == "巩固导数与单调性")
        #expect(DemoScenarioStore().mastery == 0.43)
    }
}
