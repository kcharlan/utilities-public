import SwiftUI
import BrewVersionCore

struct OtherUpdatesSection: View {
    let controller: WatchController
    let undo: WatchUndoAction
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        if controller.state.showOtherUpdates && !controller.others.isEmpty {
            Divider().padding(.vertical, 4)
            Button {
                withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.15)) {
                    controller.setOtherUpdatesCollapsed(!controller.state.otherUpdatesCollapsed)
                }
            } label: {
                HStack {
                    Text("Other updates")
                    Spacer()
                    Text("\(controller.others.count)")
                    Image(systemName: "chevron.right").rotationEffect(.degrees(controller.state.otherUpdatesCollapsed ? 0 : 90))
                }.font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
            }.buttonStyle(.plain).disabled(!controller.canSave).help("Installed packages checked at launch and daily, without alerts")
                .accessibilityLabel("Other updates, \(controller.others.count), \(controller.state.otherUpdatesCollapsed ? "collapsed" : "expanded")")
            if !controller.state.otherUpdatesCollapsed {
                ForEach(Array(controller.others.enumerated()), id: \.offset) { _, row in
                    PackageRow(name: row.listing.name, kind: row.listing.kind, listing: row.listing, installed: row.installed,
                               amber: true, watched: false, canSave: controller.canSave,
                               watch: { Task { await undo.watch(row.listing.name, kind: row.listing.kind, controller: controller) } })
                }
            }
        }
    }
}
