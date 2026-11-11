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
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: dir) }
    let script = dir.appendingPathComponent("synthetic-brew")
    try Data("#!/bin/sh\nprintf 'synthetic stderr' >&2\nhead -c 400000 /dev/zero\nexit 7\n".utf8).write(to: script)
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
    let result = try await ProcessBrewRunner(executable: script).run([], environment: [:], timeout: 10)
    #expect(result.exitCode == 7 && result.stdout.count == 256 * 1024)
    #expect(String(decoding: result.stderr, as: UTF8.self) == "synthetic stderr")
}
@Test func processRunnerTimesOutEvenWhenDescendantKeepsPipeOpen() async throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
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
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: dir) }
    let script = dir.appendingPathComponent("synthetic-brew")
    try Data("#!/bin/sh\nprintf '%s:%s:%s' \"$HOMEBREW_NO_AUTO_UPDATE\" \"$HOMEBREW_NO_COLOR\" \"$HOMEBREW_NO_ENV_HINTS\"\nprintf 'synthetic error' >&2\nexit 4\n".utf8).write(to: script)
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
    let result = try await ProcessBrewRunner(executable: script).run([], environment: ["HOMEBREW_NO_AUTO_UPDATE": "1"], timeout: 5)
    #expect(result.exitCode == 4 && String(decoding: result.stdout, as: UTF8.self) == "1:1:1")
    #expect(String(decoding: result.stderr, as: UTF8.self) == "synthetic error")
}
@Test func processRunnerKillsProcessThatIgnoresTerminate() async throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: dir) }
    let script = dir.appendingPathComponent("synthetic-brew")
    try Data("#!/bin/sh\ntrap '' TERM\nwhile :; do :; done\n".utf8).write(to: script)
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
    let start = Date()
    do { _ = try await ProcessBrewRunner(executable: script).run([], environment: [:], timeout: 2); Issue.record("Expected timeout") }
    catch { #expect(error is BrewRunnerError) }
    #expect(Date().timeIntervalSince(start) >= 7 && Date().timeIntervalSince(start) < 12)
}
