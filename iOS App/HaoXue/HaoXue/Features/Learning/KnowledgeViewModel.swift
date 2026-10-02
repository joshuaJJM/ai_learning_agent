import Foundation
import Observation

enum KnowledgeLoadPhase: Equatable { case idle, loading, loaded, failed }

@MainActor @Observable
final class KnowledgeOverviewViewModel {
    private let provider: any KnowledgeDataProviding
    private(set) var phase: KnowledgeLoadPhase = .idle
    private(set) var overview: KnowledgeOverview?
    private(set) var errorMessage: String?

    init(provider: any KnowledgeDataProviding) { self.provider = provider }

    func loadIfNeeded() async {
        guard phase == .idle else { return }
        await refresh()
    }

    func refresh() async {
        guard phase != .loading else { return }
        phase = .loading
        overview = nil
        errorMessage = nil
        do {
            overview = try await provider.fetchKnowledgeOverview()
            try Task.checkCancellation()
            phase = .loaded
        } catch is CancellationError {
            phase = .idle
        } catch {
            errorMessage = KnowledgeError.message(for: error)
            phase = .failed
        }
    }
}

@MainActor @Observable
final class KnowledgeDetailViewModel {
    private let id: String
    private let provider: any KnowledgeDataProviding
    private(set) var phase: KnowledgeLoadPhase = .idle
    private(set) var detail: KnowledgePointDetail?
    private(set) var relatedWrongQuestions: [WrongQuestionSummary] = []
    private(set) var isLoadingRelated = false
    private(set) var relatedError: String?
    private(set) var errorMessage: String?

    init(id: String, provider: any KnowledgeDataProviding) {
        self.id = id
        self.provider = provider
    }

    func loadIfNeeded() async {
        guard phase == .idle else { return }
        await refresh()
    }

    func refresh() async {
        guard phase != .loading else { return }
        phase = .loading
        detail = nil
        relatedWrongQuestions = []
        isLoadingRelated = false
        relatedError = nil
        errorMessage = nil
        do {
            detail = try await provider.fetchKnowledgeDetail(id: id)
            try Task.checkCancellation()
            phase = .loaded
            isLoadingRelated = true
            do {
                relatedWrongQuestions = try await provider.fetchRelatedWrongQuestions(knowledgePointID: id)
            } catch {
                relatedError = "相关错题暂时无法获取"
            }
            isLoadingRelated = false
        } catch is CancellationError {
            phase = .idle
        } catch {
            detail = nil
            errorMessage = KnowledgeError.message(for: error)
            phase = .failed
        }
    }
}

enum KnowledgeError {
    static func message(for error: Error) -> String {
        guard let error = error as? NetworkError else { return "暂时无法获取知识状态，请重试" }
        return switch error {
        case .backend(let code, _, _, _):
            switch code {
            case "KNOWLEDGE_POINT_NOT_FOUND": "这个知识点已不存在"
            case "UNAUTHORIZED": "请重新连接学习档案后重试"
            case "SERVICE_UNAVAILABLE": "服务暂时不可用，请稍后重试"
            case "INTERNAL_ERROR": "知识状态暂时无法显示，请稍后重试"
            default: "暂时无法获取知识状态，请重试"
            }
        case .timeout, .transport: "网络连接中断，请重试"
        case .decoding: "知识状态数据暂时无法显示，请稍后重试"
        default: "暂时无法获取知识状态，请重试"
        }
    }
}

enum KnowledgeEvidencePresentation {
    static func sourceLabel(_ value: String) -> String {
        switch value {
        case "homework": "作业分析"
        case "tutor": "学习检查"
        case "practice": "练习"
        case "exam": "测验"
        default: "学习记录"
        }
    }

    static func resultLabel(_ value: String) -> String {
        switch value {
        case "correct": "回答正确"
        case "partial": "部分正确"
        case "incorrect": "回答错误"
        case "unknown": "待确认"
        default: "结果待确认"
        }
    }

    static func trendLabel(_ value: String) -> String? {
        switch value {
        case "improving": "近期正在提升"
        case "declining": "近期需要关注"
        case "stable": "近期保持稳定"
        default: nil
        }
    }
}
