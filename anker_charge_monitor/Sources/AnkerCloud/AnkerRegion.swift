import Foundation

/// Ports anker-solix-api `apitypes.py`, API_COUNTRIES / API_SERVERS, and
/// `session.py`, AnkerSolixClientSession.__init__, commit 8a5222b.
public enum AnkerRegion {
    private static let comCountries: Set<String> = [
        "DZ", "LB", "SY", "EG", "LY", "TN", "MA", "JO", "PS", "AR", "AU", "BR",
        "HK", "IN", "MX", "NG", "NZ", "RU", "ZA", "KR", "TW", "US", "CA"
    ]

    public static func baseURL(country: String) -> URL {
        // Every remaining known country is EU, as is an unknown country.
        URL(string: comCountries.contains(country.uppercased())
            ? "https://ankerpower-api.anker.com" : "https://ankerpower-api-eu.anker.com")!
    }
}
