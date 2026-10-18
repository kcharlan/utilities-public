import AppKit
import SwiftUI
import ServiceManagement
import UserNotifications
import BrewVersionCore

// This entry exists only in the isolated renderer. No real inventory, state,
// notifications, login registration, HTTP, windows on screen or native input.
@main struct Snapshots {
    @MainActor static func main() async throws {
        _ = NSApplication.shared
        guard CommandLine.arguments.count == 2 else { fatalError("Expected private OS temporary output directory") }
        let home = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true).standardizedFileURL
        let temporary = FileManager.default.temporaryDirectory.standardizedFileURL.resolvingSymlinksInPath()
        guard home.resolvingSymlinksInPath().path.hasPrefix(temporary.path + "/"),
              (try FileManager.default.attributesOfItem(atPath: home.path)[.posixPermissions] as? NSNumber)?.intValue == 0o700 else { fatalError("Snapshots require a private OS temporary home") }
        var heights: [String: CGFloat] = [:]
        for dark in [false, true] {
            for state in ["empty", "watching", "other-updates", "search-results", "suggestions", "error", "settings", "tap-watching", "tap-suggestions", "scrolled"] {
                let directory = home.appendingPathComponent("fixture-\(state)-\(dark)")
                let fixture = try await makeFixture(state: state, home: directory)
                let view: AnyView
                if state == "settings" {
                    view = AnyView(SettingsView(controller: fixture.controller, notifier: fixture.notifier, login: LoginItem(service: SnapshotLogin())))
                } else {
                    view = AnyView(PopoverView(controller: fixture.controller, notifier: fixture.notifier, openSettings: {}, focusGeneration: UUID(), search: fixture.input, selection: fixture.selection))
                }
                let label = "\(state)-\(dark ? "dark" : "light")"
                let size = try render(view, width: state == "settings" ? 460 : 340, dark: dark, to: home.appendingPathComponent(label + ".png"),
                                      scrollOffset: state == "scrolled" ? 260 : nil)
                heights[label] = size.height
            }
            // Exercise the maintained full popover with an unbounded list too.
            let long = try await makeFixture(state: "long", home: home.appendingPathComponent("fixture-long-\(dark)"))
            let size = try render(AnyView(PopoverView(controller: long.controller, notifier: long.notifier, openSettings: {}, focusGeneration: UUID())), width: 340, dark: dark, to: nil)
            guard size.height <= 560, size.height > 400 else { fatalError("Long list lost its bounded viewport: \(size)") }
            let warningLong = try await makeFixture(state: "long-warning", home: home.appendingPathComponent("fixture-long-warning-\(dark)"))
            let warningSize = try render(AnyView(PopoverView(controller: warningLong.controller, notifier: warningLong.notifier, openSettings: {}, focusGeneration: UUID())), width: 340, dark: dark, to: nil)
            guard warningSize.height <= 560, warningSize.height > 400 else { fatalError("Wrapped notification warning displaced the footer: \(warningSize)") }
            let palette = dark ? "dark" : "light"
            guard heights["empty-\(palette)"]! < heights["watching-\(palette)"]!, heights["empty-\(palette)"]! < 300 else { fatalError("Empty popover does not hug content") }
        }
        let pngs = try FileManager.default.contentsOfDirectory(at: home, includingPropertiesForKeys: nil).filter { $0.pathExtension == "png" }
        guard pngs.count == 20 else { fatalError("Expected twenty PNGs") }
        print("Validated twenty maintained-view PNGs, both appearances, content-hugging empty state, bounded long lists and pinned list headers.")
    }

    @MainActor private static func render(_ root: AnyView, width: CGFloat, dark: Bool, to destination: URL?, scrollOffset: CGFloat? = nil) throws -> NSSize {
        let appearance = NSAppearance(named: dark ? .darkAqua : .aqua)!
        // An offscreen content capture has no popover compositor behind its clear
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
        guard abs(size.width - width) < 0.5, size.height > 100, size.height <= (width == 460 ? 700 : 560) else { fatalError("Invalid maintained layout \(size), expected width \(width)") }
        view.frame.size = size
        window.setContentSize(size)
        view.layoutSubtreeIfNeeded()
        for scroll in nativeScrolls(view) {
            guard scroll.frame.height > 0, scroll.frame.width <= width + 0.5 else { fatalError("Collapsed or horizontally clipped scroll viewport") }
            if let document = scroll.documentView {
                guard document.frame.width <= scroll.contentView.bounds.width + 0.5 else { fatalError("Horizontally clipped package content") }
            }
        }
        // A scrolled list shows its section header pinned above the rows beneath it.
        if let scrollOffset, let list = nativeScrolls(view).first {
            list.contentView.scroll(to: NSPoint(x: 0, y: scrollOffset))
            list.reflectScrolledClipView(list.contentView)
            view.layoutSubtreeIfNeeded()
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
            view.layoutSubtreeIfNeeded()
        }
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
        if let destination { try data.write(to: destination) }
        guard colors.count > 25, opaque > 100 else { fatalError("Blank rendering: \(colors.count) colors, \(opaque) painted pixels, \(destination?.path ?? "long-list")") }
        if let destination {
            try data.write(to: destination)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: destination.path)
            print("\(destination.path) (\(Int(size.width)) × \(Int(size.height)) pt; \(colors.count) colors)")
        }
        window.contentView = nil
        return size
    }
    @MainActor private static func nativeScrolls(_ view: NSView) -> [NSScrollView] {
        if let scroll = view as? NSScrollView { return [scroll] }
        return view.subviews.flatMap(nativeScrolls)
    }

    @MainActor private static func makeFixture(state: String, home: URL) async throws -> Fixture {
        let service = SnapshotTransport()
        let notificationFailure = state == "error" || state == "long-warning"
        let notifier = UserNotifier(service: SnapshotNotifications(failAuthorization: notificationFailure))
        if notificationFailure { await notifier.requestAuthorization() }
        let store = WatchStore(fileURL: home.appendingPathComponent("state.json"))
        var saved = AppState.initial
        saved.lastCheck = Date(timeIntervalSince1970: 1_700_000_000)
        saved.showOtherUpdates = ["other-updates", "tap-watching", "scrolled"].contains(state)
        saved.otherUpdatesCollapsed = false
        if !["empty", "settings", "suggestions", "search-results"].contains(state) {
            saved.watched = ((state.hasPrefix("long") || state == "scrolled") ? (0..<35).map { "synthetic-item-\($0)" } : ["synthetic-a", "synthetic-b", "synthetic-c"]).enumerated().map { index, text in
                let kind: PackageKind = index == 1 ? .cask : .formula
                let listing = Listing(name: PackageName(text)!, kind: kind, version: index == 2 ? "1.0.0" : "1.0.1")
                return WatchEntry(name: listing.name, kind: kind, lastListing: listing,
                    installed: index == 1 ? nil : InstalledVersion(version: "1.0.0", source: .cellar),
                    lastSeenRelease: ReleaseID(Listing(name: listing.name, kind: kind, version: "1.0.0")),
                    unseenRelease: index == 1, lastError: state == "error" && index == 2 ? "Couldn't reach Homebrew. Check your connection and try again." : nil)
            }
        }
        if state == "tap-watching" {
            let name = PackageName("synthetic-owner/synthetic-tap/synthetic-tool")!
            let listing = Listing(name: name, kind: .formula, version: "4.5.6")
            saved.watched = [saved.watched[0], WatchEntry(name: name, kind: .formula, lastListing: listing,
                installed: .init(version: "1.0-synthetic", source: .cellar), unseenRelease: true),
                WatchEntry(name: PackageName("synthetic-owner/synthetic-tap/synthetic-app")!, kind: .cask,
                           lastError: "synthetic-owner/synthetic-tap is no longer tapped.")]
        }
        if state == "tap-suggestions" { saved.watched = [] }
        try store.save(saved)
        let prefix = home.appendingPathComponent("synthetic-prefix")
        let keg = prefix.appendingPathComponent("Cellar/synthetic-d/1.0.0")
        try FileManager.default.createDirectory(at: keg, withIntermediateDirectories: true)
        try Data(#"{"source":{"tap":"homebrew/core"}}"#.utf8).write(to: keg.appendingPathComponent("INSTALL_RECEIPT.json"))
        if state == "tap-suggestions" {
            let tap = prefix.appendingPathComponent("Library/Taps/synthetic-owner/homebrew-synthetic-tap")
            for path in [".git", "Formula", "Casks"] { try FileManager.default.createDirectory(at: tap.appendingPathComponent(path), withIntermediateDirectories: true) }
            try Data("[remote \"origin\"]\nurl = https://github.com/synthetic-owner/homebrew-synthetic-tap.git\n".utf8).write(to: tap.appendingPathComponent(".git/config"))
            for path in ["Formula/synthetic-tool.rb", "Casks/synthetic-app.rb"] { try Data("# synthetic discovery".utf8).write(to: tap.appendingPathComponent(path)) }
            let installed = prefix.appendingPathComponent("Cellar/synthetic-tool/1.0-synthetic")
            try FileManager.default.createDirectory(at: installed, withIntermediateDirectories: true)
            try Data(#"{"source":{"tap":"synthetic-owner/synthetic-tap"}}"#.utf8).write(to: installed.appendingPathComponent("INSTALL_RECEIPT.json"))
        }
        let prefixes = HomebrewPrefix.detectAll(candidates: [prefix])
        let controller = WatchController(transport: service, installed: InstalledReader(prefixes: prefixes, applicationDirectories: [], tappedTaps: { TapIndex.scan(prefixes: prefixes).taps }), store: store, notifier: notifier, catalogClient: CatalogClient(transport: service, cacheDirectory: home.appendingPathComponent("cache")), taps: { TapIndex.scan(prefixes: prefixes) })
        if ["other-updates", "suggestions", "tap-suggestions", "scrolled"].contains(state) { await controller.refreshCatalogIfDue() }
        let input = SearchInput()
        if state == "search-results" { input.text = "synthetic-a synthetic-b synthetic-c"; await input.lookup(controller: controller) }
        if state == "suggestions" || state == "tap-suggestions" { input.text = "synthetic"; await input.lookup(controller: controller) }
        let selection = WatchRowSelection()
        if state == "watching", let name = saved.watched.first?.name { selection.select(name) }
        return Fixture(controller: controller, notifier: notifier, input: input, selection: selection)
    }
}
private struct Fixture {
    let controller: WatchController
    let notifier: UserNotifier
    let input: SearchInput
    let selection: WatchRowSelection
}
private actor SnapshotTransport: HTTPTransport {
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        let path = url.path
        if path == "/api/formula.json" { return .init(status: 200, body: Data(#"[{"name":"synthetic-a","versions":{"stable":"1.0.1"}},{"name":"synthetic-c","versions":{"stable":"1.0.0"}},{"name":"synthetic-d","versions":{"stable":"1.0.1"}}]"#.utf8)) }
        if path == "/api/cask.json" { return .init(status: 200, body: Data(#"[{"token":"synthetic-b","version":"1.0.1"}]"#.utf8)) }
        if path.contains("synthetic-b") && path.contains("/cask/") { return .init(status: 200, body: Data(#"{"version":"1.0.1"}"#.utf8)) }
        if ["synthetic-a.json", "synthetic-c.json"].contains(url.lastPathComponent), path.contains("/formula/") { return .init(status: 200, body: Data(#"{"versions":{"stable":"1.0.1"}}"#.utf8)) }
        return .init(status: 404, body: Data())
    }
}
@MainActor private struct SnapshotNotifications: NotificationService {
    var failAuthorization = false
    func authorizationStatus() async -> UNAuthorizationStatus { failAuthorization ? .notDetermined : .authorized }
    func requestAuthorization() async throws -> Bool {
        if failAuthorization { throw SnapshotAuthorizationFailure() }
        return true
    }
    func post(_ request: UNNotificationRequest) async throws {}
}
private struct SnapshotAuthorizationFailure: LocalizedError {
    var errorDescription: String? { "Synthetic authorization was refused. Open System Settings, choose Notifications, select Brew Version, enable notifications, then retry." }
}
@MainActor private struct SnapshotLogin: LoginService {
    var status: SMAppService.Status { .notRegistered }
    func register() throws {}
    func unregister() throws {}
    func openSettings() {}
}
