import Foundation
import Testing
@testable import HaoXue

/// Issue 1: show the backend's real mastery instead of any locally invented number.
struct MasteryOverviewTests {
    @Test @MainActor func overviewDecodesTheServerScoreVerbatim() throws {
        let json = """
        {"score":60,"percent":0.6045,"weighted_mastery":0.6045,"coverage":1.0,
         "covered_count":17,"point_count":17,"evidence_count":103,
         "weakest":[{"knowledge_point_id":"kp_a","name":"导数与函数性质综合应用","mastery":0.432},
                    {"knowledge_point_id":"kp_b","name":"奇偶性、对称性与周期性中的导数关系","mastery":0.441},
                    {"knowledge_point_id":"kp_c","name":"切线相关的最值问题","mastery":0.444}]}
        """
        let dto = try MasteryOverviewJSON.decoder.decode(MasteryOverviewDTO.self, from: Data(json.utf8))
        let overview = MasteryOverviewMapper().map(dto)

        // `score` is already a 0-99 integer: the client must not scale it.
        #expect(overview.score == 60)
        #expect(overview.percent == 0.6045)
        #expect(overview.weightedMastery == 0.6045)
        #expect(overview.coverage == 1.0)
        #expect(overview.coveredCount == 17)
        #expect(overview.pointCount == 17)
        #expect(overview.evidenceCount == 103)
        #expect(overview.weakest.map(\.id) == ["kp_a", "kp_b", "kp_c"])
        #expect(overview.weakest.first?.name == "导数与函数性质综合应用")
        #expect(overview.weakest.first?.mastery == 0.432)
    }

