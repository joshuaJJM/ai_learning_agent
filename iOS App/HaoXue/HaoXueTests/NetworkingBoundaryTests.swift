import Foundation
import Testing
@testable import HaoXue

private struct ProbeDTO: Decodable { let value: String }
@MainActor private struct ProbeMapper: DomainMapper {
    func map(_ dto: ProbeDTO) throws -> String { dto.value }
}

private class StubProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() {}
    func respond(status: Int = 200, body: String = "{\"value\":\"probe\"}") {
        let response = HTTPURLResponse(url: request.url!, statusCode: status,
                                       httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
}
private final class SuccessStub: StubProtocol, @unchecked Sendable {
    override func startLoading() { respond() }
}
private final class HTTPFailureStub: StubProtocol, @unchecked Sendable {
    override func startLoading() { respond(status: 503) }
}
private final class InvalidJSONStub: StubProtocol, @unchecked Sendable {
    override func startLoading() { respond(body: "not-json") }
}
private final class NonHTTPStub: StubProtocol, @unchecked Sendable {
    override func startLoading() {
        let response = URLResponse(url: request.url!, mimeType: nil,
                                   expectedContentLength: 0, textEncodingName: nil)
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocolDidFinishLoading(self)
    }
}
private final class TimeoutStub: StubProtocol, @unchecked Sendable {
    override func startLoading() {
        client?.urlProtocol(self, didFailWithError: URLError(.timedOut))
    }
}
private final class CancelledStub: StubProtocol, @unchecked Sendable {
    override func startLoading() {
        client?.urlProtocol(self, didFailWithError: URLError(.cancelled))
    }
}
private final class OfflineStub: StubProtocol, @unchecked Sendable {
    override func startLoading() {
        client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
    }
}
private final class ForbiddenRequestStub: StubProtocol, @unchecked Sendable {
    override func startLoading() {
        Issue.record("Live skeleton must not request any endpoint")
        client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
    }
}

@MainActor
struct NetworkingBoundaryTests {
    private let request = URLRequest(url: URL(string: "https://fixture.invalid/probe")!)

    private func session(_ stub: AnyClass) -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [stub]
        return URLSession(configuration: configuration)
    }

    private func expectError(_ stub: AnyClass, _ expected: NetworkError) async {
        let session = session(stub)
        defer { session.invalidateAndCancel() }
        let client = APIClient(session: session)
        await #expect(throws: expected) {
            try await client.send(request, as: ProbeDTO.self)
        }
    }

    @Test func transportDecodesAndMapperReturnsDomain() async throws {
        let session = session(SuccessStub.self)
        defer { session.invalidateAndCancel() }
        let dto = try await APIClient(session: session).send(request, as: ProbeDTO.self)
        #expect(try ProbeMapper().map(dto) == "probe")
    }
    @Test func timeoutIsTypedWithoutWaiting() async { await expectError(TimeoutStub.self, .timeout) }
    @Test func httpStatusIsTyped() async { await expectError(HTTPFailureStub.self, .httpStatus(503)) }
    @Test func invalidJSONIsTyped() async { await expectError(InvalidJSONStub.self, .decoding) }
    @Test func nonHTTPIsTyped() async { await expectError(NonHTTPStub.self, .invalidResponse) }
    @Test func urlCancellationIsTyped() async { await expectError(CancelledStub.self, .cancelled) }
    @Test func offlineIsTyped() async { await expectError(OfflineStub.self, .transport(.notConnectedToInternet)) }

    @Test func taskCancellationIsTyped() async {
        let session = session(ForbiddenRequestStub.self)
        defer { session.invalidateAndCancel() }
        let client = APIClient(session: session)
        let task = Task { try await client.send(request, as: ProbeDTO.self) }
        task.cancel()
        await #expect(throws: NetworkError.cancelled) { try await task.value }
    }

    @Test func liveNeverRequestsOrFallsBack() async {
        let session = session(ForbiddenRequestStub.self)
        defer { session.invalidateAndCancel() }
        let live = LiveDataProvider(client: APIClient(session: session), configuration: AppConfiguration(mode: .live))
        await #expect(throws: ProviderError.contractNotConfigured) { try await live.fetchHome() }
        await #expect(throws: ProviderError.contractNotConfigured) { try await live.fetchAnalysis(id: "any") }
        await #expect(throws: ProviderError.contractNotConfigured) { try await live.fetchTutorSession(id: "any") }
        await #expect(throws: ProviderError.contractNotConfigured) { try await live.fetchPracticeSession(id: "any") }
    }

    @Test func machineErrorsPreserveUnknownCodes() {
        #expect(ServiceErrorCode(rawValue: "NEW_ERROR") == .unknown("NEW_ERROR"))
        #expect(ServiceErrorCode(rawValue: "VLM_TIMEOUT") == .vlmTimeout)
        #expect(ServiceErrorCode(rawValue: "IDEMPOTENCY_CONFLICT") == .idempotencyConflict)
    }
}
