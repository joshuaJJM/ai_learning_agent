import Foundation
import Testing
@testable import HaoXue

@MainActor
struct KnowledgeDetailTests {
    private func fixture(_ name: String) throws -> Data {
        let directory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        return try Data(contentsOf: directory.appendingPathComponent("Fixtures/\(name).json"))
    }

    @Test func detailAndTreePreserveBackendMasteryAndEvidence() throws {
        let dto = try BackendJSON.decoder.decode(KnowledgeDetailDTO.self, from: fixture("KnowledgeDetail"))
        let detail = Phase5Mapper().knowledge(dto)
        #expect(detail.id == dto.knowledgePointId)
        #expect(detail.name == dto.name)
        #expect(detail.mastery == dto.mastery)
        #expect(detail.confidence == dto.confidence)
        #expect(detail.trend == dto.trend)
        #expect(detail.masteryExplanation == dto.masteryExplanation)
        #expect(detail.evidence.map(\.id) == dto.evidence.map(\.evidenceId))
        #expect(detail.evidence.first?.result == dto.evidence.first?.result)
        #expect(detail.recentPerformance.count == dto.recentPerformance.count)
        #expect(detail.recommendedAction?.knowledgePointID == dto.recommendedAction?.knowledgePointId)
        let service = TutorRemoteService(baseURL: URL(string: "http://fixture.invalid")!,
                                         knowledgePointID: detail.id)
        let request = try #require(service.makeCreateRequest(key: "knowledge-entry").httpBody)
        let body = try #require(JSONSerialization.jsonObject(with: request) as? [String: Any])
        #expect(body["source_type"] as? String == "knowledge_point")
        #expect(body["knowledge_point_id"] as? String == detail.id)

        let treeDTO = try BackendJSON.decoder.decode(KnowledgeTreeDTO.self, from: fixture("KnowledgeTree"))
        let overview = Phase5Mapper().knowledgeOverview(treeDTO)
        #expect(overview.nodes.count == treeDTO.tree.count)
        #expect(overview.nodes.first?.mastery == treeDTO.tree.first?.mastery)
        #expect(overview.weakestIDs == Set(treeDTO.weakest.map(\.knowledgePointId)))
    }

