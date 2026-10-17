import SwiftUI
import BrewVersionCore

struct PopoverView: View {
    let controller: WatchController
    let notifier: UserNotifier
    let openSettings: () -> Void
    let focusGeneration: UUID
    var openCustomInterval: (() -> Void)? = nil
    @State var search = SearchInput()
    @State var selection = WatchRowSelection()
    @State private var undo = WatchUndoAction()
    @State private var warningHeight: CGFloat = 0
    private var watches: [WatchEntry] {
        controller.state.watched.sorted { $0.isAmber != $1.isAmber ? $0.isAmber : $0.name.rawValue < $1.name.rawValue }
    }
    private var title: String {
        let count = controller.amberCount
        if count > 0 { return count == 1 ? "1 update" : "\(count) updates" }
        return watches.isEmpty ? "Nothing watched yet" : "All up to date"
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.system(size: 13, weight: .semibold))
                    Text(controller.state.lastCheck.map { "Checked \($0.formatted(date: .omitted, time: .shortened))" } ?? "Not checked yet")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                }
                Spacer()
                Button { Task { await controller.checkNow() } } label: {
                    if controller.isChecking { ProgressView().controlSize(.small).frame(width: 16, height: 16) }
                    else { Image(systemName: "arrow.clockwise") }
                }.buttonStyle(.borderless).help("Check now").accessibilityLabel("Check now").disabled(!controller.canSave || controller.isChecking)
            }
            if hasWarnings {
                VStack(alignment: .leading, spacing: 10) {
                    if let error = controller.persistenceError {
                        InlineWarning(message: error)
                        if !controller.canSave { Button("Retry") { controller.retryLoad(); Task { await controller.hydrateCatalog(); await controller.scheduledTick() } } }
                        else if let hint = PersistencePresentation(issue: controller.persistenceIssue).saveHint { Text(hint).font(.system(size: 11)).fixedSize(horizontal: false, vertical: true) }
                    }
                    if let error = controller.catalogWriteError { InlineWarning(message: error) }
                    NotificationIssueView(notifier: notifier)
                }.background(GeometryReader { geometry in Color.clear.preference(key: WarningHeight.self, value: geometry.size.height) })
                    .onPreferenceChange(WarningHeight.self) { warningHeight = $0 }
            }
            SearchSection(controller: controller, undo: undo, input: search, focusGeneration: focusGeneration, maximumHeight: listMaximum)
            if let removed = undo.removed {
                HStack {
                    Text("Stopped watching \(removed.entry.name.rawValue)").font(.system(size: 11))
                    Button("Undo") { undo.restore(controller: controller) }.disabled(!controller.canSave)
                }
                if undo.retryRequired { Text("Undo couldn't be saved. Retry Undo before stopping another watch.").font(.system(size: 11)).foregroundStyle(.red) }
            }
            if search.text.isEmpty {
                ContentSizedScroll(maximum: listMaximum, initial: watches.isEmpty ? 112 : min(listMaximum, CGFloat(watches.count * 52 + 24))) {
                    VStack(alignment: .leading, spacing: 2) {
                        HStack { Text("Watching"); Spacer(); Text("\(watches.count)") }
                            .font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                            .help("Checked every \(controller.state.interval.label), with update alerts").padding(.bottom, 4)
                        if watches.isEmpty {
                            VStack(spacing: 5) {
                                Image(systemName: "mug").font(.system(size: 28)).foregroundStyle(.tertiary)
                                Text("Nothing watched yet").fontWeight(.medium)
                                Text("Search above to add a formula or cask.").font(.system(size: 11)).foregroundStyle(.secondary)
                            }.frame(maxWidth: .infinity).padding(.vertical, 12)
                        }
                        ForEach(watches, id: \.name) { entry in
                            WatchRowView(entry: entry, controller: controller, canRemove: undo.canRemove, selected: selection.name == entry.name) { remove(entry.name) }
                                .background(WatchRowKeyboard(focusRequest: selection.name == entry.name ? selection.focusRequest : nil) { remove(entry.name) })
                                .contentShape(Rectangle()).onTapGesture { selection.select(entry.name) }
                                .accessibilityElement(children: .contain).accessibilityLabel("Watching \(entry.name.rawValue)")
                                .accessibilityAddTraits(selection.name == entry.name ? .isSelected : [])
                                .accessibilityAction { selection.select(entry.name) }
                        }
                        OtherUpdatesSection(controller: controller, undo: undo)
                    }
                }
            }
            Divider()
            HStack(spacing: 8) {
                IntervalMenu(controller: controller, openCustom: openCustomInterval ?? openSettings)
                Spacer(minLength: 0)
                Text(nextCheckText).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1).help(nextCheckText)
                Button(action: openSettings) { Image(systemName: "gearshape") }.help("Settings…").accessibilityLabel("Settings…")
                Button { NSApp.terminate(nil) } label: { Image(systemName: "power") }.help("Quit Brew Version").accessibilityLabel("Quit Brew Version")
            }.buttonStyle(.borderless)
        }.font(.system(size: 13)).padding(12).frame(width: 340)
    }
    private var hasWarnings: Bool { controller.persistenceError != nil || controller.catalogWriteError != nil || notifier.lastError != nil }
    private var listMaximum: CGFloat {
        // Measure wrapped warning copy rather than assuming a single-line label.
        // Reserve a positive initial budget before the first geometry update.
        let warnings = hasWarnings ? (warningHeight > 0 ? warningHeight : 120) + 10 : 0
        return max(100, 390 - warnings - (undo.removed == nil ? 0 : 40))
    }
    private var nextCheckText: String {
        switch controller.nextAutomaticCheck {
        case .blocked: "Checks paused"
        case .checking: "Checking now"
        case .ready: "Next check due"
        case .scheduled(let next): "Next check \(next.formatted(date: .omitted, time: .shortened))"
        case .waitingForNetwork: "Waiting for network"
        }
    }
    private func remove(_ name: PackageName) {
        if undo.remove(name, controller: controller) { selection.clear() }
    }
}
private struct WarningHeight: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}
