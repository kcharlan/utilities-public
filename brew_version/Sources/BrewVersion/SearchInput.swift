import Observation
import BrewVersionCore

/// Transient search intent, including a kind explicitly chosen from the catalog.
@MainActor @Observable final class SearchInput {
    var text = "" {
        didSet { if text != oldValue { selectedKind = nil; selectedName = nil } }
    }
    private var selectedKind: PackageKind?
    private var selectedName: PackageName?
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
        let name: PackageName?
    }
    var request: Request { Request(text: text, kind: selectedKind, name: selectedName) }
    func select(name: PackageName, kind: PackageKind) {
        text = name.rawValue
        selectedKind = kind
        selectedName = name
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
            else if let name = request.name { await controller.search(name, kind: request.kind) }
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
    func version(for choice: SearchChoice, controller: WatchController) async -> String? {
        if case .suggestion(let name, let kind) = choice { select(name: name, kind: kind) }
        let request = self.request
        await lookup(controller: controller)
        guard !Task.isCancelled, self.request == request, completedRequest == request else { return nil }
        switch choice {
        case .suggestion(let name, let kind):
            for result in controller.results {
                if case .found(let listing, _, _) = result, listing.name == name, listing.kind == kind { return ReleaseID(listing).displayVersion }
            }
            return nil
        case .result(let index):
            guard controller.results.indices.contains(index), case .found(let listing, _, _) = controller.results[index] else { return nil }
            return ReleaseID(listing).displayVersion
        }
    }
}