    @Test func sparseAndLongExplanationsStayAsProvided() throws {
        var raw = try #require(JSONSerialization.jsonObject(with: fixture("KnowledgeDetail")) as? [String: Any])
        raw["evidence"] = []
        raw["recent_performance"] = []
        raw["mastery_explanation"] = ""
        raw["name"] = String(repeating: "很长的知识点名称", count: 12)
        let sparse = try BackendJSON.decoder.decode(KnowledgeDetailDTO.self,
            from: JSONSerialization.data(withJSONObject: raw))
        let mapped = Phase5Mapper().knowledge(sparse)
        #expect(mapped.evidence.isEmpty)
        #expect(mapped.masteryExplanation.isEmpty)
        #expect(mapped.name.count > 50)
        #expect(mapped.mastery == sparse.mastery)

        raw["mastery_explanation"] = String(repeating: "证据说明很长。", count: 90)
        let original = try #require(JSONSerialization.jsonObject(with: fixture("KnowledgeDetail")) as? [String: Any])
        let firstEvidence = try #require((original["evidence"] as? [[String: Any]])?.first)
        raw["evidence"] = Array(repeating: firstEvidence, count: 30)
        let many = try BackendJSON.decoder.decode(KnowledgeDetailDTO.self,
            from: JSONSerialization.data(withJSONObject: raw))
        #expect(Phase5Mapper().knowledge(many).evidence.count == 30)
        #expect(Phase5Mapper().knowledge(many).masteryExplanation.count > 300)
        raw.removeValue(forKey: "mastery")
        #expect(throws: Error.self) {
            try BackendJSON.decoder.decode(KnowledgeDetailDTO.self,
                from: JSONSerialization.data(withJSONObject: raw))
        }
    }

    @Test func optionalOpenAPIFieldsCanBeAbsent() throws {
        var rawTree = try #require(JSONSerialization.jsonObject(with: fixture("KnowledgeTree")) as? [String: Any])
        rawTree.removeValue(forKey: "subject")
        var nodes = try #require(rawTree["tree"] as? [[String: Any]])
        var first = try #require(nodes.first)
        first.removeValue(forKey: "description")
        first.removeValue(forKey: "children")
        nodes[0] = first
        rawTree["tree"] = nodes
        let tree = try BackendJSON.decoder.decode(KnowledgeTreeDTO.self,
            from: JSONSerialization.data(withJSONObject: rawTree))
        let overview = Phase5Mapper().knowledgeOverview(tree)
        #expect(overview.nodes.first?.children.isEmpty == true)

        var rawDetail = try #require(JSONSerialization.jsonObject(with: fixture("KnowledgeDetail")) as? [String: Any])
        rawDetail.removeValue(forKey: "subject")
        let detail = try BackendJSON.decoder.decode(KnowledgeDetailDTO.self,
            from: JSONSerialization.data(withJSONObject: rawDetail))
        #expect(Phase5Mapper().knowledge(detail).id == detail.knowledgePointId)
    }

    @Test func detailLoadsRetriesAndRefreshes() async throws {
        let dto = try BackendJSON.decoder.decode(KnowledgeDetailDTO.self, from: fixture("KnowledgeDetail"))
        let provider = ScriptedKnowledgeProvider()
        provider.detail = Phase5Mapper().knowledge(dto)
        provider.related = []
        provider.detailFailures = 1
        let model = KnowledgeDetailViewModel(id: dto.knowledgePointId, provider: provider)
        await model.loadIfNeeded()
        #expect(model.phase == .failed)
        #expect(model.detail == nil)
        #expect(model.errorMessage != "raw server text")
        await model.refresh()
        #expect(model.phase == .loaded)
        #expect(model.detail?.mastery == dto.mastery)
        #expect(model.relatedWrongQuestions.isEmpty)
        await model.refresh()
        #expect(provider.detailCalls == 3)
    }

    @Test func overviewLoadsAndUsesBackendNodes() async throws {
        let tree = try BackendJSON.decoder.decode(KnowledgeTreeDTO.self, from: fixture("KnowledgeTree"))
        let provider = ScriptedKnowledgeProvider()
        provider.overview = Phase5Mapper().knowledgeOverview(tree)
        let model = KnowledgeOverviewViewModel(provider: provider)
        await model.loadIfNeeded()
        #expect(model.phase == .loaded)
        #expect(model.overview?.nodes.first?.id == tree.tree.first?.knowledgePointId)
    }

    @Test func overviewErrorRetriesAndRelatedWrongUsesKnowledgeID() async throws {
        let tree = try BackendJSON.decoder.decode(KnowledgeTreeDTO.self, from: fixture("KnowledgeTree"))
        let wrong = try BackendJSON.decoder.decode(WrongQuestionListDTO.self, from: fixture("WrongQuestions"))
        let detailDTO = try BackendJSON.decoder.decode(KnowledgeDetailDTO.self, from: fixture("KnowledgeDetail"))
        let provider = ScriptedKnowledgeProvider()
        provider.overview = Phase5Mapper().knowledgeOverview(tree)
        provider.overviewFailures = 1
        provider.detail = Phase5Mapper().knowledge(detailDTO)
        provider.related = wrong.items.map(Phase5Mapper().summary)
        let overviewModel = KnowledgeOverviewViewModel(provider: provider)
        await overviewModel.loadIfNeeded()
        #expect(overviewModel.phase == .failed)
        await overviewModel.refresh()
        #expect(overviewModel.phase == .loaded)
        let detailModel = KnowledgeDetailViewModel(id: detailDTO.knowledgePointId, provider: provider)
        await detailModel.loadIfNeeded()
        #expect(provider.relatedRequestedID == detailDTO.knowledgePointId)
        #expect(detailModel.relatedWrongQuestions.count == wrong.items.count)
    }

    @Test func evidenceLabelsRespectAllBackendResults() {
        #expect(KnowledgeEvidencePresentation.resultLabel("correct") == "回答正确")
        #expect(KnowledgeEvidencePresentation.resultLabel("partial") == "部分正确")
        #expect(KnowledgeEvidencePresentation.resultLabel("incorrect") == "回答错误")
        #expect(KnowledgeEvidencePresentation.resultLabel("unknown") == "待确认")
        #expect(KnowledgeEvidencePresentation.sourceLabel("homework") == "作业分析")
        #expect(KnowledgeEvidencePresentation.sourceLabel("tutor") == "学习检查")
    }

    @Test func typedKnowledgeErrorsDoNotShowServerMessage() {
        for code in ["KNOWLEDGE_POINT_NOT_FOUND", "UNAUTHORIZED", "SERVICE_UNAVAILABLE", "INTERNAL_ERROR"] {
            let error = NetworkError.backend(code: code, message: "raw server text",
                                             requestID: nil, status: 500)
            #expect(KnowledgeError.message(for: error) != "raw server text")
        }
    }
}

@MainActor
private final class ScriptedKnowledgeProvider: KnowledgeDataProviding {
    var detail: KnowledgePointDetail?
    var overview: KnowledgeOverview?
    var related: [WrongQuestionSummary] = []
    var detailFailures = 0
    var overviewFailures = 0
    var detailCalls = 0
    var relatedRequestedID: String?
    func fetchKnowledgeDetail(id: String) async throws -> KnowledgePointDetail {
        detailCalls += 1
        if detailFailures > 0 {
            detailFailures -= 1
            throw NetworkError.backend(code: "KNOWLEDGE_POINT_NOT_FOUND", message: "raw server text",
                                       requestID: nil, status: 404)
        }
        return try #require(detail)
    }
    func fetchKnowledgeOverview() async throws -> KnowledgeOverview {
        if overviewFailures > 0 {
            overviewFailures -= 1
            throw NetworkError.backend(code: "SERVICE_UNAVAILABLE", message: "raw server text",
                                       requestID: nil, status: 503)
        }
        return try #require(overview)
    }
    func fetchRelatedWrongQuestions(knowledgePointID: String) async throws -> [WrongQuestionSummary] {
        relatedRequestedID = knowledgePointID
        return related
    }
}
