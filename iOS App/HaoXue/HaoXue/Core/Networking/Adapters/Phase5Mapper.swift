import Foundation

struct Phase5Mapper {
    func action(_ dto: NextActionDTO) -> NextLearningAction {
        NextLearningAction(kind: dto.action, title: dto.title, reason: dto.reason,
                           buttonTitle: dto.ctaLabel, knowledgePointID: dto.knowledgePointId,
                           knowledgePointName: dto.knowledgePointName,
                           wrongQuestionID: dto.wrongQuestionId)
    }

    func summary(_ dto: WrongQuestionSummaryDTO) -> WrongQuestionSummary {
        WrongQuestionSummary(id: dto.wrongQuestionId, questionID: dto.questionId,
                             questionNumber: dto.questionNumber, content: dto.questionContent,
                             knowledgePointID: dto.knowledgePointId,
                             knowledgePointName: dto.knowledgePointName,
                             errorType: dto.errorType, errorLabel: dto.errorLabel,
                             status: dto.status, createdAt: dto.createdAt)
    }

    func home(_ dto: HomeResponseDTO) -> HomeSnapshot {
        func knowledge(_ point: KnowledgeSummaryDTO) -> HomeSnapshot.KnowledgeSummary {
            HomeSnapshot.KnowledgeSummary(id: point.knowledgePointId, name: point.name,
                                          mastery: point.mastery, confidence: point.confidence,
                                          evidenceCount: point.evidenceCount, trend: point.trend,
                                          isWeak: point.isWeak)
        }
        let stats = dto.stats
        return HomeSnapshot(userID: dto.userId, greeting: dto.greeting,
                            nextAction: action(dto.nextAction),
                            knowledgeSummary: dto.knowledgeSummary.map(knowledge),
                            weakest: dto.weakest.map(knowledge),
                            wrongQuestionCount: dto.wrongQuestionCount,
                            recentWrongQuestions: dto.recentWrongQuestions.map(summary),
                            recentActivities: dto.recentActivities.map {
                                HomeSnapshot.Activity(type: $0.activityType, title: $0.title,
                                                      subtitle: $0.subtitle, referenceID: $0.referenceId,
                                                      occurredAt: $0.occurredAt)
                            },
                            stats: HomeSnapshot.Stats(totalEvidence: stats.totalEvidence,
                                                      homeworkCount: stats.homeworkCount,
                                                      openWrongQuestionCount: stats.wrongQuestionOpen,
                                                      tutorSessionCount: stats.tutorSessionCount,
                                                      practiceAttemptCount: stats.practiceAttemptCount,
                                                      streakDays: stats.streakDays),
                            updatedAt: dto.updatedAt)
    }

    func legacyHome(_ snapshot: HomeSnapshot) -> HomeState {
        HomeState(nextStep: snapshot.nextAction.title,
                  knowledgePoints: snapshot.knowledgeSummary.map {
                      KnowledgePoint(id: $0.id, name: $0.name, mastery: $0.mastery,
                                     trend: $0.trend, evidenceSummary: nil,
                                     recommendedAction: nil)
                  },
                  recentWrongQuestions: snapshot.recentWrongQuestions.map {
                      WrongQuestion(id: $0.id, content: $0.content, source: $0.questionNumber,
                                    studentAnswer: nil, correctAnswer: nil,
                                    knowledgePointIDs: $0.knowledgePointID.map { [$0] } ?? [],
                                    diagnosis: $0.errorLabel, timestamp: $0.createdAt)
                  })
    }

    func analysis(_ dto: AnalysisResultDTO) -> HomeworkAnalysisResult {
        HomeworkAnalysisResult(id: dto.analysisId, batchNumber: dto.batchNumber,
                               status: AnalysisStatus(rawValue: dto.status), progress: dto.progress,
                               homeworkID: dto.homeworkId, userID: dto.userId, subject: dto.subject,
                               topic: dto.topic, sourceName: dto.sourceName, bookID: dto.bookId,
                               imageCount: dto.imageCount, questionIDs: dto.questions,
                               questions: dto.questionResults.map {
                                   HomeworkAnalysisResult.Question(id: $0.questionId, number: $0.questionNumber,
                                       type: $0.questionType, content: $0.questionContent,
                                       choices: $0.choices, studentAnswer: $0.studentAnswer,
                                       correctAnswer: $0.correctAnswer, correctness: $0.correctness,
                                       knowledgePoints: $0.knowledgePoints.map { ($0.knowledgePointId, $0.name, $0.weight) },
                                       errorType: $0.errorType, errorLabel: $0.errorLabel,
                                       diagnosis: $0.diagnosis, explanation: $0.explanation,
                                       confidence: $0.confidence, difficulty: $0.difficulty,
                                       imageURL: $0.imageUrl)
                               }, correctCount: dto.correctCount, wrongCount: dto.wrongCount,
                               partialCount: dto.partialCount, unknownCount: dto.unknownCount,
                               knowledgeChanges: dto.knowledgeChanges.map {
                                   KnowledgeChange(knowledgePointID: $0.knowledgePointId,
                                                   beforeMastery: $0.before, afterMastery: $0.after,
                                                   summary: $0.name)
                               }, newWrongQuestions: dto.newWrongQuestions.map(summary),
                               nextAction: dto.nextAction.map(action), error: dto.error,
                               warnings: dto.warnings, generatedBy: dto.generatedBy,
                               createdAt: dto.createdAt, updatedAt: dto.updatedAt,
                               finishedAt: dto.finishedAt)
    }

