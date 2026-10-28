import AppKit
import Observation
import SwiftUI
import TelltaleCore

/// One row of spec section 9.4's Rules section: a rule of section 7.4's table.
enum SettingsRule: String, CaseIterable, Identifiable {
    case slower, faster, largePrompts, failedTurns, disconnects, incident, collectorHealth, usageLimit

    var id: String { rawValue }
    var title: String { RuleID(rawValue: rawValue)?.title ?? "Collector health" }
    var parameters: [RuleParameter] { RuleParameter.allCases.filter { $0.rule == self } }

    /// What a rule without parameters watches (spec section 7.4).
    var summary: String? {
        switch self {
        case .incident: "Fires for an open incident on a watched component, or one naming a model used in the last 24 hours."
        case .collectorHealth: "Fires when the collector isn't loaded, fails twice in a row, falls behind or can't read the logs."
        default: nil
        }
    }

    func switches(in settings: RuleSettings) -> any RuleSwitches {
        switch self {
        case .slower: settings.slower
        case .faster: settings.faster
        case .largePrompts: settings.largePrompts
        case .failedTurns: settings.failedTurns
        case .disconnects: settings.disconnects
        case .incident: settings.incident
        case .collectorHealth: settings.collectorHealth
        case .usageLimit: settings.usageLimit
        }
    }

    func set(_ toggle: RuleSwitch, _ on: Bool, in settings: inout RuleSettings) {
        switch self {
        case .slower: toggle.set(on, in: &settings.slower)
        case .faster: toggle.set(on, in: &settings.faster)
        case .largePrompts: toggle.set(on, in: &settings.largePrompts)
        case .failedTurns: toggle.set(on, in: &settings.failedTurns)
        case .disconnects: toggle.set(on, in: &settings.disconnects)
        case .incident: toggle.set(on, in: &settings.incident)
        case .collectorHealth: toggle.set(on, in: &settings.collectorHealth)
        case .usageLimit: toggle.set(on, in: &settings.usageLimit)
        }
    }

    /// Puts this rule back to `RuleSettings.defaults`, leaving the other rules alone.
    func reset(in settings: inout RuleSettings) {
        let defaults = RuleSettings.defaults
        switch self {
        case .slower: settings.slower = defaults.slower
        case .faster: settings.faster = defaults.faster
        case .largePrompts: settings.largePrompts = defaults.largePrompts
        case .failedTurns: settings.failedTurns = defaults.failedTurns
        case .disconnects: settings.disconnects = defaults.disconnects
        case .incident: settings.incident = defaults.incident
        case .collectorHealth: settings.collectorHealth = defaults.collectorHealth
        case .usageLimit: settings.usageLimit = defaults.usageLimit
        }
    }
}

/// The three switches every rule has (spec section 7.4).
protocol RuleSwitches {
    var enabled: Bool { get set }
    var notify: Bool { get set }
    var notifyOnClear: Bool { get set }
}

extension SpeedRule: RuleSwitches {}
extension LargePromptRule: RuleSwitches {}
extension FailedTurnRule: RuleSwitches {}
extension DisconnectRule: RuleSwitches {}
extension BasicRule: RuleSwitches {}
extension UsageLimitRule: RuleSwitches {}

enum RuleSwitch: CaseIterable {
    case enabled, notify, notifyOnClear

    var title: String {
        switch self {
        case .enabled: "On"
        case .notify: "Notify"
        case .notifyOnClear: "Notify when it clears"
        }
    }

    func value(_ rule: any RuleSwitches) -> Bool {
        switch self {
        case .enabled: rule.enabled
        case .notify: rule.notify
        case .notifyOnClear: rule.notifyOnClear
        }
    }

    func set<Rule: RuleSwitches>(_ on: Bool, in rule: inout Rule) {
        switch self {
        case .enabled: rule.enabled = on
        case .notify: rule.notify = on
        case .notifyOnClear: rule.notifyOnClear = on
        }
    }
}

