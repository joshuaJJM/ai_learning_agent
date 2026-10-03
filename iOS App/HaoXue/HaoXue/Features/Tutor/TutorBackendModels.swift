import Foundation

enum TutorJSON {
    static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    static var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }
}

struct TutorProgressDTO: Decodable, Equatable {
    let step: Int
    let totalSteps: Int
    let percent: Double
}

struct TutorChoiceDTO: Decodable, Equatable, Identifiable {
    let key: String
    let text: String
    var id: String { key }
}

struct TutorRevealedAnswerDTO: Decodable, Equatable {
    let questionId: String?
    let questionText: String?
    let correctKey: String
    let explanation: String?
}

struct TutorAnswerRevealDTO: Decodable, Equatable {
    let current: TutorRevealedAnswerDTO?
    let origin: TutorRevealedAnswerDTO?
}

struct TutorTurnDTO: Decodable, Equatable {
    let turnId: String
    let seq: Int
    let turnType: String
    let text: String
    let choices: [TutorChoiceDTO]
    let allowFreeText: Bool
    let phase: String
    let progress: TutorProgressDTO
    let completed: Bool
    let questionId: String?
    let strategy: String?
    let remedialDepth: Int
    /// True when this turn revealed the answer because remediation hit its cap.
    /// It only ever *adds* an explanation card — `turnType` still decides the
    /// main content, because the session has already moved on by then.
    /// ("remedial_exhausted" was removed from the `turn_type` values.)
    let remedialExhausted: Bool?
    let answerReveal: TutorAnswerRevealDTO?
    let createdAt: String
}

struct TutorKnowledgeChangeDTO: Decodable, Equatable {
    let knowledgePointId: String
    let name: String
    let before: Double
    let after: Double
    let delta: Double
    let evidenceCount: Int
}

struct TutorEvaluationDTO: Decodable, Equatable {
    let correctness: String
    let isCorrect: Bool
    let chosenKey: String?
    let expectedKey: String?
    let feedback: String
    let explanation: String?
    let strategy: String
    let remedialDepth: Int
    let remedialExhausted: Bool
}

struct TutorSessionDTO: Decodable {
    let tutorSessionId: String
    let sourceType: String?
    let sourceId: String?
    let knowledgePointId: String?
    let knowledgePointName: String?
    let difficulty: Double
    let completed: Bool
    let turn: TutorTurnDTO?
    let knowledgeChanges: [TutorKnowledgeChangeDTO]
    let history: [TutorTurnDTO]?
    let nextAction: NextActionDTO?
}

struct TutorTurnResponseDTO: Decodable {
    let tutorSessionId: String
    let evaluation: TutorEvaluationDTO?
    let turn: TutorTurnDTO
    let phase: String
    let completed: Bool
    let progress: TutorProgressDTO
    let studentUnderstanding: Double
    let knowledgeChanges: [TutorKnowledgeChangeDTO]
    let nextAction: NextActionDTO?
    let replayed: Bool?
}

struct TutorCreateRequestDTO: Encodable {
    let sourceType: String
    let knowledgePointId: String?
    let wrongQuestionId: String?
    let clientRequestId: String
}

struct TutorAnswerRequestDTO: Encodable {
    let selectedKey: String?
    let text: String?
    let selfReportedConfidence: String?
    let clientRequestId: String
    let answeringTurnId: String?
    let stream: Bool
}

struct TutorBackendErrorDTO: Decodable, Error {
    let errorCode: String
    let message: String
    let requestId: String?
}

struct TutorStreamMetaDTO: Decodable {
    let requestId: String
    let tutorSessionId: String
    let seq: Int
    let phase: String
    let turnType: String
    let remedialDepth: Int
}

struct TutorStreamDoneDTO: Decodable {
    let requestId: String
    let seq: Int
    let phase: String
    let completed: Bool
    let progress: TutorProgressDTO
    let studentUnderstanding: Double
}

struct TutorStreamDeltaDTO: Decodable {
    let content: String
}
