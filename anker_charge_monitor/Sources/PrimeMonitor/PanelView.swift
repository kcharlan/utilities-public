import SwiftUI
import PrimeMonitorCore

// Content follows BV's compact native popover and SettingsView.InlineWarning
// at 579ebb7; StatusContent keeps its owned macOS27 host and measurement path.
struct PanelView: View {
    let monitor: MonitorController
    /// Device names for connected ports; omitted, it is memory only.
    var catalog = DeviceCatalogStore()
    /// Expansion and naming state; StatusItemController owns the panel's.
    var detail = PortDetailState()
    var openSettings: () -> Void
    /// The panel's single cancellation action; standalone views only cancel the edit.
    var cancelAction: (() -> Void)?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var rows: [PortReading] { monitor.snapshot?.readings ?? [] }
    var alias: String {
        guard let charger = monitor.appState.charger else { return PrimeMonitorRelease.displayName }
        return charger.alias.isEmpty ? charger.name : charger.alias
    }
    var total: String? { monitor.snapshot.map { DisplayFormatter.watts(centi: $0.totalPowerCenti) } }
    func updated(at now: Date) -> String {
        monitor.snapshot.map { "Updated " + DisplayFormatter.age(now.timeIntervalSince($0.receivedAt)) } ?? "Waiting for readings…"
    }
    var ageText: String { updated(at: monitor.displayTime) }
    var warning: String? {
        switch monitor.status {
        case .networkUnavailable: "Network unavailable. Showing last received values."
        case .sessionEnded: "Session ended. Sign in again to resume updates."
        case .signInFailed(let message), .error(let message): message
        case .verificationRequired: "Verification required. Open the Anker app, then Retry in Settings."
        default: monitor.snapshot != nil && monitor.isStale ? "Readings are stale. Showing last received values." : nil
        }
    }
    var dimmed: Bool { monitor.isStale || warning != nil }
    var emptyMessage: String? {
        if monitor.status == .notConfigured { return "Sign in to your Anker account" }
        if monitor.appState.charger == nil { return "Choose a charger" }
        return nil
    }
    var recoveryTitle: String? {
        switch monitor.status {
        case .sessionEnded: "Sign In Again"
        case .verificationRequired, .signInFailed: "Open Settings"
        case .error: "Retry"
        case .networkUnavailable: nil
        default: warning == nil ? nil : "Retry"
        }
    }
    func recover() async {
        switch monitor.status {
        case .sessionEnded: await monitor.signInAgain()
        case .verificationRequired, .signInFailed: openSettings()
        case .error:
            if let selection = monitor.appState.credentials { await monitor.connect(using: selection) }
            else { openSettings() }
        default: monitor.refreshNow()
        }
    }
    func refresh() { monitor.refreshNow() }

    // MARK: Port detail presentation

    /// Expanded-detail wording for a value that was not decoded.
    nonisolated static let unavailable = "Not reported by this charger"
    var details: ChargerDetails? { monitor.snapshot?.details }
    var naming: NamingContext { NamingContext(monitor: monitor, store: catalog) }
    /// Neither warning dims readings: both are independent of reading freshness.
    var overTemperatureWarning: String? { details?.overTemperature == true ? "Charger reports over-temperature." : nil }
    var catalogWarning: String? { catalog.problem }
    func rowPresentation(_ port: PortID) -> PortRowPresentation {
        .make(port, details: details, catalog: catalog.catalog)
    }
    /// Decoded identity always wins; missing identity is never shown as
    /// nothing attached.
    func expandedIdentity(_ port: PortID) -> ExpandedIdentity {
        guard port.isUSBC else { return .usbA }
        switch details?.identities[port] {
        case nil: return .unavailable
        case .nothingAttached?: return .nothingConnected
        case .identifying?: return .identifying
        case let .identified(vendorID, productID, brandClass, modelCode)?:
            let key = DeviceKey(vendorID: vendorID, productID: productID)
            let brand = brandClass.map { catalog.catalog.brands[$0] ?? "Unknown class \($0)" } ?? Self.unavailable
            return .identified(NamingTarget(charger: naming.charger, port: port, key: key), lines: [
                DetailLine(label: "Brand", value: brand),
                DetailLine(label: "USB IDs", value: key.catalogKey),
                DetailLine(label: "Device model code", value: modelCode.map(String.init) ?? Self.unavailable),
            ])
        }
    }
    func faultLines(_ port: PortID) -> [DetailLine] {
        let value = switch details?.fault(port) {
        case true?: "Fault reported"
        case false?: "None"
        case nil: Self.unavailable
        }
        var lines = [DetailLine(label: port.isUSBC ? "Fault" : "USB-A fault", value: value)]
        if let bits = details?.faultBits {
            let digits = String(bits, radix: 16, uppercase: true)
            lines.append(DetailLine(label: "Fault bits", value: "0x" + (digits.count < 2 ? "0" : "") + digits))
        }
        return lines
    }
    /// Row click, Space and Return.
    func toggle(_ port: PortID) {
        PanelMotion.perform(reduceMotion: reduceMotion) { [detail, naming] in detail.toggle(port, naming) }
    }
    func cancelNaming() {
        if let cancelAction { cancelAction() } else { _ = detail.cancelEditing() }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(alias).font(.headline).lineLimit(2)
                    if let total {
                        Text(total).font(.system(size: 22, weight: .medium).monospacedDigit())
                            .foregroundStyle(dimmed ? .secondary : .primary)
                    }
                    Text(ageText).font(.system(size: 11)).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                Button {
                    PanelMotion.perform(reduceMotion: reduceMotion) { refresh() }
                } label: {
                    if monitor.refreshing {
                        if reduceMotion { Image(systemName: "hourglass") }
                        else { ProgressView().controlSize(.small).frame(width: 16, height: 16) }
                    } else { Image(systemName: "arrow.clockwise") }
                }.disabled(monitor.refreshing || monitor.status != .connected)
                    .help("Request readings now").accessibilityLabel(monitor.refreshing ? "Refreshing readings" : "Refresh readings now")
                Button(action: openSettings) { Image(systemName: "gearshape") }
                    .help("Open Settings").accessibilityLabel("Open Settings")
            }.buttonStyle(.borderless)
            if let warning {
                InlineWarning(message: warning)
                if let recoveryTitle { Button(recoveryTitle) { Task { await recover() } }.controlSize(.small) }
            }
            if let overTemperatureWarning { InlineWarning(message: overTemperatureWarning) }
            Divider()
            if let emptyMessage {
                VStack(alignment: .leading, spacing: 10) {
                    Text(emptyMessage).font(.system(size: 13, weight: .medium))
                    Button("Open Settings…", action: openSettings)
                }.padding(.vertical, 6)
            } else if monitor.snapshot != nil {
                VStack(spacing: 0) {
                    ForEach(PortID.allCases, id: \.self) { port in
                        if let reading = rows.first(where: { $0.port == port }) {
                            let row = PortRowView(reading: reading, presentation: rowPresentation(port), expanded: detail.expanded == port)
                            Button { toggle(port) } label: { row.opacity(dimmed ? 0.55 : 1) }
                                .buttonStyle(.borderless)
                                .onKeyPress(.return) { toggle(port); return .handled }
                                .accessibilityLabel(row.accessibilityText)
                                .accessibilityHint("Shows device details")
                            if detail.expanded == port {
                                PortDetailView(identity: expandedIdentity(port), faultLines: faultLines(port),
                                               detail: detail, catalog: catalog, naming: naming, cancel: cancelNaming)
                            }
                        } else {
                            Text("\(port.label): unavailable").font(.system(size: 12)).foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 7)
                        }
                    }
                }
            } else {
                Text(monitor.status == .connecting ? "Connecting…" : "Waiting for readings…")
                    .font(.system(size: 12)).foregroundStyle(.secondary).padding(.vertical, 8)
            }
            if let catalogWarning { InlineWarning(message: catalogWarning) }
        }.padding(16).frame(width: 400)
    }
}

