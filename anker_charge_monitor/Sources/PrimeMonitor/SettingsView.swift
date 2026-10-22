import SwiftUI
import Observation
import PrimeMonitorCore

/// Settings interpret provider keys; the controller/cache compare opaque selections.
/// No credential values enter the form.
@MainActor @Observable final class CredentialSettings {
    let monitor: MonitorController
    private(set) var item = "Anker"
    private(set) var vault = ""
    private(set) var country = "US"
    private(set) var busy = false
    init(monitor: MonitorController) { self.monitor = monitor; sync() }
    var configuration: OnePasswordConfiguration {
        .init(item: item,
              vault: vault.isEmpty ? nil : vault, country: country.uppercased())
    }
    var valid: Bool { !item.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && country.count == 2 }
    func sync() {
        // Our own edit already updated the saved selection. Keep the in-progress
        // text (including a space before the next word) when observation echoes it.
        guard monitor.appState.credentials != configuration.selection else { return }
        let saved = monitor.appState.credentials.flatMap(OnePasswordConfiguration.init(selection:))
        item = saved?.item ?? "Anker"; vault = saved?.vault ?? ""; country = saved?.country ?? "US"
    }
    func edit(item: String, vault: String, country: String) {
        self.item = item; self.vault = vault; self.country = country
        // Invalidate synchronously before an action can await credential retrieval.
        monitor.setCredentialSelection(configuration.selection)
    }
    func connect(reload: Bool = false) async {
        guard valid, !busy else { return }
        monitor.setCredentialSelection(configuration.selection)
        busy = true; defer { busy = false }
        await monitor.connect(using: configuration.selection, reload: reload)
    }
    func signOut() async { await monitor.signOut(); sync() }
}

// Port: BV SettingsView.swift, SettingsView, 579ebb7. Retain grouped native Form,
// injected LoginItem and fixed footer; substitute account/charger/cadence fields.
struct SettingsView: View {
    let monitor: MonitorController
    let login: LoginItem
    @State private var account: CredentialSettings
    static let intervals = ClosedInterval.allCases
    static let textSizes = MenuBarTextSize.allCases
    static func textSizeLabel(_ size: MenuBarTextSize) -> String { "\(size.rawValue) pt" + (size == .default ? " (standard)" : "") }
    static let countryOptions = Locale.Region.isoRegions.map(\.identifier).sorted()
    static func supportedChargers(_ chargers: [ChargerInfo]) -> [ChargerInfo] { chargers.filter { $0.model == "A2345" } }
    init(monitor: MonitorController, login: LoginItem) {
        self.monitor = monitor; self.login = login
        _account = State(initialValue: CredentialSettings(monitor: monitor))
    }
    private var chargers: [ChargerInfo] {
        var values = Self.supportedChargers(monitor.chargers)
        if let saved = monitor.appState.charger, saved.model == "A2345", !values.contains(where: { $0.serial == saved.serial }) { values.append(saved) }
        return values
    }
    private var statusText: String {
        StatusPresentation.make(status: monitor.status, snapshot: nil, isStale: false, now: Date()).tooltip
    }
    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section("Anker account") {
                    LabeledContent("Credential provider", value: "1Password")
                    TextField("1Password item name", text: Binding(get: { account.item }, set: { account.edit(item: $0, vault: account.vault, country: account.country) }))
                    TextField("Vault (optional)", text: Binding(get: { account.vault }, set: { account.edit(item: account.item, vault: $0, country: account.country) }))
                        .help("Vault name or ID, to distinguish items with the same name")
                    Picker("Country / region", selection: Binding(get: { account.country }, set: { account.edit(item: account.item, vault: account.vault, country: $0) })) {
                        ForEach(Self.countryOptions, id: \.self) { Text($0).tag($0) }
                    }
                    Button("Sign In using 1Password / Retry") { Task { await account.connect() } }
                        .disabled(account.busy || !account.valid)
                    HStack {
                        Button("Reload Credentials") { Task { await account.connect(reload: true) } }.disabled(account.busy || !account.valid)
                        Button("Sign Out") { Task { await account.signOut() } }
                    }.controlSize(.small)
                    Text(statusText).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    if case .error(let message) = monitor.status { InlineWarning(message: message) }
                    Text("Credentials and sessions stay in memory until \(PrimeMonitorRelease.displayName) quits, even if 1Password closes. If retrieval fails, open and unlock 1Password, then Retry.")
                        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                Section("Charger") {
                    Picker("Monitor", selection: Binding<String?>(get: { monitor.appState.charger?.serial }, set: { serial in
                        if let charger = chargers.first(where: { $0.serial == serial }) { Task { await monitor.select(charger) } }
                    })) {
                        Text("Choose a charger").tag(String?.none)
                        ForEach(chargers, id: \.serial) { charger in
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(charger.label) (\(charger.model))")
                                Text(charger.serial).font(.caption).foregroundStyle(.secondary)
                            }.tag(Optional(charger.serial))
                        }
                    }
                    Button("Refresh list") { Task { await monitor.reloadChargers() } }
                }
                Section("Updates") {
                    Picker("While panel is closed", selection: Binding(get: { monitor.appState.closedInterval }, set: { monitor.setClosedInterval($0) })) {
                        ForEach(Self.intervals, id: \.self) { interval in Text(intervalLabel(interval)).tag(interval) }
                    }.pickerStyle(.menu)
                    Text("While the status panel is open: every 5 seconds.").font(.caption).foregroundStyle(.secondary)
                }
                Section("Menu bar") {
                    Picker("Text size", selection: Binding(get: { monitor.appState.menuBarTextSize ?? .default }, set: { monitor.setMenuBarTextSize($0) })) {
                        ForEach(Self.textSizes, id: \.self) { size in Text(Self.textSizeLabel(size)).tag(size) }
                    }.pickerStyle(.menu)
                    Text("The icon scales with the text. Changes apply right away.").font(.caption).foregroundStyle(.secondary)
                }
                Section("General") {
                    Toggle("Launch at login", isOn: Binding(get: { login.enabled }, set: { login.setEnabled($0) }))
                    Text(login.description).font(.caption).foregroundStyle(.secondary)
                    if login.requiresApproval { Button("Open Login Items Settings") { login.openSettings() } }
                    if let error = login.error { InlineWarning(message: error) }
                }
            }.formStyle(.grouped).toggleStyle(.switch)
            VStack(spacing: 3) {
                Text("\(PrimeMonitorRelease.displayName) \(PrimeMonitorRelease.version)")
                Text("anker-solix-api 8a5222b, 9e72894")
            }.font(.caption).foregroundStyle(.secondary).frame(maxWidth: .infinity).padding(.vertical, 12)
        }.frame(width: 460)
            .onAppear { login.refresh(); account.sync() }
            .onChange(of: monitor.appState.credentials) { _, _ in account.sync() }
    }
    private func intervalLabel(_ interval: ClosedInterval) -> String {
        interval.rawValue < 60 ? "\(interval.rawValue) seconds" : "\(interval.rawValue / 60) \(interval.rawValue == 60 ? "minute" : "minutes")"
    }
}
