import Foundation
import Testing
@testable import HaoXue

/// The non-networked half of the manual answer confirmation flow. The wire
/// contract is still being agreed with the backend, so these tests pin the
/// behaviour that must hold whatever that contract turns out to be.
@MainActor
struct AnswerConfirmationTests {
    private func model(_ confirmer: any AnswerConfirming) -> AnswerConfirmationModel {
        AnswerConfirmationModel(questionID: "q_unknown", choices: ["A", "B", "C", "D"],
                                submitter: confirmer)
    }

    @Test func selectingAChoiceNeverWritesToTheServer() async throws {
        let confirmer = ScriptedConfirmer()
        let model = model(confirmer)

        model.select("C")

        #expect(model.selected == "C")
        #expect(model.canConfirm)
        #expect(confirmer.calls.isEmpty)
    }

    @Test func confirmNeedsAnExplicitSelection() async throws {
        let confirmer = ScriptedConfirmer()
        let model = model(confirmer)

        #expect(await model.confirm() == false)
        #expect(confirmer.calls.isEmpty)
        #expect(model.errorMessage == nil)
    }

    @Test func confirmSendsOnlyTheConfirmedAnswerAndNoVerdict() async throws {
        let confirmer = ScriptedConfirmer()
        let model = model(confirmer)

        model.select("D")
        #expect(await model.confirm())

        // The client's whole payload is "the answer book says D for this
        // question" — correctness / Evidence / mastery stay server-side.
        #expect(confirmer.calls.count == 1)
        #expect(confirmer.calls.first?.questionID == "q_unknown")
        #expect(confirmer.calls.first?.correctAnswer == "D")
        #expect(model.isConfirmed)
        #expect(!model.canConfirm)
    }

    @Test func rapidDoubleConfirmSendsOneLogicalRequest() async throws {
        let confirmer = ScriptedConfirmer(delay: .milliseconds(200))
        let model = model(confirmer)
        model.select("B")

        async let first = model.confirm()
        try await Task.sleep(for: .milliseconds(20))
        async let second = model.confirm()
        let results = await (first, second)

        #expect(results.0 == true)
        #expect(results.1 == false)
        #expect(confirmer.calls.count == 1)
    }

    @Test func failureKeepsTheSelectionAndRetryResendsTheSameAnswer() async throws {
        let confirmer = ScriptedConfirmer(results: [.failure(NetworkError.timeout), .success(())])
        let model = model(confirmer)
        model.select("A")

        #expect(await model.confirm() == false)
        #expect(model.errorMessage == "确认没有提交成功，请重试。")
        #expect(model.selected == "A")
        #expect(model.isConfirmed == false)
        // A failed attempt must not leave the row stuck in a loading state.
        #expect(model.isSubmitting == false)

        #expect(await model.confirm())
        #expect(confirmer.calls.map(\.correctAnswer) == ["A", "A"])
        #expect(model.errorMessage == nil)
    }

    @Test func selectionIsIgnoredWhileSubmitting() async throws {
        let confirmer = ScriptedConfirmer(delay: .milliseconds(150))
        let model = model(confirmer)
        model.select("A")

        async let run = model.confirm()
        try await Task.sleep(for: .milliseconds(20))
        model.select("D")
        #expect(model.selected == "A")
        _ = await run
        #expect(confirmer.calls.first?.correctAnswer == "A")
    }
}

@MainActor
private final class ScriptedConfirmer: AnswerConfirming {
    private(set) var calls: [(questionID: String, correctAnswer: String)] = []
    private var results: [Result<Void, Error>]
    private let delay: Duration?

    init(results: [Result<Void, Error>] = [], delay: Duration? = nil) {
        self.results = results
        self.delay = delay
    }

    func confirm(questionID: String, correctAnswer: String) async throws {
        calls.append((questionID, correctAnswer))
        if let delay { try? await Task.sleep(for: delay) }
        guard results.count > 1 else { return try results.first?.get() ?? () }
        try results.removeFirst().get()
    }
}
