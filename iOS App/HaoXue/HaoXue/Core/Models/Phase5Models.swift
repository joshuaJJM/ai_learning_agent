import Foundation

struct NextLearningAction: Equatable {
    let kind: String
    let title: String
    let reason: String
    let buttonTitle: String
    let knowledgePointID: String?
    let knowledgePointName: String?
    let wrongQuestionID: String?
}

struct WrongQuestionSummary {
    let id: String
    let questionID: String
    let questionNumber: String
    let content: String
    let knowledgePointID: String?
    let knowledgePointName: String?
    let errorType: String?
    let errorLabel: String?
    let status: String
    let createdAt: Date
}

struct HomeSnapshot {
    struct KnowledgeSummary {
        let id: String
        let name: String
        let mastery: Double
        let confidence: Double
        let evidenceCount: Int
        let trend: String
        let isWeak: Bool
    }
    struct Activity {
        let type: String
        let title: String
        let subtitle: String
        let referenceID: String?
        let occurredAt: Date
    }
    struct Stats {
        let totalEvidence: Int
        let homeworkCount: Int
        let openWrongQuestionCount: Int
        let tutorSessionCount: Int
        let practiceAttemptCount: Int
        let streakDays: Int
    }
    let userID: String
    let greeting: String
    let nextAction: NextLearningAction
    let knowledgeSummary: [KnowledgeSummary]
    let weakest: KnowledgeSummary?
    let wrongQuestionCount: Int
    let recentWrongQuestions: [WrongQuestionSummary]
    let recentActivities: [Activity]
    let stats: Stats
    let updatedAt: Date
}

struct HomeworkAnalysisResult {
    struct Question {
        let id: String
        let number: String
        let type: String
        let content: String
        let choices: [String: String]
        let studentAnswer: String?
        let correctAnswer: String?
        let correctness: String
        let knowledgePoints: [(id: String, name: String, weight: Double)]
        let errorType: String?
        let errorLabel: String?
        let diagnosis: String
        let explanation: String?
        let confidence: Double
        let difficulty: Double
        let imageURL: URL?
    }
    let id: String
    let batchNumber: Int?
    let status: AnalysisStatus
    let progress: AnalysisProgress?
    let homeworkID: String?
    let userID: String
    let subject: String
    let topic: String?
    let sourceName: String?
    let bookID: String?
    let imageCount: Int
    let questionIDs: [String]
    let questions: [Question]
    let correctCount: Int
    let wrongCount: Int
    let partialCount: Int
    let unknownCount: Int
    let knowledgeChanges: [KnowledgeChange]
    let newWrongQuestions: [WrongQuestionSummary]
    let nextAction: NextLearningAction?
    let error: BackendErrorDTO?
    let warnings: [String]
    let generatedBy: String?
    let createdAt: Date
    let updatedAt: Date
    let finishedAt: Date?
    var totalCount: Int { questionIDs.count }
}

struct WrongQuestionDetail {
    let summary: WrongQuestionSummary
    let questionType: String
    let choices: [String: String]
    let studentAnswer: String?
    let correctAnswer: String?
    let explanation: String?
    let correctness: String
    let diagnosis: String
    let imageURL: URL?
    let sourceType: String?
    let sourceID: String?
    let sourceName: String?
    let favorite: Bool
    let updatedAt: Date
    let canStartTutor: Bool
}

struct KnowledgePointDetail {
    struct ErrorPattern {
        let type: String
        let label: String
        let count: Int
        let share: Double
    }
    struct Evidence {
        let id: String
        let sourceType: String
        let sourceID: String?
        let questionID: String?
        let questionStemHash: String?
        let result: String
        let confidence: Double
        let errorType: String?
        let errorLabel: String?
        let answerExcerpt: String?
        let detail: String?
        let createdAt: Date
    }
    let id: String
    let name: String
    let description: String
    let subject: String
    let mastery: Double
    let confidence: Double
    let trend: String
    let evidenceCount: Int
    let correctCount: Int
    let partialCount: Int
    let wrongCount: Int
    let recentPerformance: [(date: Date, result: String, sourceType: String, questionID: String?)]
    let errorPatterns: [ErrorPattern]
    let evidence: [Evidence]
    let prerequisites: [(id: String, name: String, weight: Double)]
    let masteryExplanation: String
    let recommendedAction: NextLearningAction?
    let updatedAt: Date
}

struct KnowledgeOverview {
    struct Node {
        let id: String
        let name: String
        let description: String
        let mastery: Double
        let confidence: Double
        let evidenceCount: Int
        let trend: String
        let children: [Node]
    }
    struct WeakPoint {
        let id: String
        let name: String
        let reason: String
    }
    let nodes: [Node]
    let weakest: [WeakPoint]
    let totalEvidence: Int
    let updatedAt: Date
    var weakestIDs: Set<String> { Set(weakest.map(\.id)) }
}
