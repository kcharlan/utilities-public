import Foundation
import AppKit
import Network

public enum SystemEvent: Sendable { case periodic, wake, network(Bool) }
@MainActor public protocol SystemEventSource: AnyObject {
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) -> Void)
    func stop()
}
@MainActor public final class SystemEvents {
    private let sources: [any SystemEventSource]
    private let tick: @MainActor () -> Void
    private var online = true
    public init(sources: [any SystemEventSource], tick: @escaping @MainActor () -> Void) {
        self.sources = sources; self.tick = tick
    }
    public convenience init(tick: @escaping @MainActor () -> Void) {
        self.init(sources: [NativeSystemEvents()], tick: tick)
    }
    public func start() { for source in sources { source.start { [weak self] in self?.receive($0) } } }
    public func stop() { for source in sources { source.stop() } }
    private func receive(_ event: SystemEvent) {
        switch event {
        case .network(let connected):
            let reconnect = !online && connected
            online = connected
            if reconnect { tick() }
        case .periodic, .wake: if online { tick() }
        }
    }
}
@MainActor private final class NativeSystemEvents: SystemEventSource {
    private var timer: Timer?
    private var observer: NSObjectProtocol?
    private var monitor: NWPathMonitor?
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) -> Void) {
        stop()
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in
            Task { @MainActor in handler(.periodic) }
        }
        observer = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { _ in
            Task { @MainActor in handler(.wake) }
        }
        let monitor = NWPathMonitor()
        monitor.pathUpdateHandler = { path in
            let satisfied = path.status == .satisfied
            Task { @MainActor in handler(.network(satisfied)) }
        }
        monitor.start(queue: DispatchQueue(label: "BrewVersion.network")); self.monitor = monitor
    }
    func stop() {
        timer?.invalidate(); timer = nil
        if let observer { NSWorkspace.shared.notificationCenter.removeObserver(observer) }
        observer = nil; monitor?.cancel(); monitor = nil
    }
}
