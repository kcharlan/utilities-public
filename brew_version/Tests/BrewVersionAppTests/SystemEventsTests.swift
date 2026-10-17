import Testing
import Foundation
import BrewVersionCore
@testable import BrewVersion

@MainActor final class EventSource: SystemEventSource {
    var handler: (@MainActor @Sendable (SystemEvent) async -> Void)?
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) async -> Void) { self.handler = handler }
    func stop() { handler = nil }
    func send(_ event: SystemEvent) async { await handler?(event) }
}
@MainActor struct SystemEventsTests {
    @Test func initialOfflineAndReconnectUseControllerRetryCadence() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-network-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let transport = EventTransport()
        let store = WatchStore(fileURL: home.appendingPathComponent("state.json"))
        var state = AppState.initial
        state.watched = [WatchEntry(name: PackageName("synthetic-network")!, kind: .formula)]
        try store.save(state)
        let controller = WatchController(transport: transport, installed: nil, store: store, notifier: EventNotifier(), networkAvailable: false)
        let source = EventSource()
        let events = SystemEvents(sources: [source], network: { await controller.setNetworkAvailable($0) }) { await controller.scheduledTick() }
        events.start()
        await source.send(.wake); await source.send(.periodic); await source.send(.network(false))
        #expect(await transport.count == 0)
        await source.send(.network(true))
        #expect(await transport.count == 1)
        #expect(controller.state.lastCheck == nil)
        await source.send(.wake); await source.send(.periodic); await source.send(.network(true))
        #expect(await transport.count == 1)
        await transport.allow()
        await source.send(.network(false)); await source.send(.wake)
        #expect(!controller.networkAvailable)
        await source.send(.network(true))
        #expect(await transport.count == 2)
        #expect(controller.state.lastCheck != nil)
        #expect(controller.state.watched.first?.lastError == nil)
        events.stop()
    }
    @Test func scheduling() async {
        let timer = EventSource(); let wake = EventSource(); let network = EventSource()
        var count = 0
        var paths: [Bool] = []
        let adapter = SystemEvents(sources:[timer,wake,network], network: { paths.append($0) }) { count += 1 }
        adapter.start()
        await timer.send(.periodic); await wake.send(.wake)
        #expect(count == 0)
        await network.send(.network(false))
        await timer.send(.periodic); await wake.send(.wake)
        #expect(count == 0)
        await network.send(.network(true)); await network.send(.network(true))
        #expect(paths == [false, true, true])
        #expect(count == 0) // The controller's network setter owns reconnect scheduling.
        await timer.send(.periodic); await wake.send(.wake); #expect(count == 2)
        await network.send(.network(false)); await wake.send(.wake); #expect(count == 2)
        adapter.stop(); await timer.send(.periodic); #expect(count == 2)
    }
}
private actor EventTransport: HTTPTransport {
    var count = 0
    var offline = true
    func allow() { offline = false }
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        count += 1
        if offline { throw URLError(.notConnectedToInternet) }
        return .init(status: 200, body: Data(#"{"versions":{"stable":"1-synthetic"}}"#.utf8))
    }
}
private struct EventNotifier: Notifier { func post(_ notice: Notice) async {} }
