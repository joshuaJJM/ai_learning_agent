import Foundation

// Wire schemas for the live Practice contract.
// Source of truth: backend `docs/API.md` §6 / §6.5, `app/schemas.py`, live OpenAPI.
// Backend identifiers stay opaque strings; the question payload never carries the answer.

struct PracticeChoiceDTO: Decodable, Equatable {
    let key: String
    let text: String
}

struct PracticeQuestionDTO: Decodable {
    let questionId: String
    let questionNumber: String
    let stem: String
    let choices: [PracticeChoiceDTO]
    let difficulty: Double
    let knowledgePoints: [KnowledgePointRefDTO]?
    let tags: [String]?
    let index: Int
    let total: Int
}

struct PracticeSessionCreateRequestDTO: Encodable {
    let knowledgePointId: String?
    let difficulty: Double?
    let bookId: String?
    let count: Int
    let clientRequestId: String
}

struct PracticeSessionDTO: Decodable {
    let practiceSessionId: String
    let userId: String
    let knowledgePointId: String?
    let knowledgePointName: String?
    let status: String
    let total: Int
    let answered: Int
    let correct: Int
    let nextQuestion: PracticeQuestionDTO?
    let selectionMode: String?
    let targetTag: String?
    let targetTagScore: Int?
    let pickedTags: [String]?
    let createdAt: Date
}

struct PracticeAnswerRequestDTO: Encodable {
    let questionId: String
    let selectedKey: String?
    let answerText: String?
    let clientRequestId: String
}

/// Tag statistics are derived from Evidence on the server (Beta posterior with a
/// pessimistic lower bound) since contract v2, so there is no single ±1 `delta`
/// any more: each tag gets its own "score after" and "change since before".
struct PracticeTagChangeDTO: Decodable, Equatable {
    let questionId: String
    let isCorrect: Bool
    let tags: [String]
    let tagScores: [String: Int]
    let tagDeltas: [String: Int]
    enum CodingKeys: String, CodingKey {
        case questionId, isCorrect, tags, tagScores, tagDeltas
    }

    init(questionId: String, isCorrect: Bool, tags: [String] = [],
         tagScores: [String: Int] = [:], tagDeltas: [String: Int] = [:]) {
        self.questionId = questionId
        self.isCorrect = isCorrect
        self.tags = tags
        self.tagScores = tagScores
        self.tagDeltas = tagDeltas
    }

    // Every optional collection may be omitted or empty; the v1 `delta` field is
    // gone, and a missing key must never fail the whole answer response.
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        questionId = try values.decode(String.self, forKey: .questionId)
        isCorrect = try values.decode(Bool.self, forKey: .isCorrect)
        tags = try values.decodeIfPresent([String].self, forKey: .tags) ?? []
        tagScores = try values.decodeIfPresent([String: Int].self, forKey: .tagScores) ?? [:]
        tagDeltas = try values.decodeIfPresent([String: Int].self, forKey: .tagDeltas) ?? [:]
    }
}

struct PracticeAnswerResponseDTO: Decodable {
    let practiceSessionId: String
    let questionId: String
    let correctness: String
    let isCorrect: Bool
    let correctAnswer: String
    let explanation: String?
    let knowledgeChanges: [KnowledgeChangeDTO]?
    let tagChanges: PracticeTagChangeDTO?
    let replayed: Bool?
    let nextQuestion: PracticeQuestionDTO?
    let sessionCompleted: Bool?
    let answered: Int?
    let correct: Int?
    let total: Int?
    let nextAction: NextActionDTO?
}
