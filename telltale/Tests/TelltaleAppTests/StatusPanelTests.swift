// Port: brew_version/Tests/BrewVersionAppTests/StatusPanelTests.swift, whole file, 10a0fe2.
// Adaptation: the fixture hosts PanelView over a seeded synthetic database (LiveStore, UserActions)
// in place of Brew Version's WatchController and WatchStore; Settings and Open dashboard go
// through DashboardOpening; there is no custom interval and no update acknowledgment to save.
//
// Source tests at 10a0fe2 -> destination tests (unlisted names are unchanged):
// - statusItemFitsTheMugInsteadOfTheBarThickness -> same name (kept from the source; the item fits
//   Telltale's lens glyph)
// - keyboardApplicationSwitchDismissesWithPointerRestingOnIcon -> same name (its acknowledgment-save
//   assertions become "the database is not written")
// - nativeCyclesAcknowledgeUpdatesAndNeverActivateApplication -> nativeCyclesWriteNothingAndNeverActivateApplication
// - settingsAndCustomIntervalCancelBeforePresentingOwnedSettings -> settingsAndDashboardCancelBeforePresenting
// - all others: panelOpensOnActiveSpaceAndOverFullScreenApps, hiddenPlaceholdersDoNotBecomePlacedOnALowerDisplay,
//   anchorsAndSizeChangesStayInsideSyntheticScreens, validAnchorCentersAndHiddenAnchorFallsBackToVisibleTopRight,
//   placeholderAnchorsNeverPlaceThePanelAtTheScreenEdge, iconSlotSpansTheMenuBarAndPlaceholdersHaveNone,
//   alertIconIsDrawnInItsOwnColoursWithoutButtonTint, repeatedNativeSessionsAndProgrammaticRequestsUseSameRetainedHost,
//   ownedDismissalHidesAtOnceAndIgnoresLateAcknowledgment, lateOldEndCannotHideNewNativePresentation,
//   programmaticOpeningSurvivesLateAcknowledgmentAndStillDismisses, hostingEscapeAndPanelResignUseNativeCancel,
//   actualHostingPreferredSizeChangesRepositionRetainedPanel, warningGrowthAndShrinkKeepTheWholeRootVisible,
//   delayedParentResizeCannotExpandTheViewportPastItsWindow, observerDoesNotRetainController,
//   appearanceReachesPanelAndHostedContent, programmaticOpeningIsIdempotentAndFirstNativePressCloses,
//   pressingTheIconOfAProgrammaticPanelClosesItOnce, focusLossFromPressingTheIconLeavesNativeSessionInCharge,
//   focusMovingElsewhereClosesAndTheNextPressOpens, workspaceActivationPreservesOwnPanelAndCancelsANativeSessionForAnotherApp,
//   pressingTheIconOfAnOpenNativePanelClosesIt, theOpeningPressNeverClosesItsOwnPanel, onlyAPressOnTheIconCloses,
//   programmaticPanelLeavesIconPressToItsBegin, escapeKeyEquivalentDismissesEvenWithSearchResponder,
//   applicationResignAndPendingNativeEndLeaveNoDelayedReopen
// Helpers: PanelItem, PanelSession, SyntheticActivatedApplication, OffscreenStatusPanel, PanelFixture;
// PanelSaveCounter is replaced by the fixture's databaseBytes(), and DashboardStub replaces the
// settings presentation hook.
import AppKit
import SwiftUI
import UserNotifications
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

@MainActor struct StatusPanelSpaceTests {
    @Test func panelOpensOnActiveSpaceAndOverFullScreenApps() {
        // The panel is reused; it must appear on the user's current desktop
        // (including a full-screen app's Space) rather than its first Space.
        let behavior = StatusPanel().collectionBehavior
        #expect(behavior.contains(.moveToActiveSpace))
        #expect(behavior.contains(.fullScreenAuxiliary))
        #expect(!behavior.contains(.canJoinAllSpaces))
    }
}

