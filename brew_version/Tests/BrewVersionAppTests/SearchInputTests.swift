import AppKit
import SwiftUI
import Testing
@testable import BrewVersion
@testable import BrewVersionCore

private actor SearchTransport: HTTPTransport {
    var requests: [URL] = []
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        requests.append(url)
        if url.host == "raw.githubusercontent.com" {
            let version = url.path.contains("homebrew-homebrew-synthetic-tap/") ? "4.5.6" : "9.0.1"
            return .init(status: 200, body: Data("class SyntheticTool < Formula\n version \"\(version)\"\nend".utf8))
        }
        let body = url.path.contains("/cask/") ? #"{"version":"2-synthetic"}"# : #"{"versions":{"stable":"1-synthetic"}}"#
        return .init(status: 200, body: Data(body.utf8))
    }
}
private struct SearchNotifier: Notifier { func post(_ notice: Notice) async {} }

@MainActor struct SearchInputTests {
    @Test func copySuggestionVersionRejectsEditedOrCancelledIntent() async throws {
        for cancel in [false, true] {
            let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-copy-intent-" + UUID().uuidString)
            defer { try? FileManager.default.removeItem(at: home) }
            let controller = WatchController(transport: SearchTransport(), installed: nil, store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: SearchNotifier())
            let clock = DebounceGate()
            defer { clock.release() }
            let input = SearchInput(waitForDebounce: { await clock.wait() })
            let pending = Task { await input.version(for: .suggestion(PackageName("synthetic-shared")!, .cask), controller: controller) }
            try await clock.entered(1)
            if cancel { pending.cancel() } else { input.text = "synthetic-edited" }
            clock.release()
            #expect(await pending.value == nil)
            #expect(controller.state.watched.isEmpty)
        }
    }
    @Test func tapSuggestionPreservesCanonicalIdentityAndCopiesItsVersion() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-choice-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let prefix = home.appendingPathComponent("prefix")
        try FileManager.default.createDirectory(at: prefix.appendingPathComponent("Cellar"), withIntermediateDirectories: true)
        for repo in ["homebrew-homebrew-synthetic-tap", "homebrew-synthetic-tap"] {
            let tap = prefix.appendingPathComponent("Library/Taps/synthetic-owner/\(repo)")
            for path in [".git", "Formula"] { try FileManager.default.createDirectory(at: tap.appendingPathComponent(path), withIntermediateDirectories: true) }
            try Data("[remote \"origin\"]\nurl=https://github.com/synthetic-owner/\(repo).git\n".utf8).write(to: tap.appendingPathComponent(".git/config"))
            try Data("# synthetic".utf8).write(to: tap.appendingPathComponent("Formula/synthetic-tool.rb"))
        }
        let index = TapIndex.scan(prefixes: HomebrewPrefix.detectAll(candidates: [prefix]))
        let name = try #require(index.suggestions(prefix: "synthetic-tool").first { $0.name.rawValue == "synthetic-owner/homebrew-synthetic-tap/synthetic-tool" }?.name)
        let controller = WatchController(transport: SearchTransport(), installed: nil, store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: SearchNotifier(), taps: { index })
        let input = SearchInput(waitForDebounce: {})
        input.select(name: name, kind: .formula)
        await input.lookup(controller: controller)
        guard case .found(let listing, _, _) = controller.results.first else { Issue.record("Missing selected tap result"); return }
        #expect(listing.name == name)
        #expect(listing.version == "4.5.6")
        #expect(await input.version(for: .suggestion(name, .formula), controller: controller) == "4.5.6")
        await input.watchChoice(.suggestion(name, .formula), undo: WatchUndoAction(), controller: controller)
        #expect(controller.state.watched.first?.name == name)
        #expect(controller.state.watched.first?.lastListing?.version == "4.5.6")
    }
    @Test func matchingPrefixSuggestionsHideOnlyTheirExactNotFound() {
        let name = PackageName("synthetic")!
        let missing: LookupResult = .notFound(name)
        #expect(visibleSearchResultIndices([missing], query: "synthetic", hasSuggestions: true).isEmpty)
        #expect(visibleSearchResultIndices([missing], query: "synthetic", hasSuggestions: false) == [0])
        #expect(visibleSearchResultIndices([missing], query: "synthetic other", hasSuggestions: true) == [0])
        #expect(visibleSearchResultIndices([.failed(name, "Synthetic unreachable"), .invalid("INVALID")], query: "synthetic", hasSuggestions: true) == [0, 1])
    }
    @Test func keyboardSuggestionSelectionKeepsKindAndResultOffset() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-suggestion-keyboard-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let transport = SearchTransport()
        let controller = WatchController(transport: transport, installed: nil, store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: SearchNotifier())
        let name = PackageName("synthetic-shared")!
        let suggestions: [(name: PackageName, kind: PackageKind)] = [(name, .formula), (name, .cask)]
        #expect(searchChoice(selection: 0, suggestions: suggestions) == .suggestion(name, .formula))
        #expect(searchChoice(selection: 1, suggestions: suggestions) == .suggestion(name, .cask))
        #expect(searchChoice(selection: 3, suggestions: suggestions) == .result(1))
        let input = SearchInput(waitForDebounce: {})
        input.text = "synthetic"
        input.select(name: name, kind: .cask)
        let selected = searchSelectionForRequest(input.request, suggestions: suggestions)
        #expect(selected == 1)
        await input.watchChoice(searchChoice(selection: selected, suggestions: suggestions), undo: WatchUndoAction(), controller: controller)
        #expect(controller.state.watched.first?.kind == .cask)
        #expect(controller.state.watched.first?.lastListing?.version == "2-synthetic")
        #expect(await transport.requests.allSatisfy { $0.path.contains("/cask/") })
    }
    @Test func stalledSearchGatesTimeOut() async {
        do { try await HeldSearchTransport().entered(timeout: .zero); Issue.record("Expected held-lookup deadline") }
        catch { #expect(error is SearchGateTimeout) }
        do { try await DebounceGate().entered(1, timeout: .zero); Issue.record("Expected debounce deadline") }
        catch { #expect(error is SearchGateTimeout) }
    }
    @Test func inFlightLookupRetainsPreviousRows() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-retained-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let transport = HeldSearchTransport()
        let controller = WatchController(transport: transport, installed: nil, store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: SearchNotifier())
        await controller.search("synthetic-old")
        let previous = controller.results
        let search = Task { await controller.search("synthetic-held") }
        defer { search.cancel(); Task { await transport.release() } }
        try await transport.entered()
        #expect(controller.results == previous)
        await transport.release()
        await search.value
        guard case .found(let listing, _, _) = controller.results.first else { Issue.record("Missing result"); return }
        #expect(listing.name.rawValue == "synthetic-held")
    }
    @Test func debounceRetainsResultsAndReturnWaitsForCurrentIntent() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-debounce-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let transport = SearchTransport()
        let controller = WatchController(transport: transport, installed: nil, store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: SearchNotifier())
        await controller.search("synthetic-old")
        let clock = DebounceGate()
        defer { clock.release() }
        let input = SearchInput(waitForDebounce: { await clock.wait() })
        input.text = "synthetic-a"
        let first = Task { await input.lookup(controller: controller) }
        try await clock.entered(1)
        input.text = "synthetic-current"
        let current = Task { await input.lookup(controller: controller) }
        try await clock.entered(2)
        #expect(controller.results.first == .found(Listing(name: PackageName("synthetic-old")!, kind: .formula, version: "1-synthetic"), installed: nil, watched: false))
        let submitted = Task { await input.watchSelected(0, undo: WatchUndoAction(), controller: controller) }
        await Task.yield()
        #expect(controller.state.watched.isEmpty)
        clock.release()
        await first.value; await current.value; await submitted.value
        #expect(controller.state.watched.map(\.name.rawValue) == ["synthetic-current"])
        #expect(await transport.requests.map(\.lastPathComponent) == ["synthetic-old.json", "synthetic-current.json", "synthetic-current.json"])
    }

    @Test func editingAfterReturnExcludesStaleSubmission() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-return-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let controller = WatchController(transport: SearchTransport(), installed: nil, store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: SearchNotifier())
        let clock = DebounceGate()
        defer { clock.release() }
        let input = SearchInput(waitForDebounce: { await clock.wait() })
        input.text = "synthetic-old"
        let submitted = Task { await input.watchSelected(0, undo: WatchUndoAction(), controller: controller) }
        try await clock.entered(1)
        input.text = "synthetic-new"
        clock.release()
        await submitted.value
        #expect(controller.state.watched.isEmpty)
    }
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
        #expect(await input.version(for: .suggestion(name, .cask), controller: controller) == "2-synthetic")
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
        #expect(view.fittingSize.height == 380)
    }
}

