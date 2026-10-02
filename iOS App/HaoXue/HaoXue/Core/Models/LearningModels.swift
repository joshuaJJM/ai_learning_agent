import Foundation

// Frontend semantics only; Backend owns authoritative values and wire schemas.
struct HomeState: Equatable {
    let nextStep: String
    var subjects: [SubjectSummary] = []
    var knowledgePoints: [KnowledgePoint] = []
    var recentWrongQuestions: [WrongQuestion] = []
    var recentChanges: [KnowledgeChange] = []
}

struct SubjectSummary: Equatable {
    let id: String
    let name: String
    let summary: String
}

struct KnowledgePoint: Equatable {
    let id: String
    let name: String
    let mastery: Double?
    let trend: String?
    let evidenceSummary: String?
    let recommendedAction: String?
}

struct KnowledgeChange: Equatable {
    let knowledgePointID: String
    let beforeMastery: Double?
    let afterMastery: Double?
    let summary: String
}

struct WrongQuestion: Equatable {
    let id: String
    let content: String
    let source: String
    let studentAnswer: String?
    let correctAnswer: String?
    var knowledgePointIDs: [String] = []
    let diagnosis: String?
    let timestamp: Date
}