/// An editable rule parameter as Settings shows it: fractions of usual as percentages, durations in
/// minutes and prompt sizes in thousands of tokens. `field` is the name `RuleSettings.validationErrors`
/// uses, so an unreadable entry gets the same message as an invalid one.
enum RuleParameter: String, CaseIterable, Identifiable {
    case slowerThreshold, slowerDuration, slowerClearBand, slowerClearDuration
    case fasterThreshold, fasterDuration, fasterClearBand, fasterClearDuration
    case largeCount, largeOf, largeTokens, largeClearAtMost
    case failedQuiet, failedCoalesce
    case disconnectCount, disconnectWindow
    case usagePercent

    enum Unit { case percent, minutes, count, thousandTokens }

    var id: String { rawValue }

    var rule: SettingsRule {
        switch self {
        case .slowerThreshold, .slowerDuration, .slowerClearBand, .slowerClearDuration: .slower
        case .fasterThreshold, .fasterDuration, .fasterClearBand, .fasterClearDuration: .faster
        case .largeCount, .largeOf, .largeTokens, .largeClearAtMost: .largePrompts
        case .failedQuiet, .failedCoalesce: .failedTurns
        case .disconnectCount, .disconnectWindow: .disconnects
        case .usagePercent: .usageLimit
        }
    }

    var unit: Unit {
        switch self {
        case .slowerThreshold, .slowerClearBand, .fasterThreshold, .fasterClearBand, .usagePercent: .percent
        case .slowerDuration, .slowerClearDuration, .fasterDuration, .fasterClearDuration, .failedQuiet, .failedCoalesce, .disconnectWindow: .minutes
        case .largeCount, .largeOf, .largeClearAtMost, .disconnectCount: .count
        case .largeTokens: .thousandTokens
        }
    }

    /// The parameter's line in its rule's row: 0 says when it fires, 1 when it clears.
    var line: Int {
        switch self {
        case .slowerClearBand, .slowerClearDuration, .fasterClearBand, .fasterClearDuration, .largeClearAtMost, .failedQuiet: 1
        default: 0
        }
    }

    /// The words before the field and after it, so each line reads as a sentence.
    var label: (before: String, after: String) {
        switch self {
        case .slowerThreshold: ("Fires at", "% slower")
        case .fasterThreshold: ("Fires at", "% faster")
        case .slowerDuration, .fasterDuration: ("for", "min")
        case .slowerClearBand, .fasterClearBand: ("Clears within", "% of usual")
        case .slowerClearDuration, .fasterClearDuration: ("for", "min")
        case .largeCount: ("Fires when", "")
        case .largeOf: ("of the last", "prompts")
        case .largeTokens: ("are at least", "k tokens")
        case .largeClearAtMost: ("Clears at", "or fewer")
        case .failedCoalesce: ("Fires on any failed turn, notifying at most every", "min")
        case .failedQuiet: ("Clears after", "min with no failure")
        case .disconnectCount: ("Fires at", "disconnect or retry events in")
        case .disconnectWindow: ("", "min")
        case .usagePercent: ("Fires at", "% of the limit used")
        }
    }

    var field: String {
        switch self {
        case .slowerThreshold: "Slower than usual threshold"
        case .slowerDuration: "Slower than usual duration"
        case .slowerClearBand: "Slower than usual clear band"
        case .slowerClearDuration: "Slower than usual clear duration"
        case .fasterThreshold: "Faster than usual threshold"
        case .fasterDuration: "Faster than usual duration"
        case .fasterClearBand: "Faster than usual clear band"
        case .fasterClearDuration: "Faster than usual clear duration"
        case .largeCount: "Large prompts count"
        case .largeOf: "Large prompts window"
        case .largeTokens: "Large prompts input tokens"
        case .largeClearAtMost: "Large prompts clear level"
        case .failedQuiet: "Failed turns quiet period"
        case .failedCoalesce: "Failed turns notice spacing"
        case .disconnectCount: "Disconnects count"
        case .disconnectWindow: "Disconnects window"
        case .usagePercent: "Usage limit percentage"
        }
    }

