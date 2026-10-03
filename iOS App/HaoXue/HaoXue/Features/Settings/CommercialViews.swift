import SwiftUI
import UIKit

struct LearningPlanView: View {
    let commercial: CommercialDemoStore
    @State private var isPurchasing = false
    @State private var error: String?
    @State private var showStoreKit = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                Text("让好学持续理解你的学习状态。")
                    .font(.title2).padding(.top, 15)
                VStack(alignment: .leading, spacing: 16) {
                    benefit("解锁图书与题库中的全部练习资源")
                    benefit("每月 20,000,000 学习额度")
                    benefit("个性化学习资源推荐")
                    benefit("长期知识状态与学习历史")
                }
                Divider()
                Text("¥20 / 月").font(.largeTitle.bold())
                Text("Hackathon Demo 定价；本页购买状态仅用于本机演示。")
                    .font(.caption).foregroundStyle(.secondary)
                if commercial.isPlanActive {
                    Label("已加入好学计划", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                } else {
                    Button(isPurchasing ? "正在处理…" : "模拟加入好学计划") {
                        Task { await purchase(with: SimulatedPurchaseProvider()) }
                    }
                    .buttonStyle(.borderedProminent).disabled(isPurchasing)
                    Button("使用 Xcode 本地 StoreKit 体验购买") { showStoreKit = true }
                        .disabled(isPurchasing)
                }
                if let error { Text(error).foregroundStyle(.red).font(.subheadline) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(24)
        }
        .navigationTitle("好学计划")
        .confirmationDialog("本地 StoreKit 演示", isPresented: $showStoreKit) {
            Button("继续购买") { Task { await purchase(with: StoreKitDemoPurchaseProvider()) } }
        } message: {
            Text("仅供 Xcode 本地测试，不代表真实订阅或服务端权益。")
        }
    }

    private func benefit(_ title: String) -> some View {
        Label(title, systemImage: "checkmark").font(.body)
    }

    private func purchase(with provider: any PurchaseProviding) async {
        isPurchasing = true
        error = nil
        defer { isPurchasing = false }
        do {
            try await provider.purchasePlan()
            commercial.activatePlan()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct CreditView: View {
    let commercial: CommercialDemoStore
    @State private var isPurchasing = false
    @State private var error: String?

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 8) {
                    Text(commercial.creditBalance.formatted()).font(.system(size: 42, weight: .bold))
                    Text("当前可用额度").foregroundStyle(.secondary)
                }.padding(.vertical, 14)
                LabeledContent("本月使用", value: commercial.usedCredits.formatted())
                LabeledContent("每月学习额度", value: commercial.monthlyCreditAllowance.formatted())
            }
            Section {
                Text("好学在分析作业、生成个性化教学和练习时会使用学习额度。")
            }
            Section("增加学习额度 · Demo") {
                Button("1,000,000 学习额度 · ¥5") {
                    Task { await purchase(with: SimulatedPurchaseProvider(), amount: 1_000_000) }
                }
                Button("5,000,000 学习额度 · ¥20") {
                    Task { await purchase(with: SimulatedPurchaseProvider(), amount: 5_000_000) }
                }
                Button("通过 Xcode 本地 StoreKit 体验 ¥5 商品") {
                    Task { await purchase(with: StoreKitDemoPurchaseProvider(), amount: 1_000_000) }
                }
                if isPurchasing { ProgressView("正在处理…") }
                if let error { Text(error).foregroundStyle(.red) }
                Text("金额与余额均为本地 Demo 数据，不构成真实充值。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("学习额度")
    }

    private func purchase(with provider: any PurchaseProviding, amount: Int) async {
        guard !isPurchasing else { return }
        isPurchasing = true
        error = nil
        defer { isPurchasing = false }
        do {
            try await provider.purchaseCredits()
            commercial.addCredits(amount)
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct InviteView: View {
    let commercial: CommercialDemoStore
    @State private var copied = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("与你的同学一起开始好学。")
                    .font(.title2).padding(.top, 15)
                Text("你的邀请码").font(.headline)
                Text(commercial.referralCode)
                    .font(.system(.title, design: .monospaced, weight: .semibold))
                    .textSelection(.enabled)
                Button(copied ? "已复制" : "复制邀请码") {
                    UIPasteboard.general.string = commercial.referralCode
                    copied = true
                }.buttonStyle(.borderedProminent)
                Divider()
                Text("邀请一位同学开始使用好学，并完成首次学习后：")
                LabeledContent("你获得", value: "+1,000,000")
                LabeledContent("对方获得", value: "+1,000,000")
                Text("Hackathon Demo：暂不跟踪邀请或实际发放额度。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(24)
        }
        .navigationTitle("邀请同学")
    }
}
