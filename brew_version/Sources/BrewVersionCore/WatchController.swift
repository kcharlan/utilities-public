import Foundation
import Observation

public protocol Notifier: Sendable {
    func post(_ notice: Notice) async
    func requestAuthorization() async
}
public extension Notifier { func requestAuthorization() async {} }

public enum PersistenceIssue: Sendable { case recoveryWarning, loadFailure, saveFailure }

public enum AutomaticCheckSchedule: Equatable, Sendable {
    case blocked, checking, ready
    case scheduled(Date)
    case waitingForNetwork(notBefore: Date?)
}

@MainActor @Observable public final class WatchController {
    public private(set) var state: AppState
    public private(set) var persistenceError: String?
    public private(set) var persistenceIssue: PersistenceIssue?
    public private(set) var networkAvailable: Bool
    public private(set) var canSave: Bool
    public private(set) var isChecking = false
    public private(set) var results: [LookupResult] = []
    private var searchGeneration = UUID()
    private let scheduler = LookupScheduler()
    public private(set) var catalog: Catalog?
    public private(set) var others: [OtherUpdate] = []
    public private(set) var isRefreshingCatalog = false
    public private(set) var catalogWriteError: String?
    public var amberCount: Int { state.watched.filter(\.isAmber).count }
    public var nextAutomaticCheck: AutomaticCheckSchedule {
        guard canSave else { return .blocked }
        guard !isChecking else { return .checking }
        if !networkAvailable {
            let deadline = watchCheckDeadline(reconnecting: true).flatMap { $0 > now() ? $0 : nil }
            return .waitingForNetwork(notBefore: deadline)
        }
        if let deadline = watchCheckDeadline(), deadline > now() { return .scheduled(deadline) }
        return .ready
    }

    private let transport: any HTTPTransport
    private let installed: (any InstalledReading)?
    private var installedUpdates: [OtherUpdate] = []
    private var installationCapture: InstallationCapture?
    private var installedCallers = 0
    private var targetedVersions: [PackageKind: [PackageName: TargetedInstallation]] = [:]
    private var installationRevision = 0
    private let store: WatchStore
    private let notifier: any Notifier
    private let now: () -> Date
    private var cache: ListingCache
    private var client: HomebrewClient
    private var generations: [PackageName: UUID]
    private var pendingAdds: Set<PackageName> = []
    private let catalogClient: CatalogClient?
    private var lastCatalogAttempt: Date?
    private var lastCheckAttempt: Date?
    private var lastFailedSave: Date?
    private var retryWatchesOnReconnect = false

    public convenience init(transport: any HTTPTransport, installed: (any InstalledReading)?, store: WatchStore,
                notifier: any Notifier, now: @escaping () -> Date = Date.init,
                catalogClient: CatalogClient? = nil, networkAvailable: Bool = true) {
        self.init(transport: transport, installed: installed, store: store, notifier: notifier, now: now,
                  catalogClient: catalogClient, networkAvailable: networkAvailable, initialCache: nil)
    }

    init(transport: any HTTPTransport, installed: (any InstalledReading)?, store: WatchStore,
         notifier: any Notifier, now: @escaping () -> Date = Date.init,
         catalogClient: CatalogClient? = nil, networkAvailable: Bool = true, initialCache: ListingCache?) {
        let load = store.load()
        state = load.state; persistenceError = load.problem; canSave = load.canSave
        persistenceIssue = load.problem == nil ? nil : (load.canSave ? .recoveryWarning : .loadFailure)
        self.networkAvailable = networkAvailable
        self.transport = transport; self.installed = installed; self.store = store
        self.notifier = notifier; self.now = now
        self.catalogClient = catalogClient
        let cache = initialCache ?? ListingCache(entries: load.state.listingCache)
        self.cache = cache; client = HomebrewClient(transport: transport, cache: cache)
        generations = Dictionary(uniqueKeysWithValues: load.state.watched.map { ($0.name, UUID()) })
    }

