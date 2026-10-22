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
    /// The panel's single cancellation action; standalone views disarm, then cancel the edit.
    var cancelAction: (() -> Void)?
    /// Posts port phase changes and outcomes to assistive technologies.
    var announce: @MainActor (String) -> Void = PanelView.postAnnouncement
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var rows: [PortReading] { monitor.snapshot?.readings ?? [] }
    var alias: String { monitor.appState.charger?.label ?? PrimeMonitorRelease.displayName }
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
        .make(port, details: details, catalog: catalog.catalog, phase: phaseText(PortSwitch(port)))
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
        var lines = [DetailLine(label: port.isUSBC ? "Fault" : "USB-A fault", value: value, alert: details?.fault(port) == true)]
        if let bits = details?.faultBits { lines.append(DetailLine(label: "Fault bits", value: "0x" + DisplayFormatter.hex(bits))) }
        return lines
    }
    /// The charger-reported switch for a port; A1 and A2 read the one USB-A switch.
    func switchLine(_ port: PortID) -> DetailLine {
        let value = switch details?.switchedOn(port) {
        case true?: "On"
        case false?: "Off"
        case nil: Self.unavailable
        }
        return DetailLine(label: "Port switch", value: value)
    }
    /// The expanded row's state lines: fault, then the switch beside it.
    func statusLines(_ port: PortID) -> [DetailLine] { faultLines(port) + [switchLine(port)] }
    /// Row click, Space and Return.
    func toggle(_ port: PortID) {
        PanelMotion.perform(reduceMotion: reduceMotion) { [detail, naming] in detail.toggle(port, naming) }
    }
    /// The naming field's Escape. The panel's cancel owner decides when present;
    /// a standalone view has none, so it disarms an armed action first, which
    /// consumes the Escape, and only otherwise cancels the edit.
    func cancelNaming() {
        if let cancelAction { cancelAction(); return }
        if detail.disarm(in: controlGenerations, available: controlsAvailable) { return }
        _ = detail.cancelEditing(context: naming)
    }

    // MARK: Port control presentation
    // Plan "Switch state and actions", "Confirmation", "Outcome lifetime", "Wording".

    var controlGenerations: PortControlGenerations { monitor.portControlGenerations }
    var controlsAvailable: Bool { monitor.portControlBlock == nil }
    var unavailableReason: String? {
        switch monitor.portControlBlock {
        case .anotherPortChanging?: "Another port is changing."
        case .disconnected?: "Reconnect to control ports."
        case .stale?: "Readings are stale."
        case nil: nil
        }
    }
    /// The running operation's phase, shown on its target's rows and detail.
    func phaseText(_ target: PortSwitch) -> String? {
        guard let operation = monitor.portOperation, operation.target == target else { return nil }
        switch operation.phase {
        case .turningOff: return "Turning off…"
        case .paused: return "On again in \(operation.pauseSecondsRemaining(at: monitor.displayTime) ?? 0) s"
        case .turningOn: return "Turning on…"
        case .idle, .finished: return nil
        }
    }
    /// Actions for the expanded port: the reported switch decides which, the
    /// armed one reads as its confirmation, and the status line gives the phase
    /// or the reason controls are unavailable.
    func controls(_ port: PortID) -> PortControls {
        let target = PortSwitch(port)
        let armed = detail.armedAction(in: controlGenerations, available: controlsAvailable).flatMap { $0.target == target ? $0 : nil }
        let buttons = PortOperationKind.offered(switchOn: details?.switchedOn(port)).map { action in
            let armedTitle = armed?.action == action ? action.armedTitle : nil
            return PortControlButton(action: action, title: armedTitle ?? action.title(for: target), armed: armedTitle != nil)
        }
        return PortControls(buttons: buttons, enabled: controlsAvailable, caption: armed.map { _ in armedCaption(port) },
                            status: phaseText(target) ?? unavailableReason)
    }
    /// What the armed action would cut: the port's (or USB-A pair's) reported power
    /// and an identified device's label.
    func armedCaption(_ port: PortID) -> String {
        let target = PortSwitch(port)
        let powered = PortID.allCases.filter { PortSwitch($0) == target }
        let power = rows.filter { powered.contains($0.port) }.map(\.powerCenti).reduce(0, +)
        var device: String?
        if port.isUSBC, case .identified? = details?.identities[port] { device = rowPresentation(port).device }
        return "\(target.label) is supplying \(DisplayFormatter.watts(centi: power)) to \(device ?? "a connected device")."
    }
    /// Turn on acts at once; Turn off and Restart act on the confirming click,
    /// rechecked against the generations captured when armed.
    func perform(_ action: PortOperationKind, on port: PortID) {
        let target = PortSwitch(port)
        guard detail.press(action, target: target, in: controlGenerations, available: controlsAvailable) else { return }
        switch action {
        case .turnOff: monitor.turnPort(target, on: false)
        case .turnOn: monitor.turnPort(target, on: true)
        case .restart: monitor.restartPort(target)
        }
    }
    nonisolated static func outcomeMessage(_ outcome: PortOperationOutcome) -> String? {
        let target = outcome.target.label
        switch outcome.kind {
        case .confirmed: return nil
        case .offNotConfirmed: return "Couldn't confirm \(target) turned off."
        case .stillOff: return "\(target) is still off. Turn it on to restore power."
        case .onNotConfirmed: return "Couldn't confirm \(target) turned on."
        case .mayStillBeOff: return "\(target) may still be off. Check the charger and turn the port on if needed."
        }
    }
    /// Shown above the empty and readings branches with the label of the charger
    /// it came from, never on the rows of a newly selected charger.
    var outcomeText: String? {
        monitor.portOutcome.flatMap { outcome in Self.outcomeMessage(outcome).map { "\(outcome.context.chargerLabel): \($0)" } }
    }
    func dismissOutcome() { monitor.dismissPortOutcome() }
    /// Changes on a phase change or a new outcome, not on each countdown second.
    var portAnnouncementKey: String? {
        if let operation = monitor.portOperation {
            let phase = switch operation.phase {
            case .turningOff: "turning off"
            case .paused: "paused"
            case .turningOn: "turning on"
            case .idle, .finished: "idle"
            }
            return "\(operation.target.label) \(phase)"
        }
        return outcomeText
    }
    /// The text announced when `portAnnouncementKey` changes.
    var portAnnouncement: String? { monitor.portOperation.flatMap { phaseText($0.target) } ?? outcomeText }
    static func postAnnouncement(_ text: String) { AccessibilityNotification.Announcement(text).post() }

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
            if let outcomeText {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    InlineWarning(message: outcomeText)
                    Button("Dismiss", action: dismissOutcome).controlSize(.small)
                }
            }
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
                                .accessibilityValue(row.accessibilityValue)
                                .accessibilityHint("Shows device details")
                            if detail.expanded == port {
                                PortDetailView(identity: expandedIdentity(port), statusLines: statusLines(port),
                                               detail: detail, catalog: catalog, naming: naming, cancel: cancelNaming,
                                               controls: controls(port), perform: { perform($0, on: port) })
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
            // Losing control availability or the armed context disarms for good.
            .onChange(of: controlGenerations) { _, context in detail.revalidate(in: context, available: controlsAvailable) }
            .onChange(of: controlsAvailable) { _, available in detail.revalidate(in: controlGenerations, available: available) }
            .onChange(of: portAnnouncementKey) { _, key in
                if key != nil, let text = portAnnouncement { announce(text) }
            }
    }
}

