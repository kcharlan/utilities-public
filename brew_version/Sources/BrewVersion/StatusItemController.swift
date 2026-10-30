import AppKit
import SwiftUI
import Observation
import BrewVersionCore

@MainActor @Observable final class PopoverFocus { var generation = UUID() }
struct StatusContent: View {
    let controller: WatchController
    let notifier: UserNotifier
    let settings: SettingsWindowController
    let focus: PopoverFocus
    let accessory: AnyView?
    var dismiss: () -> Void = {}
    var sizeChanged: (NSSize) -> Void = { _ in }
    var body: some View {
        VStack(spacing: 0) {
            PopoverView(controller: controller, notifier: notifier, openSettings: showSettings, focusGeneration: focus.generation, openCustomInterval: showCustomInterval)
            if let accessory { accessory }
        }.fixedSize(horizontal: false, vertical: true)
            .onGeometryChange(for: NSSize.self, of: { $0.size }, action: sizeChanged)
    }
    func showSettings() { dismiss(); settings.show() }
    func showCustomInterval() { dismiss(); settings.showCustomInterval() }
    func makeHostingController() -> StatusHostingController {
        let hosting = StatusHostingController(rootView: self)
        hosting.dismiss = dismiss
        var content = self
        content.sizeChanged = { [weak hosting] in hosting?.measuredSizeChanged($0) }
        hosting.rootView = content
        // Retained hosting consumers can also read the preferred-size contract.
        // The owned panel follows SwiftUI's measured content geometry.
        hosting.sizingOptions.insert(.preferredContentSize)
        return hosting
    }
}
@MainActor final class StatusHostingController: NSHostingController<StatusContent> {
    var dismiss: () -> Void = {}
    var measuredSizeChanged: (NSSize) -> Void = { _ in }
    override func cancelOperation(_ sender: Any?) { dismiss() }
}
@MainActor protocol PopoverPresenting: AnyObject { func showPopover() }

