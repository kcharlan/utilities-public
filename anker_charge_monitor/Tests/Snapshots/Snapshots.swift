import AppKit
import SwiftUI
import ServiceManagement
import PrimeMonitorCore

// Synthetic source-copy entry only. Never starts native event observation,
// provider commands, Keychain, networking, login registration or desktop input.
@main struct Snapshots {
    @MainActor static func main() async throws {
        _ = NSApplication.shared
        guard CommandLine.arguments.count == 2 else { fatalError("Expected private temporary output directory") }
        let home = URL(filePath: CommandLine.arguments[1], directoryHint: .isDirectory).standardizedFileURL
        let temporary = FileManager.default.temporaryDirectory.standardizedFileURL.resolvingSymlinksInPath()
        guard Array(home.resolvingSymlinksInPath().pathComponents.dropLast()) == temporary.pathComponents,
              (try FileManager.default.attributesOfItem(atPath: home.path(percentEncoded: false))[.posixPermissions] as? NSNumber)?.intValue == 0o700 else { fatalError("Snapshots require a private OS temporary directory") }
        for dark in [false, true] {
            let palette = dark ? "dark" : "light"
            for state in ["live", "stale", "error", "not-set-up"] {
                let fixture = try await Fixture.make(state: state, directory: home.appending(path: "menu-\(state)-\(palette)", directoryHint: .isDirectory))
                let presentation = StatusPresentation.make(status: fixture.monitor.status, snapshot: fixture.monitor.snapshot, isStale: fixture.monitor.isStale, now: Date())
                let button = NSButton(frame: .zero)
                button.isBordered = false; button.imagePosition = .imageLeading
                presentation.apply(to: button); button.sizeToFit()
                let background = NSView(frame: NSRect(x: 0, y: 0, width: max(32, button.frame.width + 12), height: 30))
                button.setFrameOrigin(NSPoint(x: 6, y: (30 - button.frame.height) / 2)); background.addSubview(button)
                try capture(background, size: background.frame.size, dark: dark, to: home.appending(path: "menu-\(state)-\(palette).png", directoryHint: .notDirectory))
                await fixture.monitor.stop()
            }
            for state in ["live", "stale", "signed-out", "choose-charger", "error", "session-ended"] {
                let fixture = try await Fixture.make(state: state, directory: home.appending(path: "panel-\(state)-\(palette)", directoryHint: .isDirectory))
                let settings = SettingsWindowController(controller: fixture.monitor, login: LoginItem(service: SnapshotLogin()), activate: {}, present: { _ in })
                let hosting = StatusContent(controller: fixture.monitor, settings: settings, focus: PopoverFocus()).makeHostingController()
                let view = hosting.view
                view.layoutSubtreeIfNeeded()
                let size = view.fittingSize
                guard abs(size.width - 400) < 0.5, size.height > 100, size.height < 560 else { fatalError("Unexpected real panel size: \(size)") }
                try capture(view, size: size, dark: dark, to: home.appending(path: "panel-\(state)-\(palette).png", directoryHint: .notDirectory))
                await fixture.monitor.stop()
            }
            let fixture = try await Fixture.make(state: "live", directory: home.appending(path: "settings-\(palette)", directoryHint: .isDirectory))
            let hosting = NSHostingController(rootView: SettingsView(monitor: fixture.monitor, login: LoginItem(service: SnapshotLogin())))
            hosting.sizingOptions = []
            for bottom in [false, true] {
                try capture(hosting.view, size: NSSize(width: 460, height: 600), dark: dark,
                            to: home.appending(path: "settings-\(bottom ? "bottom" : "top")-\(palette).png", directoryHint: .notDirectory), scrollToBottom: bottom)
            }
            await fixture.monitor.stop()
        }
        let pngs = try FileManager.default.contentsOfDirectory(at: home, includingPropertiesForKeys: nil).filter { $0.pathExtension == "png" }
        guard pngs.count == 24 else { fatalError("Expected 24 PNGs, got \(pngs.count)") }
        print("Validated 24 maintained-view PNGs: real status presentation, owned panel hosting and grouped Settings in both appearances.")
    }

