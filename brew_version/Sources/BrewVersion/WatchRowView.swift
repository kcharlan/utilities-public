import SwiftUI
import AppKit
import BrewVersionCore

func copyText(_ value: String) { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(value, forType: .string) }
func packageCommand(_ listing: Listing, installed: InstalledVersion?) -> String {
    "brew \(installed == nil ? "install" : "upgrade") " + (listing.kind == .cask ? "--cask " : "") + listing.name.rawValue
}
func statusText(_ listing: Listing, installed: InstalledVersion?) -> String {
    switch updateStatus(listing: listing, installed: installed) {
    case .upToDate, .ahead: "Installed"
    case .updateAvailable(let value): "You have \(value)"
    case .notInstalled: "Not installed"
    case .unversioned: "Updates itself"
    }
}

/// Shared columns and controls for watches, updates, results and suggestions.
struct PackageRow: View {
    let name: PackageName
    let kind: PackageKind?
    var listing: Listing?
    var installed: InstalledVersion?
    var previousVersion: String?
    var amber = false
    var error: String?
    var compact = false
    var suggestionInstalled = false
    var selected = false
    var watched: Bool? = nil
    var canSave = true
    var canRemove = true
    var watch: (() -> Void)?
    var skip: (() -> Void)?
    var remove: (() -> Void)?
    @State private var hovering = false
    var title: String { name.shortName }
    var tapLabel: String? { name.tap?.description }
    var accessibilityName: String { name.rawValue }
    private var actionsVisible: Bool { hovering || selected }
    private var commandTitle: String { installed == nil ? "Copy install command" : "Copy upgrade command" }
    var body: some View {
        HStack(alignment: .top, spacing: 7) {
            Circle().fill(amber ? Color(nsColor: .systemOrange) : .clear).frame(width: 7, height: 7).padding(.top, 5).accessibilityHidden(true)
            Image(systemName: kind == .cask ? "macwindow" : "terminal").foregroundStyle(.secondary)
                .frame(width: 15).padding(.top, 2).accessibilityLabel(kind?.rawValue ?? "Package")
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(title).font(.system(size: 13, weight: .medium)).lineLimit(1).truncationMode(.middle)
                        .help(name.rawValue).accessibilityLabel(accessibilityName).layoutPriority(1)
                    if let tapLabel { Text(tapLabel).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle).help(name.rawValue) }
                    Spacer(minLength: 2)
                    if !compact, let listing {
                        HStack(spacing: 3) {
                            if amber, let old = installed?.version ?? previousVersion {
                                Text(old).foregroundStyle(.secondary)
                                Text("→").foregroundStyle(.secondary)
                            }
                            Text(ReleaseID(listing).displayVersion).fontWeight(amber ? .semibold : .regular)
                                .foregroundStyle(amber ? Color(nsColor: .systemOrange) : Color.primary)
                        }.font(.system(size: 11)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.8)
                            .help(ReleaseID(listing).displayVersion)
                    }
                }
                HStack(alignment: .top, spacing: 4) {
                    VStack(alignment: .leading, spacing: 2) {
                        if let error { Text(error).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true) }
                        else if compact { Text((kind?.rawValue ?? "Package") + (suggestionInstalled ? " · Installed" : "")).foregroundStyle(.secondary) }
                        else if let listing { Text(statusText(listing, installed: installed)).foregroundStyle(.secondary) }
                        if let note = installedSourceNote(installed), !compact { Text(note).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }
                    }.font(.system(size: 11)).frame(maxWidth: .infinity, alignment: .leading)
                    if let watched {
                        if watched { Label("Watching", systemImage: "checkmark").font(.system(size: 11)).foregroundStyle(.secondary) }
                        else if let watch { Button("Watch", action: watch).buttonStyle(.bordered).controlSize(.small).buttonBorderShape(.capsule).clipShape(Capsule()).contentShape(Capsule()).disabled(!canSave) }
                    } else if !compact {
                        HStack(spacing: 8) {
                            if let listing, amber {
                                Button { copyText(packageCommand(listing, installed: installed)) } label: { Image(systemName: "doc.on.doc") }
                                    .help(commandTitle).accessibilityLabel(commandTitle)
                                if let skip { Button(action: skip) { Image(systemName: "forward.end") }.help("Skip this version").accessibilityLabel("Skip this version").disabled(!canSave) }
                            }
                            if remove != nil {
                                Menu { actions } label: { Image(systemName: "ellipsis") }
                                    .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                                    .help("Actions for \(name.rawValue)").accessibilityLabel("Actions for \(name.rawValue)")
                            }
                        }.buttonStyle(.borderless).font(.system(size: 11))
                            .opacity(actionsVisible ? 1 : 0).allowsHitTesting(actionsVisible).accessibilityHidden(!actionsVisible)
                    }
                }
            }
        }.padding(.vertical, 6).padding(.horizontal, 8)
            .background {
                RoundedRectangle(cornerRadius: 6)
                    .fill(selected ? AnyShapeStyle(Color.accentColor.opacity(0.14)) : AnyShapeStyle(.quaternary))
                    .opacity(actionsVisible ? 1 : 0)
            }
            .contentShape(RoundedRectangle(cornerRadius: 6)).onHover { hovering = $0 }.contextMenu { actions }
    }
    @ViewBuilder private var actions: some View {
        if let listing {
            Button(commandTitle) { copyText(packageCommand(listing, installed: installed)) }
            if let homepage = listing.homepage, HomepageAction.isAvailable(homepage) { Button("Open homepage") { HomepageAction().open(homepage) } }
            if amber, let skip { Button("Skip this version", action: skip).disabled(!canSave) }
        }
        if let remove { Button("Stop watching \(name.rawValue)", action: remove).disabled(!canSave || !canRemove) }
    }
}

struct WatchRowView: View {
    let entry: WatchEntry
    let controller: WatchController
    var canRemove = true
    var selected = false
    let remove: () -> Void
    var body: some View {
        PackageRow(name: entry.name, kind: entry.kind, listing: entry.lastListing, installed: entry.installed,
                   previousVersion: entry.lastSeenRelease?.displayVersion, amber: entry.isAmber, error: entry.lastError,
                   selected: selected, canSave: controller.canSave, canRemove: canRemove,
                   skip: { controller.skip(entry.name) }, remove: remove)
    }
}

/// Explicit intrinsic height avoids a zero viewport in an AppKit host. The
/// measurement then hugs short content while keeping large lists scrollable.
struct ContentSizedScroll<Content: View>: View {
    var maximum: CGFloat = 390
    var initial: CGFloat = 120
    @ViewBuilder var content: () -> Content
    @State private var measured: CGFloat?
    var body: some View {
        ScrollView {
            content().frame(maxWidth: .infinity, alignment: .leading)
                .background(GeometryReader { geometry in Color.clear.preference(key: ContentHeight.self, value: geometry.size.height) })
        }.frame(height: min(maximum, max(1, measured ?? initial)))
            .onPreferenceChange(ContentHeight.self) { measured = $0 }
    }
}
private struct ContentHeight: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}
