import Foundation
import Testing
@testable import BrewVersionCore

private actor ScriptedRunner: BrewRunning {
    var responses: [BrewOutput]
    var calls: [([String], [String: String], TimeInterval)] = []
    init(_ responses: [BrewOutput]) { self.responses = responses }
    func run(_ arguments: [String], environment: [String: String], timeout: TimeInterval) async throws -> BrewOutput {
        calls.append((arguments, environment, timeout)); return responses.removeFirst()
    }
}
private func output(_ code: Int32 = 0, _ text: String = "", _ error: String = "") -> BrewOutput {
    BrewOutput(exitCode: code, stdout: Data(text.utf8), stderr: Data(error.utf8), seconds: 0)
}
@Test func gateUsesExactCommandsAndRetainsTapIdentityAfterUpdateFailure() async {
    let name = PackageName("synthetic-owner/synthetic-tap/synthetic-tool")!
    let listing = Listing(name: name, kind: .formula, version: "2")
    let runner = ScriptedRunner([output(1, "", "synthetic update problem\nmore"), output(0, "{\"formulae\":[{\"name\":\"synthetic-tool\",\"versions\":{\"stable\":\"2\"}}]}")])
    let result = await BrewGate(runner: runner, log: NoEventLog(), apiCacheDirectory: nil).confirm([listing])
    #expect(result.problem == "synthetic update problem")
    #expect(result.listings[name]?.name == name && result.listings[name]?.version == "2")
    let calls = await runner.calls
    #expect(calls[0].0 == ["update"] && calls[0].2 == 180)
    #expect(calls[1].0 == ["info", "--json=v2", "--formula", name.rawValue] && calls[1].2 == 30)
    #expect(calls[1].1["HOMEBREW_NO_AUTO_UPDATE"] == "1")
}
@Test func failedAndMalformedInfoDoesNotPreventAnotherCandidate() async {
    let a = Listing(name: PackageName("synthetic-a")!, kind: .formula, version: "2")
    let b = Listing(name: PackageName("synthetic-b")!, kind: .cask, version: "2")
    let runner = ScriptedRunner([output(), output(1, "", "synthetic error"), output(0, "{\"casks\":[{\"token\":\"synthetic-b\",\"version\":\"2\"}]}")])
    let result = await BrewGate(runner: runner, log: NoEventLog(), apiCacheDirectory: nil).confirm([a,b])
    #expect(result.listings[a.name] == nil && result.listings[b.name]?.version == "2")
    let invalid = ScriptedRunner([output(), output(0, "not json")])
    #expect(await BrewGate(runner: invalid, log: NoEventLog(), apiCacheDirectory: nil).confirm([a]).listings.isEmpty)
}
@Test func processRunnerDrainsPipesAndBoundsOutput() async throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-gate-\(UUID())")
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: dir) }
    let script = dir.appendingPathComponent("synthetic-brew")
    try Data("#!/bin/sh\nprintf 'synthetic stderr' >&2\nhead -c 400000 /dev/zero\nexit 7\n".utf8).write(to: script)
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
    let result = try await ProcessBrewRunner(executable: script).run([], environment: [:], timeout: 10)
    #expect(result.exitCode == 7 && result.stdout.count == 256 * 1024)
    #expect(String(decoding: result.stderr, as: UTF8.self) == "synthetic stderr")
}
@Test func processRunnerTimesOutEvenWhenDescendantKeepsPipeOpen() async throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-gate-\(UUID())")
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: dir) }
    let script = dir.appendingPathComponent("synthetic-brew")
    try Data("#!/bin/sh\nsleep 2 &\nwait\n".utf8).write(to: script)
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
    let start = Date()
    do { _ = try await ProcessBrewRunner(executable: script).run([], environment: [:], timeout: 0.1); Issue.record("Expected timeout") }
    catch { #expect(error is BrewRunnerError) }
    #expect(Date().timeIntervalSince(start) < 1.5)
}

final class GateEventRecorder: EventLogging, @unchecked Sendable {
    private let lock = NSLock()
    private var events: [String] = []
    func record(_ event: String, _ fields: [String: LogValue]) { lock.withLock { events.append(event) } }
    var recorded: [String] { lock.withLock { events } }
}
@Test func gateEmitsUpdateAndInfoEvents() async {
    let log = GateEventRecorder(), listing = Listing(name: PackageName("synthetic-a")!, kind: .formula, version: "2")
    let runner = ScriptedRunner([output(), output(0, "{\"formulae\":[{\"versions\":{\"stable\":\"2\"}}]}")])
    _ = await BrewGate(runner: runner, log: log, apiCacheDirectory: nil).confirm([listing])
    #expect(log.recorded == ["gate.update", "gate.info"])
}