    public func retryLoad() {
        guard !isChecking, !isRefreshingCatalog, pendingAdds.isEmpty else { return }
        let load = store.load()
        state = load.state; persistenceError = load.problem; canSave = load.canSave
        persistenceIssue = load.problem == nil ? nil : (load.canSave ? .recoveryWarning : .loadFailure)
        cache = ListingCache(entries: load.state.listingCache)
        client = HomebrewClient(transport: transport, cache: cache)
        generations = Dictionary(uniqueKeysWithValues: load.state.watched.map { ($0.name, UUID()) })
        installationCapture = nil
        targetedVersions = [:]
        recomputeOthers()
        Task { await self.refreshInstalled() }
    }

    @discardableResult private func commit(_ candidate: AppState) -> Bool {
        guard canSave else { return false }
        var candidate = candidate
        let watched = Set(candidate.watched.map(\.name))
        candidate.listingCache = candidate.listingCache.filter { watched.contains($0.value.listing.name) }
        guard candidate != state else { return true }
        do {
            try store.save(candidate)
            state = candidate; persistenceError = nil; persistenceIssue = nil
            refreshSearchWatchState()
            recomputeOthers()
            return true
        } catch {
            persistenceError = "Couldn't save state: \(error.localizedDescription)"
            persistenceIssue = .saveFailure; lastFailedSave = now()
            return false
        }
    }

    public func add(_ name: PackageName, kind: PackageKind?) async {
        guard canSave, !state.watched.contains(where: { $0.name == name }), !pendingAdds.contains(name) else { return }
        pendingAdds.insert(name)
        defer { pendingAdds.remove(name) }
        var entry = WatchEntry(name: name, kind: kind)
        var found: Listing?
        var installation = InstalledSnapshot()
        do {
            let listing = try await scheduler.lookup(name, kinds: kind.map(KindPreference.init) ?? .auto, client: client)
            found = listing
            installation = await lookupInstalled([listing])
        } catch {
            entry.lastError = (error as? LookupError)?.rowMessage ?? "Couldn't reach Homebrew."
        }
        let snapshot = cache.snapshot()
        guard canSave, !state.watched.contains(where: { $0.name == name }) else { return }
        if let listing = found {
            entry = evaluate(entry, listing: listing, installed: installation.installed(name, kind: listing.kind)).0
        }
        var candidate = state
        candidate.watched.append(entry)
        candidate.listingCache = snapshot
        if commit(candidate) {
            generations[name] = UUID()
            await notifier.requestAuthorization()
        }
    }

    public func remove(_ name: PackageName) -> (entry: WatchEntry, index: Int)? {
        guard canSave, let index = state.watched.firstIndex(where: { $0.name == name }) else { return nil }
        var candidate = state
        let entry = candidate.watched.remove(at: index)
        guard commit(candidate) else { return nil }
        generations.removeValue(forKey: name)
        // Replace the cache boundary synchronously: in-flight lookups can finish
        // into their old actor, but cannot resurrect a removed watch's ETag.
        cache = ListingCache(entries: state.listingCache)
        client = HomebrewClient(transport: transport, cache: cache)
        return (entry, index)
    }
    @discardableResult public func restore(_ entry: WatchEntry, at index: Int) -> Bool {
        guard canSave, !state.watched.contains(where: { $0.name == entry.name }) else { return false }
        var candidate = state
        candidate.watched.insert(entry, at: min(max(index, 0), candidate.watched.count))
        guard commit(candidate) else { return false }
        generations[entry.name] = UUID()
        return true
    }
    public func skip(_ name: PackageName) {
        guard canSave, let index = state.watched.firstIndex(where: { $0.name == name }),
              let listing = state.watched[index].lastListing else { return }
        var candidate = state
        candidate.watched[index].skippedRelease = ReleaseID(listing)
        candidate.watched[index].unseenRelease = false
        commit(candidate)
    }
    public func popoverClosed() {
        guard canSave else { return }
        var candidate = state
        for index in candidate.watched.indices where candidate.watched[index].installed == nil {
            if let listing = candidate.watched[index].lastListing {
                candidate.watched[index].lastSeenRelease = ReleaseID(listing)
            }
            candidate.watched[index].unseenRelease = false
        }
        commit(candidate)
    }
    public func setInterval(_ interval: CheckInterval) {
        guard canSave else { return }
        var candidate = state; candidate.interval = interval; commit(candidate)
    }
    public func checkIfDue() async {
        guard automaticRequestsAllowed,
              watchCheckDeadline().map({ $0 <= now() }) ?? true else { return }
        await checkNow()
    }