    /// The stored value as Settings shows it.
    func text(in settings: RuleSettings) -> String {
        switch self {
        case .slowerThreshold: Self.number(settings.slower.threshold * 100)
        case .slowerDuration: String(settings.slower.durationMinutes)
        case .slowerClearBand: Self.number(settings.slower.clearBand * 100)
        case .slowerClearDuration: String(settings.slower.clearMinutes)
        case .fasterThreshold: Self.number(settings.faster.threshold * 100)
        case .fasterDuration: String(settings.faster.durationMinutes)
        case .fasterClearBand: Self.number(settings.faster.clearBand * 100)
        case .fasterClearDuration: String(settings.faster.clearMinutes)
        case .largeCount: String(settings.largePrompts.count)
        case .largeOf: String(settings.largePrompts.of)
        case .largeTokens: Self.number(Double(settings.largePrompts.inputTokens) / 1_000)
        case .largeClearAtMost: String(settings.largePrompts.clearAtMost)
        case .failedQuiet: String(settings.failedTurns.quietMinutes)
        case .failedCoalesce: String(settings.failedTurns.coalesceMinutes)
        case .disconnectCount: String(settings.disconnects.count)
        case .disconnectWindow: String(settings.disconnects.windowMinutes)
        case .usagePercent: Self.number(settings.usageLimit.percent)
        }
    }

    /// Reads `text` into `settings`; false when it isn't a number of the right kind. Range checks
    /// are `RuleSettings.validationErrors`'s.
    func apply(_ text: String, to settings: inout RuleSettings) -> Bool {
        let text = text.trimmingCharacters(in: .whitespaces)
        switch unit {
        case .percent, .thousandTokens:
            guard let value = Double(text), value.isFinite else { return false }
            switch self {
            case .slowerThreshold: settings.slower.threshold = value / 100
            case .slowerClearBand: settings.slower.clearBand = value / 100
            case .fasterThreshold: settings.faster.threshold = value / 100
            case .fasterClearBand: settings.faster.clearBand = value / 100
            case .usagePercent: settings.usageLimit.percent = value
            case .largeTokens:
                guard abs(value) < 1_000_000_000 else { return false }
                settings.largePrompts.inputTokens = Int((value * 1_000).rounded())
            default: return false
            }
        case .minutes, .count:
            guard let value = Int(text) else { return false }
            switch self {
            case .slowerDuration: settings.slower.durationMinutes = value
            case .slowerClearDuration: settings.slower.clearMinutes = value
            case .fasterDuration: settings.faster.durationMinutes = value
            case .fasterClearDuration: settings.faster.clearMinutes = value
            case .largeCount: settings.largePrompts.count = value
            case .largeOf: settings.largePrompts.of = value
            case .largeClearAtMost: settings.largePrompts.clearAtMost = value
            case .failedQuiet: settings.failedTurns.quietMinutes = value
            case .failedCoalesce: settings.failedTurns.coalesceMinutes = value
            case .disconnectCount: settings.disconnects.count = value
            case .disconnectWindow: settings.disconnects.windowMinutes = value
            default: return false
            }
        }
        return true
    }

    /// Up to two decimals, without trailing zeros: 15, 7.5.
    static func number(_ value: Double) -> String {
        let rounded = (value * 100).rounded() / 100
        return rounded == rounded.rounded() && abs(rounded) < 1e15 ? String(Int(rounded)) : String(rounded)
    }
}

/// Spec section 9.4's Settings: rules, the collector, watched status components, data and general.
///
/// Every write goes through `UserActions` into the database the collector created (ruling R27), so
/// until its first run Settings shows the defaults read-only and says why. Launchd and login-item
/// changes (the interval, Rebuild's kickstart, Open at login) are the installed copy's only
/// (ruling R24); the interval and collector on/off reuse the collector view's `LaunchAgentManager`
/// path, whose failures show in `LaunchAgentError`'s words.
@MainActor @Observable final class SettingsModel {
    enum Section: Hashable { case rules, components, data, general }

    struct ComponentRow: Equatable, Identifiable {
        var name: String
        var watched: Bool
        /// A saved name the status page no longer lists.
        var missing: Bool
        var id: String { name }
        var label: String { missing ? "\(name) \(Copy.componentMissing)" : name }
    }

    struct ComponentGroup: Equatable, Identifiable {
        /// The status source's id.
        var id: String
        var name: String
        /// False until the collector has stored the page's component list.
        var loaded: Bool
        var rows: [ComponentRow]
    }

