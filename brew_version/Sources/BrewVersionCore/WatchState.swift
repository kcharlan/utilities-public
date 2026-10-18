import Darwin
import Foundation

public struct ReleaseID: Codable, Equatable, Sendable {
    public let kind: PackageKind
    public let version: String
    public let revision: Int
    public init(_ listing: Listing) {
        kind = listing.kind
        version = listing.version
        revision = listing.kind == .formula ? listing.revision : 0
    }
    public var displayVersion: String {
        kind == .formula ? installedForm(version: version, revision: revision) : version
    }
    private enum CodingKeys: String, CodingKey { case kind, version, revision }
    public init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = try c.decode(PackageKind.self, forKey: .kind)
        version = try c.decode(String.self, forKey: .version)
        let revision = try c.decode(Int.self, forKey: .revision)
        guard !version.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              kind == .cask || revision >= 0 else {
            throw DecodingError.dataCorruptedError(forKey: .version, in: c, debugDescription: "Invalid release identity")
        }
        self.revision = kind == .formula ? revision : 0
    }
}

public struct WatchEntry: Codable, Equatable, Sendable {
    public var name: PackageName
    public var kind: PackageKind?
    public var lastListing: Listing?
    public var installed: InstalledVersion?
    public var lastSeenRelease: ReleaseID?
    public var notifiedRelease: ReleaseID?
    public var skippedRelease: ReleaseID?
    public var unseenRelease: Bool
    public var lastError: String?

    public init(name: PackageName, kind: PackageKind? = nil, lastListing: Listing? = nil,
                installed: InstalledVersion? = nil, lastSeenRelease: ReleaseID? = nil,
                notifiedRelease: ReleaseID? = nil, skippedRelease: ReleaseID? = nil,
                unseenRelease: Bool = false, lastError: String? = nil) {
        self.name = name; self.kind = kind; self.lastListing = lastListing
        self.installed = installed; self.lastSeenRelease = lastSeenRelease
        self.notifiedRelease = notifiedRelease; self.skippedRelease = skippedRelease
        self.unseenRelease = unseenRelease; self.lastError = lastError
    }
    public var isAmber: Bool {
        guard let listing = lastListing, skippedRelease != ReleaseID(listing),
              !(listing.kind == .cask && listing.version == "latest") else { return false }
        switch updateStatus(listing: listing, installed: installed) {
        case .updateAvailable: return true
        case .notInstalled: return unseenRelease
        default: return false
        }
    }
}

public struct Notice: Equatable, Sendable {
    public var name: PackageName
    public var title: String
    public var body: String
    public init(name: PackageName, title: String, body: String) {
        self.name = name; self.title = title; self.body = body
    }
}

public func evaluate(_ entry: WatchEntry, listing: Listing, installed: InstalledVersion?) -> (WatchEntry, Notice?) {
    var next = entry
    next.lastListing = listing; next.installed = installed; next.kind = listing.kind; next.lastError = nil
    let release = ReleaseID(listing)
    let unversioned = listing.kind == .cask && listing.version == "latest"
    if installed != nil || unversioned { next.unseenRelease = false }
    guard let previous = entry.lastSeenRelease else {
        next.lastSeenRelease = release; next.notifiedRelease = release; next.unseenRelease = false
        return (next, nil)
    }
    if entry.skippedRelease == release {
        next.unseenRelease = false
        return (next, nil)
    }
    guard !unversioned else { return (next, nil) }
    let body: String
    switch updateStatus(listing: listing, installed: installed) {
    case .updateAvailable(let installed):
        next.lastSeenRelease = release
        body = "You have \(installed)."
    case .notInstalled:
        guard previous != release else { next.unseenRelease = false; return (next, nil) }
        guard entry.notifiedRelease != release else { return (next, nil) }
        next.unseenRelease = true
        body = "Was \(previous.displayVersion)."
    default:
        next.lastSeenRelease = release
        return (next, nil)
    }
    guard entry.notifiedRelease != release else { return (next, nil) }
    next.notifiedRelease = release
    return (next, Notice(name: entry.name, title: "\(entry.name) \(release.displayVersion) is on Homebrew", body: body))
}

public struct AppState: Codable, Equatable, Sendable {
    public var schema: Int
    public var watched: [WatchEntry]
    public var interval: CheckInterval
    public var showOtherUpdates: Bool
    public var otherUpdatesCollapsed: Bool
    public var lastCheck: Date?
    public var lastCatalogFetch: Date?
    public var listingCache: [URL: CachedListing]
    /// How often Other updates refreshes Homebrew's full catalog.
    public var catalogInterval: CheckInterval = .catalogStandard
    /// Like `brew outdated --greedy`: also list self-updating casks whose
    /// installed version can't be read from their app.
    public var includeSelfUpdating = false
    public static let currentSchema = 1
    public static let initial = AppState(schema: currentSchema, watched: [], interval: .standard,
                                        showOtherUpdates: true, otherUpdatesCollapsed: false,
                                        lastCheck: nil, lastCatalogFetch: nil, listingCache: [:])
}

