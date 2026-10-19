/// Ports anker-solix-api `errors.py`, ERRORS and raise_error, commit 8a5222b.
/// Categories without a dedicated case preserve the upstream code and message.
public enum AnkerError: Error, Equatable {
    case http(Int)
    case code(Int, String)
    case authorization
    case kickedOut
    case invalidCredentials
    case verificationRequired
    case retryExceeded
    case busy
    case throttled
    case connect
    case network
    case server
    case malformed

    public static func from(code: Int, message: String) -> AnkerError? {
        switch code {
        case 401, 403: .authorization
        case 429: .throttled
        case 502, 504, 997: .connect
        case 998: .network
        case 999: .server
        case 21105: .busy
        case 26050...26055: .verificationRequired
        case 26084: .kickedOut
        case 26108, 26156: .invalidCredentials
        case 100053: .retryExceeded
        case 10000...: .code(code, message)
        default: nil
        }
    }
}