    /// Spec section 4's retention table (`Retention`), shown, not edited **(plan call)**.
    static let retention: [(label: String, kept: String)] = [
        ("Responses and their speed points", "\(Retention.responseDays) days"),
        ("Events, episodes, incidents, failed turns, disconnects and accepted baselines", "Kept"),
        ("Collector run records", "\(Retention.runDays) days"),
    ]

    @ObservationIgnored let live: LiveStore
    @ObservationIgnored let collector: CollectorViewModel
    @ObservationIgnored let sources: [SourceSummary]
    let login: LoginItem
    /// The dashboard window applies a newly chosen appearance.
    @ObservationIgnored var appearanceChanged: (Appearance) -> Void = { _ in }

    /// Whether the collector's database exists; until then nothing can be stored (ruling R27).
    private(set) var databaseReady = false
    private(set) var rules = RuleSettings.defaults
    /// Ruling R16's note while the stored rules can't be used.
    private(set) var rulesNote: String?
    /// Entries not yet saved: an invalid one stays in its field beside its message.
    private(set) var drafts: [RuleParameter: String] = [:]
    private(set) var parameterErrors: [RuleParameter: [String]] = [:]
    private(set) var intervalDraft: String?
    private(set) var intervalError: String?
    private(set) var watched = SettingKey.watchedComponents.defaultValue
    private(set) var componentGroups: [ComponentGroup] = []
    private(set) var appearance = SettingKey.appearance.defaultValue
    private(set) var confirmingRebuild = false
    /// A failed save or action, by section.
    private(set) var errors: [Section: String] = [:]
    private(set) var loadError: String?
    @ObservationIgnored private var pages: [String: [String]] = [:]

    init(live: LiveStore, collector: CollectorViewModel, sources: [SourceSummary], login: LoginItem) {
        self.live = live
        self.collector = collector
        self.sources = sources
        self.login = login
    }

    private var actions: UserActions { collector.actions }
    var canManage: Bool { collector.canManage }
    var firstRunNote: String? { databaseReady ? nil : Copy.settingsAfterFirstRun }
    var installedCopyNote: String? { canManage ? nil : Copy.settingsInstalledCopyOnly }
    var rebuildConfirmation: String { Copy.rebuildConfirmation(days: CollectorRun.lookbackDays) }
    var canRebuild: Bool { canManage && databaseReady }

