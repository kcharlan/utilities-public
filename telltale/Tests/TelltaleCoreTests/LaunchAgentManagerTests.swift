import Foundation
import Synchronization
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

/// A conspicuously synthetic user id; the fake runner never reaches launchd.
private let syntheticUID: uid_t = 4_242
private let launchctl = "/bin/launchctl"
private let domain = "gui/4242"
private let service = "gui/4242/local.utilities.telltale.collector"

/// A path as the plist records it: standardized and symlink-resolved.
private func resolvedPath(_ url: URL) -> String { url.standardizedFileURL.resolvingSymlinksInPath().path }

/// One test's world: injected paths under a scratch directory, a fake runner, and a synthetic
/// `Telltale.app` whose Info.plist carries Telltale's bundle identifier.
private struct AgentHarness {
    let directory: URL
    let paths: TelltalePaths
    let runner: FakeCommandRunner
    let manager: LaunchAgentManager
    let app: URL

    init(_ directory: URL) throws {
        self.directory = directory
        paths = TelltalePaths(home: directory.appending(path: "home", directoryHint: .isDirectory))
        runner = FakeCommandRunner()
        manager = LaunchAgentManager(paths: paths, uid: syntheticUID, runner: runner)
        app = try Self.makeApp(in: directory.appending(path: "Applications", directoryHint: .isDirectory))
    }

    /// Writes `<name>.app` with an executable `Contents/MacOS/<executable>` and an Info.plist whose
    /// `CFBundleExecutable` is `mainExecutable` (default: the executable's own name). Returns the
    /// executable's URL.
    static func makeApp(
        in parent: URL, name: String = "Telltale", executable: String = "Telltale", mainExecutable: String? = nil,
        identifier: String = TelltaleRelease.bundleIdentifier
    ) throws -> URL {
        let contents = parent.appending(path: "\(name).app/Contents", directoryHint: .isDirectory)
        let macOS = contents.appending(path: "MacOS", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: macOS, withIntermediateDirectories: true)
        let info: [String: Any] = [
            "CFBundleExecutable": mainExecutable ?? executable,
            "CFBundleIdentifier": identifier,
            "CFBundlePackageType": "APPL",
        ]
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
            .write(to: contents.appending(path: "Info.plist"))
        let binary = macOS.appending(path: executable, directoryHint: .notDirectory)
        try makeExecutable(binary)
        return binary
    }

    static func makeExecutable(_ url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("#!/bin/sh\nexit 0\n".utf8).write(to: url)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
    }

    var plistURL: URL { manager.plistURL }
    func installedPlist() throws -> [String: Any] { try TestPaths.plistDictionary(at: plistURL) }

    func call(_ arguments: String...) -> FakeCommandRunner.Call {
        FakeCommandRunner.Call(executable: launchctl, arguments: arguments)
    }

    /// Nothing under the injected home exists and no command ran.
    func expectUntouched(_ comment: Comment? = nil) {
        #expect(!FileManager.default.fileExists(atPath: paths.launchAgents.path), comment)
        #expect(!FileManager.default.fileExists(atPath: paths.logDirectory.path), comment)
        #expect(runner.calls.isEmpty, comment)
    }

    /// `turnOn`, `changeInterval` and `repair`, which all validate before writing.
    var installActions: [(name: String, act: (URL, Int) throws -> Void)] {
        [
            ("turnOn", { try manager.turnOn(executable: $0, intervalMinutes: $1) }),
            ("changeInterval", { try manager.changeInterval(executable: $0, intervalMinutes: $1) }),
            ("repair", { try manager.repair(executable: $0, intervalMinutes: $1) }),
        ]
    }
}

private func withAgent(_ body: (AgentHarness) throws -> Void) throws {
    try withScratchDirectory { try body(AgentHarness($0)) }
}

