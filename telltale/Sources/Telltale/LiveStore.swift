import Darwin
import Foundation
import Observation
import TelltaleCore

/// The panel's view of the database (spec section 4's read contract): a read-only connection, a
/// filesystem watch on the database, its `-wal` file and their directory, and a poll as the
/// fallback.
///
/// - It holds no Store until a read-only open succeeds. A missing or uninitialized database shows
///   `PanelSnapshot.waiting`; the app never creates or initializes it (the collector does).
/// - While the database files are absent it watches the nearest existing ancestor directory, so
///   the collector's first run is seen as soon as it creates them.
/// - When the file is replaced (a new inode) or removed it drops the connection and reopens.
/// - Any other open or read failure keeps the previous snapshot, marked stale by a
///   `Copy.databaseUnavailable` footer, and retries on the next change or poll **(plan call)**.
@MainActor @Observable final class LiveStore {
    private(set) var snapshot: PanelSnapshot
    /// The latest open or read failure; nil after a clean read.
    private(set) var lastError: String?
    private(set) var hasReadableDatabase = false
    /// The latest collector health report (the dashboard's collector view shows its four lamps).
    private(set) var health: CollectorHealthReport?
    /// Counts rereads, so views that read more than the snapshot (the dashboard) know to reload.
    private(set) var generation = 0

    @ObservationIgnored private let paths: TelltalePaths
    @ObservationIgnored private let sources: [SourceSummary]
    @ObservationIgnored let calendar: Calendar
    @ObservationIgnored let now: @MainActor () -> Date
    @ObservationIgnored private let assessHealth: @MainActor () async -> CollectorHealthReport?
    @ObservationIgnored private let pollInterval: Duration
    @ObservationIgnored private let watchFiles: Bool
    @ObservationIgnored private var store: Store?
    @ObservationIgnored private var opened: FileIdentity?
    @ObservationIgnored private var refreshing = false
    @ObservationIgnored private var pending = false
    @ObservationIgnored private var poll: Task<Void, Never>?
    @ObservationIgnored private var watchers: [any DispatchSourceFileSystemObject] = []
    @ObservationIgnored private var scheduled: Task<Void, Never>?

    /// How long a burst of filesystem events settles before the reread.
    static let settle: Duration = .milliseconds(250)

    init(
        paths: TelltalePaths, sources: [SourceSummary], calendar: Calendar = .current, now: @escaping @MainActor () -> Date = Date.init,
        health: @escaping @MainActor () async -> CollectorHealthReport? = { nil }, pollInterval: Duration = .seconds(30), watchFiles: Bool = true
    ) {
        self.paths = paths
        self.sources = sources
        self.calendar = calendar
        self.now = now
        assessHealth = health
        self.pollInterval = pollInterval
        self.watchFiles = watchFiles
        snapshot = .waiting(sources: sources)
        reload()
    }

    /// Starts the watch and the poll, and refreshes now.
    func start() {
        guard poll == nil else { return }
        poll = Task { [weak self, pollInterval] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(for: pollInterval)
            }
        }
        rearm()
    }

    func stop() {
        poll?.cancel()
        poll = nil
        scheduled?.cancel()
        scheduled = nil
        for watcher in watchers { watcher.cancel() }
        watchers = []
    }

    /// Re-evaluates collector health, then rereads the database. Overlapping calls coalesce into
    /// one more pass.
    func refresh() async {
        if refreshing {
            pending = true
            return
        }
        refreshing = true
        defer { refreshing = false }
        repeat {
            pending = false
            health = await assessHealth()
            reload()
        } while pending
    }

    /// Rereads the database with the latest health report.
    func reload() {
        do {
            let current = FileIdentity(path: paths.database.path)
            if store == nil || current != opened {
                store = nil
                opened = nil
                let store = try Store.open(paths.database, mode: .readOnly)
                self.store = store
                opened = current
            }
            guard let store else { return }
            snapshot = try PanelSnapshot.load(
                store: store, baseline: BaselineEngine(store: store, calendar: calendar), health: health, sources: sources, now: now(),
                calendar: calendar)
            hasReadableDatabase = true
            lastError = nil
        } catch StoreError.notInitialized {
            hasReadableDatabase = false
            store = nil
            opened = nil
            snapshot = .waiting(sources: sources, health: health)
            lastError = nil
        } catch {
            hasReadableDatabase = false
            store = nil
            opened = nil
            let message = Copy.databaseUnavailable(reason: error.localizedDescription)
            lastError = message
            snapshot.footer = message
        }
        generation += 1
        if watchFiles, poll != nil { rearm() }
    }

    /// Runs `body` on the open read-only connection, with a fresh baseline engine; nil before the
    /// collector has created the database, or after a read failure (the snapshot's footer says so).
    func read<T>(_ body: (Store, BaselineEngine) throws -> T) throws -> T? {
        guard let store else { return nil }
        return try body(store, BaselineEngine(store: store, calendar: calendar))
    }

    /// A model's display name from its source's naming.
    func providerName(_ provider: ProviderID) -> String { sources.first { $0.provider == provider }?.name ?? provider.rawValue }

    func displayName(provider: ProviderID, model: String) -> String {
        sources.first { $0.provider == provider }?.naming.displayName(model: model) ?? model
    }

    func disambiguatedName(provider: ProviderID, model: String) -> String {
        guard let naming = sources.first(where: { $0.provider == provider })?.naming else { return model }
        let ids = (try? read { store, _ in try ModelDetail.models(store: store, provider: provider) }) ?? []
        return DisplayNames.disambiguated(ids + [model], naming: naming)[model] ?? naming.displayName(model: model)
    }

    // MARK: Watching

    /// Watches the database and its `-wal` file when they exist, and their directory, or the nearest
    /// existing ancestor while it doesn't. Each event schedules a settled refresh and re-arms,
    /// since the collector may have created or replaced what is watched.
    private func rearm() {
        guard watchFiles else { return }
        for watcher in watchers { watcher.cancel() }
        watchers = []
        var directory = paths.database.deletingLastPathComponent()
        while !FileManager.default.fileExists(atPath: directory.path), directory.pathComponents.count > 1 {
            directory = directory.deletingLastPathComponent()
        }
        let targets = [directory.path, paths.database.path, paths.database.path + "-wal"]
        for path in targets {
            let fd = open(path, O_EVTONLY | O_CLOEXEC)
            guard fd >= 0 else { continue }
            let source = DispatchSource.makeFileSystemObjectSource(
                fileDescriptor: fd, eventMask: [.write, .extend, .delete, .rename, .link, .attrib, .revoke], queue: .main)
            source.setEventHandler { [weak self] in MainActor.assumeIsolated { self?.changed() } }
            source.setCancelHandler { close(fd) }
            source.resume()
            watchers.append(source)
        }
    }

    private func changed() {
        guard scheduled == nil else { return }
        scheduled = Task { [weak self] in
            try? await Task.sleep(for: Self.settle)
            guard !Task.isCancelled, let self else { return }
            scheduled = nil
            await refresh()
        }
    }
}

/// A file's device and inode, so a replaced database is reopened rather than read through a
/// connection to the unlinked original.
private struct FileIdentity: Equatable {
    let device: dev_t
    let inode: ino_t

    init?(path: String) {
        var info = stat()
        guard stat(path, &info) == 0 else { return nil }
        device = info.st_dev
        inode = info.st_ino
    }
}