    /// Rereads the stored settings, the status pages' component lists and the login item.
    func load() {
        login.refresh()
        do {
            let loaded = try live.read { store, _ in
                (try store.usableRules(), try store.value(.watchedComponents), try store.value(.appearance),
                 try statusSources.map { ($0.id, try store.components(source: $0.id).map(\.name)) })
            }
            databaseReady = loaded != nil
            if let (usable, watched, appearance, pages) = loaded {
                rules = usable.rules
                rulesNote = usable.problems.isEmpty ? nil : Copy.storedRulesUnusable
                self.watched = watched
                self.appearance = appearance
                self.pages = Dictionary(pages, uniquingKeysWith: { first, _ in first })
            } else {
                rules = .defaults
                rulesNote = nil
                watched = SettingKey.watchedComponents.defaultValue
                appearance = SettingKey.appearance.defaultValue
                pages = [:]
            }
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
        componentGroups = groups()
    }

    // MARK: Rules

    /// The field's text: an unsaved entry, or the stored value.
    func text(_ parameter: RuleParameter) -> String { drafts[parameter] ?? parameter.text(in: rules) }

    /// Typing into a field, before it is committed.
    func setDraft(_ parameter: RuleParameter, _ text: String) {
        guard databaseReady else { return }
        drafts[parameter] = text
    }

    func edit(_ parameter: RuleParameter, _ text: String) {
        setDraft(parameter, text)
        commit(parameter)
    }

    /// Saves the parameter's entry when the edited rules pass `RuleSettings.validationErrors`;
    /// otherwise shows why beside it and stores nothing.
    func commit(_ parameter: RuleParameter) {
        guard databaseReady, let text = drafts[parameter] else { return }
        if text.trimmingCharacters(in: .whitespaces) == parameter.text(in: rules) {
            drafts[parameter] = nil
            parameterErrors[parameter] = nil
            return
        }
        var candidate = rules
        guard parameter.apply(text, to: &candidate) else {
            parameterErrors[parameter] = [Copy.invalidRuleParameter(field: parameter.field)]
            return
        }
        let problems = candidate.validationErrors()
        guard problems.isEmpty else {
            parameterErrors[parameter] = problems
            return
        }
        if save(candidate) {
            drafts[parameter] = nil
            parameterErrors[parameter] = nil
        }
    }

    func isOn(_ rule: SettingsRule, _ toggle: RuleSwitch) -> Bool { toggle.value(rule.switches(in: rules)) }

    func set(_ rule: SettingsRule, _ toggle: RuleSwitch, _ on: Bool) {
        guard databaseReady else { return }
        var candidate = rules
        rule.set(toggle, on, in: &candidate)
        save(candidate)
    }

    /// Spec section 9.4's Reset to default, for one rule; its unsaved entries go too.
    func resetToDefault(_ rule: SettingsRule) {
        guard databaseReady else { return }
        var candidate = rules
        rule.reset(in: &candidate)
        if save(candidate) {
            for parameter in rule.parameters {
                drafts[parameter] = nil
                parameterErrors[parameter] = nil
            }
        }
    }

    func errors(for rule: SettingsRule) -> [String] {
        rule.parameters.flatMap { parameterErrors[$0] ?? [] }
    }

    @discardableResult private func save(_ candidate: RuleSettings) -> Bool {
        do {
            try actions.set(.rules, candidate)
            rules = candidate
            rulesNote = nil
            errors[.rules] = nil
            return true
        } catch {
            errors[.rules] = error.localizedDescription
            return false
        }
    }

    // MARK: Collector

    var intervalText: String { intervalDraft ?? String(collector.intervalMinutes) }

    func setIntervalDraft(_ text: String) {
        guard databaseReady, canManage else { return }
        intervalDraft = text
    }

    func editInterval(_ text: String) async {
        setIntervalDraft(text)
        await commitInterval()
    }

    /// Validates with `Settings.intervalError`, then changes it through the collector view's
    /// `LaunchAgentManager` path; a launchd failure shows as the collector's error. The draft stays
    /// until this change is done, so a failed change, or one the collector view couldn't start
    /// because another was running (which says so), can be committed again.
    func commitInterval() async {
        guard databaseReady, canManage, let text = intervalDraft else { return }
        guard let minutes = Int(text.trimmingCharacters(in: .whitespaces)), Settings.intervalError(minutes) == nil else {
            intervalError = Copy.intervalError(min: Settings.intervalRange.lowerBound, max: Settings.intervalRange.upperBound)
            return
        }
        intervalError = nil
        guard minutes != collector.intervalMinutes else {
            intervalDraft = nil
            return
        }
        switch await collector.changeInterval(minutes) {
        case .done: intervalDraft = nil
        case .failed: break
        case .busy: intervalError = Copy.collectorChangeRunning
        }
    }

    // MARK: Watched status components

    func setWatched(_ name: String, _ on: Bool) {
        guard databaseReady else { return }
        var list = watched
        if on {
            if !list.contains(name) { list.append(name) }
        } else {
            list.removeAll { $0 == name }
        }
        do {
            try actions.set(.watchedComponents, list)
            watched = list
            errors[.components] = nil
        } catch {
            errors[.components] = error.localizedDescription
        }
        componentGroups = groups()
    }

    /// The status sources the usage sources name, once each.
    private var statusSources: [(id: String, name: String)] {
        var seen: Set<String> = []
        return sources.compactMap { seen.insert($0.statusSourceID).inserted ? ($0.statusSourceID, $0.statusName) : nil }
    }

    /// Each page's components in its order; saved names no page lists follow in the first group.
    private func groups() -> [ComponentGroup] {
        let listed = Set(pages.values.joined())
        var groups = statusSources.map { source in
            let names = pages[source.id] ?? []
            return ComponentGroup(
                id: source.id, name: source.name, loaded: !names.isEmpty,
                rows: names.map { ComponentRow(name: $0, watched: watched.contains($0), missing: false) })
        }
        guard !groups.isEmpty else { return [] }
        let anyLoaded = !listed.isEmpty
        groups[0].rows += watched.filter { !listed.contains($0) }.map { ComponentRow(name: $0, watched: true, missing: anyLoaded) }
        return groups
    }

    // MARK: Data

    /// Rebuild from Codex logs asks first (`Copy.rebuildConfirmation`).
    func requestRebuild() {
        guard canRebuild else { return }
        confirmingRebuild = true
    }

    func cancelRebuild() { confirmingRebuild = false }

    /// The alert's Rebuild button: stores the rebuild request, then kicks the job so the collector
    /// applies it now. Closing the alert clears `confirmingRebuild` before the button's task runs,
    /// so the alert itself is the confirmation and only `canRebuild` is checked here.
    func confirmRebuild() async {
        guard canRebuild else { return }
        confirmingRebuild = false
        do {
            try actions.requestRebuild()
            try await actions.checkNow()
            errors[.data] = nil
        } catch {
            errors[.data] = error.localizedDescription
        }
    }

    // MARK: General

    /// Spec section 3's Open at login, the only way the app registers after its first launch
    /// (ruling R32). The choice is stored first, and the system changes only once that worked; if
    /// the system change then fails, the stored setting goes back to the system's state, so the
    /// two never disagree.
    func setOpenAtLogin(_ on: Bool) {
        guard canManage, databaseReady else { return }
        do {
            try actions.set(.openAtLogin, on)
        } catch {
            errors[.general] = error.localizedDescription
            return
        }
        login.setEnabled(on)
        guard login.enabled != on else {
            errors[.general] = nil
            return
        }
        // The system didn't change (the login item's error says why): store its state again.
        do {
            try actions.set(.openAtLogin, login.enabled)
            errors[.general] = nil
        } catch {
            errors[.general] = error.localizedDescription
        }
    }

    /// Spec section 9.4's dashboard appearance; the dashboard window applies it at once.
    func setAppearance(_ appearance: Appearance) {
        guard databaseReady else { return }
        do {
            try actions.set(.appearance, appearance)
            self.appearance = appearance
            errors[.general] = nil
            appearanceChanged(appearance)
        } catch {
            errors[.general] = error.localizedDescription
        }
    }
}

// MARK: - View

/// The Settings section of the dashboard window, in the dashboard's cluster style.
struct SettingsView: View {
    let model: SettingsModel

