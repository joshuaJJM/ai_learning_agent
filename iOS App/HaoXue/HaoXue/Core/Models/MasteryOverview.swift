import Foundation

// Backend owns these numbers. iOS displays them verbatim and never recomputes them.
struct MasteryOverview: Equatable {
    let score: Int
    let percent: Double
    let weightedMastery: Double
    let coverage: Double
    let coveredCount: Int
    let pointCount: Int
    let evidenceCount: Int
    let weakest: [WeakestKnowledgePoint]

    struct WeakestKnowledgePoint: Equatable {
        let id: String
        let name: String
        let mastery: Double
    }
}
