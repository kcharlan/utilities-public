import SwiftUI
import BrewVersionCore

struct PopoverView: View {
    let controller: WatchController
    let notifier: UserNotifier
    let openSettings: () -> Void
    let focusGeneration: UUID
    @State private var search = SearchInput()
    private var query: String { search.text }
    @State private var selection = WatchRowSelection()
    @State private var undo = WatchUndoAction()
    private var watches: [WatchEntry] {
        controller.state.watched.sorted { $0.isAmber != $1.isAmber ? $0.isAmber : $0.name.rawValue < $1.name.rawValue }
    }
    private var title: String {
        let count = controller.amberCount
        if count > 0 { return count == 1 ? "1 watched update" : "\(count) watched updates" }
        let watched = watches.count
        return watched == 1 ? "Watching 1 package" : "Watching \(watched) packages"
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading) {
                    Text(title).font(.headline)
                    if let check = controller.state.lastCheck { Text("Checked \(check.formatted(date: .omitted, time: .shortened))").font(.caption).foregroundStyle(.secondary) }
                    else { Text("Not checked yet").font(.caption).foregroundStyle(.secondary) }
                }
                Spacer()
                Button { Task { await controller.checkNow() } } label: { Image(systemName: "arrow.clockwise") }
                    .accessibilityLabel("Check now").disabled(!controller.canSave || controller.isChecking)
            }
            if let error = controller.persistenceError {
                Text(error).font(.caption).foregroundStyle(.red).textSelection(.enabled)
                if !controller.canSave { Button("Retry") { controller.retryLoad(); Task { await controller.hydrateCatalog(); await controller.scheduledTick() } } }
                else if let hint = PersistencePresentation(issue: controller.persistenceIssue).saveHint { Text(hint).font(.caption) }
            }
            NotificationIssueView(notifier: notifier)
            SearchSection(controller: controller, undo: undo, input: search, focusGeneration: focusGeneration)
            if let removed = undo.removed {
                HStack {
                    Text("Stopped watching \(removed.entry.name.rawValue)").font(.caption)
                    Button("Undo") { undo.restore(controller: controller) }.disabled(!controller.canSave)
                }
                if undo.retryRequired {
                    Text("Undo couldn't be saved. Retry Undo before stopping another watch.")
                        .font(.caption).foregroundStyle(.red)
                }
            }
            if query.isEmpty {
                ScrollView {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Watching").font(.headline)
                        Text("Checked every \(controller.state.interval.label), with alerts").font(.caption).foregroundStyle(.secondary)
                        if watches.isEmpty { Text("Search for a formula or cask to start watching it.").foregroundStyle(.secondary).padding(.vertical, 12) }
                        ForEach(watches, id: \.name) { entry in
                            WatchRowView(entry: entry, controller: controller, canRemove: undo.canRemove) { remove(entry.name) }
                                .background(selection.name == entry.name ? Color.accentColor.opacity(0.08) : Color.clear, in: RoundedRectangle(cornerRadius: 6))
                                .background(WatchRowKeyboard(focusRequest: selection.name == entry.name ? selection.focusRequest : nil) { remove(entry.name) })
                                .contentShape(Rectangle())
                                .onTapGesture { selection.select(entry.name) }
                                .accessibilityElement(children: .contain)
                                .accessibilityLabel("Watching \(entry.name.rawValue)")
                                .accessibilityAddTraits(selection.name == entry.name ? .isSelected : [])
                                .accessibilityAction { selection.select(entry.name) }
                        }
                        OtherUpdatesSection(controller: controller, undo: undo)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }.frame(height: 390)
            }
            Divider()
            HStack {
                IntervalMenu(controller: controller)
                Spacer()
                Button(action: openSettings) { Image(systemName: "gearshape") }.help("Settings…").accessibilityLabel("Settings…")
                Button { NSApp.terminate(nil) } label: { Image(systemName: "power") }.help("Quit Brew Version").accessibilityLabel("Quit Brew Version")
            }
            Text(nextCheckText).font(.caption).foregroundStyle(.secondary)
        }.padding(16).frame(width: 450)
    }
    private var nextCheckText: String {
        switch controller.nextAutomaticCheck {
        case .blocked: "Automatic checks paused until state can be loaded"
        case .checking: "Checking now"
        case .ready: "Next check due"
        case .scheduled(let next): "Next check \(next.formatted(date: .omitted, time: .shortened))"
        case .waitingForNetwork(let next):
            if let next { "Offline: next check after \(next.formatted(date: .omitted, time: .shortened)) when connected" }
            else { "Offline: next check when connected" }
        }
    }
    private func remove(_ name: PackageName) {
        if undo.remove(name, controller: controller) { selection.clear() }
    }
}
