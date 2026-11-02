import Foundation
import Testing
import PrimeMonitorCore
@testable import PrimeMonitor
@Suite struct StateStoreTests {
    @Test func readFailurePreservesStatePathAndBlocksSaving() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-" + UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        let path = root.appending(path: "state.json", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true)
        let load = StateStore(fileURL: path).load()
        #expect(!load.canSave && load.problem != nil)
        #expect(FileManager.default.fileExists(atPath: path.path(percentEncoded: false)))
        #expect(!FileManager.default.fileExists(atPath: path.appendingPathExtension("bad").path(percentEncoded: false)))
    }
    @Test func decodedPathsPreserveAtomicReplacementAndQuarantine() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-" + UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        let directory = root.appending(path: "spaces % café/%2F", directoryHint: .isDirectory)
        let store = StateStore(fileURL: directory.appending(path: "state.json", directoryHint: .notDirectory))
        let first = AppState(charger: appCharger, closedInterval: .m5)
        try store.save(first)
        let reader = try FileHandle(forReadingFrom: store.fileURL)
        defer { try? reader.close() }
        try store.save(.initial)
        #expect(store.load().state == .initial)
        let heldBytes = try #require(try reader.readToEnd())
        #expect(try JSONDecoder().decode(AppState.self, from: heldBytes) == first)
        try Data("first corrupt state".utf8).write(to: store.fileURL)
        #expect(store.load().canSave)
        try Data("second corrupt state".utf8).write(to: store.fileURL)
        #expect(store.load().canSave)
        let files = try FileManager.default.contentsOfDirectory(atPath: directory.path(percentEncoded: false))
        #expect(files.contains("state.json.bad"))
        #expect(files.filter { $0.hasPrefix("state.json.bad-") }.count == 1)
        #expect(!files.contains { $0.hasPrefix(".state-") })
        #expect(!FileManager.default.fileExists(atPath: directory.path(percentEncoded: true)))
        #expect(!FileManager.default.fileExists(atPath: store.fileURL.path(percentEncoded: false)))
        try store.save(first)
        #expect(store.load().state == first)
        #expect(try FileManager.default.contentsOfDirectory(atPath: root.path(percentEncoded: false)) == ["spaces % café"])
    }
    @Test func roundTripAndDefaults() throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-" + UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = StateStore(fileURL: directory.appending(path: "state.json", directoryHint: .notDirectory))
        #expect(store.load().state == AppState(charger: nil, closedInterval: .m1))
        let value = AppState(charger: appCharger, closedInterval: .m5)
        try store.save(value); #expect(store.load().state == value)
        var sized = value; sized.menuBarTextSize = .pt11
        try store.save(sized); #expect(store.load().state == sized)
        #expect(try FileManager.default.attributesOfItem(atPath: directory.path(percentEncoded: false))[.posixPermissions] as? Int == 0o700)
        #expect(try FileManager.default.attributesOfItem(atPath: store.fileURL.path(percentEncoded: false))[.posixPermissions] as? Int == 0o600)
        try Data("invalid".utf8).write(to: store.fileURL)
        let bad = store.load(); #expect(bad.problem != nil); #expect(bad.canSave); #expect(bad.state.charger == nil)
        #expect(FileManager.default.fileExists(atPath: store.fileURL.appendingPathExtension("bad").path(percentEncoded: false)))
        try store.save(value); #expect(store.load().state == value)
    }
    @Test(arguments: [
        (#"{"charger":{"serial":"synthetic-charger","model":"A2345","alias":"Desk","name":"Prime"},"closedInterval":300,"credentials":{"provider":"onePassword","settings":{"item":"Synthetic Item","country":"ZZ"}}}"#, nil as MenuBarTextSize?),
        (#"{"charger":{"serial":"synthetic-charger","model":"A2345","alias":"Desk","name":"Prime"},"closedInterval":300,"credentials":{"provider":"onePassword","settings":{"item":"Synthetic Item","country":"ZZ"}},"menuBarTextSize":11}"#, .pt11)
    ]) func pinnedStateShapesLoadWithoutQuarantine(json: String, size: MenuBarTextSize?) throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-" + UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let store = StateStore(fileURL: directory.appending(path: "state.json", directoryHint: .notDirectory))
        try Data(json.utf8).write(to: store.fileURL)
        let loaded = store.load()
        #expect(loaded.problem == nil && loaded.canSave)
        #expect(loaded.state.charger == ChargerInfo(serial: "synthetic-charger", model: "A2345", alias: "Desk", name: "Prime"))
        #expect(loaded.state.credentials == CredentialSelection(provider: "onePassword", settings: ["item": "Synthetic Item", "country": "ZZ"]))
        #expect(loaded.state.closedInterval == .m5 && loaded.state.menuBarTextSize == size)
        #expect(!FileManager.default.fileExists(atPath: store.fileURL.appendingPathExtension("bad").path(percentEncoded: false)))
    }
    @Test func unknownEnumValuesFallBackWithoutLosingSelection() throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-" + UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let store = StateStore(fileURL: directory.appending(path: "state.json", directoryHint: .notDirectory))
        let json = #"{"charger":{"serial":"synthetic-charger","model":"A2345","alias":"Desk","name":"Prime"},"closedInterval":45,"credentials":{"provider":"onePassword","settings":{"item":"Synthetic Item","country":"ZZ"}},"menuBarTextSize":99}"#
        try Data(json.utf8).write(to: store.fileURL)
        let loaded = store.load()
        #expect(loaded.problem == nil && loaded.canSave)
        #expect(loaded.state.charger == ChargerInfo(serial: "synthetic-charger", model: "A2345", alias: "Desk", name: "Prime"))
        #expect(loaded.state.credentials == CredentialSelection(provider: "onePassword", settings: ["item": "Synthetic Item", "country": "ZZ"]))
        #expect(loaded.state.closedInterval == .default && loaded.state.menuBarTextSize == nil)
        #expect(!FileManager.default.fileExists(atPath: store.fileURL.appendingPathExtension("bad").path(percentEncoded: false)))
    }
    @Test(arguments: [#"{"charger":{"serial":123},"closedInterval":60}"#, #"{"charger":null}"#])
    func invalidChargerOrMissingIntervalStillQuarantines(json: String) throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-" + UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let store = StateStore(fileURL: directory.appending(path: "state.json", directoryHint: .notDirectory))
        try Data(json.utf8).write(to: store.fileURL)
        let loaded = store.load()
        #expect(loaded.problem != nil && loaded.canSave)
        #expect(FileManager.default.fileExists(atPath: store.fileURL.appendingPathExtension("bad").path(percentEncoded: false)))
    }
}
