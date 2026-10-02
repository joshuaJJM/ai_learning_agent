import Foundation

enum DataMode { case mock, live }

struct AppConfiguration {
    var mode: DataMode = .mock
    var baseURL: URL? = nil
    var timeout: TimeInterval = 30
}
