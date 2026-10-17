import SwiftUI
import BrewVersionCore

struct PopoverView: View {
    let controller: WatchController
    @State private var query = ""
    @State private var selected: PackageName?
    @FocusState private var focusedWatch: PackageName?
    @State private var removed: (entry: WatchEntry, index: Int)?
    @State private var undoGeneration = UUID()
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
                else { Text("Retry the failed action to save it.").font(.caption) }
            }
            SearchSection(controller: controller, query: $query)
            if query.isEmpty {
                ScrollView {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Watching").font(.headline)
                        Text("Checked every \(controller.state.interval.label), with alerts").font(.caption).foregroundStyle(.secondary)
                        if watches.isEmpty { Text("Search for a formula or cask to start watching it.").foregroundStyle(.secondary).padding(.vertical, 12) }
                        ForEach(watches, id: \.name) { entry in
                            WatchRowView(entry: entry, controller: controller) { remove(entry.name) }
                                .background(selected == entry.name ? Color.accentColor.opacity(0.08) : Color.clear, in: RoundedRectangle(cornerRadius: 6))
                                .contentShape(Rectangle()).focusable().focused($focusedWatch, equals: entry.name)
                                .onTapGesture { selected = entry.name; focusedWatch = entry.name }
                                .onKeyPress(.delete) { remove(entry.name); return .handled }
                        }
                        if let removed {
                            HStack {
                                Text("Stopped watching \(removed.entry.name.rawValue)").font(.caption)
                                Button("Undo") { controller.restore(removed.entry, at: removed.index); self.removed = nil; undoGeneration = UUID() }.disabled(!controller.canSave)
                            }
                        }
                        OtherUpdatesSection(controller: controller)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }.frame(maxHeight: 390)
            }
            Divider()
            HStack {
                IntervalMenu(controller: controller)
                Spacer()
                SettingsLink { Image(systemName: "gearshape") }.help("Settings…").accessibilityLabel("Settings…")
                Button { NSApp.terminate(nil) } label: { Image(systemName: "power") }.help("Quit Brew Version").accessibilityLabel("Quit Brew Version")
            }
            if let next = CheckSchedule.nextDue(lastCheck: controller.state.lastCheck, interval: controller.state.interval) {
                Text("Next check \(next.formatted(date: .omitted, time: .shortened))").font(.caption).foregroundStyle(.secondary)
            }
        }.padding(16).frame(width: 450)
        .onDeleteCommand { if query.isEmpty, let selected { remove(selected) } }
    }
    private func remove(_ name: PackageName) {
        guard let removal = controller.remove(name) else { return }
        removed = removal; selected = nil
        let generation = UUID(); undoGeneration = generation
        Task { try? await Task.sleep(for: .seconds(5)); if undoGeneration == generation { removed = nil } }
    }
}
