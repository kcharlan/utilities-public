import Foundation
import Observation
import PrimeMonitorCore

/// The file identity compared before decoding: device, inode, size and
/// modification time in nanoseconds.
struct DeviceCatalogFileSignature: Equatable, Sendable {
    let device: Int64
    let inode: UInt64
    let size: Int64
    let modificationNanoseconds: Int64
}
enum DeviceCatalogFileOperation: Equatable, Sendable {
    case inspect(URL), read(URL), create(URL), replace(URL)
}
/// File access behind the store, so tests can observe or fail each operation.
@MainActor protocol DeviceCatalogFiles {
    /// nil when nothing exists at `url`.
    func signature(of url: URL) throws -> DeviceCatalogFileSignature?
    func read(_ url: URL) throws -> Data
    /// Private atomic replacement; with `replacing` false an existing file
    /// is left untouched and the write fails with EEXIST.
    func write(_ data: Data, to url: URL, replacing: Bool) throws
}
struct SystemDeviceCatalogFiles: DeviceCatalogFiles {
    func signature(of url: URL) throws -> DeviceCatalogFileSignature? {
        var info = stat()
        guard stat(url.path(percentEncoded: false), &info) == 0 else {
            if errno == ENOENT { return nil }
            throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
        }
        return .init(device: Int64(info.st_dev), inode: UInt64(info.st_ino), size: Int64(info.st_size),
                     modificationNanoseconds: Int64(info.st_mtimespec.tv_sec) * 1_000_000_000 + Int64(info.st_mtimespec.tv_nsec))
    }
    func read(_ url: URL) throws -> Data { try Data(contentsOf: url) }
    func write(_ data: Data, to url: URL, replacing: Bool) throws {
        try PrivateFile.replace(url, with: data, temporaryPrefix: ".devices-", exclusive: !replacing)
    }
}

struct DeviceNamingError: LocalizedError, Equatable {
    let message: String
    var errorDescription: String? { message }
}

/// The device-name catalog. `init()` is memory only. The persistent form
/// seeds an absent file from the bundled catalog, reloads while the panel
/// is open and writes names with private atomic replacement.
@MainActor @Observable final class DeviceCatalogStore {
    private(set) var catalog = DeviceCatalog()
    private(set) var problem: String?

    private struct Persistence {
        let fileURL: URL
        let seedURL: URL?
        let scheduler: any PollScheduler
        let files: any DeviceCatalogFiles
    }
    private enum Observed: Equatable { case unknown, absent, present(DeviceCatalogFileSignature) }
    @ObservationIgnored private let persistence: Persistence?
    @ObservationIgnored private var observed = Observed.unknown
    @ObservationIgnored private var tick: (any Cancellable)?
    @ObservationIgnored private var loopGeneration = 0

    /// Test instrumentation: each registered observer receives every file
    /// operation of every store, with that store's identity.
    static var fileAccessObservers: [UUID: (ObjectIdentifier, DeviceCatalogFileOperation) -> Void] = [:]

