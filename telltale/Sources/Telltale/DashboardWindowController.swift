// Port: brew_version/Sources/BrewVersion/SettingsWindowController.swift, SettingsWindowController, 41ed183.
// Adaptation: owns the dashboard window (spec section 3: resizable, about 1100 × 760) instead of
// Settings; conforms to the panel's DashboardOpening, with Settings as one of the dashboard's
// sections; switches the activation policy so the Dock icon shows only while the window is open;
// applies the stored dashboard appearance (spec section 9.4) unless a harness sets one, and a choice
// made in Settings at once; refreshes the login item when the window becomes key; no custom-interval
// focus.
import AppKit
import SwiftUI
import TelltaleCore

/// What the dashboard shows: a model's view, the collector view or Settings (spec section 9.2's sidebar).
enum DashboardSection: Hashable {
    case model(ProviderID, String)
    case collector
    case settings
}

/// The app's activation policy, injected so tests never change the test process's.
@MainActor protocol ActivationPolicyApplying: AnyObject {
    @discardableResult func setActivationPolicy(_ policy: NSApplication.ActivationPolicy) -> Bool
}

extension NSApplication: ActivationPolicyApplying {}

/// Owns and reuses one dashboard window (docs/lessons_learned.md, 2026-10-17: "Own a menu bar app's
/// Settings window explicitly" and "Reused AppKit windows keep their original Space"): every open
/// activates the app and brings that same window forward on the current Space.
@MainActor final class DashboardWindowController: NSObject, NSWindowDelegate, DashboardOpening {
    static let defaultSize = NSSize(width: 1100, height: 760)
    static let minimumSize = NSSize(width: 860, height: 600)

    let model: DashboardModel
    private let activation: any ActivationPolicyApplying
    private let activate: () -> Void
    private let present: (NSWindow) -> Void
    private var ownedWindow: NSWindow?
    /// A harness's explicit appearance; nil applies the stored setting at each open.
    private var appearance: NSAppearance?

    init(model: DashboardModel, activation: any ActivationPolicyApplying = NSApplication.shared,
         activate: @escaping () -> Void = { NSApp.activate() },
         present: @escaping (NSWindow) -> Void = { $0.makeKeyAndOrderFront(nil) }) {
        self.model = model; self.activation = activation
        self.activate = activate; self.present = present
        super.init()
        model.settings.appearanceChanged = { [weak self] in self?.applySettingsAppearance($0) }
    }

    func show(section: DashboardSection) {
        model.isVisible = true
        model.select(section)
        if ownedWindow == nil {
            let hosting = NSHostingController(rootView: DashboardView(model: model))
            // The window owns its viewport (lessons_learned: "Give an AppKit-owned grouped Form a
            // real content area"); hosting must not shrink it to the content's ideal size.
            hosting.sizingOptions = []
            let window = NSWindow(contentViewController: hosting)
            window.title = TelltaleRelease.displayName
            window.styleMask = [.titled, .closable, .miniaturizable, .resizable]
            window.isReleasedWhenClosed = false
            // The window is reused, so it keeps the Space it was first shown on.
            // Bring it to the current Space instead of switching the user there.
            window.collectionBehavior.insert(.moveToActiveSpace)
            window.setContentSize(Self.defaultSize)
            window.contentMinSize = Self.minimumSize
            window.delegate = self
            window.center()
            ownedWindow = window
        }
        ownedWindow?.appearance = appearance ?? Theme.dashboardAppearance(model.appearanceSetting())
        // Spec section 3: a Dock icon only while the dashboard is open.
        activation.setActivationPolicy(.regular)
        activate()
        if let ownedWindow { present(ownedWindow) }
    }

    func openDashboard() { show(section: model.selection ?? model.defaultSection()) }
    func openSettings() { show(section: .settings) }

    func setAppearance(_ appearance: NSAppearance?) {
        self.appearance = appearance
        ownedWindow?.appearance = appearance
    }

    /// A choice made in Settings applies at once and replaces a harness's explicit appearance.
    private func applySettingsAppearance(_ setting: Appearance) {
        appearance = nil
        ownedWindow?.appearance = Theme.dashboardAppearance(setting)
    }

    /// Login-item approval can change in System Settings while the app stays open
    /// (lessons_learned, 2026-10-17: "Refresh login approval when Settings becomes key").
    func windowDidBecomeKey(_ notification: Notification) { model.settings.login.refresh() }

    func windowWillClose(_ notification: Notification) {
        model.isVisible = false
        activation.setActivationPolicy(.accessory)
    }
}
