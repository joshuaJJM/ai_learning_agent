import UIKit

enum ScanSource { case camera, photos }

struct ScanPage: Identifiable {
    let id = UUID()
    let image: UIImage
    let source: ScanSource
    let wasDocumentCorrected: Bool
    let originalSize: CGSize

    init(image: UIImage, source: ScanSource, wasDocumentCorrected: Bool = false,
         originalSize: CGSize? = nil) {
        self.image = image
        self.source = source
        self.wasDocumentCorrected = wasDocumentCorrected
        self.originalSize = originalSize ?? image.size
    }
}
