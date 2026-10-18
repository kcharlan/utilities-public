import Foundation
import Observation
import BrewVersionCore

@MainActor @Observable final class WatchUndoAction {
    private(set) var removed: (entry: WatchEntry, index: Int)?
    private(set) var retryRequired = false
    var canRemove: Bool { !retryRequired }
    @ObservationIgnored private(set) var expiryTask: Task<Void, Never>?
    private var generation = UUID()
    private let waitForExpiry: @Sendable () async -> Void

    init(waitForExpiry: @escaping @Sendable () async -> Void = { try? await Task.sleep(for: .seconds(5)) }) {
        self.waitForExpiry = waitForExpiry
    }
    @discardableResult func remove(_ name: PackageName, controller: WatchController) -> Bool {
        guard canRemove, let removal = controller.remove(name) else { return false }
        removed = removal
        let generation = UUID(); self.generation = generation
        expiryTask?.cancel()
        expiryTask = Task {
            await waitForExpiry()
            if !Task.isCancelled, self.generation == generation { removed = nil }
        }
        return true
    }
    func restore(controller: WatchController) {
        guard let removed else { return }
        let restored = controller.restore(removed.entry, at: removed.index)
        if restored { self.removed = nil }
        retryRequired = !restored
        // A failed persistence action must not expire its only recovery entry.
        generation = UUID()
        expiryTask?.cancel()
    }
    func watch(_ name: PackageName, kind: PackageKind, controller: WatchController) async {
        if removed?.entry.name == name { restore(controller: controller) }
        else { await controller.add(name, kind: kind, exactSource: true) }
    }
}
