import SwiftUI
import BrewVersionCore

struct OtherUpdatesSection: View {
    let controller: WatchController
    let undo: WatchUndoAction
    var body: some View {
        if controller.state.showOtherUpdates && !controller.others.isEmpty {
            Divider()
            Button {
                controller.setOtherUpdatesCollapsed(!controller.state.otherUpdatesCollapsed)
            } label: {
                HStack {
                    Image(systemName: controller.state.otherUpdatesCollapsed ? "chevron.right" : "chevron.down")
                    Text("Other updates on this Mac").font(.headline)
                }
            }.buttonStyle(.plain).disabled(!controller.canSave)
            Text("At launch and daily, no alerts").font(.caption).foregroundStyle(.secondary)
            if !controller.state.otherUpdatesCollapsed {
                ForEach(Array(controller.others.enumerated()), id: \.offset) { _, row in
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text("\(row.listing.name.rawValue) · \(row.listing.kind.rawValue) · \(ReleaseID(row.listing).displayVersion)")
                            Text(statusText(row.listing, installed: row.installed)).font(.caption).foregroundStyle(.secondary)
                            if row.installed.source == .caskroomFallback {
                                Text("Version from Homebrew's records; the app may have updated itself.").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        Spacer()
                        Button("Watch") { Task { await undo.watch(row.listing.name, kind: row.listing.kind, controller: controller) } }.disabled(!controller.canSave)
                    }.padding(.vertical, 4)
                }
            }
        }
    }
}
