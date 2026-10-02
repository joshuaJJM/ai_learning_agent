import Foundation

enum DataMode { case mock, live }

struct AppConfiguration {
    static let demoBackendURL = URL(string: "http://121.43.137.176:17283")!
    var mode: DataMode = .mock
    var baseURL: URL? = nil
    var timeout: TimeInterval = 30
}
