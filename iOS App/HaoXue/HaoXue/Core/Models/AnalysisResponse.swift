import Foundation

enum AnalysisPhase: String, Decodable { case queued, processing, completed, failed }
enum AnalysisStageState: String, Decodable { case done, active, pending, failed }

struct AnalysisStage: Decodable, Identifiable {
    let key: String
    let labelZH: String
    let state: AnalysisStageState
    var id: String { key }
    enum CodingKeys: String, CodingKey { case key, state, labelZH = "label_zh" }
}

struct AnalysisProgress: Decodable {
    let percent: Double
    let currentStageKey: String?
    let currentStageLabelZH: String?
    let stages: [AnalysisStage]
    enum CodingKeys: String, CodingKey {
        case percent, stages
        case currentStageKey = "current_stage_key"
        case currentStageLabelZH = "current_stage_label_zh"
    }
}

struct AnalysisFailure: Decodable {
    let errorCode: String
    let message: String?
    enum CodingKeys: String, CodingKey { case errorCode = "error_code", message }
}

struct AnalysisResponse: Decodable {
    let analysisID: String
    let status: AnalysisPhase
    let progress: AnalysisProgress?
    let error: AnalysisFailure?
    enum CodingKeys: String, CodingKey {
        case analysisID = "analysis_id", status, progress, error
    }
}

struct CreateAnalysisResponse: Decodable {
    let analysisID: String
    let status: AnalysisPhase
    enum CodingKeys: String, CodingKey { case analysisID = "analysis_id", status }
}