    /// All watch retry gates share this deadline, including its reconnect preview.
    private func watchCheckDeadline(reconnecting: Bool = false) -> Date? {
        [lastFailedSave,
         reconnecting && retryWatchesOnReconnect ? nil : lastCheckAttempt,
         retryWatchesOnReconnect ? nil : state.lastCheck]
            .compactMap { CheckSchedule.nextDue(lastCheck: $0, interval: state.interval) }.max()
    }

    private var automaticRequestsAllowed: Bool {
        networkAvailable && CheckSchedule.isDue(lastCheck: lastFailedSave, interval: state.interval, now: now())
    }

    /// The app starts with networkAvailable=false until its path monitor answers.
    /// Reconnection bypasses transport-failure backoff, never failed-save backoff.
    public func setNetworkAvailable(_ available: Bool) async {
        let reconnect = !networkAvailable && available
        networkAvailable = available
        guard reconnect else { return }
        if retryWatchesOnReconnect { lastCheckAttempt = nil }
        lastCatalogAttempt = nil
        await scheduledTick()
    }

    private func recomputeOthers() {
        guard state.showOtherUpdates else { others = []; return }
        let watched = Set(state.watched.map(\.name))
        others = installedUpdates.filter { !watched.contains($0.listing.name) }
    }

    /// A group of overlapping callers shares one capture, plus at most one
    /// replacement for new listing metadata. Late metadata uses targeted reads.
    @discardableResult private func refreshInstalled(extraListings: [Listing] = []) async -> InstalledSnapshot {
        installedCallers += 1
        defer {
            installedCallers -= 1
            if installedCallers == 0 { installationCapture = nil; targetedVersions = [:] }
        }
        let requestedCatalog = catalog
        let listings = (catalog?.listings ?? []) + state.watched.compactMap(\.lastListing) + extraListings
        let requested = InstallationMetadata(listings)
        let needsCapture = installationCapture.map { !$0.replacement && !$0.metadata.covers(requested) } ?? true
        if needsCapture {
            let replacing = installationCapture != nil
            let installed = self.installed; let catalog = self.catalog
            let capture = InstallationCapture(metadata: requested, revision: installationRevision,
                catalogIdentity: catalog?.identity, replacement: replacing, task: Task.detached {
                    let snapshot = installed?.snapshot(listings: listings) ?? InstalledSnapshot()
                    let updates = catalog.map { otherUpdates(catalog: $0, snapshot: snapshot, watched: []) } ?? []
                    return (snapshot, updates)
                })
            installationCapture = capture
        }
        var capture = installationCapture!
        var result = await capture.task.value
        // Adopt newer work instead of restarting the scan that superseded us.
        if let newer = installationCapture, newer.id != capture.id {
            capture = newer
            result = await newer.task.value
        }
        if installationCapture?.id == capture.id, installationCapture?.published == false,
           catalog?.identity == capture.catalogIdentity {
            installedUpdates = result.1
            capture.published = true
            installationCapture = capture
            recomputeOthers()
        }
        var snapshot = result.0
        for versions in targetedVersions.values {
            for value in versions.values where value.revision > capture.revision && requested.contains(value.listing) {
                snapshot.versions[value.listing.kind, default: [:]][value.listing.name] = value.version
            }
        }
        // A third caller may need a different cask's app artifacts. Resolve
        // just that metadata rather than beginning a third full receipt scan.
        let missing = requested.listings.values.flatMap { $0.values }.filter { !capture.metadata.contains($0) }
        if !missing.isEmpty {
            let targeted = await lookupInstalled(missing)
            for listing in missing {
                snapshot.versions[listing.kind, default: [:]][listing.name] = targeted.installed(listing.name, kind: listing.kind)
            }
        }
        if capture.catalogIdentity != requestedCatalog?.identity {
            let adjusted = snapshot
            let updates = await Task.detached {
                requestedCatalog.map { otherUpdates(catalog: $0, snapshot: adjusted, watched: []) } ?? []
            }.value
            if installationCapture?.id == capture.id, catalog?.identity == requestedCatalog?.identity {
                installedUpdates = updates
                recomputeOthers()
            }
        }
        return snapshot
    }

