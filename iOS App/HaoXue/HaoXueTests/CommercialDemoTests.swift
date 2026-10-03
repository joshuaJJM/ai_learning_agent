import Testing
@testable import HaoXue

struct CommercialDemoTests {
    @Test @MainActor func catalogHasEightLocalBooksAndDistinctCovers() {
        #expect(DemoBookCatalog.books.count == 8)
        #expect(Set(DemoBookCatalog.books.map(\.coverAssetName)).count == 8)
    }

    @Test @MainActor func recommendationUsesBackendMasteryOnlyForRanking() {
        let points = [
            RecommendationPoint(id: "weak", name: "导数与单调性", mastery: 0.43),
            RecommendationPoint(id: "strong", name: "基础求导", mastery: 0.91)
        ]
        let ranked = BookRecommendationEngine.rank(DemoBookCatalog.books, using: points)
        #expect(ranked.first?.book.id == "monotonicity")
        #expect(ranked.first?.matchedPoints.count == 1)
        #expect(ranked.first?.matchedPoints.first?.mastery == 0.43)
    }

    @Test @MainActor func localEntitlementsAreIndependentFromLearningState() {
        let store = CommercialDemoStore()
        #expect(store.creditBalance == 1_000_000)
        #expect(store.hasAccess(to: "derivative") == false)
        store.unlock("derivative")
        #expect(store.hasAccess(to: "derivative"))
        #expect(store.hasAccess(to: "extrema") == false)
        store.activatePlan()
        #expect(store.hasAccess(to: "extrema"))
        #expect(store.monthlyCreditAllowance == 20_000_000)
    }
}
