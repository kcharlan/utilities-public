import Foundation

public struct AnkerCredentials: Codable, Equatable, Sendable {
    public let email: String
    public let password: String
    public let country: String

    public init(email: String, password: String, country: String) {
        self.email = email
        self.password = password
        self.country = country
    }
}

public struct AccountSession: Codable, Equatable, Sendable {
    public let authToken: String
    public let userID: String
    public let expiresAt: Date
    public let nickname: String

    public init(authToken: String, userID: String, expiresAt: Date, nickname: String) {
        self.authToken = authToken
        self.userID = userID
        self.expiresAt = expiresAt
        self.nickname = nickname
    }
}

public enum BackendEvent: Sendable {
    case snapshot(ChargerSnapshot)
    case status(ConnectionStatus)
    case sessionUpdated(AccountSession)
    case alive(Date)
}

public protocol ChargerBackend: Sendable {
    func signIn(_ credentials: AnkerCredentials) async throws -> AccountSession
    func restore(_ session: AccountSession, credentials: AnkerCredentials) async
    func listChargers() async throws -> [ChargerInfo]
    func connect(to charger: ChargerInfo) async throws
    func requestSnapshot() async throws
    /// A fresh, independent, non-replaying subscription on each access.
    /// Cancellation removes only that subscription. Events emitted before the
    /// subscription is created cannot appear in its queue.
    var events: AsyncStream<BackendEvent> { get }
    /// Explicit async form for clients that hand over authentication contexts.
    /// After disconnect has invalidated old producers, cancel/await the previous
    /// consumer, subscribe afresh, then sign in or restore. Repeat this handover
    /// before EVERY restore, including reconnects. An event already queued for
    /// the old context stays in the old subscription and cannot cross handover.
    /// Backend implementations must generation-check producers across awaits.
    func subscribeToEvents() async -> AsyncStream<BackendEvent>
    func disconnect() async
}
