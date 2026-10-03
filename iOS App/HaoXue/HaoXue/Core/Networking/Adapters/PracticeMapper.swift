import Foundation

struct PracticeMapper {
    func question(_ dto: PracticeQuestionDTO) -> PracticeQuestion {
        PracticeQuestion(id: dto.questionId, number: dto.questionNumber, stem: dto.stem,
                         choices: dto.choices.map { PracticeChoice(key: $0.key, text: $0.text) },
                         difficulty: dto.difficulty,
                         knowledgePoints: (dto.knowledgePoints ?? []).map {
                             PracticeQuestion.KnowledgePoint(id: $0.knowledgePointId,
                                                             name: $0.name, weight: $0.weight)
                         },
                         tags: dto.tags ?? [], index: dto.index, total: dto.total)
    }

    func session(_ dto: PracticeSessionDTO) -> PracticeSessionState {
        PracticeSessionState(id: dto.practiceSessionId, userID: dto.userId,
                             knowledgePointID: dto.knowledgePointId,
                             knowledgePointName: dto.knowledgePointName,
                             status: PracticeSessionStatus(rawValue: dto.status),
                             total: dto.total, answered: dto.answered, correct: dto.correct,
                             nextQuestion: dto.nextQuestion.map(question),
                             selectionMode: PracticeSelectionMode(
                                 rawValue: dto.selectionMode ?? "knowledge_point"),
                             targetTag: dto.targetTag, targetTagScore: dto.targetTagScore,
                             pickedTags: dto.pickedTags ?? [], createdAt: dto.createdAt)
    }

    func answer(_ dto: PracticeAnswerResponseDTO) -> PracticeAnswerOutcome {
        PracticeAnswerOutcome(sessionID: dto.practiceSessionId, questionID: dto.questionId,
                              correctness: dto.correctness, isCorrect: dto.isCorrect,
                              correctAnswer: dto.correctAnswer, explanation: dto.explanation,
                              knowledgeChanges: (dto.knowledgeChanges ?? []).map(change),
                              tagChange: dto.tagChanges.map(tagChange),
                              replayed: dto.replayed ?? false,
                              nextQuestion: dto.nextQuestion.map(question),
                              sessionCompleted: dto.sessionCompleted ?? false,
                              answered: dto.answered ?? 0, correct: dto.correct ?? 0,
                              total: dto.total ?? 0,
                              nextAction: dto.nextAction.map(action))
    }

    func tagChange(_ dto: PracticeTagChangeDTO) -> PracticeTagChange {
        PracticeTagChange(questionID: dto.questionId, isCorrect: dto.isCorrect,
                          tags: dto.tags, scores: dto.tagScores, deltas: dto.tagDeltas)
    }

    /// Copies the server-reported progress and the server-provided next question
    /// back into the session state. Pure value transform — nothing is computed here.
    func session(_ session: PracticeSessionState, applying outcome: PracticeAnswerOutcome,
                 nextQuestion: PracticeQuestion?) -> PracticeSessionState {
        PracticeSessionState(id: session.id, userID: session.userID,
                             knowledgePointID: session.knowledgePointID,
                             knowledgePointName: session.knowledgePointName,
                             status: outcome.sessionCompleted ? .completed : session.status,
                             total: outcome.total, answered: outcome.answered,
                             correct: outcome.correct, nextQuestion: nextQuestion,
                             selectionMode: session.selectionMode,
                             targetTag: session.targetTag, targetTagScore: session.targetTagScore,
                             pickedTags: session.pickedTags, createdAt: session.createdAt)
    }

    private func change(_ dto: KnowledgeChangeDTO) -> KnowledgeChange {
        KnowledgeChange(knowledgePointID: dto.knowledgePointId,
                        beforeMastery: dto.before, afterMastery: dto.after,
                        summary: dto.name, delta: dto.delta,
                        evidenceCount: dto.evidenceCount)
    }

    private func action(_ dto: NextActionDTO) -> NextLearningAction {
        NextLearningAction(kind: dto.action, title: dto.title, reason: dto.reason,
                           buttonTitle: dto.ctaLabel, knowledgePointID: dto.knowledgePointId,
                           knowledgePointName: dto.knowledgePointName,
                           wrongQuestionID: dto.wrongQuestionId)
    }
}
