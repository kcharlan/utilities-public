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
                    if input.invalid { Label(CheckInterval.validationMessage(), systemImage: "exclamationmark.triangle.fill").font(.caption).foregroundStyle(.red) }
                }
                Section("Other updates") {
                    Toggle("Show other updates on this Mac", isOn: Binding(get: { controller.state.showOtherUpdates }, set: { controller.setShowOtherUpdates($0) })).disabled(!controller.canSave)
                }
                Section("General") {
                    Toggle("Open at login", isOn: Binding(get: { login.enabled }, set: { login.setEnabled($0) }))
                    Text(login.description).font(.caption).foregroundStyle(.secondary)
                    if login.requiresApproval { Button("Open Login Items Settings") { login.openSettings() } }
                    if let error = login.error { Label(error, systemImage: "exclamationmark.triangle.fill").font(.caption).foregroundStyle(.red).textSelection(.enabled) }
                    NotificationIssueView(notifier: notifier)
                    if let error = controller.persistenceError { Label(error, systemImage: "exclamationmark.triangle.fill").font(.caption).foregroundStyle(.red).textSelection(.enabled) }
                    if let error = controller.catalogWriteError { Label(error, systemImage: "exclamationmark.triangle.fill").font(.caption).foregroundStyle(.red).textSelection(.enabled) }
                }
            }.formStyle(.grouped).toggleStyle(.switch)
            Text("Brew Version \(BrewVersionRelease.version)").font(.caption).foregroundStyle(.secondary).frame(maxWidth: .infinity).padding(.bottom, 14)
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
            Label(error, systemImage: "exclamationmark.triangle.fill").font(.caption).foregroundStyle(.red).textSelection(.enabled)
            Button("Retry notifications") { Task { await notifier.retry() } }
        }
    }
}
