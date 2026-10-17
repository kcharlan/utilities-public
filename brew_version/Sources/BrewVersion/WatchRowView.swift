import SwiftUI
import AppKit
import BrewVersionCore

func copyText(_ value: String) { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(value, forType: .string) }
func upgradeCommand(_ listing: Listing) -> String { "brew upgrade " + (listing.kind == .cask ? "--cask " : "") + listing.name.rawValue }
func statusText(_ listing: Listing, installed: InstalledVersion?) -> String {
    switch updateStatus(listing: listing, installed: installed) {
    case .upToDate, .ahead: "Installed"
    case .updateAvailable(let value): "You have \(value)"
    case .notInstalled: "Not installed"
    case .unversioned: "Updates itself"
    }
}
struct WatchRowView: View {
    let entry: WatchEntry
    let controller: WatchController
    let remove: () -> Void
    @State private var hovering = false
    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(entry.name.rawValue).fontWeight(.medium)
                    Text(entry.kind?.rawValue ?? "").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text(entry.lastListing.map { ReleaseID($0).displayVersion } ?? "—").monospacedDigit()
                }
                if let error = entry.lastError { Text(error).font(.caption).foregroundStyle(.red) }
                else if let listing = entry.lastListing { Text(statusText(listing, installed: entry.installed)).font(.caption).foregroundStyle(.secondary) }
                if entry.isAmber, let listing = entry.lastListing {
                    HStack {
                        Button("Copy upgrade command") { copyText(upgradeCommand(listing)) }
                        Button("Skip this version") { controller.skip(entry.name) }.disabled(!controller.canSave)
                    }.font(.caption)
                }
            }
            Menu { actions } label: { Image(systemName: "ellipsis") }
                .menuStyle(.borderlessButton).frame(width: 22).opacity(hovering ? 1 : 0)
                .accessibilityLabel("Actions for \(entry.name.rawValue)")
        }.padding(8)
        .background(entry.isAmber ? Color.orange.opacity(0.15) : Color.clear, in: RoundedRectangle(cornerRadius: 6))
        .onHover { hovering = $0 }.contextMenu { actions }
    }
    @ViewBuilder private var actions: some View {
        if let listing = entry.lastListing {
            Button("Copy upgrade command") { copyText(upgradeCommand(listing)) }
            if let homepage = listing.homepage { Button("Open homepage") { NSWorkspace.shared.open(homepage) } }
            if entry.isAmber { Button("Skip this version") { controller.skip(entry.name) }.disabled(!controller.canSave) }
        }
        Button("Stop watching \(entry.name.rawValue)", action: remove).disabled(!controller.canSave)
    }
}