@Suite struct LaunchAgentManagerTests {
    @Test func plistHasSpecKeys() throws {
        try withAgent { h in
            #expect(h.plistURL == h.paths.launchAgents.appending(path: "local.utilities.telltale.collector.plist"))
            let plist = h.manager.plist(executable: h.app, intervalMinutes: 7)
            #expect(Set(plist.keys) == [
                "Label", "ProgramArguments", "StartInterval", "RunAtLoad", "ProcessType", "StandardOutPath", "StandardErrorPath",
            ])
            #expect(plist["Label"] as? String == "local.utilities.telltale.collector")
            #expect(plist["ProgramArguments"] as? [String] == [resolvedPath(h.app), "--collect"])
            #expect(plist["StartInterval"] as? Int == 420)
            #expect(plist["RunAtLoad"] as? Bool == true)
            #expect(plist["ProcessType"] as? String == "Background")
            #expect(plist["StandardOutPath"] as? String == h.paths.log.path)
            #expect(plist["StandardErrorPath"] as? String == h.paths.log.path)
        }
    }

    @Test func turnOnOrderIsWriteBootoutBootstrap() throws {
        try withAgent { h in
            let plistPath = h.plistURL.path
            let plistExisted = Mutex<[Bool]>([])
            h.runner.observe { _ in plistExisted.withLock { $0.append(FileManager.default.fileExists(atPath: plistPath)) } }

            try h.manager.turnOn(executable: h.app, intervalMinutes: 5)

            #expect(h.runner.calls == [h.call("bootout", service), h.call("bootstrap", domain, plistPath)])
            #expect(plistExisted.withLock { $0 } == [true, true])
            let written = try h.installedPlist()
            #expect(written["ProgramArguments"] as? [String] == [resolvedPath(h.app), "--collect"])
            #expect(written["StartInterval"] as? Int == 300)
            // launchd opens the log at spawn and doesn't create its directory.
            #expect(FileManager.default.fileExists(atPath: h.paths.logDirectory.path))
            #expect(h.manager.installedExecutable()?.path == resolvedPath(h.app))
        }
    }

    /// The plist records the validated file, not the symlink it was reached through, so a link that
    /// later moves can't point the job at another binary.
    @Test func plistRecordsTheResolvedExecutable() throws {
        try withAgent { h in
            let link = h.directory.appending(path: "LinkedApplications", directoryHint: .isDirectory)
            try FileManager.default.createSymbolicLink(at: link, withDestinationURL: h.app.deletingLastPathComponent())
            let throughLink = link.appending(path: "Telltale", directoryHint: .notDirectory)

            try h.manager.turnOn(executable: throughLink, intervalMinutes: 5)
            let recorded = try #require((try h.installedPlist()["ProgramArguments"] as? [String])?.first)
            #expect(recorded == resolvedPath(h.app))
            #expect(recorded != throughLink.path)
            #expect(h.manager.plist(executable: throughLink, intervalMinutes: 5)["ProgramArguments"] as? [String] == [recorded, "--collect"])
        }
    }

    @Test func installedAtIsThePlistModificationDate() throws {
        try withAgent { h in
            #expect(h.manager.installedAt() == nil)
            try h.manager.turnOn(executable: h.app, intervalMinutes: 5)
            let turnedOn = Date(timeIntervalSince1970: 1_767_225_600)
            try FileManager.default.setAttributes([.modificationDate: turnedOn], ofItemAtPath: h.plistURL.path)
            #expect(h.manager.installedAt() == turnedOn)
            try h.manager.turnOff()
            #expect(h.manager.installedAt() == nil)
        }
    }

    @Test(arguments: [
        CommandResult(status: 3, stdout: "", stderr: "Boot-out failed: 3: No such process\n"),
        CommandResult(status: 113, stdout: "", stderr: "Could not find service \"local.utilities.telltale.collector\" in domain for user gui: 4242\n"),
    ])
    func turnOnIgnoresNotLoadedBootout(_ notLoaded: CommandResult) throws {
        try withAgent { h in
            h.runner.respond(to: "bootout", with: notLoaded)
            try h.manager.turnOn(executable: h.app, intervalMinutes: 5)
            #expect(h.runner.calls == [h.call("bootout", service), h.call("bootstrap", domain, h.plistURL.path)])
        }
    }

    @Test func otherBootoutFailuresStopBeforeBootstrap() throws {
        try withAgent { h in
            h.runner.respond(to: "bootout", with: CommandResult(status: 5, stdout: "", stderr: "Boot-out failed: 5: Input/output error\n"))
            #expect(throws: LaunchAgentError.launchctl(command: "bootout", status: 5, stderr: "Boot-out failed: 5: Input/output error")) {
                try h.manager.turnOn(executable: h.app, intervalMinutes: 5)
            }
            #expect(h.runner.calls == [h.call("bootout", service)])
        }
    }

    @Test func bootstrapFailureSurfacesStderr() throws {
        try withAgent { h in
            h.runner.respond(to: "bootstrap", with: CommandResult(status: 5, stdout: "", stderr: "Bootstrap failed: 5: Input/output error\n"))
            let error = #expect(throws: LaunchAgentError.self) { try h.manager.turnOn(executable: h.app, intervalMinutes: 5) }
            #expect(error == .launchctl(command: "bootstrap", status: 5, stderr: "Bootstrap failed: 5: Input/output error"))
            #expect(error?.localizedDescription == "Collector command bootstrap failed (5): Bootstrap failed: 5: Input/output error")
        }
    }

    @Test func runnerErrorsPropagate() throws {
        try withAgent { h in
            h.runner.fail("bootstrap", with: CommandRunnerError.timedOut(executable: launchctl, seconds: 10))
            #expect(throws: CommandRunnerError.timedOut(executable: launchctl, seconds: 10)) {
                try h.manager.turnOn(executable: h.app, intervalMinutes: 5)
            }
        }
    }

    @Test func turnOffBootsOutAndRemovesPlist() throws {
        try withAgent { h in
            try h.manager.turnOn(executable: h.app, intervalMinutes: 5)
            let before = h.runner.calls.count
            try h.manager.turnOff()
            #expect(Array(h.runner.calls.dropFirst(before)) == [h.call("bootout", service)])
            #expect(!FileManager.default.fileExists(atPath: h.plistURL.path))
            #expect(h.manager.installedExecutable() == nil)

            // Already off: not loaded and no plist is still success.
            h.runner.respond(to: "bootout", with: CommandResult(status: 3, stdout: "", stderr: "Boot-out failed: 3: No such process\n"))
            try h.manager.turnOff()
        }
    }

    @Test func turnOffKeepsThePlistWhenBootoutFails() throws {
        try withAgent { h in
            try h.manager.turnOn(executable: h.app, intervalMinutes: 5)
            h.runner.respond(to: "bootout", with: CommandResult(status: 1, stdout: "", stderr: "Operation not permitted\n"))
            #expect(throws: LaunchAgentError.launchctl(command: "bootout", status: 1, stderr: "Operation not permitted")) {
                try h.manager.turnOff()
            }
            #expect(FileManager.default.fileExists(atPath: h.plistURL.path))
        }
    }

    @Test func changeIntervalRewritesAndReloads() throws {
        try withAgent { h in
            try h.manager.turnOn(executable: h.app, intervalMinutes: 5)
            let before = h.runner.calls.count
            try h.manager.changeInterval(executable: h.app, intervalMinutes: 15)
            #expect(try h.installedPlist()["StartInterval"] as? Int == 900)
            #expect(Array(h.runner.calls.dropFirst(before)) == [h.call("bootout", service), h.call("bootstrap", domain, h.plistURL.path)])
        }
    }

    @Test(arguments: [0, 61, -5])
    func invalidIntervalThrowsBeforeAnyWrite(_ minutes: Int) throws {
        try withAgent { h in
            for action in h.installActions {
                #expect(throws: LaunchAgentError.invalidInterval("Choose an interval from 1 to 60 minutes"), "\(action.name)") {
                    try action.act(h.app, minutes)
                }
                h.expectUntouched("\(action.name)")
            }

            // An installed agent is left exactly as it was.
            try h.manager.turnOn(executable: h.app, intervalMinutes: 5)
            let installed = try Data(contentsOf: h.plistURL)
            let calls = h.runner.calls
            for action in h.installActions {
                #expect(throws: LaunchAgentError.self, "\(action.name)") { try action.act(h.app, minutes) }
            }
            #expect(try Data(contentsOf: h.plistURL) == installed)
            #expect(h.runner.calls == calls)
        }
    }

    @Test func kickstartCommand() throws {
        try withAgent { h in
            try h.manager.kickstart()
            #expect(h.runner.calls == [h.call("kickstart", service)])

            h.runner.respond(to: "kickstart", with: CommandResult(status: 113, stdout: "", stderr: "Could not find service\n"))
            #expect(throws: LaunchAgentError.launchctl(command: "kickstart", status: 113, stderr: "Could not find service")) {
                try h.manager.kickstart()
            }
        }
    }

    @Test func isLoadedFromPrintStatus() throws {
        try withAgent { h in
            h.runner.respond(to: "print", with: CommandResult(status: 0, stdout: "synthetic service description\n", stderr: ""))
            #expect(h.manager.isLoaded())
            #expect(h.runner.calls == [h.call("print", service)])

            h.runner.respond(to: "print", with: CommandResult(status: 113, stdout: "", stderr: "Could not find service\n"))
            #expect(!h.manager.isLoaded())

            h.runner.fail("print", with: CommandRunnerError.timedOut(executable: launchctl, seconds: 10))
            #expect(!h.manager.isLoaded())
        }
    }

    @Test func needsRepairWhenPlistPointsElsewhere() throws {
        try withAgent { h in
            // Off: nothing to repair.
            #expect(h.manager.installedExecutable() == nil)
            #expect(!h.manager.plistMismatch(currentExecutable: h.app))

            try h.manager.turnOn(executable: h.app, intervalMinutes: 5)
            #expect(!h.manager.plistMismatch(currentExecutable: h.app))

            // The same file through a symlinked directory and an unstandardized path still matches.
            let link = h.directory.appending(path: "Linked", directoryHint: .isDirectory)
            try FileManager.default.createSymbolicLink(at: link, withDestinationURL: h.app.deletingLastPathComponent())
            #expect(!h.manager.plistMismatch(currentExecutable: link.appending(path: "Telltale")))
            let unstandardized = URL(fileURLWithPath: h.app.deletingLastPathComponent().path + "/../MacOS/Telltale")
            #expect(!h.manager.plistMismatch(currentExecutable: unstandardized))

            // The app moved: the plist points elsewhere until Repair rewrites it.
            let moved = try AgentHarness.makeApp(in: h.directory.appending(path: "Moved", directoryHint: .isDirectory))
            #expect(h.manager.plistMismatch(currentExecutable: moved))
            let before = h.runner.calls.count
            try h.manager.repair(executable: moved, intervalMinutes: 5)
            #expect(!h.manager.plistMismatch(currentExecutable: moved))
            #expect(h.manager.installedExecutable()?.path == resolvedPath(moved))
            #expect(Array(h.runner.calls.dropFirst(before)) == [h.call("bootout", service), h.call("bootstrap", domain, h.plistURL.path)])

            // An unreadable plist needs repair too.
            try Data("not a plist".utf8).write(to: h.plistURL)
            #expect(h.manager.installedExecutable() == nil)
            #expect(h.manager.plistMismatch(currentExecutable: moved))
        }
    }

    /// Review Focus "Non-installed collector launch": only an app bundle's main executable may be
    /// installed as the collector.
    @Test func turnOnRefusesExecutableOutsideAppBundle() throws {
        try withAgent { h in
            let loose = h.directory.appending(path: "build/debug/Telltale")
            try AgentHarness.makeExecutable(loose)
            let notMain = try AgentHarness.makeApp(
                in: h.directory.appending(path: "Other", directoryHint: .isDirectory), executable: "Helper", mainExecutable: "Telltale")
            let missing = h.app.deletingLastPathComponent().appending(path: "Missing")
            let linkedLoose = h.app.deletingLastPathComponent().appending(path: "Linked")
            try FileManager.default.createSymbolicLink(at: linkedLoose, withDestinationURL: loose)

            for executable in [loose, notMain, missing, linkedLoose] {
                for action in h.installActions {
                    let error = #expect(throws: LaunchAgentError.self, "\(action.name) \(executable.path)") { try action.act(executable, 5) }
                    #expect(error == .notInAppBundle)
                    #expect(error?.localizedDescription == "Run Telltale from Telltale.app to turn on the collector")
                    h.expectUntouched("\(action.name) \(executable.path)")
                }
            }
        }
    }

    /// Review Focus "Non-installed collector launch": the acceptance build (Task 11's bundle
    /// identifier) must never install itself as the collector.
    @Test func turnOnRefusesOtherBundleIdentifier() throws {
        try withAgent { h in
            let acceptance = try AgentHarness.makeApp(
                in: h.directory.appending(path: "Acceptance", directoryHint: .isDirectory), identifier: "com.example.telltale.acceptance")
            for action in h.installActions {
                let error = #expect(throws: LaunchAgentError.self, "\(action.name)") { try action.act(acceptance, 5) }
                #expect(error == .wrongBundle("com.example.telltale.acceptance"))
                #expect(error?.localizedDescription == "This copy of Telltale can't run the collector")
                h.expectUntouched("\(action.name)")
            }
        }
    }
}

