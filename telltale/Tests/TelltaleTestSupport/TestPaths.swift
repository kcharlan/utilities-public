import Foundation
import TelltaleCore

/// Locations and plist helpers shared by Telltale's test targets.
public enum TestPaths {
    /// The `telltale/` package directory, derived from this file's location
    /// (`Tests/TelltaleTestSupport/TestPaths.swift`).
    public static let packageRoot: URL = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()

    public static func synthetic(home: URL) -> TelltalePaths {
        TelltalePaths(home: home, codexHome: home.appending(path: "synthetic-codex"), claudeHome: home.appending(path: "synthetic-claude"))
    }

    public struct PlistError: Error, CustomStringConvertible {
        public let description: String
    }

    public static func plistDictionary(at url: URL) throws -> [String: Any] {
        let data = try Data(contentsOf: url)
        guard let dictionary = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else {
            throw PlistError(description: "\(url.lastPathComponent) is not a property-list dictionary")
        }
        return dictionary
    }
}