    var body: some View {
        VStack(alignment: .leading, spacing: 26) {
            if let note = model.firstRunNote {
                Text(note).foregroundStyle(Theme.swiftUI(Theme.dim))
            }
            if let error = model.loadError {
                AlertLine(color: Theme.red, text: error)
            }
            RulesSection(model: model)
            CollectorSettingsSection(model: model)
            ComponentsSection(model: model)
            DataSection(model: model)
            GeneralSection(model: model)
        }
        .frame(maxWidth: 760, alignment: .leading)
        .font(.system(size: 13))
        .foregroundStyle(Theme.swiftUI(Theme.readout))
        .disabled(!model.databaseReady)
    }
}

/// A dim note under a control.
private struct Note: View {
    let text: String
    var body: some View { Text(text).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim)) }
}

private struct Separator: View {
    var body: some View { Rectangle().fill(Theme.swiftUI(Theme.housing)).frame(height: 1) }
}

private struct RulesSection: View {
    let model: SettingsModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Rules")
            if let note = model.rulesNote { AlertLine(color: Theme.amber, text: note) }
            if let error = model.errors[.rules] { AlertLine(color: Theme.red, text: error) }
            VStack(alignment: .leading, spacing: 0) {
                ForEach(SettingsRule.allCases) { rule in
                    Separator()
                    RuleRow(model: model, rule: rule).padding(.vertical, 10)
                }
                Separator()
            }
        }
    }
}

private struct RuleRow: View {
    let model: SettingsModel
    let rule: SettingsRule

