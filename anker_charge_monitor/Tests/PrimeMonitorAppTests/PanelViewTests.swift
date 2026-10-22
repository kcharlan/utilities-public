import SwiftUI
import Observation
import Testing
import PrimeMonitorCore
@testable import PrimeMonitor

let panelReadings = PortID.allCases.map {
    PortReading(port: $0, active: $0 == .c4, voltageMilli: $0 == .c4 ? 20000 : 0,
                currentMilli: $0 == .c4 ? 1490 : ($0.rawValue.hasPrefix("c") ? 20 : 0), powerCenti: $0 == .c4 ? 4321 : 0)
}
@MainActor private func panelReply(_ rig: ControllerRig) async {
    rig.backend.output.yield(.snapshot(.init(receivedAt: rig.clock.date, readings: panelReadings.reversed())))
    await settle()
}
@Suite @MainActor struct PanelViewTests {
    @Test func rowsFollowPortOrderAndInactiveRowsAreDimmed() async throws {
        let rig = try ControllerRig(); await rig.start(); await panelReply(rig)
        let view = PanelView(monitor: rig.controller, openSettings: {})
        #expect(view.rows.map(\.port) == PortID.allCases)
        #expect(PortRowView(reading: view.rows[0]).dimmed)
        #expect(!PortRowView(reading: view.rows[3]).dimmed)
        #expect(PortRowView(reading: view.rows[0]).current == "0.020 A")
        await rig.finish()
    }
    @Test func headerShowsTotalAndAge() async throws {
        let rig = try ControllerRig(); await rig.start(); await panelReply(rig)
        let view = PanelView(monitor: rig.controller, openSettings: {})
        #expect(view.alias == "Desk" && view.total == "43.21 W")
        #expect(view.updated(at: rig.clock.date.addingTimeInterval(8)) == "Updated 8 s ago")
        // Same total in both places; the menu bar only narrows the unit separator to a thin space.
        #expect(view.total == StatusPresentation.make(status: .connected, snapshot: rig.controller.snapshot, isStale: false, now: rig.clock.date).title.replacingOccurrences(of: "\u{2009}", with: " "))
        await rig.finish()
    }
    @Test func staleShowsWarningAndKeepsValues() async throws {
        let rig = try ControllerRig(); await rig.start(); await panelReply(rig)
        await rig.clock.advance(131)
        let view = PanelView(monitor: rig.controller, openSettings: {})
        #expect(view.warning == "Readings are stale. Showing last received values.")
        #expect(view.dimmed && view.rows == panelReadings && view.total == "43.21 W")
        await rig.events.send(.network(false))
        #expect(view.warning?.contains("Network unavailable") == true && view.rows == panelReadings)
        await rig.finish()
    }
    @Test func signedOutAndNoChargerShowEmptyStates() async throws {
        let rig = try ControllerRig(configured: false); await rig.start()
        let view = PanelView(monitor: rig.controller, openSettings: {})
        #expect(view.emptyMessage == "Sign in to your Anker account")
        await rig.controller.signIn(appCredentials)
        #expect(view.emptyMessage == "Choose a charger")
        await rig.finish()
    }
    @Test func sessionEndedShowsSignInAgain() async throws {
        let rig = try ControllerRig(); await rig.start(); await panelReply(rig)
        rig.backend.output.yield(.status(.sessionEnded)); await settle()
        let view = PanelView(monitor: rig.controller, openSettings: {})
        #expect(view.recoveryTitle == "Sign In Again" && view.warning?.contains("Session ended") == true)
        #expect(view.rows == panelReadings && view.dimmed)
        await view.recover(); #expect(await rig.backend.log.contains("login"))
        await rig.finish()
    }
    @Test func rowAccessibilityReadsLabelPowerVoltageCurrent() {
        let row = PortRowView(reading: panelReadings[3])
        #expect(row.accessibilityText == "C4, 43.21 W, 20.000 V, 1.490 A")
    }
    @Test func panelCarriesInjectedCatalogAndOmittedCatalogIsMemoryOnly() async throws {
        let rig = try ControllerRig(), catalog = try CatalogRig()
        catalog.store.load()
        let view = PanelView(monitor: rig.controller, catalog: catalog.store, openSettings: {})
        #expect(view.catalog === catalog.store && view.catalog.catalog.brands == [7: "Synthetic Seed Brand"])
        #expect(PanelView(monitor: rig.controller, openSettings: {}).catalog.fileURL == nil)
        await rig.finish()
    }
    @Test func animationsRespectReduceMotion() {
        var changes = 0, animated = 0
        PanelMotion.perform(reduceMotion: true, animate: { _ in animated += 1 }) { changes += 1 }
        #expect(changes == 1 && animated == 0)
        PanelMotion.perform(reduceMotion: false, animate: { change in animated += 1; change() }) { changes += 1 }
        #expect(changes == 2 && animated == 1)
    }
    @Test func refreshUsesExistingBoundedSpinner() async throws {
        let rig = try ControllerRig(); await rig.start(); await panelReply(rig)
        let view = PanelView(monitor: rig.controller, openSettings: {})
        let before = await rig.backend.log.filter { $0 == "request" }.count
        view.refresh(); await settle()
        #expect(rig.controller.refreshing)
        #expect(await rig.backend.log.filter { $0 == "request" }.count == before + 1)
        await rig.clock.advance(10); #expect(!rig.controller.refreshing)
        await rig.finish()
    }
    @Test(arguments: ["stale", "network", "error", "session-ended"])
    func retainedAgeObservesExistingTickAfterReadingsAndStatusSettle(_ state: String) async throws {
        let rig = try ControllerRig(); await rig.start(); await panelReply(rig)
        switch state {
        case "network": await rig.events.send(.network(false))
        case "error": rig.backend.output.yield(.status(.error("Synthetic connection failure"))); await settle()
        case "session-ended": rig.backend.output.yield(.status(.sessionEnded)); await settle()
        default: break
        }
        await rig.clock.advance(131)
        let snapshot = rig.controller.snapshot, status = rig.controller.status
        #expect(rig.controller.isStale)
        let view = PanelView(monitor: rig.controller, openSettings: {})
        #expect(view.ageText == "Updated 2 min ago")
        let requests = await rig.backend.log.filter { $0 == "request" }.count
        await confirmation("The maintained panel observes advancing retained-reading age", expectedCount: 1) { changed in
            withObservationTracking {
                _ = view.body
            } onChange: { changed() }
            await rig.clock.advance(60)
        }
        #expect(rig.controller.snapshot == snapshot && rig.controller.status == status && rig.controller.isStale)
        #expect(view.ageText == "Updated 3 min ago")
        // Only the already scheduled normal closed-panel request is allowed.
        #expect(await rig.backend.log.filter { $0 == "request" }.count == requests + (state == "stale" ? 1 : 0))
        await rig.finish()
    }
}
