import Foundation
import Observation

public protocol Notifier: Sendable {
    func post(_ notice: Notice) async
}

@MainActor @Observable public final class WatchController {
    public private(set) var state: AppState
    public private(set) var persistenceError: String?
    public private(set) var canSave: Bool
    public private(set) var isChecking = false
    public var amberCount: Int { state.watched.filter(\.isAmber).count }

    private let transport: any HTTPTransport
    private let installed: InstalledReader?
    private let store: WatchStore
    private let notifier: any Notifier
    private let now: () -> Date
    private var cache: ListingCache
    private var client: HomebrewClient
    private var generations: [PackageName: UUID]
    private var pendingAdds: Set<PackageName> = []

    public init(transport: any HTTPTransport, installed: InstalledReader?, store: WatchStore,
                notifier: any Notifier, now: @escaping () -> Date = Date.init) {
        let load = store.load()
        state = load.state; persistenceError = load.problem; canSave = load.canSave
        self.transport = transport; self.installed = installed; self.store = store
        self.notifier = notifier; self.now = now
        let cache = ListingCache(entries: load.state.listingCache)
        self.cache = cache; client = HomebrewClient(transport: transport, cache: cache)
        generations = Dictionary(uniqueKeysWithValues: load.state.watched.map { ($0.name, UUID()) })
    }

    public func retryLoad() {
        guard !isChecking, pendingAdds.isEmpty else { return }
        let load = store.load()
        state = load.state; persistenceError = load.problem; canSave = load.canSave
        cache = ListingCache(entries: load.state.listingCache)
        client = HomebrewClient(transport: transport, cache: cache)
        generations = Dictionary(uniqueKeysWithValues: load.state.watched.map { ($0.name, UUID()) })
    }

    @discardableResult private func commit(_ candidate: AppState) -> Bool {
        guard canSave else { return false }
        do {
            try store.save(candidate)
            state = candidate; persistenceError = nil
            return true
        } catch {
            persistenceError = "Couldn't save state: \(error.localizedDescription)"
            return false
        }
    }

    public func add(_ name: PackageName, kind: PackageKind?) async {
        guard canSave, !state.watched.contains(where: { $0.name == name }), !pendingAdds.contains(name) else { return }
        pendingAdds.insert(name)
        defer { pendingAdds.remove(name) }
        var entry = WatchEntry(name: name, kind: kind)
        do {
            let listing = try await client.lookup(name, kinds: kind.map(KindPreference.init) ?? .auto)
            entry = evaluate(entry, listing: listing, installed: installed?.installed(name, kind: listing.kind, listing: listing)).0
        } catch {
            entry.lastError = (error as? LookupError)?.rowMessage ?? "Couldn't reach Homebrew."
        }
        let snapshot = await cache.snapshot()
        guard canSave, !state.watched.contains(where: { $0.name == name }) else { return }
        var candidate = state
        candidate.watched.append(entry); candidate.listingCache = snapshot
        if commit(candidate) { generations[name] = UUID() }
    }

    public func remove(_ name: PackageName) -> (entry: WatchEntry, index: Int)? {
        guard canSave, let index = state.watched.firstIndex(where: { $0.name == name }) else { return nil }
        var candidate = state
        let entry = candidate.watched.remove(at: index)
        guard commit(candidate) else { return nil }
        generations.removeValue(forKey: name)
        return (entry, index)
    }
    public func restore(_ entry: WatchEntry, at index: Int) {
        guard canSave, !state.watched.contains(where: { $0.name == entry.name }) else { return }
        var candidate = state
        candidate.watched.insert(entry, at: min(max(index, 0), candidate.watched.count))
        if commit(candidate) { generations[entry.name] = UUID() }
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
        guard CheckSchedule.isDue(lastCheck: state.lastCheck, interval: state.interval, now: now()) else { return }
        await checkNow()
    }

    public func checkNow() async {
        guard canSave, !isChecking else { return }
        isChecking = true
        defer { isChecking = false }
        let client = self.client
        let requested = state.watched.map { ($0, generations[$0.name]) }
        let results = await withTaskGroup(of: CheckResult.self, returning: [CheckResult].self) { group in
            var iterator = requested.makeIterator()
            func enqueue(_ item: (WatchEntry, UUID?)) {
                group.addTask {
                    let (entry, generation) = item
                    do {
                        let listing = try await client.lookup(entry.name, kinds: entry.kind.map(KindPreference.init) ?? .auto)
                        return CheckResult(name: entry.name, generation: generation, result: .success(listing))
                    } catch {
                        return CheckResult(name: entry.name, generation: generation,
                                           result: .failure((error as? LookupError) ?? .unreachable(entry.name)))
                    }
                }
            }
            for _ in 0..<4 { if let item = iterator.next() { enqueue(item) } }
            var results: [CheckResult] = []
            for await result in group {
                results.append(result)
                if let item = iterator.next() { enqueue(item) }
            }
            return results
        }
        let snapshot = await cache.snapshot()
        // No suspension from here through commit: merge into the latest committed state.
        var candidate = state
        var notices: [Notice] = []
        for result in results {
            guard generations[result.name] == result.generation,
                  let index = candidate.watched.firstIndex(where: { $0.name == result.name }) else { continue }
            switch result.result {
            case .success(let listing):
                let local = installed?.installed(result.name, kind: listing.kind, listing: listing)
                let (entry, notice) = evaluate(candidate.watched[index], listing: listing, installed: local)
                candidate.watched[index] = entry
                if let notice { notices.append(notice) }
            case .failure(let error): candidate.watched[index].lastError = error.rowMessage
            }
        }
        candidate.lastCheck = now(); candidate.listingCache = snapshot
        guard commit(candidate) else { return }
        for notice in notices { await notifier.post(notice) }
    }
}

private struct CheckResult: Sendable {
    let name: PackageName
    let generation: UUID?
    let result: Result<Listing, LookupError>
}