struct StatusPanelGeometryTests {
    @Test func hiddenPlaceholdersDoNotBecomePlacedOnALowerDisplay() throws {
        let main = StatusScreen(frame: NSRect(x: 0, y: 0, width: 1440, height: 900), visibleFrame: NSRect(x: 0, y: 0, width: 1440, height: 876))
        let below = StatusScreen(frame: NSRect(x: 0, y: -900, width: 1440, height: 900), visibleFrame: NSRect(x: 0, y: -900, width: 1440, height: 876))
        for anchor in [NSRect(x: 0, y: -39, width: 34, height: 39), NSRect(x: 0, y: -30.5, width: 67, height: 22), NSRect(x: 6, y: -32, width: 22, height: 64), NSRect(x: 6, y: -51.5, width: 22, height: 64)] {
            let frame = try #require(StatusPanelFrame.make(contentSize: NSSize(width: 340, height: 515), anchor: anchor, screens: [main, below]))
            #expect(frame == NSRect(x: 1100, y: 361, width: 340, height: 515))
            #expect(!StatusPanelFrame.iconContains(NSPoint(x: anchor.midX, y: -12), anchor: anchor, screens: [main, below]))
        }
        // Real placements elsewhere on the lower bar, including tall windows,
        // still use that display. Negative coordinates alone are not hidden.
        for anchor in [NSRect(x: 1200, y: -24, width: 24, height: 24), NSRect(x: 1200, y: -44, width: 24, height: 64)] {
            let frame = try #require(StatusPanelFrame.make(contentSize: NSSize(width: 340, height: 515), anchor: anchor, screens: [main, below]))
            #expect(frame == NSRect(x: 1042, y: -539, width: 340, height: 515))
            #expect(StatusPanelFrame.iconContains(NSPoint(x: 1212, y: -12), anchor: anchor, screens: [main, below]))
        }
    }
    @Test func anchorsAndSizeChangesStayInsideSyntheticScreens() throws {
        let screens = [
            StatusScreen(frame: NSRect(x: 0, y: 0, width: 1200, height: 900), visibleFrame: NSRect(x: 0, y: 40, width: 1200, height: 830)),
            StatusScreen(frame: NSRect(x: -1500, y: -400, width: 1000, height: 800), visibleFrame: NSRect(x: -1500, y: -360, width: 1000, height: 730))
        ]
        for screen in screens {
            for anchor in [NSRect(x: screen.frame.minX, y: screen.frame.maxY - 22, width: 25, height: 22), NSRect(x: screen.frame.maxX - 25, y: screen.frame.maxY - 22, width: 25, height: 22), NSRect(x: 0, y: -50, width: 25, height: 22)] {
                for height in [120.0, 540.0, 2000.0] {
                    let frame = try #require(StatusPanelFrame.make(contentSize: NSSize(width: 340, height: height), anchor: anchor, screens: [screen]))
                    #expect(screen.visibleFrame.contains(frame))
                    #expect(frame.width == 340)
                    let expectedHeight: CGFloat = min(CGFloat(height), screen.visibleFrame.height)
                    #expect(frame.height == expectedHeight)
                }
            }
        }
    }
    @Test func validAnchorCentersAndHiddenAnchorFallsBackToVisibleTopRight() throws {
        let screen = StatusScreen(frame: NSRect(x: -1200, y: 200, width: 1000, height: 800), visibleFrame: NSRect(x: -1200, y: 240, width: 1000, height: 730))
        let frame = try #require(StatusPanelFrame.make(contentSize: NSSize(width: 340, height: 200), anchor: NSRect(x: -800, y: 978, width: 24, height: 22), screens: [screen]))
        #expect(frame.midX == -788 && frame.maxY == 970)
        let hidden = try #require(StatusPanelFrame.make(contentSize: NSSize(width: 340, height: 200), anchor: NSRect(x: 0, y: -40, width: 24, height: 22), screens: [screen]))
        #expect(hidden.maxX == screen.visibleFrame.maxX && hidden.maxY == screen.visibleFrame.maxY)
    }
    @Test func placeholderAnchorsNeverPlaceThePanelAtTheScreenEdge() throws {
        // Geometry recorded on the macOS 27 host: a 39-point menu bar, placed
        // icons (one in a 64-point window that extends above the screen), and
        // the placeholders an unplaced or hidden item reports. A placeholder
        // once put the panel at the lower-left corner, and the tall placed
        // window was once mistaken for a placeholder.
        let main = StatusScreen(frame: NSRect(x: 0, y: 0, width: 2056, height: 1329), visibleFrame: NSRect(x: 0, y: 54, width: 2056, height: 1235))
        let side = StatusScreen(frame: NSRect(x: 2056, y: 200, width: 1600, height: 900), visibleFrame: NSRect(x: 2056, y: 200, width: 1600, height: 876))
        for placeholder in [NSRect(x: 0, y: -39, width: 34, height: 39), NSRect(x: 0, y: -30.5, width: 67, height: 22), NSRect(x: 6, y: -32, width: 22, height: 64), NSRect(x: 6, y: -51.5, width: 22, height: 64), NSRect.zero] {
            #expect(StatusPanelFrame.placedAnchor(placeholder, screens: [main, side]) == nil)
            let frame = try #require(StatusPanelFrame.make(contentSize: NSSize(width: 340, height: 515), anchor: placeholder, screens: [main, side]))
            #expect(frame.maxX == main.visibleFrame.maxX && frame.maxY == main.visibleFrame.maxY)
        }
        #expect(StatusPanelFrame.make(contentSize: NSSize(width: 340, height: 515), anchor: nil, screens: []) == nil)
        for icon in [NSRect(x: 1203, y: 1290, width: 34, height: 39), NSRect(x: 831, y: 1298.5, width: 67, height: 22), NSRect(x: 1599, y: 1277.5, width: 22, height: 64)] {
            let frame = try #require(StatusPanelFrame.make(contentSize: NSSize(width: 340, height: 515), anchor: icon, screens: [main, side]))
            #expect(frame.midX == icon.midX && frame.maxY == main.visibleFrame.maxY)
        }
        let sideIcon = NSRect(x: 3000, y: 1076, width: 34, height: 24)
        let sideFrame = try #require(StatusPanelFrame.make(contentSize: NSSize(width: 340, height: 515), anchor: sideIcon, screens: [main, side]))
        #expect(sideFrame.midX == sideIcon.midX && side.visibleFrame.contains(sideFrame))
    }
    @Test func iconSlotSpansTheMenuBarAndPlaceholdersHaveNone() {
        let main = StatusScreen(frame: NSRect(x: 0, y: 0, width: 2056, height: 1329), visibleFrame: NSRect(x: 0, y: 54, width: 2056, height: 1235))
        let icon = NSRect(x: 831, y: 1298.5, width: 67, height: 22)
        for point in [NSPoint(x: 864, y: 1310), NSPoint(x: 832, y: 1328.9), NSPoint(x: 897, y: 1291)] {
            #expect(StatusPanelFrame.iconContains(point, anchor: icon, screens: [main]))
        }
        for point in [NSPoint(x: 864, y: 1280), NSPoint(x: 820, y: 1310), NSPoint(x: 910, y: 1310)] {
            #expect(!StatusPanelFrame.iconContains(point, anchor: icon, screens: [main]))
        }
        #expect(!StatusPanelFrame.iconContains(NSPoint(x: 17, y: -20), anchor: NSRect(x: 0, y: -39, width: 34, height: 39), screens: [main]))
        let tall = NSRect(x: 1599, y: 1277.5, width: 22, height: 64)
        #expect(StatusPanelFrame.iconContains(NSPoint(x: 1610, y: 1310), anchor: tall, screens: [main]))
        #expect(!StatusPanelFrame.iconContains(NSPoint(x: 1610, y: 1280), anchor: tall, screens: [main]))
        #expect(!StatusPanelFrame.iconContains(NSPoint(x: 1650, y: 1310), anchor: tall, screens: [main]))
        // An auto-hidden menu bar reserves no visible frame; its icons still count.
        let autoHidden = StatusScreen(frame: main.frame, visibleFrame: NSRect(x: 0, y: 54, width: 2056, height: 1275))
        #expect(StatusPanelFrame.placedAnchor(NSRect(x: 900, y: 1305, width: 24, height: 24), screens: [autoHidden]) != nil)
    }
}

