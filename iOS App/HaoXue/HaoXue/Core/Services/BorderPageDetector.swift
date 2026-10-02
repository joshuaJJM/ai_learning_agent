import CoreGraphics
import Vision

/// Estimates a page whose outer edge runs beyond the photo frame.
/// The estimate is used only when long, consistent light-to-dark borders exist.
struct BorderPageDetector {
    private struct Sample {
        let position: Double
        let boundary: Double
    }

    private struct Line {
        let intercept: Double
        let slope: Double
        func value(at position: Double) -> Double { intercept + slope * position }
    }

    func detect(in image: CGImage) -> VNRectangleObservation? {
        let width = 240
        let height = max(160, Int((Double(image.height) / Double(image.width) * Double(width)).rounded()))
        var pixels = [UInt8](repeating: 0, count: width * height)
        guard let context = CGContext(data: &pixels, width: width, height: height,
                                      bitsPerComponent: 8, bytesPerRow: width,
                                      space: CGColorSpaceCreateDeviceGray(),
                                      bitmapInfo: CGImageAlphaInfo.none.rawValue) else { return nil }
        context.translateBy(x: 0, y: CGFloat(height))
        context.scaleBy(x: 1, y: -1)
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))

        func brightness(_ x: Int, _ y: Int) -> Double {
            let clampedX = min(max(x, 0), width - 1)
            let clampedY = min(max(y, 0), height - 1)
            var sum = 0
            for row in (clampedY - 2)...(clampedY + 2) {
                let yy = min(max(row, 0), height - 1)
                for column in (clampedX - 2)...(clampedX + 2) {
                    let xx = min(max(column, 0), width - 1)
                    sum += Int(pixels[(height - 1 - yy) * width + xx])
                }
            }
            return Double(sum) / 25
        }

        func strongest(in range: Range<Int>, strength: (Int) -> Double) -> (Int, Double)? {
            guard let candidate = range.map({ ($0, strength($0)) }).max(by: { $0.1 < $1.1 }),
                  candidate.1 >= 23 else { return nil }
            return candidate
        }

        let rows = (1...8).map { Int(Double(height) * Double($0) / 10) }
        let columns = [0.2, 0.35, 0.5, 0.65, 0.8].map { Int(Double(width) * $0) }
        let left = rows.compactMap { y -> Sample? in
            guard let edge = strongest(in: Int(Double(width) * 0.035)..<Int(Double(width) * 0.30),
                                       strength: { brightness($0 + 4, y) - brightness($0 - 4, y) }) else { return nil }
            return Sample(position: Double(y), boundary: Double(edge.0))
        }
        let right = rows.compactMap { y -> Sample? in
            guard let edge = strongest(in: Int(Double(width) * 0.70)..<(width - 4),
                                       strength: { brightness($0 - 4, y) - brightness($0 + 4, y) }) else { return nil }
            return Sample(position: Double(y), boundary: Double(edge.0))
        }
        let top = columns.compactMap { x -> Sample? in
            guard let edge = strongest(in: 4..<Int(Double(height) * 0.13),
                                       strength: { brightness(x, $0 + 4) - brightness(x, $0 - 4) }) else { return nil }
            return Sample(position: Double(x), boundary: Double(edge.0))
        }
        let bottom = columns.compactMap { x -> Sample? in
            guard let edge = strongest(in: Int(Double(height) * 0.86)..<(height - 4),
                                       strength: { brightness(x, $0 - 4) - brightness(x, $0 + 4) }) else { return nil }
            return Sample(position: Double(x), boundary: Double(edge.0))
        }
        ScanDiagnostics.log("[BorderPage] samples left=\(left.map { "\(Int($0.position)):\(Int($0.boundary))" }) right=\(right.map { "\(Int($0.position)):\(Int($0.boundary))" }) top=\(top.map { "\(Int($0.position)):\(Int($0.boundary))" }) bottom=\(bottom.map { "\(Int($0.position)):\(Int($0.boundary))" })")
        guard left.count >= 5, right.count >= 4, top.count >= 3, bottom.count >= 3,
              let leftLine = fit(left), let rightLine = fit(right),
              let topLine = fit(top), let bottomLine = fit(bottom) else { return nil }

        func intersection(vertical: Line, horizontal: Line) -> CGPoint? {
            let denominator = 1 - vertical.slope * horizontal.slope
            guard abs(denominator) > 0.1 else { return nil }
            let x = (vertical.intercept + vertical.slope * horizontal.intercept) / denominator
            let y = horizontal.value(at: x)
            return CGPoint(x: min(max(x / Double(width), 0.005), 0.995),
                           y: min(max(y / Double(height), 0.005), 0.995))
        }
        guard let tl = intersection(vertical: leftLine, horizontal: topLine),
              let tr = intersection(vertical: rightLine, horizontal: topLine),
              let bl = intersection(vertical: leftLine, horizontal: bottomLine),
              let br = intersection(vertical: rightLine, horizontal: bottomLine),
              tl.x < 0.3, tr.x > 0.7, bl.x < 0.3, br.x > 0.7,
              tl.y < 0.15, tr.y < 0.15, bl.y > 0.85, br.y > 0.85,
              tr.x - tl.x > 0.6, br.x - bl.x > 0.6 else { return nil }
        ScanDiagnostics.log("[BorderPage] corners TL=\(tl) TR=\(tr) BL=\(bl) BR=\(br)")

        // The book gutter can cast a wide shadow onto the page. Leave room for
        // the first characters of questions beside that shadow.
        let leftMargin = 0.07
        let rightMargin = 0.015
        let topLeft = CGPoint(x: max(tl.x - leftMargin, 0), y: max(tl.y - 0.005, 0))
        let topRight = CGPoint(x: min(tr.x + rightMargin, 1), y: max(tr.y - 0.005, 0))
        let bottomLeft = CGPoint(x: max(bl.x - leftMargin, 0), y: min(bl.y + 0.005, 1))
        let bottomRight = CGPoint(x: min(br.x + rightMargin, 1), y: min(br.y + 0.005, 1))
        // Bitmap samples use a top-left origin; Vision points use a bottom-left origin.
        return VNRectangleObservation(requestRevision: 1,
                                      topLeft: CGPoint(x: topLeft.x, y: 1 - topLeft.y),
                                      topRight: CGPoint(x: topRight.x, y: 1 - topRight.y),
                                      bottomRight: CGPoint(x: bottomRight.x, y: 1 - bottomRight.y),
                                      bottomLeft: CGPoint(x: bottomLeft.x, y: 1 - bottomLeft.y))
    }

    private func fit(_ samples: [Sample]) -> Line? {
        var best = [Sample]()
        for first in samples.indices {
            for second in samples.indices where second > first {
                let a = samples[first]
                let b = samples[second]
                let slope = (b.boundary - a.boundary) / (b.position - a.position)
                let intercept = a.boundary - slope * a.position
                let inliers = samples.filter { abs(intercept + slope * $0.position - $0.boundary) < 7 }
                if inliers.count > best.count { best = inliers }
            }
        }
        guard best.count >= max(3, samples.count - 1) else { return nil }
        let count = Double(best.count)
        let meanPosition = best.reduce(0) { $0 + $1.position } / count
        let meanBoundary = best.reduce(0) { $0 + $1.boundary } / count
        let variance = best.reduce(0) { $0 + pow($1.position - meanPosition, 2) }
        guard variance > 1 else { return nil }
        let covariance = best.reduce(0) { $0 + ($1.position - meanPosition) * ($1.boundary - meanBoundary) }
        let slope = covariance / variance
        let intercept = meanBoundary - slope * meanPosition
        let residual = best.reduce(0) { $0 + abs(intercept + slope * $1.position - $1.boundary) } / count
        guard residual < 8 else { return nil }
        return Line(intercept: intercept, slope: slope)
    }
}
