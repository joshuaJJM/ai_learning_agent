import Testing
@testable import HaoXue

@MainActor
struct DomainBoundaryTests {
    @Test func unknownStatesPreserveRawValue() {
        #expect(AnalysisStatus(rawValue: "future_status") == .unknown("future_status"))
        #expect(TutorPhase(rawValue: "future_phase") == .unknown("future_phase"))
    }

    @Test func missingMasteryRemainsAbsent() {
        let point = KnowledgePoint(id: "kp", name: "导数", mastery: nil,
                                   trend: nil, evidenceSummary: nil, recommendedAction: nil)
        #expect(point.mastery == nil)
    }

    @Test func knownStatesRetainTheirSemantics() {
        #expect(AnalysisStatus(rawValue: "queued") == .queued)
        #expect(AnalysisStatus(rawValue: "processing") == .processing)
        #expect(AnalysisStatus(rawValue: "completed") == .completed)
        #expect(AnalysisStatus(rawValue: "failed") == .failed)
        #expect(TutorPhase(rawValue: "diagnose") == .diagnose)
        #expect(TutorPhase(rawValue: "teach") == .teach)
        #expect(TutorPhase(rawValue: "concept_check") == .conceptCheck)
        #expect(TutorPhase(rawValue: "guided_practice") == .guidedPractice)
        #expect(TutorPhase(rawValue: "independent_practice") == .independentPractice)
        #expect(TutorPhase(rawValue: "completed") == .completed)
    }
}
