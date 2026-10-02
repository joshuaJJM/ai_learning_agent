import UIKit

enum ScanSource { case camera, photos }

struct ScanPage: Identifiable {
    let id = UUID()
    let image: UIImage
    let source: ScanSource
}