    static let reloadInterval: TimeInterval = 1
    static let emptyDocument = Data(#"{"brands":{},"devices":{},"schema":1,"vendors":{}}"#.utf8)

    init() { persistence = nil }
    init(fileURL: URL, seedURL: URL?, scheduler: any PollScheduler, files: any DeviceCatalogFiles = SystemDeviceCatalogFiles()) {
        persistence = .init(fileURL: fileURL, seedURL: seedURL, scheduler: scheduler, files: files)
    }

    var fileURL: URL? { persistence?.fileURL }

    func load() {
        guard let persistence else { return }
        observed = .unknown
        refresh(persistence)
    }
    func panelOpened() {
        guard let persistence else { return }
        refresh(persistence)
        if tick == nil { scheduleReload(persistence) }
    }
    func panelClosed() {
        loopGeneration += 1
        tick?.cancel(); tick = nil
    }

    /// Reads and validates the current file immediately before changing
    /// `devices[key]`; a blank or nil name removes the entry.
    func setName(_ name: String?, for key: DeviceKey) throws {
        let trimmed = DeviceCatalog.normalizedName(name)
        if let trimmed, trimmed.count > DeviceCatalog.maximumNameLength {
            throw DeviceNamingError(message: "Device names can have at most \(DeviceCatalog.maximumNameLength) characters.")
        }
        guard let persistence else {
            var updated = catalog; updated.devices[key] = trimmed; publish(updated, problem: problem)
            return
        }
        let file = persistence.fileURL.lastPathComponent
        let signature: DeviceCatalogFileSignature?
        do { signature = try current(persistence) }
        catch { throw DeviceNamingError(message: setUnavailable(persistence)) }
        let data: Data
        if signature != nil {
            do { data = try access(.read(persistence.fileURL), persistence) { try $0.read(persistence.fileURL) } }
            catch { throw DeviceNamingError(message: setUnreadable(persistence)) }
        } else { data = Self.emptyDocument }
        var object: [String: Any]
        do { object = try DeviceCatalog.decodeDocument(data).object }
        catch {
            observed = signature.map(Observed.present) ?? .unknown
            throw DeviceNamingError(message: setInvalid(error, persistence))
        }
        // Validation guarantees the section; match entries by decoded key.
        var devices = (object["devices"] as? [String: Any] ?? [:]).filter { DeviceKey(catalogKey: $0.key) != key }
        if let trimmed { devices[key.catalogKey] = trimmed }
        object["devices"] = devices
        let encoded: Data, updated: DeviceCatalog
        do {
            encoded = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]) + Data("\n".utf8)
            updated = try DeviceCatalog.decode(encoded)
            try access(.replace(persistence.fileURL), persistence) { try $0.write(encoded, to: persistence.fileURL, replacing: true) }
        } catch { throw DeviceNamingError(message: "Couldn't save device names file \(file).") }
        let written = try? access(.inspect(persistence.fileURL), persistence) { try $0.signature(of: persistence.fileURL) }
        observed = written.map(Observed.present) ?? .unknown
        publish(updated, problem: nil)
    }

    private func scheduleReload(_ persistence: Persistence) {
        loopGeneration += 1
        let generation = loopGeneration
        tick = persistence.scheduler.schedule(after: Self.reloadInterval) { [weak self] in
            guard let self, self.loopGeneration == generation else { return }
            self.refresh(persistence)
            self.scheduleReload(persistence)
        }
    }

    /// Decodes only when the file signature differs from the last attempt,
    /// including an attempt that found invalid content.
    private func refresh(_ persistence: Persistence) {
        let signature: DeviceCatalogFileSignature?
        do { signature = try current(persistence) }
        catch { _ = setUnavailable(persistence); return }
        guard let signature else {
            if observed != .absent { observed = .absent; publish(DeviceCatalog(), problem: nil) }
            return
        }
        guard observed != .present(signature) else { return }
        let data: Data
        do { data = try access(.read(persistence.fileURL), persistence) { try $0.read(persistence.fileURL) } }
        catch { _ = setUnreadable(persistence); return }
        observed = .present(signature)
        do throws(DeviceCatalogError) { publish(try DeviceCatalog.decode(data), problem: nil) }
        catch { _ = setInvalid(error, persistence) }
    }

    /// The seeding rule: an absent file receives the seed's bytes when a seed
    /// exists; existing content is never replaced. nil means neither exists.
    private func current(_ persistence: Persistence) throws -> DeviceCatalogFileSignature? {
        let url = persistence.fileURL
        if let signature = try access(.inspect(url), persistence, { try $0.signature(of: url) }) { return signature }
        guard let seedURL = persistence.seedURL else { return nil }
        let seed = try access(.read(seedURL), persistence) { try $0.read(seedURL) }
        do { try access(.create(url), persistence) { try $0.write(seed, to: url, replacing: false) } }
        catch let error as POSIXError where error.code == .EEXIST {}
        return try access(.inspect(url), persistence) { try $0.signature(of: url) }
    }

    private func access<T>(_ operation: DeviceCatalogFileOperation, _ persistence: Persistence,
                           _ body: (any DeviceCatalogFiles) throws -> T) throws -> T {
        for observer in Self.fileAccessObservers.values { observer(ObjectIdentifier(self), operation) }
        return try body(persistence.files)
    }

    private func publish(_ updated: DeviceCatalog, problem updatedProblem: String?) {
        if catalog != updated { catalog = updated }
        if problem != updatedProblem { problem = updatedProblem }
    }
    private func report(_ message: String) -> String {
        if problem != message { problem = message }
        return message
    }
    private func setInvalid(_ error: DeviceCatalogError, _ persistence: Persistence) -> String {
        report("Device names file \(persistence.fileURL.lastPathComponent) wasn't loaded: \(error.description)")
    }
    private func setUnreadable(_ persistence: Persistence) -> String {
        // Not recorded as attempted: a permission fix keeps the signature.
        observed = .unknown
        return report("Couldn't read device names file \(persistence.fileURL.lastPathComponent).")
    }
    private func setUnavailable(_ persistence: Persistence) -> String {
        observed = .unknown
        return report("Couldn't open or create device names file \(persistence.fileURL.lastPathComponent).")
    }
}