    func legacyAnalysis(_ result: HomeworkAnalysisResult) -> UploadAnalysis {
        UploadAnalysis(id: result.id, status: result.status,
                       stageDescription: result.progress?.currentStageLabelZH,
                       questions: result.questions.map {
                           QuestionResult(id: $0.id, content: $0.content,
                                          choices: $0.choices.sorted { $0.key < $1.key }.compactMap {
                                              guard let id = ChoiceID(rawValue: $0.key) else { return nil }
                                              return TutorChoice(id: id, text: $0.value)
                                          }, studentAnswer: $0.studentAnswer.flatMap(ChoiceID.init(rawValue:)),
                                          correctAnswer: $0.correctAnswer.flatMap(ChoiceID.init(rawValue:)),
                                          isCorrect: $0.correctness == "correct" ? true :
                                              $0.correctness == "wrong" ? false : nil,
                                          knowledgePointIDs: $0.knowledgePoints.map(\.id),
                                          diagnosis: $0.diagnosis)
                       }, knowledgeChanges: result.knowledgeChanges,
                       recommendation: result.nextAction?.title, errorCode: result.error?.errorCode)
    }

    func wrongQuestion(_ dto: WrongQuestionDetailDTO) -> WrongQuestionDetail {
        WrongQuestionDetail(summary: WrongQuestionSummary(id: dto.wrongQuestionId,
            questionID: dto.questionId, questionNumber: dto.questionNumber,
            content: dto.questionContent, knowledgePointID: dto.knowledgePointId,
            knowledgePointName: dto.knowledgePointName, errorType: dto.errorType,
            errorLabel: dto.errorLabel, status: dto.status, createdAt: dto.createdAt),
            questionType: dto.questionType, choices: dto.choices,
            studentAnswer: dto.studentAnswer, correctAnswer: dto.correctAnswer,
            explanation: dto.explanation, correctness: dto.correctness,
            diagnosis: dto.diagnosis, imageURL: dto.imageUrl,
            sourceType: dto.sourceType, sourceID: dto.sourceId, sourceName: dto.sourceName,
            favorite: dto.favorite, updatedAt: dto.updatedAt, canStartTutor: dto.canStartTutor)
    }

    func knowledge(_ dto: KnowledgeDetailDTO) -> KnowledgePointDetail {
        KnowledgePointDetail(id: dto.knowledgePointId, name: dto.name,
            description: dto.description, subject: dto.subject, mastery: dto.mastery,
            confidence: dto.confidence, trend: dto.trend, evidenceCount: dto.evidenceCount,
            correctCount: dto.correctCount, partialCount: dto.partialCount,
            wrongCount: dto.wrongCount, recentPerformance: dto.recentPerformance.map {
                ($0.occurredAt, $0.result, $0.sourceType, $0.questionId)
            }, errorPatterns: dto.errorPatterns.map {
                KnowledgePointDetail.ErrorPattern(type: $0.errorType, label: $0.label,
                                                   count: $0.count, share: $0.share)
            }, evidence: dto.evidence.map {
                KnowledgePointDetail.Evidence(id: $0.evidenceId, sourceType: $0.sourceType,
                    sourceID: $0.sourceId, questionID: $0.questionId,
                    questionStemHash: $0.questionStemHash, result: $0.result,
                    confidence: $0.confidence, errorType: $0.errorType,
                    errorLabel: $0.errorLabel, answerExcerpt: $0.answerExcerpt,
                    detail: $0.detail, createdAt: $0.createdAt)
            }, prerequisites: dto.prerequisites.map { ($0.knowledgePointId, $0.name, $0.weight) },
            masteryExplanation: dto.masteryExplanation,
            recommendedAction: dto.recommendedAction.map(action), updatedAt: dto.updatedAt)
    }
}
