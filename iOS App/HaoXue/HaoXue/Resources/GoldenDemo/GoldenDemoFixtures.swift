import Foundation

// Frontend Mock Domain Data, never a final Backend JSON contract.
// All outcomes are fixed server-like snapshots, not evaluated on device.
enum GoldenDemoFixtures {
    private static let knowledgeID = "derivative-monotonicity"
    private static let choices = [
        TutorChoice(id: .A, text: "函数在该区间单调递增"),
        TutorChoice(id: .B, text: "函数在该区间单调递减"),
        TutorChoice(id: .C, text: "函数值恒为正"),
        TutorChoice(id: .D, text: "函数存在极大值")
    ]
    private static let wrongQuestion = WrongQuestion(
        id: "wrong-6", content: "在一个区间内 f′(x) > 0，函数有什么性质？",
        source: "Golden Demo 导数选择题", studentAnswer: "C", correctAnswer: "A",
        knowledgePointIDs: [knowledgeID], diagnosis: "导数符号 → 函数性质理解薄弱",
        timestamp: Date(timeIntervalSince1970: 1_790_899_200))

    static let masteryChange = KnowledgeChange(
        knowledgePointID: knowledgeID, beforeMastery: 0.43, afterMastery: 0.51,
        summary: "完成引导与独立练习，固定模拟服务器结果")

    static let homeBefore = HomeState(
        nextStep: "导数与函数单调性",
        subjects: [SubjectSummary(id: "math", name: "数学", summary: "导数基础")],
        knowledgePoints: [KnowledgePoint(id: knowledgeID, name: "导数与单调性", mastery: 0.43,
            trend: "需要关注", evidenceSummary: "基础求导熟练，导数符号到函数性质理解薄弱",
            recommendedAction: "进入 Tutor")], recentWrongQuestions: [wrongQuestion])

    static let homeAfter = HomeState(
        nextStep: "巩固导数与单调性",
        subjects: [SubjectSummary(id: "math", name: "数学", summary: "导数基础")],
        knowledgePoints: [KnowledgePoint(id: knowledgeID, name: "导数与单调性", mastery: 0.51,
            trend: "提升", evidenceSummary: "完成引导并答对独立练习",
            recommendedAction: "继续巩固")], recentWrongQuestions: [wrongQuestion],
        recentChanges: [masteryChange])

    static let analysisQueued = UploadAnalysis(id: "analysis-queued", status: .queued,
        stageDescription: "图片已上传", recommendation: nil, errorCode: nil)
    static let analysisProcessing = UploadAnalysis(id: "analysis-processing", status: .processing,
        stageDescription: "正在分析作答", recommendation: nil, errorCode: nil)
    static let analysisFailed = UploadAnalysis(id: "analysis-failed", status: .failed,
        stageDescription: nil, recommendation: "稍后重试", errorCode: "ANALYSIS_FAILED")

    static let analysisCompleted = UploadAnalysis(id: "analysis-completed", status: .completed,
        stageDescription: "知识状态已更新", questions: [
            QuestionResult(id: "q1", content: "f(x) = x² 的导数是什么？",
                choices: [TutorChoice(id: .A, text: "2x"), TutorChoice(id: .B, text: "x"),
                    TutorChoice(id: .C, text: "2"), TutorChoice(id: .D, text: "x²")],
                studentAnswer: .A, correctAnswer: .A, isCorrect: true,
                knowledgePointIDs: [knowledgeID], diagnosis: nil),
            QuestionResult(id: "q2", content: "常数函数的导数是什么？",
                choices: [TutorChoice(id: .A, text: "1"), TutorChoice(id: .B, text: "0"),
                    TutorChoice(id: .C, text: "x"), TutorChoice(id: .D, text: "不存在")],
                studentAnswer: .B, correctAnswer: .B, isCorrect: true,
                knowledgePointIDs: [knowledgeID], diagnosis: nil),
            QuestionResult(id: "q3", content: "f(x) = x³ 的导数是什么？",
                choices: [TutorChoice(id: .A, text: "x²"), TutorChoice(id: .B, text: "3x"),
                    TutorChoice(id: .C, text: "3x²"), TutorChoice(id: .D, text: "3")],
                studentAnswer: .C, correctAnswer: .C, isCorrect: true,
                knowledgePointIDs: [knowledgeID], diagnosis: nil),
            QuestionResult(id: "q4", content: "f(x) = 2x + 1 的导数是什么？",
                choices: [TutorChoice(id: .A, text: "2x"), TutorChoice(id: .B, text: "1"),
                    TutorChoice(id: .C, text: "0"), TutorChoice(id: .D, text: "2")],
                studentAnswer: .D, correctAnswer: .D, isCorrect: true,
                knowledgePointIDs: [knowledgeID], diagnosis: nil),
            QuestionResult(id: "q5", content: "f′(x) < 0 时函数在该区间如何变化？",
                choices: choices, studentAnswer: .B, correctAnswer: .B, isCorrect: true,
                knowledgePointIDs: [knowledgeID], diagnosis: nil),
            QuestionResult(id: "q6", content: wrongQuestion.content, choices: choices,
                studentAnswer: .C, correctAnswer: .A, isCorrect: false,
                knowledgePointIDs: [knowledgeID], diagnosis: wrongQuestion.diagnosis)
        ], recommendation: "进入 Tutor 理解导数符号", errorCode: nil)

