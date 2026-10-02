import Foundation

enum ScanDiagnostics {
    static func log(_ message: String) {
        #if DEBUG
        NSLog("[ScanDebug] %@ %@", ISO8601DateFormatter().string(from: Date()), message)
        #endif
    }
}
