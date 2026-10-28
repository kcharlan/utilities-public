import Foundation
import Testing
import PrimeMonitorCore
@testable import PrimeMonitor

/// Real file access confined to one private temporary root; any path outside
/// it is recorded as an issue and refused, so the owner's runtime directory
/// is never observed.
@MainActor final class RecordingCatalogFiles: DeviceCatalogFiles {
    let root: URL
    var operations: [String] = []
    var failWrites = false
    private let system = SystemDeviceCatalogFiles()
    init(root: URL) { self.root = root }
    func count(_ kind: String) -> Int { operations.filter { $0.hasPrefix(kind + " ") }.count }
    private func admit(_ kind: String, _ url: URL) throws {
        let path = url.standardizedFileURL.path(percentEncoded: false)
        guard path.hasPrefix(root.standardizedFileURL.path(percentEncoded: false)) else {
            Issue.record("Catalog file access outside the private test root: \(kind)")
            throw CocoaError(.fileReadNoPermission)
        }
        operations.append(kind + " " + url.lastPathComponent)
    }
    func signature(of url: URL) throws -> DeviceCatalogFileSignature? { try admit("inspect", url); return try system.signature(of: url) }
    func read(_ url: URL) throws -> Data { try admit("read", url); return try system.read(url) }
    func write(_ data: Data, to url: URL, replacing: Bool) throws {
        try admit(replacing ? "replace" : "create", url)
        if failWrites { throw CocoaError(.fileWriteNoPermission) }
        try system.write(data, to: url, replacing: replacing)
    }
}

@MainActor final class CatalogRig {
    let root = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-catalog-" + UUID().uuidString, directoryHint: .isDirectory)
    let file: URL, seed: URL
    let scheduler = ManualScheduler()
    let files: RecordingCatalogFiles
    let store: DeviceCatalogStore
    static let seedText = #"{"schema": 1, "brands": {"7": "Synthetic Seed Brand"}, "vendors": {}, "devices": {}, "source": "synthetic seed"}"# + "\n"
    init(seeded: Bool = true) throws {
        // Spaces, a literal percent escape and non-ASCII text in every directory.
        file = root.appending(path: "Prime Monitör % café/%2F state/devices.json", directoryHint: .notDirectory)
        seed = root.appending(path: "Bündle Resources ✓/device_catalog.json", directoryHint: .notDirectory)
        try FileManager.default.createDirectory(at: seed.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(Self.seedText.utf8).write(to: seed)
        files = RecordingCatalogFiles(root: root)
        store = DeviceCatalogStore(fileURL: file, seedURL: seeded ? seed : nil, scheduler: scheduler, files: files)
    }
    deinit { try? FileManager.default.removeItem(at: root) }
    var path: String { file.path(percentEncoded: false) }
    var exists: Bool { FileManager.default.fileExists(atPath: path) }
    func contents() throws -> String { try String(contentsOf: file, encoding: .utf8) }
    func object() throws -> [String: Any] { try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any]) }
    func devices() throws -> [String: String] { try #require(try object()["devices"] as? [String: String]) }
    /// Creates the parent privately and replaces the file, as an editor's save would.
    func save(_ text: String) throws {
        try PrivateFile.replace(file, with: Data(text.utf8), temporaryPrefix: ".editor-")
    }
    /// Rewrites bytes in place, keeping device and inode.
    func overwriteInPlace(_ text: String) throws {
        let handle = try FileHandle(forWritingTo: file)
        defer { try? handle.close() }
        try handle.truncate(atOffset: 0); try handle.write(contentsOf: Data(text.utf8))
    }
    func modification() -> timespec {
        var info = stat(); _ = stat(path, &info); return info.st_mtimespec
    }
    func setModification(_ time: timespec) {
        var times = [timespec(tv_sec: 0, tv_nsec: Int(UTIME_OMIT)), time]
        #expect(utimensat(AT_FDCWD, path, &times, 0) == 0)
    }
    func mode(_ url: URL) throws -> Int? {
        try FileManager.default.attributesOfItem(atPath: url.path(percentEncoded: false))[.posixPermissions] as? Int
    }
}

