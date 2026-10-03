import Foundation
import Testing
@testable import HaoXue

@MainActor
struct LiveHomeTests {
    private func capturedHome() throws -> HomeSnapshot {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/Home.json")
        let dto = try BackendJSON.decoder.decode(HomeResponseDTO.self, from: Data(contentsOf: url))
        return Phase5Mapper().home(dto)
    }

    @Test func initialLoadPublishesBackendSnapshotAndDoesNotFetchTwice() async throws {
        let home = try capturedHome()
        let provider = ScriptedHomeProvider([.success(home)])
        let model = HomeViewModel(provider: provider)
        provider.onFetch = { #expect(model.phase == .loading) }

        await model.loadIfNeeded()
        await model.loadIfNeeded()

        #expect(model.phase == .loaded)
        #expect(model.snapshot?.greeting == "夜深了，同学")
        #expect(model.snapshot?.nextAction.title == home.nextAction.title)
        #expect(provider.callCount == 1)
    }

    @Test func backendFailureShowsTypedErrorAndRetryUsesLiveData() async throws {
        let home = try capturedHome()
        let provider = ScriptedHomeProvider([
            .failure(NetworkError.backend(code: "SERVICE_UNAVAILABLE", message: "server detail",
                                          requestID: "req_1", status: 503)),
            .success(home), .success(home)
        ])
        let model = HomeViewModel(provider: provider)

        await model.loadIfNeeded()
        #expect(model.phase == .failed)
        #expect(model.snapshot == nil)
        #expect(model.errorMessage != "server detail")

        await model.refresh()
        #expect(model.phase == .loaded)
        #expect(model.snapshot?.userID == home.userID)
        await model.refresh()
        #expect(provider.callCount == 3)
    }

    @Test func actionRoutingUsesBackendKindAndIdentifiers() {
        func action(_ kind: String, knowledgeID: String? = nil,
                    wrongID: String? = nil) -> NextLearningAction {
            NextLearningAction(kind: kind, title: "下一步", reason: "原因", buttonTitle: "继续",
                               knowledgePointID: knowledgeID, knowledgePointName: nil,
                               wrongQuestionID: wrongID)
        }

        #expect(HomeActionRoute(action("start_tutor", knowledgeID: "kp_1")) == .tutor("kp_1"))
        #expect(HomeActionRoute(action("start_tutor")) == .none)
        #expect(HomeActionRoute(action("review_wrong_question", wrongID: "wq_1")) == .wrongQuestion("wq_1"))
        #expect(HomeActionRoute(action("review_wrong_question")) == .none)
        #expect(HomeActionRoute(action("continue_practice")) == .practice(nil))
        #expect(HomeActionRoute(action("increase_difficulty", knowledgeID: "kp_2"))
                == .practice("kp_2"))
        #expect(HomeActionRoute(action("next_knowledge_point", knowledgeID: "kp_3"))
                == .knowledge("kp_3"))
        #expect(HomeActionRoute(action("next_knowledge_point")) == .none)
        #expect(HomeActionRoute(action("review_later")) == .none)
        #expect(HomeActionRoute(action("all_good")) == .none)
        #expect(HomeActionRoute(action("future_action")) == .none)
    }

    /// Tutor completion offers Practice only when the *structured* backend action
    /// says so; the natural-language title never influences routing.
    @Test func tutorCompletionRoutesFromStructuredNextActionOnly() {
        func dto(_ kind: String, knowledgeID: String?, title: String = "下一步") -> NextActionDTO {
            NextActionDTO(action: kind, title: title, reason: "原因", ctaLabel: "继续",
                          knowledgePointId: knowledgeID, knowledgePointName: nil,
                          wrongQuestionId: nil)
        }
        let mapper = Phase5Mapper()
        #expect(HomeActionRoute(mapper.action(dto("continue_practice", knowledgeID: "kp_1")))
                == .practice("kp_1"))
        #expect(HomeActionRoute(mapper.action(dto("start_tutor", knowledgeID: "kp_1")))
                == .tutor("kp_1"))
        #expect(HomeActionRoute(mapper.action(dto("all_good", knowledgeID: "kp_9",
                                                  title: "开始针对性练习"))) == .none)
    }

    @Test func tutorCreationUsesHomeKnowledgePointID() throws {
        let service = TutorRemoteService(baseURL: URL(string: "http://fixture.invalid")!,
                                         knowledgePointID: "math.derivative.extrema_parameter")
        let request = try service.makeCreateRequest(key: "logical-key")
        let body = try #require(request.httpBody)
        let object = try #require(JSONSerialization.jsonObject(with: body) as? [String: Any])
        #expect(object["knowledge_point_id"] as? String == "math.derivative.extrema_parameter")
    }

    @Test func masteryUsesPresentationRoundingWithoutChangingSource() {
        let mastery = 0.436
        #expect(mastery.demoPercent == "44%")
        #expect(mastery == 0.436)
    }
}

@MainActor
private final class ScriptedHomeProvider: HomeSnapshotProviding {
    private var responses: [Result<HomeSnapshot, Error>]
    private(set) var callCount = 0
    var onFetch: (() -> Void)?

    init(_ responses: [Result<HomeSnapshot, Error>]) { self.responses = responses }

    func fetchHomeSnapshot() async throws -> HomeSnapshot {
        callCount += 1
        onFetch?()
        return try responses.removeFirst().get()
    }
}