    private func lookupInstalled(_ listings: [Listing]) async -> InstalledSnapshot {
        let installed = self.installed
        // Order observations when they start, so an older blocked read cannot
        // replace the newer value already observed by another caller.
        installationRevision += 1
        let revision = installationRevision
        let snapshot = await Task.detached {
            var snapshot = InstalledSnapshot()
            for listing in listings {
                snapshot.versions[listing.kind, default: [:]][listing.name] = installed?.installed(
                    listing.name, kind: listing.kind, listing: listing)
            }
            return snapshot
        }.value
        if installedCallers > 0 {
            for listing in listings where (targetedVersions[listing.kind]?[listing.name]?.revision ?? -1) < revision {
                targetedVersions[listing.kind, default: [:]][listing.name] = TargetedInstallation(
                    listing: listing, version: snapshot.installed(listing.name, kind: listing.kind), revision: revision)
            }
        }
        return snapshot
    }

    public func hydrateCatalog() async {
        guard let catalogClient else { return }
        let cached = try? await catalogClient.cached()
        // A refresh may have completed while disk hydration was suspended.
        if catalog == nil { catalog = cached }
        await refreshInstalled()
    }

    public func refreshCatalogIfDue() async {
        guard canSave, automaticRequestsAllowed, let catalogClient, !isRefreshingCatalog,
              CheckSchedule.isDue(lastCheck: lastCatalogAttempt, interval: state.interval, now: now()) else { return }
        isRefreshingCatalog = true
        defer { isRefreshingCatalog = false }
        if catalog == nil { await hydrateCatalog() }
        guard automaticRequestsAllowed,
              catalog == nil || (state.lastCatalogFetch.map({ $0.addingTimeInterval(86400) <= now() }) ?? true),
              CheckSchedule.isDue(lastCheck: lastCatalogAttempt, interval: state.interval, now: now()) else { return }
        lastCatalogAttempt = now()
        do {
            let result = try await catalogClient.load()
            catalogWriteError = result.cacheWriteError
            // Merge only after the final await, preserving watch/settings commits made in flight.
            if result.revalidated {
                var candidate = state
                candidate.lastCatalogFetch = now()
                guard commit(candidate) else { return }
            }
            catalog = result.catalog
            await refreshInstalled()
        } catch {
            // Existing content survives an offline or invalid first refresh. The attempt
            // clock bounds retries; only a successful persisted fetch advances the daily clock.
        }
    }

    public func scheduledTick() async {
        async let watches: Void = checkIfDue()
        async let catalog: Void = refreshCatalogIfDue()
        _ = await (watches, catalog)
    }

    public func setShowOtherUpdates(_ on: Bool) {
        guard state.showOtherUpdates != on else { return }
        var candidate = state; candidate.showOtherUpdates = on
        guard commit(candidate) else { return }
        if on {
            Task { await self.hydrateCatalog(); await self.refreshCatalogIfDue() }
        } else {
            others = []
        }
    }

    public func setOtherUpdatesCollapsed(_ collapsed: Bool) {
        var candidate = state; candidate.otherUpdatesCollapsed = collapsed; commit(candidate)
    }

