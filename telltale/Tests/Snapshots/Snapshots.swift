// Port: brew_version/Tests/Snapshots/Snapshots.swift, Snapshots and render, 579ebb7.
// Adaptation: Telltale's maintained-view inventory is spec section 13's panel states (quiet,
// alerting, lasting-shift prompt), rendered from seeded synthetic databases through the real
// LiveStore and PanelView, plus the dashboard's model view and collector problem state at the
// window's default width (Task 12), and Settings with an invalid Rules entry (Task 13).
// The Homebrew fixture and transport are replaced by SyntheticEnvironment; the login double is
// SnapshotLoginService.
import AppKit
import ServiceManagement
import SwiftUI
import UserNotifications
import TelltaleCore

// This entry exists only in the isolated renderer. No real database, collector, launchctl,
// notifications, windows on screen or native input.
@main struct Snapshots {
    static let states: [SyntheticEnvironment.Scene] = [.quiet, .alerting, .acknowledged, .shift, .twoProviders, .arrival]
    static let dashboardStates: [SyntheticEnvironment.Scene] = [.dashboard, .collectorProblem, .settings, .claudeDashboard, .providersNormal, .providersNotSetUp, .providersFormatProblem, .providersBackfilling]

    @MainActor static func main() async throws {
        _ = NSApplication.shared
        guard CommandLine.arguments.count == 2 else { fatalError("Expected private OS temporary output directory") }
        let home = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true).standardizedFileURL
        let temporary = FileManager.default.temporaryDirectory.standardizedFileURL.resolvingSymlinksInPath()
        guard home.resolvingSymlinksInPath().path.hasPrefix(temporary.path + "/"),
              (try FileManager.default.attributesOfItem(atPath: home.path)[.posixPermissions] as? NSNumber)?.intValue == 0o700 else { fatalError("Snapshots require a private OS temporary home") }
        // build.sh copies the bundled fonts into the home; the readouts must render in Barlow.
        guard Fonts.register(from: home.appendingPathComponent("Fonts", isDirectory: true)), Fonts.isAvailable else {
            fatalError("Bundled fonts did not register")
        }
        var heights: [String: CGFloat] = [:]
        for dark in [false, true] {
            for state in states {
                let directory = home.appendingPathComponent("fixture-\(state.rawValue)-\(dark)")
                let model = try await makeModel(state, home: directory)
                try expect(state, model.store)
                let label = "\(state.rawValue)-\(dark ? "dark" : "light")"
                let size = try render(AnyView(PanelView(model: model, openSettings: {}, openDashboard: {}, openProvider: { _, _ in })), dark: dark, to: home.appendingPathComponent(label + ".png"))
                heights[label] = size.height
            }
            let palette = dark ? "dark" : "light"
            guard heights["quiet-\(palette)"]! < heights["alerting-\(palette)"]!, heights["quiet-\(palette)"]! < heights["shift-\(palette)"]! else {
                fatalError("Quiet panel does not hug its content")
            }
        }
        try await renderDashboards(home: home)
        let pngs = try FileManager.default.contentsOfDirectory(at: home, includingPropertiesForKeys: nil).filter { $0.pathExtension == "png" }
        guard pngs.count == 28 else { fatalError("Expected twenty-eight PNGs") }
        print("Validated twelve maintained panel PNGs (quiet, alerting, acknowledged, lasting-shift prompt, two providers, arrival), both appearances, content-hugging quiet state.")
        print("Validated sixteen maintained dashboard PNGs (model views, collector, settings and four provider states), both appearances, Barlow Semi Condensed registered.")
    }

    /// The seeded scene's snapshot carries what its PNG is meant to show.
    @MainActor private static func expect(_ state: SyntheticEnvironment.Scene, _ live: LiveStore) throws {
        let snapshot = live.snapshot
        guard snapshot.checkedAt != nil, snapshot.models.count == ((state == .twoProviders || state == .arrival) ? 4 : 2) else { fatalError("\(state): unexpected model rows") }
        switch state {
        case .quiet:
            guard snapshot.alerts.isEmpty, snapshot.shift == nil, snapshot.models.allSatisfy({ $0.color == nil }) else { fatalError("quiet: expected no alerts, rows or shift prompt in color") }
        case .alerting:
            guard snapshot.alerts.count == 2, snapshot.lamps[.speed] == .amber, snapshot.lamps[.load] == .amber,
                  snapshot.models.map(\.color) == [.amber, nil] else { fatalError("alerting: expected Speed and Load amber and an amber Example row") }
        case .acknowledged:
            let episode = try live.read { store, _ in try store.openEpisodes().first { $0.rule == RuleID.failedTurns.rawValue } }!!
            let detail = try FailedTurnEpisodeDetail.decode(episode.detail)!
            let saved = try live.read { store, _ in try store.value(.alertAcknowledgements)[Acknowledgements.key(episode)] }!!
            let first = snapshot.alerts.first!
            guard snapshot.alerts.count == 3, snapshot.alerts.dropFirst().allSatisfy({ $0.acknowledgedAt != nil }),
                  first.acknowledgedAt == nil, first.failedTurns == detail.failures.count + detail.priorCount,
                  first.failedTurns! > saved.failedTurns!, first.detail == Copy.failedTurnsTotal(count: first.failedTurns!, since: episode.onset, calendar: SyntheticEnvironment.calendar),
                  snapshot.attention == .red else { fatalError("acknowledged: expected acknowledged seed alerts and re-armed failed turn") }
        case .shift:
            guard snapshot.alerts.isEmpty, snapshot.shift?.days == 3, snapshot.shiftText != nil else { fatalError("shift: expected a 3-day lasting-shift prompt") }
        case .acceptance:
            guard !snapshot.alerts.isEmpty, snapshot.shift != nil else { fatalError("acceptance: expected alerts and a shift prompt") }
        case .dashboard:
            guard snapshot.alerts.count == 2, snapshot.lamps[.speed] == .amber else { fatalError("dashboard: expected the alerting panel's alerts") }
        case .collectorProblem:
            guard snapshot.collector == .red, snapshot.alerts.isEmpty else { fatalError("collector problem: expected a red Collector lamp and no alerts") }
        case .settings:
            guard snapshot.alerts.isEmpty else { fatalError("settings: expected the quiet scene") }
        case .twoProviders:
            guard Set(snapshot.models.map(\.provider)).count == 2, Set(snapshot.models.map(\.name)).count == 4 else { fatalError("two providers: expected distinct names") }
        case .arrival:
            guard snapshot.arrivals.count == 1, snapshot.arrivals[0].provider == .claude else { fatalError("arrival: expected Claude note") }
        case .claudeDashboard, .providersNormal, .providersNotSetUp, .providersFormatProblem, .providersBackfilling:
            fatalError("dashboard scene is not a panel scene")
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
        let colors = try checkPixels(bitmap, destination: destination)
        try data.write(to: destination)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: destination.path)
        print("\(destination.path) (\(Int(size.width)) × \(Int(size.height)) pt; \(colors) colors)")
        window.contentView = nil
        return size
    }

    /// The dashboard window at its default width: the model view with its whole scroll content,
    /// and the collector view's problem state (spec section 13).
    @MainActor private static func renderDashboards(home: URL) async throws {
        for dark in [false, true] {
            for state in dashboardStates {
                let directory = home.appendingPathComponent("fixture-\(state.rawValue)-\(dark)")
                let model = try await makeDashboard(state, home: directory)
                expectDashboard(state, model)
                let name = switch state { case .dashboard: "dashboard"; case .claudeDashboard: "claude-dashboard"; case .settings: "settings"; case .collectorProblem: "collector-problem"; default: state.rawValue }
                let label = "\(name)-\(dark ? "dark" : "light")"
                // The model view and Settings scroll inside the window; render the window tall enough to
                // show all of it, so the PNG can be compared with the mockup's full page.
                var height = DashboardWindowController.defaultSize.height
                let section: AnyView? = switch state {
                case .dashboard, .claudeDashboard: AnyView(ModelView(model: model))
                case .settings, .providersNormal, .providersNotSetUp, .providersFormatProblem, .providersBackfilling: AnyView(SettingsView(model: model.settings))
                default: nil
                }
                if let section {
                    let content = NSHostingView(rootView: section
                        .padding(.horizontal, 22).padding(.top, 18).padding(.bottom, 24)
                        .frame(width: DashboardWindowController.defaultSize.width - 201))
                    height = max(height, content.fittingSize.height.rounded(.up))
                }
                let size = NSSize(width: DashboardWindowController.defaultSize.width, height: height)
                try renderWindow(AnyView(DashboardView(model: model)), size: size, dark: dark, to: home.appendingPathComponent(label + ".png"))
            }
        }
    }

    /// The seeded scene's dashboard carries what its PNG is meant to show.
    @MainActor private static func expectDashboard(_ state: SyntheticEnvironment.Scene, _ model: DashboardModel) {
        switch state {
        case .dashboard:
            guard let detail = model.detail, model.workload != nil, detail.dots.count >= 100, detail.failures.count == 3, detail.incidents.count == 1,
                  detail.dots.contains(where: { $0.color == .blue }), detail.dots.contains(where: { $0.color == .red }),
                  Set(model.feed.map(\.kind)).isSuperset(of: [.slowdown, .speedup, .failedTurns, .statusPost, .disconnects, .largePrompts])
            else { fatalError("dashboard: expected 14 days of dots with a fast spell and a slow morning, failures, an incident and events") }
        case .collectorProblem:
            let collector = model.collector
            guard collector.lamps.map(\.state) == [.green, .green, .red, .green], collector.problems.count == 1, !collector.showsRepair,
                  collector.logLines.count == 6, collector.logLines.filter(\.isError).count == 1,
                  collector.facts.map(\.label) == ["Runs", "Last run", "Next run", "Last success", "Job label"]
            else { fatalError("collector problem: expected Last run red, one problem, six log lines and the run facts") }
        case .settings:
            let settings = model.settings
            let rows = settings.componentGroups.first?.rows ?? []
            guard settings.databaseReady, settings.canManage, settings.parameterErrors == [.slowerClearBand: [Copy.clearBandError]],
                  settings.text(.slowerClearBand) == "15", rows.count == 7, rows.filter(\.missing).count == 4, settings.login.enabled
            else { fatalError("settings: expected an invalid clear band, the component checklist with four missing names and Open at login on") }
        case .claudeDashboard:
            guard model.selectedModel?.provider == .claude, model.workload?.hasFastMode == true,
                  model.sidebar.first(where: { $0.provider == .claude })?.isBackfilling == true else { fatalError("Claude dashboard: expected fast mode and backfill") }
        case .providersNormal, .providersNotSetUp, .providersFormatProblem, .providersBackfilling:
            guard let provider = model.settings.providers.first(where: { $0.provider == .claude }) else { fatalError("missing Claude provider") }
            switch (state, provider.state) {
            case (.providersNormal, .normal), (.providersNotSetUp, .notSetUp), (.providersFormatProblem, .formatProblem), (.providersBackfilling, .backfilling): break
            default: fatalError("unexpected provider state: \(provider.state)")
            }
        default:
            fatalError("\(state) is not a dashboard scene")
        }
    }

    /// A seeded scene's dashboard, read through the maintained LiveStore with synthetic health. The
    /// collector view gets a recording launchctl double and Settings a login-item double; the only
    /// input is Settings' invalid clear-band entry, which stores nothing.
    @MainActor private static func makeDashboard(_ state: SyntheticEnvironment.Scene, home: URL) async throws -> DashboardModel {
        let panel = try await makeModel(state, home: home)
        let paths = SyntheticEnvironment.paths(home: home)
        let now = SyntheticEnvironment.snapshotNow
        let calendar = SyntheticEnvironment.calendar
        let collector = CollectorViewModel(
            live: panel.store, actions: panel.actions, manager: LaunchAgentManager(paths: paths, uid: 501, runner: SyntheticCommandRunner()),
            currentExecutable: home.appendingPathComponent("Telltale"), canManage: true, paths: paths, calendar: calendar, now: { now },
            reveal: { _ in })
        let sources = [.claudeDashboard, .providersNormal, .providersNotSetUp, .providersFormatProblem, .providersBackfilling].contains(state) ? SyntheticEnvironment.twoSources : SyntheticEnvironment.sources
        let settings = SettingsModel(live: panel.store, collector: collector, sources: sources, statusSummaries: SyntheticEnvironment.statusSummaries, login: LoginItem(service: SnapshotLoginService()))
        let model = DashboardModel(
            live: panel.store, panel: panel, collector: collector, settings: settings, sources: sources, calendar: calendar, now: { now })
        switch state {
        case .dashboard: model.select(.model(.codex, SyntheticEnvironment.example))
        case .claudeDashboard: model.select(.model(.claude, SyntheticEnvironment.claude))
        case .providersNormal, .providersNotSetUp, .providersFormatProblem, .providersBackfilling: model.select(.settings)
        case .settings:
            model.select(.settings)
            // The slower rule's clear band equal to its trigger: shown with its message, not saved.
            settings.edit(.slowerClearBand, "15")
        default: model.select(.collector)
        }
        return model
    }

    /// Renders a fixed-size window's content (the dashboard owns its viewport) and checks its pixels.
    @MainActor private static func renderWindow(_ root: AnyView, size: NSSize, dark: Bool, to destination: URL) throws {
        let appearance = NSAppearance(named: dark ? .darkAqua : .aqua)!
        let view = NSHostingView(rootView: root.environment(\.colorScheme, dark ? .dark : .light))
        view.sizingOptions = []
        view.appearance = appearance
        let window = NSWindow(contentRect: NSRect(origin: NSPoint(x: -10000, y: -10000), size: size), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.appearance = appearance
        window.contentView = view
        view.frame = NSRect(origin: .zero, size: size)
        for _ in 0..<8 {
            view.layoutSubtreeIfNeeded()
            RunLoop.current.run(until: Date().addingTimeInterval(0.025))
        }
        guard view.frame.size == size else { fatalError("Invalid dashboard layout \(view.frame.size), expected \(size)") }
        window.displayIfNeeded()
        view.display()
        guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { fatalError("Cannot allocate image") }
        appearance.performAsCurrentDrawingAppearance {
            view.cacheDisplay(in: view.bounds, to: bitmap)
        }
        guard let data = bitmap.representation(using: .png, properties: [:]) else { fatalError("Cannot encode PNG") }
        let colors = try checkPixels(bitmap, destination: destination)
        try data.write(to: destination)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: destination.path)
        print("\(destination.path) (\(Int(size.width)) × \(Int(size.height)) pt; \(colors) colors)")
        window.contentView = nil
    }

    /// Verifies actual bitmap pixels, not just an allocated PNG or alpha plane; returns the colors seen.
    private static func checkPixels(_ bitmap: NSBitmapImageRep, destination: URL) throws -> Int {
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
        return colors.count
    }

    /// A seeded scene read through the maintained LiveStore, with synthetic health and no watch.
    @MainActor private static func makeModel(_ state: SyntheticEnvironment.Scene, home: URL) async throws -> PanelModel {
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        let now = SyntheticEnvironment.snapshotNow
        let calendar = SyntheticEnvironment.calendar
        let paths = try SyntheticEnvironment.seed(state, home: home, now: now, calendar: calendar)
        let health = SyntheticEnvironment.health(state)
        let live = LiveStore(
            paths: paths, sources: (state == .twoProviders || state == .arrival || state == .claudeDashboard) ? SyntheticEnvironment.twoSources : SyntheticEnvironment.sources, calendar: calendar, now: { now }, health: { health }, pollInterval: .seconds(3_600),
            watchFiles: false)
        await live.refresh()
        let actions = UserActions(paths: paths, calendar: calendar, now: { now }, kickstart: {})
        return PanelModel(store: live, actions: actions, notifier: UserNotifier(service: SnapshotNotifications()), calendar: calendar)
    }
}

/// Open at login, registered: Settings shows the switch on. Nothing reaches the system login service.
@MainActor private struct SnapshotLoginService: LoginService {
    var status: LoginStatus { .enabled }
    func register() throws {}
    func unregister() throws {}
    func openSettings() {}
}

@MainActor private struct SnapshotNotifications: NotificationService {
    func authorizationStatus() async -> UNAuthorizationStatus { .authorized }
    func requestAuthorization() async throws -> Bool { true }
    func post(_ request: UNNotificationRequest) async throws {}
    func delivered() async -> [UNNotification] { [] }
    func removeDelivered(identifiers: [String]) {}
}
