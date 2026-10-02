import Foundation

@MainActor
protocol AnalysisServing {
    func create(images: [Data], key: UUID) async throws -> CreateAnalysisResponse
    func get(id: String) async throws -> AnalysisResponse
}

enum AnalysisServiceError: Error {
    case backend(String)
    case unexpectedStatus(Int)
}

@MainActor
struct LiveAnalysisService: AnalysisServing {
    let baseURL: URL
    let client: APIClient

    func makeCreateRequest(images: [Data], key: UUID) -> URLRequest {
        let boundary = "HaoXue-\(key.uuidString)"
        var request = URLRequest(url: baseURL.appendingPathComponent("api/v1/homework/analyses"))
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.setValue(key.uuidString, forHTTPHeaderField: "Idempotency-Key")
        var body = Data()
        for (index, image) in images.enumerated() {
            body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"images\"; filename=\"page-\(index + 1).jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".utf8))
            body.append(image)
            body.append(Data("\r\n".utf8))
        }
        body.append(Data("--\(boundary)--\r\n".utf8))
        request.httpBody = body
        return request
    }

    func create(images: [Data], key: UUID) async throws -> CreateAnalysisResponse {
        let (data, response) = try await client.sendData(makeCreateRequest(images: images, key: key))
        ScanDiagnostics.log("CREATE http=\(response.statusCode) body=\(String(decoding: data.prefix(2048), as: UTF8.self))")
        try validate(response, data: data)
        guard response.statusCode == 202 else { throw AnalysisServiceError.unexpectedStatus(response.statusCode) }
        do {
            let created = try JSONDecoder().decode(CreateAnalysisResponse.self, from: data)
            ScanDiagnostics.log("CREATE analysis_id=\(created.analysisID) status=\(created.status.rawValue)")
            return created
        } catch {
            ScanDiagnostics.log("CREATE decode_error=\(error)")
            throw error
        }
    }

    func get(id: String) async throws -> AnalysisResponse {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/v1/homework/analyses/\(id)"))
        request.httpMethod = "GET"
        let (data, response) = try await client.sendData(request)
        ScanDiagnostics.log("POLL http=\(response.statusCode) analysis_id=\(id)")
        try validate(response, data: data)
        do {
            return try JSONDecoder().decode(AnalysisResponse.self, from: data)
        } catch {
            ScanDiagnostics.log("POLL decode_error=\(error) analysis_id=\(id)")
            throw error
        }
    }

    private func validate(_ response: HTTPURLResponse, data: Data) throws {
        guard (200...299).contains(response.statusCode) else {
            let error = try? JSONDecoder().decode(AnalysisFailure.self, from: data)
            throw AnalysisServiceError.backend(error?.errorCode ?? "HTTP_\(response.statusCode)")
        }
    }
}

@MainActor
final class MockAnalysisService: AnalysisServing {
    private var polls = 0

    func create(images: [Data], key: UUID) async throws -> CreateAnalysisResponse {
        polls = 0
        return CreateAnalysisResponse(analysisID: "mock-\(key.uuidString)", status: .queued)
    }

    func get(id: String) async throws -> AnalysisResponse {
        polls += 1
        let keys = ["image_received", "questions_detected", "answers_understood", "error_patterns", "knowledge_updated"]
        let labels = ["已接收图片", "已识别题目", "已理解作答", "正在分析错误模式", "正在更新知识状态"]
        let active = min(polls - 1, 4)
        let complete = polls > 5
        let stages = zip(keys, labels).enumerated().map { index, pair in
            AnalysisStage(key: pair.0, labelZH: pair.1,
                          state: complete || index < active ? .done : index == active ? .active : .pending)
        }
        return AnalysisResponse(analysisID: id, status: complete ? .completed : .processing,
                                progress: AnalysisProgress(percent: complete ? 1 : Double(polls) / 6,
                                                           currentStageKey: complete ? nil : keys[active],
                                                           currentStageLabelZH: complete ? nil : labels[active], stages: stages),
                                error: nil)
    }
}