    // Port: BV Snapshots.swift render, 579ebb7. Offscreen NSWindow capture,
    // actual pixels/viewport checks; supported URL API replaces legacy copying.
    @MainActor private static func capture(_ view: NSView, size: NSSize, dark: Bool, to destination: URL, scrollToBottom: Bool = false) throws {
        let appearance = NSAppearance(named: dark ? .darkAqua : .aqua)!
        let window = NSWindow(contentRect: NSRect(origin: NSPoint(x: -10000, y: -10000), size: size), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.appearance = appearance
        window.backgroundColor = .windowBackgroundColor; window.contentView = view
        view.appearance = appearance
        view.wantsLayer = true; view.layer?.backgroundColor = (dark ? NSColor(calibratedWhite: 0.14, alpha: 1) : NSColor(calibratedWhite: 0.97, alpha: 1)).cgColor
        for _ in 0..<8 {
            window.setContentSize(size); view.frame.size = size; view.layoutSubtreeIfNeeded()
            RunLoop.current.run(until: Date().addingTimeInterval(0.025))
        }
        for scroll in scrolls(view) {
            guard scroll.frame.width <= size.width + 0.5, scroll.frame.height > 0 else { fatalError("Invalid scroll viewport") }
            if let document = scroll.documentView {
                guard document.frame.width <= scroll.contentView.bounds.width + 0.5 else { fatalError("Horizontally clipped content") }
                if scrollToBottom { scroll.contentView.scroll(to: NSPoint(x: 0, y: max(0, document.frame.height - scroll.contentView.bounds.height))); scroll.reflectScrolledClipView(scroll.contentView) }
            }
        }
        view.layoutSubtreeIfNeeded(); window.displayIfNeeded(); view.display()
        guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { fatalError("Cannot allocate image") }
        appearance.performAsCurrentDrawingAppearance { view.cacheDisplay(in: view.bounds, to: bitmap) }
        var colors: Set<UInt32> = []
        let sampleStep = size.height <= 30 ? 1 : 3
        for y in stride(from: 0, to: bitmap.pixelsHigh, by: sampleStep) {
            for x in stride(from: 0, to: bitmap.pixelsWide, by: sampleStep) {
                if let color = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB), color.alphaComponent > 0.1 {
                    colors.insert(UInt32(color.redComponent * 255) << 16 | UInt32(color.greenComponent * 255) << 8 | UInt32(color.blueComponent * 255))
                }
            }
        }
        guard let data = bitmap.representation(using: .png, properties: [:]) else { fatalError("Cannot encode PNG") }
        try data.write(to: destination)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: destination.path(percentEncoded: false))
        guard colors.count > 15 else { fatalError("Blank rendering: \(colors.count) colors, \(destination.path(percentEncoded: false))") }
        print("\(destination.path(percentEncoded: false)) (\(Int(size.width)) × \(Int(size.height)) pt; \(colors.count) colors")
        window.contentView = nil
    }
    @MainActor private static func scrolls(_ view: NSView) -> [NSScrollView] {
        if let scroll = view as? NSScrollView { return [scroll] }
        return view.subviews.flatMap(scrolls)
    }
}

