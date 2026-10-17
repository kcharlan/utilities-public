import AppKit
import SwiftUI
import Testing
@testable import BrewVersion
@testable import BrewVersionCore

private actor SearchTransport: HTTPTransport {
    var requests: [URL] = []
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        requests.append(url)
        let body = url.path.contains("/cask/") ? #"{"version":"2-synthetic"}"# : #"{"versions":{"stable":"1-synthetic"}}"#
        return .init(status: 200, body: Data(body.utf8))
    }
}
private struct SearchNotifier: Notifier { func post(_ notice: Notice) async {} }

@MainActor struct SearchInputTests {
    @Test func selectedCaskSurvivesLookupAndWatchThenEditingRestoresAutomaticLookup() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-search-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let transport = SearchTransport()
        let controller = WatchController(transport: transport, installed: nil, store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: SearchNotifier())
        let input = SearchInput()
        let name = PackageName("synthetic-shared")!
        input.text = name.rawValue
        let automatic = input.request
        input.select(name: name, kind: .cask)
        #expect(input.request != automatic) // Same text must still restart the text task.
        await input.lookup(controller: controller)
        guard case .found(let listing, _, false) = controller.results.first else { Issue.record("Expected cask suggestion result"); return }
        #expect(listing.kind == .cask)
        await WatchUndoAction().watch(listing.name, kind: listing.kind, controller: controller)
        #expect(controller.state.watched.first?.kind == .cask)
        #expect(await transport.requests.allSatisfy { $0.path == "/api/cask/synthetic-shared.json" })
        _ = controller.remove(name)
        input.text = "synthetic-other"
        input.text = name.rawValue
        await input.lookup(controller: controller)
        #expect(await transport.requests.last?.path == "/api/formula/synthetic-shared.json")
        let previous = controller.results
        input.text = ""
        let cancelled = Task { await input.lookup(controller: controller) }
        cancelled.cancel()
        await cancelled.value
        #expect(controller.results == previous)
        await input.lookup(controller: controller)
        #expect(controller.results.isEmpty)
    }

    @Test func largeSearchLayoutStaysBoundedOffscreen() async {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-search-layout-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let controller = WatchController(transport: SearchTransport(), installed: nil, store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: SearchNotifier())
        let input = SearchInput()
        input.text = (0..<100).map { "synthetic-result-\($0)" }.joined(separator: " ")
        await input.lookup(controller: controller)
        #expect(controller.results.count == 100)
        let view = NSHostingView(rootView: SearchResults(controller: controller, undo: WatchUndoAction(), query: input.text, selection: .constant(99), selectSuggestion: { _, _ in }).frame(width: 418))
        view.layoutSubtreeIfNeeded()
        #expect(controller.results.count == 100)
        #expect(view.fittingSize.height == 300)
    }
}
