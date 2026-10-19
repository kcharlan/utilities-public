import SwiftUI
import PrimeMonitorCore

// Content follows BV's compact native popover and SettingsView.InlineWarning
// at 579ebb7; StatusContent keeps its owned macOS27 host and measurement path.
struct PanelView: View {
    let monitor: MonitorController
    var openSettings: () -> Void
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
                            PortRowView(reading: reading).opacity(dimmed ? 0.55 : 1)
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
        }.padding(16).frame(width: 400)
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