    var body: some View {
        let enabled = model.isOn(rule, .enabled)
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 10) {
                Toggle(rule.title, isOn: binding(.enabled)).toggleStyle(.switch).controlSize(.small).labelsHidden()
                    .accessibilityLabel(rule.title)
                Text(rule.title).font(.system(size: 13, weight: .medium))
                    .foregroundStyle(enabled ? Theme.swiftUI(Theme.readout) : Theme.swiftUI(Theme.dim))
                Spacer(minLength: 8)
                Button("Reset to default") { model.resetToDefault(rule) }.buttonStyle(DashboardButtonStyle(quiet: true))
            }
            if let summary = rule.summary {
                Text(summary).foregroundStyle(Theme.swiftUI(Theme.dim)).padding(.leading, 46)
            }
            ForEach([0, 1], id: \.self) { line in
                let parameters = rule.parameters.filter { $0.line == line }
                if !parameters.isEmpty {
                    HStack(spacing: 6) {
                        ForEach(parameters) { parameter in
                            if !parameter.label.before.isEmpty { Text(parameter.label.before).foregroundStyle(Theme.swiftUI(Theme.dim)) }
                            ParameterField(model: model, parameter: parameter)
                            if !parameter.label.after.isEmpty { Text(parameter.label.after).foregroundStyle(Theme.swiftUI(Theme.dim)) }
                        }
                    }
                    .padding(.leading, 46)
                }
            }
            HStack(spacing: 16) {
                Toggle(RuleSwitch.notify.title, isOn: binding(.notify))
                Toggle(RuleSwitch.notifyOnClear.title, isOn: binding(.notifyOnClear))
            }
            .toggleStyle(.checkbox)
            .padding(.leading, 46)
            ForEach(model.errors(for: rule), id: \.self) { error in
                AlertLine(color: Theme.red, text: error).padding(.leading, 46)
            }
        }
    }

    private func binding(_ toggle: RuleSwitch) -> Binding<Bool> {
        Binding(get: { model.isOn(rule, toggle) }, set: { model.set(rule, toggle, $0) })
    }
}

/// A short numeric entry on the cluster: the sidebar's darker step, outlined in housing, or in red
/// while its entry is invalid.
private struct NumberFieldStyle: ViewModifier {
    let invalid: Bool

    func body(content: Content) -> some View {
        content
            .labelsHidden()
            .textFieldStyle(.plain)
            .multilineTextAlignment(.trailing)
            .monospacedDigit()
            .frame(width: 46)
            .padding(.horizontal, 6).padding(.vertical, 3)
            .background(RoundedRectangle(cornerRadius: 5).fill(Theme.swiftUI(Theme.sidebar)))
            .overlay {
                RoundedRectangle(cornerRadius: 5)
                    .strokeBorder(invalid ? Theme.swiftUI(Theme.red) : Theme.swiftUI(Theme.housing), lineWidth: invalid ? 1.5 : 1)
            }
    }
}

/// A rule parameter's entry: saved on Return or when focus leaves it.
private struct ParameterField: View {
    let model: SettingsModel
    let parameter: RuleParameter
    @FocusState private var focused: Bool

    var body: some View {
        let invalid = model.parameterErrors[parameter] != nil
        TextField(parameter.field, text: Binding(get: { model.text(parameter) }, set: { model.setDraft(parameter, $0) }))
            .modifier(NumberFieldStyle(invalid: invalid))
            .focused($focused)
            .onSubmit { model.commit(parameter) }
            .onChange(of: focused) { if !focused { model.commit(parameter) } }
            .accessibilityLabel(parameter.field)
    }
}

private struct CollectorSettingsSection: View {
    let model: SettingsModel
    @FocusState private var focused: Bool

