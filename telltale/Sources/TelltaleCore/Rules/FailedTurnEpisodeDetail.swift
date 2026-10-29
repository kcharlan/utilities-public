import Foundation

/// Ordered membership of counted failed turns. Older episodes can have an unknown prefix.
public struct FailedTurnEpisodeDetail: Codable, Sendable, Equatable {
    public struct Failure: Codable, Sendable, Equatable {
        public var turnID: String
        public var errorCode: String
        public init(turnID: String, errorCode: String) { self.turnID = turnID; self.errorCode = errorCode }
    }
    public var priorCount: Int
    public var failures: [Failure]
    public init(priorCount: Int, failures: [Failure]) { self.priorCount = priorCount; self.failures = failures }
    private func validate() throws {
        guard priorCount >= 0, priorCount <= Int.max - failures.count,
              Set(failures.map(\.turnID)).count == failures.count else {
            throw StoreError.invalidData("Invalid failed-turn episode detail")
        }
    }
    public func encoded() throws -> Data { try validate(); return Data(try StoreJSON.encode(self).utf8) }
    public static func decode(_ data: Data?) throws -> Self? {
        guard let data else { return nil }
        do { let value = try JSONDecoder().decode(Self.self, from: data); try value.validate(); return value }
        catch { throw StoreError.invalidData("Invalid failed-turn episode detail") }
    }
    public func reasons(in range: Range<Int>) -> [String]? {
        guard (try? validate()) != nil, range.lowerBound >= 0, range.upperBound <= priorCount + failures.count else { return nil }
        if range.isEmpty { return [] }
        guard range.lowerBound >= priorCount else { return nil }
        return failures[(range.lowerBound - priorCount)..<(range.upperBound - priorCount)].map(\.errorCode)
    }
}
