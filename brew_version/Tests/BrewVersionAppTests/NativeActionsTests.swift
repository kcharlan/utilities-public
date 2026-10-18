import AppKit
import SwiftUI
import Observation
import ServiceManagement
import Testing
import UserNotifications
@testable import BrewVersionCore
@testable import BrewVersion

@MainActor final class NotificationServiceStub: NotificationService {
    var status: UNAuthorizationStatus = .notDetermined
    var allowed = false
    var fail = false
    var authorizationFailure: String?
    var postingFailure: String?
    var delivered: [String] = []
    var requests: [UNNotificationRequest] = []
    var authorizationRequests = 0
    var postingGate: (@MainActor () async -> Void)?
    func authorizationStatus() async -> UNAuthorizationStatus { status }
    func requestAuthorization() async throws -> Bool {
        authorizationRequests += 1
        if let authorizationFailure { throw SyntheticAuthorizationFailure(message: authorizationFailure) }
        if fail { throw CocoaError(.fileReadUnknown) }
        status = allowed ? .authorized : .denied
        return allowed
    }
    func post(_ request: UNNotificationRequest) async throws {
        requests.append(request)
        await postingGate?()
        if let postingFailure { throw SyntheticAuthorizationFailure(message: postingFailure) }
        if fail { throw CocoaError(.fileWriteUnknown) }
        delivered.append(request.content.title)
    }
}
private struct SyntheticAuthorizationFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}
@MainActor final class LoginServiceStub: LoginService {
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
private struct ReopenCatalogTransport: HTTPTransport {
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        let json = url.path.contains("/cask")
            ? #"[{"token":"synthetic-fallback","version":"2-synthetic","auto_updates":true,"artifacts":[{"app":["Synthetic Missing.app"]}]}]"#
            : #"[{"name":"synthetic-catalog","versions":{"stable":"2-synthetic"}}]"#
        return HTTPResponse(status: 200, body: Data(json.utf8))
    }
}

