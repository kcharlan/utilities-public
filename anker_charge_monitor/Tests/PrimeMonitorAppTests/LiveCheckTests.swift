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
        let (output, snapshot) = try await liveCheckOutput(fixture: "synthetic_0a00_frames.txt")
        #expect(output == Self.rowZeroReadings + ["Details: unavailable"])
        #expect(output[2].contains(DisplayFormatter.watts(centi: snapshot.readings[2].powerCenti)))
    }
    /// Owner-gate evidence: the live check prints decoded detail beside raw payloads.
    @Test func printsDetailEvidenceFromWireFrame() async throws {
        let (output, _) = try await liveCheckOutput(fixture: "synthetic_0a00_details_frames.txt")
        #expect(output == Self.rowZeroReadings + [
            "Fault bits: 0x00; over-temperature=false; C1 fault=false; C2 fault=false; C3 fault=false; C4 fault=false; USB-A fault=false",
            "Identity support: 6",
            "C1 identity: nothing attached",
            "C2 identity: identifying",
            "C3 identity: vendor=0xFEED; product=0xBEEF; class=10; model code=7",
            "C4 identity: vendor=0xC0DE; product=0x0042; class=99; model code=257",
            "Raw A3: 04 00 00",
            "Raw B7: 04 FF 06",
            "Raw BD: 04 FA FF FB FF 00 00 00 00 ED FE EF BE DE C0 42 00",
            "Raw BE: 04 FF FF FF FF FF FF FF FF 0A 00 07 00 63 00 01 01",
        ])
    }
    @Test func readoutShowsUnavailableDetailValues() {
        let details = ChargerDetails(faultBits: 0x29, identitySupport: nil, identities: [
            .c1: .identified(vendorID: 0xfeed, productID: 0x0001, brandClass: nil, modelCode: 0),
            .c2: .identified(vendorID: 0x00c0, productID: 0xbeef, brandClass: 0x1234, modelCode: nil),
            .c3: .nothingAttached,
        ], rawFields: [0xa3: [0x02, 0x29, 0x00], 0xbd: [], 0xbe: [0x01]])
        let lines = DiagnosticReadout.lines(ChargerSnapshot(receivedAt: .distantPast, readings: [], details: details))
        #expect(lines == [
            "C1: unavailable", "C2: unavailable", "C3: unavailable", "C4: unavailable", "A1: unavailable", "A2: unavailable",
            "Total: reported=0.00 W",
            "Fault bits: 0x29; over-temperature=true; C1 fault=false; C2 fault=false; C3 fault=true; C4 fault=false; USB-A fault=true",
            "Identity support: unavailable",
            "C1 identity: vendor=0xFEED; product=0x0001; class=unavailable; model code=0",
            "C2 identity: vendor=0x00C0; product=0xBEEF; class=4660; model code=unavailable",
            "C3 identity: nothing attached",
            "C4 identity: unavailable",
            "Raw A3: 02 29 00",
            "Raw B7: unavailable",
            "Raw BD: empty",
            "Raw BE: 01",
        ])
        let unknown = ChargerDetails(faultBits: nil, identitySupport: 2, identities: [:], rawFields: [0xb7: [0x04, 0xff, 0x02]])
        #expect(Array(DiagnosticReadout.lines(ChargerSnapshot(receivedAt: .distantPast, readings: [], details: unknown)).suffix(10)) == [
            "Fault bits: unavailable",
            "Identity support: 2",
            "C1 identity: unavailable", "C2 identity: unavailable", "C3 identity: unavailable", "C4 identity: unavailable",
            "Raw A3: unavailable", "Raw B7: 04 FF 02", "Raw BD: unavailable", "Raw BE: unavailable",
        ])
    }

    private static let rowZeroReadings = [
        "C1: active=false; reported=0.00 W; voltage=0.000 V; current=0.007 A",
        "C2: active=false; reported=0.00 W; voltage=0.000 V; current=0.007 A",
        "C3: active=true; reported=1.23 W; voltage=12.345 V; current=0.321 A",
        "C4: active=true; reported=4.56 W; voltage=23.456 V; current=0.654 A",
        "A1: active=false; reported=0.00 W; voltage=0.000 V; current=0.000 A",
        "A2: active=false; reported=0.00 W; voltage=0.000 V; current=0.000 A",
        "Total: reported=5.79 W"
    ]
    /// Runs the live check on row zero of a synthetic AnkerCloud fixture corpus.
    private func liveCheckOutput(fixture: String) async throws -> ([String], ChargerSnapshot) {
        let rig = try ControllerRig(); var output: [String] = []
        let task = Task { await LiveCheck.run(controller: rig.controller, acquireLease: { AppInstanceLease {} }, timeout: 2, output: { output.append($0) }) }
        await settle(); await rig.events.send(.network(true)); await settle()
        let root = URL(filePath: #filePath, directoryHint: .notDirectory).deletingLastPathComponent().deletingLastPathComponent()
        let text = try String(contentsOf: root.appending(path: "AnkerCloudTests/Fixtures/\(fixture)", directoryHint: .notDirectory), encoding: .utf8)
        let row = try #require(text.split(separator: "\n").first)
        var bytes: [UInt8] = []; var index = row.startIndex
        while index < row.endIndex { let next = row.index(index, offsetBy: 2); bytes.append(try #require(UInt8(row[index..<next], radix: 16))); index = next }
        let snapshot = try #require(PortDecoder.snapshot(from: HexFrame.parse(bytes), receivedAt: rig.clock.date))
        rig.backend.output.yield(.snapshot(snapshot))
        #expect(await task.value == 0)
        await rig.finish()
        return (output, snapshot)
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
