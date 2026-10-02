import Testing
@testable import HaoXue

@MainActor
struct DemoScenarioStoreTests {
    @Test func correctAnswerCompletesLessonAndUpdatesRecommendation() {
        let store = DemoScenarioStore()
        #expect(store.mastery == 0.43)
        #expect(store.home.nextStep == "导数与函数单调性")

        store.startLesson()
        store.selectChoice(.A)
        store.submitChoice()
        #expect(store.tutorStep == .feedback)
        #expect(store.mastery == 0.43)
        store.continueLesson()
        #expect(store.tutorStep == .completion)
        #expect(store.mastery == 0.51)
        #expect(store.home.nextStep == "巩固导数与单调性")
    }

    @Test func wrongAnswerReturnsToQuestionWithoutChangingMastery() {
        let store = DemoScenarioStore()
        store.startLesson()
        store.selectChoice(.B)
        store.submitChoice()
        #expect(store.feedbackIsCorrect == false)
        store.continueLesson()
        #expect(store.tutorStep == .question)
        #expect(store.mastery == 0.43)
    }

    @Test func aFreshStoreStartsAtInitialDemoState() {
        let first = DemoScenarioStore()
        first.startLesson()
        first.selectChoice(.A)
        first.submitChoice()
        first.continueLesson()
        #expect(first.mastery == 0.51)
        #expect(DemoScenarioStore().mastery == 0.43)
    }

    @Test func reopeningLessonDoesNotUndoCompletedKnowledgeState() {
        let store = DemoScenarioStore()
        store.startLesson()
        store.selectChoice(.A)
        store.submitChoice()
        store.continueLesson()
        store.startLesson()
        #expect(store.mastery == 0.51)
        #expect(store.home.nextStep == "巩固导数与单调性")
    }
}
