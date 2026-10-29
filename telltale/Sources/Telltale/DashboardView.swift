import AppKit
import Observation
import SwiftUI
import TelltaleCore

/// What the dashboard window shows (spec section 9.2): the sidebar, the selected model's detail,
/// workload and events, the collector view and Settings. Everything is read through the panel's
/// read-only `LiveStore`, and every write goes through `UserActions` (ruling R27).
@MainActor @Observable final class DashboardModel {
    /// One provider in the sidebar: its models, or why there are none.
    struct SidebarGroup: Equatable, Identifiable {
        enum State: Equatable {
            case models([SidebarModel])
            /// The source reported it can't read its data (`SetupState.notSetUp`).
            case notSetUp
            /// Set up, with no stored response yet.
            case empty
            /// Stored models, none with a response in the sidebar window (`ModelDetail.sidebarWindow`).
            case idle
        }
        var provider: ProviderID
        var name: String
        var state: State
        var isBackfilling = false
        var id: ProviderID { provider }
    }

    struct SidebarModel: Equatable, Identifiable {
        var provider: ProviderID
        var model: String
        var name: String
        /// The model's lamp in the panel, when it is in a speed episode.
        var color: LampColor?
        var id: String { "\(provider.rawValue)/\(model)" }
    }

    /// How many entries the event list shows (plan call).
    static let feedLimit = 50

    @ObservationIgnored let live: LiveStore
    @ObservationIgnored let panel: PanelModel
    @ObservationIgnored let collector: CollectorViewModel
    @ObservationIgnored let settings: SettingsModel
    @ObservationIgnored let sources: [SourceSummary]
    @ObservationIgnored let calendar: Calendar
    @ObservationIgnored let now: @MainActor () -> Date

    private(set) var selection: DashboardSection?
    var range: ChartRange = .twoWeeks {
        didSet { if range != oldValue { load() } }
    }
    private(set) var sidebar: [SidebarGroup] = []
    private(set) var detail: ModelDetail?
    private(set) var workload: Workload?
    private(set) var feed: [FeedEvent] = []
    private(set) var loadError: String?
    /// The Accept as usual… picker's date while it is open (spec section 8's picker contract).
    var acceptingSince: Date?
    /// An older acceptance whose Undo waits for confirmation.
    private(set) var pendingUndo: FeedEvent?
    /// Whether the dashboard window is open. While it is closed, store changes reread nothing.
    var isVisible = false

    init(
        live: LiveStore, panel: PanelModel, collector: CollectorViewModel, settings: SettingsModel, sources: [SourceSummary],
        calendar: Calendar = .current, now: @escaping @MainActor () -> Date = Date.init
    ) {
        self.live = live
        self.panel = panel
        self.collector = collector
        self.settings = settings
        self.sources = sources
        self.calendar = calendar
        self.now = now
    }

    /// Open dashboard's landing section before anything was chosen: the first model, or the
    /// collector before the first run has stored one. Rereads the sidebar to find it.
    func defaultSection() -> DashboardSection {
        loadSidebar()
        for group in sidebar {
            if case .models(let models) = group.state, let first = models.first { return .model(first.provider, first.model) }
        }
        return .collector
    }

    /// The status-page incidents the selected model's shift prompt links to (ruling R31).
    var shiftIncidents: [IncidentLink] { detail?.shift?.incidents ?? [] }

    var selectedModel: SidebarModel? {
        guard case .model(let provider, let model) = selection else { return nil }
        for group in sidebar {
            if case .models(let models) = group.state, let found = models.first(where: { $0.provider == provider && $0.model == model }) {
                return found
            }
        }
        return SidebarModel(provider: provider, model: model, name: live.disambiguatedName(provider: provider, model: model))
    }

    func select(_ section: DashboardSection) {
        if section != selection {
            acceptingSince = nil
            pendingUndo = nil
        }
        selection = section
        load()
    }

    /// A store change: rereads the open dashboard, and nothing while it is closed (opening it
    /// selects a section, which reads everything again).
    func liveChanged() {
        guard isVisible else { return }
        load()
    }

