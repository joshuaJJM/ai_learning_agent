import Foundation

/// Poll status for one analysis. Decoding never fails: a status this build does
/// not know about degrades to `.unknown` instead of breaking the whole poll
/// (the backend grew `retrying` stages once already — contract drift must not
/// turn a live demo into "analysis failed").
enum AnalysisPhase: Equatable, Decodable {
    case queued, processing, completed, failed
    case unknown(String)

    init(rawValue: String) {
        switch rawValue {
        case "queued": self = .queued
        case "processing": self = .processing
        case "completed": self = .completed
        case "failed": self = .failed
        default: self = .unknown(rawValue)
        }
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        self.init(rawValue: try container.decode(String.self))
    }

    var rawValue: String {
        switch self {
        case .queued: "queued"
        case .processing: "processing"
        case .completed: "completed"
        case .failed: "failed"
        case .unknown(let raw): raw
        }
    }
}

/// `retrying` is a third state, not a failure: the backend is switching to a
/// backup model while the task keeps making progress.
enum AnalysisStageState: Equatable {
    case done, active, retrying, pending, failed
    case unknown(String)

    init(rawValue: String) {
        switch rawValue {
        case "done": self = .done
        case "active": self = .active
        case "retrying": self = .retrying
        case "pending": self = .pending
        case "failed": self = .failed
        default: self = .unknown(rawValue)
        }
    }

    var rawValue: String {
        switch self {
        case .done: "done"
        case .active: "active"
        case .retrying: "retrying"
        case .pending: "pending"
        case .failed: "failed"
        case .unknown(let raw): raw
        }
    }

    var isRetrying: Bool { self == .retrying }
}

struct AnalysisStage: Decodable, Identifiable, Equatable {
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
        state = AnalysisStageState(rawValue: try values.decode(String.self, forKey: .state))
        labelZH = try values.decodeIfPresent(String.self, forKey: .labelZH)
            ?? values.decode(String.self, forKey: .labelZh)
    }
}

struct AnalysisProgress: Decodable, Equatable {
    let percent: Double
    let currentStageKey: String?
    let currentStageLabelZH: String?
    let stages: [AnalysisStage]
    /// Server-reported fallback (model degradation) state. `retryNote` is
    /// already display-ready Chinese text — never rebuild it on the client.
    let retrying: Bool
    let retryNote: String?
    enum CodingKeys: String, CodingKey {
        case percent, stages, retrying
        case currentStageKey = "current_stage_key"
        case currentStageLabelZH = "current_stage_label_zh"
        case retryNote = "retry_note"
        case convertedStageKey = "currentStageKey"
        case convertedStageLabel = "currentStageLabelZh"
        case convertedRetryNote = "retryNote"
    }

    init(percent: Double, currentStageKey: String?, currentStageLabelZH: String?,
         stages: [AnalysisStage], retrying: Bool = false, retryNote: String? = nil) {
        self.percent = percent
        self.currentStageKey = currentStageKey
        self.currentStageLabelZH = currentStageLabelZH
        self.stages = stages
        self.retrying = retrying
        self.retryNote = retryNote
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        percent = try values.decode(Double.self, forKey: .percent)
        stages = try values.decode([AnalysisStage].self, forKey: .stages)
        retrying = try values.decodeIfPresent(Bool.self, forKey: .retrying) ?? false
        // Decoded through two coders: the raw snake_case one (poll struct) and
        // `BackendJSON` with `.convertFromSnakeCase` (completed result DTO).
        retryNote = try values.decodeIfPresent(String.self, forKey: .retryNote)
            ?? values.decodeIfPresent(String.self, forKey: .convertedRetryNote)
        currentStageKey = try values.decodeIfPresent(String.self, forKey: .currentStageKey)
            ?? values.decodeIfPresent(String.self, forKey: .convertedStageKey)
        currentStageLabelZH = try values.decodeIfPresent(String.self, forKey: .currentStageLabelZH)
            ?? values.decodeIfPresent(String.self, forKey: .convertedStageLabel)
    }

    /// True while any stage — or the progress payload itself — reports a retry.
    var isRetrying: Bool { retrying || stages.contains { $0.state.isRetrying } }
}

struct AnalysisFailure: Decodable {
    let errorCode: String
    let message: String?
    enum CodingKeys: String, CodingKey {
        case errorCode = "error_code", message
        // `BackendJSON` converts snake_case before matching keys, so both forms
        // are needed depending on which decoder reads the payload.
        case convertedErrorCode = "errorCode"
    }

    init(errorCode: String, message: String?) {
        self.errorCode = errorCode
        self.message = message
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        errorCode = try values.decodeIfPresent(String.self, forKey: .errorCode)
            ?? values.decode(String.self, forKey: .convertedErrorCode)
        message = try values.decodeIfPresent(String.self, forKey: .message)
    }
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
