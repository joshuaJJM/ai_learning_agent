import Foundation
import StoreKit

protocol PurchaseProviding {
    func purchasePlan() async throws
    func purchaseCredits() async throws
}

struct SimulatedPurchaseProvider: PurchaseProviding {
    func purchasePlan() async throws { try await Task.sleep(for: .milliseconds(600)) }
    func purchaseCredits() async throws { try await Task.sleep(for: .milliseconds(600)) }
}

enum DemoPurchaseError: LocalizedError {
    case productUnavailable, pending, cancelled, unverified
    var errorDescription: String? {
        switch self {
        case .productUnavailable: "本地 StoreKit 商品暂不可用，可使用模拟体验"
        case .pending: "购买正在等待确认"
        case .cancelled: "购买已取消"
        case .unverified: "交易未通过本地验证"
        }
    }
}

struct StoreKitDemoPurchaseProvider: PurchaseProviding {
    static let planID = "haoxue.demo.plan.monthly"
    static let creditsID = "haoxue.demo.credits.1000000"

    func purchasePlan() async throws { try await purchase(Self.planID) }
    func purchaseCredits() async throws { try await purchase(Self.creditsID) }

    private func purchase(_ id: String) async throws {
        guard let product = try await Product.products(for: [id]).first else {
            throw DemoPurchaseError.productUnavailable
        }
        switch try await product.purchase() {
        case .success(let verification):
            guard case .verified(let transaction) = verification else { throw DemoPurchaseError.unverified }
            await transaction.finish()
        case .pending: throw DemoPurchaseError.pending
        case .userCancelled: throw DemoPurchaseError.cancelled
        @unknown default: throw DemoPurchaseError.productUnavailable
        }
    }
}