/// On macOS 27 MenuBarAgent hosts the status item, so the expanded-interface
/// session is the reliable record of a press that opens the panel: begin shows
/// the panel, end hides it, and every owned dismissal hides the panel
/// synchronously and then cancels the session it was showing. A press on the
/// icon of an open panel reaches neither this app nor the session, so a global
/// mouse monitor recognizes that one closing press.
@MainActor final class StatusItemController: NSObject, @MainActor NSStatusItemExpandedInterfaceDelegate, NSWindowDelegate, PopoverPresenting {
    private let controller: WatchController
    private let item: NSStatusItem
    private let panel: StatusPanel
    private let focus = PopoverFocus()
    private let settings: SettingsWindowController
    private let notifications: NotificationCenter
    private let workspaceNotifications: NotificationCenter
    private let screens: () -> [StatusScreen]
    private let anchor: () -> NSRect?
    private let pointer: () -> NSPoint
    private let activate: () -> Void
    private let cancelSession: (NSStatusItemExpandedInterfaceSession) -> Void
    private let now: () -> TimeInterval
    private var statusObservation: StatusObservation?
    nonisolated(unsafe) private var globalMouseMonitor: Any?
    /// The session whose presentation is visible; nil when the panel is hidden
    /// or was opened by Finder or a notification without a session.
    private var session: NSStatusItemExpandedInterfaceSession?
    /// System uptime when the visible session began, on the NSEvent clock.
    private var sessionBegan: TimeInterval = 0
    private var iconPressStartedWhileOpen = false
    init(controller: WatchController, notifier: UserNotifier, accessory: AnyView? = nil,
         item suppliedItem: NSStatusItem? = nil, panel suppliedPanel: StatusPanel? = nil,
         settings suppliedSettings: SettingsWindowController? = nil, notifications: NotificationCenter = .default,
         workspaceNotifications: NotificationCenter = NSWorkspace.shared.notificationCenter,
         screens: @escaping () -> [StatusScreen] = { NSScreen.screens.map { StatusScreen(frame: $0.frame, visibleFrame: $0.visibleFrame) } },
         anchor: (() -> NSRect?)? = nil,
         pointer: @escaping () -> NSPoint = { NSEvent.mouseLocation },
         now: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
         monitorGlobalMouse: (@escaping @MainActor (NSEvent.EventType, NSPoint, TimeInterval) -> Void) -> Any? = { handle in
             // Global events carry screen locations and uptime timestamps.
             NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .leftMouseUp]) { event in
                 let type = event.type, location = event.locationInWindow, time = event.timestamp
                 MainActor.assumeIsolated { handle(type, location, time) }
             }
         },
         cancelSession: @escaping (NSStatusItemExpandedInterfaceSession) -> Void = { $0.cancel() },
         activate: @escaping () -> Void = { NSApp.activate(ignoringOtherApps: true) }) {
        self.controller = controller
        let item = suppliedItem ?? Self.makeItem()
        self.item = item
        panel = suppliedPanel ?? StatusPanel()
        settings = suppliedSettings ?? SettingsWindowController(controller: controller, notifier: notifier)
        self.notifications = notifications
        self.workspaceNotifications = workspaceNotifications
        self.screens = screens
        self.pointer = pointer
        self.now = now
        self.cancelSession = cancelSession
        self.activate = activate
        self.anchor = anchor ?? {
            guard let button = item.button, let window = button.window else { return nil }
            return window.convertToScreen(button.convert(button.bounds, to: nil))
        }
        super.init()
        let hosting = StatusContent(controller: controller, notifier: notifier, settings: settings, focus: focus, accessory: accessory, dismiss: { [weak self] in self?.dismiss() }).makeHostingController()
        let content = StatusPanelContentController(hosting: hosting)
        content.sizeChanged = { [weak self] in self?.positionPanel() }
        panel.contentViewController = content
        if let guide = panel.contentLayoutGuide {
            // A measured resize can precede the window's frame-view layout.
            // Explicit edges avoid capturing that temporary gap in translated
            // autoresizing constraints and applying it again during layout.
            content.view.autoresizingMask = []
            content.view.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([NSLayoutConstraint.Attribute.leading, .trailing, .top, .bottom].map {
                NSLayoutConstraint(item: content.view, attribute: $0, relatedBy: .equal, toItem: guide, attribute: $0, multiplier: 1, constant: 0)
            })
        }
        item.expandedInterfaceDelegate = self
        panel.delegate = self
        panel.dismiss = { [weak self] in self?.dismiss() }
        notifications.addObserver(self, selector: #selector(applicationResignedActive), name: NSApplication.didResignActiveNotification, object: NSApp)
        workspaceNotifications.addObserver(self, selector: #selector(workspaceActivatedApplication), name: NSWorkspace.didActivateApplicationNotification, object: nil)
        globalMouseMonitor = monitorGlobalMouse { [weak self] type, location, time in
            if type == .leftMouseDown { self?.globalMouseDown(at: location, time: time) } else { self?.globalMouseUp(at: location) }
        }
        statusObservation = StatusObservation(controller: controller) { [weak self] presentation in
            guard let self else { return }
            self.item.button?.image = StatusIcon.image(for: presentation)
            self.item.button?.setAccessibilityLabel(presentation.accessibility)
            self.item.button?.setAccessibilityHelp(presentation.accessibility)
            self.item.button?.toolTip = presentation.accessibility
        }
    }
    /// Variable length fits the item to its mug. Square length pads every
    /// image to the bar's 22pt thickness, leaving wide gaps beside the
    /// narrower mug; the amber dot widens the item by a few points instead.
    static func makeItem(in bar: NSStatusBar = .system) -> NSStatusItem {
        bar.statusItem(withLength: NSStatusItem.variableLength)
    }
    deinit {
        notifications.removeObserver(self)
        workspaceNotifications.removeObserver(self)
        if let globalMouseMonitor { NSEvent.removeMonitor(globalMouseMonitor) }
    }
    func statusItem(_ statusItem: NSStatusItem, didBegin session: NSStatusItemExpandedInterfaceSession) {
        if panel.isVisible && self.session == nil {
            // Finder or a notification opened the panel without a session, so
            // the system reports this press as an opening. The user pressed
            // the icon of an open panel: close it.
            hidePanel()
            cancelSession(session)
            return
        }
        self.session = session
        sessionBegan = now()
        presentPanel()
    }
    func statusItemDidEndExpandedInterfaceSession(_ statusItem: NSStatusItem, animated: Bool) {
        // The property is cleared before the end callback. Ends for a session
        // already dropped here, or for an older session after a newer begin,
        // leave the current presentation alone.
        guard let current = session, item.expandedInterfaceSession !== current else { return }
        session = nil
        hidePanel()
    }
    func showPopover() {
        guard !panel.isVisible else { return }
        activate()
        presentPanel()
    }
    func dismiss() {
        hidePanel()
        guard let ending = session else { return }
        session = nil
        cancelSession(ending)
    }
    private func presentPanel() {
        guard !panel.isVisible else { return }
        focus.generation = UUID()
        positionPanel()
        panel.makeKeyAndOrderFront(nil)
        controller.acknowledgeAlerts()
    }
    private func hidePanel() {
        guard panel.isVisible else { return }
        panel.orderOut(nil)
        controller.popoverClosed()
    }
    @objc private func applicationResignedActive(_ notification: Notification) { focusLeft() }
    @objc private func workspaceActivatedApplication(_ notification: Notification) {
        guard let application = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
              application.processIdentifier != ProcessInfo.processInfo.processIdentifier,
              application.bundleIdentifier != "com.apple.MenuBarAgent" else { return }
        // A real application activation is independent of the pointer. The
        // status-item host can take focus before begin; leave that transition
        // to the session, but dismiss a keyboard switch even over our icon.
        dismiss()
    }
    func windowDidResignKey(_ notification: Notification) {
        if !panel.isKeyWindow { focusLeft() }
    }
    private func focusLeft() {
        // Pressing the icon takes focus from this app before the system's
        // matching begin or end arrives. That press belongs to the session;
        // dismissing for it here would let the begin reopen the panel.
        guard panel.isVisible, !onIcon(pointer()) else { return }
        dismiss()
    }
    /// The press that opened the panel always went down before its begin
    /// arrived, so only a press that started later, on the icon, closes it. A
    /// Finder or notification opening has no session; its begin closes it.
    func globalMouseDown(at location: NSPoint, time: TimeInterval) {
        iconPressStartedWhileOpen = session != nil && time > sessionBegan && onIcon(location)
    }
    func globalMouseUp(at location: NSPoint) {
        guard iconPressStartedWhileOpen else { return }
        iconPressStartedWhileOpen = false
        if session != nil && onIcon(location) { dismiss() }
    }
    private func onIcon(_ point: NSPoint) -> Bool {
        StatusPanelFrame.iconContains(point, anchor: anchor(), screens: screens())
    }
    private func positionPanel() {
        guard let view = panel.contentViewController?.view else { return }
        let preferred = (panel.contentViewController as? StatusPanelContentController)?.desiredContentSize ?? .zero
        let fitting = view.fittingSize
        let size = NSSize(width: preferred.width > 0 ? preferred.width : fitting.width, height: preferred.height > 0 ? preferred.height : fitting.height)
        guard let frame = StatusPanelFrame.make(contentSize: size, anchor: anchor(), screens: screens()) else { return }
        panel.setFrame(frame, display: panel.isVisible)
    }
    func setAppearance(_ appearance: NSAppearance?) {
        NSApp.appearance = appearance
        panel.appearance = appearance
        settings.setAppearance(appearance)
    }
}