struct DetailLine: Hashable {
    let label: String
    let value: String
    var text: String { "\(label) \(value)" }
}

/// What an expanded port shows about its connected device.
enum ExpandedIdentity: Equatable {
    case usbA
    /// USB-C identity was not decoded.
    case unavailable
    case nothingConnected
    /// Reported {0, 0}: the device may never answer identity discovery.
    case identifying
    case identified(NamingTarget, lines: [DetailLine])

    /// The single statement for states without device-specific controls.
    var message: String? {
        switch self {
        case .usbA: "USB-A ports don't report connected devices."
        case .unavailable: "Connected device: \(PanelView.unavailable)"
        case .nothingConnected: "Nothing connected."
        case .identifying: "This device hasn't reported its identity."
        case .identified: nil
        }
    }
}

/// Expanded detail for one port: the naming field and device metadata for an
/// identified device, otherwise one identity statement, then the fault lines.
struct PortDetailView: View {
    let identity: ExpandedIdentity
    let faultLines: [DetailLine]
    let detail: PortDetailState
    let catalog: DeviceCatalogStore
    let naming: NamingContext
    let cancel: () -> Void
    @FocusState private var nameFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if case let .identified(target, lines) = identity {
                TextField("Name this device", text: Binding(
                    get: { detail.text(for: target, in: catalog.catalog) },
                    set: { detail.edit($0, for: target, in: catalog.catalog) }))
                    .textFieldStyle(.roundedBorder).controlSize(.small)
                    .focused($nameFocused)
                    .onSubmit { detail.commit(naming) }
                    .onExitCommand(perform: cancel)
                    .onChange(of: nameFocused) { _, focused in
                        if focused { detail.beginEditing() } else { detail.endEditing(naming) }
                    }
                    .onChange(of: detail.editing) { _, editing in
                        if !editing && nameFocused { nameFocused = false }
                    }
                if let failure = detail.failure(for: target) {
                    Text(failure.inlineText).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
                }
                DetailLines(lines: lines)
            } else if let message = identity.message {
                Text(message).foregroundStyle(.secondary)
            }
            DetailLines(lines: faultLines)
        }.font(.system(size: 11))
            .padding(.leading, PortRowView.labelWidth + PortRowView.spacing).padding(.bottom, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityElement(children: .contain)
    }
}

private struct DetailLines: View {
    let lines: [DetailLine]
    var body: some View {
        Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 8, verticalSpacing: 3) {
            ForEach(lines, id: \.self) { line in
                GridRow {
                    Text(line.label).foregroundStyle(.secondary)
                    Text(line.value).foregroundStyle(line.value == "Fault reported" ? AnyShapeStyle(.red) : AnyShapeStyle(.primary))
                        .lineLimit(1).truncationMode(.tail)
                }.accessibilityElement(children: .combine)
            }
        }
    }
}

// Port: BV OtherUpdatesSection.swift, OtherUpdatesHeader, 579ebb7. The reduced
// motion path executes directly, without entering withAnimation at all.
enum PanelMotion {
    static func perform(reduceMotion: Bool,
                        animate: (@escaping () -> Void) -> Void = { change in withAnimation(.easeInOut(duration: 0.15), change) },
                        change: @escaping () -> Void) {
        if reduceMotion { change() } else { animate(change) }
    }
}
