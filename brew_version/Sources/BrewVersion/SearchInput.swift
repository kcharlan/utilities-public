import Observation
import BrewVersionCore

/// Transient search intent, including a kind explicitly chosen from the catalog.
@MainActor @Observable final class SearchInput {
    var text = "" {
        didSet { if text != oldValue { selectedKind = nil } }
    }
    private var selectedKind: PackageKind?
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
        if request.text.isEmpty { controller.clearSearch() }
        else { await controller.search(request.text, kind: request.kind) }
    }
}