@MainActor private struct Fixture {
    let monitor: MonitorController
    static func make(state: String, directory: URL) async throws -> Self {
        let empty = state == "signed-out" || state == "not-set-up"
        let store = StateStore(fileURL: directory.appending(path: "state.json", directoryHint: .notDirectory))
        let charger = ChargerInfo(serial: "synthetic-charger", model: "A2345", alias: "Desk charger", name: "Anker Prime")
        if !empty { try store.save(.init(charger: state == "choose-charger" ? nil : charger, closedInterval: .default, credentials: OnePasswordConfiguration(item: "Anker", vault: nil, country: "US").selection)) }
        let date = Date(), scheduler = SnapshotScheduler()
        let backend = SnapshotBackend(charger: charger, receivedAt: state == "stale" ? date.addingTimeInterval(-180) : date)
        let events = SnapshotEvents()
        let monitor = MonitorController(backend: backend, secrets: MemorySessionStore(), state: store, events: SystemEvents(sources: [events]), now: { scheduler.date }, scheduler: scheduler, makeProvider: { _ in SnapshotProvider() })
        monitor.start()
        await events.handler?(.network(true))
        for _ in 0..<1000 {
            if empty && monitor.status == .notConfigured { break }
            if state == "choose-charger" && !monitor.chargers.isEmpty { break }
            if monitor.snapshot != nil { break }
            await Task.yield()
        }
        if !empty && state != "choose-charger" { guard monitor.snapshot != nil else { fatalError("Synthetic snapshot not delivered") } }
        if state == "error" { await events.handler?(.network(false)) }
        if state == "session-ended" { backend.output.yield(.status(.sessionEnded)); for _ in 0..<100 { await Task.yield() } }
        return .init(monitor: monitor)
    }
}
private struct SnapshotProvider: CredentialProvider {
    func retrieve() async throws -> AnkerCredentials { .init(email: "synthetic@example.invalid", password: "synthetic-password", country: "US") }
}
@MainActor private final class SnapshotEvents: SystemEventSource {
    var handler: (@MainActor @Sendable (SystemEvent) async -> Void)?
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) async -> Void) { self.handler = handler }
    func stop() { handler = nil }
}
@MainActor private final class SnapshotScheduler: PollScheduler {
    let date = Date()
    private final class Token: Cancellable { func cancel() {} }
    func schedule(after: TimeInterval, _ fire: @escaping @MainActor () -> Void) -> any Cancellable { Token() }
}
@MainActor private struct SnapshotLogin: LoginService {
    var status: SMAppService.Status { .requiresApproval }
    func register() throws { fatalError("Snapshot cannot register login item") }
    func unregister() throws { fatalError("Snapshot cannot unregister login item") }
    func openSettings() { fatalError("Snapshot cannot open System Settings") }
}
private actor SnapshotBackend: ChargerBackend {
    final class Output: @unchecked Sendable {
        private let lock = NSLock()
        private var channels: [UUID: AsyncStream<BackendEvent>.Continuation] = [:]
        func subscribe() -> AsyncStream<BackendEvent> {
            let id = UUID(), (stream, continuation) = AsyncStream<BackendEvent>.makeStream()
            lock.withLock { channels[id] = continuation }
            continuation.onTermination = { [weak self] _ in self?.remove(id) }
            return stream
        }
        private func remove(_ id: UUID) { _ = lock.withLock { channels.removeValue(forKey: id) } }
        func yield(_ event: BackendEvent) { for channel in lock.withLock({ Array(channels.values) }) { channel.yield(event) } }
    }
    nonisolated let output = Output()
    let charger: ChargerInfo
    let receivedAt: Date
    init(charger: ChargerInfo, receivedAt: Date) { self.charger = charger; self.receivedAt = receivedAt }
    nonisolated var events: AsyncStream<BackendEvent> { output.subscribe() }
    func subscribeToEvents() async -> AsyncStream<BackendEvent> { output.subscribe() }
    func signIn(_ credentials: AnkerCredentials) async throws -> AccountSession { .init(authToken: "synthetic-token", userID: "synthetic-user", expiresAt: .distantFuture, nickname: "") }
    func restore(_ session: AccountSession, credentials: AnkerCredentials) async {}
    func listChargers() async throws -> [ChargerInfo] { [charger] }
    func connect(to charger: ChargerInfo) async throws {}
    func requestSnapshot() async throws {
        let readings = PortID.allCases.map { port in
            PortReading(port: port, active: port == .c4, voltageMilli: port == .c4 ? 20000 : 0,
                        currentMilli: port == .c4 ? 1490 : (port.rawValue.hasPrefix("c") ? 20 : 0), powerCenti: port == .c4 ? 4321 : 0)
        }
        output.yield(.snapshot(.init(receivedAt: receivedAt, readings: readings)))
    }
    func disconnect() async {}
}
