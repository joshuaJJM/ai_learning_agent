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
    case productUnavailable, productLoadingFailed(String), pending, cancelled, unverified
    var errorDescription: String? {
        switch self {
        case .productUnavailable: "找不到本地 StoreKit 商品。请检查 Xcode Run Scheme 的 StoreKit Configuration 是否选择 Products.storekit。"
        case .productLoadingFailed(let detail): "加载 StoreKit 商品失败：\(detail)"
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
        let products: [Product]
        do {
            products = try await Product.products(for: [id])
        } catch {
            #if DEBUG
            print("[StoreKit Demo] 商品加载失败 id=\(id): \(error)")
            #endif
            throw DemoPurchaseError.productLoadingFailed(error.localizedDescription)
        }
        guard let product = products.first(where: { $0.id == id }) else {
            #if DEBUG
            print("[StoreKit Demo] 未加载到商品 id=\(id)")
            #endif
            throw DemoPurchaseError.productUnavailable
        }
        #if DEBUG
        print("[StoreKit Demo] 已加载商品 id=\(product.id), name=\(product.displayName), price=\(product.displayPrice)")
        #endif
        switch try await product.purchase() {
        case .success(let verification):
            guard case .verified(let transaction) = verification else {
                #if DEBUG
                print("[StoreKit Demo] 交易未验证 id=\(id)")
                #endif
                throw DemoPurchaseError.unverified
            }
            await transaction.finish()
            #if DEBUG
            print("[StoreKit Demo] 已验证并结束交易 id=\(id)")
            #endif
        case .pending:
            #if DEBUG
            print("[StoreKit Demo] 购买待处理 id=\(id)")
            #endif
            throw DemoPurchaseError.pending
        case .userCancelled:
            #if DEBUG
            print("[StoreKit Demo] 用户取消购买 id=\(id)")
            #endif
            throw DemoPurchaseError.cancelled
        @unknown default: throw DemoPurchaseError.productUnavailable
        }
    }
}
