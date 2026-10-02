import Foundation

enum NetworkError: Error, Equatable {
    case invalidResponse
    case transport(URLError.Code)
    case cancelled
    case timeout
    case httpStatus(Int)
    case decoding
    case backend(code: String, message: String, requestID: String?, status: Int)
}

// Semantic error codes; a future Backend DTO mapper owns envelope parsing.
enum ServiceErrorCode: Equatable {
    case invalidImage, analysisFailed, vlmTimeout, questionNotRecognized
    case idempotencyConflict, sessionNotFound, sessionCompleted, internalError
    case unknown(String)

    init(rawValue: String) {
        switch rawValue {
        case "INVALID_IMAGE": self = .invalidImage
        case "ANALYSIS_FAILED": self = .analysisFailed
        case "VLM_TIMEOUT": self = .vlmTimeout
        case "QUESTION_NOT_RECOGNIZED": self = .questionNotRecognized
        case "IDEMPOTENCY_CONFLICT": self = .idempotencyConflict
        case "SESSION_NOT_FOUND": self = .sessionNotFound
        case "SESSION_COMPLETED": self = .sessionCompleted
        case "INTERNAL_ERROR": self = .internalError
        default: self = .unknown(rawValue)
        }
    }
}

@MainActor
final class APIClient {
    private let session: URLSession
    private let timeout: TimeInterval

    init(session: URLSession = .shared, timeout: TimeInterval = 30) {
        self.session = session
        self.timeout = timeout
    }

    func sendData(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        var request = request
        request.timeoutInterval = timeout
        do {
            try Task.checkCancellation()
            let (data, response) = try await session.data(for: request)
            try Task.checkCancellation()
            guard let response = response as? HTTPURLResponse else { throw NetworkError.invalidResponse }
            return (data, response)
        } catch is CancellationError {
            throw NetworkError.cancelled
        } catch let error as URLError {
            if error.code == .cancelled { throw NetworkError.cancelled }
            if error.code == .timedOut { throw NetworkError.timeout }
            throw NetworkError.transport(error.code)
        }
    }

    // Caller supplies URLRequest; no endpoint schema or request framework yet.
    func send<DTO: Decodable>(_ request: URLRequest, as: DTO.Type) async throws -> DTO {
        var request = request
        request.timeoutInterval = timeout
        let data: Data
        let response: URLResponse
        do {
            try Task.checkCancellation()
            (data, response) = try await session.data(for: request)
            try Task.checkCancellation()
        } catch is CancellationError {
            throw NetworkError.cancelled
        } catch let error as URLError {
            switch error.code {
            case .cancelled: throw NetworkError.cancelled
            case .timedOut: throw NetworkError.timeout
            default: throw NetworkError.transport(error.code)
            }
        } catch {
            throw NetworkError.transport(.unknown)
        }
        guard let response = response as? HTTPURLResponse else {
            throw NetworkError.invalidResponse
        }
        try validate(response, data: data)
        do {
            return try BackendJSON.decoder.decode(DTO.self, from: data)
        } catch {
            throw NetworkError.decoding
        }
    }

    func validate(_ response: HTTPURLResponse, data: Data) throws {
        guard (200...299).contains(response.statusCode) else {
            if let error = try? BackendJSON.decoder.decode(BackendErrorDTO.self, from: data) {
                throw NetworkError.backend(code: error.errorCode, message: error.message,
                                           requestID: error.requestId, status: response.statusCode)
            }
            throw NetworkError.httpStatus(response.statusCode)
        }
    }
}
