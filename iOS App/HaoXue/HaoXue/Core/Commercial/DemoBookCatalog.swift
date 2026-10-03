import Foundation

struct DemoBook: Identifiable {
    let id: String
    let title: String
    let subtitle: String
    let category: String
    let coverAssetName: String
    let knowledgeTags: [String]
    let questionCount: Int
    let difficulty: String
    let description: String
}

enum DemoBookCatalog {
    // Original demo titles based on common Chinese high-school math workbook categories.
    static let books: [DemoBook] = [
        .init(id: "derivative", title: "导数专项训练", subtitle: "从求导到函数应用", category: "导数专项", coverAssetName: "book-derivative", knowledgeTags: ["导数", "基础求导", "导数与单调性"], questionCount: 128, difficulty: "进阶", description: "围绕求导、导数符号与函数变化设计的分层练习。"),
        .init(id: "monotonicity", title: "函数单调性精练", subtitle: "读懂变化的方向", category: "导数专项", coverAssetName: "book-monotonicity", knowledgeTags: ["函数", "单调性", "导数与单调性"], questionCount: 96, difficulty: "基础", description: "从图像与导数两个角度理解函数单调区间。"),
        .init(id: "extrema", title: "极值与最值突破", subtitle: "关键题型逐步掌握", category: "导数专项", coverAssetName: "book-extrema", knowledgeTags: ["函数极值", "极值", "最值", "导数"], questionCount: 112, difficulty: "进阶", description: "聚焦极值点、最值与参数讨论的常见题型。"),
        .init(id: "foundation", title: "高中数学基础巩固", subtitle: "每天一组，稳步向前", category: "高中数学精选", coverAssetName: "book-foundation", knowledgeTags: ["基础求导", "函数", "数学基础"], questionCount: 180, difficulty: "基础", description: "通过短练习巩固函数与基础运算。"),
        .init(id: "gaokao", title: "高考数学综合练习", subtitle: "真题思路与模拟训练", category: "高中数学精选", coverAssetName: "book-gaokao", knowledgeTags: ["高考数学", "导数", "函数极值"], questionCount: 220, difficulty: "综合", description: "以高考常见模块组织综合训练。"),
        .init(id: "multiple", title: "选择题每日练", subtitle: "用十分钟保持手感", category: "高中数学精选", coverAssetName: "book-multiple", knowledgeTags: ["选择题", "导数与单调性", "函数"], questionCount: 160, difficulty: "基础", description: "精选短时选择题，适合日常检验理解。"),
        .init(id: "topic", title: "函数专题题组", subtitle: "分类练习，逐个突破", category: "更多训练", coverAssetName: "book-topic", knowledgeTags: ["函数", "单调性", "函数极值"], questionCount: 144, difficulty: "进阶", description: "按知识主题组织函数性质与应用题组。"),
        .init(id: "review", title: "导数考前回顾", subtitle: "重要方法再看一遍", category: "更多训练", coverAssetName: "book-review", knowledgeTags: ["基础求导", "导数", "最值"], questionCount: 88, difficulty: "综合", description: "用典型题回顾导数模块的重要解题方法。")
    ]
}

struct BookRelevance {
    let book: DemoBook
    let matchedPoints: [RecommendationPoint]
    let score: Double
    var explanation: String {
        guard let first = matchedPoints.first else { return "适合探索新的数学主题" }
        return "与你正在学习的「\(first.name)」相关"
    }
}

struct RecommendationPoint {
    let id: String
    let name: String
    let mastery: Double
}

enum BookRecommendationEngine {
    static func points(from overview: KnowledgeOverview?) -> [RecommendationPoint] {
        guard let overview else { return [] }
        func flatten(_ nodes: [KnowledgeOverview.Node]) -> [KnowledgeOverview.Node] {
            nodes.flatMap { [$0] + flatten($0.children) }
        }
        let weakIDs = overview.weakestIDs
        return flatten(overview.nodes)
            .filter { weakIDs.contains($0.id) || $0.mastery < 0.7 }
            .map { RecommendationPoint(id: $0.id, name: $0.name, mastery: $0.mastery) }
    }

    static func rank(_ books: [DemoBook], using points: [RecommendationPoint]) -> [BookRelevance] {
        books.map { book in
            let matches = points.filter { point in
                book.knowledgeTags.contains { tag in point.name.contains(tag) || tag.contains(point.name) }
            }
            let score = matches.reduce(0.0) { sum, point in
                let specificity = book.knowledgeTags.reduce(0.0) { value, tag in
                    if point.name.contains(tag) { return value + Double(tag.count) / 3 }
                    if tag.contains(point.name) { return value + 0.5 }
                    return value
                }
                return sum + (1 - min(max(point.mastery, 0), 1)) * specificity
            }
            return BookRelevance(book: book, matchedPoints: matches, score: score)
        }.sorted { $0.score == $1.score ? $0.book.id < $1.book.id : $0.score > $1.score }
    }
}
