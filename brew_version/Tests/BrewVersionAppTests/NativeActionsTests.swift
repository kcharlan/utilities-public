import AppKit
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
        settings.show(); settings.show()
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
@MainActor private final class ChangeFlag { var changed = false }
private struct QuietNotifier: Notifier { func post(_ notice: Notice) async {} }