private actor HeldSearchTransport: HTTPTransport {
    var held: CheckedContinuation<Void, Never>?
    private var isWaiting: Bool { held != nil }
    func entered(timeout: Duration = .seconds(3)) async throws {
        try await awaitSearchCondition(timeout: timeout) { await self.isWaiting }
    }
    func release() { held?.resume(); held = nil }
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        try Task.checkCancellation()
        if url.lastPathComponent == "synthetic-held.json" { await withCheckedContinuation { held = $0 } }
        return .init(status: 200, body: Data(#"{"versions":{"stable":"1-synthetic"}}"#.utf8))
    }
}

@MainActor private final class DebounceGate {
    var waits: [CheckedContinuation<Void, Never>] = []
    func wait() async { await withCheckedContinuation { waits.append($0) } }
    private var pendingCount: Int { waits.count }
    func entered(_ count: Int, timeout: Duration = .seconds(3)) async throws {
        try await awaitSearchCondition(timeout: timeout) { await self.pendingCount >= count }
    }
    func release() { let pending = waits; waits = []; for wait in pending { wait.resume() } }
}

private struct SearchGateTimeout: Error {}
private func awaitSearchCondition(timeout: Duration, condition: @Sendable () async -> Bool) async throws {
    let deadline = ContinuousClock.now.advanced(by: timeout)
    while !(await condition()) {
        try Task.checkCancellation()
        guard ContinuousClock.now < deadline else { throw SearchGateTimeout() }
        await Task.yield()
    }
}
