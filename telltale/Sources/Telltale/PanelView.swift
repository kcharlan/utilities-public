import AppKit
import Observation
import SwiftUI
import TelltaleCore

/// The panel's Settings and Open dashboard buttons (Task 12's dashboard controller conforms).
@MainActor protocol DashboardOpening: AnyObject {
    func openDashboard()
    func openSettings()
    func openProvider(_ provider: ProviderID, model: String?)
}

/// The panel's state beyond the snapshot: Check now, the shift prompt's actions and their
/// confirmation, and the last action error.
@MainActor @Observable final class PanelModel {
    struct Confirmation: Equatable {
        var text: String
        var epochID: Int64
    }

    let store: LiveStore
    let actions: UserActions
    let notifier: UserNotifier
    let calendar: Calendar
    let canAcknowledgeCollector: Bool
    private(set) var checking = false
    private(set) var actionError: String?
    private(set) var confirmation: Confirmation?

    init(store: LiveStore, actions: UserActions, notifier: UserNotifier, calendar: Calendar = .current, canAcknowledgeCollector: Bool = false) {
        self.store = store
        self.actions = actions
        self.notifier = notifier
        self.calendar = calendar
        self.canAcknowledgeCollector = canAcknowledgeCollector
    }

    /// The strip's lamps: Collector is shown in the footer instead (visual doc's panel).
    var stripSignals: [Signal] { store.snapshot.signals.filter { $0 != .collector } }
    /// Spec section 9.1's quiet panel.
    var emptyMessage: String? { store.snapshot.alerts.isEmpty ? Copy.nothingToReport : nil }
    var checkedText: String? { store.snapshot.checkedAt.map { Copy.checked(at: $0, calendar: calendar) } }
    var offersCollectorAcknowledgement: Bool { canAcknowledgeCollector && store.hasReadableDatabase && store.snapshot.collector == .red }
    /// The status-page incidents the shift prompt links to (spec section 8, ruling R31).
    var shiftIncidents: [IncidentLink] { store.snapshot.shift?.incidents ?? [] }

    func checkNow() async {
        guard !checking else { return }
        checking = true
        defer { checking = false }
        do {
            try await actions.checkNow()
            actionError = nil
        } catch {
            actionError = error.localizedDescription
        }
    }

    /// "Accept as usual…" defaults to the first episode day (spec section 8).
    func acceptSince(for prompt: ShiftPrompt) -> Date { prompt.firstDay.start(in: calendar) }

    func accept(_ prompt: ShiftPrompt, since date: Date) {
        accept(provider: prompt.provider, model: prompt.model, since: date, displayName: store.snapshot.shiftName)
    }

    /// "Accept as usual…" for any model, from the panel's prompt or the dashboard (spec section 8).
    func accept(provider: ProviderID, model: String, since date: Date, displayName: String? = nil) {
        let name = displayName ?? store.disambiguatedName(provider: provider, model: model)
        perform {
            let acceptance = try actions.accept(provider: provider, model: model, since: LocalDay(date, calendar: calendar))
            confirmation = Confirmation(
                text: Copy.acceptance(model: name, percent: acceptance.percentChange),
                epochID: acceptance.epochID)
        }
    }

    func undoAcceptance() {
        guard let confirmation else { return }
        undo(epochID: confirmation.epochID)
    }

    /// Undoes an acceptance (spec section 8), from the confirmation or the dashboard's event list.
    func undo(epochID: Int64) {
        perform {
            try actions.undo(epochID: epochID)
            // Undo also undoes the model's later acceptances, so a confirmation at or after it goes.
            if let shown = confirmation?.epochID, shown >= epochID { confirmation = nil }
        }
    }

    func keepAsAbnormal(_ prompt: ShiftPrompt) {
        perform { try actions.keepAsAbnormal(prompt) }
    }

    func dismissArrival(_ provider: ProviderID) {
        perform { try actions.dismissArrival(provider: provider); store.reload() }
    }

    func acknowledge(_ alerts: [PanelSnapshot.Alert]) {
        perform {
            try actions.acknowledge(alerts)
            store.reload()
            let threadIDs = Set(alerts.compactMap(\.threadID))
            Task { await notifier.removeDelivered(threadIDs: threadIDs) }
        }
    }

    func markAsNew(_ alert: PanelSnapshot.Alert) {
        perform { try actions.markAsNew(key: alert.key); store.reload() }
    }

    func acknowledgeCollector() {
        guard offersCollectorAcknowledgement, let health = store.health else { return }
        perform {
            try actions.acknowledgeCollector(keys: Array(health.problemKeys).sorted())
            store.reload()
            Task { await notifier.removeDelivered(threadIDs: [CollectorMonitor.threadID]) }
        }
    }

