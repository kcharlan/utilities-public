import Foundation
import Testing
import PrimeMonitorCore
import AnkerCloud
@testable import PrimeMonitor

@Suite @MainActor struct LiveCheckTests {
    @Test func exitCodes() async throws {
        let empty = try ControllerRig(configured: false)
        var released = false
        #expect(await LiveCheck.run(controller: empty.controller, acquireLease: { AppInstanceLease { released = true } }, timeout: 0.01, output: { _ in }) == 2)
        #expect(released); await empty.finish()
        let rig = try ControllerRig()
        #expect(await LiveCheck.run(controller: rig.controller, acquireLease: { throw CocoaError(.fileReadUnknown) }, timeout: 0, output: { _ in }) == 5)
        #expect(await LiveCheck.run(controller: rig.controller, acquireLease: { AppInstanceLease {} }, timeout: 0, output: { _ in }) == 3)
        await rig.finish()
    }
    @Test func rejectedConcurrentRunDoesNotStart() async throws {
        let rig = try ControllerRig()
        #expect(await LiveCheck.run(controller: rig.controller, acquireLease: { throw AppInstanceGateError.alreadyRunning }, timeout: 0, output: { _ in }) == 4)
        #expect(await rig.backend.log.isEmpty); #expect(rig.events.handler == nil)
        await rig.finish()
    }
    @Test func selectedChargerRequired() async throws {
        let rig = try ControllerRig(configured: false); rig.secrets.value = .init(credentials: appCredentials, session: appSession)
        #expect(await LiveCheck.run(controller: rig.controller, acquireLease: { AppInstanceLease {} }, timeout: 0, output: { _ in }) == 2)
        await rig.finish()
    }
    @Test(arguments: ["success", "timeout", "startup", "backend"])
    func cleanupPrecedesReturnOnEveryOwnedExit(_ path: String) async throws {
        let rig = try ControllerRig(); await rig.start()
        if path == "success" { await rig.reply() }
        if path == "backend" { rig.backend.output.yield(.status(.error("synthetic failure"))); await settle() }
        let controller: MonitorController
        if path == "startup" {
            // A real startup persistence failure replaces the removed temporary
            // identity preparation failure; shutdown must still hold the lease.
            await rig.controller.stop()
            let stateURL = rig.directory.appending(path: "state.json", directoryHint: .notDirectory)
            try Data("corrupt synthetic state".utf8).write(to: stateURL)
            controller = MonitorController(backend: rig.backend, secrets: rig.secrets, state: StateStore(fileURL: stateURL), events: SystemEvents(sources: []), now: Date.init, scheduler: TimerPollScheduler())
        } else { controller = rig.controller }
        await rig.backend.blockDisconnection()
        var released = false, returned = false
        let task = Task {
            let result = await LiveCheck.run(controller: controller, acquireLease: { AppInstanceLease { released = true } }, timeout: 0, output: { _ in })
            returned = true; return result
        }
        await settle(); #expect(!released); #expect(!returned)
        await rig.backend.releaseDisconnection()
        #expect(await task.value == (path == "success" ? 0 : path == "timeout" ? 3 : 5)); #expect(released)
        await rig.finish()
    }
    @Test func printsEveryPortThenExitsZero() async throws {
        let rig = try ControllerRig(); var output: [String] = []
        let task = Task { await LiveCheck.run(controller: rig.controller, acquireLease: { AppInstanceLease {} }, timeout: 2, output: { output.append($0) }) }
        await settle(); await rig.events.send(.network(true)); await settle()
        let root = URL(filePath: #filePath, directoryHint: .notDirectory).deletingLastPathComponent().deletingLastPathComponent()
        let text = try String(contentsOf: root.appending(path: "AnkerCloudTests/Fixtures/synthetic_0a00_frames.txt", directoryHint: .notDirectory), encoding: .utf8)
        let row = try #require(text.split(separator: "\n").first)
        var bytes: [UInt8] = []; var index = row.startIndex
        while index < row.endIndex { let next = row.index(index, offsetBy: 2); bytes.append(try #require(UInt8(row[index..<next], radix: 16))); index = next }
        let snapshot = try #require(PortDecoder.snapshot(from: HexFrame.parse(bytes), receivedAt: rig.clock.date))
        rig.backend.output.yield(.snapshot(snapshot))
        #expect(await task.value == 0)
        #expect(output == [
            "C1: active=false; reported=0.00 W; voltage=0.000 V; current=0.007 A",
            "C2: active=false; reported=0.00 W; voltage=0.000 V; current=0.007 A",
            "C3: active=true; reported=1.23 W; voltage=12.345 V; current=0.321 A",
            "C4: active=true; reported=4.56 W; voltage=23.456 V; current=0.654 A",
            "A1: active=false; reported=0.00 W; voltage=0.000 V; current=0.000 A",
            "A2: active=false; reported=0.00 W; voltage=0.000 V; current=0.000 A",
            "Total: reported=5.79 W"
        ])
        #expect(output[2].contains(DisplayFormatter.watts(centi: snapshot.readings[2].powerCenti)))
        await rig.finish()
    }
}

@MainActor private struct UnreadableSecrets: SecretStore {
    func replaceProvider(_ provider: (any CredentialProvider)?, selection: CredentialSelection?) { preconditionFailure("Immutable failure fixture") }
    func load() throws -> StoredSecrets? { throw CocoaError(.fileReadUnknown) }
    func save(_ value: StoredSecrets) throws {}
    func delete() throws {}
}
@Suite @MainActor struct LiveCheckPersistenceTests {
    @Test func unreadableCredentialsReturnFive() async throws {
        let rig = try ControllerRig()
        let controller = MonitorController(backend: rig.backend, secrets: UnreadableSecrets(), state: StateStore(fileURL: rig.directory.appending(path: "state.json", directoryHint: .notDirectory)), events: SystemEvents(sources: []), now: Date.init, scheduler: TimerPollScheduler())
        #expect(await LiveCheck.run(controller: controller, acquireLease: { AppInstanceLease {} }, timeout: 1, output: { _ in }) == 5)
        await rig.finish()
    }
    @Test func stateLoadFailureIsNotMissingAccount() async throws {
        let rig = try ControllerRig(configured: false)
        try FileManager.default.createDirectory(at: rig.directory, withIntermediateDirectories: true)
        let state = StateStore(fileURL: rig.directory.appending(path: "state.json", directoryHint: .notDirectory))
        try Data("corrupt synthetic state".utf8).write(to: state.fileURL)
        let controller = MonitorController(backend: rig.backend, secrets: rig.secrets, state: state, events: SystemEvents(sources: []), now: Date.init, scheduler: TimerPollScheduler())
        #expect(await LiveCheck.run(controller: controller, acquireLease: { AppInstanceLease {} }, timeout: 0, output: { _ in }) == 5)
        await rig.finish()
    }
}