    var body: some View {
        let collector = model.collector
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Collector")
            HStack(spacing: 8) {
                Text("Run every").foregroundStyle(Theme.swiftUI(Theme.dim))
                TextField("Interval in minutes", text: Binding(get: { model.intervalText }, set: { model.setIntervalDraft($0) }))
                    .modifier(NumberFieldStyle(invalid: model.intervalError != nil))
                    .focused($focused)
                    .onSubmit { Task { await model.commitInterval() } }
                    .onChange(of: focused) { if !focused { Task { await model.commitInterval() } } }
                    .disabled(!model.canManage || collector.busy)
                Text("minutes (\(Settings.intervalRange.lowerBound)–\(Settings.intervalRange.upperBound))").foregroundStyle(Theme.swiftUI(Theme.dim))
            }
            if let error = model.intervalError { AlertLine(color: Theme.red, text: error) }
            Toggle("Collector on", isOn: Binding(
                get: { collector.enabled },
                set: { on in Task { if on { await collector.turnOn() } else { await collector.turnOff() } } }))
                .toggleStyle(.switch).controlSize(.small)
                .disabled(!model.canManage || collector.busy || (collector.enabled && !collector.offersTurnOff))
            if let note = model.installedCopyNote { Note(text: note) }
            if model.databaseReady, let note = collector.firstRunNote { Note(text: note) }
            if let error = collector.error { AlertLine(color: Theme.red, text: error) }
        }
    }
}

private struct ComponentsSection: View {
    let model: SettingsModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Watched status components")
            ForEach(model.componentGroups) { group in
                VStack(alignment: .leading, spacing: 6) {
                    Text(group.name).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim))
                    if !group.loaded { Note(text: Copy.componentsNotLoaded) }
                    ForEach(group.rows) { row in
                        Toggle(isOn: Binding(get: { row.watched }, set: { model.setWatched(row.name, $0) })) {
                            HStack(spacing: 4) {
                                Text(row.name)
                                if row.missing { Text(Copy.componentMissing).foregroundStyle(Theme.swiftUI(Theme.dim)) }
                            }
                        }
                        .toggleStyle(.checkbox)
                        .accessibilityLabel(row.label)
                    }
                }
            }
            if let error = model.errors[.components] { AlertLine(color: Theme.red, text: error) }
        }
    }
}

private struct DataSection: View {
    let model: SettingsModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Data")
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                ForEach(SettingsModel.retention, id: \.label) { row in
                    GridRow {
                        Text(row.label).foregroundStyle(Theme.swiftUI(Theme.dim))
                        Text(row.kept)
                    }
                }
            }
            Button("Rebuild from Codex logs…") { model.requestRebuild() }
                .buttonStyle(DashboardButtonStyle(quiet: true))
                .disabled(!model.canRebuild)
            if let note = model.installedCopyNote { Note(text: note) }
            if let error = model.errors[.data] { AlertLine(color: Theme.red, text: error) }
        }
        .alert(
            "Rebuild from Codex logs?",
            isPresented: Binding(get: { model.confirmingRebuild }, set: { if !$0 { model.cancelRebuild() } })
        ) {
            Button("Rebuild") { Task { await model.confirmRebuild() } }
            Button("Cancel", role: .cancel) { model.cancelRebuild() }
        } message: {
            Text(model.rebuildConfirmation)
        }
    }
}

private struct GeneralSection: View {
    let model: SettingsModel

    var body: some View {
        let login = model.login
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "General")
            HStack(spacing: 10) {
                Toggle("Open at login", isOn: Binding(get: { login.enabled }, set: { model.setOpenAtLogin($0) }))
                    .toggleStyle(.switch).controlSize(.small)
                    .disabled(!model.canManage)
                Text(login.description).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim))
                if login.requiresApproval {
                    Button("Open Login Items Settings") { login.openSettings() }.buttonStyle(DashboardButtonStyle(quiet: true))
                }
            }
            if let note = model.installedCopyNote { Note(text: note) }
            if let error = login.error { AlertLine(color: Theme.red, text: error) }
            HStack(spacing: 10) {
                Text("Dashboard appearance").foregroundStyle(Theme.swiftUI(Theme.dim))
                Picker("Dashboard appearance", selection: Binding(get: { model.appearance }, set: { model.setAppearance($0) })) {
                    Text("Dark").tag(Appearance.dark)
                    Text("Light").tag(Appearance.light)
                    Text("Match system").tag(Appearance.system)
                }
                .labelsHidden().pickerStyle(.segmented).fixedSize()
            }
            Note(text: "The menu-bar panel always follows the system.")
            if let error = model.errors[.general] { AlertLine(color: Theme.red, text: error) }
        }
    }
}
