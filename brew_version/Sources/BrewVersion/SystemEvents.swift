import Foundation
import AppKit
import Network

public enum SystemEvent: Sendable { case periodic, wake, network(Bool) }
@MainActor public protocol SystemEventSource: AnyObject {
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) async -> Void)
    func stop()
}
@MainActor public final class SystemEvents {
    private let sources: [any SystemEventSource]
    private let tick: @MainActor () async -> Void
    private let network: @MainActor (Bool) async -> Void
    private var online = false
    public init(sources: [any SystemEventSource], network: @escaping @MainActor (Bool) async -> Void, tick: @escaping @MainActor () async -> Void) {
        self.sources = sources; self.tick = tick; self.network = network
    }
    public convenience init(network: @escaping @MainActor (Bool) async -> Void, tick: @escaping @MainActor () async -> Void) {
        self.init(sources: [NativeSystemEvents()], network: network, tick: tick)
    }
    public func start() { for source in sources { source.start { [weak self] in await self?.receive($0) } } }
    public func stop() { for source in sources { source.stop() } }
    private func receive(_ event: SystemEvent) async {
        switch event {
        case .network(let connected):
            online = connected
            await network(connected)
        case .periodic, .wake: if online { await tick() }
        }
    }
}
@MainActor private final class NativeSystemEvents: SystemEventSource {
    private var timer: Timer?
    private var observer: NSObjectProtocol?
    private var monitor: NWPathMonitor?
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) async -> Void) {
        stop()
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in
            Task { @MainActor in await handler(.periodic) }
        }
        observer = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { _ in
            Task { @MainActor in await handler(.wake) }
        }
        let monitor = NWPathMonitor()
        monitor.pathUpdateHandler = { path in
            let satisfied = path.status == .satisfied
            Task { @MainActor in await handler(.network(satisfied)) }
        }
        monitor.start(queue: DispatchQueue(label: "BrewVersion.network")); self.monitor = monitor
    }
    func stop() {
        timer?.invalidate(); timer = nil
        if let observer { NSWorkspace.shared.notificationCenter.removeObserver(observer) }
        observer = nil; monitor?.cancel(); monitor = nil
    }
}
