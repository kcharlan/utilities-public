import AppKit
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

// MARK: Port detail presentation and naming

let syntheticLamp = DeviceKey(vendorID: 0x0a1b, productID: 0x2c3d)
let syntheticDock = DeviceKey(vendorID: 0xfeed, productID: 0xbeef)
/// Invented detail values: C1 an identified lamp (seed brand 7), C2 an unknown
/// class without model code, C3 unresolved, C4 nothing attached; C1 and the
/// USB-A ports report faults and the charger over-temperature.
func syntheticDetails(faultBits: UInt8? = 0x23, support: UInt8? = 6,
                      c1: PortIdentity = .identified(vendorID: 0x0a1b, productID: 0x2c3d, brandClass: 7, modelCode: 3)) -> ChargerDetails {
    ChargerDetails(faultBits: faultBits, identitySupport: support, identities: [
        .c1: c1, .c2: .identified(vendorID: 0xfeed, productID: 0xbeef, brandClass: 42, modelCode: nil),
        .c3: .identifying, .c4: .nothingAttached,
    ], rawFields: [:])
}
/// The owner-gate shape with invented values: support 2 does not stop a
/// resolved identity beside the no-device sentinel and an unresolved port.
func supportTwoMixedDetails() -> ChargerDetails {
    ChargerDetails(faultBits: 0, identitySupport: 2, identities: [
        .c1: .identified(vendorID: 0xfeed, productID: 0xbeef, brandClass: 10, modelCode: 7),
        .c2: .nothingAttached, .c3: .identifying, .c4: .nothingAttached,
    ], rawFields: [:])
}
@MainActor func detailReply(_ rig: ControllerRig, _ details: ChargerDetails?) async {
    rig.backend.output.yield(.snapshot(.init(receivedAt: rig.clock.date, readings: panelReadings, details: details)))
    await settle()
}
/// Lets AppKit and SwiftUI process hosted-view work. A nested run loop inside a
/// main-actor job blocks every other main-actor job, so run short slices and
/// yield between them; one long run starved wall-clock tests running in parallel.
@MainActor func pumpRunLoop() async {
    for _ in 0..<8 { runLoopSlice(); await Task.yield() }
}
@MainActor private func runLoopSlice() { RunLoop.current.run(until: Date().addingTimeInterval(0.005)) }
/// Hosted-field tests in different suites run in parallel, and beginning to
/// edit in one window ends editing in another; each holds this while it edits.
@MainActor final class HostedFieldLock {
    static let shared = HostedFieldLock()
    private var held = false
    private var waiters: [CheckedContinuation<Void, Never>] = []
    func acquire() async {
        if held { await withCheckedContinuation { waiters.append($0) } } else { held = true }
    }
    /// Hands the lock straight to the next waiter.
    func release() {
        if waiters.isEmpty { held = false } else { waiters.removeFirst().resume() }
    }
}
@MainActor func editableTextFields(in view: NSView) -> [NSTextField] {
    ((view as? NSTextField).map { $0.isEditable ? [$0] : [] } ?? []) + view.subviews.flatMap(editableTextFields)
}
/// Types into the focused field editor as a user would: replaces its text.
@MainActor func typeIntoFieldEditor(_ window: NSWindow, _ text: String) async throws {
    let editor = try #require(window.firstResponder as? NSTextView)
    editor.selectAll(nil)
    editor.insertText(text, replacementRange: editor.selectedRange())
    await pumpRunLoop()
}

