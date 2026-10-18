import Foundation
import Observation

public protocol Notifier: Sendable {
    func post(_ notice: Notice) async
    func requestAuthorization() async
}
public extension Notifier { func requestAuthorization() async {} }

public struct Suggestion: Equatable, Sendable {
    public let name: PackageName
    public let kind: PackageKind
    public let installed: Bool
}

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
    public private(set) var tapIndex: TapIndex
    public private(set) var tapCheckFailures = 0
    public private(set) var tapUncheckable = 0
    public private(set) var installedNames: [PackageKind: Set<PackageName>] = [:]
    private let taps: @Sendable () -> TapIndex
    private var tapListings: [PackageKind: [PackageName: Listing]] = [:]
    private var combinedCatalog: Catalog?
    private var pendingIdentities: Set<PackageName> = []
    private var resolver: PackageResolver {
        PackageResolver(client: client, tapClient: TapClient(transport: transport, cache: cache), taps: tapIndex)
    }
    public private(set) var catalog: Catalog?
    public private(set) var others: [OtherUpdate] = []
    public private(set) var isRefreshingCatalog = false
    public private(set) var catalogWriteError: String?
    /// Why the most recent catalog refresh failed; cleared by the next success.
    public private(set) var catalogRefreshError: String?
    /// Installed self-updating casks left out of Other updates because their
    /// real version can't be read and `includeSelfUpdating` is off.
    public private(set) var hiddenSelfUpdatingCount = 0
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
    /// Each launch refreshes the catalog once, however recent the saved fetch is.
    private var launchCatalogRefreshDone = false
    private var lastCheckAttempt: Date?
    private var lastFailedSave: Date?
    private var retryWatchesOnReconnect = false

    public convenience init(transport: any HTTPTransport, installed: (any InstalledReading)?, store: WatchStore,
                notifier: any Notifier, now: @escaping () -> Date = Date.init,
                catalogClient: CatalogClient? = nil, networkAvailable: Bool = true, taps: @escaping @Sendable () -> TapIndex = { .empty }) {
        self.init(transport: transport, installed: installed, store: store, notifier: notifier, now: now,
                  catalogClient: catalogClient, networkAvailable: networkAvailable, initialCache: nil, taps: taps)
    }

    init(transport: any HTTPTransport, installed: (any InstalledReading)?, store: WatchStore,
         notifier: any Notifier, now: @escaping () -> Date = Date.init,
         catalogClient: CatalogClient? = nil, networkAvailable: Bool = true, initialCache: ListingCache?, taps: @escaping @Sendable () -> TapIndex = { .empty }) {
        let load = store.load()
        state = load.state; persistenceError = load.problem; canSave = load.canSave
        persistenceIssue = load.problem == nil ? nil : (load.canSave ? .recoveryWarning : .loadFailure)
        self.networkAvailable = networkAvailable
        self.transport = transport; self.installed = installed; self.store = store
        self.notifier = notifier; self.now = now
        self.catalogClient = catalogClient
        self.taps = taps; tapIndex = taps()
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
        let search = searchGeneration
        var reserved: PackageName?
        defer {
            pendingAdds.remove(name)
            if let reserved { pendingIdentities.remove(reserved) }
        }
        var entry = WatchEntry(name: name, kind: kind)
        var found: Listing?
        var installation = InstalledSnapshot()
        do {
            let resolver = self.resolver
            let listing = try await scheduler.run {
                try await resolver.resolveBare(name, kinds: kind.map(KindPreference.init) ?? .auto)
            }
            // Resolve first, then reserve the canonical identity without suspending.
            guard canSave, !state.watched.contains(where: { $0.name == listing.name }),
                  !pendingIdentities.contains(listing.name) else { return }
            pendingIdentities.insert(listing.name); reserved = listing.name
            entry = WatchEntry(name: listing.name, kind: listing.kind)
            found = listing
            installation = await lookupInstalled([listing])
        } catch {
            let message = (error as? LookupError)?.rowMessage ?? "Couldn't reach Homebrew."
            if name.tap == nil {
                if searchGeneration == search {
                    results.removeAll { result in
                        switch result {
                        case .failed(let value, _), .notFound(let value): value == name
                        case .found(let listing, _, _): listing.name == name
                        case .invalid: false
                        }
                    }
                    results.append(.failed(name, message))
                }
                return
            }
            guard !pendingIdentities.contains(name) else { return }
            pendingIdentities.insert(name); reserved = name
            entry.lastError = message
        }
        let snapshot = cache.snapshot()
        guard canSave, !state.watched.contains(where: { $0.name == entry.name }) else { return }
        if let listing = found {
            entry = evaluate(entry, listing: listing, installed: installation.installed(entry.name, kind: listing.kind)).0
        }
        var candidate = state
        candidate.watched.append(entry)
        candidate.listingCache = snapshot
        if commit(candidate) {
            generations[entry.name] = UUID()
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
    public func setCatalogInterval(_ interval: CheckInterval) {
        guard canSave else { return }
        var candidate = state; candidate.catalogInterval = interval; commit(candidate)
    }
    public func setIncludeSelfUpdating(_ on: Bool) {
        guard canSave else { return }
        var candidate = state; candidate.includeSelfUpdating = on; commit(candidate)
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
        guard state.showOtherUpdates else { others = []; hiddenSelfUpdatingCount = 0; return }
        let watched = Set(state.watched.map(\.name))
        let candidates = installedUpdates.filter { !watched.contains($0.listing.name) }
        // Match `brew outdated`: a self-updating cask whose app can't be read only
        // has Homebrew's install record, which is often older than the real app.
        let unreadable = candidates.filter { $0.listing.autoUpdates && $0.installed.source == .caskroomFallback }
        hiddenSelfUpdatingCount = state.includeSelfUpdating ? 0 : unreadable.count
        others = state.includeSelfUpdating ? candidates : candidates.filter {
            !($0.listing.autoUpdates && $0.installed.source == .caskroomFallback)
        }
    }

    /// A group of overlapping callers shares one capture, plus at most one
    /// replacement for new listing metadata. Late metadata uses targeted reads.
    @discardableResult private func refreshInstalled(extraListings: [Listing] = []) async -> InstalledSnapshot {
        installedCallers += 1
        defer {
            installedCallers -= 1
            if installedCallers == 0 { installationCapture = nil; targetedVersions = [:] }
        }
        let requestedCatalog = combinedCatalog
        let listings = (combinedCatalog?.listings ?? []) + state.watched.compactMap(\.lastListing) + extraListings
        let requested = InstallationMetadata(listings)
        let needsCapture = installationCapture.map { !$0.replacement && !$0.metadata.covers(requested) } ?? true
        if needsCapture {
            let replacing = installationCapture != nil
            let installed = self.installed; let catalog = self.combinedCatalog
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
        var snapshot = result.0
        // A third caller may need a different cask's app artifacts. Resolve
        // just that metadata rather than beginning a third full receipt scan.
        let missing = requested.listings.values.flatMap { $0.values }.filter { !capture.metadata.contains($0) }
        if !missing.isEmpty {
            let targeted = await lookupInstalled(missing)
            for listing in missing {
                snapshot.versions[listing.kind, default: [:]][listing.name] = targeted.installed(listing.name, kind: listing.kind)
            }
        }
        var updates = result.1
        if capture.catalogIdentity != requestedCatalog?.identity {
            let adjusted = snapshot
            updates = await Task.detached {
                requestedCatalog.map { otherUpdates(catalog: $0, snapshot: adjusted, watched: []) } ?? []
            }.value
        }
        // Reconcile only after the last suspension. A missing-metadata read or
        // derived-list calculation may have yielded to a newer named lookup.
        var changedListings: [Listing] = []
        for versions in targetedVersions.values {
            for value in versions.values where value.revision > capture.revision && requested.contains(value.listing) {
                if snapshot.installed(value.listing.name, kind: value.listing.kind) != value.version,
                   let listing = requestedCatalog?.listing(for: value.listing.name, kind: value.listing.kind) {
                    changedListings.append(listing)
                }
                snapshot.versions[value.listing.kind, default: [:]][value.listing.name] = value.version
            }
        }
        if !changedListings.isEmpty {
            // Repair only affected names and the retained update rows, without
            // another full catalog calculation or a third filesystem scan.
            let changed = InstallationMetadata(changedListings)
            let retained = updates.filter { !changed.contains($0.listing) }.map(\.listing)
            updates = otherUpdates(catalog: Catalog(listings: retained + changedListings), snapshot: snapshot, watched: [])
        }
        if installationCapture?.id == capture.id, combinedCatalog?.identity == requestedCatalog?.identity {
            installedNames = snapshot.versions.mapValues { Set($0.keys) }
            installedUpdates = updates
            recomputeOthers()
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
        if catalog == nil { catalog = cached; rebuildCombinedCatalog() }
        await refreshInstalled()
    }

    /// Automatic refresh: once per launch, then on the Other updates interval.
    public func refreshCatalogIfDue() async { await refreshCatalog(manual: false) }

    /// The refresh button: checks watched packages and, when the catalog is older
    /// than Homebrew's API cache lifetime, Other updates too. It skips the network
    /// gate, since a path monitor can report offline while HTTP works.
    public func refreshNow() async {
        tapIndex = taps()
        async let watches: Void = checkNow()
        async let catalog: Void = refreshCatalog(manual: true)
        _ = await (watches, catalog)
    }

    private func catalogRefreshDue(manual: Bool) -> Bool {
        if catalog == nil { return true }
        guard let fetched = state.lastCatalogFetch else { return true }
        if manual { return now().timeIntervalSince(fetched) >= CheckInterval.manualCatalogFreshness }
        return !launchCatalogRefreshDone || CheckSchedule.isDue(lastCheck: fetched, interval: state.catalogInterval, now: now())
    }

    private func refreshCatalog(manual: Bool) async {
        // Failed automatic attempts retry no sooner than the shortest check interval.
        let retryFloor = CheckInterval(minutes: CheckInterval.allowedMinutes.lowerBound)!
        guard canSave, !isRefreshingCatalog,
              manual || (automaticRequestsAllowed && CheckSchedule.isDue(lastCheck: lastCatalogAttempt, interval: retryFloor, now: now()))
        else { return }
        tapIndex = taps()
        isRefreshingCatalog = true
        defer { isRefreshingCatalog = false }
        if catalog == nil { await hydrateCatalog() }
        guard manual || automaticRequestsAllowed, catalogRefreshDue(manual: manual) else { return }
        lastCatalogAttempt = now()
        // Keep the discovery snapshot and its metadata replacement in the same
        // overlap group as watched checks, including across the tap HTTP awaits.
        installedCallers += 1
        defer {
            installedCallers -= 1
            if installedCallers == 0 { installationCapture = nil; targetedVersions = [:] }
        }
        if let catalogClient {
            do {
                let result = try await catalogClient.load()
                catalogWriteError = result.cacheWriteError
                catalogRefreshError = result.refreshError
                // Merge only after the final await, preserving watch/settings commits made in flight.
                if result.revalidated {
                    var candidate = state
                    candidate.lastCatalogFetch = now()
                    // The other source still refreshes when saving the official timestamp fails.
                    if commit(candidate) {
                        launchCatalogRefreshDone = true
                        catalog = result.catalog
                        rebuildCombinedCatalog()
                    }
                } else {
                    catalog = result.catalog
                    rebuildCombinedCatalog()
                }
            } catch {
                // Existing content survives an offline or invalid first refresh. The attempt
                // clock bounds retries; only a successful persisted fetch advances the fetch time.
                catalogRefreshError = catalogRefreshMessage(error)
            }
        }
        await refreshTapListings()
        await refreshInstalled()
    }

    private func rebuildCombinedCatalog() {
        let values = (catalog?.listings ?? []) + tapListings.values.flatMap { $0.values }
        let combined = Catalog(listings: values)
        if combinedCatalog == nil || combined.listings != combinedCatalog?.listings {
            combinedCatalog = combined
        }
    }

    private func refreshTapListings() async {
        guard installed != nil, !tapIndex.taps.isEmpty || !tapListings.isEmpty else { return }
        let snapshot = await refreshInstalled()
        let resolver = self.resolver; let scheduler = self.scheduler
        let outcomes = await withTaskGroup(of: (PackageKind, PackageName, Result<Listing, LookupError>).self) { group in
            for (kind, values) in snapshot.versions {
                for name in values.keys where name.tap != nil {
                    group.addTask {
                        do {
                            let listing = try await scheduler.run { try await resolver.lookup(name, kinds: KindPreference(kind)) }
                            return (kind, name, .success(listing))
                        } catch { return (kind, name, .failure((error as? LookupError) ?? .tapUnreachable(name))) }
                    }
                }
            }
            var outcomes: [(PackageKind, PackageName, Result<Listing, LookupError>)] = []
            for await outcome in group { outcomes.append(outcome) }
            return outcomes
        }
        tapCheckFailures = 0; tapUncheckable = 0
        // Drop uninstalled rows, but retain the last listing for each failed source.
        for kind in [PackageKind.formula, .cask] {
            tapListings[kind] = tapListings[kind]?.filter { snapshot.versions[kind]?[$0.key] != nil }
        }
        for (kind, name, outcome) in outcomes {
            switch outcome {
            case .success(let listing): tapListings[kind, default: [:]][name] = listing
            case .failure(.tapUnreachable), .failure(.tapHTTP): tapCheckFailures += 1
            case .failure(.unreadableTapVersion), .failure(.unsupportedTapRemote), .failure(.notFoundInTap): tapUncheckable += 1
            case .failure: break
            }
        }
        rebuildCombinedCatalog()
    }

    public func suggestions(prefix: String, limit: Int = 8) -> [Suggestion] {
        guard limit > 0 else { return [] }
        let official = (catalog?.suggestions(prefix: prefix, limit: Int.max) ?? []).map {
            Suggestion(name: $0.name, kind: $0.kind, installed: installedNames[$0.kind]?.contains($0.name) == true)
        }
        let tapEntries = prefix.contains("/")
            ? tapIndex.suggestions(prefix: "").filter { $0.name.rawValue.hasPrefix(prefix) }
            : tapIndex.suggestions(prefix: prefix)
        var seen: [PackageKind: Set<PackageName>] = [:]
        let entries = (official + tapEntries.map {
            Suggestion(name: $0.name, kind: $0.kind, installed: installedNames[$0.kind]?.contains($0.name) == true)
        }).filter { seen[$0.kind, default: []].insert($0.name).inserted }
        return Array(entries.sorted {
            if $0.installed != $1.installed { return $0.installed }
            let a = $0.name.shortName == prefix, b = $1.name.shortName == prefix
            if a != b { return a }
            if ($0.name.tap == nil) != ($1.name.tap == nil) { return $0.name.tap == nil }
            if $0.name != $1.name { return $0.name.rawValue < $1.name.rawValue }
            return $0.kind.rawValue < $1.kind.rawValue
        }.prefix(limit))
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
        let resolver = self.resolver; let scheduler = self.scheduler
        let knownKinds = Dictionary(uniqueKeysWithValues: state.watched.compactMap { entry in
            entry.kind.map { (entry.name, $0) }
        })
        let found = await withTaskGroup(of: (Int, [LookupResult]).self, returning: [LookupResult].self) { group in
            for (index, token) in tokens.enumerated() {
                group.addTask {
                    guard case .valid(let name) = token else {
                        if case .invalid(let value) = token { return (index, [.invalid(value)]) }
                        preconditionFailure()
                    }
                    let kinds = (knownKinds[name] ?? (tokens.count == 1 ? kind : nil)).map(KindPreference.init) ?? .auto
                    var rows: [LookupResult] = []
                    var officialMissing = false
                    do {
                        let listing = try await scheduler.run { try await resolver.lookup(name, kinds: kinds) }
                        rows.append(.found(listing, installed: nil, watched: false))
                    } catch LookupError.notFound { officialMissing = true }
                    catch { rows.append(.failed(name, (error as? LookupError)?.rowMessage ?? "Couldn't reach Homebrew.")) }
                    if name.tap == nil {
                        for match in resolver.tapMatches(name, kinds: kinds) {
                            do {
                                let listing = try await scheduler.run { try await resolver.lookup(match.name, kinds: KindPreference(match.kind)) }
                                rows.append(.found(listing, installed: nil, watched: false))
                            } catch { rows.append(.failed(match.name, (error as? LookupError)?.rowMessage ?? "Couldn't reach GitHub.")) }
                        }
                    }
                    if officialMissing && rows.isEmpty { rows = [.notFound(name)] }
                    return (index, rows)
                }
            }
            var rows: [(Int, [LookupResult])] = []
            for await row in group { rows.append(row) }
            return rows.sorted { $0.0 < $1.0 }.flatMap(\.1)
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
        let resolver = self.resolver
        let scheduler = self.scheduler
        let requested = state.watched.map { ($0, generations[$0.name]) }
        let results = await withTaskGroup(of: CheckResult.self, returning: [CheckResult].self) { group in
            for item in requested {
                group.addTask {
                    let (entry, generation) = item
                    do {
                        let listing = try await scheduler.run {
                            try await resolver.lookup(entry.name, kinds: entry.kind.map(KindPreference.init) ?? .auto)
                        }
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
            if case .failure(.tapUnreachable) = $0.result { return true }
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
}

private struct TargetedInstallation {
    let listing: Listing
    let version: InstalledVersion?
    let revision: Int
}
