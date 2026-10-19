public enum ConnectionStatus: Equatable, Sendable {
    case notConfigured, connecting, connected
    case networkUnavailable
    case sessionEnded
    case signInFailed(String)
    case verificationRequired
    case error(String)
}
