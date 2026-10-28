// Port: anker_charge_monitor/Tests/PrimeMonitorAppTests/SettingsWindowTests.swift,
// settingsWindowOpensOnActiveSpace and settingsReuseRefreshAndLoginApprovalAction, 4f965e8 (itself
// BV NativeActionsTests at 579ebb7).
// Adaptation: the dashboard window replaces Settings (spec section 3's window contract: about
// 1100 × 760, resizable, a Dock icon only while it is open); no login item.
import AppKit
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

@MainActor @Suite struct DashboardWindowTests {
    @Test func showSetsRegularPolicyAndCloseRestoresAccessory() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths)
            let activation = ActivationRecorder()
            var windows: [NSWindow] = []
            let dashboard = world.controller(activation: activation, presented: { windows.append($0) })
            dashboard.show(section: .collector)
            #expect(activation.policies == [.regular])
            #expect(windows.count == 1)
            let window = try #require(windows.first)
            #expect(window.delegate === dashboard)

            dashboard.windowWillClose(Notification(name: NSWindow.willCloseNotification, object: window))
            #expect(activation.policies == [.regular, .accessory])

            // Reopening shows the Dock icon again.
            dashboard.openSettings()
            #expect(activation.policies == [.regular, .accessory, .regular])
            #expect(world.model.selection == .settings)
        }
    }

    @Test func windowIsReusedAndMovesToActiveSpace() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths)
            world.live.reload()
            let activation = ActivationRecorder()
            var windows: [NSWindow] = []
            var activations = 0
            let dashboard = world.controller(activation: activation, presented: { windows.append($0) }, activations: { activations += 1 })
            dashboard.setAppearance(NSAppearance(named: .darkAqua))
            dashboard.openDashboard()
            // Open dashboard lands on the first model when nothing was chosen yet.
            #expect(world.model.selection == .model(.codex, Synth.model))
            dashboard.show(section: .collector)
            #expect(windows.count == 2 && windows[0] === windows[1])
            #expect(activations == 2)
            #expect(world.model.selection == .collector)
            let window = windows[0]
            #expect(window.collectionBehavior.contains(.moveToActiveSpace))
            #expect(!window.collectionBehavior.contains(.canJoinAllSpaces))
            #expect(!window.isReleasedWhenClosed)
            #expect(window.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua)
            dashboard.setAppearance(NSAppearance(named: .aqua))
            #expect(window.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .aqua)
            // Open dashboard returns to the last section shown.
            dashboard.openDashboard()
            #expect(world.model.selection == .collector)
        }
    }

    @Test func defaultSizeFromSpec() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            let activation = ActivationRecorder()
            var windows: [NSWindow] = []
            let dashboard = world.controller(activation: activation, presented: { windows.append($0) })
            dashboard.openDashboard()
            let window = try #require(windows.first)
            #expect(window.contentLayoutRect.size == NSSize(width: 1100, height: 760))
            #expect(window.contentMinSize.width >= 800 && window.contentMinSize.height >= 560)
            #expect(window.styleMask.isSuperset(of: [.titled, .closable, .miniaturizable, .resizable]))
            #expect(window.title == "Telltale")
            // The window owns its viewport: laying out the content doesn't shrink it.
            window.contentView?.layoutSubtreeIfNeeded()
            #expect(window.contentLayoutRect.size == NSSize(width: 1100, height: 760))
            // With no model yet (before the first run) it opens on the collector.
            #expect(world.model.selection == .collector)
        }
    }

    /// Spec section 9.4: Dark by default, Light, or Match system (nil follows the system).
    @Test func dashboardAppearanceFollowsTheSetting() {
        #expect(Theme.dashboardAppearance(.dark)?.name == .darkAqua)
        #expect(Theme.dashboardAppearance(.light)?.name == .aqua)
        #expect(Theme.dashboardAppearance(.system) == nil)
    }
}
