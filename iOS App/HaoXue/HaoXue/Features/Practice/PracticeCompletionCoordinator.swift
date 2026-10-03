import Foundation
import Observation

/// Bridges “practice finished” to “learning state is stale”.
///
/// Deliberately tiny: it holds no backend state, no mastery and no second
/// source of truth. It only signals the existing owners to re-GET and reports
/// whether that refresh worked. Retrying a refresh never replays the answer
/// mutation — the two lifecycles stay separate.
@MainActor @Observable
final class PracticeCompletionCoordinator {
    enum Notice: Equatable {
        case refreshed
        case refreshFailed(String)

        var text: String {
            switch self {
            case .refreshed: "练习完成 · 学习状态已更新"
            case .refreshFailed(let message): message
            }
        }
    }

    private let refreshHome: () async -> Bool
    private let refreshKnowledge: () async -> Bool

    private(set) var notice: Notice?
    private(set) var lastCompletion: PracticeAnswerOutcome?
    private(set) var isRefreshing = false

    init(refreshHome: @escaping () async -> Bool,
         refreshKnowledge: @escaping () async -> Bool) {
        self.refreshHome = refreshHome
        self.refreshKnowledge = refreshKnowledge
    }

    /// Called once per finished practice session, after the cover is dismissed.
    func practiceCompleted(_ outcome: PracticeAnswerOutcome) async {
        lastCompletion = outcome
        await refreshLearningState()
    }

    /// Re-GETs Home and Knowledge only. No mutation is replayed.
    func refreshLearningState() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        let home = await refreshHome()
        let knowledge = await refreshKnowledge()
        notice = home && knowledge
            ? .refreshed
            : .refreshFailed("练习已完成 · 学习状态暂时无法刷新")
    }

    func dismissNotice() {
        notice = nil
    }
}
