import CoreImage
import UIKit
import Vision

/// Applies a conservative perspective correction to photos that contain a clear page.
struct DocumentImageProcessor {
    private let context = CIContext()

    func process(_ image: UIImage) -> UIImage {
        let normalized = normalize(image)
        guard let cgImage = normalized.cgImage else { return normalized }

        let request = VNDetectRectanglesRequest()
        request.maximumObservations = 1
        request.minimumSize = 0.3
        request.minimumAspectRatio = 0.3
        request.quadratureTolerance = 25
        do {
            try VNImageRequestHandler(cgImage: cgImage).perform([request])
        } catch {
            ScanDiagnostics.log("documentDetectionError=\(error)")
            return normalized
        }
        guard let rectangle = request.results?.first,
              rectangle.confidence >= 0.65,
              isLikelyPage(rectangle) else {
            ScanDiagnostics.log("documentDetectionFallback")
            return normalized
        }

        let input = CIImage(cgImage: cgImage)
        let width = CGFloat(cgImage.width)
        let height = CGFloat(cgImage.height)
        let filter = CIFilter(name: "CIPerspectiveCorrection")!
        filter.setValue(input, forKey: kCIInputImageKey)
        filter.setValue(vector(rectangle.topLeft, width, height), forKey: "inputTopLeft")
        filter.setValue(vector(rectangle.topRight, width, height), forKey: "inputTopRight")
        filter.setValue(vector(rectangle.bottomLeft, width, height), forKey: "inputBottomLeft")
        filter.setValue(vector(rectangle.bottomRight, width, height), forKey: "inputBottomRight")
        guard let output = filter.outputImage,
              let corrected = context.createCGImage(output, from: output.extent.integral) else {
            return normalized
        }
        ScanDiagnostics.log("documentCorrected original=\(cgImage.width)x\(cgImage.height) output=\(corrected.width)x\(corrected.height) confidence=\(rectangle.confidence)")
        return UIImage(cgImage: corrected, scale: normalized.scale, orientation: .up)
    }

    private func normalize(_ image: UIImage) -> UIImage {
        guard image.imageOrientation != .up else { return image }
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = image.scale
        return UIGraphicsImageRenderer(size: image.size, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: image.size))
        }
    }

    private func isLikelyPage(_ rectangle: VNRectangleObservation) -> Bool {
        let points = [rectangle.topLeft, rectangle.topRight,
                      rectangle.bottomRight, rectangle.bottomLeft]
        let area = abs(points.indices.reduce(CGFloat.zero) { sum, index in
            let next = points[(index + 1) % points.count]
            return sum + points[index].x * next.y - next.x * points[index].y
        }) / 2
        return area >= 0.18 && rectangle.boundingBox.width >= 0.35 && rectangle.boundingBox.height >= 0.35
    }

    private func vector(_ point: CGPoint, _ width: CGFloat, _ height: CGFloat) -> CIVector {
        CIVector(x: point.x * width, y: point.y * height)
    }
}
