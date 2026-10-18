import Foundation
import Testing
@testable import BrewVersionCore

struct ReleaseTests {
    @Test func infoPlistMatchesRelease() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("Resources/Info.plist"))
        let plist = try #require(PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any])
        #expect(plist["CFBundleShortVersionString"] as? String == BrewVersionRelease.version)
        #expect(plist["CFBundleIdentifier"] as? String == "local.utilities.brew-version")
        #expect(plist["CFBundleExecutable"] as? String == "BrewVersion")
        #expect(plist["LSUIElement"] as? Bool == true)
        #expect(plist["LSMinimumSystemVersion"] as? String == "27.0")
    }
}
