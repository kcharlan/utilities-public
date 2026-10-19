import CryptoKit
import Foundation
import PrimeMonitorCore
import Testing
@testable import AnkerCloud

@Test func usUsesComServerAndUnknownFallsBackToEU() {
    #expect(AnkerRegion.baseURL(country: "us").absoluteString == "https://ankerpower-api.anker.com")
    for country in ["ZZ", "", "DE", "JP", "SG", "UK"] {
        #expect(AnkerRegion.baseURL(country: country).absoluteString == "https://ankerpower-api-eu.anker.com")
    }
}

@Test func allUpstreamComCountriesUseComServer() {
    for country in ["DZ", "LB", "SY", "EG", "LY", "TN", "MA", "JO", "PS", "AR", "AU", "BR", "HK", "IN", "MX", "NG", "NZ", "RU", "ZA", "KR", "TW", "US", "CA"] {
        #expect(AnkerRegion.baseURL(country: country.lowercased()).absoluteString == "https://ankerpower-api.anker.com")
    }
}

@Test func headersMatchUpstream() {
    let h = RequestBuilder.headers(country: "us", timeZone: TimeZone(secondsFromGMT: -4 * 3600)!, session: nil)
    #expect(h == ["content-type": "application/json", "model-type": "DESKTOP", "app-name": "anker_power",
                  "os-type": "android", "country": "US", "timezone": "GMT-04:00"])
    let s = AccountSession(authToken: "tok", userID: "synthetic-user", expiresAt: .distantFuture, nickname: "")
    let h2 = RequestBuilder.headers(country: "US", timeZone: .gmt, session: s)
    let md5 = Insecure.MD5.hash(data: Data("synthetic-user".utf8)).map { String(format: "%02x", $0) }.joined()
    #expect(h2["x-auth-token"] == "tok")
    #expect(h2["gtoken"] == md5)
    #expect(h2["timezone"] == "GMT+00:00")
}

@Test func emptyCountryAndTokenAreOmittedAndFractionalOffsetsArePreserved() {
    let session = AccountSession(authToken: "", userID: "synthetic-user", expiresAt: .distantFuture, nickname: "")
    let headers = RequestBuilder.headers(country: "", timeZone: TimeZone(secondsFromGMT: 5 * 3600 + 45 * 60)!, session: session)
    #expect(headers["country"] == nil)
    #expect(headers["x-auth-token"] == nil)
    #expect(headers["gtoken"] == nil)
    #expect(headers["timezone"] == "GMT+05:45")
    #expect(RequestBuilder.headers(country: "US", timeZone: TimeZone(secondsFromGMT: -3 * 3600 - 30 * 60)!, session: nil)["timezone"] == "GMT-03:30")
}

@Test func loginBodyFields() throws {
    let vectors = try loadVectors()
    let crypto = LoginCrypto(privateKey: try .init(rawRepresentation: bytes(hex: vectors.privateScalarHex)))
    let credentials = AnkerCredentials(email: "synthetic@example.invalid", password: "synthetic-password-123", country: "us")
    let data = try RequestBuilder.loginBody(credentials: credentials, crypto: crypto,
                                           now: Date(timeIntervalSince1970: 1_700_000_000.125),
                                           timeZone: TimeZone(secondsFromGMT: -4 * 3600)!)
    let body = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    #expect(Set(body.keys) == Set(["ab", "client_secret_info", "enc", "email", "password", "time_zone", "transaction"]))
    #expect(body["ab"] as? String == "US")
    #expect(body["client_secret_info"] as? [String: String] == ["public_key": vectors.publicKeyHex])
    #expect(body["enc"] as? Int == 0)
    #expect(body["email"] as? String == "synthetic@example.invalid")
    #expect(body["password"] as? String == vectors.passwordB64)
    #expect(body["time_zone"] as? Int == -14_400_000)
    #expect(body["transaction"] as? String == "1700000000125")
}

@Test func loginBodyUsesSuppliedDateForDaylightSavingAndTruncatesMilliseconds() throws {
    let zone = try #require(TimeZone(identifier: "America/New_York"))
    let credentials = AnkerCredentials(email: "synthetic@example.invalid", password: "", country: "ca")
    for (timestamp, offset, transaction) in [(1_704_067_200.9999, -18_000_000, "1704067200999"),
                                              (1_719_792_000.9999, -14_400_000, "1719792000999")] {
        let data = try RequestBuilder.loginBody(credentials: credentials, crypto: LoginCrypto(),
                                               now: Date(timeIntervalSince1970: timestamp), timeZone: zone)
        let body = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        #expect(body["time_zone"] as? Int == offset)
        #expect(body["transaction"] as? String == transaction)
    }
}
