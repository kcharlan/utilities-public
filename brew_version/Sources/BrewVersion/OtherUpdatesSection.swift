import SwiftUI
import BrewVersionCore

struct OtherUpdatesSection: View {
    let controller: WatchController
    let undo: WatchUndoAction
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        if controller.state.showOtherUpdates {
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
            }.buttonStyle(.plain).disabled(!controller.canSave)
                .help("Installed packages Homebrew lists as newer, without alerts. Checked when the app opens and every \(controller.state.catalogInterval.label).")
                .accessibilityLabel("Other updates, \(controller.others.count), \(controller.state.otherUpdatesCollapsed ? "collapsed" : "expanded")")
            CatalogStatusLine(controller: controller)
            if !controller.state.otherUpdatesCollapsed {
                if controller.others.isEmpty {
                    Text(controller.state.lastCatalogFetch == nil && controller.catalog == nil
                         ? "Waiting for Homebrew's package list." : "Everything else installed is up to date.")
                        .font(.system(size: 11)).foregroundStyle(.secondary).padding(.vertical, 4)
                }
                ForEach(Array(controller.others.enumerated()), id: \.offset) { _, row in
                    PackageRow(name: row.listing.name, kind: row.listing.kind, listing: row.listing, installed: row.installed,
                               amber: true, watched: false, canSave: controller.canSave,
                               watch: { Task { await undo.watch(row.listing.name, kind: row.listing.kind, controller: controller) } })
                }
                if controller.hiddenSelfUpdatingCount > 0 {
                    Text(hiddenText(controller.hiddenSelfUpdatingCount))
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true).padding(.top, 2)
                }
            }
        }
    }
    private func hiddenText(_ count: Int) -> String {
        let apps = count == 1 ? "1 self-updating app is" : "\(count) self-updating apps are"
        return "\(apps) hidden because its real installed version can't be read. You can show them in Settings."
    }
}

/// How current the Other updates list is: refreshing, failed, or last updated.
struct CatalogStatusLine: View {
    let controller: WatchController
    var body: some View {
        Group {
            if controller.isRefreshingCatalog {
                Text("Updating…").foregroundStyle(.secondary)
            } else if let error = controller.catalogRefreshError {
                Label {
                    Text("Couldn't update. \(error) " + (controller.state.lastCatalogFetch.map { "Showing the list from \(catalogTimestamp($0))." } ?? ""))
                        .fixedSize(horizontal: false, vertical: true)
                } icon: { Image(systemName: "exclamationmark.triangle.fill") }
                    .foregroundStyle(.orange)
            } else if let fetched = controller.state.lastCatalogFetch {
                Text("Updated \(catalogTimestamp(fetched))").foregroundStyle(.secondary)
            } else {
                Text("Not updated yet").foregroundStyle(.secondary)
            }
        }.font(.system(size: 11)).frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Today's refreshes show only the time; older ones include the date.
func catalogTimestamp(_ date: Date, now: Date = Date(), calendar: Calendar = .current) -> String {
    calendar.isDate(date, inSameDayAs: now)
        ? date.formatted(date: .omitted, time: .shortened)
        : date.formatted(date: .abbreviated, time: .shortened)
}
