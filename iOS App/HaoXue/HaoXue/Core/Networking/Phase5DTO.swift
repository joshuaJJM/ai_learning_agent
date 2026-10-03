import Foundation

enum BackendJSON {
    static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let value = try decoder.singleValueContainer().decode(String.self)
            let fractional = ISO8601DateFormatter()
            fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let standard = ISO8601DateFormatter()
            guard let date = fractional.date(from: value) ?? standard.date(from: value) else {
                throw DecodingError.dataCorruptedError(in: try decoder.singleValueContainer(),
                                                       debugDescription: "Invalid ISO-8601 date: \(value)")
            }
            return date
        }
        return decoder
    }

    static var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }
}

struct BackendErrorDTO: Decodable, Error {
    let errorCode: String
    let message: String
    let requestId: String?
    let details: [String: JSONValue]?
}

indirect enum JSONValue: Decodable {
    case string(String), number(Double), bool(Bool), object([String: JSONValue])
    case array([JSONValue]), null

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if value.decodeNil() { self = .null }
        else if let item = try? value.decode(Bool.self) { self = .bool(item) }
        else if let item = try? value.decode(Double.self) { self = .number(item) }
        else if let item = try? value.decode(String.self) { self = .string(item) }
        else if let item = try? value.decode([String: JSONValue].self) { self = .object(item) }
        else { self = .array(try value.decode([JSONValue].self)) }
    }
}

struct ErrorCodeCatalogDTO: Decodable {
    struct Item: Decodable {
        let errorCode: String
        let httpStatus: Int
        let description: String
    }
    let count: Int
    let codes: [String]
    let items: [Item]
}

struct KnowledgePointCatalogDTO: Decodable {
    struct Item: Decodable {
        let id: String
        let name: String
        let description: String?
    }
    let count: Int
    let items: [Item]
}

struct NextActionDTO: Decodable {
    let action: String
    let title: String
    let reason: String
    let ctaLabel: String
    let knowledgePointId: String?
    let knowledgePointName: String?
    let wrongQuestionId: String?
}

struct KnowledgeChangeDTO: Decodable {
    let knowledgePointId: String
    let name: String
    let before: Double
    let after: Double
    let delta: Double
    let evidenceCount: Int
}

struct KnowledgeSummaryDTO: Decodable {
    let knowledgePointId: String
    let name: String
    let mastery: Double
    let confidence: Double
    let evidenceCount: Int
    let trend: String
    let isWeak: Bool
}

struct WrongQuestionSummaryDTO: Decodable {
    let wrongQuestionId: String
    let questionId: String
    let questionNumber: String
    let questionContent: String
    let knowledgePointId: String?
    let knowledgePointName: String?
    let errorType: String?
    let errorLabel: String?
    let status: String
    let createdAt: Date
}

struct WrongQuestionListDTO: Decodable {
    let userId: String
    let total: Int
    let items: [WrongQuestionSummaryDTO]
}

struct WrongQuestionPatchDTO: Encodable {
    let status: String?
    let favorite: Bool?
}

struct WrongQuestionDetailDTO: Decodable {
    let wrongQuestionId: String
    let questionId: String
    let questionNumber: String
    let questionType: String
    let questionContent: String
    let choices: [String: String]
    let studentAnswer: String?
    let correctAnswer: String?
    let explanation: String?
    let correctness: String
    let knowledgePointId: String?
    let knowledgePointName: String?
    let errorType: String?
    let errorLabel: String?
    let diagnosis: String
    let imageUrl: URL?
    let sourceType: String?
    let sourceId: String?
    let sourceName: String?
    let status: String
    let favorite: Bool
    let createdAt: Date
    let updatedAt: Date
    let canStartTutor: Bool
}

