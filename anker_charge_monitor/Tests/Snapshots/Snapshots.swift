import AppKit
import SwiftUI
import ServiceManagement
import PrimeMonitorCore

// Synthetic source-copy entry only. Never starts native event observation,
// provider commands, Keychain, networking, login registration or desktop input.
@main struct Snapshots {
    static let menuStates: [(String, MenuBarTextSize)] = [("live", .default), ("stale", .default), ("error", .default), ("not-set-up", .default), ("live", .pt10)]
    /// "details": invented faults, over-temperature, identity support 2 beside
    /// a resolved, a no-device and an unresolved port, and a catalog problem.
    /// "switches-off": invented switch states, C2 and the shared USB-A switch off,
    /// with C2 expanded to show its port-switch line.
    /// "expanded-named": an expanded row naming a synthetic device.
    /// "armed": Turn off armed on the expanded C4, with its caption.
    /// "restart-paused": a C1 restart held in its pause; the backend confirmed
    /// off and then stopped replying, under the non-firing scheduler.
    /// "outcome-off": a turn-on of C2 the charger ignored, reported as still off.
    static let panelStates = ["live", "stale", "signed-out", "choose-charger", "error", "session-ended", "details", "switches-off", "expanded-named",
                              "armed", "restart-paused", "outcome-off"]
    @MainActor static func main() async throws {
        _ = NSApplication.shared
        guard CommandLine.arguments.count == 2 else { fatalError("Expected private temporary output directory") }
        let home = URL(filePath: CommandLine.arguments[1], directoryHint: .isDirectory).standardizedFileURL
        let temporary = FileManager.default.temporaryDirectory.standardizedFileURL.resolvingSymlinksInPath()
        // A caller-owned home may sit inside the caller's own private scratch.
        guard home.resolvingSymlinksInPath().pathComponents.starts(with: temporary.pathComponents),
              home.resolvingSymlinksInPath().pathComponents.count > temporary.pathComponents.count,
              (try FileManager.default.attributesOfItem(atPath: home.path(percentEncoded: false))[.posixPermissions] as? NSNumber)?.intValue == 0o700 else { fatalError("Snapshots require a private OS temporary directory") }
        for dark in [false, true] {
            let palette = dark ? "dark" : "light"
            for (state, size) in menuStates {
                let name = size == .default ? state : "\(state)-\(size.rawValue)pt"
                let fixture = try await Fixture.make(state: state, directory: home.appending(path: "menu-\(name)-\(palette)", directoryHint: .isDirectory))
                let presentation = StatusPresentation.make(status: fixture.monitor.status, snapshot: fixture.monitor.snapshot, isStale: fixture.monitor.isStale, now: Date(), textSize: size)
                let button = NSButton(frame: .zero)
                button.isBordered = false
                presentation.apply(to: button); button.sizeToFit()
                // The composed image is the whole button: no title-cell insets.
                guard let image = button.image, button.frame.width == image.size.width, button.title.isEmpty else { fatalError("Status button wider than its image: \(button.frame.width)") }
                let background = NSView(frame: NSRect(x: 0, y: 0, width: max(32, button.frame.width + 12), height: 30))
                button.setFrameOrigin(NSPoint(x: 6, y: (30 - button.frame.height) / 2)); background.addSubview(button)
                try capture(background, size: background.frame.size, dark: dark, to: home.appending(path: "menu-\(name)-\(palette).png", directoryHint: .notDirectory))
                await fixture.monitor.stop()
            }
            for state in panelStates {
                let fixture = try await Fixture.make(state: state, directory: home.appending(path: "panel-\(state)-\(palette)", directoryHint: .isDirectory))
                let settings = SettingsWindowController(controller: fixture.monitor, login: LoginItem(service: SnapshotLogin()), activate: {}, present: { _ in })
                let hosting = StatusContent(controller: fixture.monitor, catalog: fixture.catalog, detail: fixture.detail, settings: settings, focus: PopoverFocus()).makeHostingController()
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
        // Both appearances of every menu and panel state plus two Settings scroll positions.
        let expected = 2 * (menuStates.count + panelStates.count + 2)
        guard pngs.count == expected else { fatalError("Expected \(expected) PNGs, got \(pngs.count)") }
        print("Validated \(expected) maintained-view PNGs: real status presentation at standard and 10 pt (\(menuStates.count) states), owned panel hosting (\(panelStates.count) states: \(panelStates.joined(separator: ", "))) and grouped Settings in both appearances.")
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
    let catalog: DeviceCatalogStore
    let detail: PortDetailState
    /// Invented detail values; never captured from a charger.
    static func details(for state: String) -> ChargerDetails? {
        switch state {
        case "details":
            // Over-temperature, C2 and the shared USB-A bit.
            ChargerDetails(faultBits: 0x25, identitySupport: 2, identities: [
                .c1: .identified(vendorID: 0xfeed, productID: 0xbeef, brandClass: 10, modelCode: 7),
                .c2: .nothingAttached, .c3: .identifying, .c4: .nothingAttached,
            ], rawFields: [:])
        case "expanded-named":
            ChargerDetails(faultBits: 0, identitySupport: 6, identities: [
                .c1: .identified(vendorID: 0x0a1b, productID: 0x2c3d, brandClass: 7, modelCode: 3),
                .c2: .identified(vendorID: 0xfeed, productID: 0xbeef, brandClass: 42, modelCode: nil),
                .c3: .identifying, .c4: .nothingAttached,
            ], rawFields: [:], switches: [.c1: true, .c2: true, .c3: true, .c4: true, .usbA: true])
        case "switches-off":
            // C2 and the shared USB-A switch off; C3 reports no switch, so it makes no claim.
            ChargerDetails(faultBits: 0, identitySupport: 6, identities: [
                .c1: .identified(vendorID: 0x0a1b, productID: 0x2c3d, brandClass: 7, modelCode: 3),
                .c2: .nothingAttached, .c3: .identifying, .c4: .nothingAttached,
            ], rawFields: [:], switches: [.c1: true, .c2: false, .c4: true, .usbA: false])
        case "armed":
            // C4 supplies the fixture's only power to the named lamp.
            ChargerDetails(faultBits: 0, identitySupport: 6, identities: [
                .c1: .nothingAttached, .c2: .nothingAttached, .c3: .identifying,
                .c4: .identified(vendorID: 0x0a1b, productID: 0x2c3d, brandClass: 7, modelCode: 3),
            ], rawFields: [:], switches: [.c1: true, .c2: true, .c3: true, .c4: true, .usbA: true])
        case "restart-paused", "outcome-off":
            // Every switch on, except C2 for the ignored turn-on.
            ChargerDetails(faultBits: 0, identitySupport: 6, identities: [
                .c1: .identified(vendorID: 0x0a1b, productID: 0x2c3d, brandClass: 7, modelCode: 3),
                .c2: .nothingAttached, .c3: .identifying, .c4: .nothingAttached,
            ], rawFields: [:], switches: [.c1: true, .c2: state != "outcome-off", .c3: true, .c4: true, .usbA: true])
        default: nil
        }
    }
    static let syntheticCatalog = Data(#"{"brands": {"10": "Synthetic Brand Ten", "7": "Synthetic Brand"}, "devices": {"0A1B:2C3D": "Synthetic Desk Lamp"}, "schema": 1, "source": "synthetic snapshot catalog", "vendors": {}}"#.utf8)
    static func make(state: String, directory: URL) async throws -> Self {
        let empty = state == "signed-out" || state == "not-set-up"
        let store = StateStore(fileURL: directory.appending(path: "state.json", directoryHint: .notDirectory))
        let charger = ChargerInfo(serial: "synthetic-charger", model: "A2345", alias: "Desk charger", name: "Anker Prime")
        if !empty { try store.save(.init(charger: state == "choose-charger" ? nil : charger, closedInterval: .default, credentials: OnePasswordConfiguration(item: "Anker", vault: nil, country: "US").selection)) }
        let scheduler = SnapshotScheduler(), date = scheduler.date
        // The paused restart's backend reports the commanded switch once, then
        // stops replying; the outcome's backend ignores commands.
        let backend = SnapshotBackend(charger: charger, receivedAt: state == "stale" ? date.addingTimeInterval(-180) : date, details: details(for: state),
                                      followsCommandOnce: state == "restart-paused")
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
        // An explicit private temporary catalog; never the owner's runtime file.
        let catalogFile = directory.appending(path: "devices.json", directoryHint: .notDirectory)
        let catalog = DeviceCatalogStore(fileURL: catalogFile, seedURL: nil, scheduler: scheduler)
        if details(for: state) != nil { try PrivateFile.replace(catalogFile, with: syntheticCatalog, temporaryPrefix: ".snapshot-") }
        catalog.load()
        if state == "details" {
            // An invalid edit: the last good names stay and the panel reports the entry.
            try PrivateFile.replace(catalogFile, with: Data(#"{"brands": {}, "devices": {"0a1b:2c3d": ""}, "schema": 1, "vendors": {}}"#.utf8), temporaryPrefix: ".snapshot-")
            catalog.load()
            guard catalog.problem != nil, !catalog.catalog.brands.isEmpty else { fatalError("Synthetic catalog problem not reported") }
        }
        let detail = PortDetailState()
        if state == "expanded-named" {
            detail.toggle(.c1, NamingContext(monitor: monitor, store: catalog))
            guard detail.expanded == .c1 else { fatalError("Synthetic row not expanded") }
        }
        if state == "switches-off" {
            detail.toggle(.c2, NamingContext(monitor: monitor, store: catalog))
            guard detail.expanded == .c2 else { fatalError("Synthetic row not expanded") }
        }
        let naming = NamingContext(monitor: monitor, store: catalog)
        detail.now = { scheduler.date }
        switch state {
        case "armed":
            detail.toggle(.c4, naming)
            guard monitor.portControlBlock == nil, !detail.press(.turnOff, target: .c4, in: monitor.portControlGenerations, available: true),
                  detail.armedAction(in: monitor.portControlGenerations, available: true) != nil else { fatalError("Synthetic action not armed") }
        case "restart-paused":
            guard monitor.restartPort(.c1) else { fatalError("Synthetic restart refused") }
            for _ in 0..<10000 where monitor.portOperation?.pauseEnd == nil { await Task.yield() }
            guard monitor.portOperation?.pauseSecondsRemaining(at: scheduler.date) == Int(PortControlPolicy.restartPause) else { fatalError("Synthetic restart not paused") }
            detail.toggle(.c1, naming)
        case "outcome-off":
            guard monitor.turnPort(.c2, on: true) else { fatalError("Synthetic turn-on refused") }
            for _ in 0..<10000 where monitor.portOperation?.latestFreshReport != false { await Task.yield() }
            guard monitor.portOperation?.latestFreshReport == false else { fatalError("Synthetic off report not delivered") }
            // Past the confirmation deadline, the next reply still reports C2 off.
            scheduler.date = scheduler.date.addingTimeInterval(PortControlPolicy.confirmationDeadline)
            await backend.setReceivedAt(scheduler.date)
            monitor.refreshNow()
            for _ in 0..<10000 where monitor.portOutcome == nil { await Task.yield() }
            guard monitor.portOutcome?.kind == .stillOff else { fatalError("Synthetic outcome not reported") }
            detail.toggle(.c2, naming)
        default: break
        }
        return .init(monitor: monitor, catalog: catalog, detail: detail)
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
    var date = Date()
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
    private var receivedAt: Date
    private var details: ChargerDetails?
    /// Applies the first switch command to the reported switches, answers one
    /// more request, then stops replying.
    private let followsCommandOnce: Bool
    private var repliesLeft: Int?
    init(charger: ChargerInfo, receivedAt: Date, details: ChargerDetails?, followsCommandOnce: Bool = false) {
        self.charger = charger; self.receivedAt = receivedAt; self.details = details; self.followsCommandOnce = followsCommandOnce
    }
    func setReceivedAt(_ date: Date) { receivedAt = date }
    nonisolated var events: AsyncStream<BackendEvent> { output.subscribe() }
    func subscribeToEvents() async -> AsyncStream<BackendEvent> { output.subscribe() }
    func signIn(_ credentials: AnkerCredentials) async throws -> AccountSession { .init(authToken: "synthetic-token", userID: "synthetic-user", expiresAt: .distantFuture, nickname: "") }
    func restore(_ session: AccountSession, credentials: AnkerCredentials) async {}
    func listChargers() async throws -> [ChargerInfo] { [charger] }
    func connect(to charger: ChargerInfo) async throws {}
    func requestSnapshot() async throws {
        if let left = repliesLeft {
            guard left > 0 else { return }
            repliesLeft = left - 1
        }
        let readings = PortID.allCases.map { port in
            PortReading(port: port, active: port == .c4, voltageMilli: port == .c4 ? 20000 : 0,
                        currentMilli: port == .c4 ? 1490 : (port.rawValue.hasPrefix("c") ? 20 : 0), powerCenti: port == .c4 ? 4321 : 0)
        }
        replies += 1
        output.yield(.snapshot(.init(receivedAt: receivedAt, readings: readings, details: details),
                               ReceiveMark(connection: ConnectionEpoch(1), sequence: replies)))
    }
    private var replies: UInt64 = 0
    /// Recorded only; the snapshot renderer never sends a command to a charger.
    private(set) var switchCommands: [(target: PortSwitch, on: Bool)] = []
    func setPortSwitch(_ target: PortSwitch, on: Bool) async throws -> PortCommandReceipt {
        switchCommands.append((target, on))
        if followsCommandOnce, repliesLeft == nil, let current = details {
            var switches = current.switches; switches[target] = on
            details = ChargerDetails(faultBits: current.faultBits, identitySupport: current.identitySupport,
                                     identities: current.identities, rawFields: current.rawFields, switches: switches)
            repliesLeft = 1
        }
        return PortCommandReceipt(fence: ReceiveMark(connection: ConnectionEpoch(1), sequence: replies))
    }
    func commandFence() async throws -> PortCommandReceipt {
        PortCommandReceipt(fence: ReceiveMark(connection: ConnectionEpoch(1), sequence: replies))
    }
    func abortCommands() async {}
    func disconnect() async {}
}
