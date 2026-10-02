import Foundation

enum AnalysisStatus: Equatable {
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
}

struct UploadAnalysis: Equatable {
    let id: String
    let status: AnalysisStatus
    let stageDescription: String?
    var questions: [QuestionResult] = []
    var knowledgeChanges: [KnowledgeChange] = []
    let recommendation: String?
    let errorCode: String?
}

struct QuestionResult: Equatable {
    let id: String
    let content: String
    var choices: [TutorChoice] = []
    let studentAnswer: ChoiceID?
    let correctAnswer: ChoiceID?
    let isCorrect: Bool?
    var knowledgePointIDs: [String] = []
    let diagnosis: String?
}