    /// Rereads everything the selected section shows.
    func load() {
        loadSidebar()
        do {
            let loaded = try live.read { store, baseline -> (ModelDetail?, Workload?, [FeedEvent]) in
                var detail: ModelDetail?
                var workload: Workload?
                if case .model(let provider, let model) = selection {
                    let at = now()
                    detail = try ModelDetail.load(
                        store: store, baseline: baseline, provider: provider, model: model,
                        statusSourceID: sources.first { $0.provider == provider }?.statusSourceID, range: range, now: at, calendar: calendar)
                    workload = try Workload.load(store: store, provider: provider, model: model, now: at, calendar: calendar, supportedRules: sources.first { $0.provider == provider }?.supportedRules ?? [])
                }
                let feed = try EventFeed.load(
                    store: store, limit: Self.feedLimit, naming: { live.displayName(provider: $0, model: $1) }, calendar: calendar, sources: sources)
                return (detail, workload, feed)
            }
            (detail, workload, feed) = loaded ?? (nil, nil, [])
            loadError = nil
        } catch {
            loadError = Copy.databaseUnavailable(reason: error.localizedDescription)
        }
        if let pending = pendingUndo, !feed.contains(where: { $0.id == pending.id && $0.undoableEpochID != nil }) {
            pendingUndo = nil
        }
        collector.load()
        if selection == .settings { settings.load() }
    }

    /// Spec section 9.4's dashboard appearance; Dark until the collector's first run stores settings.
    func appearanceSetting() -> Appearance {
        ((try? live.read { store, _ in try store.value(.appearance) }) ?? nil) ?? SettingKey.appearance.defaultValue
    }

    // MARK: Accept as usual and Undo (spec section 8)

    /// Opens the picker on the lasting shift's first day, or today when there is none (plan call).
    func beginAccept() {
        acceptingSince = detail?.shift?.firstDay.start(in: calendar) ?? calendar.startOfDay(for: now())
    }

    func cancelAccept() { acceptingSince = nil }

    func accept() {
        guard case .model(let provider, let model) = selection, let since = acceptingSince else { return }
        panel.accept(provider: provider, model: model, since: since, displayName: selectedModel?.name)
        acceptingSince = nil
        load()
    }

    func keepAsAbnormal() {
        guard let shift = detail?.shift else { return }
        panel.keepAsAbnormal(shift)
        load()
    }

    /// Undo from the event list. Undoing an acceptance with later live ones asks first.
    func requestUndo(_ event: FeedEvent) {
        guard event.undoableEpochID != nil else { return }
        if event.undoConfirmation != nil {
            pendingUndo = event
        } else {
            undo(event)
        }
    }

    /// The alert's Undo button, given the event the alert presented. Closing the alert may clear
    /// `pendingUndo` before the button's action runs, so the event can't be read back from it.
    func confirmUndo(_ event: FeedEvent) {
        pendingUndo = nil
        undo(event)
    }

    func cancelUndo() { pendingUndo = nil }

    private func undo(_ event: FeedEvent) {
        guard let epochID = event.undoableEpochID else { return }
        panel.undo(epochID: epochID)
        load()
    }

    private func loadSidebar() {
        let groups = try? live.read { store, _ in
            try sources.map { source -> SidebarGroup in
                let models = try ModelDetail.models(store: store, provider: source.provider)
                let recent = try ModelDetail.recentModels(store: store, provider: source.provider, now: now())
                let backfilling = try store.backfill(unit: source.provider.rawValue).map { $0.finishedAt == nil } ?? false
                if models.isEmpty {
                    if case .notSetUp = try store.sourceState(source.provider.rawValue)?.state {
                        return SidebarGroup(provider: source.provider, name: source.name, state: .notSetUp, isBackfilling: backfilling)
                    }
                    return SidebarGroup(provider: source.provider, name: source.name, state: .empty, isBackfilling: backfilling)
                }
                if recent.isEmpty { return SidebarGroup(provider: source.provider, name: source.name, state: .idle, isBackfilling: backfilling) }
                let colors = live.snapshot.models.filter { $0.provider == source.provider }
                // Names are made unique over every stored model, so a model keeps its name as it leaves and returns.
                let names = DisplayNames.disambiguated(models, naming: source.naming)
                return SidebarGroup(provider: source.provider, name: source.name, state: .models(recent.map { model in
                    SidebarModel(
                        provider: source.provider, model: model, name: names[model] ?? model,
                        color: colors.first { $0.model == model }?.color)
                }), isBackfilling: backfilling)
            }
        }
        sidebar = (groups ?? nil) ?? sources.map { SidebarGroup(provider: $0.provider, name: $0.name, state: .empty) }
    }
}

