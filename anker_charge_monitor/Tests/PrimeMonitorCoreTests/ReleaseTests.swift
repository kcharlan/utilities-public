import Foundation
import Testing
import PrimeMonitorCore

struct ReleaseTests {
    @Test func plistVersionMatchesRelease() throws {
        let root = URL(filePath: #filePath, directoryHint: .notDirectory).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let info = try #require(PropertyListSerialization.propertyList(from: Data(contentsOf: root.appending(path: "Resources/Info.plist", directoryHint: .notDirectory)), format: nil) as? [String: Any])
        #expect(info["CFBundleShortVersionString"] as? String == PrimeMonitorRelease.version)
        #expect(info["CFBundleIdentifier"] as? String == "local.utilities.prime-monitor")
        #expect(info["CFBundleExecutable"] as? String == "PrimeMonitor")
        #expect(info["CFBundleVersion"] as? String == "7")
        #expect(info["LSUIElement"] as? Bool == true)
        #expect(info["LSMinimumSystemVersion"] as? String == "27.0")
    }
}