    @Test @MainActor func overviewToleratesAPartialResponse() throws {
        let dto = try MasteryOverviewJSON.decoder.decode(MasteryOverviewDTO.self, from: Data(#"{"score":7}"#.utf8))
        let overview = MasteryOverviewMapper().map(dto)
        #expect(overview.score == 7)
        #expect(overview.weakest.isEmpty)
        #expect(overview.evidenceCount == 0)
    }

    @Test @MainActor func overviewRequestTargetsTheKnowledgeEndpoint() {
        let service = MasteryOverviewService(baseURL: URL(string: "http://127.0.0.1:17283")!)
        let request = service.makeOverviewRequest()
        #expect(request.httpMethod == "GET")
        #expect(request.url?.absoluteString == "http://127.0.0.1:17283/api/v1/knowledge/mastery-overview")
    }

    @Test @MainActor func overviewScoreIsUsedWithoutRecomputation() async {
        let mastery = StubMasteryService(overview: MasteryOverviewTests.overview(score: 60))
        let model = RemoteTutorViewModel(service: MasteryTutorService(), masteryService: mastery)
        await model.load()
        #expect(model.overallMasteryScore == 60)
    }

    @Test @MainActor func overviewFailureDoesNotBlockTheTutorSession() async {
        let mastery = StubMasteryService(error: NetworkError.timeout)
        let model = RemoteTutorViewModel(service: MasteryTutorService(), masteryService: mastery)
        await model.load()

        #expect(model.sessionId == "tut_mastery")
        #expect(model.turn?.turnId == "turn_1")
        #expect(model.errorMessage == nil)
        #expect(model.isLoading == false)
        #expect(model.overallMasteryScore == nil)

        model.select("A")
        await model.submit()
        #expect(model.pendingNextTurn?.turnId == "turn_2")
        #expect(model.errorMessage == nil)
    }

    @Test @MainActor func tutorAdoptsTheFirstServerBeforeAsSessionStart() async {
        let tutor = MasteryTutorService()
        tutor.changePayloads = [MasteryFixture.changes(before: 0.4322, after: 0.3968, evidence: 13)]
        tutor.changePayloads.append(MasteryFixture.emptyChanges)
        let model = RemoteTutorViewModel(service: tutor)

        await model.load()
        #expect(model.sessionStartMastery == nil)
        #expect(model.currentMastery == nil)

        model.select("B")
        await model.submit()
        #expect(model.sessionStartMastery == 0.4322)
        #expect(model.currentMastery == 0.3968)
    }

    @Test @MainActor func emptyKnowledgeChangesKeepThePreviousMastery() async {
        let tutor = MasteryTutorService()
        tutor.changePayloads = [
            MasteryFixture.changes(before: 0.4322, after: 0.3968, evidence: 13),
            MasteryFixture.emptyChanges,
            MasteryFixture.emptyChanges
        ]
        let model = RemoteTutorViewModel(service: tutor)
        await model.load()

        model.select("B")
        await model.submit()
        #expect(model.currentMastery == 0.3968)

        model.continueToNext()
        model.select("B")
        await model.submit()
        model.continueToNext()
        model.select("B")
        await model.submit()

        // No reset to nil, no reset to zero, no recomputation from student_understanding.
        #expect(model.sessionStartMastery == 0.4322)
        #expect(model.currentMastery == 0.3968)
        #expect(model.canShowMastery)
    }

    @Test @MainActor func completionUsesServerBeforeAndAfterOnly() async {
        let tutor = MasteryTutorService()
        tutor.completesImmediately = true
        // student_understanding and difficulty are deliberately different values:
        // neither may leak into the displayed mastery.
        tutor.changePayloads = [MasteryFixture.changes(before: 0.4322, after: 0.51, evidence: 14)]
        let model = RemoteTutorViewModel(service: tutor)
        await model.load()

        model.select("A")
        await model.submit()

        #expect(model.completed)
        #expect(model.sessionStartMastery == 0.4322)
        #expect(model.currentMastery == 0.51)
        #expect(model.hasMasteryChange)
        #expect(model.completionChanges.first?.before == 0.4322)
        #expect(model.completionChanges.first?.after == 0.51)
    }

    @Test @MainActor func completionWithoutKnowledgeChangeDoesNotInventNumbers() async {
        let tutor = MasteryTutorService()
        tutor.completesImmediately = true
        let model = RemoteTutorViewModel(service: tutor)
        await model.load()

        model.select("A")
        await model.submit()

        #expect(model.completed)
        #expect(model.sessionStartMastery == nil)
        #expect(model.currentMastery == nil)
        #expect(model.hasMasteryChange == false)
    }

    @Test @MainActor func masteryChangeForAnotherKnowledgePointIsStillAdopted() async {
        let tutor = MasteryTutorService()
        tutor.changePayloads = [MasteryFixture.changes(before: 0.2, after: 0.25, evidence: 4,
                                                       pointId: "kp_something_else")]
        let model = RemoteTutorViewModel(service: tutor)
        await model.load()
        model.select("B")
        await model.submit()
        #expect(model.sessionStartMastery == 0.2)
        #expect(model.currentMastery == 0.25)
    }

    static func overview(score: Int) -> MasteryOverview {
        MasteryOverview(score: score, percent: 0.6045, weightedMastery: 0.6045, coverage: 1,
                        coveredCount: 17, pointCount: 17, evidenceCount: 103, weakest: [])
    }
}

enum MasteryFixture {
    static let emptyChanges = "[]"

    static func changes(before: Double, after: Double, evidence: Int,
                        pointId: String = "kp_mastery") -> String {
        """
        [{"knowledge_point_id":"\(pointId)","name":"导数与函数性质综合应用",
          "before":\(before),"after":\(after),"delta":\(after - before),"evidence_count":\(evidence)}]
        """
        .replacingOccurrences(of: "\n", with: "")
    }
}

@MainActor
private final class StubMasteryService: MasteryOverviewServing {
    private let overview: MasteryOverview?
    private let error: Error?

    init(overview: MasteryOverview) {
        self.overview = overview
        error = nil
    }

    init(error: Error) {
        overview = nil
        self.error = error
    }

    func fetchOverview() async throws -> MasteryOverview {
        if let error { throw error }
        guard let overview else { throw NetworkError.invalidResponse }
        return overview
    }
}

@MainActor
private final class MasteryTutorService: TutorRemoteServing {
    var changePayloads: [String] = []
    var completesImmediately = false
    private var submissions = 0

    func createSession(key: String) async throws -> TutorSessionDTO {
        try TutorJSON.decoder.decode(TutorSessionDTO.self, from: Data("""
        {"tutor_session_id":"tut_mastery","knowledge_point_id":"kp_mastery",
         "knowledge_point_name":"导数与函数性质综合应用","difficulty":0.9,"completed":false,
         "knowledge_changes":[],
         "turn":{"turn_id":"turn_1","seq":1,"turn_type":"concept_question",
                 "text":"已知 h(x)=ae^x-x^2/2+x",
                 "choices":[{"key":"A","text":"e^3"},{"key":"B","text":"1/(2e^(3/2))"}],
                 "allow_free_text":false,"phase":"diagnose",
                 "progress":{"step":1,"total_steps":6,"percent":0.166},
                 "completed":false,"question_id":"q_1","strategy":null,"remedial_depth":0,
                 "answer_reveal":null,"created_at":"2026-10-02T12:00:00+00:00"}}
        """.utf8))
    }

    func fetchSession(id: String) async throws -> TutorSessionDTO {
        try await createSession(key: "restore")
    }

    func submit(sessionId: String, selectedKey: String?, text: String?, key: String,
                onEvent: @escaping @MainActor (TutorStreamEvent) -> Void) async throws -> TutorTurnResponseDTO {
        submissions += 1
        let changes = changePayloads.indices.contains(submissions - 1)
            ? changePayloads[submissions - 1]
            : MasteryFixture.emptyChanges
        let completed = completesImmediately
        let json = """
        {"tutor_session_id":"tut_mastery",
         "evaluation":{"correctness":"correct","is_correct":true,"chosen_key":"A","expected_key":"A",
                       "feedback":"很好","explanation":null,
                       "strategy":"\(completed ? "finish" : "advance")",
                       "remedial_depth":0,"remedial_exhausted":false},
         "turn":{"turn_id":"turn_\(submissions + 1)","seq":\(submissions + 1),
                 "turn_type":"\(completed ? "summary" : "guided_practice")",
                 "text":"h(x)=ae^x-x^2/2+x",
                 "choices":[{"key":"A","text":"e^3"},{"key":"B","text":"2/e^3"}],
                 "allow_free_text":false,"phase":"\(completed ? "completed" : "guided_practice")",
                 "progress":{"step":1,"total_steps":6,"percent":0.166},
                 "completed":\(completed),"question_id":"q_\(submissions + 1)",
                 "strategy":"\(completed ? "finish" : "advance")","remedial_depth":0,
                 "answer_reveal":null,"created_at":"2026-10-02T12:00:00+00:00"},
         "phase":"\(completed ? "completed" : "guided_practice")","completed":\(completed),
         "progress":{"step":1,"total_steps":6,"percent":0.166},
         "student_understanding":0.9,
         "knowledge_changes":\(changes)}
        """
        return try TutorJSON.decoder.decode(TutorTurnResponseDTO.self, from: Data(json.utf8))
    }
}