    func markCollectorAsNew() {
        guard offersCollectorAcknowledgement else { return }
        perform { try actions.markCollectorAsNew(); store.reload() }
    }

    func providerName(_ provider: ProviderID) -> String { store.providerName(provider) }

    private func perform(_ body: () throws -> Void) {
        do {
            try body()
            actionError = nil
        } catch {
            actionError = error.localizedDescription
        }
    }
}

/// Spec section 9.1's panel, laid out as the visual doc's wireframe and the mockup: 340 pt wide,
/// system material, 13 pt body and 11 pt secondary text, lamp colors the only custom colors.
struct PanelView: View {
    let model: PanelModel
    var openSettings: (() -> Void)?
    var openDashboard: (() -> Void)?
    var openProvider: ((ProviderID, String?) -> Void)?
    var focusGeneration = UUID()
    @State private var acceptingSince: Date?

    static let width: CGFloat = 340

    var body: some View {
        // The owned panel's frame snaps to whole points; whole-point content keeps the window and
        // its scroll viewport exactly the measured size, with no stray half-point scroll.
        IntegralSize { content }
    }

    private var content: some View {
        let snapshot = model.store.snapshot
        return VStack(alignment: .leading, spacing: 10) {
            header(snapshot)
            LampStrip(signals: model.stripSignals, snapshot: snapshot)
            Divider()
            alerts(snapshot)
            if !snapshot.models.isEmpty {
                Divider()
                VStack(alignment: .leading, spacing: 4) {
                    let providers = Array(Set(snapshot.models.map(\.provider)))
                    let width = min(96, max(60, snapshot.models.map { ($0.name as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: 13)]).width }.max() ?? 60))
                    ForEach(Array(snapshot.models.enumerated()), id: \.element.id) { index, row in
                        if providers.count > 1 && (index == 0 || snapshot.models[index - 1].provider != row.provider) {
                            Text(row.providerName).font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                        ModelRowView(row: row, nameWidth: width)
                    }
                }
            }
            if let shift = snapshot.shift, let text = snapshot.shiftText {
                Divider()
                shiftPrompt(shift, text: text)
            }
            ForEach(snapshot.arrivals, id: \.provider) { arrival in
                Divider()
                VStack(alignment: .leading, spacing: 6) {
                    Text(arrival.text).fixedSize(horizontal: false, vertical: true)
                    HStack {
                        Button("Open \(model.providerName(arrival.provider))") { openProvider?(arrival.provider, arrival.firstModel) }.disabled(openProvider == nil || arrival.firstModel == nil)
                        Button("Dismiss") { model.dismissArrival(arrival.provider) }
                    }
                }
            }
            if let confirmation = model.confirmation {
                HStack(alignment: .firstTextBaseline) {
                    Text(confirmation.text).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 8)
                    Button("Undo") { model.undoAcceptance() }
                }
            }
            if let warning = model.notifier.lastError { notificationIssue(warning) }
            if let error = model.actionError {
                Text(error).font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            Divider()
            footer(snapshot)
        }
        .font(.system(size: 13))
        .padding(12)
        .frame(width: Self.width, alignment: .leading)
        .onChange(of: focusGeneration) { acceptingSince = nil }
    }

    private func header(_ snapshot: PanelSnapshot) -> some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 1) {
                Text(TelltaleRelease.displayName).font(.system(size: 13, weight: .semibold))
                if let checked = model.checkedText {
                    Text(checked).font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }
            Spacer()
            Button { Task { await model.checkNow() } } label: {
                Image(systemName: "arrow.clockwise").font(.system(size: 13))
            }
            .buttonStyle(.borderless)
            .disabled(model.checking)
            .help("Check now")
            .accessibilityLabel("Check now")
        }
    }

    @ViewBuilder private func alerts(_ snapshot: PanelSnapshot) -> some View {
        if let empty = model.emptyMessage {
            Text(empty).foregroundStyle(.secondary).padding(.vertical, 4)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(snapshot.alerts.enumerated()), id: \.offset) { _, alert in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Diamond(color: Theme.color(alert.color), hollow: alert.acknowledgedAt != nil)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(alert.text).foregroundStyle(alert.acknowledgedAt == nil ? Color.primary : Color.secondary).fixedSize(horizontal: false, vertical: true)
                            if let detail = alert.detail { Text(detail).font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }
                        }
                        Spacer(minLength: 0)
                        AlertAcknowledgeButton(acknowledged: alert.acknowledgedAt != nil) {
                            if alert.acknowledgedAt == nil { model.acknowledge([alert]) } else { model.markAsNew(alert) }
                        }
                    }
                }
                let newAlerts = snapshot.alerts.filter { $0.acknowledgedAt == nil }
                if newAlerts.count > 1 {
                    HStack { Spacer(); Button(Copy.acknowledgeAll) { model.acknowledge(newAlerts) }.buttonStyle(.borderless).font(.system(size: 11)) }
                }
            }
        }
    }

    private func shiftPrompt(_ shift: ShiftPrompt, text: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(text).fixedSize(horizontal: false, vertical: true)
            IncidentLinks(incidents: model.shiftIncidents, size: 11)
            if let since = acceptingSince {
                HStack {
                    DatePicker("Since", selection: Binding(get: { since }, set: { acceptingSince = $0 }), in: ...Date(), displayedComponents: .date)
                        .labelsHidden()
                    Button("Accept") {
                        model.accept(shift, since: since)
                        acceptingSince = nil
                    }
                    Button("Cancel") { acceptingSince = nil }
                }
            } else {
                HStack {
                    Button("Accept as usual…") { acceptingSince = model.acceptSince(for: shift) }
                    Button("Keep as abnormal") { model.keepAsAbnormal(shift) }
                }
            }
        }
    }

    private func notificationIssue(_ warning: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: "exclamationmark.triangle").foregroundStyle(.secondary).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(warning).font(.system(size: 11)).fixedSize(horizontal: false, vertical: true)
                Button("Retry notifications") { Task { await model.notifier.retry() } }.font(.system(size: 11))
            }
        }
    }

    private func footer(_ snapshot: PanelSnapshot) -> some View {
        // The visual doc's mockup: collector state on its own line, Open dashboard below it at the right.
        VStack(alignment: .leading, spacing: 6) {
            if Self.collectorDot(snapshot.collector) != nil || !snapshot.footer.isEmpty {
                HStack(alignment: .center, spacing: 6) {
                    if let dot = Self.collectorDot(snapshot.collector) {
                        if snapshot.collectorAcknowledgedAt != nil {
                            Circle().stroke(dot, lineWidth: 1.5).frame(width: 7, height: 7).accessibilityHidden(true)
                        } else {
                            Circle().fill(dot).frame(width: 7, height: 7).accessibilityHidden(true)
                        }
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        Text(snapshot.footer).font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        if let at = snapshot.collectorAcknowledgedAt { Text(Copy.acknowledged(at: at, calendar: model.calendar)).font(.system(size: 11)).foregroundStyle(.secondary) }
                    }
                    if model.offersCollectorAcknowledgement {
                        Spacer(minLength: 0)
                        AlertAcknowledgeButton(acknowledged: snapshot.collectorAcknowledgedAt != nil) {
                            if snapshot.collectorAcknowledgedAt == nil { model.acknowledgeCollector() } else { model.markCollectorAsNew() }
                        }
                    }
                }
            }
            HStack(alignment: .center, spacing: 6) {
                Text(Copy.versionLine).font(.system(size: 11)).foregroundStyle(.tertiary)
                    .help(AppBundle.buildHelp(info: Bundle.main.infoDictionary) ?? "").accessibilityIdentifier("version")
                Spacer(minLength: 0)
                Button { openSettings?() } label: { Image(systemName: "gearshape") }
                    .buttonStyle(.borderless).disabled(openSettings == nil).help("Settings").accessibilityLabel("Settings")
                Button("Open dashboard") { openDashboard?() }.disabled(openDashboard == nil)
            }
        }
    }

    static func collectorDot(_ state: LampState) -> Color? {
        switch state {
        case .unlit: nil
        case .green: Color(nsColor: Theme.green)
        case .red: Theme.color(.red)
        }
    }
}