/// The dashboard window's content, laid out as the visual doc's dashboard wireframe and mockup: a
/// 200 pt sidebar on the cluster's darker step, and the selected section on the cluster.
struct DashboardView: View {
    let model: DashboardModel

    var body: some View {
        HStack(spacing: 0) {
            DashboardSidebar(model: model)
                .frame(width: 200)
            Rectangle().fill(Theme.swiftUI(Theme.housing).opacity(0.6)).frame(width: 1)
            ScrollView {
                content
                    .padding(.horizontal, 22).padding(.top, 18).padding(.bottom, 24)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .scrollIndicators(.automatic)
        }
        .frame(minWidth: DashboardWindowController.minimumSize.width, minHeight: DashboardWindowController.minimumSize.height)
        .background(Theme.swiftUI(Theme.cluster))
        .foregroundStyle(Theme.swiftUI(Theme.readout))
        .font(.system(size: 13))
        .environment(\.timeZone, model.calendar.timeZone)
        .environment(\.calendar, model.calendar)
        .onChange(of: model.live.generation) { model.liveChanged() }
    }

    @ViewBuilder private var content: some View {
        switch model.selection {
        case .model?:
            ModelView(model: model)
        case .collector?, nil:
            CollectorView(model: model.collector, openSettings: { model.select(.settings) })
        case .settings?:
            SettingsView(model: model.settings)
        }
    }
}

/// Providers and their models, then Collector and Settings (spec section 9.2).
private struct DashboardSidebar: View {
    let model: DashboardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(model.sidebar) { group in
                Text(group.name).font(.system(size: 11)).foregroundStyle(Theme.swiftUI(Theme.dim))
                    .padding(.horizontal, 8).padding(.top, group.id == model.sidebar.first?.id ? 0 : 12).padding(.bottom, 4)
                if group.isBackfilling { dimmed("Reading history…") }
                switch group.state {
                case .models(let models):
                    ForEach(models) { item in
                        row(item.name, color: item.color, section: .model(item.provider, item.model))
                            .opacity(group.isBackfilling ? 0.5 : 1)
                            .help(item.model)
                    }
                case .notSetUp:
                    dimmed(Copy.notSetUp)
                case .empty:
                    if !group.isBackfilling { dimmed(Copy.noResponsesYet) }
                case .idle:
                    if !group.isBackfilling { dimmed(Copy.noRecentModels) }
                }
            }
            Rectangle().fill(Theme.swiftUI(Theme.housing)).frame(height: 1).padding(.top, 24).padding(.bottom, 10)
            row("Collector", color: model.live.health?.lamp == .red ? .red : nil, section: .collector)
            row("Settings", color: nil, section: .settings)
            Spacer(minLength: 0)
            Text(Copy.versionLine).font(.system(size: 11)).foregroundStyle(Theme.swiftUI(Theme.dim))
                .padding(.horizontal, 8).help(AppBundle.buildHelp(info: Bundle.main.infoDictionary) ?? "").accessibilityIdentifier("version")
        }
        .padding(.horizontal, 10).padding(.vertical, 14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Theme.swiftUI(Theme.sidebar))
    }

    private func row(_ title: String, color: LampColor?, section: DashboardSection) -> some View {
        let selected = model.selection == section
        return Button { model.select(section) } label: {
            HStack {
                Text(title).lineLimit(1)
                Spacer(minLength: 4)
                if let color { Diamond(color: Theme.color(color)) }
            }
            .padding(.horizontal, 8).padding(.vertical, 5)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 6).fill(selected ? Theme.swiftUI(Theme.housing) : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityLabel(color.map { "\(title), \($0.rawValue)" } ?? title)
    }

    private func dimmed(_ text: String) -> some View {
        Text(text).foregroundStyle(Theme.swiftUI(Theme.unlitCaption)).padding(.horizontal, 8).padding(.vertical, 5)
    }
}