    private func refreshSearchWatchState() {
        results = results.map { result in
            guard case .found(let listing, let installed, _) = result else { return result }
            return .found(listing, installed: installed, watched: state.watched.contains { $0.name == listing.name })
        }
    }
    public func clearSearch() { searchGeneration = UUID(); results = [] }
    public func search(_ text: String, kind: PackageKind? = nil) async {
        guard !Task.isCancelled else { return }
        let generation = UUID(); searchGeneration = generation
        let tokens = tokenize(text)
        let client = self.client; let scheduler = self.scheduler
        let knownKinds = Dictionary(uniqueKeysWithValues: state.watched.compactMap { entry in
            entry.kind.map { (entry.name, $0) }
        })
        let found = await withTaskGroup(of: (Int, LookupResult).self, returning: [LookupResult].self) { group in
            for (index, token) in tokens.enumerated() {
                group.addTask {
                    guard case .valid(let name) = token else {
                        if case .invalid(let value) = token { return (index, .invalid(value)) }
                        preconditionFailure()
                    }
                    let kinds = (knownKinds[name] ?? (tokens.count == 1 ? kind : nil)).map(KindPreference.init) ?? .auto
                    do { return (index, .found(try await scheduler.lookup(name, kinds: kinds, client: client), installed: nil, watched: false)) }
                    catch LookupError.notFound { return (index, .notFound(name)) }
                    catch { return (index, .failed(name, (error as? LookupError)?.rowMessage ?? "Couldn't reach Homebrew.")) }
                }
            }
            var rows: [(Int, LookupResult)] = []
            for await row in group { rows.append(row) }
            return rows.sorted { $0.0 < $1.0 }.map(\.1)
        }
        guard !Task.isCancelled, searchGeneration == generation else { return }
        let listings = found.compactMap { result -> Listing? in
            if case .found(let listing, _, _) = result { return listing }; return nil
        }
        let installation = await lookupInstalled(listings)
        guard !Task.isCancelled, searchGeneration == generation else { return }
        results = found.map { result in
            guard case .found(let listing, _, _) = result else { return result }
            return .found(listing, installed: installation.installed(listing.name, kind: listing.kind), watched: state.watched.contains { $0.name == listing.name })
        }
    }

    public func checkNow() async {
        guard canSave, !isChecking else { return }
        isChecking = true
        lastCheckAttempt = now()
        defer { isChecking = false }
        let client = self.client
        let scheduler = self.scheduler
        let requested = state.watched.map { ($0, generations[$0.name]) }
        let results = await withTaskGroup(of: CheckResult.self, returning: [CheckResult].self) { group in
            for item in requested {
                group.addTask {
                    let (entry, generation) = item
                    do {
                        let listing = try await scheduler.lookup(entry.name, kinds: entry.kind.map(KindPreference.init) ?? .auto, client: client)
                        return CheckResult(name: entry.name, generation: generation, result: .success(listing))
                    } catch {
                        return CheckResult(name: entry.name, generation: generation,
                                           result: .failure((error as? LookupError) ?? .unreachable(entry.name)))
                    }
                }
            }
            var results: [CheckResult] = []
            for await result in group {
                results.append(result)
            }
            return results
        }
        let listings = results.compactMap { try? $0.result.get() }
        let installation = await refreshInstalled(extraListings: listings)
        let snapshot = cache.snapshot()
        // No suspension from here through commit: merge into the latest committed state.
        var candidate = state
        var notices: [Notice] = []
        for result in results {
            guard generations[result.name] == result.generation,
                  let index = candidate.watched.firstIndex(where: { $0.name == result.name }) else { continue }
            switch result.result {
            case .success(let listing):
                let local = installation.installed(result.name, kind: listing.kind)
                let (entry, notice) = evaluate(candidate.watched[index], listing: listing, installed: local)
                candidate.watched[index] = entry
                if let notice { notices.append(notice) }
            case .failure(let error): candidate.watched[index].lastError = error.rowMessage
            }
        }
        retryWatchesOnReconnect = results.contains {
            if case .failure(.unreachable) = $0.result { return true }
            return false
        }
        if !retryWatchesOnReconnect { candidate.lastCheck = now() }
        candidate.listingCache = snapshot
        guard commit(candidate) else { return }
        for notice in notices { await notifier.post(notice) }
    }
}

private struct CheckResult: Sendable {
    let name: PackageName
    let generation: UUID?
    let result: Result<Listing, LookupError>
}

private struct InstallationMetadata: Sendable {
    var listings: [PackageKind: [PackageName: Listing]] = [:]
    init(_ values: [Listing]) {
        for listing in values { listings[listing.kind, default: [:]][listing.name] = listing }
    }
    func contains(_ listing: Listing) -> Bool { listings[listing.kind]?[listing.name] == listing }
    func covers(_ other: Self) -> Bool { other.listings.values.allSatisfy { $0.values.allSatisfy(contains) } }
}

private struct InstallationCapture {
    let id = UUID()
    let metadata: InstallationMetadata
    let revision: Int
    let catalogIdentity: UUID?
    let replacement: Bool
    let task: Task<(InstalledSnapshot, [OtherUpdate]), Never>
    var published = false
}

private struct TargetedInstallation {
    let listing: Listing
    let version: InstalledVersion?
    let revision: Int
}