@Test func olderBrewListingExplainsWhyReleaseRemainsPending() async {
    let listing = Listing(name: PackageName("synthetic-a")!, kind: .formula, version: "2")
    let runner = ScriptedRunner([output(), output(0, "{\"formulae\":[{\"versions\":{\"stable\":\"1\"}}]}")])
    let result = await BrewGate(runner: runner, log: NoEventLog(), apiCacheDirectory: nil).confirm([listing])
    #expect(result.listings[listing.name]?.version == "1" && result.problem != nil)
}

@Test func failedUpdateStillReturnsOlderInfoAndItsTruncatedFirstErrorLine() async {
    let listing = Listing(name: PackageName("synthetic-a")!, kind: .formula, version: "2")
    let runner = ScriptedRunner([output(1, "", String(repeating: "x", count: 220) + "\nignored"), output(0, "{\"formulae\":[{\"versions\":{\"stable\":\"1\"}}]}")])
    let result = await BrewGate(runner: runner, log: NoEventLog(), apiCacheDirectory: nil).confirm([listing])
    #expect(result.listings[listing.name]?.version == "1")
    #expect(result.problem == String(repeating: "x", count: 200))
}
@Test func processRunnerPassesOverridesAndCapturesShortOutput() async throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-gate-\(UUID())")
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: dir) }
    let script = dir.appendingPathComponent("synthetic-brew")
    try Data("#!/bin/sh\nprintf '%s:%s:%s' \"$HOMEBREW_NO_AUTO_UPDATE\" \"$HOMEBREW_NO_COLOR\" \"$HOMEBREW_NO_ENV_HINTS\"\nprintf 'synthetic error' >&2\nexit 4\n".utf8).write(to: script)
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
    let result = try await ProcessBrewRunner(executable: script).run([], environment: ["HOMEBREW_NO_AUTO_UPDATE": "1"], timeout: 5)
    #expect(result.exitCode == 4 && String(decoding: result.stdout, as: UTF8.self) == "1:1:1")
    #expect(String(decoding: result.stderr, as: UTF8.self) == "synthetic error")
}
@Test func processRunnerKillsProcessThatIgnoresTerminate() async throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-gate-\(UUID())")
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: dir) }
    let script = dir.appendingPathComponent("synthetic-brew")
    try Data("#!/bin/sh\ntrap '' TERM\nwhile :; do :; done\n".utf8).write(to: script)
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
    let start = Date()
    do { _ = try await ProcessBrewRunner(executable: script).run([], environment: [:], timeout: 2); Issue.record("Expected timeout") }
    catch { #expect(error is BrewRunnerError) }
    #expect(Date().timeIntervalSince(start) >= 7 && Date().timeIntervalSince(start) < 12)
}

@Test func liveGateAvailabilityTracksSyntheticExecutableRemoval() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-gate-\(UUID())")
    defer { try? FileManager.default.removeItem(at: root) }
    let bin = root.appendingPathComponent("bin")
    try FileManager.default.createDirectory(at: bin, withIntermediateDirectories: true)
    let executable = bin.appendingPathComponent("brew")
    try Data("#!/bin/sh\nexit 0\n".utf8).write(to: executable)
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
    let gate = try #require(BrewGate.live(prefixes: [HomebrewPrefix(root: root)], home: root, log: NoEventLog()))
    #expect(gate.isAvailable)
    try FileManager.default.removeItem(at: executable)
    #expect(!gate.isAvailable)
    #expect(BrewGate.live(prefixes: [HomebrewPrefix(root: root)], home: root, log: NoEventLog()) == nil)
}

@Test func gateRecordsDiagnosticFieldsForOlderListing() async {
    let log = FieldRecorder(), listing = Listing(name: PackageName("synthetic-a")!, kind: .formula, version: "2")
    let runner = ScriptedRunner([BrewOutput(exitCode: 1, stdout: Data("first\nlast\n".utf8), stderr: Data("locked\nmore".utf8), seconds: 1.25), BrewOutput(exitCode: 0, stdout: Data("{\"formulae\":[{\"versions\":{\"stable\":\"1\"}}]}".utf8), stderr: Data(), seconds: 0.125)])
    _ = await BrewGate(runner: runner, log: log, apiCacheDirectory: nil).confirm([listing])
    let update = log.fields("gate.update"), info = log.fields("gate.info")
    #expect(update["exit"] == .int(1) && update["ms"] == .int(1250) && update["timedOut"] == .bool(false))
    #expect(update["summary"] == .string("last") && update["error"] == .string("locked"))
    #expect(info["announced"] == .string("2") && info["brew"] == .string("1") && info["covered"] == .bool(false))
    #expect(info["exit"] == .int(0) && info["ms"] == .int(125))
}

