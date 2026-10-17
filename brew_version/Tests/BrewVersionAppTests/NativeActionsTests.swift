import AppKit
import SwiftUI
import Observation
import ServiceManagement
import Testing
import UserNotifications
@testable import BrewVersionCore
@testable import BrewVersion

@MainActor private final class NotificationServiceStub: NotificationService {
    var status: UNAuthorizationStatus = .notDetermined
    var allowed = false
    var fail = false
    var delivered: [String] = []
    func authorizationStatus() async -> UNAuthorizationStatus { status }
    func requestAuthorization() async throws -> Bool {
        if fail { throw CocoaError(.fileReadUnknown) }
        status = allowed ? .authorized : .denied
        return allowed
    }
    func post(_ request: UNNotificationRequest) async throws {
        if fail { throw CocoaError(.fileWriteUnknown) }
        delivered.append(request.content.title)
    }
}
@MainActor private final class LoginServiceStub: LoginService {
    var status: SMAppService.Status = .notRegistered
    var fail = false
    var settingsOpened = false
    func register() throws { if fail { throw CocoaError(.fileWriteUnknown) }; status = .requiresApproval }
    func unregister() throws { status = .notRegistered }
    func openSettings() { settingsOpened = true }
}
@MainActor private final class PopoverPresenterStub: PopoverPresenting {
    var opens = 0
    func showPopover() { opens += 1 }
}

