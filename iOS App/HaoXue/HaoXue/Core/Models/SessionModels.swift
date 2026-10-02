import Foundation

enum ChoiceID: String, Equatable, CaseIterable {
    case A, B, C, D
}

struct TutorChoice: Equatable {
    let id: ChoiceID
    let text: String
}

enum TutorSource: Equatable {
    case knowledgePoint(String)
    case wrongQuestion(String)
    case uploadedQuestion(String)
    case recommendation(String)
}

enum TutorPhase: Equatable {
    case diagnose, teach, conceptCheck, guidedPractice, independentPractice, completed
    case unknown(String)

    init(rawValue: String) {
        switch rawValue {
        case "diagnose": self = .diagnose
        case "teach": self = .teach
        case "concept_check": self = .conceptCheck
        case "guided_practice": self = .guidedPractice
        case "independent_practice": self = .independentPractice
        case "completed": self = .completed
        default: self = .unknown(rawValue)
        }
    }
}

struct TutorSession: Equatable {
    let id: String
    let source: TutorSource
    let knowledgePointID: String
    let currentTurn: TutorTurn
}

struct TutorTurn: Equatable {
    let id: String
    let type: String
    let text: String
    let choices: [TutorChoice]?
    let phase: TutorPhase
    let progress: Double?
    let completed: Bool
    let knowledgeChange: KnowledgeChange?
}

struct PracticeSession: Equatable {
    let id: String
    let currentQuestion: PracticeQuestion?
    let progress: Double?
    let completed: Bool
    let result: PracticeResult?
}

struct PracticeQuestion: Equatable {
    let id: String
    let content: String
    var choices: [TutorChoice] = []
    var knowledgePointIDs: [String] = []
}

struct PracticeResult: Equatable {
    let isCorrect: Bool
    let explanation: String
    let knowledgeChange: KnowledgeChange?
    let nextAction: String?
}