extension AppState {
    private enum CodingKeys: String, CodingKey {
        case schema, watched, interval, showOtherUpdates, otherUpdatesCollapsed, lastCheck, lastCatalogFetch,
             listingCache, catalogInterval, includeSelfUpdating
    }
    // Settings added after 1.0.1 default when absent, so earlier saved state
    // loads normally instead of being set aside as unreadable.
    public init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(schema: try c.decode(Int.self, forKey: .schema),
                  watched: try c.decode([WatchEntry].self, forKey: .watched),
                  interval: try c.decode(CheckInterval.self, forKey: .interval),
                  showOtherUpdates: try c.decode(Bool.self, forKey: .showOtherUpdates),
                  otherUpdatesCollapsed: try c.decode(Bool.self, forKey: .otherUpdatesCollapsed),
                  lastCheck: try c.decodeIfPresent(Date.self, forKey: .lastCheck),
                  lastCatalogFetch: try c.decodeIfPresent(Date.self, forKey: .lastCatalogFetch),
                  listingCache: try c.decode([URL: CachedListing].self, forKey: .listingCache))
        catalogInterval = try c.decodeIfPresent(CheckInterval.self, forKey: .catalogInterval) ?? .catalogStandard
        includeSelfUpdating = try c.decodeIfPresent(Bool.self, forKey: .includeSelfUpdating) ?? false
    }
}

public struct StoreLoad: Sendable {
    public let state: AppState
    public let problem: String?
    public let canSave: Bool
}

// A narrow filesystem boundary permits deterministic failures without replacing persistence logic.
struct WatchStoreIO: Sendable {
    var read: @Sendable (URL) throws -> Data
    var move: @Sendable (URL, URL) throws -> Void
    var write: @Sendable (Data, URL) throws -> Void
    var replace: @Sendable (URL, URL) throws -> Void
    static let live = WatchStoreIO(read: { try Data(contentsOf: $0) },
        move: { try FileManager.default.moveItem(at: $0, to: $1) },
        write: { try $0.write(to: $1) }, replace: { source, destination in
            guard rename(source.path, destination.path) == 0 else {
                throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
            }
        })
}

public struct WatchStore: Sendable {
    public let fileURL: URL
    private let io: WatchStoreIO
    public init(fileURL: URL) { self.init(fileURL: fileURL, io: .live) }
    init(fileURL: URL, io: WatchStoreIO) { self.fileURL = fileURL; self.io = io }

    public func load() -> StoreLoad {
        guard FileManager.default.fileExists(atPath: fileURL.path) else {
            return StoreLoad(state: .initial, problem: nil, canSave: true)
        }
        do {
            let state = try JSONDecoder().decode(AppState.self, from: io.read(fileURL))
            guard state.schema == AppState.currentSchema,
                  Set(state.watched.map(\.name)).count == state.watched.count,
                  state.watched.allSatisfy({ entry in
                      entry.lastListing.map { validListing($0) && $0.name == entry.name } ?? true
                  }), state.listingCache.values.allSatisfy({ validListing($0.listing) }) else {
                throw CocoaError(.coderReadCorrupt)
            }
            return StoreLoad(state: state, problem: nil, canSave: true)
        } catch {
            var quarantine = fileURL.appendingPathExtension("bad")
            while FileManager.default.fileExists(atPath: quarantine.path) {
                quarantine = URL(fileURLWithPath: fileURL.path + ".bad-" + UUID().uuidString)
            }
            do {
                try io.move(fileURL, quarantine)
                return StoreLoad(state: .initial, problem: "Unreadable saved state was set aside as \(quarantine.lastPathComponent).", canSave: true)
            } catch {
                return StoreLoad(state: .initial, problem: "Couldn't set aside unreadable saved state: \(error.localizedDescription)", canSave: false)
            }
        }
    }
    public func save(_ state: AppState) throws {
        let directory = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path)
        let temporary = directory.appendingPathComponent(".state-\(UUID().uuidString).tmp")
        defer { try? FileManager.default.removeItem(at: temporary) }
        // Create privately before writing; even a partial temporary output stays private.
        guard FileManager.default.createFile(atPath: temporary.path, contents: nil, attributes: [.posixPermissions: 0o600]) else {
            throw CocoaError(.fileWriteUnknown)
        }
        try io.write(JSONEncoder().encode(state), temporary)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path)
        try io.replace(temporary, fileURL)
    }
    private func validListing(_ listing: Listing) -> Bool {
        !listing.version.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && (listing.kind == .cask || listing.revision >= 0)
    }
}
