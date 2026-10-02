import Foundation

// Keeps the wire schema out of the View layer: DTO -> domain model, in one place.
@MainActor
struct MasteryOverviewMapper {
    func map(_ dto: MasteryOverviewDTO) -> MasteryOverview {
        MasteryOverview(
            score: dto.score,
            percent: dto.percent,
            weightedMastery: dto.weightedMastery,
            coverage: dto.coverage,
            coveredCount: dto.coveredCount,
            pointCount: dto.pointCount,
            evidenceCount: dto.evidenceCount,
            weakest: dto.weakest.map {
                MasteryOverview.WeakestKnowledgePoint(id: $0.knowledgePointId,
                                                      name: $0.name,
                                                      mastery: $0.mastery)
            }
        )
    }
}
