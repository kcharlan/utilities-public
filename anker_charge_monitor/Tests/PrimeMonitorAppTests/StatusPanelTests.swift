// Port: BrewVersion/Tests/BrewVersionAppTests/StatusPanelTests.swift, 579ebb7.
// Each original test name is retained; monitor/readout replace watch and notification dependencies.
import AppKit
import SwiftUI

import Synchronization
import Testing
@testable import PrimeMonitor

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

private final class PanelItem: NSStatusItem {
    let anchor: NSStatusBarButton
    init(anchor: NSStatusBarButton) { self.anchor = anchor; super.init() }
    override var button: NSStatusBarButton? { anchor }
    var session: NSStatusItemExpandedInterfaceSession?
    override var expandedInterfaceSession: NSStatusItemExpandedInterfaceSession? { session }
}
private final class PanelSession: NSStatusItemExpandedInterfaceSession { override func cancel() {} }
private final class SyntheticActivatedApplication: NSRunningApplication, @unchecked Sendable {
    let identifier: String
    init(_ identifier: String) { self.identifier = identifier; super.init() }
    override var processIdentifier: pid_t { 424242 }
    override var bundleIdentifier: String? { identifier }
}

@MainActor private final class OffscreenStatusPanel: StatusPanel {
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
@MainActor private final class PanelFixture {
    static let screen = StatusScreen(frame: NSRect(x: -900, y: 100, width: 900, height: 700), visibleFrame: NSRect(x: -900, y: 140, width: 900, height: 630))
    static let icon = NSRect(x: -50, y: 778, width: 22, height: 22)
    let item = PanelItem(anchor: NSStatusBarButton(frame: NSRect(x: 0, y: 0, width: 22, height: 22)))
    let panel = OffscreenStatusPanel()
    let notifications = NotificationCenter()
    let workspaceNotifications = NotificationCenter()

