// Port: BrewVersion/Sources/BrewVersion/StatusItemController.swift, StatusItemController, 579ebb7.
// Adaptation: MonitorController and charger content replace BV watches/notifications; no custom interval.
import AppKit
import SwiftUI
import Observation
import PrimeMonitorCore

@MainActor @Observable final class PopoverFocus { var generation = UUID() }
struct StatusContent: View {
    let controller: MonitorController
    var catalog = DeviceCatalogStore()
    var detail = PortDetailState()
    let settings: SettingsWindowController
    let focus: PopoverFocus
    var dismiss: () -> Void = {}
    /// The panel's single cancellation action (Escape): cancels a naming edit,
    /// otherwise dismisses. Omitted, cancellation dismisses.
    var cancel: (() -> Void)?
    var sizeChanged: (NSSize) -> Void = { _ in }
    var body: some View {
        PanelView(monitor: controller, catalog: catalog, detail: detail, openSettings: showSettings, cancelAction: cancel).fixedSize(horizontal: false, vertical: true)
            .onGeometryChange(for: NSSize.self, of: { $0.size }, action: sizeChanged)
    }
    func showSettings() { dismiss(); settings.show() }
    func makeHostingController() -> StatusHostingController {
        let hosting = StatusHostingController(rootView: self)
        hosting.cancel = cancel ?? dismiss
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
    var cancel: () -> Void = {}
    var measuredSizeChanged: (NSSize) -> Void = { _ in }
    /// Calls the panel's cancellation action directly; never forwards the
    /// command to the panel, which would run the action twice.
    override func cancelOperation(_ sender: Any?) { cancel() }
}
@MainActor protocol PopoverPresenting: AnyObject {
    func showPopover()
    func showSettings()
    /// Saves a pending device-name edit, as closing the panel does.
    func settlePendingEdits()
}
extension PopoverPresenting {
    func showSettings() {}
    func settlePendingEdits() {}
}

/// On macOS 27 MenuBarAgent hosts the status item, so the expanded-interface
/// session is the reliable record of a press that opens the panel: begin shows
/// the panel, end hides it, and every owned dismissal hides the panel
/// synchronously and then cancels the session it was showing. A press on the
/// icon of an open panel reaches neither this app nor the session, so a global
/// mouse monitor recognizes that one closing press.
@MainActor final class StatusItemController: NSObject, @MainActor NSStatusItemExpandedInterfaceDelegate, NSWindowDelegate, PopoverPresenting {
    private let controller: MonitorController
    let catalog: DeviceCatalogStore
    /// Expansion and naming state, retained across snapshots and panel closing.
    let detail = PortDetailState()
    private let item: NSStatusItem
    private let panel: StatusPanel
    /// The SwiftUI content, whose only editable control is the naming field.
    private weak var hostedContent: NSView?
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
    init(controller: MonitorController, catalog: DeviceCatalogStore = DeviceCatalogStore(),
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
         activate: @escaping () -> Void = { NSApp.activate() }) {
        self.controller = controller
        self.catalog = catalog
        let item = suppliedItem ?? NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        self.item = item
        panel = suppliedPanel ?? StatusPanel()
        settings = suppliedSettings ?? SettingsWindowController(controller: controller)
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
        let hosting = StatusContent(controller: controller, catalog: catalog, detail: detail, settings: settings, focus: focus,
                                    dismiss: { [weak self] in self?.dismiss() }, cancel: { [weak self] in self?.cancel() }).makeHostingController()
        hostedContent = hosting.view
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
        item.button?.postsFrameChangedNotifications = true
        NotificationCenter.default.addObserver(self, selector: #selector(buttonFrameChanged), name: NSView.frameDidChangeNotification, object: item.button)
        item.expandedInterfaceDelegate = self
        panel.delegate = self
        panel.cancel = { [weak self] in self?.cancel() }
        notifications.addObserver(self, selector: #selector(applicationResignedActive), name: NSApplication.didResignActiveNotification, object: NSApp)
        workspaceNotifications.addObserver(self, selector: #selector(workspaceActivatedApplication), name: NSWorkspace.didActivateApplicationNotification, object: nil)
        globalMouseMonitor = monitorGlobalMouse { [weak self] type, location, time in
            if type == .leftMouseDown { self?.globalMouseDown(at: location, time: time) } else { self?.globalMouseUp(at: location) }
        }
        statusObservation = StatusObservation(controller: controller) { [weak self] presentation in
            guard let self else { return }
            if let button = self.item.button { presentation.apply(to: button) }
            if self.panel.isVisible { self.positionPanel() }
        }
    }
    deinit {
        notifications.removeObserver(self)
        NotificationCenter.default.removeObserver(self)
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
    func showSettings() { dismiss(); settings.show() }
    /// Quitting saves a pending name through the same path as closing; a failed
    /// save never blocks termination.
    func settlePendingEdits() { detail.settle(NamingContext(monitor: controller, store: catalog)) }
    func showPopover() {
        guard !panel.isVisible else { return }
        activate()
        presentPanel()
    }
    /// Escape, from every route: StatusPanel.performKeyEquivalent and
    /// cancelOperation, StatusHostingController.cancelOperation and the naming
    /// field's onExitCommand. While naming it cancels the edit, marked before
    /// focus leaves the field so the focus-loss save cannot commit it; it then
    /// clears the field's focus so a later Escape dismisses the panel.
    func cancel() {
        if detail.cancelEditing(fieldFocused: namingFieldFocused, context: NamingContext(monitor: controller, store: catalog)) {
            _ = panel.makeFirstResponder(nil)
        }
        else { dismiss() }
    }
    /// A field editor is editing a control of the hosted panel content; other
    /// responders, such as an added search field, keep normal dismissal.
    private var namingFieldFocused: Bool {
        guard let editor = panel.firstResponder as? NSText, let field = editor.delegate as? NSView, let hostedContent else { return false }
        return field.isDescendant(of: hostedContent)
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
        controller.panelOpened(); catalog.panelOpened()
        panel.makeKeyAndOrderFront(nil)
        // Open without editing: AppKit can focus the naming field when the
        // window becomes key, and a field left focused at closing stays so.
        if namingFieldFocused { _ = panel.makeFirstResponder(nil) }
    }
    private func hidePanel() {
        guard panel.isVisible else { return }
        detail.settle(NamingContext(monitor: controller, store: catalog))
        panel.orderOut(nil)
        controller.panelClosed(); catalog.panelClosed()
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
    @objc private func buttonFrameChanged(_ notification: Notification) {
        if panel.isVisible { positionPanel() }
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
