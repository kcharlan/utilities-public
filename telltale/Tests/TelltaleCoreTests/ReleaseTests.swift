import Foundation
import Testing
import TelltaleCore
import TelltaleTestSupport

@Suite struct ReleaseTests {
    /// Spec section 3 identifiers, kept literal here so the plist, the code and
    /// the spec are three separately maintained statements of one contract.
    @Test func infoPlistMatchesRelease() throws {
        let plist = try TestPaths.plistDictionary(at: TestPaths.packageRoot.appending(path: "Resources/Info.plist"))
        #expect(TelltaleRelease.version == "0.1.1")
        #expect(TelltaleRelease.displayName == "Telltale")
        #expect(TelltaleRelease.bundleIdentifier == "local.utilities.telltale")
        #expect(TelltaleRelease.collectorLabel == "local.utilities.telltale.collector")
        #expect(plist["CFBundleIdentifier"] as? String == TelltaleRelease.bundleIdentifier)
        #expect(plist["CFBundleShortVersionString"] as? String == TelltaleRelease.version)
        #expect(plist["CFBundleName"] as? String == TelltaleRelease.displayName)
        #expect(plist["CFBundleDisplayName"] as? String == TelltaleRelease.displayName)
        #expect(plist["CFBundleExecutable"] as? String == "Telltale")
        #expect(plist["CFBundlePackageType"] as? String == "APPL")
        #expect(plist["LSUIElement"] as? Bool == true)
        #expect(plist["CFBundleVersion"] as? String != nil)

        let anker = try TestPaths.plistDictionary(at: TestPaths.packageRoot.appending(path: "../anker_charge_monitor/Resources/Info.plist"))
        #expect(plist["LSMinimumSystemVersion"] as? String == anker["LSMinimumSystemVersion"] as? String)
        #expect(plist["LSMinimumSystemVersion"] as? String == "27.0")
    }

    @Test func pathsDeriveFromInjectedHome() {
        let home = URL(fileURLWithPath: "/tmp/telltale-synthetic-home", isDirectory: true)
        let paths = TelltalePaths(home: home)
        #expect(paths.appSupport.path == "/tmp/telltale-synthetic-home/Library/Application Support/Telltale")
        #expect(paths.database.path == "/tmp/telltale-synthetic-home/Library/Application Support/Telltale/telltale.sqlite")
        #expect(paths.lock.path == "/tmp/telltale-synthetic-home/Library/Application Support/Telltale/collector.lock")
        #expect(paths.appLock.path == "/tmp/telltale-synthetic-home/Library/Application Support/Telltale/app.lock")
        #expect(paths.logDirectory.path == "/tmp/telltale-synthetic-home/Library/Logs/Telltale")
        #expect(paths.log.path == "/tmp/telltale-synthetic-home/Library/Logs/Telltale/collector.log")
        #expect(paths.launchAgents.path == "/tmp/telltale-synthetic-home/Library/LaunchAgents")
        #expect(paths.codexHome.path == "/tmp/telltale-synthetic-home/.codex")
    }

    @Test func explicitCodexHomeOverridesDerivedOne() {
        let home = URL(fileURLWithPath: "/tmp/telltale-synthetic-home", isDirectory: true)
        let codex = URL(fileURLWithPath: "/tmp/telltale-synthetic-codex", isDirectory: true)
        let paths = TelltalePaths(home: home, codexHome: codex)
        #expect(paths.codexHome.path == "/tmp/telltale-synthetic-codex")
        #expect(paths.database.path.hasPrefix("/tmp/telltale-synthetic-home/"))
    }

    @Test func codexHomeHonorsEnvironment() {
        let overridden = TelltalePaths.live(environment: ["CODEX_HOME": "/tmp/telltale-synthetic-codex"])
        #expect(overridden.codexHome.path == "/tmp/telltale-synthetic-codex")
        // An empty value is treated as unset, so the derived default applies.
        let empty = TelltalePaths.live(environment: ["CODEX_HOME": ""])
        let unset = TelltalePaths.live(environment: [:])
        #expect(empty == unset)
        #expect(unset.codexHome.lastPathComponent == ".codex")
        #expect(unset.codexHome.deletingLastPathComponent().path == unset.launchAgents.deletingLastPathComponent().deletingLastPathComponent().path)
    }
}
