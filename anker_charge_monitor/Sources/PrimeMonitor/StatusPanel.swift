// Port: BrewVersion/Sources/BrewVersion/StatusPanel.swift, StatusPanel, 579ebb7.
// Adaptation: MonitorController and interim checkpoint content replace BV watches/notifications; no custom interval.
import AppKit

struct StatusScreen {
    let frame: NSRect
    let visibleFrame: NSRect
    /// The strip the menu bar occupies at the top of the screen. An auto-hidden
    /// menu bar reserves none of the visible frame, so assume at least the
    /// classic 24-point bar.
    var menuBar: NSRect {
        let height = max(frame.maxY - visibleFrame.maxY, 24)
        return NSRect(x: frame.minX, y: frame.maxY - height, width: frame.width, height: height)
    }
}
enum StatusPanelFrame {
    /// MenuBarAgent hosts the status item. The button's own window is centered
    /// on the menu bar but can be taller than it, such as (1599, 1277.5, 22, 64)
    /// on a 39-point bar. Until the item is placed, or while a menu bar manager
    /// hides it, the window reports placeholder geometry such as (0, -39, 34, 39).
    /// Known placeholders can overlap a lower display's menu bar. The public
    /// visibility flag includes obscured items and supplies no placement proof.
    /// Prefer fallback for these exact recorded rects, even if a real icon has
    /// identical geometry; other anchors still qualify by their center.
    static func placedAnchor(_ anchor: NSRect?, screens: [StatusScreen]) -> (rect: NSRect, screen: StatusScreen)? {
        guard let anchor, anchor.width > 0, anchor.height > 0 else { return nil }
        let placeholders = [
            NSRect(x: 0, y: -39, width: 34, height: 39),
            NSRect(x: 0, y: -30.5, width: 67, height: 22),
            NSRect(x: 6, y: -32, width: 22, height: 64),
            NSRect(x: 6, y: -51.5, width: 22, height: 64)
        ]
        guard !placeholders.contains(anchor) else { return nil }
        let center = NSPoint(x: anchor.midX, y: anchor.midY)
        guard let screen = screens.first(where: { $0.menuBar.contains(center) }) else { return nil }
        return (anchor, screen)
    }
    /// Places the panel under a placed icon, otherwise at the top right of the
    /// first screen, which carries the menu bar.
    static func make(contentSize: NSSize, anchor: NSRect?, screens: [StatusScreen]) -> NSRect? {
        let placed = placedAnchor(anchor, screens: screens)
        guard let screen = placed?.screen ?? screens.first else { return nil }
        let visible = screen.visibleFrame
        let size = NSSize(width: min(max(0, contentSize.width), visible.width), height: min(max(0, contentSize.height), visible.height))
        let x = placed.map { $0.rect.midX - size.width / 2 } ?? (visible.maxX - size.width)
        let top = min(screen.menuBar.minY, visible.maxY)
        return NSRect(x: min(max(x, visible.minX), visible.maxX - size.width), y: min(max(top - size.height, visible.minY), visible.maxY - size.height), width: size.width, height: size.height)
    }
    /// Whether a screen point is on the icon's column of the menu bar.
    static func iconContains(_ point: NSPoint, anchor: NSRect?, screens: [StatusScreen]) -> Bool {
        guard let placed = placedAnchor(anchor, screens: screens) else { return false }
        let bar = placed.screen.menuBar
        let slot = NSRect(x: placed.rect.minX, y: bar.minY, width: placed.rect.width, height: bar.height)
        return slot.insetBy(dx: -1, dy: -1).contains(point)
    }
}
@MainActor class StatusPanel: NSPanel {
    var dismiss: () -> Void = {}
    init() {
        super.init(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isReleasedWhenClosed = false
        hidesOnDeactivate = false
        animationBehavior = .none
        level = .popUpMenu
        // The panel is reused: show it on the current desktop, including a
        // full-screen app's Space, instead of the Space it first appeared on.
        collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary]
        hasShadow = true
        isOpaque = false
        backgroundColor = .clear
    }
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) { dismiss() }
    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        if event.charactersIgnoringModifiers == "\u{1b}" {
            cancelOperation(nil)
            return true
        }
        return super.performKeyEquivalent(with: event)
    }
}
// Follow SwiftUI measurements without making the hosting view the window's
// intrinsic minimum-size contract.
@MainActor final class StatusPanelContentController: NSViewController {
    var sizeChanged: () -> Void = {}
    private(set) var desiredContentSize: NSSize = .zero
    init(hosting: StatusHostingController) {
        super.init(nibName: nil, bundle: nil)
        addChild(hosting)
        desiredContentSize = hosting.view.fittingSize
        hosting.view.frame.size = desiredContentSize
        // Keep the hosting view out of the window's root sizing contract.
        // A small display can scroll the whole content instead of losing its
        // footer; the normal bounded list retains its existing inner scroll.
        let scroll = NSScrollView(frame: NSRect(origin: .zero, size: desiredContentSize))
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = true
        scroll.autohidesScrollers = true
        scroll.documentView = hosting.view
        let material = NSVisualEffectView(frame: scroll.frame)
        material.material = .popover
        material.blendingMode = .behindWindow
        material.state = .active
        material.wantsLayer = true
        material.layer?.cornerRadius = 12
        material.layer?.masksToBounds = true
        scroll.translatesAutoresizingMaskIntoConstraints = false
        material.addSubview(scroll)
        NSLayoutConstraint.activate([
            scroll.leadingAnchor.constraint(equalTo: material.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: material.trailingAnchor),
            scroll.topAnchor.constraint(equalTo: material.topAnchor),
            scroll.bottomAnchor.constraint(equalTo: material.bottomAnchor)
        ])
        view = material
        hosting.measuredSizeChanged = { [weak self, weak hosting] size in
            guard let self, let hosting else { return }
            desiredContentSize = size
            hosting.view.frame.size = size
            sizeChanged()
        }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}
