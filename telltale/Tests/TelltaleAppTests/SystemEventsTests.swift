// Port: brew_version/Tests/BrewVersionAppTests/SystemEventsTests.swift, SystemEventsTests, fbd3e03.
// Adaptation: Telltale reads local files, so its SystemEvents carries wake only: the periodic
// tick and the network path have no Telltale consumer (LiveStore polls and CollectorMonitor
// checks on their own clocks).
//
// Source tests at fbd3e03 -> destination tests:
// - initialOfflineAndReconnectUseControllerRetryCadence -> wakeRefreshesThePanelStore (the network
//   retry cadence has no Telltale counterpart; a wake re-reads the database instead)
// - scheduling -> scheduling (wake only)
// Helpers: EventSource; EventTransport and EventNotifier are Homebrew-specific and not ported.
import Testing
import Foundation
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

@MainActor final class EventSource: SystemEventSource {
    var handler: (@MainActor @Sendable (SystemEvent) async -> Void)?
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) async -> Void) { self.handler = handler }
    func stop() { handler = nil }
    func send(_ event: SystemEvent) async { await handler?(event) }
}
@MainActor struct SystemEventsTests {
    @Test func wakeRefreshesThePanelStore() async throws {
        try await withAsyncScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let writer = try PanelWorld.seed(paths)
            // No poll or watch in time: only the wake can refresh.
            let live = PanelWorld.live(paths)
            let source = EventSource()
            let events = SystemEvents(sources: [source]) { await live.refresh() }
            events.start()
            try PanelWorld.addAlert(writer)
            #expect(live.snapshot.alerts.isEmpty)
            await source.send(.wake)
            #expect(live.snapshot.alerts.map(\.text) == [PanelWorld.alertText])
            events.stop()
        }
    }
    @Test func scheduling() async {
        let first = EventSource(); let second = EventSource()
        var count = 0
        let adapter = SystemEvents(sources: [first, second]) { count += 1 }
        await first.send(.wake)
        #expect(count == 0) // Not started.
        adapter.start()
        await first.send(.wake); await second.send(.wake)
        #expect(count == 2)
        adapter.stop(); await first.send(.wake); await second.send(.wake)
        #expect(count == 2)
    }
}
