import CoreImage
import UIKit
import Vision

struct DocumentProcessingResult {
    let image: UIImage
    let wasDocumentCorrected: Bool
}

enum DocumentCoordinateMapper {
    static func vector(for point: CGPoint, in extent: CGRect) -> CIVector {
        let x = min(max(point.x, 0), 1)
        let y = min(max(point.y, 0), 1)
        return CIVector(x: extent.minX + x * extent.width,
                        y: extent.minY + y * extent.height)
    }
}

/// Applies a conservative perspective correction to photos that contain a clear page.
struct DocumentImageProcessor {
    private let context = CIContext()

    func process(_ image: UIImage) -> UIImage { processWithMetadata(image).image }

    func processWithMetadata(_ image: UIImage) -> DocumentProcessingResult {
        let normalized = normalize(image)
        guard let cgImage = normalized.cgImage else {
            return DocumentProcessingResult(image: normalized, wasDocumentCorrected: false)
        }

        let request = VNDetectRectanglesRequest()
        request.maximumObservations = 0
        request.minimumSize = 0.3
        request.minimumAspectRatio = 0.3
        request.quadratureTolerance = 25
        ScanDiagnostics.log("[DocumentDetection] request started originalSize=\(image.size) originalOrientation=\(image.imageOrientation.rawValue) normalizedSize=\(normalized.size) normalizedPixels=\(cgImage.width)x\(cgImage.height) minimumConfidence=\(request.minimumConfidence) minimumAspectRatio=\(request.minimumAspectRatio) maximumAspectRatio=\(request.maximumAspectRatio) minimumSize=\(request.minimumSize) quadratureTolerance=\(request.quadratureTolerance) maximumObservations=\(request.maximumObservations)")
        do {
            try VNImageRequestHandler(cgImage: cgImage, orientation: .up).perform([request])
        } catch {
            ScanDiagnostics.log("[DocumentDetection] request error=\(error); falling back to original")
            return DocumentProcessingResult(image: normalized, wasDocumentCorrected: false)
        }
        let rectangles = request.results ?? []
        ScanDiagnostics.log("[DocumentDetection] rectangle count=\(rectangles.count)")
        for candidate in rectangles {
            ScanDiagnostics.log("[DocumentDetection] candidate confidence=\(candidate.confidence) boundingBox=\(candidate.boundingBox) topLeft=\(candidate.topLeft) topRight=\(candidate.topRight) bottomLeft=\(candidate.bottomLeft) bottomRight=\(candidate.bottomRight)")
            if candidate.confidence < 0.65 { ScanDiagnostics.log("[DocumentDetection] rejected: confidence=\(candidate.confidence)") }
            else if !isLikelyPage(candidate) { ScanDiagnostics.log("[DocumentDetection] rejected: geometry or area boundingBox=\(candidate.boundingBox)") }
        }
        let detected = rectangles.filter { $0.confidence >= 0.65 && isLikelyPage($0) }
            .max { polygonArea($0) < polygonArea($1) }
        let rectangle: VNRectangleObservation
        if let detected {
            rectangle = detected
        } else if let borderEstimate = BorderPageDetector().detect(in: cgImage) {
            rectangle = borderEstimate
            ScanDiagnostics.log("[DocumentDetection] border estimate topLeft=\(rectangle.topLeft) topRight=\(rectangle.topRight) bottomLeft=\(rectangle.bottomLeft) bottomRight=\(rectangle.bottomRight)")
        } else {
            ScanDiagnostics.log("[DocumentDetection] document rectangle NOT FOUND; falling back to original")
            return DocumentProcessingResult(image: normalized, wasDocumentCorrected: false)
        }
        ScanDiagnostics.log("[DocumentDetection] document rectangle FOUND")

        let input = CIImage(cgImage: cgImage)
        let filter = CIFilter(name: "CIPerspectiveCorrection")!
        filter.setValue(input, forKey: kCIInputImageKey)
        filter.setValue(DocumentCoordinateMapper.vector(for: rectangle.topLeft, in: input.extent), forKey: "inputTopLeft")
        filter.setValue(DocumentCoordinateMapper.vector(for: rectangle.topRight, in: input.extent), forKey: "inputTopRight")
        filter.setValue(DocumentCoordinateMapper.vector(for: rectangle.bottomLeft, in: input.extent), forKey: "inputBottomLeft")
        filter.setValue(DocumentCoordinateMapper.vector(for: rectangle.bottomRight, in: input.extent), forKey: "inputBottomRight")
        ScanDiagnostics.log("[PerspectiveCorrection] input extent=\(input.extent)")
        guard let output = filter.outputImage,
              let corrected = context.createCGImage(output, from: output.extent.integral) else {
            ScanDiagnostics.log("[PerspectiveCorrection] output unavailable; falling back to original")
            return DocumentProcessingResult(image: normalized, wasDocumentCorrected: false)
        }
        ScanDiagnostics.log("[PerspectiveCorrection] output extent=\(output.extent) output size=\(corrected.width)x\(corrected.height)")
        return DocumentProcessingResult(
            image: UIImage(cgImage: corrected, scale: normalized.scale, orientation: .up),
            wasDocumentCorrected: true
        )
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
        let area = polygonArea(rectangle)
        return area >= 0.18 && rectangle.boundingBox.width >= 0.35 && rectangle.boundingBox.height >= 0.35
    }

    private func polygonArea(_ rectangle: VNRectangleObservation) -> CGFloat {
        let points = [rectangle.topLeft, rectangle.topRight,
                      rectangle.bottomRight, rectangle.bottomLeft]
        let area = abs(points.indices.reduce(CGFloat.zero) { sum, index in
            let next = points[(index + 1) % points.count]
            return sum + points[index].x * next.y - next.x * points[index].y
        }) / 2
        return area
    }

}