@MainActor struct NativeActionsTests {
    @Test func tapRowTitleAndCommand() {
        let name = PackageName("synthetic-owner/synthetic-tap/synthetic-tool")!
        let row = PackageRow(name: name, kind: .formula)
        #expect(row.title == "synthetic-tool")
        #expect(row.tapLabel == "synthetic-owner/synthetic-tap")
        #expect(row.accessibilityName == name.rawValue)
        for kind in [PackageKind.formula, .cask] {
            let listing = Listing(name: name, kind: kind, version: "4.5.6")
            let flag = kind == .cask ? "--cask " : ""
            #expect(packageCommand(listing, installed: nil) == "brew install " + flag + name.rawValue)
            #expect(packageCommand(listing, installed: .init(version: "1.0", source: .cellar)) == "brew upgrade " + flag + name.rawValue)
        }
        #expect(PackageRow(name: PackageName("synthetic-tool")!, kind: .formula).tapLabel == nil)
    }
    @Test func tapStatusCopy() {
        #expect(tapStatusMessages(failures: 0, uncheckable: 0).isEmpty)
        #expect(tapStatusMessages(failures: 1, uncheckable: 1) == ["Couldn't check 1 tap package.", "1 tap package can't be checked."])
        #expect(tapStatusMessages(failures: 3, uncheckable: 2) == ["Couldn't check 3 tap packages.", "2 tap packages can't be checked."])
    }
    @Test func successfulTestKeepsAuthorizationBlockedPackageRetryVisible() async {
        let service = NotificationServiceStub(); service.status = .denied
        let notifier = UserNotifier(service: service)
        let package = Notice(name: PackageName("synthetic-authorization")!, title: "Synthetic authorization-blocked update", body: "Synthetic authorization retry body.")
        await notifier.post(package)
        service.status = .authorized
        await notifier.sendTestNotification()
        #expect(notifier.lastError != nil)
        await notifier.retry()
        #expect(service.requests.filter { $0.content.title == package.title && $0.content.body == package.body }.count == 1)
        #expect(notifier.lastError == nil)
    }
    @Test func testNotificationPreservesFailedPackageRecoveryForEveryOutcome() async {
        for outcome in ["success", "denied", "posting-failure"] {
            let service = NotificationServiceStub(); service.status = .authorized
            let notifier = UserNotifier(service: service)
            let package = Notice(name: PackageName("synthetic-package")!, title: "Synthetic package update", body: "Synthetic package changed from 1-synthetic to 2-synthetic.")
            service.postingFailure = "Synthetic package posting failed"
            await notifier.post(package)
            service.postingFailure = outcome == "posting-failure" ? "Synthetic test posting failed" : nil
            service.status = outcome == "denied" ? .denied : .authorized
            await notifier.sendTestNotification()
            #expect(notifier.lastError?.contains("Synthetic package posting failed") == true)
            service.postingFailure = nil; service.status = .authorized
            await notifier.retry()
            let packageRequests = service.requests.filter { $0.content.title == package.title }
            #expect(packageRequests.count == 2)
            #expect(packageRequests.last?.content.body == package.body)
            #expect(notifier.lastError == nil)
        }
    }
    @Test func completedTestNotificationCannotEraseOverlappingPackageFailure() async {
        let service = NotificationServiceStub(); service.status = .authorized
        let notifier = UserNotifier(service: service)
        let package = Notice(name: PackageName("synthetic-overlap")!, title: "Synthetic overlapping package update", body: "Synthetic package retry body.")
        service.postingGate = {
            service.postingGate = nil
            service.postingFailure = "Synthetic overlapping package failure"
            await notifier.post(package)
            service.postingFailure = nil
        }
        await notifier.sendTestNotification()
        #expect(notifier.lastError?.contains("Synthetic overlapping package failure") == true)
        await notifier.retry()
        #expect(service.requests.filter { $0.content.title == package.title && $0.content.body == package.body }.count == 2)
        #expect(notifier.lastError == nil)
    }
    @Test func successfulPackageNotificationPreservesFailedTestRecovery() async {
        let service = NotificationServiceStub(); service.status = .authorized
        let notifier = UserNotifier(service: service)
        service.postingFailure = "Synthetic test failure"
        await notifier.sendTestNotification()
        service.postingFailure = nil
        await notifier.post(Notice(name: PackageName("synthetic-other")!, title: "Synthetic other update", body: "Synthetic other body."))
        #expect(notifier.lastError?.contains("Synthetic test failure") == true)
        await notifier.retry()
        #expect(service.requests.filter { $0.content.title == "Brew Version test notification" }.count == 2)
        #expect(notifier.lastError == nil)
    }
    @Test func olderPackageCompletionCannotEraseNewerPackageFailure() async {
        let service = NotificationServiceStub(); service.status = .authorized
        let notifier = UserNotifier(service: service)
        let newer = Notice(name: PackageName("synthetic-newer")!, title: "Synthetic newer update", body: "Synthetic newer retry body.")
        service.postingGate = {
            service.postingGate = nil
            service.postingFailure = "Synthetic newer package failure"
            await notifier.post(newer)
            service.postingFailure = nil
        }
        await notifier.post(Notice(name: PackageName("synthetic-older")!, title: "Synthetic older update", body: "Synthetic older body."))
        #expect(notifier.lastError?.contains("Synthetic newer package failure") == true)
        await notifier.retry()
        #expect(service.requests.filter { $0.content.title == newer.title && $0.content.body == newer.body }.count == 2)
        #expect(notifier.lastError == nil)
    }
    @Test func testNotificationUsesAuthorizationAndKeepsFailedRequestRetryable() async throws {
        let service = NotificationServiceStub()
        let notifier = UserNotifier(service: service)
        await notifier.sendTestNotification()
        #expect(service.authorizationRequests == 1)
        #expect(service.requests.isEmpty)
        #expect(notifier.lastError?.contains("Notifications are off") == true)
        service.status = .authorized
        service.postingFailure = "Synthetic test posting failed"
        await notifier.retry()
        let failed = try #require(service.requests.first)
        #expect(failed.content.title == "Brew Version test notification")
        #expect(failed.content.body == "This is a test notification from Brew Version. Click to open the popover.")
        #expect(failed.trigger == nil)
        #expect(notifier.lastError?.contains("Synthetic test posting failed") == true)
        service.postingFailure = nil
        await notifier.retry()
        #expect(service.requests.count == 2)
        #expect(service.requests.last?.content.title == failed.content.title)
        #expect(service.requests.last?.content.body == failed.content.body)
        #expect(notifier.lastError == nil)
        #expect(!notifier.isSendingTestNotification)
    }
    @Test func testNotificationIgnoresDuplicateSendWhilePosting() async {
        let service = NotificationServiceStub(); service.status = .authorized
        let notifier = UserNotifier(service: service)
        service.postingGate = { await notifier.sendTestNotification() }
        await notifier.sendTestNotification()
        #expect(service.requests.count == 1)
        #expect(!notifier.isSendingTestNotification)
    }
    @Test func retainedStatusContentKeepsBoundedPreferredSizeAcrossAttachment() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-retained-host-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        for count in [0, 3, 12] {
            let fixture = home.appendingPathComponent("case-\(count)")
            let store = WatchStore(fileURL: fixture.appendingPathComponent("state.json"))
            var state = AppState.initial; state.showOtherUpdates = count == 3; state.otherUpdatesCollapsed = false
            // The fixture's one other update is a self-updating cask with no readable app.
            state.includeSelfUpdating = true
            state.watched = (0..<count).map {
                let listing = Listing(name: PackageName("synthetic-reopen-\($0)")!, kind: .formula, version: "2-synthetic")
                return WatchEntry(name: listing.name, kind: .formula, lastListing: listing)
            }
            try store.save(state)
            let prefix = fixture.appendingPathComponent("synthetic-prefix")
            try FileManager.default.createDirectory(at: prefix.appendingPathComponent("Cellar"), withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: prefix.appendingPathComponent("Caskroom/synthetic-fallback/1-synthetic"), withIntermediateDirectories: true)
            let controller = WatchController(transport: ReopenCatalogTransport(), installed: InstalledReader(prefixes: HomebrewPrefix.detectAll(candidates: [prefix]), applicationDirectories: []), store: store, notifier: QuietNotifier(), catalogClient: CatalogClient(transport: ReopenCatalogTransport(), cacheDirectory: fixture.appendingPathComponent("catalog")))
            if count == 3 { await controller.refreshCatalogIfDue(); #expect(controller.others.count == 1) }
            let notifier = UserNotifier(service: NotificationServiceStub())
            let settings = SettingsWindowController(controller: controller, notifier: notifier, login: LoginItem(service: LoginServiceStub()), activate: {}, present: { _ in })
            let focus = PopoverFocus()
            let host = StatusContent(controller: controller, notifier: notifier, settings: settings, focus: focus, accessory: nil).makeHostingController()
            let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: 340, height: 560), styleMask: [.borderless], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false
            defer { window.contentViewController = nil }
            for cycle in 0..<4 {
                focus.generation = UUID()
                window.appearance = NSAppearance(named: cycle.isMultiple(of: 2) ? .aqua : .darkAqua)
                host.viewWillAppear()
                window.contentViewController = host
                for _ in 0..<8 {
                    host.view.layoutSubtreeIfNeeded()
                    try await Task.sleep(for: .milliseconds(25))
                }
                #expect(host.preferredContentSize.width == 340)
                #expect(host.preferredContentSize.height > 100 && host.preferredContentSize.height <= 560)
                if count == 0 { #expect(host.preferredContentSize.height < 300) }
                if count == 3 { #expect(host.preferredContentSize.height < 500) }
                #expect((nativeScrollViews(host.view).first?.frame.height ?? 0) > 60)
                host.viewDidAppear()
                host.viewWillDisappear()
                window.contentViewController = nil
                host.viewDidDisappear()
                controller.popoverClosed()
                for _ in 0..<8 { try await Task.sleep(for: .milliseconds(25)) }
            }
        }
    }
    @Test func notificationFailuresKeepOneSentenceBoundary() async {
        for (description, sentence) in [("Synthetic failure", "Synthetic failure."), ("Synthetic failure.", "Synthetic failure."), ("Synthetic failure!", "Synthetic failure!"), ("Synthetic failure?", "Synthetic failure?"), ("Synthetic failure.\n", "Synthetic failure.")] {
            let service = NotificationServiceStub()
            service.authorizationFailure = description
            let notifier = UserNotifier(service: service)
            await notifier.requestAuthorization()
            #expect(notifier.lastError == "Notification authorization failed: \(sentence) Retry notifications.")
            service.authorizationFailure = nil; service.status = .authorized
            service.postingFailure = description
            await notifier.post(Notice(name: PackageName("synthetic-punctuation")!, title: "Synthetic notice", body: "Synthetic retry"))
            #expect(notifier.lastError == "Couldn't post notification: \(sentence) Retry notifications.")
        }
    }
    @Test func longNotificationWarningWrapsWithinMaintainedPopover() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-warning-layout-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let service = NotificationServiceStub()
        service.authorizationFailure = "Synthetic authorization was refused. Open System Settings, choose Notifications, select Brew Version, enable notifications, then retry."
        let notifier = UserNotifier(service: service)
        await notifier.requestAuthorization()
        let warning = try #require(notifier.lastError)
        #expect(warning.contains("enable notifications"))
        let notice = NSHostingView(rootView: VStack(alignment: .leading, spacing: 10) { NotificationIssueView(notifier: notifier) }.frame(width: 316))
        notice.frame.size = notice.fittingSize
        notice.layoutSubtreeIfNeeded()
        #expect(notice.fittingSize.height > 70)
        let store = WatchStore(fileURL: home.appendingPathComponent("state.json"))
        var state = AppState.initial; state.showOtherUpdates = false
        state.watched = (0..<12).map { WatchEntry(name: PackageName("synthetic-warning-\($0)")!, kind: .formula) }
        try store.save(state)
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: store, notifier: QuietNotifier())
        let settings = SettingsWindowController(controller: controller, notifier: notifier, login: LoginItem(service: LoginServiceStub()), activate: {}, present: { _ in })
        let host = StatusContent(controller: controller, notifier: notifier, settings: settings, focus: PopoverFocus(), accessory: nil).makeHostingController()
        let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: 340, height: 560), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentViewController = host
        defer { window.contentViewController = nil }
        host.view.frame.size = host.view.fittingSize
        host.view.layoutSubtreeIfNeeded()
        #expect(host.view.fittingSize.width == 340)
        #expect(host.view.fittingSize.height <= 560)
        let scroll = try #require(nativeScrollViews(host.view).first)
        #expect(scroll.frame.height > 80)
        let viewport = scroll.convert(scroll.bounds, to: host.view)
        let footerSpace = host.view.isFlipped ? host.view.bounds.maxY - viewport.maxY : viewport.minY - host.view.bounds.minY
        #expect(footerSpace >= 30)
    }
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
    /// Hosts a popover whose watch list must scroll, in an offscreen window.
    private func scrollingPopover(_ name: String) throws -> (window: NSWindow, host: NSHostingView<PopoverView>, scroll: NSScrollView, cleanup: () -> Void) {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-\(name)-" + UUID().uuidString)
        let store = WatchStore(fileURL: home.appendingPathComponent("state.json"))
        var state = AppState.initial; state.showOtherUpdates = false
        state.watched = (0..<16).map { index in
            let listing = Listing(name: PackageName("synthetic-scroll-\(index)")!, kind: .formula, version: "2.0")
            return WatchEntry(name: listing.name, kind: .formula, lastListing: listing)
        }
        try store.save(state)
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: store, notifier: QuietNotifier())
        let host = NSHostingView(rootView: PopoverView(controller: controller, notifier: UserNotifier(service: NotificationServiceStub()),
                                                       openSettings: {}, focusGeneration: UUID()))
        let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: 340, height: 600), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        host.frame = NSRect(origin: .zero, size: host.fittingSize)
        host.layoutSubtreeIfNeeded()
        let scroll = try #require(nativeScrollViews(host).first)
        return (window, host, scroll, { window.contentView = nil; try? FileManager.default.removeItem(at: home) })
    }
    @Test func listScrollBarTravelsInPopoverMargin() throws {
        let popover = try scrollingPopover("scroll-gutter"); defer { popover.cleanup() }
        let frame = popover.scroll.convert(popover.scroll.bounds, to: popover.host)
        // The scroll view starts with the content and reaches the popover's edge,
        // so its scroll bar sits in the side margin rather than over the rows.
        #expect(abs(frame.minX - 12) < 0.5)
        #expect(abs(frame.maxX - 340) < 0.5)
        #expect(ContentSizedScroll<EmptyView>.scrollerGutter == 12)
    }
    @Test func watchingHeaderStaysPinnedWhileRowsScroll() throws {
        let popover = try scrollingPopover("pinned-header"); defer { popover.cleanup() }
        let scroll = popover.scroll
        // The header strip at the top of the list must look the same before and
        // after scrolling: a pinned header stays, unpinned content would move.
        func headerStrip() -> Data? {
            let strip = NSRect(x: 0, y: scroll.contentView.isFlipped ? 0 : scroll.bounds.height - 18, width: scroll.bounds.width - 16, height: 18)
            guard let rep = scroll.bitmapImageRepForCachingDisplay(in: strip) else { return nil }
            scroll.cacheDisplay(in: strip, to: rep)
            return rep.representation(using: .png, properties: [:])
        }
        func rowStrip() -> Data? {
            let strip = NSRect(x: 0, y: scroll.contentView.isFlipped ? 60 : scroll.bounds.height - 78, width: scroll.bounds.width - 16, height: 18)
            guard let rep = scroll.bitmapImageRepForCachingDisplay(in: strip) else { return nil }
            scroll.cacheDisplay(in: strip, to: rep)
            return rep.representation(using: .png, properties: [:])
        }
        let headerBefore = headerStrip(), rowsBefore = rowStrip()
        let documentHeight = scroll.documentView?.frame.height ?? 0
        #expect(documentHeight > scroll.contentView.bounds.height + 100)
        scroll.contentView.scroll(to: NSPoint(x: 0, y: scroll.contentView.isFlipped ? 100 : max(0, documentHeight - scroll.contentView.bounds.height - 100)))
        scroll.reflectScrolledClipView(scroll.contentView)
        popover.host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
        popover.host.layoutSubtreeIfNeeded()
        #expect(headerBefore != nil && headerStrip() == headerBefore)
        // Guard against a vacuous pass: the rows below the header really moved.
        #expect(rowStrip() != rowsBefore)
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
            #expect((scrolls.first?.frame.height ?? 0) > 60)
            #expect((scrolls.first?.frame.height ?? 800) < 390)
            #expect(view.fittingSize.width == 340)
            #expect(view.fittingSize.height < 560)
        }
    }
    @Test func maintainedStatusHostKeepsViewportAcrossAppearanceAndRehosting() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-status-layout-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let store = WatchStore(fileURL: home.appendingPathComponent("state.json"))
        var state = AppState.initial; state.showOtherUpdates = false
        state.watched = (0..<12).map { index in
            let listing = Listing(name: PackageName("synthetic-host-\(index)")!, kind: .cask, version: "2.0")
            return WatchEntry(name: listing.name, kind: .cask, lastListing: listing,
                              installed: InstalledVersion(version: "1.0", source: .caskroomFallback))
        }
        try store.save(state)
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: store, notifier: QuietNotifier())
        let notifier = UserNotifier(service: NotificationServiceStub())
        for _ in 0..<2 {
            let settings = SettingsWindowController(controller: controller, notifier: notifier, login: LoginItem(service: LoginServiceStub()), activate: {}, present: { _ in })
            let host = StatusContent(controller: controller, notifier: notifier, settings: settings, focus: PopoverFocus(), accessory: nil).makeHostingController()
            let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: 340, height: 560), styleMask: [.borderless], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false
            window.contentViewController = host
            for appearance in [NSAppearance.Name.darkAqua, .aqua, .darkAqua] {
                // The status panel carries the appearance for its hosted content.
                window.appearance = NSAppearance(named: appearance)
                host.view.frame.size = host.view.fittingSize
                window.setContentSize(host.view.fittingSize)
                host.view.layoutSubtreeIfNeeded()
                #expect(host.view.fittingSize.width == 340)
                #expect(host.view.fittingSize.height <= 560)
                #expect(host.preferredContentSize.width == 340)
                #expect(host.preferredContentSize.height > 100)
                #expect(host.view.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == appearance)
                #expect((nativeScrollViews(host.view).first?.frame.height ?? 0) > 100)
            }
            window.contentViewController = nil
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
        let close = commands.first { $0.keyEquivalent == "w" }
        #expect(close?.action == #selector(NSWindow.performClose(_:)))
        #expect(close != nil && close?.target == nil)
        let undo = commands.first { $0.keyEquivalent == "z" && $0.keyEquivalentModifierMask == [.command] }
        let redo = commands.first { $0.keyEquivalent == "z" && $0.keyEquivalentModifierMask == [.command, .shift] }
        #expect(undo?.action == Selector(("undo:")))
        #expect(redo?.action == Selector(("redo:")))
        #expect(undo != nil && undo?.target == nil)
        #expect(redo != nil && redo?.target == nil)
    }
    @Test func commandOffersInstallOnlyForAbsentPackages() {
        for kind in [PackageKind.formula, .cask] {
            let listing = Listing(name: PackageName("synthetic-command")!, kind: kind, version: "2.0")
            let flag = kind == .cask ? "--cask " : ""
            #expect(packageCommand(listing, installed: nil) == "brew install \(flag)synthetic-command")
            #expect(packageCommand(listing, installed: InstalledVersion(version: "1.0", source: .caskroomFallback)) == "brew upgrade \(flag)synthetic-command")
        }
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
        #expect(windows[0].contentLayoutRect.height >= 400)
        #expect(windows[0].contentLayoutRect.width == 460)
        #expect(windows[0].contentMinSize.height >= 400)
        windows[0].contentView?.layoutSubtreeIfNeeded()
        let formScrolls = windows[0].contentView.map(nativeScrollViews) ?? []
        #expect(!formScrolls.isEmpty)
        #expect((formScrolls.first?.frame.height ?? 0) > 300)
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
    @Test func catalogAgeShowsDateOnlyWhenNotToday() {
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = TimeZone(identifier: "UTC")!
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let earlier = now.addingTimeInterval(-3600), yesterday = now.addingTimeInterval(-86400)
        #expect(catalogTimestamp(earlier, now: now, calendar: calendar) == earlier.formatted(date: .omitted, time: .shortened))
        #expect(catalogTimestamp(yesterday, now: now, calendar: calendar) == yesterday.formatted(date: .abbreviated, time: .shortened))
    }
    @Test func settingsWindowOpensOnActiveSpace() {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-settings-space-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: nil, store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: QuietNotifier())
        var windows: [NSWindow] = []
        let settings = SettingsWindowController(controller: controller, notifier: UserNotifier(service: NotificationServiceStub()),
            login: LoginItem(service: LoginServiceStub()), activate: {}, present: { windows.append($0) })
        settings.show()
        // The reused window must follow the user's current Space instead of
        // switching the user back to the Space where it was first shown.
        #expect(windows.first?.collectionBehavior.contains(.moveToActiveSpace) == true)
        #expect(windows.first?.collectionBehavior.contains(.canJoinAllSpaces) == false)
        // Every Settings row, including the Other updates interval, fits without scrolling.
        #expect((windows.first?.contentLayoutRect.height ?? 0) >= 581)
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
        // StatusPanelTests exercises session ownership; the former transient
        // popover close veto consumed clicks before a button action arrived.
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
struct QuietNotifier: Notifier { func post(_ notice: Notice) async {} }
