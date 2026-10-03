import Foundation

// Wire schema for manual answer confirmation.
// Source of truth: backend `docs/API.md` §2.2.3 (contract `8A-final`, commit 629f99e).

struct ConfirmAnswerRequestDTO: Encodable {
    let correctAnswer: String
    let clientRequestId: String
}

struct ConfirmAnswerResponseDTO: Decodable {
    struct ConfirmationDTO: Decodable {
        let source: String
        let confirmedAt: Date?
        /// What the AI originally said (for `unknown` questions: the
        /// `possible_answer` guess). Kept so a model mistake stays traceable.
        let originalCorrectAnswer: String?
        let correctionCount: Int
    }

    struct SummaryDTO: Decodable {
        let questionCount: Int
        let correctCount: Int
        let wrongCount: Int
        let partialCount: Int
        let unansweredCount: Int
        let unknownCount: Int
    }

    /// The question's *current* open wrong-question entry; `null` when it is
    /// graded correct or has already been put away.
    struct WrongQuestionDTO: Decodable {
        let wrongQuestionId: String
        let status: String?
        let attemptCount: Int?
    }

    let analysisId: String
    let questionId: String
    let studentAnswer: String?
    let correctAnswer: String?
    let correctness: String
    let confirmation: ConfirmationDTO
    let analysisSummary: SummaryDTO
    let wrongQuestion: WrongQuestionDTO?
    let nextAction: NextActionDTO?
    let replayed: Bool
}
