import Observation
import BrewVersionCore

/// Transient search intent, including a kind explicitly chosen from the catalog.
@MainActor @Observable final class SearchInput {
    var text = "" {
        didSet { if text != oldValue { selectedKind = nil } }
    }
    private var selectedKind: PackageKind?
    @ObservationIgnored private var lookupTask: Task<Void, Never>?
    private var activeRequest: Request?
    private var completedRequest: Request?
    private let waitForDebounce: @MainActor () async -> Void
    init(waitForDebounce: @escaping @MainActor () async -> Void = { try? await Task.sleep(for: .milliseconds(300)) }) {
        self.waitForDebounce = waitForDebounce
    }
    struct Request: Equatable {
        let text: String
        let kind: PackageKind?
    }
    var request: Request { Request(text: text, kind: selectedKind) }
    func select(name: PackageName, kind: PackageKind) {
        text = name.rawValue
        selectedKind = kind
    }
    func lookup(controller: WatchController) async {
        guard !Task.isCancelled else { return }
        let request = self.request
        if activeRequest == request, let lookupTask { await lookupTask.value; return }
        lookupTask?.cancel()
        activeRequest = request
        completedRequest = nil
        let task = Task {
            if !request.text.isEmpty { await waitForDebounce() }
            guard !Task.isCancelled, self.request == request else { return }
            if request.text.isEmpty { controller.clearSearch() }
            else { await controller.search(request.text, kind: request.kind) }
            guard !Task.isCancelled, self.request == request else { return }
            completedRequest = request
        }
        lookupTask = task
        await task.value
    }
    func watchSelected(_ index: Int, undo: WatchUndoAction, controller: WatchController) async {
        let request = self.request
        await lookup(controller: controller)
        guard !Task.isCancelled, self.request == request, completedRequest == request,
              controller.canSave, controller.results.indices.contains(index),
              case .found(let listing, _, false) = controller.results[index] else { return }
        await undo.watch(listing.name, kind: listing.kind, controller: controller)
    }
    func watchChoice(_ choice: SearchChoice, undo: WatchUndoAction, controller: WatchController) async {
        switch choice {
        case .suggestion(let name, let kind):
            select(name: name, kind: kind)
            await watchSelected(0, undo: undo, controller: controller)
        case .result(let index): await watchSelected(index, undo: undo, controller: controller)
        }
    }
}