@Suite struct ProcessRunnerTests {
    @Test func capturesStatusAndBothStreams() throws {
        let result = try ProcessRunner().run("/bin/sh", ["-c", "printf synthetic-out; printf synthetic-err >&2; exit 3"])
        #expect(result == CommandResult(status: 3, stdout: "synthetic-out", stderr: "synthetic-err"))
    }

    @Test func drainsLargeOutputWithoutStalling() throws {
        let result = try ProcessRunner().run("/bin/sh", ["-c", "head -c 300000 /dev/zero | tr '\\0' x"])
        #expect(result.status == 0)
        #expect(result.stdout.count == 300_000)
    }

    @Test func defaultTimeoutIsTenSeconds() {
        #expect(ProcessRunner().timeout == 10)
    }

    @Test func timesOutAndStopsTheProcess() throws {
        let start = Date()
        #expect(throws: CommandRunnerError.timedOut(executable: "/bin/sleep", seconds: 0.5)) {
            try ProcessRunner(timeout: 0.5).run("/bin/sleep", ["30"])
        }
        #expect(Date().timeIntervalSince(start) < 5)
    }

    @Test func missingExecutableThrows() {
        #expect(throws: CommandRunnerError.self) { try ProcessRunner().run("/nonexistent-synthetic/tool", []) }
    }
}