struct HomeResponseDTO: Decodable {
    struct Activity: Decodable {
        let activityType: String
        let title: String
        let subtitle: String
        let referenceId: String?
        let occurredAt: Date
    }
    struct Stats: Decodable {
        let totalEvidence: Int
        let homeworkCount: Int
        let wrongQuestionOpen: Int
        let tutorSessionCount: Int
        let practiceAttemptCount: Int
        let streakDays: Int
    }
    let userId: String
    let greeting: String
    let nextAction: NextActionDTO
    let knowledgeSummary: [KnowledgeSummaryDTO]
    let weakest: KnowledgeSummaryDTO?
    let wrongQuestionCount: Int
    let recentWrongQuestions: [WrongQuestionSummaryDTO]
    let recentActivities: [Activity]
    let stats: Stats
    let updatedAt: Date
}

struct KnowledgePointRefDTO: Decodable {
    let knowledgePointId: String
    let name: String
    let weight: Double
}

struct QuestionResultDTO: Decodable {
    let questionId: String
    let questionNumber: String
    let questionType: String
    let questionContent: String
    let choices: [String: String]
    let studentAnswer: String?
    let correctAnswer: String?
    let correctness: String
    let knowledgePoints: [KnowledgePointRefDTO]
    let errorType: String?
    let errorLabel: String?
    let diagnosis: String
    let explanation: String?
    let confidence: Double
    let difficulty: Double
    let imageUrl: URL?
}

struct AnalysisResultDTO: Decodable {
    let analysisId: String
    let batchNumber: Int?
    let status: String
    let progress: AnalysisProgress?
    let homeworkId: String?
    let userId: String
    let subject: String
    let topic: String?
    let sourceName: String?
    let bookId: String?
    let imageCount: Int
    let questions: [String]
    let questionResults: [QuestionResultDTO]
    let correctCount: Int
    let wrongCount: Int
    let partialCount: Int
    let unknownCount: Int
    let knowledgeChanges: [KnowledgeChangeDTO]
    let newWrongQuestions: [WrongQuestionSummaryDTO]
    let nextAction: NextActionDTO?
    let error: BackendErrorDTO?
    let warnings: [String]
    let generatedBy: String?
    let createdAt: Date
    let updatedAt: Date
    let finishedAt: Date?
}

struct KnowledgeTreeDTO: Decodable {
    struct Node: Decodable {
        let knowledgePointId: String
        let name: String
        let description: String?
        let mastery: Double
        let confidence: Double
        let evidenceCount: Int
        let trend: String
        let children: [Node]?
    }
    struct WeakPoint: Decodable {
        let knowledgePointId: String
        let name: String
        let mastery: Double
        let confidence: Double
        let priority: Double
        let reason: String
    }
    let userId: String
    let subject: String?
    let updatedAt: Date
    let tree: [Node]
    let weakest: [WeakPoint]
    let nextAction: NextActionDTO?
    let totalEvidence: Int
}

struct EvidenceDTO: Decodable {
    let evidenceId: String
    let knowledgePointId: String
    let sourceType: String
    let sourceId: String?
    let questionId: String?
    let questionStemHash: String?
    let result: String
    let confidence: Double
    let errorType: String?
    let errorLabel: String?
    let answerExcerpt: String?
    let detail: String?
    let createdAt: Date
}

struct KnowledgeDetailDTO: Decodable {
    struct Performance: Decodable {
        let occurredAt: Date
        let result: String
        let sourceType: String
        let questionId: String?
    }
    struct ErrorPattern: Decodable {
        let errorType: String
        let label: String
        let count: Int
        let share: Double
    }
    let knowledgePointId: String
    let name: String
    let description: String
    let subject: String?
    let mastery: Double
    let confidence: Double
    let trend: String
    let evidenceCount: Int
    let correctCount: Int
    let partialCount: Int
    let wrongCount: Int
    let recentPerformance: [Performance]
    let errorPatterns: [ErrorPattern]
    let evidence: [EvidenceDTO]
    let prerequisites: [KnowledgePointRefDTO]
    let masteryExplanation: String
    let recommendedAction: NextActionDTO?
    let updatedAt: Date
}
