import CryptoKit
import Foundation
import PrimeMonitorCore

/// Ports anker-solix-api `apitypes.py`, API_HEADERS, and `session.py`,
/// AnkerSolixClientSession.generate_header / async_authenticate, commit 8a5222b.
public enum RequestBuilder {
    public static func headers(country: String, timeZone: TimeZone, session: AccountSession?) -> [String: String] {
        let minutes = timeZone.secondsFromGMT() / 60
        var result = [
            "content-type": "application/json", "model-type": "DESKTOP",
            "app-name": "anker_power", "os-type": "android",
            "timezone": String(format: "GMT%@%02d:%02d", minutes < 0 ? "-" : "+", abs(minutes) / 60, abs(minutes) % 60)
        ]
        if !country.isEmpty { result["country"] = country.uppercased() }
        if let session, !session.authToken.isEmpty {
            result["x-auth-token"] = session.authToken
            result["gtoken"] = Insecure.MD5.hash(data: Data(session.userID.utf8))
                .map { String(format: "%02x", $0) }.joined()
        }
        return result
    }

    public static func loginBody(credentials: AnkerCredentials, crypto: LoginCrypto, now: Date, timeZone: TimeZone) throws -> Data {
        try JSONSerialization.data(withJSONObject: [
            "ab": credentials.country.uppercased(),
            "client_secret_info": ["public_key": crypto.publicKeyHex],
            "enc": 0,
            "email": credentials.email,
            "password": crypto.encryptPassword(credentials.password),
            "time_zone": timeZone.secondsFromGMT(for: now) * 1000,
            "transaction": String(Int64(now.timeIntervalSince1970 * 1000))
        ])
    }
}