    var status: StatusItemController!
    var activations = 0
    var cancelCount = 0
    var settingsPresentations = 0
    var visibleAtSettingsPresentation = false
    var immediateCancel = true
    var pointer = NSPoint(x: -600, y: 400)
    var clock: TimeInterval = 100
    let rig: ControllerRig
    let directory: URL
    var currentAnchor = PanelFixture.icon
    /// nil when the caller supplied the catalog.
    let catalogFile: URL?
    init(home: URL, catalog suppliedCatalog: DeviceCatalogStore? = nil) throws {
        _ = NSApplication.shared
        rig = try ControllerRig()
        directory = rig.directory
        let controller = rig.controller
        // An explicit temporary store, removed with the rig directory.
        let catalog: DeviceCatalogStore
        if let suppliedCatalog { catalogFile = nil; catalog = suppliedCatalog } else {
            let file = rig.directory.appending(path: "Catalog café/devices.json", directoryHint: .notDirectory)
            catalogFile = file; catalog = DeviceCatalogStore(fileURL: file, seedURL: nil, scheduler: rig.clock)
        }
        let settings = SettingsWindowController(controller: controller, login: LoginItem(service: LoginServiceStub()), activate: {}, present: { [weak self] _ in
            guard let self else { return }
            settingsPresentations += 1
            visibleAtSettingsPresentation = panel.isVisible
        })
        status = StatusItemController(controller: controller, catalog: catalog,
 item: item, panel: panel, settings: settings, notifications: notifications, workspaceNotifications: workspaceNotifications,
            screens: { [Self.screen] }, anchor: { [weak self] in self?.currentAnchor },
            pointer: { [weak self] in self?.pointer ?? .zero },
            now: { [weak self] in self?.clock ?? 0 },
            // Tests call the monitor's entry points directly; no global
            // monitor is installed and no desktop input is observed.
            monitorGlobalMouse: { _ in nil },
            cancelSession: { [weak self] _ in
                guard let self else { return }; cancelCount += 1
                if immediateCancel { end() }
            }, activate: { [weak self] in self?.activations += 1 })
    }
    deinit { try? FileManager.default.removeItem(at: directory) }
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
}
@testable import PrimeMonitorCore
@MainActor struct StatusPanelLifecycleTests {
    @Test func repeatedNativeSessionsAndProgrammaticRequestsUseSameRetainedHost() throws {
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
    // Adaptation: changing actual monitor warnings replaces BV's removed accessory.
    @Test func actualHostingPreferredSizeChangesRepositionRetainedPanel() async throws {
        let fixture = try PanelFixture(home: FileManager.default.temporaryDirectory)
        await fixture.rig.start(); fixture.begin()
        let content = try #require(fixture.panel.contentViewController as? StatusPanelContentController)
        let hosting = try #require(content.children.first as? StatusHostingController)
        for message in ["short", String(repeating: "Synthetic warning text. ", count: 30), "short"] {
            fixture.rig.backend.output.yield(.status(.error(message)))
            await settle()
            hosting.view.layoutSubtreeIfNeeded()
            await MainActor.run { RunLoop.current.run(until: Date().addingTimeInterval(0.06)) }
            #expect(fixture.panel.frame == StatusPanelFrame.make(contentSize: content.desiredContentSize, anchor: fixture.currentAnchor, screens: [PanelFixture.screen]))
            #expect(hosting.preferredContentSize.height > 0)
            #expect(content.view.frame.size == fixture.panel.contentLayoutRect.size)
        }
        fixture.status.dismiss(); await fixture.rig.finish()
    }
    // Adaptation: controller warnings replace notification authorization warnings.
    @Test func warningGrowthAndShrinkKeepTheWholeRootVisible() async throws {
        let fixture = try PanelFixture(home: FileManager.default.temporaryDirectory)
        await fixture.rig.start(); fixture.begin()
        let content = try #require(fixture.panel.contentViewController as? StatusPanelContentController)
        let hosting = try #require(content.children.first as? StatusHostingController)
        let scroll = try #require(content.view.subviews.first as? NSScrollView)
        var shortHeight: CGFloat = 0
        for warning in [false, true, false, true, false] {
            fixture.rig.backend.output.yield(.status(.error(warning ? String(repeating: "Warning ", count: 60) : "short")))
            await settle()
            hosting.view.layoutSubtreeIfNeeded()
            await MainActor.run { RunLoop.current.run(until: Date().addingTimeInterval(0.06)) }
            #expect(content.view.frame.size == fixture.panel.contentLayoutRect.size)
            #expect(scroll.frame.size == fixture.panel.contentLayoutRect.size)
            if warning { #expect(content.desiredContentSize.height > shortHeight) }
            else { shortHeight = content.desiredContentSize.height }
            if content.desiredContentSize.height <= fixture.panel.frame.height {
                #expect(scroll.documentVisibleRect.contains(hosting.view.bounds))
            }
            #expect(hosting.view.frame.size == content.desiredContentSize)
        }
        fixture.status.dismiss(); await fixture.rig.finish()
    }
    @Test func delayedParentResizeCannotExpandTheViewportPastItsWindow() throws {
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
}
@MainActor struct DirectPanelOpeningTests {
    @Test func programmaticOpeningIsIdempotentAndFirstNativePressCloses() throws {
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
            let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.status.showPopover()
        fixture.pointAtIcon(); fixture.loseFocus()
        fixture.workspaceNotifications.post(name: NSWorkspace.didActivateApplicationNotification, object: NSWorkspace.shared,
            userInfo: [NSWorkspace.applicationUserInfoKey: SyntheticActivatedApplication("test.synthetic.other-app")])
        #expect(!fixture.panel.isVisible && fixture.panel.hides == 1)
        fixture.loseFocus()
        #expect(fixture.panel.hides == 1)
        #expect(fixture.cancelCount == 0)
    }
    @Test func workspaceActivationPreservesOwnPanelAndCancelsANativeSessionForAnotherApp() throws {
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
            let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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
    @Test func escapeKeyEquivalentDismissesEvenWithSearchResponder() async throws {
        // Focusing a field ends editing in any other test window: hold the lock.
        await HostedFieldLock.shared.acquire(); defer { HostedFieldLock.shared.release() }
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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

/// A shown panel with an expanded identified device on C1 and a persistent
/// private catalog; `focusAndType` edits its real hosted naming field.
@MainActor private final class NamingPanel {
    let catalog: CatalogRig
    let fixture: PanelFixture
    var detail: PortDetailState { fixture.status.detail }
    var panel: OffscreenStatusPanel { fixture.panel }
    static let escape = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 1, windowNumber: 0, context: nil,
                                         characters: "\u{1b}", charactersIgnoringModifiers: "\u{1b}", isARepeat: false, keyCode: 53)!
    init() async throws {
        catalog = try CatalogRig()
        fixture = try PanelFixture(home: FileManager.default.temporaryDirectory, catalog: catalog.store)
        await fixture.rig.start()
        await detailReply(fixture.rig, syntheticDetails())
        fixture.begin()
        detail.toggle(.c1, NamingContext(monitor: fixture.rig.controller, store: catalog.store))
        await pumpRunLoop()
    }
    var host: StatusHostingController { panel.contentViewController!.children.first as! StatusHostingController }
    func field() throws -> NSTextField { try #require(editableTextFields(in: panel.contentView!).first) }
    var fieldEditing: Bool { panel.firstResponder is NSText }
    func focusAndType(_ text: String) async throws {
        #expect(panel.makeFirstResponder(try field())); await pumpRunLoop()
        try await typeIntoFieldEditor(panel, text)
        #expect(detail.editing && detail.draft?.text == text && fieldEditing)
    }
    func finish() async { fixture.status.dismiss(); catalog.store.panelClosed(); await fixture.rig.finish() }
}
@MainActor struct StatusPanelNamingTests {
    /// Every cancellation route cancels the edit while naming, keeps the panel
    /// open and clears the field's focus; the focus transition commits nothing,
    /// and a later Escape outside editing dismisses normally.
    @Test(arguments: ["escape-event", "key-equivalent", "panel-cancel", "hosting-cancel"])
    func escapeWhileNamingCancelsTheEditThenDismisses(_ route: String) async throws {
        await HostedFieldLock.shared.acquire(); defer { HostedFieldLock.shared.release() }
        let naming = try await NamingPanel()
        try await naming.focusAndType("Synthetic Abandoned Name")
        switch route {
        // The field editor receives the key: AppKit's cancelOperation reaches
        // the TextField's onExitCommand.
        case "escape-event": naming.panel.sendEvent(NamingPanel.escape)
        case "key-equivalent": #expect(naming.panel.performKeyEquivalent(with: NamingPanel.escape))
        case "panel-cancel": naming.panel.cancelOperation(nil)
        default: naming.host.cancelOperation(nil)
        }
        #expect(naming.panel.isVisible && naming.fixture.cancelCount == 0 && naming.panel.hides == 0)
        #expect(!naming.detail.dirty && !naming.detail.editing && !naming.fieldEditing)
        // The subsequent focus transition and field value push.
        await pumpRunLoop()
        #expect(!naming.detail.dirty && naming.catalog.files.count("replace") == 0)
        #expect(try naming.catalog.store.catalog.devices.isEmpty && naming.field().stringValue == "")
        #expect(naming.detail.expanded == .c1)
        // Outside editing, the same route dismisses once.
        switch route {
        case "escape-event", "key-equivalent": #expect(naming.panel.performKeyEquivalent(with: NamingPanel.escape))
        case "panel-cancel": naming.panel.cancelOperation(nil)
        default: naming.host.cancelOperation(nil)
        }
        #expect(!naming.panel.isVisible && naming.fixture.cancelCount == 1 && naming.panel.hides == 1)
        await naming.finish()
    }
    /// Switching or collapsing the edited row saves and removes the focused
    /// field; the next Escape must dismiss rather than cancel a stale edit.
    @Test(arguments: [PortID.c2, .c1])
    func rowChangeWhileNamingSavesAndTheNextEscapeDismisses(_ destination: PortID) async throws {
        await HostedFieldLock.shared.acquire(); defer { HostedFieldLock.shared.release() }
        let naming = try await NamingPanel()
        try await naming.focusAndType("Synthetic Switched Name")
        #expect(naming.detail.toggle(destination, NamingContext(monitor: naming.fixture.rig.controller, store: naming.catalog.store)))
        await pumpRunLoop()
        #expect(naming.detail.expanded == (destination == .c1 ? nil : destination))
        #expect(naming.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Switched Name"] && !naming.detail.dirty)
        #expect(!naming.detail.editing && !naming.fieldEditing)
        #expect(naming.panel.performKeyEquivalent(with: NamingPanel.escape))
        #expect(!naming.panel.isVisible && naming.fixture.cancelCount == 1 && naming.panel.hides == 1)
        await naming.finish()
    }
    /// A snapshot that removes the focused field (device unplugged, unresolved
    /// or replaced) must not leave Escape cancelling an unseen edit.
    @Test(arguments: ["unplugged", "unresolved", "replaced"])
    func snapshotRemovingTheFieldLetsEscapeDismissWithoutWriting(_ change: String) async throws {
        await HostedFieldLock.shared.acquire(); defer { HostedFieldLock.shared.release() }
        let naming = try await NamingPanel()
        try await naming.focusAndType("Synthetic Vanished Draft")
        switch change {
        case "unplugged": await detailReply(naming.fixture.rig, syntheticDetails(c1: .nothingAttached))
        case "unresolved": await detailReply(naming.fixture.rig, syntheticDetails(c1: .identifying))
        default:
            await detailReply(naming.fixture.rig, syntheticDetails(c1: .identified(vendorID: 0xfeed, productID: 0x0001, brandClass: nil, modelCode: nil)))
        }
        await pumpRunLoop()
        if change == "replaced" { #expect(try naming.field().stringValue == "") }
        else { #expect(editableTextFields(in: naming.panel.contentView!).isEmpty) }
        #expect(!naming.detail.editing && !naming.fieldEditing)
        #expect(naming.panel.performKeyEquivalent(with: NamingPanel.escape))
        #expect(!naming.panel.isVisible && naming.fixture.cancelCount == 1)
        // Closing settled the unshown draft by discarding it: nothing was written.
        #expect(naming.catalog.files.count("replace") == 0 && naming.catalog.store.catalog.devices.isEmpty && !naming.detail.dirty)
        await naming.finish()
    }
    @Test func quittingSavesThePendingNameAndAFailureDoesNotThrow() async throws {
        await HostedFieldLock.shared.acquire(); defer { HostedFieldLock.shared.release() }
        let naming = try await NamingPanel()
        try await naming.focusAndType("Synthetic Quit Name")
        naming.fixture.status.settlePendingEdits()
        #expect(naming.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Quit Name"] && !naming.detail.dirty)
        naming.catalog.files.failWrites = true
        try await typeIntoFieldEditor(naming.panel, "Synthetic Unsaved Quit Name")
        naming.fixture.status.settlePendingEdits()
        #expect(naming.detail.dirty && naming.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Quit Name"])
        await naming.finish()
    }
    @Test func closingSavesTheEditAndReopeningLeavesTheFieldUnfocused() async throws {
        await HostedFieldLock.shared.acquire(); defer { HostedFieldLock.shared.release() }
        let naming = try await NamingPanel()
        try await naming.focusAndType("Synthetic Closing Name")
        naming.fixture.end()
        #expect(!naming.panel.isVisible && naming.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Closing Name"])
        #expect(try naming.catalog.devices() == ["0A1B:2C3D": "Synthetic Closing Name"] && !naming.detail.dirty)
        naming.fixture.begin(); await pumpRunLoop()
        #expect(naming.panel.isVisible && !naming.fieldEditing && naming.detail.expanded == .c1)
        #expect(try naming.field().stringValue == "Synthetic Closing Name")
        // A first Escape with nothing to cancel dismisses.
        #expect(naming.panel.performKeyEquivalent(with: NamingPanel.escape))
        #expect(!naming.panel.isVisible)
        await naming.finish()
    }
    @Test func failedSaveAtClosingShowsItsDraftAndErrorAfterReopening() async throws {
        await HostedFieldLock.shared.acquire(); defer { HostedFieldLock.shared.release() }
        let naming = try await NamingPanel()
        naming.catalog.files.failWrites = true
        try await naming.focusAndType("Synthetic Unsaved Name")
        naming.fixture.end(); await pumpRunLoop()
        #expect(!naming.panel.isVisible && naming.detail.dirty)
        naming.fixture.begin(); await pumpRunLoop()
        let lamp = NamingTarget(charger: appCharger.serial, port: .c1, key: syntheticLamp)
        let failure = try #require(naming.detail.failure(for: lamp))
        #expect(try naming.detail.expanded == .c1 && naming.field().stringValue == "Synthetic Unsaved Name")
        // Retry through Return in the real field.
        naming.catalog.files.failWrites = false
        #expect(naming.panel.makeFirstResponder(try naming.field())); await pumpRunLoop()
        let editor = try #require(naming.panel.firstResponder as? NSTextView)
        editor.insertNewline(nil); await pumpRunLoop()
        #expect(!naming.detail.dirty && naming.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Unsaved Name"])
        #expect(naming.detail.failure(for: lamp) == nil && failure.inlineText.hasPrefix("Name not saved"))
        await naming.finish()
    }
}
@MainActor struct StatusPanelIntegrationTests {
    @Test func nativeCyclesAcknowledgeUpdatesAndNeverActivateApplication() throws {
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        for _ in 0..<6 { fixture.begin(); fixture.end() }
        #expect(fixture.activations == 0 && fixture.panel.hides == 6)
        // BV release acknowledgment persistence has no charger equivalent.
        fixture.end(); #expect(fixture.panel.hides == 6)
    }
    @Test func settingsAndCustomIntervalCancelBeforePresentingOwnedSettings() throws {
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: home) }
        let fixture = try PanelFixture(home: home)
        fixture.begin()
        let host = try #require(fixture.panel.contentViewController?.children.first as? StatusHostingController)
        host.rootView.showSettings()
        #expect(fixture.cancelCount == 1 && fixture.settingsPresentations == 1)
        #expect(!fixture.visibleAtSettingsPresentation)
        // Custom update interval is outside Prime Monitor v1; Settings route above is retained.
    }
    @Test func applicationResignAndPendingNativeEndLeaveNoDelayedReopen() throws {
        let home = FileManager.default.temporaryDirectory.appending(path: "synthetic-panel-" + UUID().uuidString, directoryHint: .isDirectory)
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

@MainActor struct StatusItemWidthTests {
    @Test func pressAndReleaseEachUseTheCurrentFrame() throws {
        let fixture = try PanelFixture(home: FileManager.default.temporaryDirectory)
        fixture.begin()
        fixture.status.globalMouseDown(at: PanelFixture.onIcon, time: 101)
        fixture.currentAnchor = NSRect(x: -100, y: 778, width: 80, height: 22)
        fixture.status.globalMouseUp(at: NSPoint(x: -95, y: 790))
        #expect(!fixture.panel.isVisible)
        fixture.begin()
        fixture.status.globalMouseDown(at: NSPoint(x: -95, y: 790), time: 102)
        fixture.currentAnchor = PanelFixture.icon
        fixture.status.globalMouseUp(at: NSPoint(x: -95, y: 790))
        #expect(fixture.panel.isVisible)
        fixture.status.dismiss()
    }
    @Test func panelStaysAnchoredWhenWidthChanges() throws {
        let fixture = try PanelFixture(home: FileManager.default.temporaryDirectory)
        fixture.begin()
        let content = try #require(fixture.panel.contentViewController as? StatusPanelContentController)
        fixture.currentAnchor = NSRect(x: -500, y: 778, width: 120, height: 22)
        fixture.item.button?.frame.size.width = 120
        #expect(fixture.panel.frame == StatusPanelFrame.make(contentSize: content.desiredContentSize, anchor: fixture.currentAnchor, screens: [PanelFixture.screen]))
        fixture.status.dismiss()
    }
    @Test func panelOpenAndCloseDriveController() async throws {
        let fixture = try PanelFixture(home: FileManager.default.temporaryDirectory)
        await fixture.rig.start()
        let before = await fixture.rig.backend.log.filter { $0 == "request" }.count
        fixture.begin(); await settle()
        #expect(await fixture.rig.backend.log.filter { $0 == "request" }.count == before + 1)
        await fixture.rig.clock.advance(5)
        #expect(await fixture.rig.backend.log.filter { $0 == "request" }.count == before + 2)
        fixture.end()
        await fixture.rig.clock.advance(59)
        #expect(await fixture.rig.backend.log.filter { $0 == "request" }.count == before + 2)
        await fixture.rig.clock.advance(1)
        #expect(await fixture.rig.backend.log.filter { $0 == "request" }.count == before + 3)
        await fixture.rig.finish()
    }
}

private func catalogText(vendor: String) -> Data {
    Data(#"{"schema": 1, "brands": {}, "vendors": {"0a1b": "\#(vendor)"}, "devices": {}}"#.utf8)
}
private func path(_ operation: DeviceCatalogFileOperation) -> String {
    switch operation {
    case .inspect(let url), .read(let url), .create(let url), .replace(let url): url.path(percentEncoded: false)
    }
}
@MainActor struct StatusPanelCatalogTests {
    @Test func panelPresentationPairsCatalogReloadLifecycle() async throws {
        let fixture = try PanelFixture(home: FileManager.default.temporaryDirectory)
        let file = try #require(fixture.catalogFile)
        let catalog = fixture.status.catalog
        #expect(catalog.fileURL == file)
        fixture.begin()
        try PrivateFile.replace(file, with: catalogText(vendor: "Synthetic Vendor"), temporaryPrefix: ".editor-")
        await fixture.rig.clock.advance(1)
        #expect(catalog.catalog.vendors == [0x0a1b: "Synthetic Vendor"])
        fixture.end(); #expect(!fixture.panel.isVisible)
        try PrivateFile.replace(file, with: catalogText(vendor: "Synthetic Later Vendor"), temporaryPrefix: ".editor-")
        await fixture.rig.clock.advance(3)
        #expect(catalog.catalog.vendors == [0x0a1b: "Synthetic Vendor"])
        // Reopening refreshes immediately; a programmatic dismissal also stops the loop.
        fixture.status.showPopover()
        #expect(catalog.catalog.vendors == [0x0a1b: "Synthetic Later Vendor"])
        fixture.status.dismiss()
        try PrivateFile.replace(file, with: catalogText(vendor: "Synthetic Closed Vendor"), temporaryPrefix: ".editor-")
        await fixture.rig.clock.advance(3)
        #expect(catalog.catalog.vendors == [0x0a1b: "Synthetic Later Vendor"])
    }
    @Test func omittedCatalogsStayFilelessThroughOpeningClosingReloadingAndNaming() async throws {
        var events: [(store: ObjectIdentifier, operation: DeviceCatalogFileOperation)] = []
        let token = UUID()
        DeviceCatalogStore.fileAccessObservers[token] = { events.append(($0, $1)) }
        defer { DeviceCatalogStore.fileAccessObservers[token] = nil }
        let rig = try ControllerRig()
        // AppDelegate's omitted catalog is what its default status factory passes on.
        let delegate = AppDelegate(controller: rig.controller, acquireLease: { AppInstanceLease {} })
        let fixture = try PanelFixture(home: FileManager.default.temporaryDirectory, catalog: delegate.catalog)
        let catalog = fixture.status.catalog
        #expect(catalog === delegate.catalog && catalog.fileURL == nil && fixture.catalogFile == nil)
        let settings = SettingsWindowController(controller: rig.controller, login: LoginItem(service: LoginServiceStub()), activate: {}, present: { _ in })
        #expect(StatusContent(controller: rig.controller, settings: settings, focus: PopoverFocus()).catalog.fileURL == nil)
        #expect(PanelView(monitor: rig.controller, openSettings: {}).catalog.fileURL == nil)
        fixture.begin()
        await fixture.rig.clock.advance(3)
        fixture.end()
        fixture.status.showPopover()
        let key = DeviceKey(vendorID: 0x0a1b, productID: 0x2c3d)
        try catalog.setName("Synthetic Desk Lamp", for: key)
        #expect(catalog.catalog.devices == [key: "Synthetic Desk Lamp"])
        await fixture.rig.clock.advance(2)
        fixture.status.dismiss()
        try catalog.setName(nil, for: key)
        #expect(catalog.catalog == DeviceCatalog() && catalog.problem == nil)
        #expect(!events.contains { $0.store == ObjectIdentifier(catalog) })
        // No store touched the owner's runtime directory meanwhile.
        let owner = StateStore().fileURL.deletingLastPathComponent().path(percentEncoded: false)
        #expect(!events.contains { path($0.operation).hasPrefix(owner) })
        // Positive control: the same instrumentation observes a persistent store.
        let control = try CatalogRig()
        control.store.load()
        #expect(events.contains { $0.store == ObjectIdentifier(control.store) })
        await rig.finish()
    }
}

@MainActor struct StatusButtonObservationTests {
    @Test(arguments: ["stale", "network", "error", "session-ended"])
    func retainedAgeUpdatesActualButtonTooltipAndAccessibility(_ state: String) async throws {
        let fixture = try PanelFixture(home: FileManager.default.temporaryDirectory)
        await fixture.rig.start()
        let reading = PortReading(port: .c4, active: true, voltageMilli: 20000, currentMilli: 1551, powerCenti: 4321)
        fixture.rig.backend.output.snapshot(.init(receivedAt: fixture.rig.clock.date, readings: [reading]))
        await settle()
        let reason: String
        switch state {
        case "network": await fixture.rig.events.send(.network(false)); reason = "Network unavailable"
        case "error": fixture.rig.backend.output.yield(.status(.error("Synthetic status failure"))); reason = "Synthetic status failure"
        case "session-ended": fixture.rig.backend.output.yield(.status(.sessionEnded)); reason = "Session ended — sign in again"
        default: reason = "Stale readings"
        }
        await settle(); await fixture.rig.clock.advance(131); await settle()
        let snapshot = fixture.rig.controller.snapshot, status = fixture.rig.controller.status
        #expect(fixture.rig.controller.isStale)
        let button = try #require(fixture.item.button)
        let before = reason + "; updated 2 min ago"
        #expect(button.toolTip == before)
        #expect(button.accessibilityLabel() == "Anker Charge Monitor, 43.21 W, " + before)
        #expect(button.accessibilityHelp() == "Anker Charge Monitor, 43.21 W, " + before)
        let requests = await fixture.rig.backend.log.filter { $0 == "request" }.count
        await fixture.rig.clock.advance(60); await settle()
        #expect(fixture.rig.controller.snapshot == snapshot && fixture.rig.controller.status == status && fixture.rig.controller.isStale)
        let after = reason + "; updated 3 min ago"
        #expect(button.toolTip == after)
        #expect(button.accessibilityLabel() == "Anker Charge Monitor, 43.21 W, " + after)
        #expect(button.accessibilityHelp() == "Anker Charge Monitor, 43.21 W, " + after)
        #expect(await fixture.rig.backend.log.filter { $0 == "request" }.count == requests + (state == "stale" ? 1 : 0))
        await fixture.rig.finish()
    }
    /// Width of the symbol, the gap and the reading, measured apart from StatusImage.
    static func composedWidth(_ title: String, symbol: String = "bolt.fill", size: MenuBarTextSize) throws -> CGFloat {
        let image = try #require(NSImage(systemSymbolName: symbol, accessibilityDescription: nil)?.withSymbolConfiguration(.init(pointSize: size.pointSize, weight: .regular)))
        let text = title.isEmpty ? 0 : StatusImage.gap + NSAttributedString(string: title, attributes: [.font: NSFont.monospacedDigitSystemFont(ofSize: size.pointSize, weight: .regular)]).size().width
        return ceil(image.size.width + text)
    }
    /// The most opaque pixel of `image` drawn under `name`: its alpha and red level.
    static func ink(_ image: NSImage, _ name: NSAppearance.Name) throws -> (alpha: CGFloat, level: CGFloat) {
        let rep = try #require(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(image.size.width), pixelsHigh: Int(image.size.height), bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
        try #require(NSAppearance(named: name)).performAsCurrentDrawingAppearance {
            NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
            image.draw(in: NSRect(origin: .zero, size: image.size)); NSGraphicsContext.restoreGraphicsState()
        }
        var peak: (alpha: CGFloat, level: CGFloat) = (0, 0)
        for y in 0..<rep.pixelsHigh { for x in 0..<rep.pixelsWide {
            if let color = rep.colorAt(x: x, y: y), color.alphaComponent > peak.alpha { peak = (color.alphaComponent, color.redComponent) }
        } }
        return peak
    }
    @Test func monitorPresentationUpdatesActualStatusButton() async throws {
        let fixture = try PanelFixture(home: FileManager.default.temporaryDirectory)
        await fixture.rig.start()
        let reading = PortReading(port: .c4, active: true, voltageMilli: 20000, currentMilli: 1551, powerCenti: 4321)
        fixture.rig.backend.output.snapshot(.init(receivedAt: fixture.rig.clock.date, readings: [reading]))
        await settle()
        let button = try #require(fixture.item.button)
        // One image holds the symbol and reading, so the button has no title
        // and no title-cell insets. A thin space separates the unit.
        #expect(button.imagePosition == .imageOnly)
        #expect(button.title.isEmpty && button.attributedTitle.length == 0)
        let image = try #require(button.image)
        #expect(!image.isTemplate)
        #expect(image.size.width == (try Self.composedWidth("43.21\u{2009}W", size: .default)))
        #expect(image.accessibilityDescription?.contains("43.21 W") == true)
        // Convert before #expect: its operand capture mis-compares mixed Double and CGFloat.
        let standard = CGFloat(MenuBarTextSize.default.pointSize), menuBarFont = NSFont.menuBarFont(ofSize: 0).pointSize
        #expect(standard == menuBarFont)
        #expect(StatusImage.font(.default) == NSFont.monospacedDigitSystemFont(ofSize: 13, weight: .regular))
        #expect(button.toolTip?.contains("Connected") == true)
        #expect(button.accessibilityLabel()?.contains("43.21 W") == true)
        await fixture.rig.events.send(.network(false)); await settle()
        // The macOS 27 menu bar draws a tinted template image black, so the
        // dimmed colour is drawn into the image rather than set as a tint.
        #expect(button.contentTintColor == nil)
        let dimmed = try #require(button.image)
        #expect(dimmed !== image && !dimmed.isTemplate)
        #expect(dimmed.size.width == (try Self.composedWidth("43.21\u{2009}W", symbol: "exclamationmark.triangle.fill", size: .default)))
        #expect(try Self.ink(dimmed, .vibrantDark).level < Self.ink(image, .vibrantDark).level - 0.3)
        #expect(button.toolTip?.contains("Network unavailable") == true)
        #expect(button.title.isEmpty)
        await fixture.rig.finish()
    }
    @Test func textSizeSettingResizesTheActualStatusButtonImmediately() async throws {
        let fixture = try PanelFixture(home: FileManager.default.temporaryDirectory)
        await fixture.rig.start()
        let reading = PortReading(port: .c4, active: true, voltageMilli: 20000, currentMilli: 1551, powerCenti: 4321)
        fixture.rig.backend.output.snapshot(.init(receivedAt: fixture.rig.clock.date, readings: [reading]))
        await settle()
        let button = try #require(fixture.item.button)
        for size in MenuBarTextSize.allCases.reversed() {
            fixture.rig.controller.setMenuBarTextSize(size); await settle()
            let image = try #require(button.image)
            #expect(image.size.width == (try Self.composedWidth("43.21\u{2009}W", size: size)))
            #expect(!image.isTemplate && button.imagePosition == .imageOnly && button.title.isEmpty)
        }
        #expect(StateStore(fileURL: fixture.directory.appending(path: "state.json", directoryHint: .notDirectory)).load().state.menuBarTextSize == .pt10)
        await fixture.rig.finish()
    }
    /// NSStatusBarButton's title cell pads a title by about 3 pt on each side.
    /// The button must be exactly as wide as its image, in every state and size.
    @Test func statusButtonAddsNoTitleInsets() throws {
        let snapshot = ChargerSnapshot(receivedAt: Date(), readings: [.init(port: .c4, active: true, voltageMilli: 20000, currentMilli: 1551, powerCenti: 3576)])
        for size in MenuBarTextSize.allCases {
            for (status, stale) in [(ConnectionStatus.connected, false), (.connected, true), (.networkUnavailable, false), (.notConfigured, false)] {
                let presentation = StatusPresentation.make(status: status, snapshot: status == .notConfigured ? nil : snapshot, isStale: stale, now: Date(), textSize: size)
                let button = NSStatusBarButton(frame: .zero); button.isBordered = false
                presentation.apply(to: button); button.sizeToFit()
                let image = try #require(button.image)
                #expect(image.size.width == (try Self.composedWidth(presentation.title, symbol: presentation.symbol, size: size)))
                #expect(button.frame.width == image.size.width)
                #expect(button.intrinsicContentSize.width == image.size.width)
            }
        }
    }
    /// The image is drawn at draw time, so one image follows every appearance:
    /// opaque ink for a live reading, and a visible grey (never black on a
    /// dark bar) when dimmed.
    @Test func composedImageInkFollowsTheBarAppearance() throws {
        let live = try #require(StatusImage.make(for: .init(symbol: "bolt.fill", title: "43.21\u{2009}W", dimmed: false, tooltip: "", accessibility: "")))
        let dimmed = try #require(StatusImage.make(for: .init(symbol: "exclamationmark.triangle.fill", title: "43.21\u{2009}W", dimmed: true, tooltip: "", accessibility: "")))
        for name in [NSAppearance.Name.aqua, .vibrantLight] {
            let ink = try Self.ink(live, name)
            #expect(ink.alpha > 0.99 && ink.level < 0.05, "\(name.rawValue)")
        }
        for name in [NSAppearance.Name.darkAqua, .vibrantDark] {
            let ink = try Self.ink(live, name)
            #expect(ink.alpha > 0.99 && ink.level > 0.95, "\(name.rawValue)")
        }
        for name in [NSAppearance.Name.vibrantLight, .vibrantDark] {
            let ink = try Self.ink(dimmed, name)
            #expect(ink.level > 0.3 && ink.level < 0.7, "\(name.rawValue)")
        }
        for name in [NSAppearance.Name.aqua, .darkAqua] {
            #expect(try Self.ink(dimmed, name).alpha < 0.7, "\(name.rawValue)")
        }
    }
    @Test func everyTextSizeIsNarrowerThanThePreviousLayouts() {
        func width(_ configure: (NSStatusBarButton) -> Void) -> CGFloat {
            let button = NSStatusBarButton(frame: .zero); button.isBordered = false
            configure(button); button.sizeToFit(); return button.frame.width
        }
        // The 0.1.1 layout: default-size symbol, leading space and a full space before the unit.
        let original = width { button in
            button.image = NSImage(systemSymbolName: "bolt.fill", accessibilityDescription: nil); button.imagePosition = .imageLeading
            button.attributedTitle = NSAttributedString(string: " 43.21 W", attributes: [.font: NSFont.monospacedDigitSystemFont(ofSize: 13, weight: .regular)])
        }
        // The 0.2.0 layout at the same size: sized symbol plus a button title,
        // which the title cell pads by about 3 pt on each side.
        func titled(_ size: MenuBarTextSize) -> CGFloat {
            width { button in
                button.image = NSImage(systemSymbolName: "bolt.fill", accessibilityDescription: nil)?.withSymbolConfiguration(.init(pointSize: size.pointSize, weight: .regular))
                button.imagePosition = .imageLeading
                button.attributedTitle = NSAttributedString(string: "43.21\u{2009}W", attributes: [.font: NSFont.monospacedDigitSystemFont(ofSize: size.pointSize, weight: .regular)])
            }
        }
        let snapshot = ChargerSnapshot(receivedAt: Date(), readings: [.init(port: .c4, active: true, voltageMilli: 20000, currentMilli: 1551, powerCenti: 4321)])
        let widths = MenuBarTextSize.allCases.map { size in
            width { StatusPresentation.make(status: .connected, snapshot: snapshot, isStale: false, now: Date(), textSize: size).apply(to: $0) }
        }
        #expect(widths.allSatisfy { $0 < original - 4 })
        #expect(zip(MenuBarTextSize.allCases, widths).allSatisfy { $1 < titled($0) - 1 })
        #expect(zip(widths, widths.dropFirst()).allSatisfy { $0 < $1 })
    }
}
