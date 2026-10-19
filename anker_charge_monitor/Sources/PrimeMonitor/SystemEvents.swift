import Foundation
import AppKit
import Network

// Port of BrewVersion/SystemEvents.swift, SystemEventSource/NativeSystemEvents,
// 579ebb7. Sleep added; network gating moved to MonitorController; no timer.
enum SystemEvent: Equatable, Sendable { case sleep, wake, network(Bool) }
@MainActor protocol SystemEventSource: AnyObject {
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) async -> Void)
    func stop()
}
@MainActor final class SystemEvents {
    private let sources: [any SystemEventSource]
    init(sources: [any SystemEventSource]) { self.sources = sources }
    convenience init() { self.init(sources: [NativeSystemEvents()]) }
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) async -> Void) {
        for source in sources { source.start(handler) }
    }
    func stop() { for source in sources { source.stop() } }
}
@MainActor final class NativeSystemEvents: SystemEventSource {
    private let center: NotificationCenter
    private let observeNetwork: Bool
    private var observers: [NSObjectProtocol] = []
    private var monitor: NWPathMonitor?
    private var generation = UUID()
    init(center: NotificationCenter = NSWorkspace.shared.notificationCenter, observeNetwork: Bool = true) {
        self.center = center; self.observeNetwork = observeNetwork
    }
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) async -> Void) {
        stop(); let generation = generation
        for (name, event) in [(NSWorkspace.willSleepNotification, SystemEvent.sleep), (NSWorkspace.didWakeNotification, .wake)] {
            observers.append(center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in guard self?.generation == generation else { return }; await handler(event) }
            })
        }
        guard observeNetwork else { return }
        let monitor = NWPathMonitor()
        monitor.pathUpdateHandler = { [weak self] path in
            let online = path.status == .satisfied
            Task { @MainActor in guard self?.generation == generation else { return }; await handler(.network(online)) }
        }
        monitor.start(queue: DispatchQueue(label: "PrimeMonitor.network")); self.monitor = monitor
    }
    func stop() {
        generation = UUID()
        for observer in observers { center.removeObserver(observer) }; observers.removeAll()
        monitor?.cancel(); monitor = nil
    }
}

@MainActor protocol Cancellable { func cancel() }
@MainActor protocol PollScheduler {
    func schedule(after: TimeInterval, _ fire: @escaping @MainActor () -> Void) -> any Cancellable
}
@MainActor struct TimerPollScheduler: PollScheduler {
    private final class Token: Cancellable {
        var task: Task<Void, Never>?
        func cancel() { task?.cancel(); task = nil }
    }
    func schedule(after delay: TimeInterval, _ fire: @escaping @MainActor () -> Void) -> any Cancellable {
        let token = Token()
        token.task = Task { try? await Task.sleep(for: .seconds(delay)); guard !Task.isCancelled else { return }; fire() }
        return token
    }
}
