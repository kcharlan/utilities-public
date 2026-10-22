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

/// One backend MQTT connection. Each connection attempt, and so each successful
/// connect, takes a new value; replies and receipts from different connections
/// never share one.
public struct ConnectionEpoch: Hashable, Sendable {
    public let value: UInt64
    public init(_ value: UInt64) { self.value = value }
}

/// Position in the backend's receive order: the connection a reply arrived on and
/// a receive sequence that increases with every reply the backend receives, across
/// connections. The backend assigns it when it takes the reply from its connection,
/// before the reply is decoded or queued to subscribers.
public struct ReceiveMark: Hashable, Sendable {
    public let connection: ConnectionEpoch
    public let sequence: UInt64
    public init(connection: ConnectionEpoch, sequence: UInt64) {
        self.connection = connection
        self.sequence = sequence
    }
}

/// Backend-issued freshness fence for a port command: the connection and the latest
/// receive sequence when the command write completed (or, for
/// `ChargerBackend.commandFence()`, when the fence was read). A reply is newer than
/// the command only when its mark has this connection and a greater sequence.
public struct PortCommandReceipt: Hashable, Sendable {
    public let fence: ReceiveMark
    public init(fence: ReceiveMark) { self.fence = fence }
}

public enum BackendEvent: Sendable {
    /// A decoded status reply and its position in the backend's receive order.
    case snapshot(ChargerSnapshot, ReceiveMark)
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
    /// Publishes one port switch command and returns when the write completed. It is
    /// publish-only: it never waits for, or implies, a change in the charger's state;
    /// a later status reply newer than the receipt's fence is the only confirmation.
    /// Throws when not connected, or when the connection or its context was replaced
    /// during the write.
    func setPortSwitch(_ target: PortSwitch, on: Bool) async throws -> PortCommandReceipt
    /// A fence for the current connection without publishing (a resumed operation
    /// after reconnection). Throws when not connected.
    func commandFence() async throws -> PortCommandReceipt
    /// Bounded-ending abort: revoke the current command context, close the captured
    /// link without the graceful MQTT DISCONNECT, cancel queued writes and resume
    /// pending sends with an error, and return only after they drained, so a
    /// replacement connection cannot start before. Authentication is kept: the
    /// backend can connect again later. Emits no status event.
    func abortCommands() async
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