/// One port control button: an armed action reads as its confirmation.
struct PortControlButton: Equatable {
    let action: PortOperationKind
    let title: String
    let armed: Bool
}

/// The expanded port's controls.
struct PortControls: Equatable {
    let buttons: [PortControlButton]
    let enabled: Bool
    /// What an armed action would cut power to.
    let caption: String?
    /// The running operation's phase on this target, else why controls are unavailable.
    let status: String?
}

extension PortOperationKind {
    /// "Switch state and actions": reported on offers restart and turn-off,
    /// reported off offers turn-on, unknown offers each, in Wording order.
    static func offered(switchOn: Bool?) -> [PortOperationKind] {
        switch switchOn {
        case true?: [.restart, .turnOff]
        case false?: [.turnOn]
        case nil: [.restart, .turnOff, .turnOn]
        }
    }
    func title(for target: PortSwitch) -> String {
        let usbA = target == .usbA
        return switch self {
        case .restart: usbA ? "Restart USB-A ports" : "Restart"
        case .turnOff: usbA ? "Turn off USB-A ports" : "Turn off"
        case .turnOn: usbA ? "Turn on USB-A ports" : "Turn on"
        }
    }
    /// nil for Turn on, which never arms.
    var armedTitle: String? {
        switch self {
        case .restart: "Confirm restart"
        case .turnOff: "Confirm turn off"
        case .turnOn: nil
        }
    }
}

struct DetailLine: Hashable {
    let label: String
    let value: String
    /// Shown in red: a reported fault.
    var alert = false
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
/// identified device, otherwise one identity statement, then the fault and switch lines.
struct PortDetailView: View {
    let identity: ExpandedIdentity
    let statusLines: [DetailLine]
    let detail: PortDetailState
    let catalog: DeviceCatalogStore
    let naming: NamingContext
    let cancel: () -> Void
    let controls: PortControls
    let perform: (PortOperationKind) -> Void
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
                    .onDisappear { detail.fieldRemoved() }
                    // A replacement device or charger gets a new, unfocused field.
                    .id(target)
                if let failure = detail.failure(for: target) {
                    Text(failure.inlineText).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
                }
                // One grid, so identity and status values share a column.
                DetailLines(lines: lines + statusLines)
            } else {
                if let message = identity.message { Text(message).foregroundStyle(.secondary) }
                DetailLines(lines: statusLines)
            }
            PortControlsView(controls: controls, perform: perform).padding(.top, 2)
        }.font(.system(size: 11))
            .padding(.leading, PortRowView.labelWidth + PortRowView.spacing).padding(.bottom, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityElement(children: .contain)
    }
}

/// The port's switch actions, the armed caption above them and the phase or
/// unavailable reason below. An armed button reads in red.
private struct PortControlsView: View {
    let controls: PortControls
    let perform: (PortOperationKind) -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            if let caption = controls.caption {
                Label {
                    Text(caption).fixedSize(horizontal: false, vertical: true)
                } icon: {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
                }
            }
            HStack(spacing: 6) {
                ForEach(controls.buttons, id: \.action) { button in
                    // An explicit label colour: an accent tint is greyed whenever the
                    // panel is not the key window. Only an armed (so enabled) button
                    // sets one; others keep the system's enabled and disabled colours.
                    Button { perform(button.action) } label: {
                        if button.armed { Text(button.title).fontWeight(.semibold).foregroundStyle(.red) }
                        else { Text(button.title) }
                    }
                }
            }.buttonStyle(.bordered).controlSize(.small).disabled(!controls.enabled)
            if let status = controls.status {
                Text(status).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

private struct DetailLines: View {
    let lines: [DetailLine]
    var body: some View {
        Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 8, verticalSpacing: 3) {
            ForEach(lines, id: \.self) { line in
                GridRow {
                    Text(line.label).foregroundStyle(.secondary)
                    Text(line.value).foregroundStyle(line.alert ? AnyShapeStyle(.red) : AnyShapeStyle(.primary))
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
