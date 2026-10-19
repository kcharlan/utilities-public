import Foundation

public struct BackoffPolicy: Sendable {
    private var delay: TimeInterval = 1

    public init() {}

    /// Mirrors paho-mqtt 2.1.0 client.py, Client._reconnect_wait and the
    /// constructor's 1/120 s defaults. Anker's mqtt.py, connect_client_async,
    /// delegates reconnects to that client (anker-solix-api commit 8a5222b;
    /// protocol reference §3.2).
    public mutating func nextDelay() -> TimeInterval {
        let result = delay
        delay = min(delay * 2, 120)
        return result
    }

    public mutating func reset() { delay = 1 }
}
