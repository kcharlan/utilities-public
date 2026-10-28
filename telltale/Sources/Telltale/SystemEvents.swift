// Port: brew_version/Sources/BrewVersion/SystemEvents.swift, SystemEvents and NativeSystemEvents, fbd3e03.
// Adaptation: wake only. Telltale reads local files, so it has no network path to follow, and
// LiveStore and CollectorMonitor run their own clocks; a wake re-reads at once instead of waiting.
import Foundation
import AppKit

public enum SystemEvent: Sendable { case wake }
@MainActor public protocol SystemEventSource: AnyObject {
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) async -> Void)
    func stop()
}
@MainActor public final class SystemEvents {
    private let sources: [any SystemEventSource]
    private let wake: @MainActor () async -> Void
    public init(sources: [any SystemEventSource], wake: @escaping @MainActor () async -> Void) {
        self.sources = sources; self.wake = wake
    }
    public convenience init(wake: @escaping @MainActor () async -> Void) {
        self.init(sources: [NativeSystemEvents()], wake: wake)
    }
    public func start() { for source in sources { source.start { [weak self] in await self?.receive($0) } } }
    public func stop() { for source in sources { source.stop() } }
    private func receive(_ event: SystemEvent) async {
        switch event {
        case .wake: await wake()
        }
    }
}
@MainActor final class NativeSystemEvents: SystemEventSource {
    private var observer: NSObjectProtocol?
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) async -> Void) {
        stop()
        observer = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { _ in
            Task { @MainActor in await handler(.wake) }
        }
    }
    func stop() {
        if let observer { NSWorkspace.shared.notificationCenter.removeObserver(observer) }
        observer = nil
    }
}
