import AppKit
import Testing
@testable import PrimeMonitor
@Suite @MainActor struct SystemEventsTests {
    @Test func sleepAndWakeAreDelivered() async {
        let source = TestEvents(), events = SystemEvents(sources: [TestEvents()])
        var received: [SystemEvent] = []
        let injected = SystemEvents(sources: [source]); injected.start { received.append($0) }
        await source.send(.network(false)); await source.send(.sleep); await source.send(.wake)
        await source.send(.network(true)); await source.send(.sleep); await source.send(.wake)
        #expect(received == [.network(false), .sleep, .wake, .network(true), .sleep, .wake])
        injected.stop(); #expect(source.stopped); events.stop()
    }
    @Test func nativeObserversAreRemovedOnStop() async {
        let center = NotificationCenter()
        let native = NativeSystemEvents(center: center, observeNetwork: false)
        var received: [SystemEvent] = []
        native.start { received.append($0) }
        center.post(name: NSWorkspace.willSleepNotification, object: nil); center.post(name: NSWorkspace.didWakeNotification, object: nil); await settle()
        #expect(received == [.sleep, .wake]); native.stop()
        center.post(name: NSWorkspace.didWakeNotification, object: nil); center.post(name: NSWorkspace.willSleepNotification, object: nil); await settle()
        #expect(received == [.sleep, .wake])
    }
}
