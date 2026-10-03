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

// Semantic error codes. This mirrors the live backend catalog
// (`GET /api/v1/meta/error-codes`); `unknown` preserves any code added later.
enum ServiceErrorCode: Equatable {
    case unauthorized, notFound, analysisNotFound, sessionNotFound
    case knowledgePointNotFound, wrongQuestionNotFound, bookNotFound, noQuestionsAvailable
    case invalidImage, invalidSerialNumber, questionNotInSession, questionNotRecognized
    case validationError, sessionCompleted, idempotencyConflict, vlmTimeout
    case serviceUnavailable, internalError
    case unknown(String)

    init(rawValue: String) {
        switch rawValue {
        case "UNAUTHORIZED": self = .unauthorized
        case "NOT_FOUND": self = .notFound
        case "ANALYSIS_NOT_FOUND": self = .analysisNotFound
        case "SESSION_NOT_FOUND": self = .sessionNotFound
        case "KNOWLEDGE_POINT_NOT_FOUND": self = .knowledgePointNotFound
        case "WRONG_QUESTION_NOT_FOUND": self = .wrongQuestionNotFound
        case "BOOK_NOT_FOUND": self = .bookNotFound
        case "NO_QUESTIONS_AVAILABLE": self = .noQuestionsAvailable
        case "INVALID_IMAGE": self = .invalidImage
        case "INVALID_SERIAL_NUMBER": self = .invalidSerialNumber
        case "QUESTION_NOT_IN_SESSION": self = .questionNotInSession
        case "QUESTION_NOT_RECOGNIZED": self = .questionNotRecognized
        case "VALIDATION_ERROR": self = .validationError
        case "SESSION_COMPLETED": self = .sessionCompleted
        case "IDEMPOTENCY_CONFLICT": self = .idempotencyConflict
        case "VLM_TIMEOUT": self = .vlmTimeout
        case "SERVICE_UNAVAILABLE": self = .serviceUnavailable
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