@Suite @MainActor struct PortDetailPresentationTests {
    @Test func rowsShowFaultAndDeviceBeforeReadings() async throws {
        let rig = try ControllerRig(), catalog = try CatalogRig()
        try catalog.save(#"{"schema": 1, "brands": {"7": "Synthetic Brand"}, "vendors": {}, "devices": {"0A1B:2C3D": "Synthetic Desk Lamp"}}"#)
        catalog.store.load()
        await rig.start(); await detailReply(rig, syntheticDetails())
        let view = PanelView(monitor: rig.controller, catalog: catalog.store, openSettings: {})
        let rows = PortID.allCases.map(view.rowPresentation)
        #expect(rows.map(\.secondaryText) == ["Fault reported · Synthetic Desk Lamp", "FEED:BEEF", "Unidentified device", nil, "USB-A fault", "USB-A fault"])
        #expect(rows.map(\.faulted) == [true, false, false, false, true, true])
        let c1 = PortRowView(reading: view.rows[0], presentation: rows[0])
        #expect(c1.accessibilityText == "C1, Fault reported, Synthetic Desk Lamp, 0.00 W, 0.000 V, 0.020 A")
        #expect(PortRowView(reading: view.rows[3], presentation: rows[3]).accessibilityText == "C4, 43.21 W, 20.000 V, 1.490 A")
        #expect(PortRowView(reading: view.rows[4], presentation: rows[4]).accessibilityText == "A1, USB-A fault, 0.00 W, 0.000 V, 0.000 A")
        // Inactive dimming is unchanged by faults.
        #expect(c1.dimmed && c1.faulted && !PortRowView(reading: view.rows[3], presentation: rows[3]).dimmed)
        // Undecoded fault bits make no claim; a clear bit is no fault.
        await detailReply(rig, syntheticDetails(faultBits: nil))
        #expect(PortID.allCases.map { view.rowPresentation($0).fault } == Array(repeating: nil, count: 6))
        #expect(view.rowPresentation(.a1).secondaryText == nil)
        await detailReply(rig, nil)
        #expect(PortID.allCases.allSatisfy { view.rowPresentation($0).secondaryText == nil })
        await rig.finish()
    }
    @Test func numericColumnsFitWireExtremes() {
        // Readings are signed 16-bit wire integers; measure the actual reading font.
        let font = NSFont.monospacedDigitSystemFont(ofSize: PortRowView.readingFontSize, weight: .regular)
        func width(_ text: String, _ font: NSFont) -> CGFloat { ceil(NSAttributedString(string: text, attributes: [.font: font]).size().width) }
        for value in [Int(Int16.min), Int(Int16.max), 0, -1] {
            #expect(width(DisplayFormatter.watts(centi: value), font) <= PortRowView.powerWidth)
            #expect(width(DisplayFormatter.volts(milli: value), font) <= PortRowView.voltageWidth)
            #expect(width(DisplayFormatter.amps(milli: value), font) <= PortRowView.currentWidth)
        }
        #expect(width(DisplayFormatter.watts(centi: Int(Int16.min)), font) > PortRowView.powerWidth - 4)
        let label = NSFont.monospacedDigitSystemFont(ofSize: PortRowView.readingFontSize, weight: .semibold)
        #expect(PortID.allCases.allSatisfy { width($0.label, label) <= PortRowView.labelWidth })
        // The 400 pt panel's 368 pt content leaves the device text real room.
        let fixed = PortRowView.labelWidth + PortRowView.powerWidth + PortRowView.voltageWidth + PortRowView.currentWidth + PortRowView.disclosureWidth + 5 * PortRowView.spacing
        #expect(368 - fixed >= 100)
    }
    @Test func expandedIdentityStates() async throws {
        let rig = try ControllerRig(), catalog = try CatalogRig()
        catalog.store.load()
        await rig.start()
        let view = PanelView(monitor: rig.controller, catalog: catalog.store, openSettings: {})
        // No details at all: unavailable, never nothing attached.
        await detailReply(rig, nil)
        #expect(PortID.usbC.allSatisfy { view.expandedIdentity($0) == .unavailable })
        #expect(view.expandedIdentity(.c1).message == "Connected device: Not reported by this charger")
        #expect(view.expandedIdentity(.a1) == .usbA && view.expandedIdentity(.a2).message == "USB-A ports don't report connected devices.")
        await detailReply(rig, syntheticDetails())
        let c1 = NamingTarget(charger: appCharger.serial, port: .c1, key: syntheticLamp)
        #expect(view.expandedIdentity(.c1) == .identified(c1, lines: [
            DetailLine(label: "Brand", value: "Synthetic Seed Brand"), DetailLine(label: "USB IDs", value: "0A1B:2C3D"),
            DetailLine(label: "Device model code", value: "3")]))
        // A reported unknown class keeps its number; a missing model code is unavailable.
        #expect(view.expandedIdentity(.c2) == .identified(NamingTarget(charger: appCharger.serial, port: .c2, key: syntheticDock), lines: [
            DetailLine(label: "Brand", value: "Unknown class 42"), DetailLine(label: "USB IDs", value: "FEED:BEEF"),
            DetailLine(label: "Device model code", value: "Not reported by this charger")]))
        #expect(view.expandedIdentity(.c3) == .identifying && view.expandedIdentity(.c3).message == "This device hasn't reported its identity.")
        #expect(view.expandedIdentity(.c4) == .nothingConnected && view.expandedIdentity(.c4).message == "Nothing connected.")
        #expect(view.expandedIdentity(.a1) == .usbA)
        // Device-specific controls and metadata belong only to identified devices.
        for port in [PortID.c3, .c4, .a1] { #expect(view.naming.target(port) == nil) }
        #expect(view.naming.target(.c1) == c1)
        await detailReply(rig, syntheticDetails(c1: .identified(vendorID: 0x0a1b, productID: 0x2c3d, brandClass: nil, modelCode: nil)))
        guard case let .identified(_, lines) = view.expandedIdentity(.c1) else { Issue.record("not identified"); return }
        #expect(lines.map(\.text) == ["Brand Not reported by this charger", "USB IDs 0A1B:2C3D", "Device model code Not reported by this charger"])
        // Identity missing for one port only.
        await detailReply(rig, ChargerDetails(faultBits: 0, identitySupport: nil, identities: [.c2: .nothingAttached], rawFields: [:]))
        #expect(view.expandedIdentity(.c1) == .unavailable && view.expandedIdentity(.c2) == .nothingConnected)
        await rig.finish()
    }
    @Test func identitySupportTwoStillShowsDecodedIdentities() async throws {
        let rig = try ControllerRig(), catalog = try CatalogRig()
        try catalog.save(#"{"schema": 1, "brands": {"10": "Synthetic Brand Ten"}, "vendors": {}, "devices": {}}"#)
        catalog.store.load()
        await rig.start(); await detailReply(rig, supportTwoMixedDetails())
        let view = PanelView(monitor: rig.controller, catalog: catalog.store, openSettings: {})
        #expect(view.rowPresentation(.c1).device == "Synthetic Brand Ten")
        guard case let .identified(target, lines) = view.expandedIdentity(.c1) else { Issue.record("not identified"); return }
        #expect(target.key == syntheticDock)
        #expect(lines.map(\.text) == ["Brand Synthetic Brand Ten", "USB IDs FEED:BEEF", "Device model code 7"])
        #expect([view.expandedIdentity(.c2), view.expandedIdentity(.c3), view.expandedIdentity(.c4)] == [.nothingConnected, .identifying, .nothingConnected])
        #expect(view.rowPresentation(.c3).device == "Unidentified device")
        let messages = PortID.allCases.compactMap { view.expandedIdentity($0).message }
        #expect(!messages.contains { $0.contains("can't identify") })
        await rig.finish()
    }
    @Test func expandedFaultWording() async throws {
        let rig = try ControllerRig(); await rig.start()
        let view = PanelView(monitor: rig.controller, openSettings: {})
        await detailReply(rig, syntheticDetails(faultBits: 0x23))
        #expect(view.faultLines(.c1).map(\.text) == ["Fault Fault reported", "Fault bits 0x23"])
        #expect(view.faultLines(.c2).map(\.text) == ["Fault None", "Fault bits 0x23"])
        #expect(view.faultLines(.a2).map(\.text) == ["USB-A fault Fault reported", "Fault bits 0x23"])
        await detailReply(rig, syntheticDetails(faultBits: 0x04))
        #expect(view.faultLines(.a1).map(\.text) == ["USB-A fault None", "Fault bits 0x04"])
        await detailReply(rig, syntheticDetails(faultBits: nil))
        #expect(view.faultLines(.c1).map(\.text) == ["Fault Not reported by this charger"])
        await rig.finish()
    }
    @Test func warningsReportTemperatureAndCatalogWithoutDimming() async throws {
        let rig = try ControllerRig(), catalog = try CatalogRig()
        catalog.store.load()
        await rig.start(); await detailReply(rig, syntheticDetails(faultBits: 0x01))
        let view = PanelView(monitor: rig.controller, catalog: catalog.store, openSettings: {})
        #expect(view.overTemperatureWarning == "Charger reports over-temperature.")
        try catalog.save(#"{"schema": 1, "brands": {}, "vendors": {}, "devices": {"0a1b:2c3d": ""}}"#)
        catalog.store.load()
        #expect(view.catalogWarning == "Device names file devices.json wasn't loaded: devices entry \"0a1b:2c3d\": the name is empty.")
        #expect(view.warning == nil && !view.dimmed)
        await detailReply(rig, syntheticDetails(faultBits: 0x3e))
        #expect(view.overTemperatureWarning == nil)
        await detailReply(rig, syntheticDetails(faultBits: nil))
        #expect(view.overTemperatureWarning == nil)
        await rig.finish()
    }
}

@Suite @MainActor struct PortNamingTests {
    /// A rig with a persistent private catalog and an identified lamp on C1.
    @MainActor final class Naming {
        let rig: ControllerRig, catalog: CatalogRig, detail = PortDetailState()
        init() async throws {
            rig = try ControllerRig(); catalog = try CatalogRig()
            catalog.store.load()
            await rig.start(); await detailReply(rig, syntheticDetails())
        }
        var context: NamingContext { NamingContext(monitor: rig.controller, store: catalog.store) }
        var lamp: NamingTarget { NamingTarget(charger: appCharger.serial, port: .c1, key: syntheticLamp) }
        func text() -> String { detail.text(for: lamp, in: catalog.store.catalog) }
        func type(_ text: String) { detail.beginEditing(); detail.edit(text, for: lamp, in: catalog.store.catalog) }
    }
    @Test func returnCommitsThroughTheStoreAndEchoesAreNotEdits() async throws {
        let n = try await Naming()
        #expect(n.detail.toggle(.c1, n.context) && n.detail.expanded == .c1)
        // The field echoing its displayed value is not a draft.
        n.detail.edit("", for: n.lamp, in: n.catalog.store.catalog)
        #expect(!n.detail.dirty)
        n.type("Synthetic Desk Lamp")
        #expect(n.detail.dirty && n.detail.editedKey == syntheticLamp && n.text() == "Synthetic Desk Lamp")
        #expect(n.detail.commit(n.context))
        #expect(!n.detail.dirty && n.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Desk Lamp"])
        #expect(try n.catalog.devices() == ["0A1B:2C3D": "Synthetic Desk Lamp"] && n.text() == "Synthetic Desk Lamp")
        // An unchanged name is not rewritten; a blank one removes the entry.
        n.type("Synthetic Desk Lamp"); #expect(!n.detail.dirty)
        let replaces = n.catalog.files.count("replace")
        n.type("  "); #expect(n.detail.commit(n.context))
        #expect(n.catalog.files.count("replace") == replaces + 1 && n.catalog.store.catalog.devices.isEmpty)
        await n.rig.finish()
    }
    @Test func escapeCancelsBeforeTheFocusLossSave() async throws {
        let n = try await Naming()
        n.detail.toggle(.c1, n.context)
        n.type("Synthetic Abandoned Name")
        #expect(n.detail.cancelEditing() && !n.detail.dirty && !n.detail.editing)
        // The field's end-of-editing value push and the focus-loss save follow.
        n.detail.edit("Synthetic Abandoned Name", for: n.lamp, in: n.catalog.store.catalog)
        n.detail.endEditing(n.context)
        #expect(!n.detail.dirty && n.catalog.files.count("replace") == 0 && n.text() == "")
        // Nothing left to cancel: a later Escape is the panel's.
        #expect(!n.detail.cancelEditing())
        // The cancellation mark does not outlive that focus transition.
        n.type("Synthetic Kept Name"); n.detail.endEditing(n.context)
        #expect(n.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Kept Name"])
        #expect(n.detail.expanded == .c1)
        await n.rig.finish()
    }
    @Test func failedSaveKeepsDraftAndErrorForRetry() async throws {
        let n = try await Naming()
        n.detail.toggle(.c1, n.context)
        n.catalog.files.failWrites = true
        n.type("Synthetic Retry Name")
        #expect(!n.detail.commit(n.context))
        let failure = try #require(n.detail.failure(for: n.lamp))
        #expect(failure.inlineText == "Name not saved: Couldn't save device names file devices.json. Press Return to retry.")
        #expect(n.catalog.store.problem == nil && n.text() == "Synthetic Retry Name")
        // Closing settles through the same path and keeps the failure.
        n.detail.endEditing(n.context); n.detail.settle(n.context)
        #expect(n.detail.failure(for: n.lamp) == failure && n.text() == "Synthetic Retry Name")
        n.catalog.files.failWrites = false
        #expect(n.detail.commit(n.context))
        #expect(n.detail.failure(for: n.lamp) == nil && n.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Retry Name"])
        await n.rig.finish()
    }
    @Test func invalidFileFailureIsReportedOnceAsTheCatalogProblem() async throws {
        let n = try await Naming()
        n.detail.toggle(.c1, n.context)
        try n.catalog.save(#"{"schema": 1, "brands": {}, "vendors": {}, "devices": {"0a1b:2c3d": ""}}"#)
        n.type("Synthetic Blocked Name")
        #expect(!n.detail.commit(n.context))
        let view = PanelView(monitor: n.rig.controller, catalog: n.catalog.store, detail: n.detail, openSettings: {})
        let problem = "Device names file devices.json wasn't loaded: devices entry \"0a1b:2c3d\": the name is empty."
        #expect(view.catalogWarning == problem)
        let failure = try #require(n.detail.failure(for: n.lamp))
        #expect(failure.sharedWithCatalog && !failure.inlineText.contains(problem))
        #expect(failure.inlineText == "Name not saved. Correct the device names file, then press Return to retry.")
        // Fixing the file clears the warning; the field still offers its retry.
        try n.catalog.save(#"{"schema": 1, "brands": {}, "vendors": {}, "devices": {}}"#)
        n.catalog.store.panelOpened()
        #expect(view.catalogWarning == nil && n.detail.failure(for: n.lamp) == failure)
        #expect(n.detail.commit(n.context) && n.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Blocked Name"])
        n.catalog.store.panelClosed()
        await n.rig.finish()
    }
    @Test func failedRowSwitchKeepsEditedRowUntilRetryOrCancel() async throws {
        let n = try await Naming()
        n.detail.toggle(.c1, n.context)
        n.catalog.files.failWrites = true
        n.type("Synthetic Switch Name")
        #expect(!n.detail.toggle(.c2, n.context))
        #expect(n.detail.expanded == .c1 && n.text() == "Synthetic Switch Name" && n.detail.failure(for: n.lamp) != nil)
        // Collapsing the edited row is also a switch.
        #expect(!n.detail.toggle(.c1, n.context) && n.detail.expanded == .c1)
        // The destination's state never replaces the pending draft.
        let dock = NamingTarget(charger: appCharger.serial, port: .c2, key: syntheticDock)
        #expect(n.detail.text(for: dock, in: n.catalog.store.catalog) == "" && n.detail.editedKey == syntheticLamp)
        n.catalog.files.failWrites = false
        #expect(n.detail.toggle(.c2, n.context) && n.detail.expanded == .c2)
        #expect(n.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Switch Name"] && !n.detail.dirty)
        // Cancellation path: a failed switch, then Escape, then the switch.
        n.detail.toggle(.c1, n.context)
        n.catalog.files.failWrites = true
        n.type("Synthetic Cancelled Name")
        #expect(!n.detail.toggle(.c3, n.context) && n.detail.expanded == .c1)
        #expect(n.detail.cancelEditing())
        n.detail.endEditing(n.context)
        #expect(n.detail.toggle(.c3, n.context) && n.detail.expanded == .c3)
        #expect(n.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Switch Name"])
        await n.rig.finish()
    }
    @Test func expansionSurvivesSnapshotsAndCatalogReloadKeepsDraft() async throws {
        let n = try await Naming()
        n.detail.toggle(.c1, n.context)
        n.type("Synthetic Draft Name")
        n.catalog.store.panelOpened()
        try n.catalog.save(#"{"schema": 1, "brands": {}, "vendors": {}, "devices": {"0A1B:2C3D": "Synthetic Editor Name"}}"#)
        await n.catalog.scheduler.advance(1)
        #expect(n.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Editor Name"])
        #expect(n.text() == "Synthetic Draft Name" && n.detail.dirty)
        await detailReply(n.rig, syntheticDetails(faultBits: 0))
        #expect(n.detail.expanded == .c1 && n.text() == "Synthetic Draft Name")
        // Without a draft the reloaded name shows.
        #expect(n.detail.cancelEditing()); n.detail.endEditing(n.context)
        #expect(n.text() == "Synthetic Editor Name")
        n.catalog.store.panelClosed()
        await n.rig.finish()
    }
    @Test func replacementDeviceOrChargerNeverReceivesTheDraft() async throws {
        let n = try await Naming()
        n.detail.toggle(.c1, n.context)
        n.type("Synthetic Lamp Draft")
        // Another device on the same port.
        await detailReply(n.rig, syntheticDetails(c1: .identified(vendorID: 0xfeed, productID: 0x0001, brandClass: nil, modelCode: nil)))
        let replacement = NamingTarget(charger: appCharger.serial, port: .c1, key: DeviceKey(vendorID: 0xfeed, productID: 0x0001))
        #expect(n.detail.text(for: replacement, in: n.catalog.store.catalog) == "" && n.detail.failure(for: replacement) == nil)
        #expect(n.detail.expanded == .c1)
        // The original device returning restores its own draft.
        await detailReply(n.rig, syntheticDetails())
        #expect(n.text() == "Synthetic Lamp Draft")
        // The same device behind another charger is a different target.
        let otherCharger = NamingContext(snapshot: n.rig.controller.snapshot, charger: "synthetic-other-charger", store: n.catalog.store)
        let elsewhere = try #require(otherCharger.target(.c1))
        #expect(elsewhere != n.lamp && n.detail.text(for: elsewhere, in: n.catalog.store.catalog) == "")
        #expect(n.detail.commit(otherCharger) && !n.detail.dirty && n.catalog.files.count("replace") == 0)
        // Settling while a replacement device is shown discards, never renames it.
        n.type("Synthetic Second Draft")
        await detailReply(n.rig, syntheticDetails(c1: .nothingAttached))
        n.detail.settle(n.context)
        #expect(!n.detail.dirty && n.catalog.files.count("replace") == 0 && n.catalog.store.catalog.devices.isEmpty)
        await n.rig.finish()
    }
    @Test func hostedFieldFocusLossSavesAndFailureKeepsTheFieldDraft() async throws {
        await HostedFieldLock.shared.acquire(); defer { HostedFieldLock.shared.release() }
        let n = try await Naming()
        let window = StatusPanel()
        defer { window.contentViewController = nil }
        window.setFrame(NSRect(x: -10000, y: -10000, width: 400, height: 600), display: false)
        window.contentViewController = NSHostingController(rootView: PanelView(monitor: n.rig.controller, catalog: n.catalog.store, detail: n.detail, openSettings: {}))
        #expect(editableTextFields(in: window.contentView!).isEmpty)
        n.detail.toggle(.c1, n.context)
        await pumpRunLoop()
        let field = try #require(editableTextFields(in: window.contentView!).first)
        #expect(field.placeholderString == "Name this device")
        #expect(window.makeFirstResponder(field)); await pumpRunLoop()
        #expect(n.detail.editing)
        try await typeIntoFieldEditor(window, "Synthetic Hosted Lamp")
        #expect(n.detail.draft?.text == "Synthetic Hosted Lamp" && n.catalog.files.count("replace") == 0)
        _ = window.makeFirstResponder(nil); await pumpRunLoop()
        #expect(!n.detail.editing && !n.detail.dirty)
        #expect(try n.catalog.devices() == ["0A1B:2C3D": "Synthetic Hosted Lamp"])
        // A failed focus-loss save leaves the draft and its error in the field.
        n.catalog.files.failWrites = true
        #expect(window.makeFirstResponder(field)); await pumpRunLoop()
        try await typeIntoFieldEditor(window, "Synthetic Unsaved Lamp")
        _ = window.makeFirstResponder(nil); await pumpRunLoop()
        #expect(n.detail.draft?.text == "Synthetic Unsaved Lamp" && n.detail.failure(for: n.lamp) != nil)
        #expect(field.stringValue == "Synthetic Unsaved Lamp" && n.catalog.store.catalog.devices == [syntheticLamp: "Synthetic Hosted Lamp"])
        await n.rig.finish()
    }
}
