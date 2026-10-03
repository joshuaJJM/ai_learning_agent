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

/// The server's verdict for one question. Five distinct values since the
/// backend split "did not answer" from "could not verify the answer":
///
/// - `correct` / `wrong` / `partial` — counted toward mastery;
/// - `unanswered` — the student left it blank (or it was unreadable);
/// - `unknown` — the two models disagreed, so the answer is not trusted.
///
/// `unanswered` and `unknown` must never be merged in the UI, and neither
/// counts toward mastery. The verdict always comes from the server; the client
/// never derives it. An unrecognised value degrades to `.other` so a future
/// backend addition cannot break decoding.
enum QuestionCorrectness: Equatable {
    case correct, wrong, partial, unanswered, unknown
    case other(String)

    init(rawValue: String) {
        switch rawValue {
        case "correct": self = .correct
        case "wrong": self = .wrong
        case "partial": self = .partial
        case "unanswered": self = .unanswered
        case "unknown": self = .unknown
        default: self = .other(rawValue)
        }
    }

    var rawValue: String {
        switch self {
        case .correct: "correct"
        case .wrong: "wrong"
        case .partial: "partial"
        case .unanswered: "unanswered"
        case .unknown: "unknown"
        case .other(let raw): raw
        }
    }

    /// Whether the backend counted this question toward mastery/Evidence.
    var countsTowardMastery: Bool {
        switch self {
        case .correct, .wrong, .partial: true
        case .unanswered, .unknown, .other: false
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
