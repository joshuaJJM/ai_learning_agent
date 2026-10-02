import Foundation

struct TutorSSEFrame: Equatable {
    let event: String
    let data: Data
}

enum TutorSSEParserError: Error {
    case invalidUTF8
}

struct TutorSSEParser {
    private var pending = Data()
    private var eventName = ""
    private var dataLines: [Data] = []

    mutating func append(_ chunk: Data) throws -> [TutorSSEFrame] {
        pending.append(chunk)
        var frames: [TutorSSEFrame] = []
        while let newline = pending.firstIndex(of: 0x0A) {
            var line = pending.prefix(upTo: newline)
            pending.removeSubrange(pending.startIndex...newline)
            if line.last == 0x0D { line = line.dropLast() }
            if line.isEmpty {
                if !dataLines.isEmpty {
                    let data = dataLines.reduce(into: Data()) { result, part in
                        if !result.isEmpty { result.append(0x0A) }
                        result.append(part)
                    }
                    frames.append(TutorSSEFrame(event: eventName, data: data))
                }
                eventName = ""
                dataLines = []
            } else if line.starts(with: Data("event:".utf8)) {
                guard let name = String(data: line.dropFirst(6), encoding: .utf8) else {
                    throw TutorSSEParserError.invalidUTF8
                }
                eventName = name.trimmingCharacters(in: .whitespaces)
            } else if line.starts(with: Data("data:".utf8)) {
                let content = line.dropFirst(5)
                dataLines.append(Data(content.first == 0x20 ? content.dropFirst() : content))
            }
        }
        return frames
    }
}