final class PanelItem: NSStatusItem {
    let anchor: NSStatusBarButton
    init(anchor: NSStatusBarButton) { self.anchor = anchor; super.init() }
    override var button: NSStatusBarButton? { anchor }
    var session: NSStatusItemExpandedInterfaceSession?
    override var expandedInterfaceSession: NSStatusItemExpandedInterfaceSession? { session }
}
final class PanelSession: NSStatusItemExpandedInterfaceSession { override func cancel() {} }
private final class SyntheticActivatedApplication: NSRunningApplication, @unchecked Sendable {
    let identifier: String
    init(_ identifier: String) { self.identifier = identifier; super.init() }
    override var processIdentifier: pid_t { 424242 }
    override var bundleIdentifier: String? { identifier }
}
@MainActor final class OffscreenStatusPanel: StatusPanel {
    var shown = false
    var shows = 0
    var hides = 0
    override var contentViewController: NSViewController? {
        get { super.contentViewController }
        set {
            super.contentViewController = newValue
            // Match the root mask recorded by the live native resize trace
            // without ordering this test window onto a screen.
            newValue?.view.autoresizingMask = [.width, .height]
        }
    }
    override var isVisible: Bool { shown }
    override func makeKeyAndOrderFront(_ sender: Any?) { shown = true; shows += 1 }
    override func orderOut(_ sender: Any?) { shown = false; hides += 1 }
}
/// Records the panel's Settings and Open dashboard requests (Task 12's dashboard controller).
@MainActor final class DashboardStub: DashboardOpening {
    var presentations: [String] = []
    var visibleAtPresentation: [Bool] = []
    var panelVisible: () -> Bool = { false }
    func openDashboard() { presentations.append("dashboard"); visibleAtPresentation.append(panelVisible()) }
    func openSettings() { presentations.append("settings"); visibleAtPresentation.append(panelVisible()) }
}
@MainActor final class PanelFixture {
    static let screen = StatusScreen(frame: NSRect(x: -900, y: 100, width: 900, height: 700), visibleFrame: NSRect(x: -900, y: 140, width: 900, height: 630))
    static let icon = NSRect(x: -50, y: 778, width: 22, height: 22)
    let item = PanelItem(anchor: NSStatusBarButton(frame: NSRect(x: 0, y: 0, width: 22, height: 22)))
    let panel = OffscreenStatusPanel()
    let notifications = NotificationCenter()
    let workspaceNotifications = NotificationCenter()
    let notificationService = NotificationServiceStub()
    let dashboard = DashboardStub()
    var status: StatusItemController!
    var activations = 0
    var cancelCount = 0
    var immediateCancel = true
    var pointer = NSPoint(x: -600, y: 400)
    var clock: TimeInterval = 100
    let paths: TelltalePaths
    let store: LiveStore
    init(home: URL) throws {
        _ = NSApplication.shared
        // A seeded synthetic database with one amber alert, read by the panel's live store.
        paths = PanelWorld.paths(home)
        try PanelWorld.seed(paths, alerting: true)
        store = PanelWorld.live(paths)
        let notifier = UserNotifier(service: notificationService)
        status = StatusItemController(
            model: PanelModel(store: store, actions: PanelWorld.actions(paths), notifier: notifier), dashboard: dashboard,
            item: item, panel: panel, notifications: notifications, workspaceNotifications: workspaceNotifications,
            screens: { [Self.screen] }, anchor: { Self.icon },
            pointer: { [weak self] in self?.pointer ?? .zero },
            now: { [weak self] in self?.clock ?? 0 },
            // Tests call the monitor's entry points directly; no global
            // monitor is installed and no desktop input is observed.
            monitorGlobalMouse: { _ in nil },
            cancelSession: { [weak self] _ in
                guard let self else { return }; cancelCount += 1
                if immediateCancel { end() }
            }, activate: { [weak self] in self?.activations += 1 })
        dashboard.panelVisible = { [weak self] in self?.panel.isVisible ?? false }
    }
    @discardableResult func begin() -> PanelSession {
        let session = PanelSession(); item.session = session
        item.expandedInterfaceDelegate?.statusItem(item, didBegin: session)
        return session
    }
    func end() {
        item.session = nil
        item.expandedInterfaceDelegate?.statusItemDidEndExpandedInterfaceSession(item, animated: true)
    }
    static let onIcon = NSPoint(x: icon.midX, y: screen.frame.maxY - 1)
    static let elsewhere = NSPoint(x: -600, y: 400)
    /// A press seen by the global monitor: down at `time`, then up.
    func press(down: NSPoint = onIcon, up: NSPoint = onIcon, at time: TimeInterval) {
        status.globalMouseDown(at: down, time: time)
        status.globalMouseUp(at: up)
    }
    func pointAtIcon() { pointer = NSPoint(x: Self.icon.midX, y: Self.screen.frame.maxY - 1) }
    func pointElsewhere() { pointer = NSPoint(x: -600, y: 400) }
    /// What a press elsewhere, or on the icon, does before the system's begin
    /// or end: the application resigns active and the panel resigns key.
    func loseFocus() {
        notifications.post(name: NSApplication.didResignActiveNotification, object: NSApp)
        status.windowDidResignKey(Notification(name: NSWindow.didResignKeyNotification, object: panel))
    }
    /// The database's bytes and its WAL's: the panel's presentation must never write.
    func databaseBytes() throws -> [Data] {
        try ["", "-wal"].compactMap { suffix in
            let path = paths.database.path + suffix
            return FileManager.default.fileExists(atPath: path) ? try Data(contentsOf: URL(fileURLWithPath: path)) : nil
        }
    }
}
@MainActor struct StatusPanelLifecycleTests {
    @Test func alertIconIsDrawnInItsOwnColoursWithoutButtonTint() throws {
        // A template image tinted through contentTintColor renders black in
        // the macOS 27 menu bar, which hides the alert on a dark bar.
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        let button = try #require(fixture.item.button)
        let image = try #require(button.image)
        #expect(button.contentTintColor == nil)
        #expect(!image.isTemplate)
        #expect(button.accessibilityLabel() == "Telltale: Speed amber.")
    }
    @Test func statusItemFitsTheMugInsteadOfTheBarThickness() {
        // Square length padded the icon to 22pt, leaving ~10pt gaps beside it.
        let bar = NSStatusBar()
        let item = StatusItemController.makeItem(in: bar)
        defer { bar.removeStatusItem(item) }
        #expect(item.length == NSStatusItem.variableLength)
    }
    @Test func repeatedNativeSessionsAndProgrammaticRequestsUseSameRetainedHost() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        let host = fixture.panel.contentViewController
        for _ in 0..<6 {
            fixture.begin(); #expect(fixture.panel.isVisible)
            fixture.end(); #expect(!fixture.panel.isVisible)
            #expect(fixture.panel.contentViewController === host)
        }
        fixture.status.showPopover(); fixture.status.showPopover()
        #expect(fixture.activations == 1 && fixture.panel.isVisible)
        // An end with no session shown here is a stale acknowledgment. It must
        // not hide a Finder or notification opening; the next press closes it.
        fixture.end(); #expect(fixture.panel.isVisible)
        fixture.begin(); #expect(!fixture.panel.isVisible && fixture.cancelCount == 1)
        #expect(fixture.panel.shows == 7 && fixture.panel.hides == 7)
    }
    @Test func ownedDismissalHidesAtOnceAndIgnoresLateAcknowledgment() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.begin(); fixture.immediateCancel = false
        fixture.status.dismiss(); fixture.status.dismiss()
        #expect(fixture.cancelCount == 1 && !fixture.panel.isVisible)
        // No request waits for the acknowledgment, so a reopen is immediate
        // and the late end of the cancelled session cannot take it away.
        fixture.status.showPopover()
        #expect(fixture.activations == 1 && fixture.panel.isVisible)
        fixture.end()
        #expect(fixture.panel.isVisible)
        fixture.status.dismiss()
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 1)
    }
}