// MARK: Shared dashboard pieces

/// A 45° square: the visual doc's alert and event mark.
struct Diamond: View {
    let color: Color
    var size: CGFloat = 7
    var hollow = false

    var body: some View {
        Group { if hollow { Rectangle().stroke(color, lineWidth: 1.5) } else { Rectangle().fill(color) } }
            .frame(width: size, height: size).rotationEffect(.degrees(45)).accessibilityHidden(true)
    }
}

/// A dashboard lamp: housing lens; lit, it outlines and colors its icon, and its caption turns Readout.
struct DashboardLamp: View {
    let label: String
    let symbol: String
    let color: Color?
    var width: CGFloat = 92

    var body: some View {
        VStack(spacing: 5) {
            Image(systemName: symbol).font(.system(size: 19)).frame(height: 24)
                .foregroundStyle(color ?? Theme.swiftUI(Theme.unlitIcon))
            Text(label).font(Fonts.gauge(14)).lineLimit(1).minimumScaleFactor(0.7)
                .foregroundStyle(color == nil ? Theme.swiftUI(Theme.unlitCaption) : Theme.swiftUI(Theme.readout))
        }
        .frame(width: width)
        .padding(.top, 9).padding(.bottom, 7)
        .background(RoundedRectangle(cornerRadius: 6).fill(Theme.swiftUI(Theme.housing)))
        .overlay { if let color { RoundedRectangle(cornerRadius: 6).strokeBorder(color, lineWidth: 1.5) } }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(label), \(color == nil ? "unlit" : "lit")")
    }
}

/// An alert or problem line: a colored diamond, the message, and an optional dim detail line.
struct AlertLine: View {
    let color: NSColor
    let text: String
    var detail: String?
    var hollow = false
    var accessory: AnyView?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Diamond(color: Theme.swiftUI(color), size: 8, hollow: hollow)
            VStack(alignment: .leading, spacing: 2) {
                Text(text).foregroundStyle(hollow ? Color.secondary : Color.primary).fixedSize(horizontal: false, vertical: true)
                if let detail { Text(detail).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim)) }
            }
            if let accessory { Spacer(minLength: 0); accessory }
        }
        .font(.system(size: 14))
    }
}

/// The mockup's `.btn`: housing fill, or a housing outline when `quiet`.
struct DashboardButtonStyle: ButtonStyle {
    var quiet = false
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13))
            .foregroundStyle(Theme.swiftUI(Theme.readout))
            .padding(.horizontal, 12).padding(.vertical, 5)
            .background(RoundedRectangle(cornerRadius: 6).fill(quiet ? .clear : Theme.swiftUI(Theme.housing)))
            .overlay { if quiet { RoundedRectangle(cornerRadius: 6).strokeBorder(Theme.swiftUI(Theme.housing), lineWidth: 1) } }
            .opacity(isEnabled ? (configuration.isPressed ? 0.7 : 1) : 0.45)
            .contentShape(Rectangle())
    }
}

/// A section heading with an optional dim aside at the right.
struct SectionHeader<Trailing: View>: View {
    let title: String
    var aside: String?
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(title).font(.system(size: 15, weight: .medium))
            Spacer(minLength: 8)
            if let aside { Text(aside).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim)) }
            trailing
        }
    }
}

extension SectionHeader where Trailing == EmptyView {
    init(title: String, aside: String? = nil) {
        self.init(title: title, aside: aside) { EmptyView() }
    }
}