struct AlertAcknowledgeButton: View {
    let acknowledged: Bool
    let action: () -> Void
    var body: some View {
        let label = acknowledged ? Copy.markAsNew : Copy.acknowledge
        Button(action: action) { Image(systemName: acknowledged ? "checkmark.circle.fill" : "checkmark.circle").font(.system(size: 13)) }
            .buttonStyle(.borderless).help(label).accessibilityLabel(label)
    }
}

/// Rounds its content's size up to whole points.
struct IntegralSize: Layout {
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let size = subviews.first?.sizeThatFits(proposal) ?? .zero
        return CGSize(width: size.width.rounded(.up), height: size.height.rounded(.up))
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        subviews.first?.place(at: bounds.origin, proposal: ProposedViewSize(bounds.size))
    }
}

/// The lamp strip: unlit lamps sit in the housing color; a lit lamp outlines and colors its icon
/// and caption in its lamp color.
struct LampStrip: View {
    let signals: [Signal]
    let snapshot: PanelSnapshot

    var body: some View {
        // Every lamp is the same size: a fixed icon box and one caption line (a symbol's own height,
        // or a long status name scaled down, would otherwise make its lamp taller or shorter).
        HStack(spacing: 6) {
            ForEach(signals, id: \.self) { signal in
                let color = snapshot.lamps[signal].flatMap { $0 }
                let label = snapshot.labels[signal] ?? signal.rawValue.capitalized
                let unlit = Color.secondary.opacity(0.6)
                // A lit lamp colors its icon and outline; its caption turns Readout (primary), as in
                // the mockup's `.lamp[data-on] { --cap: var(--readout) }`.
                VStack(spacing: 3) {
                    Image(systemName: Self.symbol(signal)).font(.system(size: 15)).frame(height: 18)
                        .foregroundStyle(color.map(Theme.color) ?? unlit)
                    Text(label).font(.system(size: 11, weight: .medium)).lineLimit(1).minimumScaleFactor(0.7).frame(height: 14)
                        .foregroundStyle(color == nil ? unlit : Color.primary)
                }
                .frame(maxWidth: .infinity)
                .padding(.top, 6).padding(.bottom, 5).padding(.horizontal, 2)
                .background(RoundedRectangle(cornerRadius: 6).fill(.quaternary))
                .overlay { if let color { RoundedRectangle(cornerRadius: 6).strokeBorder(Theme.color(color), lineWidth: 1.5) } }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(label) \(color?.rawValue ?? "unlit")")
            }
        }
    }

