import Foundation

// Implement concrete Codable DTOs and mappers only after Backend schema alignment.
@MainActor
protocol DomainMapper {
    associatedtype DTO: Decodable
    associatedtype Domain
    func map(_ dto: DTO) throws -> Domain
}
