import Foundation

enum AnalysisPhase: String, Decodable { case queued, processing, completed, failed }
enum AnalysisStageState: String, Decodable { case done, active, pending, failed }

struct AnalysisStage: Decodable, Identifiable {
    let key: String
    let labelZH: String
    let state: AnalysisStageState
    var id: String { key }
    enum CodingKeys: String, CodingKey {
        case key, state, labelZH = "label_zh", labelZh
    }

    init(key: String, labelZH: String, state: AnalysisStageState) {
        self.key = key
        self.labelZH = labelZH
        self.state = state
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        key = try values.decode(String.self, forKey: .key)
        state = try values.decode(AnalysisStageState.self, forKey: .state)
        labelZH = try values.decodeIfPresent(String.self, forKey: .labelZH)
            ?? values.decode(String.self, forKey: .labelZh)
    }
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
        case convertedStageKey = "currentStageKey"
        case convertedStageLabel = "currentStageLabelZh"
    }

    init(percent: Double, currentStageKey: String?, currentStageLabelZH: String?,
         stages: [AnalysisStage]) {
        self.percent = percent
        self.currentStageKey = currentStageKey
        self.currentStageLabelZH = currentStageLabelZH
        self.stages = stages
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        percent = try values.decode(Double.self, forKey: .percent)
        stages = try values.decode([AnalysisStage].self, forKey: .stages)
        currentStageKey = try values.decodeIfPresent(String.self, forKey: .currentStageKey)
            ?? values.decodeIfPresent(String.self, forKey: .convertedStageKey)
        currentStageLabelZH = try values.decodeIfPresent(String.self, forKey: .currentStageLabelZH)
            ?? values.decodeIfPresent(String.self, forKey: .convertedStageLabel)
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
    let result: HomeworkAnalysisResult?
    enum CodingKeys: String, CodingKey {
        case analysisID = "analysis_id", status, progress, error
    }

    init(analysisID: String, status: AnalysisPhase, progress: AnalysisProgress?,
         error: AnalysisFailure?, result: HomeworkAnalysisResult? = nil) {
        self.analysisID = analysisID
        self.status = status
        self.progress = progress
        self.error = error
        self.result = result
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        analysisID = try values.decode(String.self, forKey: .analysisID)
        status = try values.decode(AnalysisPhase.self, forKey: .status)
        progress = try values.decodeIfPresent(AnalysisProgress.self, forKey: .progress)
        error = try values.decodeIfPresent(AnalysisFailure.self, forKey: .error)
        result = nil
    }

    static func decodeBackend(_ data: Data) throws -> AnalysisResponse {
        let poll = try JSONDecoder().decode(AnalysisResponse.self, from: data)
        guard poll.status == .completed else { return poll }
        let completed = try BackendJSON.decoder.decode(AnalysisResultDTO.self, from: data)
        return AnalysisResponse(analysisID: poll.analysisID, status: poll.status,
                                progress: poll.progress, error: poll.error,
                                result: Phase5Mapper().analysis(completed))
    }
}

struct CreateAnalysisResponse: Decodable {
    let analysisID: String
    let status: AnalysisPhase
    let createdAt: Date?
    enum CodingKeys: String, CodingKey {
        case analysisID = "analysis_id", status, createdAt = "created_at"
    }

    init(analysisID: String, status: AnalysisPhase, createdAt: Date? = nil) {
        self.analysisID = analysisID
        self.status = status
        self.createdAt = createdAt
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        analysisID = try values.decode(String.self, forKey: .analysisID)
        status = try values.decode(AnalysisPhase.self, forKey: .status)
        if let raw = try values.decodeIfPresent(String.self, forKey: .createdAt) {
            let fractional = ISO8601DateFormatter()
            fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            createdAt = fractional.date(from: raw) ?? ISO8601DateFormatter().date(from: raw)
            if createdAt == nil {
                throw DecodingError.dataCorruptedError(forKey: .createdAt, in: values,
                                                       debugDescription: "Invalid ISO-8601 date")
            }
        } else {
            createdAt = nil
        }
    }
}