private func catalogDocument(brands: String = "{}", vendors: String = "{}", devices: String = "{}") -> String {
    #"{"schema": 1, "brands": \#(brands), "vendors": \#(vendors), "devices": \#(devices)}"#
}
private let lamp = DeviceKey(vendorID: 0x0a1b, productID: 0x2c3d)

@Suite @MainActor struct DeviceCatalogStoreTests {
    @Test func seedsAbsentFileAndReseedsAfterDeletion() async throws {
        let rig = try CatalogRig()
        rig.store.load()
        #expect(try rig.contents() == CatalogRig.seedText)
        #expect(rig.store.catalog.brands == [7: "Synthetic Seed Brand"] && rig.store.problem == nil)
        #expect(try rig.mode(rig.file) == 0o600 && rig.mode(rig.file.deletingLastPathComponent()) == 0o700)
        try FileManager.default.removeItem(at: rig.file)
        rig.store.panelOpened()
        #expect(try rig.contents() == CatalogRig.seedText)
        try FileManager.default.removeItem(at: rig.file)
        #expect(rig.files.count("create") == 2)
        await rig.scheduler.advance(1)
        #expect(try rig.contents() == CatalogRig.seedText && rig.files.count("create") == 3)
        #expect(rig.store.catalog.brands == [7: "Synthetic Seed Brand"])
        rig.store.panelClosed()
    }

