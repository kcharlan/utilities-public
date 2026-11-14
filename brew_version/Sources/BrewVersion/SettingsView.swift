import SwiftUI
import BrewVersionCore

@MainActor @Observable final class SettingsFocus {
    var intervalRequest = 0
    func requestInterval() { intervalRequest += 1 }
}

struct SettingsView: View {
    let controller: WatchController
    let notifier: UserNotifier
    let login: LoginItem
    var focus = SettingsFocus()
    @State private var input = CustomIntervalInput()
    @FocusState private var intervalFocused: Bool
    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section("Checking") {
                    Picker("Check every", selection: Binding(get: { controller.state.interval }, set: { controller.setInterval($0); input.minutes = String($0.minutes); input.invalid = false })) {
                        ForEach(IntervalSelection(current: controller.state.interval).options, id: \.self) { interval in Text(interval.label).tag(interval) }
                    }.pickerStyle(.menu).disabled(!controller.canSave)
                    LabeledContent("Custom interval") {
                        HStack(spacing: 5) {
                            TextField("Minutes", text: $input.minutes).labelsHidden().frame(width: 55).multilineTextAlignment(.trailing)
                                .accessibilityLabel("Custom interval in minutes").focused($intervalFocused).onSubmit(save)
                            Stepper("Minutes", value: Binding(get: { Int(input.minutes) ?? controller.state.interval.minutes }, set: { input.minutes = String($0); save() }), in: CheckInterval.allowedMinutes)
                                .labelsHidden().accessibilityLabel("Custom interval minutes")
                            Text("minutes").foregroundStyle(.secondary)
                            Button("Apply", action: save).controlSize(.small).disabled(!controller.canSave)
                        }
                    }
                    if input.invalid { InlineWarning(message: CheckInterval.validationMessage()) }
                    VStack(alignment: .leading, spacing: 3) {
                        Toggle("Alert only when brew can install", isOn: Binding(get: { controller.state.confirmWithBrew }, set: { controller.setConfirmWithBrew($0) }))
                            .disabled(!controller.canSave || !controller.brewGateAvailable)
                        Text("Runs brew update when a watched package has a new version, and waits to alert until brew lists it.")
                            .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        if !controller.brewGateAvailable { Text("Homebrew was not found.").font(.caption).foregroundStyle(.secondary) }
                    }
                    Picker("While waiting, check every", selection: Binding(get: { controller.state.announcedInterval }, set: { controller.setAnnouncedInterval($0) })) {
                        ForEach(IntervalSelection(current: controller.state.announcedInterval, presets: CheckInterval.announcedPresets).options, id: \.self) { interval in Text(interval.label).tag(interval) }
                    }.pickerStyle(.menu).disabled(!controller.canSave || !controller.state.confirmWithBrew || !controller.brewGateAvailable)
                        .help("How often to run brew update while a watched package has a new version that brew does not list yet. Never slower than the regular check.")
                }
                Section("Other updates") {
                    Toggle("Show other updates on this Mac", isOn: Binding(get: { controller.state.showOtherUpdates }, set: { controller.setShowOtherUpdates($0) })).disabled(!controller.canSave)
                    VStack(alignment: .leading, spacing: 3) {
                        Toggle("Show a dot on the menu bar mug", isOn: Binding(get: { controller.state.badgeOtherUpdates }, set: { controller.setBadgeOtherUpdates($0) }))
                            .disabled(!controller.canSave || !controller.state.showOtherUpdates)
                        Text("Uses the mug's color while this list has updates. Watched updates still show amber. Never sends notifications.")
                            .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                    Picker("Check every", selection: Binding(get: { controller.state.catalogInterval }, set: { controller.setCatalogInterval($0) })) {
                        ForEach(IntervalSelection(current: controller.state.catalogInterval, presets: CheckInterval.catalogPresets).options, id: \.self) { interval in Text(interval.label).tag(interval) }
                    }.pickerStyle(.menu).disabled(!controller.canSave || !controller.state.showOtherUpdates)
                        .help("Each check downloads Homebrew's full package list, about 7 MB. The list also refreshes when the app opens.")
                    VStack(alignment: .leading, spacing: 3) {
                        Toggle("Include self-updating apps", isOn: Binding(get: { controller.state.includeSelfUpdating }, set: { controller.setIncludeSelfUpdating($0) }))
                            .disabled(!controller.canSave || !controller.state.showOtherUpdates)
                        Text("Also list apps that update themselves when their real installed version can't be read, like brew outdated --greedy.")
                            .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                    CatalogStatusLine(controller: controller)
                }
                Section("General") {
                    Toggle("Open at login", isOn: Binding(get: { login.enabled }, set: { value in login.setEnabled(value); if login.error == nil { notifier.log.record("setting", ["key": "openAtLogin", "value": .bool(login.enabled)]) } }))
                    Text(login.description).font(.caption).foregroundStyle(.secondary)
                    if login.requiresApproval { Button("Open Login Items Settings") { login.openSettings() } }
                    if let error = login.error { InlineWarning(message: error) }
                    Button("Show log in Finder") { LogRevealAction().reveal() }
                    Button("Send test notification") { Task { await notifier.sendTestNotification() } }
                        .disabled(notifier.isSendingTestNotification)
                        .help("Send a Brew Version test notification. Click it to open the popover.")
                    NotificationIssueView(notifier: notifier)
                    if let error = controller.persistenceError { InlineWarning(message: error) }
                    if let error = controller.catalogWriteError { InlineWarning(message: error) }
                }
            }.formStyle(.grouped).toggleStyle(.switch)
            Text(BrewVersionRelease.versionLine).font(.caption).foregroundStyle(.secondary).frame(maxWidth: .infinity).padding(.bottom, 14)
        }.frame(width: 460)
            .onAppear { login.refresh(); input.minutes = String(controller.state.interval.minutes); intervalFocused = focus.intervalRequest > 0 }
            .onChange(of: focus.intervalRequest) { _, _ in input.minutes = String(controller.state.interval.minutes); input.invalid = false; intervalFocused = true }
    }
    private func save() { _ = input.save(controller: controller) }
}

struct NotificationIssueView: View {
    let notifier: UserNotifier
    var body: some View {
        if let error = notifier.lastError {
            InlineWarning(message: error)
            Button("Retry notifications") { Task { await notifier.retry() } }
        }
    }
}

/// Warnings must keep their recovery instructions when a popover proposes a
/// short height. Let their text grow vertically; the package list yields space.
struct InlineWarning: View {
    let message: String
    var body: some View {
        Label {
            Text(message).fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: "exclamationmark.triangle.fill")
        }.font(.system(size: 11)).foregroundStyle(.red)
            .frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled).help(message)
    }
}