final class FieldRecorder: EventLogging, @unchecked Sendable {
    private let lock = NSLock()
    private var entries: [(String, [String: LogValue])] = []
    func record(_ event: String, _ fields: [String: LogValue]) { lock.withLock { entries.append((event, fields)) } }
    func fields(_ event: String) -> [String: LogValue] { lock.withLock { entries.last(where: { $0.0 == event })?.1 ?? [:] } }
}

@Test func gateRecordsSyntheticCacheMetadataWithoutBody() async throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-cache-\(UUID())")
    defer { try? FileManager.default.removeItem(at: dir) }
    let internalDir = dir.appendingPathComponent("internal")
    try FileManager.default.createDirectory(at: internalDir, withIntermediateDirectories: true)
    let file = internalDir.appendingPathComponent("packages.synthetic.jws.json")
    try Data("synthetic private body".utf8).write(to: file)
    try Data("synthetic-etag\n".utf8).write(to: URL(fileURLWithPath: file.path + ".etag"))
    let log = FieldRecorder()
    _ = await BrewGate(runner: ScriptedRunner([output()]), log: log, apiCacheDirectory: dir).confirm([])
    let fields = log.fields("gate.cache")
    #expect(fields["file"] == .string("packages.synthetic.jws.json"))
    #expect(fields["etag"] == .string("synthetic-etag") && fields["bytes"] == .int(22))
    #expect(fields["modified"] != nil && !fields.values.contains(.string("synthetic private body")))
}

@Test func gateLogsMalformedAndNonzeroInfoEvidence() async {
    let listing = Listing(name: PackageName("synthetic-a")!, kind: .formula, version: "2")
    for response in [output(1, "", "synthetic failure"), output(0, "bad json")] {
        let log = FieldRecorder()
        _ = await BrewGate(runner: ScriptedRunner([output(), response]), log: log, apiCacheDirectory: nil).confirm([listing])
        let info = log.fields("gate.info")
        #expect(info["announced"] == .string("2") && info["covered"] == .bool(false))
        #expect(info["exit"] == .int(Int(response.exitCode)) && info["ms"] == .int(0) && info["error"] != nil)
    }
}

@Test func gateRecordsLaunchErrorAndRealTimeoutDiagnostics() async throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-gate-\(UUID())")
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: dir) }
    let log = FieldRecorder(), missing = ProcessBrewRunner(executable: dir.appendingPathComponent("missing"))
    _ = await BrewGate(runner: missing, log: log, apiCacheDirectory: nil).confirm([])
    #expect(log.fields("gate.update")["timedOut"] == .bool(false) && log.fields("gate.update")["ms"] != nil && log.fields("gate.update")["error"] != nil)
    let script = dir.appendingPathComponent("synthetic-brew")
    try Data("#!/bin/sh\nprintf 'started\\n'\nprintf 'synthetic lock\\n' >&2\nsleep 2 &\nwait\n".utf8).write(to: script)
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
    let timed = TimeoutRunner(base: ProcessBrewRunner(executable: script))
    let timeoutLog = FieldRecorder()
    _ = await BrewGate(runner: timed, log: timeoutLog, apiCacheDirectory: nil).confirm([])
    let fields = timeoutLog.fields("gate.update")
    #expect(fields["timedOut"] == .bool(true) && fields["summary"] == .string("started") && fields["error"] == .string("synthetic lock"))
    if case .int(let ms) = fields["ms"] { #expect(ms >= 100 && ms < 1500) } else { Issue.record("Missing timeout duration") }
}
private struct TimeoutRunner: BrewRunning {
    let base: ProcessBrewRunner
    func run(_ arguments: [String], environment: [String: String], timeout: TimeInterval) async throws -> BrewOutput {
        try await base.run(arguments, environment: environment, timeout: 0.1)
    }
}
@Test func gateRecordsCoveredVersion() async {
    let listing = Listing(name: PackageName("synthetic-a")!, kind: .formula, version: "2"), log = FieldRecorder()
    _ = await BrewGate(runner: ScriptedRunner([output(), output(0, "{\"formulae\":[{\"versions\":{\"stable\":\"3\"}}]}")]), log: log, apiCacheDirectory: nil).confirm([listing])
    #expect(log.fields("gate.info")["brew"] == .string("3") && log.fields("gate.info")["covered"] == .bool(true))
}
