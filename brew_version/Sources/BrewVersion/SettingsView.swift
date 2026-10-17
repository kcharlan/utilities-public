import SwiftUI
import BrewVersionCore

struct SettingsView: View {
    let controller: WatchController
    let notifier: UserNotifier
    let login: LoginItem
    var body: some View {
        Form {
            Text("Brew Version \(BrewVersionRelease.version)").font(.headline)
            IntervalMenu(controller: controller)
            Toggle("Show other updates on this Mac", isOn: Binding(get: { controller.state.showOtherUpdates }, set: { controller.setShowOtherUpdates($0) }))
                .disabled(!controller.canSave)
            Toggle("Open at login", isOn: Binding(get: { login.enabled }, set: { login.setEnabled($0) }))
            Text(login.description).font(.caption).foregroundStyle(.secondary)
            if login.requiresApproval { Button("Open Login Items Settings") { login.openSettings() } }
            NotificationIssueView(notifier: notifier)
            if let error = login.error { Text(error).foregroundStyle(.red).textSelection(.enabled) }
            if let error = controller.persistenceError { Text(error).foregroundStyle(.red).textSelection(.enabled) }
        }.padding(24).frame(width: 390).onAppear { login.refresh() }
    }
}

struct NotificationIssueView: View {
    let notifier: UserNotifier
    var body: some View {
        if let error = notifier.lastError {
            Text(error).font(.caption).foregroundStyle(.red).textSelection(.enabled)
            Button("Retry notifications") { Task { await notifier.retry() } }
        }
    }
}