    @Test func existingContentIsNotReplacedBySeed() async throws {
        let rig = try CatalogRig()
        let valid = catalogDocument(vendors: #"{"0a1b": "Synthetic Vendor"}"#)
        try rig.save(valid)
        rig.store.load()
        #expect(rig.store.catalog.vendors == [0x0a1b: "Synthetic Vendor"] && rig.store.catalog.brands.isEmpty)
        #expect(try rig.contents() == valid)
        #expect(rig.files.count("create") == 0 && !rig.files.operations.contains("read device_catalog.json"))
        // Invalid existing content is left untouched too.
        try rig.save("{ synthetic invalid")
        rig.store.load()
        #expect(try rig.contents() == "{ synthetic invalid" && rig.files.count("create") == 0)
        #expect(rig.store.catalog.vendors == [0x0a1b: "Synthetic Vendor"])
    }

    @Test func missingSeedUsesEmptyCatalogUntilFirstNamingSave() throws {
        let rig = try CatalogRig(seeded: false)
        rig.store.load(); rig.store.panelOpened(); rig.store.panelClosed()
        #expect(!rig.exists && rig.store.catalog == DeviceCatalog() && rig.store.problem == nil)
        #expect(!FileManager.default.fileExists(atPath: rig.file.deletingLastPathComponent().path(percentEncoded: false)))
        try rig.store.setName("  Synthetic Desk Lamp \n", for: lamp)
        let object = try rig.object()
        #expect(object["schema"] as? Int == 1 && (object["brands"] as? [String: Any])?.isEmpty == true && (object["vendors"] as? [String: Any])?.isEmpty == true)
        #expect(try rig.devices() == ["0A1B:2C3D": "Synthetic Desk Lamp"])
        #expect(rig.store.catalog.devices == [lamp: "Synthetic Desk Lamp"] && rig.store.problem == nil)
        #expect(try rig.mode(rig.file) == 0o600 && rig.mode(rig.file.deletingLastPathComponent()) == 0o700)
    }

    @Test(arguments: [true, false])
    func deletionBetweenLoadAndSaveFollowsSeedingRule(_ seeded: Bool) throws {
        let rig = try CatalogRig(seeded: seeded)
        try rig.save(catalogDocument(vendors: #"{"0a1b": "Synthetic Earlier Vendor"}"#))
        rig.store.load()
        #expect(rig.store.catalog.vendors == [0x0a1b: "Synthetic Earlier Vendor"])
        try FileManager.default.removeItem(at: rig.file)
        try rig.store.setName("Synthetic Desk Lamp", for: lamp)
        let object = try rig.object()
        #expect(try rig.devices() == ["0A1B:2C3D": "Synthetic Desk Lamp"])
        #expect((object["vendors"] as? [String: Any])?.isEmpty == true)
        #expect((object["brands"] as? [String: String]) == (seeded ? ["7": "Synthetic Seed Brand"] : [:]))
        #expect(object["source"] as? String == (seeded ? "synthetic seed" : nil))
        #expect(rig.store.catalog.brands == (seeded ? [7: "Synthetic Seed Brand"] : [:]) && rig.store.catalog.vendors.isEmpty)
    }

    @Test func invalidEditsRetainLastGoodCatalogAndRecover() async throws {
        let rig = try CatalogRig()
        try rig.save(catalogDocument(vendors: #"{"0a1b": "Synthetic Vendor"}"#))
        rig.store.load()
        let good = rig.store.catalog
        let invalid = catalogDocument(vendors: #"{"0a1b": "Synthetic A", "0A1B": "Synthetic B"}"#)
        try rig.save(invalid)
        rig.store.panelOpened()
        let message = "Device names file devices.json wasn't loaded: vendors entry \"0a1b\" repeats entry \"0A1B\"."
        #expect(rig.store.problem == message && rig.store.catalog == good)
        // Naming writes are refused while the current file is invalid.
        #expect(throws: DeviceNamingError(message: message)) { try rig.store.setName("Synthetic Desk Lamp", for: lamp) }
        #expect(try rig.contents() == invalid && rig.files.count("replace") == 0)
        // A corrected file recovers on the next reload tick.
        try rig.save(catalogDocument(vendors: #"{"0a1b": "Synthetic Fixed Vendor"}"#))
        await rig.scheduler.advance(1)
        #expect(rig.store.problem == nil && rig.store.catalog.vendors == [0x0a1b: "Synthetic Fixed Vendor"])
        rig.store.panelClosed()
        // With the panel closed, a naming retry is the recovery path.
        try rig.save(catalogDocument(devices: #"{"0a1b:2c3d": ""}"#))
        rig.store.load()
        #expect(rig.store.problem == "Device names file devices.json wasn't loaded: devices entry \"0a1b:2c3d\": the name is empty.")
        #expect(throws: DeviceNamingError.self) { try rig.store.setName("Synthetic Desk Lamp", for: lamp) }
        try rig.save(catalogDocument())
        try rig.store.setName("Synthetic Desk Lamp", for: lamp)
        #expect(rig.store.problem == nil && rig.store.catalog.devices == [lamp: "Synthetic Desk Lamp"])
        #expect(try rig.devices() == ["0A1B:2C3D": "Synthetic Desk Lamp"])
    }

    @Test func reloadComparesSignaturesIncludingInvalidContent() async throws {
        let rig = try CatalogRig()
        try rig.save(catalogDocument(vendors: #"{"0a1b": "Synthetic Alpha"}"#))
        rig.store.panelOpened()
        #expect(rig.store.catalog.vendors == [0x0a1b: "Synthetic Alpha"] && rig.files.count("read") == 1)
        await rig.scheduler.advance(3)
        #expect(rig.files.count("inspect") == 4 && rig.files.count("read") == 1)
        // Same size, inode and restored mtime: outside the reload guarantee, not decoded.
        let original = rig.modification()
        try rig.overwriteInPlace(catalogDocument(vendors: #"{"0a1b": "Synthetic Omega"}"#))
        rig.setModification(original)
        await rig.scheduler.advance(2)
        #expect(rig.files.count("read") == 1 && rig.store.catalog.vendors == [0x0a1b: "Synthetic Alpha"])
        // Only the modification time differs: that metadata triggers the reload.
        rig.setModification(timespec(tv_sec: original.tv_sec, tv_nsec: (original.tv_nsec + 1) % 1_000_000_000))
        await rig.scheduler.advance(1)
        #expect(rig.files.count("read") == 2 && rig.store.catalog.vendors == [0x0a1b: "Synthetic Omega"])
        // Invalid content is decoded once; its attempted signature is recorded.
        try rig.save(catalogDocument(vendors: #"{"zz": "Synthetic"}"#))
        await rig.scheduler.advance(1)
        #expect(rig.files.count("read") == 3 && rig.store.problem?.contains("vendors entry \"zz\"") == true)
        await rig.scheduler.advance(5)
        #expect(rig.files.count("read") == 3 && rig.store.catalog.vendors == [0x0a1b: "Synthetic Omega"])
        rig.store.panelClosed()
    }

    @Test func lifecycleCallsRunOneLoopAndCloseCancelsIt() async throws {
        let rig = try CatalogRig()
        rig.store.load()
        let loaded = rig.files.count("inspect")
        rig.store.panelOpened(); rig.store.panelOpened(); rig.store.panelOpened()
        #expect(rig.scheduler.entries.filter { !$0.cancelled }.count == 1)
        #expect(rig.files.count("inspect") == loaded + 3)
        await rig.scheduler.advance(4)
        #expect(rig.files.count("inspect") == loaded + 7 && rig.scheduler.entries.filter { !$0.cancelled }.count == 1)
        rig.store.panelClosed(); rig.store.panelClosed()
        #expect(rig.scheduler.entries.allSatisfy { $0.cancelled })
        await rig.scheduler.advance(10)
        #expect(rig.files.count("inspect") == loaded + 7)
        rig.store.panelOpened()
        await rig.scheduler.advance(2)
        #expect(rig.files.count("inspect") == loaded + 10 && rig.scheduler.entries.filter { !$0.cancelled }.count == 1)
        rig.store.panelClosed()
    }

    @Test func namingPreservesSourceAndUnknownKeysAndRemovesNames() throws {
        let rig = try CatalogRig()
        try rig.save(#"""
        {"schema": 1, "source": {"note": "synthetic provenance", "list": [1, "two", null]}, "zz-extra": true,
         "brands": {"7": "Synthetic Brand"}, "vendors": {}, "devices": {"0a1b:0001": " Synthetic Other "}}
        """#)
        rig.store.load()
        try rig.store.setName("Synthetic Desk Lamp", for: lamp)
        let object = try rig.object()
        let source = try #require(object["source"] as? [String: Any])
        #expect(source["note"] as? String == "synthetic provenance")
        let list = try #require(source["list"] as? [Any])
        #expect(list.count == 3 && list[0] as? Int == 1 && list[1] as? String == "two" && list[2] is NSNull)
        #expect(object["zz-extra"] as? Bool == true && object["brands"] as? [String: String] == ["7": "Synthetic Brand"])
        // Untouched entries keep their exact spelling and text.
        #expect(try rig.devices() == ["0a1b:0001": " Synthetic Other ", "0A1B:2C3D": "Synthetic Desk Lamp"])
        // Sorted, pretty-printed JSON.
        let text = try rig.contents()
        #expect(text.hasPrefix("{\n  \"brands\" : {\n") && text.hasSuffix("}\n"))
        let order = ["\"brands\"", "\"devices\"", "\"schema\"", "\"source\"", "\"vendors\"", "\"zz-extra\""].compactMap { text.range(of: "\n  " + $0)?.lowerBound }
        #expect(order.count == 6 && order == order.sorted())
        try rig.store.setName(nil, for: lamp)
        #expect(try rig.devices() == ["0a1b:0001": " Synthetic Other "])
        #expect(rig.store.catalog.devices == [DeviceKey(vendorID: 0x0a1b, productID: 1): "Synthetic Other"])
        // Too-long names are rejected before any file access.
        let operations = rig.files.operations.count
        #expect(throws: DeviceNamingError(message: "Device names can have at most 64 characters.")) {
            try rig.store.setName(String(repeating: "n", count: 65), for: lamp)
        }
        #expect(rig.files.operations.count == operations)
        try rig.store.setName(String(repeating: "n", count: 64), for: lamp)
        #expect(rig.store.catalog.devices[lamp]?.count == 64)
    }

    @Test(arguments: ["0a1b:2c3d", "0A1B:2C3D", "0a1B:2C3d"])
    func namingUsesDecodedDeviceKeys(_ spelling: String) throws {
        let rig = try CatalogRig()
        try rig.save(catalogDocument(devices: #"{"\#(spelling)": "Synthetic Old Name", "0a1b:2c3e": "Synthetic Neighbour"}"#))
        rig.store.load()
        #expect(rig.store.catalog.devices[lamp] == "Synthetic Old Name")
        try rig.store.setName("Synthetic New Name", for: DeviceKey(vendorID: 0x0a1b, productID: 0x2c3d))
        #expect(try rig.devices() == ["0A1B:2C3D": "Synthetic New Name", "0a1b:2c3e": "Synthetic Neighbour"])
        rig.store.load()
        #expect(rig.store.problem == nil && rig.store.catalog.devices[lamp] == "Synthetic New Name")
        // Removal also matches the decoded key, whatever its spelling.
        try rig.save(catalogDocument(devices: #"{"\#(spelling)": "Synthetic Old Name", "0a1b:2c3e": "Synthetic Neighbour"}"#))
        try rig.store.setName("   ", for: lamp)
        #expect(try rig.devices() == ["0a1b:2c3e": "Synthetic Neighbour"])
        #expect(rig.store.catalog.devices == [DeviceKey(vendorID: 0x0a1b, productID: 0x2c3e): "Synthetic Neighbour"])
    }

    @Test func writesUsePrivateAtomicReplacementAndPreserveHeldReaders() throws {
        let rig = try CatalogRig()
        try rig.store.setName("Synthetic First", for: lamp)
        let first = try rig.contents()
        let reader = try FileHandle(forReadingFrom: rig.file)
        defer { try? reader.close() }
        var before = stat(); _ = stat(rig.path, &before)
        try rig.store.setName("Synthetic Second", for: lamp)
        var after = stat(); _ = stat(rig.path, &after)
        #expect(before.st_ino != after.st_ino)
        #expect(String(decoding: try #require(try reader.readToEnd()), as: UTF8.self) == first)
        #expect(try rig.devices()["0A1B:2C3D"] == "Synthetic Second")
        #expect(try rig.mode(rig.file) == 0o600 && rig.mode(rig.file.deletingLastPathComponent()) == 0o700)
        let names = try FileManager.default.contentsOfDirectory(atPath: rig.file.deletingLastPathComponent().path(percentEncoded: false))
        #expect(names == ["devices.json"])
        // Encoded path components were not created as separate literal paths.
        #expect(!FileManager.default.fileExists(atPath: rig.file.path(percentEncoded: true)))
        // A failed write keeps the file and the published catalog.
        rig.files.failWrites = true
        #expect(throws: DeviceNamingError(message: "Couldn't save device names file devices.json.")) { try rig.store.setName("Synthetic Third", for: lamp) }
        #expect(try rig.devices()["0A1B:2C3D"] == "Synthetic Second" && rig.store.catalog.devices[lamp] == "Synthetic Second")
    }

    @Test func defaultStoreIsMemoryOnly() throws {
        var operations = 0
        let token = UUID()
        DeviceCatalogStore.fileAccessObservers[token] = { _, _ in operations += 1 }
        defer { DeviceCatalogStore.fileAccessObservers[token] = nil }
        let store = DeviceCatalogStore()
        store.load(); store.panelOpened(); store.panelOpened(); store.panelClosed()
        try store.setName(" Synthetic Desk Lamp ", for: lamp)
        #expect(store.catalog.devices == [lamp: "Synthetic Desk Lamp"] && store.fileURL == nil)
        try store.setName(nil, for: lamp)
        #expect(store.catalog == DeviceCatalog() && store.problem == nil && operations == 0)
    }
}
