// Port: brew_version/Tests/Snapshots/Snapshots.swift, Snapshots and render, 579ebb7.
// Adaptation: Telltale's maintained-view inventory is spec section 13's panel states (quiet,
// alerting, lasting-shift prompt), rendered from seeded synthetic databases through the real
// LiveStore and PanelView; dashboard, collector view and Settings join it with Tasks 12 and 13.
// The Homebrew fixture, transport and login doubles are replaced by SyntheticEnvironment.
import AppKit
import SwiftUI
import UserNotifications
import TelltaleCore

// This entry exists only in the isolated renderer. No real database, collector, launchctl,
// notifications, windows on screen or native input.
@main struct Snapshots {
    static let states: [SyntheticEnvironment.Scene] = [.quiet, .alerting, .shift]

    @MainActor static func main() async throws {
        _ = NSApplication.shared
        guard CommandLine.arguments.count == 2 else { fatalError("Expected private OS temporary output directory") }
        let home = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true).standardizedFileURL
        let temporary = FileManager.default.temporaryDirectory.standardizedFileURL.resolvingSymlinksInPath()
        guard home.resolvingSymlinksInPath().path.hasPrefix(temporary.path + "/"),
              (try FileManager.default.attributesOfItem(atPath: home.path)[.posixPermissions] as? NSNumber)?.intValue == 0o700 else { fatalError("Snapshots require a private OS temporary home") }
        var heights: [String: CGFloat] = [:]
        for dark in [false, true] {
            for state in states {
                let directory = home.appendingPathComponent("fixture-\(state.rawValue)-\(dark)")
                let model = try await makeModel(state, home: directory)
                expect(state, model.store.snapshot)
                let label = "\(state.rawValue)-\(dark ? "dark" : "light")"
                let size = try render(AnyView(PanelView(model: model, openSettings: {}, openDashboard: {})), dark: dark, to: home.appendingPathComponent(label + ".png"))
                heights[label] = size.height
            }
            let palette = dark ? "dark" : "light"
            guard heights["quiet-\(palette)"]! < heights["alerting-\(palette)"]!, heights["quiet-\(palette)"]! < heights["shift-\(palette)"]! else {
                fatalError("Quiet panel does not hug its content")
            }
        }
        let pngs = try FileManager.default.contentsOfDirectory(at: home, includingPropertiesForKeys: nil).filter { $0.pathExtension == "png" }
        guard pngs.count == 6 else { fatalError("Expected six PNGs") }
        print("Validated six maintained panel PNGs (quiet, alerting, lasting-shift prompt), both appearances, content-hugging quiet state.")
    }

    /// The seeded scene's snapshot carries what its PNG is meant to show.
    @MainActor private static func expect(_ state: SyntheticEnvironment.Scene, _ snapshot: PanelSnapshot) {
        guard snapshot.checkedAt != nil, snapshot.models.count == 2 else { fatalError("\(state): expected a checked time and two model rows") }
        switch state {
        case .quiet:
            guard snapshot.alerts.isEmpty, snapshot.shift == nil, snapshot.models.allSatisfy({ $0.color == nil }) else { fatalError("quiet: expected no alerts, rows or shift prompt in color") }
        case .alerting:
            guard snapshot.alerts.count == 2, snapshot.lamps[.speed] == .amber, snapshot.lamps[.load] == .amber,
                  snapshot.models.map(\.color) == [.amber, nil] else { fatalError("alerting: expected Speed and Load amber and an amber Example row") }
        case .shift:
            guard snapshot.alerts.isEmpty, snapshot.shift?.days == 3, snapshot.shiftText != nil else { fatalError("shift: expected a 3-day lasting-shift prompt") }
        case .acceptance:
            guard !snapshot.alerts.isEmpty, snapshot.shift != nil else { fatalError("acceptance: expected alerts and a shift prompt") }
        }
    }

    @MainActor private static func render(_ root: AnyView, dark: Bool, to destination: URL) throws -> NSSize {
        let width = PanelView.width
        let appearance = NSAppearance(named: dark ? .darkAqua : .aqua)!
        // An offscreen content capture has no panel compositor behind its clear
        // pixels. Supply the native material only at this rendering boundary.
        let view = NSHostingView(rootView: root.background(.regularMaterial).environment(\.colorScheme, dark ? .dark : .light))
        view.appearance = appearance
        let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: width, height: 560), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.appearance = appearance
        window.backgroundColor = .windowBackgroundColor
        window.contentView = view
        // Rendering does not order the offscreen window onto the display.
        for _ in 0..<8 {
            view.frame.size = view.fittingSize
            view.layoutSubtreeIfNeeded()
            RunLoop.current.run(until: Date().addingTimeInterval(0.025))
        }
        let size = view.fittingSize
        guard abs(size.width - width) < 0.5, size.height > 100, size.height <= 700, size.height == size.height.rounded() else {
            fatalError("Invalid maintained layout \(size), expected width \(width) and whole-point height")
        }
        view.frame.size = size
        window.setContentSize(size)
        view.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
        view.display()
        guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { fatalError("Cannot allocate image") }
        appearance.performAsCurrentDrawingAppearance {
            view.cacheDisplay(in: view.bounds, to: bitmap)
        }
        guard let data = bitmap.representation(using: .png, properties: [:]) else { fatalError("Cannot encode PNG") }
        // Verify actual bitmap pixels, not just an allocated PNG or alpha plane.
        var colors: Set<UInt32> = []
        var opaque = 0
        for y in stride(from: 0, to: bitmap.pixelsHigh, by: 3) {
            for x in stride(from: 0, to: bitmap.pixelsWide, by: 3) {
                if let color = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB), color.alphaComponent > 0.1 {
                    opaque += 1
                    let value = UInt32(color.redComponent * 255) << 16 | UInt32(color.greenComponent * 255) << 8 | UInt32(color.blueComponent * 255)
                    colors.insert(value)
                }
            }
        }
        guard colors.count > 25, opaque > 100 else { fatalError("Blank rendering: \(colors.count) colors, \(opaque) painted pixels, \(destination.path)") }
        try data.write(to: destination)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: destination.path)
        print("\(destination.path) (\(Int(size.width)) × \(Int(size.height)) pt; \(colors.count) colors)")
        window.contentView = nil
        return size
    }

    /// A seeded scene read through the maintained LiveStore, with synthetic health and no watch.
    @MainActor private static func makeModel(_ state: SyntheticEnvironment.Scene, home: URL) async throws -> PanelModel {
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        let now = SyntheticEnvironment.snapshotNow
        let calendar = SyntheticEnvironment.calendar
        let paths = try SyntheticEnvironment.seed(state, home: home, now: now, calendar: calendar)
        let health = SyntheticEnvironment.health(state)
        let live = LiveStore(
            paths: paths, sources: SyntheticEnvironment.sources, calendar: calendar, now: { now }, health: { health }, pollInterval: .seconds(3_600),
            watchFiles: false)
        await live.refresh()
        let actions = UserActions(paths: paths, calendar: calendar, now: { now }, kickstart: {})
        return PanelModel(store: live, actions: actions, notifier: UserNotifier(service: SnapshotNotifications()), calendar: calendar)
    }
}

@MainActor private struct SnapshotNotifications: NotificationService {
    func authorizationStatus() async -> UNAuthorizationStatus { .authorized }
    func requestAuthorization() async throws -> Bool { true }
    func post(_ request: UNNotificationRequest) async throws {}
    func delivered() async -> [UNNotification] { [] }
}