@MainActor struct NativeActionsTests {
    @Test func sharedWatchSelectionRenewsNativeFocusWithoutStealingSearchEditing() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-accessible-rows-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let store = WatchStore(fileURL: home.appendingPathComponent("state.json"))
        var state = AppState.initial; state.showOtherUpdates = false
        state.watched = ["synthetic-first", "synthetic-second"].map { name in
            var entry = WatchEntry(name: PackageName(name)!, kind: .formula)
            entry.lastListing = Listing(name: entry.name, kind: .formula, version: "2-synthetic")
            entry.installed = InstalledVersion(version: "1-synthetic", source: .cellar)
            return entry
        }
        try store.save(state)
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: store, notifier: QuietNotifier())
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 450, height: 700), styleMask: [.borderless], backing: .buffered, defer: true)
        defer { window.makeFirstResponder(nil) }
        let selection = WatchRowSelection()
        let undo = WatchUndoAction()
        let search = NSTextView(frame: .zero); search.string = "synthetic"
        window.contentView?.addSubview(search)
        for entry in state.watched {
            let row = WatchRowKeyboardView()
            row.remove = { _ = undo.remove(entry.name, controller: controller) }
            window.contentView?.addSubview(row)
            // Mouse and default accessibility actions both call this selection.
            selection.select(entry.name)
            row.updateFocusRequest(selection.focusRequest)
            #expect(selection.name == entry.name)
            #expect(window.firstResponder === row)
            #expect(window.firstResponder?.tryToPerform(#selector(NSResponder.deleteBackward(_:)), with: nil) == true)
            #expect(!store.load().state.watched.contains { $0.name == entry.name })
            undo.restore(controller: controller)
            #expect(store.load().state.watched == state.watched)
            #expect(window.makeFirstResponder(search))
            search.setSelectedRange(NSRange(location: search.string.count, length: 0))
            row.updateFocusRequest(selection.focusRequest)
            #expect(window.firstResponder === search)
            #expect(window.firstResponder?.tryToPerform(#selector(NSResponder.deleteBackward(_:)), with: nil) == true)
            #expect(search.string == (entry.name.rawValue == "synthetic-first" ? "syntheti" : "synthet"))
            #expect(store.load().state.watched == state.watched)
            selection.select(entry.name)
            row.updateFocusRequest(selection.focusRequest)
            #expect(window.firstResponder === row)
            let rebuiltRow = WatchRowKeyboardView()
            rebuiltRow.focusRequest = selection.focusRequest
            window.contentView?.addSubview(rebuiltRow)
            #expect(window.makeFirstResponder(search))
            rebuiltRow.updateFocusRequest(selection.focusRequest)
            #expect(window.firstResponder === search)
            selection.clear()
            #expect(selection.name == nil)
        }
    }
    @Test func appearanceAppliesToPopoverAndActualHostedContent() {
        let popover = NSPopover()
        popover.contentViewController = NSHostingController(rootView: Text("Synthetic appearance"))
        for name in [NSAppearance.Name.darkAqua, .aqua] {
            PopoverAppearance.apply(NSAppearance(named: name), to: popover)
            #expect(popover.appearance?.name == name)
            #expect(popover.contentViewController?.view.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == name)
        }
    }
    @Test func fullPopoverKeepsWatchingViewportAfterFreshHostingWithOtherHidden() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-popover-layout-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let store = WatchStore(fileURL: home.appendingPathComponent("state.json"))
        var state = AppState.initial
        state.interval = CheckInterval(minutes: 47)!
        state.showOtherUpdates = false
        state.watched = ["synthetic-formula", "synthetic-cask"].map { WatchEntry(name: PackageName($0)!, kind: .formula) }
        try store.save(state)
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: store, notifier: QuietNotifier())
        let notifier = UserNotifier(service: NotificationServiceStub())
        for _ in 0..<2 {
            let view = NSHostingView(rootView: PopoverView(controller: controller, notifier: notifier, openSettings: {}, focusGeneration: UUID()))
            view.frame.size = view.fittingSize
            view.layoutSubtreeIfNeeded()
            let scrolls = nativeScrollViews(view)
            #expect(scrolls.count == 1)
            #expect(scrolls.first?.frame.height == 390)
            #expect(view.fittingSize.height > 390)
            #expect(view.fittingSize.height < 800)
        }
    }
    @Test func watchRowNativeDeleteRoutesBothKeysAndPreservesSearchEditing() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-delete-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let store = WatchStore(fileURL: home.appendingPathComponent("state.json"))
        let entry = WatchEntry(name: PackageName("synthetic-delete")!, kind: .formula)
        var state = AppState.initial; state.watched = [entry]
        try store.save(state)
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: store, notifier: QuietNotifier())
        let undo = WatchUndoAction()
        let row = WatchRowKeyboardView()
        row.remove = { _ = undo.remove(entry.name, controller: controller) }
        for code: UInt16 in [51, 117] {
            let event = try #require(NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: 0,
                context: nil, characters: "\u{7f}", charactersIgnoringModifiers: "\u{7f}", isARepeat: false, keyCode: code))
            row.keyDown(with: event)
            #expect(controller.state.watched.isEmpty && store.load().state.watched.isEmpty)
            undo.restore(controller: controller)
            #expect(store.load().state.watched == [entry])
        }
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 300, height: 200), styleMask: [.borderless], backing: .buffered, defer: true)
        window.contentView?.addSubview(row)
        let search = NSTextView(frame: NSRect(x: 0, y: 0, width: 200, height: 100))
        search.string = "synthetic"
        window.contentView?.addSubview(search)
        #expect(window.makeFirstResponder(row))
        #expect(window.firstResponder?.tryToPerform(#selector(NSResponder.deleteBackward(_:)), with: nil) == true)
        #expect(controller.state.watched.isEmpty)
        undo.restore(controller: controller)
        #expect(window.makeFirstResponder(search))
        search.setSelectedRange(NSRange(location: 9, length: 0))
        #expect(window.firstResponder?.tryToPerform(#selector(NSResponder.deleteBackward(_:)), with: nil) == true)
        #expect(search.string == "syntheti")
        #expect(store.load().state.watched == [entry])
        window.makeFirstResponder(nil)
    }
    @Test func normalAppReopenShowsPopoverWithOrWithoutSettingsVisible() {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-reopen-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let notifier = UserNotifier(service: NotificationServiceStub())
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: notifier)
        let presenter = PopoverPresenterStub()
        let delegate = AppDelegate(controller: controller, notifier: notifier, status: presenter)
        #expect(presenter.opens == 0)
        #expect(delegate.applicationShouldHandleReopen(NSApplication.shared, hasVisibleWindows: false))
        #expect(delegate.applicationShouldHandleReopen(NSApplication.shared, hasVisibleWindows: true))
        #expect(presenter.opens == 2)
    }
    @Test func appKitLifecycleRetainsStandardQuitAndEditingCommands() {
        let menu = ApplicationMenu.make()
        let commands = menu.items.flatMap { $0.submenu?.items ?? [] }
        #expect(commands.first(where: { $0.keyEquivalent == "q" })?.action == #selector(NSApplication.terminate(_:)))
        #expect(commands.first(where: { $0.keyEquivalent == "v" })?.action == #selector(NSText.paste(_:)))
        #expect(commands.first(where: { $0.keyEquivalent == "a" })?.action == #selector(NSText.selectAll(_:)))
        let undo = commands.first { $0.keyEquivalent == "z" && $0.keyEquivalentModifierMask == [.command] }
        let redo = commands.first { $0.keyEquivalent == "z" && $0.keyEquivalentModifierMask == [.command, .shift] }
        #expect(undo?.action == Selector(("undo:")))
        #expect(redo?.action == Selector(("redo:")))
        #expect(undo != nil && undo?.target == nil)
        #expect(redo != nil && redo?.target == nil)
    }
    @Test func statusObservationPublishesAmberChanges() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-status-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let store = WatchStore(fileURL: home.appendingPathComponent("state.json"))
        var state = AppState.initial
        let listing = Listing(name: PackageName("synthetic-status")!, kind: .formula, version: "2-synthetic")
        var entry = WatchEntry(name: listing.name, kind: listing.kind)
        entry.lastListing = listing
        entry.installed = InstalledVersion(version: "1-synthetic", source: .cellar)
        state.watched = [entry]
        try store.save(state)
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: store, notifier: QuietNotifier())
        var values: [String] = []
        let observation = StatusObservation(controller: controller) { values.append($0.accessibility) }
        #expect(values == ["Brew Version, 1 watched update available"])
        controller.skip(entry.name)
        for _ in 0..<100 where values.count < 2 { await Task.yield() }
        #expect(values.last == "Brew Version, no watched updates")
        withExtendedLifetime(observation) {}
    }
    @Test func notificationDenialErrorAndPostingRetryAreObservable() async {
        let service = NotificationServiceStub()
        let notifier = UserNotifier(service: service)
        let observed = ChangeFlag()
        withObservationTracking { _ = notifier.lastError } onChange: { Task { @MainActor in observed.changed = true } }
        await notifier.requestAuthorization()
        await Task.yield()
        #expect(notifier.lastError?.contains("System Settings") == true)
        #expect(observed.changed)
        service.status = .authorized
        await notifier.requestAuthorization()
        #expect(notifier.lastError == nil)
        service.fail = true
        await notifier.post(Notice(name: PackageName("synthetic-notice")!, title: "synthetic notice", body: "synthetic body"))
        #expect(notifier.lastError != nil)
        service.fail = false
        await notifier.retry()
        #expect(notifier.lastError == nil)
        #expect(service.delivered == ["synthetic notice"])
        service.status = .notDetermined; service.fail = true
        await notifier.requestAuthorization()
        #expect(notifier.lastError?.contains("authorization") == true)
    }
    @Test func settingsReuseRefreshAndLoginApprovalAction() {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-settings-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: QuietNotifier())
        let service = LoginServiceStub()
        let login = LoginItem(service: service)
        var windows: [NSWindow] = []
        var activations = 0
        let settings = SettingsWindowController(controller: controller, notifier: UserNotifier(service: NotificationServiceStub()), login: login,
            activate: { activations += 1 }, present: { windows.append($0) })
        settings.setAppearance(NSAppearance(named: .darkAqua))
        settings.show(); settings.show()
        #expect(windows[0].effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua)
        settings.setAppearance(NSAppearance(named: .aqua))
        #expect(windows[0].effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .aqua)
        #expect(windows.count == 2)
        #expect(windows[0] === windows[1])
        #expect(!windows[0].isReleasedWhenClosed)
        #expect(activations == 2)
        login.setEnabled(true)
        #expect(login.requiresApproval)
        login.openSettings()
        #expect(service.settingsOpened)
        service.status = .enabled
        settings.windowDidBecomeKey(Notification(name: NSWindow.didBecomeKeyNotification))
        #expect(login.description == "Enabled")
        service.fail = true; login.setEnabled(true)
        #expect(login.error != nil)
        login.setEnabled(false)
        #expect(!login.enabled && login.error == nil)
    }
    @Test func homepageActionRejectsUnsafeSchemes() {
        var opened: [URL] = []
        let action = HomepageAction(open: { opened.append($0) })
        for value in ["file:///synthetic", "javascript:synthetic", "mailto:synthetic@example.invalid", "ftp://example.invalid", "/synthetic"] {
            #expect(!action.open(URL(string: value)!))
        }
        #expect(action.open(URL(string: "https://example.invalid/synthetic")!))
        #expect(action.open(URL(string: "http://example.invalid/synthetic")!))
        #expect(opened.count == 2)
    }
    @Test func customIntervalRetainsInvalidAndFailedSaveInput() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-interval-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let file = home.appendingPathComponent("state.json")
        let live = WatchStore(fileURL: file)
        try live.save(.initial)
        var io = WatchStoreIO.live
        io.replace = { _, _ in throw CocoaError(.fileWriteUnknown) }
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: WatchStore(fileURL: file, io: io), notifier: QuietNotifier())
        let input = CustomIntervalInput(minutes: "9")
        #expect(!input.save(controller: controller))
        #expect(input.invalid && input.minutes == "9")
        input.minutes = "47"
        #expect(!input.save(controller: controller))
        #expect(input.minutes == "47" && controller.state.interval == .standard)
        #expect(controller.persistenceIssue == .saveFailure)
        let recovered = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: live, notifier: QuietNotifier())
        #expect(input.save(controller: recovered))
        #expect(recovered.state.interval.minutes == 47)
        #expect(live.load().state.interval.minutes == 47)
    }
    @Test func nativeActionPolicies() {
        #expect(StatusPresentation(amberCount: 0).accessibility == "Brew Version, no watched updates")
        #expect(StatusPresentation(amberCount: 1).accessibility == "Brew Version, 1 watched update available")
        #expect(StatusPresentation(amberCount: 3).accessibility == "Brew Version, 3 watched updates available")
        #expect(!PopoverActions.shouldAllowTransientClose(event: .leftMouseDown, mouseInButton: true))
        #expect(!PopoverActions.shouldAllowTransientClose(event: .leftMouseUp, mouseInButton: true))
        #expect(PopoverActions.shouldAllowTransientClose(event: .keyDown, mouseInButton: true))
        #expect(PopoverActions.shouldAllowTransientClose(event: .leftMouseDown, mouseInButton: false))
        var shown = true
        PopoverActions.toggle(isShown: shown, show: { shown = true }, close: { shown = false })
        #expect(!shown)
        #expect(installedSourceNote(InstalledVersion(version: "1-synthetic", source: .caskroomFallback)) != nil)
        #expect(installedSourceNote(InstalledVersion(version: "1-synthetic", source: .appBundle)) == nil)
        #expect(PersistencePresentation(issue: .recoveryWarning).saveHint == nil)
        #expect(PersistencePresentation(issue: .saveFailure).saveHint != nil)
        #expect(IntervalSelection(current: CheckInterval(minutes: 47)!).options.contains(CheckInterval(minutes: 47)!))
        let custom = CustomIntervalInput(minutes: "9")
        #expect(custom.validInterval == nil)
        #expect(custom.minutes == "9")
        custom.minutes = "47"
        #expect(custom.validInterval?.minutes == 47)
    }
}
@MainActor private func nativeScrollViews(_ view: NSView) -> [NSScrollView] {
    (view as? NSScrollView).map { [$0] } ?? view.subviews.flatMap(nativeScrollViews)
}
@MainActor private final class ChangeFlag { var changed = false }
private struct QuietNotifier: Notifier { func post(_ notice: Notice) async {} }
