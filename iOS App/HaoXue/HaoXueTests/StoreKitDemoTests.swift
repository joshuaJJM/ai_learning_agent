import Foundation
import StoreKit
import StoreKitTest
import Testing
@testable import HaoXue

struct StoreKitDemoTests {
    @Test @MainActor func localConfigurationLoadsBothProducts() async throws {
        let file = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Products.storekit")
        let session = try SKTestSession(contentsOf: file)
        session.disableDialogs = true
        let products = try await Product.products(for: [
            StoreKitDemoPurchaseProvider.planID,
            StoreKitDemoPurchaseProvider.creditsID
        ])
        #expect(products.count == 2)
        #expect(products.contains { $0.id == StoreKitDemoPurchaseProvider.planID })
        #expect(products.contains { $0.id == StoreKitDemoPurchaseProvider.creditsID })
    }
}