    static func symbol(_ signal: Signal) -> String {
        switch signal {
        case .speed: "gauge.with.dots.needle.33percent"
        case .errors: "exclamationmark.triangle"
        case .link: "link"
        case .provider: "server.rack"
        case .load: "scalemass"
        case .collector: "arrow.triangle.2.circlepath"
        }
    }
}

/// One active model: tok/s with usual beside it, a 3-hour sparkline, and a thin-data or learning note.
private struct ModelRowView: View {
    let row: PanelSnapshot.ModelRow
    let nameWidth: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(row.name).fixedSize(horizontal: false, vertical: true).frame(width: nameWidth, alignment: .leading).help(row.model)
                HStack(alignment: .firstTextBaseline, spacing: 2) {
                    // A model in a speed episode shows its numeral and sparkline in the lamp color (mockup).
                    Text(row.tps.map { String(Int($0.rounded())) } ?? "–").font(.system(size: 17, weight: .medium).monospacedDigit())
                        .foregroundStyle(row.color.map(Theme.color) ?? Color.primary)
                    Text("tok/s").font(.system(size: 11)).foregroundStyle(.secondary)
                }
                .frame(width: 80, alignment: .leading)
                Text(row.usual.map { "usual \(Int($0.rounded()))" } ?? "").font(.system(size: 11)).foregroundStyle(.secondary)
                Spacer(minLength: 4)
                Sparkline(values: row.sparkline, reference: row.usual)
                    .stroke(row.color.map(Theme.color) ?? Color.secondary, style: StrokeStyle(lineWidth: 1.2, lineCap: .round, lineJoin: .round))
                    .frame(width: 64, height: 16)
                    .accessibilityHidden(true)
            }
            if let note = row.note {
                Text(note).font(.system(size: 11)).foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// The stored points' median tok/s, oldest at the left; gaps break the line. Scaled to the points
/// and the usual together, so a drop below usual reads as a drop. The scale spans at least a quarter
/// of usual (plan call, from the snapshot harness), centred on the points, so ordinary noise draws
/// as a near-flat line, as in the visual doc's mockup, instead of a full-height wave.
struct Sparkline: Shape {
    static let minimumSpan = 0.25
    let values: [Double?]
    let reference: Double?

    func path(in rect: CGRect) -> Path {
        let known = values.compactMap { $0 } + (reference.map { [$0] } ?? [])
        guard var low = known.min(), let high = known.max(), values.count > 1 else { return Path() }
        let span = max(high - low, (reference ?? high) * Self.minimumSpan, 1)
        low -= (span - (high - low)) / 2
        let step = rect.width / CGFloat(values.count - 1)
        var path = Path()
        var drawing = false
        for (index, value) in values.enumerated() {
            guard let value else { drawing = false; continue }
            let point = CGPoint(x: rect.minX + CGFloat(index) * step, y: rect.maxY - CGFloat((value - low) / span) * rect.height)
            if drawing { path.addLine(to: point) } else { path.move(to: point); drawing = true }
        }
        return path
    }
}

/// The status-page incidents in a shift prompt's period, each a link to its page (spec section 8,
/// ruling R31). Shared by the panel's and the dashboard's prompts.
struct IncidentLinks: View {
    let incidents: [IncidentLink]
    var size: CGFloat = 12

    var body: some View {
        if !incidents.isEmpty {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(incidents) { incident in
                    Link(destination: incident.link) {
                        Label(incident.name, systemImage: "arrow.up.right.square").labelStyle(.titleAndIcon)
                    }
                    .font(.system(size: size))
                    .help(incident.link.absoluteString)
                }
            }
        }
    }
}
