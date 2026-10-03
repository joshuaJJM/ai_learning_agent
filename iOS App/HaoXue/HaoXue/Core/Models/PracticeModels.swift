import Foundation

// Practice domain models. Every authoritative learning value comes from the server:
// correctness, correct answer, knowledge/tag changes, completion and next action.
// iOS never derives or recomputes them.

enum PracticeSessionStatus: Equatable {
    case active, completed, abandoned
    case unknown(String)

    init(rawValue: String) {
        switch rawValue {
        case "active": self = .active
        case "completed": self = .completed
        case "abandoned": self = .abandoned
        default: self = .unknown(rawValue)
        }
    }
}

enum PracticeSelectionMode: Equatable {
    case tag, knowledgePoint
    case unknown(String)

    init(rawValue: String) {
        switch rawValue {
        case "tag": self = .tag
        case "knowledge_point": self = .knowledgePoint
        default: self = .unknown(rawValue)
        }
    }
}

struct PracticeChoice: Equatable, Identifiable {
    let key: String
    let text: String
    var id: String { key }
}

struct PracticeQuestion: Equatable {
    struct KnowledgePoint: Equatable {
        let id: String
        let name: String
        let weight: Double
    }
    let id: String
    let number: String
    let stem: String
    let choices: [PracticeChoice]
    let difficulty: Double
    let knowledgePoints: [KnowledgePoint]
    let tags: [String]
    let index: Int
    let total: Int
}

struct PracticeSessionState: Equatable {
    let id: String
    let userID: String
    let knowledgePointID: String?
    let knowledgePointName: String?
    let status: PracticeSessionStatus
    let total: Int
    let answered: Int
    let correct: Int
    let nextQuestion: PracticeQuestion?
    let selectionMode: PracticeSelectionMode
    let targetTag: String?
    let targetTagScore: Int?
    let pickedTags: [String]
    let createdAt: Date
}

struct PracticeTagChange: Equatable {
    let questionID: String
    let isCorrect: Bool
    let tags: [String]
    /// Score for each tag **after** this answer (0–100, server-computed).
    let scores: [String: Int]
    /// Change since before this answer, per tag (0–100 units).
    let deltas: [String: Int]

    init(questionID: String, isCorrect: Bool, tags: [String] = [],
         scores: [String: Int] = [:], deltas: [String: Int] = [:]) {
        self.questionID = questionID
        self.isCorrect = isCorrect
        self.tags = tags
        self.scores = scores
        self.deltas = deltas
    }

    func delta(for tag: String) -> Int? { deltas[tag] }
}

struct PracticeAnswerOutcome: Equatable {
    let sessionID: String
    let questionID: String
    let correctness: String
    let isCorrect: Bool
    let correctAnswer: String
    let explanation: String?
    let knowledgeChanges: [KnowledgeChange]
    let tagChange: PracticeTagChange?
    let replayed: Bool
    let nextQuestion: PracticeQuestion?
    let sessionCompleted: Bool
    let answered: Int
    let correct: Int
    let total: Int
    let nextAction: NextLearningAction?
}
