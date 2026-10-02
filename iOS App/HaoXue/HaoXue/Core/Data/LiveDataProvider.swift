import Foundation

@MainActor
struct LiveDataProvider: HomeDataProviding, HomeSnapshotProviding, AnalysisDataProviding, TutorDataProviding, PracticeDataProviding {
    private let client: APIClient
    private let configuration: AppConfiguration
    private let mapper = Phase5Mapper()

    init(client: APIClient, configuration: AppConfiguration) {
        self.client = client
        self.configuration = configuration
    }

    func fetchHome() async throws -> HomeState {
        mapper.legacyHome(try await fetchHomeSnapshot())
    }
    func fetchAnalysis(id: String) async throws -> UploadAnalysis {
        mapper.legacyAnalysis(try await fetchAnalysisResult(id: id))
    }
    func fetchTutorSession(id: String) async throws -> TutorSession {
        let dto: TutorSessionDTO = try await get("tutor/sessions/\(id)")
        guard let turn = dto.turn else { throw ProviderError.contractNotConfigured }
        let source: TutorSource
        switch dto.sourceType {
        case "wrong_question": source = .wrongQuestion(dto.sourceId ?? "")
        case "uploaded_question": source = .uploadedQuestion(dto.sourceId ?? "")
        default: source = .knowledgePoint(dto.knowledgePointId ?? "")
        }
        return TutorSession(id: dto.tutorSessionId, source: source,
                            knowledgePointID: dto.knowledgePointId ?? "",
                            currentTurn: TutorTurn(id: turn.turnId, type: turn.turnType,
                text: turn.text, choices: turn.choices.compactMap {
                    guard let id = ChoiceID(rawValue: $0.key) else { return nil }
                    return TutorChoice(id: id, text: $0.text)
                }, phase: TutorPhase(rawValue: turn.phase), progress: turn.progress.percent,
                completed: dto.completed, knowledgeChange: dto.knowledgeChanges.first.map {
                    KnowledgeChange(knowledgePointID: $0.knowledgePointId,
                                    beforeMastery: $0.before, afterMastery: $0.after,
                                    summary: $0.name)
                }))
    }
    func fetchPracticeSession(id: String) async throws -> PracticeSession {
        throw ProviderError.contractNotConfigured
    }

    func fetchHomeSnapshot() async throws -> HomeSnapshot {
        let dto: HomeResponseDTO = try await get("home")
        return mapper.home(dto)
    }

    func fetchAnalysisResult(id: String) async throws -> HomeworkAnalysisResult {
        let dto: AnalysisResultDTO = try await get("homework/analyses/\(id)")
        return mapper.analysis(dto)
    }

    func fetchWrongQuestions(knowledgePointID: String? = nil, bookID: String? = nil,
                             status: String? = nil, dateFrom: Date? = nil,
                             limit: Int = 100) async throws -> [WrongQuestionSummary] {
        var query = [URLQueryItem(name: "limit", value: String(limit))]
        if let knowledgePointID { query.append(URLQueryItem(name: "knowledge_point_id", value: knowledgePointID)) }
        if let bookID { query.append(URLQueryItem(name: "book_id", value: bookID)) }
        if let status { query.append(URLQueryItem(name: "status", value: status)) }
        if let dateFrom { query.append(URLQueryItem(name: "date_from", value: ISO8601DateFormatter().string(from: dateFrom))) }
        let dto: WrongQuestionListDTO = try await get("wrong-questions", query: query)
        return dto.items.map(mapper.summary)
    }

    func fetchWrongQuestion(id: String) async throws -> WrongQuestionDetail {
        let dto: WrongQuestionDetailDTO = try await get("wrong-questions/\(id)")
        return mapper.wrongQuestion(dto)
    }

    func updateWrongQuestion(id: String, status: String? = nil,
                             favorite: Bool? = nil) async throws -> WrongQuestionDetail {
        var request = URLRequest(url: url("wrong-questions/\(id)"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(WrongQuestionPatchDTO(status: status, favorite: favorite))
        let dto: WrongQuestionDetailDTO = try await client.send(request, as: WrongQuestionDetailDTO.self)
        return mapper.wrongQuestion(dto)
    }

    func fetchKnowledgeDetail(id: String) async throws -> KnowledgePointDetail {
        let dto: KnowledgeDetailDTO = try await get("knowledge/\(id)")
        return mapper.knowledge(dto)
    }

    func fetchKnowledgeTree() async throws -> KnowledgeTreeDTO {
        try await get("knowledge")
    }

    func fetchErrorCodes() async throws -> ErrorCodeCatalogDTO {
        try await get("meta/error-codes")
    }

    func fetchKnowledgePoints() async throws -> KnowledgePointCatalogDTO {
        try await get("meta/knowledge-points")
    }

    private func get<DTO: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> DTO {
        var url = url(path)
        if !query.isEmpty {
            var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
            components.queryItems = query
            url = components.url!
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return try await client.send(request, as: DTO.self)
    }

    private func url(_ path: String) -> URL {
        let base = configuration.baseURL ?? AppConfiguration.demoBackendURL
        var url = base.appendingPathComponent("api/v1")
        for segment in path.split(separator: "/") {
            url.appendPathComponent(String(segment))
        }
        return url
    }
}
