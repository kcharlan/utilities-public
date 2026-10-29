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
    @Test func dashboardSidebarFitsWithVersion() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths)
            world.live.reload()
            var windows: [NSWindow] = []
            let dashboard = world.controller(activation: ActivationRecorder(), presented: { windows.append($0) })
            dashboard.openDashboard()
            let window = try #require(windows.first)
            window.contentView?.layoutSubtreeIfNeeded()
            #expect(window.contentLayoutRect.size == NSSize(width: 1100, height: 760))
            #expect(window.contentMinSize.width >= 800 && window.contentMinSize.height >= 560)
            #expect(world.model.sidebar.first?.state == .models([DashboardModel.SidebarModel(provider: .codex, model: Synth.model, name: "Example")]))
        }
    }
    @Test func openProviderSelectsItsFirstModel() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths)
            world.live.reload()
            let dashboard = world.controller(activation: ActivationRecorder(), presented: { _ in })
            dashboard.openProvider(.codex, model: Synth.model)
            #expect(world.model.selection == .model(.codex, Synth.model))
        }
    }
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

    /// The closed window's views stay in memory; a database change then rereads nothing until the
    /// window opens again.
    @Test func closedDashboardSkipsReloads() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths, alerting: true)
            world.live.reload()
            let dashboard = world.controller(activation: ActivationRecorder(), presented: { _ in })
            dashboard.show(section: .model(.codex, Synth.model))
            #expect(world.model.isVisible)
            let shown = world.model.feed.count
            dashboard.windowWillClose(Notification(name: NSWindow.willCloseNotification, object: nil))
            #expect(!world.model.isVisible)

            try PanelWorld.addAlert(Store.open(world.paths.database, mode: .readWrite), body: "Synthetic second alert.")
            world.live.reload()
            world.model.liveChanged()
            #expect(world.model.feed.count == shown)

            dashboard.openDashboard()
            #expect(world.model.feed.count == shown + 1)
            world.live.reload()
            world.model.liveChanged()
            #expect(world.model.feed.count == shown + 1)
        }
    }

    /// Spec section 9.2: the sidebar lists the models with a response in the last 14 days.
    @Test func sidebarHidesModelsUnusedOutsideTheWindow() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths)
            try Self.addStaleModel(world)
            world.live.reload()
            // The stale model sorts before the recent one, so it would be the default section if listed.
            #expect(world.model.defaultSection() == .model(.codex, Synth.model))
            let group = try #require(world.model.sidebar.first)
            #expect(group.state == .models([DashboardModel.SidebarModel(provider: .codex, model: Synth.model, name: "Example")]))
        }
    }

    @Test func sidebarShowsIdleWhenNoModelIsRecent() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths)
            world.live.reload()
            world.clock.now = PanelWorld.now.addingTimeInterval(ModelDetail.sidebarWindow + 3_600)
            #expect(world.model.defaultSection() == .collector)
            let group = try #require(world.model.sidebar.first)
            #expect(group.provider == .codex)
            #expect(group.state == .idle)
        }
    }

    @Test func hiddenModelOpensUnderItsDisambiguatedName() throws {
        try withScratchDirectory { directory in
            let source = SourceSummary(
                provider: .codex, name: "Codex", statusName: "Example Status", statusSourceID: PanelWorld.statusSourceID, signals: [.speed],
                naming: DashboardCollisionNaming())
            let world = try DashboardWorld(directory, sources: [source])
            try PanelWorld.seed(world.paths)
            try Self.addStaleModel(world)
            world.live.reload()
            // Naming is over every stored model, so the hidden model's pair keeps the recent one's suffix.
            _ = world.model.defaultSection()
            let group = try #require(world.model.sidebar.first)
            guard case .models(let rows) = group.state else {
                Issue.record("expected the recent model's row, got \(group.state)")
                return
            }
            #expect(rows.map(\.model) == [Synth.model])
            #expect(rows.map(\.name) == ["Example (1.0)"])
            world.model.select(.model(.codex, Self.staleModel))
            #expect(world.model.selectedModel?.name == "Example (0.5)")
            #expect(world.model.loadError == nil)
            #expect(world.model.detail != nil)
        }
    }

    private static let staleModel = "example-model-0.5"

    /// A model that sorts before `Synth.model` and last responded 20 days before the seed's time.
    private static func addStaleModel(_ world: DashboardWorld) throws {
        var synth = Synth(firstNumber: 1_000)
        let end = PanelWorld.now.addingTimeInterval(-20 * 86_400)
        try Store.open(world.paths.database, mode: .readWrite).upsert(responses: synth.responses(2, model: staleModel, throughput: 40, from: end))
    }

    /// Spec section 9.4: Dark by default, Light, or Match system (nil follows the system).
    @Test func dashboardAppearanceFollowsTheSetting() {
        #expect(Theme.dashboardAppearance(.dark)?.name == .darkAqua)
        #expect(Theme.dashboardAppearance(.light)?.name == .aqua)
        #expect(Theme.dashboardAppearance(.system) == nil)
    }
}

/// Every model shares one display name, so the sidebar must tell them apart by version.
private struct DashboardCollisionNaming: ModelNaming {
    func displayName(model: String) -> String { "Example" }
    func incidentTitle(_ title: String, names model: String) -> Bool { false }
}
