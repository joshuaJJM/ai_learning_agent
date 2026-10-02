import Foundation

// GET /api/v1/knowledge/mastery-overview
//
// `score` is the value the UI shows: a 0-99 integer the server already computed.
// Every other field is optional detail, so a partial response still yields a usable
// overview instead of failing the whole decode.
struct MasteryOverviewDTO: Decodable, Equatable {
    struct WeakestPointDTO: Decodable, Equatable {
        let knowledgePointId: String
        let name: String
        let mastery: Double
    }

    let score: Int
    let percent: Double
    let weightedMastery: Double
    let coverage: Double
    let coveredCount: Int
    let pointCount: Int
    let evidenceCount: Int
    let weakest: [WeakestPointDTO]

    init(score: Int, percent: Double, weightedMastery: Double, coverage: Double,
         coveredCount: Int, pointCount: Int, evidenceCount: Int, weakest: [WeakestPointDTO]) {
        self.score = score
        self.percent = percent
        self.weightedMastery = weightedMastery
        self.coverage = coverage
        self.coveredCount = coveredCount
        self.pointCount = pointCount
        self.evidenceCount = evidenceCount
        self.weakest = weakest
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        score = try container.decode(Int.self, forKey: .score)
        percent = try container.decodeIfPresent(Double.self, forKey: .percent) ?? 0
        weightedMastery = try container.decodeIfPresent(Double.self, forKey: .weightedMastery) ?? 0
        coverage = try container.decodeIfPresent(Double.self, forKey: .coverage) ?? 0
        coveredCount = try container.decodeIfPresent(Int.self, forKey: .coveredCount) ?? 0
        pointCount = try container.decodeIfPresent(Int.self, forKey: .pointCount) ?? 0
        evidenceCount = try container.decodeIfPresent(Int.self, forKey: .evidenceCount) ?? 0
        weakest = try container.decodeIfPresent([WeakestPointDTO].self, forKey: .weakest) ?? []
    }

    // Decoded with `convertFromSnakeCase`, so the raw values stay camelCase.
    private enum CodingKeys: String, CodingKey {
        case score, percent, weightedMastery, coverage, coveredCount, pointCount, evidenceCount, weakest
    }
}
