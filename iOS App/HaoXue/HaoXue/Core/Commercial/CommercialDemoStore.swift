import Foundation
import Observation

@MainActor @Observable
final class CommercialDemoStore {
    private(set) var creditBalance = 1_000_000
    private(set) var monthlyCreditAllowance = 1_000_000
    private(set) var usedCredits = 0
    private(set) var isPlanActive = false
    private(set) var unlockedBookIDs: Set<String> = []
    let referralCode = "HAOXUE-7K3F"

    func unlock(_ bookID: String) { unlockedBookIDs.insert(bookID) }
    func hasAccess(to bookID: String) -> Bool { isPlanActive || unlockedBookIDs.contains(bookID) }
    func activatePlan() {
        isPlanActive = true
        monthlyCreditAllowance = 20_000_000
        creditBalance = 20_000_000
    }
    func addCredits(_ amount: Int) { creditBalance += amount }
}
