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
        nextStep: "学习导数符号与函数单调性的关系",
        subjects: [SubjectSummary(id: "math", name: "数学", summary: "导数基础")],
        knowledgePoints: [KnowledgePoint(id: knowledgeID, name: "导数与单调性", mastery: 0.43,
            trend: "需要关注", evidenceSummary: "基础求导熟练，导数符号到函数性质理解薄弱",
            recommendedAction: "进入 Tutor")], recentWrongQuestions: [wrongQuestion])

    static let homeAfter = HomeState(
        nextStep: "继续巩固导数与单调性",
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

    private static let independentQuestion = PracticeQuestion(id: "practice-q1",
        content: "在一个区间内 f′(x) > 0，函数有什么性质？",
        choices: choices, knowledgePointIDs: [knowledgeID])
    static let practiceQuestion = PracticeSession(id: "practice-question",
        currentQuestion: independentQuestion, progress: 0, completed: false, result: nil)
    static let practiceCompleted = PracticeSession(id: "practice-completed",
        currentQuestion: independentQuestion, progress: 1, completed: true,
        result: PracticeResult(isCorrect: true, explanation: "导数为正，函数在该区间单调递增。",
            knowledgeChange: masteryChange, nextAction: "继续巩固导数与单调性"))
}