    static let tutorDiagnose = TutorSession(id: "tutor-diagnose", source: .wrongQuestion("wrong-6"),
        knowledgePointID: knowledgeID, currentTurn: TutorTurn(id: "turn-diagnose", type: "question",
            text: "f′(x) > 0 意味着什么？", choices: choices, phase: .diagnose,
            progress: 0, completed: false, knowledgeChange: nil))
    static let tutorTeach = TutorSession(id: "tutor-teach", source: .wrongQuestion("wrong-6"),
        knowledgePointID: knowledgeID, currentTurn: TutorTurn(id: "turn-teach", type: "explanation",
            text: "固定错答后的模拟快照：换一种解释，导数表示变化率。变化率为正时，函数沿 x 增大的方向上升。",
            choices: choices, phase: .teach, progress: 0.5, completed: false, knowledgeChange: nil))
    static let tutorCompleted = TutorSession(id: "tutor-completed", source: .wrongQuestion("wrong-6"),
        knowledgePointID: knowledgeID, currentTurn: TutorTurn(id: "turn-completed", type: "summary",
            text: "已完成引导，接下来独立练习。", choices: nil, phase: .completed,
            progress: 1, completed: true, knowledgeChange: nil))

    private static let practiceTags = ["利用导数判断函数单调性与单调区间"]
    // v2 tag statistics: one score change per tag, not a single ±1 delta.
    private static let tagScores = Dictionary(uniqueKeysWithValues: practiceTags.map { ($0, 34) })
    private static let tagDeltas = Dictionary(uniqueKeysWithValues: practiceTags.map { ($0, 2) })
    private static let practiceChoices = [
        PracticeChoice(key: "A", text: "函数在该区间单调递增"),
        PracticeChoice(key: "B", text: "函数在该区间单调递减"),
        PracticeChoice(key: "C", text: "函数值恒为正"),
        PracticeChoice(key: "D", text: "函数存在极大值")
    ]
    private static let practiceIndependentQuestion = PracticeQuestion(id: "practice-q1",
        number: "017", stem: "在一个区间内 f′(x) > 0，函数有什么性质？",
        choices: practiceChoices, difficulty: 0.35,
        knowledgePoints: [PracticeQuestion.KnowledgePoint(id: knowledgeID, name: "导数与单调性",
                                                          weight: 1)],
        tags: practiceTags, index: 1, total: 2)
    private static let practiceSecondQuestion = PracticeQuestion(id: "practice-q2",
        number: "018", stem: "f′(x) < 0 时，函数在该区间的变化是什么？",
        choices: [
            PracticeChoice(key: "A", text: "单调递增"),
            PracticeChoice(key: "B", text: "单调递减"),
            PracticeChoice(key: "C", text: "取得极大值"),
            PracticeChoice(key: "D", text: "保持不变")
        ], difficulty: 0.4,
        knowledgePoints: [PracticeQuestion.KnowledgePoint(id: knowledgeID, name: "导数与单调性",
                                                          weight: 1)],
        tags: practiceTags, index: 2, total: 2)

    static let practiceTagSession = PracticeSessionState(id: "practice-question",
        userID: "golden-demo-user", knowledgePointID: knowledgeID,
        knowledgePointName: "导数与单调性", status: .active, total: 2, answered: 0, correct: 0,
        nextQuestion: practiceIndependentQuestion, selectionMode: .tag,
        targetTag: "函数关系式与导数的综合应用", targetTagScore: -3,
        pickedTags: ["函数关系式与导数的综合应用"], createdAt: Date(timeIntervalSince1970: 1_790_899_200))

    static let practiceKnowledgePointSession = PracticeSessionState(id: "practice-knowledge-point",
        userID: "golden-demo-user", knowledgePointID: knowledgeID,
        knowledgePointName: "导数与单调性", status: .active, total: 2, answered: 1, correct: 1,
        nextQuestion: practiceIndependentQuestion, selectionMode: .knowledgePoint,
        targetTag: nil, targetTagScore: nil, pickedTags: [],
        createdAt: Date(timeIntervalSince1970: 1_790_899_200))

    static let practiceCompletedSession = PracticeSessionState(id: "practice-completed",
        userID: "golden-demo-user", knowledgePointID: knowledgeID,
        knowledgePointName: "导数与单调性", status: .completed, total: 2, answered: 2, correct: 1,
        nextQuestion: nil, selectionMode: .tag, targetTag: "函数关系式与导数的综合应用",
        targetTagScore: -3, pickedTags: ["函数关系式与导数的综合应用"],
        createdAt: Date(timeIntervalSince1970: 1_790_899_200))

    static let practiceAnswerOutcome = PracticeAnswerOutcome(sessionID: "practice-question",
        questionID: "practice-q1", correctness: "correct", isCorrect: true, correctAnswer: "A",
        explanation: "导数为正，函数在该区间单调递增。", knowledgeChanges: [masteryChange],
        tagChange: PracticeTagChange(questionID: "practice-q1", isCorrect: true,
                                     tags: practiceTags, scores: tagScores, deltas: tagDeltas),
        replayed: false, nextQuestion: practiceSecondQuestion, sessionCompleted: false,
        answered: 1, correct: 1, total: 2, nextAction: nil)

    static let practiceCompletedOutcome = PracticeAnswerOutcome(sessionID: "practice-question",
        questionID: "practice-q2", correctness: "correct", isCorrect: true, correctAnswer: "B",
        explanation: "导数为负，函数在该区间单调递减。", knowledgeChanges: [masteryChange],
        tagChange: PracticeTagChange(questionID: "practice-q2", isCorrect: true,
                                     tags: practiceTags, scores: tagScores, deltas: tagDeltas),
        replayed: false, nextQuestion: nil, sessionCompleted: true, answered: 2, correct: 2,
        total: 2, nextAction: NextLearningAction(kind: "all_good", title: "本次练习已完成",
                                                reason: "这一组题都已作答", buttonTitle: "完成练习",
                                                knowledgePointID: knowledgeID,
                                                knowledgePointName: "导数与单调性",
                                                wrongQuestionID: nil))
}
