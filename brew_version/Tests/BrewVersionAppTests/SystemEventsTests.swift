import Testing
@testable import BrewVersion

@MainActor final class EventSource: SystemEventSource {
    var handler: (@MainActor @Sendable (SystemEvent) -> Void)?
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) -> Void) { self.handler = handler }
    func stop() { handler = nil }
    func send(_ event: SystemEvent) { handler?(event) }
}
@MainActor struct SystemEventsTests {
    @Test func scheduling() async {
        let timer = EventSource(); let wake = EventSource(); let network = EventSource()
        var count = 0
        let adapter = SystemEvents(sources:[timer,wake,network]) { count += 1 }
        adapter.start()
        timer.send(.periodic); wake.send(.wake)
        #expect(count == 2)
        network.send(.network(false))
        timer.send(.periodic); wake.send(.wake)
        #expect(count == 2)
        network.send(.network(true)); network.send(.network(true))
        #expect(count == 3)
        timer.send(.periodic); #expect(count == 4)
        adapter.stop(); timer.send(.periodic); #expect(count == 4)
    }
}
