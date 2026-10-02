import Observation

enum DemoStage {
    case initial
    case learning
    case lessonCompleted
}

enum DemoTutorStep {
    case question
    case feedback
    case completion
}

struct DemoSubject {
    let name: String
    let mastery: Double
    let colorName: String
}

// In-memory presentation of fixed mock snapshots. Live mastery remains backend-owned.
@MainActor @Observable
final class DemoScenarioStore {
    private(set) var stage: DemoStage = .initial
    private(set) var tutorStep: DemoTutorStep = .question
    private(set) var selectedChoice: ChoiceID?
    private(set) var feedbackIsCorrect = false
    private(set) var scanPageCount = 3
    private(set) var scanAnalysisCompleted = false

    let lessonTitle = "导数与单调性"
    let knowledgeLink = "导数符号 → 函数性质"
    let tutorQuestionLead = "如果在某个区间内："
    let tutorExpression = "f′(x) > 0"
    let tutorQuestionEnd = "这说明函数 f(x) 在这个区间内……"
    let correctFeedback = "很好。当 f′(x) > 0 时，函数在该区间内单调递增。"
    let incorrectFeedback = "还差一点。想一想：导数为正意味着函数值随着 x 增加时发生怎样的变化？"
    let practiceSummary = "5 道选择题 · 约 8 分钟\n难度会根据你的作答实时调整"
    let scanPageHeading = "高中数学 · 导数"
    let scanQuestion = "4. 已知函数 f(x) 的导函数图像，判断函数的单调递增区间。"
    let scanChoices = "A. (-∞, -1)\nB. (-1, 2)\nC. (2, +∞)\nD. (-1, +∞)"
    let scanFocusPoints = [
        (title: "导数与单调性", mastery: 0.43, wrongCount: 2),
        (title: "函数极值", mastery: 0.68, wrongCount: 1)
    ]
    let learningSettings = [
        ("专注模式", "减少学习时的干扰"),
        ("题库与图书", "管理学习内容与序列号")
    ]
    let productSettings = [
        ("订阅与学习额度", "1,000,000 演示额度"),
        ("数据与隐私", "学习数据与图片处理说明"),
        ("服务器状态", "演示模式 · 本地数据")
    ]
    let aboutSettings = [
        ("关于好学", "Personal Learning Agent"),
        ("版本", "Hackathon Demo · 1.0")
    ]
    let subjects = [
        DemoSubject(name: "数学", mastery: 0.78, colorName: "blue"),
        DemoSubject(name: "化学", mastery: 0.69, colorName: "green"),
        DemoSubject(name: "物理", mastery: 0.84, colorName: "orange")
    ]
    let recentWrongQuestions = [
        (title: "导数与单调性", detail: "昨天 · 周练 · 第 7 题"),
        (title: "函数极值", detail: "9 月 29 日 · 月考 · 第 16 题")
    ]
    let tutorChoices = [
        TutorChoice(id: .A, text: "单调递增"),
        TutorChoice(id: .B, text: "单调递减"),
        TutorChoice(id: .C, text: "一定存在最大值"),
        TutorChoice(id: .D, text: "无法判断")
    ]

    var home: HomeState {
        stage == .lessonCompleted ? GoldenDemoFixtures.homeAfter : GoldenDemoFixtures.homeBefore
    }

    var mastery: Double { home.knowledgePoints.first?.mastery ?? 0.43 }

    var nextStepDetail: String {
        stage == .lessonCompleted
            ? "刚才的学习让这一知识点从 43% 提升到了 51%。再完成针对练习，可以帮助你巩固刚刚学会的内容。"
            : "最近 3 次相关作答中，有 2 次在「导数符号 → 函数性质」上出现问题。"
    }

    func startLesson() {
        if stage == .initial { stage = .learning }
        tutorStep = .question
        selectedChoice = nil
        feedbackIsCorrect = false
    }

    func selectChoice(_ choice: ChoiceID) {
        guard tutorStep == .question else { return }
        selectedChoice = choice
    }

    func submitChoice() {
        guard tutorStep == .question, let selectedChoice else { return }
        feedbackIsCorrect = selectedChoice == .A
        tutorStep = .feedback
    }

    func continueLesson() {
        guard tutorStep == .feedback else { return }
        if feedbackIsCorrect {
            stage = .lessonCompleted
            tutorStep = .completion
        } else {
            selectedChoice = nil
            tutorStep = .question
        }
    }

    func showScanResult() { scanAnalysisCompleted = true }

    func uploadMoreDemoPage() {
        scanPageCount += 1
        scanAnalysisCompleted = false
    }
}