@MainActor struct StatusPanelOwnershipTests {
    @Test func lateOldEndCannotHideNewNativePresentation() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.immediateCancel = false
        fixture.begin(); fixture.status.dismiss()
        #expect(!fixture.panel.isVisible)
        let newer = fixture.begin()
        // Old cancel acknowledgment arrives after a new live SDK session.
        fixture.item.expandedInterfaceDelegate?.statusItemDidEndExpandedInterfaceSession(fixture.item, animated: false)
        #expect(fixture.panel.isVisible && fixture.item.session === newer)
        fixture.status.dismiss()
        #expect(fixture.cancelCount == 2 && !fixture.panel.isVisible && fixture.panel.hides == 2)
        // Neither acknowledgment has a presentation left to hide.
        fixture.end(); fixture.end()
        #expect(fixture.panel.hides == 2)
    }
    @Test func programmaticOpeningSurvivesLateAcknowledgmentAndStillDismisses() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.immediateCancel = false
        fixture.begin(); fixture.status.dismiss(); fixture.status.showPopover()
        fixture.end()
        #expect(fixture.panel.isVisible && fixture.activations == 1)
        let host = try #require(fixture.panel.contentViewController?.children.first as? StatusHostingController)
        host.cancelOperation(nil)
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 1)
        fixture.begin(); fixture.status.dismiss(); fixture.status.showPopover()
        fixture.loseFocus()
        #expect(!fixture.panel.isVisible)
        fixture.end()
        #expect(!fixture.panel.isVisible && fixture.activations == 2 && fixture.cancelCount == 2)
    }
    @Test func hostingEscapeAndPanelResignUseNativeCancel() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.begin()
        let host = try #require(fixture.panel.contentViewController?.children.first as? StatusHostingController)
        host.cancelOperation(nil)
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 1)
        fixture.begin()
        fixture.status.windowDidResignKey(Notification(name: NSWindow.didResignKeyNotification, object: fixture.panel))
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 2)
        #expect(fixture.panel.canBecomeKey && !fixture.panel.canBecomeMain)
        #expect(fixture.panel.styleMask.contains(.nonactivatingPanel))
    }
    @Test func actualHostingPreferredSizeChangesRepositionRetainedPanel() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.begin()
        let content = try #require(fixture.panel.contentViewController as? StatusPanelContentController)
        let host = try #require(content.children.first)
        for height in [180.0, 560.0, 220.0] {
            let hosting = host as! StatusHostingController
            let root = hosting.rootView
            hosting.rootView = StatusContent(model: root.model, dashboard: root.dashboard, focus: root.focus, accessory: AnyView(Color.clear.frame(height: height)), dismiss: root.dismiss, sizeChanged: root.sizeChanged)
            hosting.view.layoutSubtreeIfNeeded()
            await MainActor.run { RunLoop.current.run(until: Date().addingTimeInterval(0.03)) }
            await Task.yield()
            #expect(fixture.panel.frame.width == 340)
            let expectedHeight = min(host.preferredContentSize.height, CGFloat(630))
            #expect(fixture.panel.frame.height == expectedHeight)
            #expect(host.preferredContentSize.height > height)
            #expect(NSRect(x: -900, y: 140, width: 900, height: 630).contains(fixture.panel.frame))
            let scroll = try #require(content.view.subviews.first as? NSScrollView)
            #expect(content.view.frame.size == fixture.panel.contentLayoutRect.size)
            #expect(scroll.frame.size == fixture.panel.contentLayoutRect.size)
            if content.desiredContentSize.height <= 630 {
                #expect(scroll.documentVisibleRect.contains(hosting.view.bounds))
            }
        }
    }
    @Test func warningGrowthAndShrinkKeepTheWholeRootVisible() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.begin()
        let content = try #require(fixture.panel.contentViewController as? StatusPanelContentController)
        let hosting = try #require(content.children.first as? StatusHostingController)
        let root = hosting.rootView
        hosting.rootView = StatusContent(model: root.model, dashboard: root.dashboard, focus: root.focus, accessory: AnyView(Color.clear.frame(height: 100)), dismiss: root.dismiss, sizeChanged: root.sizeChanged)
        let scroll = try #require(content.view.subviews.first as? NSScrollView)
        var unwarnedHeight: CGFloat = 0
        for status in [UNAuthorizationStatus.authorized, .denied, .authorized, .denied, .authorized] {
            fixture.notificationService.status = status
            await root.model.notifier.requestAuthorization()
            for _ in 0..<8 {
                try await Task.sleep(for: .milliseconds(25))
            }
            #expect(content.desiredContentSize.height < 630)
            #expect(content.view.frame.size == fixture.panel.contentLayoutRect.size)
            #expect(scroll.frame.size == fixture.panel.contentLayoutRect.size)
            if status == .authorized { unwarnedHeight = content.desiredContentSize.height }
            else { #expect(content.desiredContentSize.height > unwarnedHeight + 20) }
            #expect(scroll.documentVisibleRect.contains(hosting.view.bounds))
            #expect(hosting.view.frame.size == content.desiredContentSize)
        }
    }
    @Test func delayedParentResizeCannotExpandTheViewportPastItsWindow() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.begin()
        let content = try #require(fixture.panel.contentViewController as? StatusPanelContentController)
        let scroll = try #require(content.view.subviews.first as? NSScrollView)
        let hosting = try #require(content.children.first as? StatusHostingController)
        let parent = try #require(content.view.superview)
        // Live passive trace: SwiftUI changed the window 459 -> 386 -> 534
        // before contentLayoutRect caught up. AppKit then added the stale
        // 534-459 delta again to the root, leaving it 609pt inside 534pt.
        for height in [459.0, 386.0, 534.0] {
            fixture.panel.setFrame(NSRect(x: -400, y: 200, width: 340, height: height), display: false)
        }
        // Replay the captured late public frame write AFTER normal window
        // resize handling. Layout ownership must restore the viewport; a
        // delegate called before this write cannot repair it.
        content.view.frame = NSRect(x: 0, y: 0, width: 340, height: 609)
        parent.needsLayout = true
        parent.layoutSubtreeIfNeeded()
        #expect(content.view.frame == NSRect(x: 0, y: 0, width: 340, height: 534))
        #expect(scroll.frame.size == NSSize(width: 340, height: 534))
        #expect(hosting.view.visibleRect.minY == hosting.view.bounds.minY)
    }
    @Test func observerDoesNotRetainController() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        weak var status: StatusItemController?
        var notifications: NotificationCenter!
        try autoreleasepool {
            var fixture: PanelFixture? = try PanelFixture(home: home)
            status = fixture?.status
            notifications = fixture?.notifications
            fixture = nil
        }
        #expect(status == nil)
        notifications.post(name: NSApplication.didResignActiveNotification, object: NSApp)
    }
    @Test func appearanceReachesPanelAndHostedContent() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        defer { fixture.status.setAppearance(nil) }
        let host = try #require(fixture.panel.contentViewController?.children.first)
        for name in [NSAppearance.Name.darkAqua, .aqua] {
            fixture.status.setAppearance(NSAppearance(named: name))
            #expect(fixture.panel.appearance?.name == name)
            #expect(host.view.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == name)
        }
    }
    /// Ruling R33: a harness's panel appearance never pins the whole application, or the dashboard
    /// window could no longer follow the system.
    @Test func panelAppearanceNeverPinsTheApplication() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        defer {
            fixture.status.setAppearance(nil)
            NSApp.appearance = nil
        }
        #expect(NSApp.appearance == nil)
        fixture.status.setAppearance(NSAppearance(named: .aqua))
        #expect(NSApp.appearance == nil)
        #expect(fixture.panel.appearance?.name == .aqua)
        fixture.status.setAppearance(NSAppearance(named: .darkAqua))
        #expect(NSApp.appearance == nil)
        #expect(fixture.panel.appearance?.name == .darkAqua)
        fixture.status.setAppearance(nil)
        #expect(NSApp.appearance == nil && fixture.panel.appearance == nil)
    }
}
@MainActor struct DirectPanelOpeningTests {
    @Test func programmaticOpeningIsIdempotentAndFirstNativePressCloses() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.status.showPopover(); fixture.status.showPopover()
        #expect(fixture.panel.isVisible)
        #expect(fixture.item.session == nil)
        fixture.begin()
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 1)
        fixture.begin()
        #expect(fixture.panel.isVisible)
        fixture.end()
        #expect(!fixture.panel.isVisible)
    }
    @Test func pressingTheIconOfAProgrammaticPanelClosesItOnce() throws {
        // Recorded order on the macOS 27 host: the press on the icon took focus
        // from the app about 45 ms before the system's begin. Dismissing for
        // that focus loss hid the panel, and the begin then reopened it.
        for immediate in [true, false] {
            let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
            defer { try? FileManager.default.removeItem(at: home) }
            let fixture = try PanelFixture(home: home)
            fixture.immediateCancel = immediate
            fixture.status.showPopover()
            fixture.pointAtIcon(); fixture.loseFocus()
            fixture.workspaceNotifications.post(name: NSWorkspace.didActivateApplicationNotification, object: NSWorkspace.shared,
                userInfo: [NSWorkspace.applicationUserInfoKey: SyntheticActivatedApplication("com.apple.MenuBarAgent")])
            #expect(fixture.panel.isVisible && fixture.cancelCount == 0)
            fixture.begin()
            #expect(!fixture.panel.isVisible && fixture.cancelCount == 1)
            if !immediate { fixture.end() }
            #expect(!fixture.panel.isVisible && fixture.panel.shows == 1 && fixture.panel.hides == 1)
            // The next press opens again.
            fixture.begin()
            #expect(fixture.panel.isVisible && fixture.panel.shows == 2)
        }
    }
    @Test func focusLossFromPressingTheIconLeavesNativeSessionInCharge() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        for _ in 0..<3 {
            fixture.pointElsewhere(); fixture.begin()
            fixture.pointAtIcon(); fixture.loseFocus()
            #expect(fixture.panel.isVisible && fixture.cancelCount == 0)
            fixture.end()
            #expect(!fixture.panel.isVisible)
        }
        #expect(fixture.panel.shows == 3 && fixture.panel.hides == 3)
    }
    @Test func focusMovingElsewhereClosesAndTheNextPressOpens() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.status.showPopover()
        fixture.pointElsewhere(); fixture.loseFocus()
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 0)
        fixture.begin()
        #expect(fixture.panel.isVisible)
        fixture.immediateCancel = false
        fixture.loseFocus()
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 1)
        fixture.end()
        fixture.begin()
        #expect(fixture.panel.isVisible && fixture.panel.shows == 3 && fixture.panel.hides == 2)
    }
    @Test func keyboardApplicationSwitchDismissesWithPointerRestingOnIcon() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.status.showPopover()
        fixture.pointAtIcon(); fixture.loseFocus()
        let bytesBefore = try fixture.databaseBytes()
        fixture.workspaceNotifications.post(name: NSWorkspace.didActivateApplicationNotification, object: NSWorkspace.shared,
            userInfo: [NSWorkspace.applicationUserInfoKey: SyntheticActivatedApplication("test.synthetic.other-app")])
        #expect(!fixture.panel.isVisible && fixture.panel.hides == 1)
        #expect(try fixture.databaseBytes() == bytesBefore)
        fixture.loseFocus()
        #expect(try fixture.panel.hides == 1 && fixture.databaseBytes() == bytesBefore)
        #expect(fixture.cancelCount == 0)
    }
    @Test func workspaceActivationPreservesOwnPanelAndCancelsANativeSessionForAnotherApp() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.pointAtIcon(); fixture.begin()
        fixture.workspaceNotifications.post(name: NSWorkspace.didActivateApplicationNotification, object: NSWorkspace.shared,
            userInfo: [NSWorkspace.applicationUserInfoKey: NSRunningApplication.current])
        #expect(fixture.panel.isVisible && fixture.cancelCount == 0)
        fixture.immediateCancel = false
        fixture.workspaceNotifications.post(name: NSWorkspace.didActivateApplicationNotification, object: NSWorkspace.shared,
            userInfo: [NSWorkspace.applicationUserInfoKey: SyntheticActivatedApplication("test.synthetic.other-app")])
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 1)
        fixture.end()
        fixture.begin()
        #expect(fixture.panel.isVisible && fixture.panel.shows == 2)
    }
}
@MainActor struct StatusIconPressTests {
    // Recorded on the macOS 27 host: while a session shows the panel, a press
    // on the icon delivered no event and no end, so it never closed.
    @Test func pressingTheIconOfAnOpenNativePanelClosesIt() throws {
        for immediate in [true, false] {
            let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
            defer { try? FileManager.default.removeItem(at: home) }
            let fixture = try PanelFixture(home: home)
            fixture.immediateCancel = immediate
            for cycle in 0..<4 {
                fixture.clock = 100 + Double(cycle) * 10
                fixture.begin()
                #expect(fixture.panel.isVisible)
                fixture.press(at: fixture.clock + 1)
                #expect(!fixture.panel.isVisible && fixture.cancelCount == cycle + 1)
                if !immediate { fixture.end() }
                #expect(!fixture.panel.isVisible)
            }
            #expect(fixture.panel.shows == 4 && fixture.panel.hides == 4)
        }
    }
    @Test func theOpeningPressNeverClosesItsOwnPanel() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        // The monitor sees the opening press before the begin arrives...
        fixture.status.globalMouseDown(at: PanelFixture.onIcon, time: 99)
        fixture.begin()
        fixture.status.globalMouseUp(at: PanelFixture.onIcon)
        #expect(fixture.panel.isVisible && fixture.cancelCount == 0)
        fixture.end()
        // ...or after it, still stamped before the session began.
        fixture.clock = 200
        fixture.begin()
        fixture.press(at: 199.98)
        #expect(fixture.panel.isVisible && fixture.cancelCount == 0)
    }
    @Test func onlyAPressOnTheIconCloses() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.begin()
        // Dragging off the icon, or onto it from elsewhere, is not a press on it.
        fixture.press(up: PanelFixture.elsewhere, at: 101)
        fixture.press(down: PanelFixture.elsewhere, at: 102)
        #expect(fixture.panel.isVisible && fixture.cancelCount == 0)
        // An end before the release leaves nothing to close.
        fixture.status.globalMouseDown(at: PanelFixture.onIcon, time: 103)
        fixture.end()
        fixture.status.globalMouseUp(at: PanelFixture.onIcon)
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 0 && fixture.panel.hides == 1)
    }
    @Test func programmaticPanelLeavesIconPressToItsBegin() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.status.showPopover()
        fixture.press(at: 101)
        #expect(fixture.panel.isVisible && fixture.cancelCount == 0)
        fixture.begin()
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 1 && fixture.panel.hides == 1)
    }
}
@MainActor struct StatusPanelKeyboardTests {
    @Test func escapeKeyEquivalentDismissesEvenWithSearchResponder() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.begin()
        let search = NSSearchField(frame: NSRect(x: 0, y: 0, width: 200, height: 24))
        fixture.panel.contentView?.addSubview(search)
        _ = fixture.panel.makeFirstResponder(search)
        // Constructing an event for an owned offscreen responder method does
        // not send, post or synthesize desktop input.
        let escape = try #require(NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 1, windowNumber: 0, context: nil, characters: "\u{1b}", charactersIgnoringModifiers: "\u{1b}", isARepeat: false, keyCode: 53))
        #expect(fixture.panel.performKeyEquivalent(with: escape))
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 1)
    }
}
@MainActor struct StatusPanelIntegrationTests {
    @Test func nativeCyclesWriteNothingAndNeverActivateApplication() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        // Telltale has nothing to acknowledge on close: the panel reads the database and never writes it.
        let before = try fixture.databaseBytes()
        for _ in 0..<6 { fixture.begin(); fixture.end() }
        #expect(fixture.activations == 0 && fixture.panel.hides == 6)
        #expect(try fixture.databaseBytes() == before)
        fixture.end(); #expect(fixture.panel.hides == 6)
    }
    @Test func settingsAndDashboardCancelBeforePresenting() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.begin()
        let host = try #require(fixture.panel.contentViewController?.children.first as? StatusHostingController)
        host.rootView.showSettings()
        #expect(fixture.cancelCount == 1 && fixture.dashboard.presentations == ["settings"])
        fixture.begin(); host.rootView.showDashboard()
        #expect(fixture.cancelCount == 2 && fixture.dashboard.presentations == ["settings", "dashboard"])
        #expect(fixture.dashboard.visibleAtPresentation == [false, false])
    }
    @Test func applicationResignAndPendingNativeEndLeaveNoDelayedReopen() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("telltale-panel-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.begin()
        fixture.notifications.post(name: NSApplication.didResignActiveNotification, object: NSApp)
        #expect(!fixture.panel.isVisible && fixture.cancelCount == 1)
        fixture.immediateCancel = false
        fixture.begin(); fixture.status.dismiss()
        fixture.begin(); fixture.end()
        // The cancelled session's late end arrives last and hides nothing.
        fixture.end()
        #expect(!fixture.panel.isVisible && fixture.panel.hides == 3)
        fixture.begin(); #expect(fixture.panel.isVisible)
    }
}
