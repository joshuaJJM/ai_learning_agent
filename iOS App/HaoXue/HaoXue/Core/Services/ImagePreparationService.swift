import UIKit

enum ImagePreparationError: Error { case invalidImage, tooLarge }

struct ImagePreparationService {
    let longestEdge: CGFloat = 2400
    let maxBytes = 12 * 1024 * 1024

    func prepare(_ image: UIImage) throws -> Data {
        let original = image.size
        guard original.width > 0, original.height > 0 else { throw ImagePreparationError.invalidImage }
        var edge = longestEdge
        var quality: CGFloat = 0.82
        for _ in 0..<6 {
            let scale = min(1, edge / max(original.width, original.height))
            let size = CGSize(width: max(1, (original.width * scale).rounded()),
                              height: max(1, (original.height * scale).rounded()))
            let format = UIGraphicsImageRendererFormat.default()
            format.scale = 1
            format.opaque = true
            let renderer = UIGraphicsImageRenderer(size: size, format: format)
            let normalized = renderer.image { _ in
                UIColor.white.setFill()
                UIRectFill(CGRect(origin: .zero, size: size))
                image.draw(in: CGRect(origin: .zero, size: size))
            }
            guard let data = normalized.jpegData(compressionQuality: quality) else {
                throw ImagePreparationError.invalidImage
            }
            if data.count <= maxBytes { return data }
            edge *= 0.8
            quality = max(0.58, quality - 0.06)
        }
        throw ImagePreparationError.tooLarge
    }
}
