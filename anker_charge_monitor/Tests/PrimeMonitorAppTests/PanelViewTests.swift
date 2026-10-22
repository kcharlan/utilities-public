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
    rig.backend.output.snapshot(.init(receivedAt: rig.clock.date, readings: panelReadings.reversed()))
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
                      c1: PortIdentity = .identified(vendorID: 0x0a1b, productID: 0x2c3d, brandClass: 7, modelCode: 3),
                      switches: [PortSwitch: Bool] = [:]) -> ChargerDetails {
    ChargerDetails(faultBits: faultBits, identitySupport: support, identities: [
        .c1: c1, .c2: .identified(vendorID: 0xfeed, productID: 0xbeef, brandClass: 42, modelCode: nil),
        .c3: .identifying, .c4: .nothingAttached,
    ], rawFields: [:], switches: switches)
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
    rig.backend.output.snapshot(.init(receivedAt: rig.clock.date, readings: panelReadings, details: details))
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
        // The row control exposes its expansion state.
        #expect(c1.accessibilityValue == "Collapsed")
        #expect(PortRowView(reading: view.rows[0], presentation: rows[0], expanded: true).accessibilityValue == "Expanded")
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
    @Test func rowsShowAnOffSwitchBetweenFaultAndDevice() async throws {
        let rig = try ControllerRig(), catalog = try CatalogRig()
        try catalog.save(#"{"schema": 1, "brands": {"7": "Synthetic Brand"}, "vendors": {}, "devices": {"0A1B:2C3D": "Synthetic Desk Lamp"}}"#)
        catalog.store.load()
        await rig.start()
        // C1 off with a fault and a named device; C2 on; C4 off without a device; USB-A off beside its fault.
        await detailReply(rig, syntheticDetails(switches: [.c1: false, .c2: true, .c4: false, .usbA: false]))
        let view = PanelView(monitor: rig.controller, catalog: catalog.store, openSettings: {})
        let rows = PortID.allCases.map(view.rowPresentation)
        #expect(rows.map(\.secondaryText) == ["Fault reported · Off · Synthetic Desk Lamp", "FEED:BEEF", "Unidentified device", "Off", "USB-A fault · Off", "USB-A fault · Off"])
        #expect(rows.map(\.switchOn) == [false, true, nil, false, false, false])
        // Off is not a fault: only the fault text turns a row red.
        #expect(rows.map(\.faulted) == [true, false, false, false, true, true])
        #expect(PortRowView(reading: view.rows[0], presentation: rows[0]).accessibilityText == "C1, Fault reported, Off, Synthetic Desk Lamp, 0.00 W, 0.000 V, 0.020 A")
        #expect(PortRowView(reading: view.rows[1], presentation: rows[1]).accessibilityText == "C2, FEED:BEEF, 0.00 W, 0.000 V, 0.020 A")
        #expect(PortRowView(reading: view.rows[3], presentation: rows[3]).accessibilityText == "C4, Off, 43.21 W, 20.000 V, 1.490 A")
        #expect(PortRowView(reading: view.rows[5], presentation: rows[5]).accessibilityText == "A2, USB-A fault, Off, 0.00 W, 0.000 V, 0.000 A")
        // Unknown and on make no off claim, even beside a decoded fault bit.
        await detailReply(rig, syntheticDetails(switches: [.c1: true]))
        #expect(view.rowPresentation(.c1).secondaryText == "Fault reported · Synthetic Desk Lamp")
        #expect(PortID.allCases.dropFirst().allSatisfy { view.rowPresentation($0).switchOn == nil })
        await detailReply(rig, nil)
        #expect(PortID.allCases.allSatisfy { view.rowPresentation($0).secondaryText == nil && view.rowPresentation($0).switchOn == nil })
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
        // Only a reported fault value is styled as an alert.
        #expect(view.faultLines(.c1).map(\.alert) == [true, false] && view.faultLines(.c2).map(\.alert) == [false, false])
        #expect(view.faultLines(.c2).map(\.text) == ["Fault None", "Fault bits 0x23"])
        #expect(view.faultLines(.a2).map(\.text) == ["USB-A fault Fault reported", "Fault bits 0x23"])
        await detailReply(rig, syntheticDetails(faultBits: 0x04))
        #expect(view.faultLines(.a1).map(\.text) == ["USB-A fault None", "Fault bits 0x04"])
        await detailReply(rig, syntheticDetails(faultBits: nil))
        #expect(view.faultLines(.c1).map(\.text) == ["Fault Not reported by this charger"])
        await rig.finish()
    }
    @Test func expandedDetailShowsThePortSwitchBesideTheFaultLines() async throws {
        let rig = try ControllerRig(); await rig.start()
        let view = PanelView(monitor: rig.controller, openSettings: {})
        await detailReply(rig, syntheticDetails(faultBits: 0x23, switches: [.c1: false, .c2: true, .usbA: false]))
        #expect(PortID.allCases.map { view.switchLine($0).text } == [
            "Port switch Off", "Port switch On", "Port switch Not reported by this charger",
            "Port switch Not reported by this charger", "Port switch Off", "Port switch Off",
        ])
        // A switch is state, not a fault alert.
        #expect(PortID.allCases.allSatisfy { !view.switchLine($0).alert })
        #expect(view.statusLines(.c1).map(\.text) == ["Fault Fault reported", "Fault bits 0x23", "Port switch Off"])
        #expect(view.statusLines(.a2).map(\.text) == ["USB-A fault Fault reported", "Fault bits 0x23", "Port switch Off"])
        // Without fault bits the switch line still shows beside the unavailable fault.
        await detailReply(rig, syntheticDetails(faultBits: nil, switches: [.c2: true]))
        #expect(view.statusLines(.c2).map(\.text) == ["Fault Not reported by this charger", "Port switch On"])
        await detailReply(rig, nil)
        #expect(view.statusLines(.c1).map(\.text) == ["Fault Not reported by this charger", "Port switch Not reported by this charger"])
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
    @Test func removedFieldEndsEditingAndEscapeIgnoresAnUnshownDraft() async throws {
        let n = try await Naming()
        n.detail.toggle(.c1, n.context)
        n.type("Synthetic Unplugged Draft")
        // The device goes away: the field is removed without a focus-loss report.
        await detailReply(n.rig, syntheticDetails(c1: .nothingAttached))
        n.detail.fieldRemoved()
        #expect(!n.detail.editing && n.detail.dirty && n.catalog.files.count("replace") == 0)
        // Nothing shown to cancel, so Escape belongs to the panel.
        #expect(!n.detail.cancelEditing(context: n.context) && n.detail.dirty)
        // A shown failed draft with an unfocused field is cancelled by Escape.
        await detailReply(n.rig, syntheticDetails())
        #expect(n.detail.cancelEditing(context: n.context) && !n.detail.dirty)
        #expect(!n.detail.cancelEditing(context: n.context))
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

// MARK: Port control presentation ("Switch state and actions", "Confirmation", "Wording")

/// A connected, fresh controller with invented details and a panel whose
/// confirmation window runs on the rig's manual clock.
@MainActor final class ControlPanel {
    let rig: ControllerRig, catalog: CatalogRig, detail = PortDetailState()
    let view: PanelView
    init(_ details: ChargerDetails? = syntheticDetails(faultBits: 0, switches: [.c1: true, .c2: true, .c3: true, .c4: true, .usbA: true])) async throws {
        rig = try ControllerRig(); catalog = try CatalogRig()
        try catalog.save(#"{"schema": 1, "brands": {"7": "Synthetic Brand"}, "vendors": {}, "devices": {"0A1B:2C3D": "Synthetic Desk Lamp"}}"#)
        catalog.store.load()
        detail.now = { [clock = rig.clock] in clock.date }
        view = PanelView(monitor: rig.controller, catalog: catalog.store, detail: detail, openSettings: {})
        await rig.start(); await detailReply(rig, details)
    }
    var naming: NamingContext { NamingContext(monitor: rig.controller, store: catalog.store) }
    func titles(_ port: PortID) -> [String] { view.controls(port).buttons.map(\.title) }
    func press(_ action: PortOperationKind, _ port: PortID) async { view.perform(action, on: port); await settle() }
}

@Suite @MainActor struct PortControlPresentationTests {
    @Test func actionsFollowTheReportedSwitch() async throws {
        let p = try await ControlPanel(syntheticDetails(faultBits: 0, switches: [.c1: true, .c2: false, .usbA: true]))
        // Reported on: restart and turn off; reported off: turn on; unknown: every action.
        #expect(p.titles(.c1) == ["Restart", "Turn off"])
        #expect(p.titles(.c2) == ["Turn on"])
        #expect(p.titles(.c3) == ["Restart", "Turn off", "Turn on"])
        // The USB-A pair has its own button forms on either row.
        #expect(p.titles(.a1) == ["Restart USB-A ports", "Turn off USB-A ports"])
        #expect(p.titles(.a2) == p.titles(.a1))
        await detailReply(p.rig, syntheticDetails(faultBits: 0, switches: [.usbA: false]))
        #expect(p.titles(.a2) == ["Turn on USB-A ports"])
        #expect(p.titles(.c1) == ["Restart", "Turn off", "Turn on"])
        await detailReply(p.rig, nil)
        #expect(PortID.allCases.allSatisfy { p.view.controls($0).buttons.count == 3 && p.view.controls($0).enabled })
        #expect(PortID.allCases.allSatisfy { p.view.controls($0).caption == nil && p.view.controls($0).status == nil })
        await p.rig.finish()
    }
    @Test func turnOffAndRestartArmThenActOnTheSecondClickAndTurnOnActsAtOnce() async throws {
        let p = try await ControlPanel()
        await p.press(.turnOff, .c2)
        #expect(await p.rig.commands().isEmpty)
        #expect(p.titles(.c2) == ["Restart", "Confirm turn off"])
        #expect(p.view.controls(.c2).buttons.map(\.armed) == [false, true])
        // Arming is the target's alone; other rows are unchanged.
        #expect(p.titles(.c1) == ["Restart", "Turn off"] && p.view.controls(.c1).caption == nil)
        await p.press(.turnOff, .c2)
        #expect(await p.rig.commands() == ["c2 off"] && p.detail.armed == nil)
        await p.rig.switchReply(.c2, false)
        // Restart, on the USB-A pair from either of its rows.
        await detailReply(p.rig, syntheticDetails(faultBits: 0, switches: [.c2: false, .usbA: true]))
        await p.press(.restart, .a1)
        #expect(p.titles(.a2) == ["Confirm restart", "Turn off USB-A ports"])
        await p.press(.restart, .a2)
        #expect(await p.rig.commands() == ["c2 off", "usbA off"])
        await p.rig.switchReply(.usbA, false); await p.rig.clock.advance(PortControlPolicy.restartPause)
        await p.rig.switchReply(.usbA, true)
        #expect(p.rig.controller.portOperation == nil)
        // Turn on needs no confirmation.
        await p.press(.turnOn, .c2)
        #expect(await p.rig.commands() == ["c2 off", "usbA off", "usbA on", "c2 on"] && p.detail.armed == nil)
        await p.rig.finish()
    }
    @Test func armingDisarmsOnExpiryAnotherActionAndARowChange() async throws {
        let p = try await ControlPanel()
        await p.press(.turnOff, .c1)
        await p.rig.clock.advance(PortControlPolicy.confirmationWindow - 1)
        #expect(p.titles(.c1) == ["Restart", "Confirm turn off"])
        await p.rig.clock.advance(1)
        // Expired: shown unarmed, and the next click arms again instead of acting.
        #expect(p.titles(.c1) == ["Restart", "Turn off"])
        await p.press(.turnOff, .c1)
        #expect(await p.rig.commands().isEmpty && p.titles(.c1) == ["Restart", "Confirm turn off"])
        // A click on any other action disarms; a first click of that action arms it.
        await p.press(.restart, .c1)
        #expect(p.titles(.c1) == ["Confirm restart", "Turn off"])
        await p.press(.turnOff, .c1)
        #expect(p.titles(.c1) == ["Restart", "Confirm turn off"]); #expect(await p.rig.commands().isEmpty)
        // Another target's action counts as another action too.
        await p.press(.turnOff, .c3)
        #expect(p.titles(.c1) == ["Restart", "Turn off"] && p.titles(.c3) == ["Restart", "Confirm turn off"])
        // Changing the expanded row disarms, collapsing included.
        p.detail.toggle(.c3, p.naming)
        #expect(p.detail.armed == nil)
        await p.press(.turnOff, .c3); p.detail.toggle(.c3, p.naming)
        #expect(p.detail.armed == nil && p.detail.expanded == nil)
        await p.press(.turnOff, .c3)
        #expect(await p.rig.commands().isEmpty)
        await p.rig.finish()
    }
    @Test(arguments: ["network", "link", "charger", "sign-out"])
    func armingDisarmsOnLostAvailabilityOrAContextChange(_ change: String) async throws {
        let p = try await ControlPanel()
        await p.press(.turnOff, .c1)
        let armedUnder = p.rig.controller.portControlGenerations
        switch change {
        case "network":
            await p.rig.events.send(.network(false))
            #expect(p.view.controls(.c1).caption == nil && !p.view.controls(.c1).enabled)
            await p.rig.events.send(.network(true)); await settle()
        case "link":
            // The backend's own link drop and replacement, within the confirmation window.
            p.rig.backend.output.yield(.status(.error("Synthetic link drop"))); await settle()
            p.rig.backend.output.yield(.status(.connected)); await settle()
            await detailReply(p.rig, syntheticDetails(faultBits: 0, switches: [.c1: true]))
        case "charger":
            await p.rig.controller.select(appCharger); await settle()
            await detailReply(p.rig, syntheticDetails(faultBits: 0, switches: [.c1: true]))
        default:
            await p.rig.controller.signOut()
            #expect(p.view.controls(.c1).caption == nil)
        }
        #expect(p.rig.controller.portControlGenerations != armedUnder)
        // The hosted panel revalidates on these changes; the model check is the same.
        p.detail.revalidate(in: p.rig.controller.portControlGenerations, available: p.view.controlsAvailable)
        #expect(p.detail.armed == nil)
        // The confirming click under the new context arms afresh rather than acting.
        if p.view.controlsAvailable {
            #expect(p.titles(.c1) == ["Restart", "Turn off"])
            await p.press(.turnOff, .c1)
            #expect(p.titles(.c1) == ["Restart", "Confirm turn off"])
        }
        #expect(await p.rig.commands().isEmpty)
        await p.rig.finish()
    }
    @Test func losingAvailabilityDisarmsEvenWhenItReturns() async throws {
        let p = try await ControlPanel()
        await p.press(.turnOff, .c1)
        let context = p.rig.controller.portControlGenerations
        // Unavailable controls never show or confirm an armed action...
        #expect(p.detail.armedAction(in: context, available: false) == nil && p.detail.armed != nil)
        #expect(!p.detail.press(.turnOff, target: .c1, in: context, available: false))
        #expect(p.detail.armed == nil)
        // ...and losing availability disarms for good, within the same context.
        await p.press(.turnOff, .c1)
        p.detail.revalidate(in: context, available: false)
        #expect(p.detail.armed == nil && p.detail.armedAction(in: context, available: true) == nil)
        await p.press(.turnOff, .c1)
        #expect(await p.rig.commands().isEmpty && p.titles(.c1) == ["Restart", "Confirm turn off"])
        await p.rig.finish()
    }
    @Test func aStaleArmedContextNeverDispatchesEvenWithoutRevalidation() async throws {
        let p = try await ControlPanel()
        await p.press(.turnOff, .c1)
        p.rig.backend.output.yield(.status(.error("Synthetic link drop"))); await settle()
        p.rig.backend.output.yield(.status(.connected)); await settle()
        await detailReply(p.rig, syntheticDetails(faultBits: 0, switches: [.c1: true]))
        // No hosted revalidation ran: the confirming click rechecks the context itself.
        #expect(p.detail.armed != nil && p.view.controlsAvailable)
        await p.press(.turnOff, .c1)
        #expect(await p.rig.commands().isEmpty && p.titles(.c1) == ["Restart", "Confirm turn off"])
        await p.rig.finish()
    }
    @Test func armedCaptionNamesThePortPowerAndDevice() async throws {
        // C1 carries the named lamp; C3 is unresolved; C4 supplies power with nothing identified.
        let readings = PortID.allCases.map {
            PortReading(port: $0, active: true, voltageMilli: 5000, currentMilli: 100,
                        powerCenti: [PortID.c1: 1234, .c4: 4321, .a1: 250, .a2: 125][$0] ?? 0)
        }
        let p = try await ControlPanel()
        p.rig.backend.output.snapshot(.init(receivedAt: p.rig.clock.date, readings: readings,
                                            details: syntheticDetails(faultBits: 0, switches: [.c1: true, .c3: true, .c4: true, .usbA: true])))
        await settle()
        await p.press(.turnOff, .c1)
        #expect(p.view.controls(.c1).caption == "C1 is supplying 12.34 W to Synthetic Desk Lamp.")
        await p.press(.restart, .c3)
        #expect(p.view.controls(.c3).caption == "C3 is supplying 0.00 W to a connected device.")
        #expect(p.view.controls(.c1).caption == nil)
        await p.press(.turnOff, .c4)
        #expect(p.view.controls(.c4).caption == "C4 is supplying 43.21 W to a connected device.")
        // The USB-A pair reports its combined power on either row.
        await p.press(.restart, .a2)
        #expect(p.view.controls(.a2).caption == "A1 and A2 is supplying 3.75 W to a connected device.")
        #expect(p.view.controls(.a1).caption == p.view.controls(.a2).caption)
        await p.rig.finish()
    }
    @Test func eachUnavailableReason() async throws {
        let p = try await ControlPanel()
        #expect(p.view.unavailableReason == nil && p.view.controlsAvailable)
        // Another port is changing: every other target is disabled and says why;
        // the active target shows its phase instead.
        p.rig.controller.turnPort(.c2, on: false); await settle()
        #expect(PortID.allCases.allSatisfy { !p.view.controls($0).enabled })
        #expect(p.view.controls(.c1).status == "Another port is changing.")
        #expect(p.view.controls(.a1).status == "Another port is changing.")
        #expect(p.view.controls(.c2).status == "Turning off…")
        await p.rig.switchReply(.c2, false)
        #expect(p.view.controlsAvailable && p.view.controls(.c1).status == nil)
        await p.rig.events.send(.network(false))
        #expect(p.view.unavailableReason == "Reconnect to control ports.")
        #expect(PortID.allCases.allSatisfy { !p.view.controls($0).enabled && p.view.controls($0).status == "Reconnect to control ports." })
        // Pressing a disabled control does nothing.
        await p.press(.turnOn, .c2)
        #expect(await p.rig.commands() == ["c2 off"])
        await p.rig.events.send(.network(true)); await settle()
        await p.rig.clock.advance(131)
        #expect(p.rig.controller.isStale && p.view.unavailableReason == "Readings are stale.")
        #expect(!p.view.controls(.c4).enabled && p.view.controls(.c4).status == "Readings are stale.")
        await p.rig.finish()
    }
    @Test func phaseTextInTheRowAndDetail() async throws {
        let p = try await ControlPanel()
        p.rig.controller.restartPort(.usbA); await settle()
        #expect(p.view.phaseText(.usbA) == "Turning off…")
        #expect(p.view.rowPresentation(.a1).secondaryText == "Turning off…" && p.view.rowPresentation(.a2).phase == "Turning off…")
        #expect(p.view.rowPresentation(.c1).phase == nil)
        await p.rig.switchReply(.usbA, false)
        #expect(p.view.phaseText(.usbA) == "On again in 5 s")
        await p.rig.clock.advance(2)
        #expect(p.view.phaseText(.usbA) == "On again in 3 s" && p.view.controls(.a1).status == "On again in 3 s")
        await p.rig.clock.advance(3)
        #expect(p.view.phaseText(.usbA) == "Turning on…")
        // Phase text leads, so a narrow row keeps it ahead of the off claim and device label.
        await detailReply(p.rig, syntheticDetails(faultBits: 0, switches: [.c1: true, .usbA: false]))
        #expect(p.view.rowPresentation(.a1).secondaryText == "Turning on… · Off")
        #expect(PortRowView(reading: p.view.rows[4], presentation: p.view.rowPresentation(.a1)).accessibilityText == "A1, Turning on…, Off, 0.00 W, 0.000 V, 0.000 A")
        await p.rig.switchReply(.usbA, true)
        // Successful confirmation clears phase text and leaves no outcome.
        #expect(p.view.phaseText(.usbA) == nil && p.view.outcomeText == nil && p.view.rowPresentation(.a1).phase == nil)
        await p.rig.finish()
    }
    @Test func outcomeTextForEachFailure() async throws {
        let p = try await ControlPanel()
        p.rig.controller.turnPort(.c2, on: false); await settle()
        await p.rig.clock.advance(PortControlPolicy.confirmationDeadline)
        #expect(p.view.outcomeText == "Desk: Couldn't confirm C2 turned off.")
        p.view.dismissOutcome()
        #expect(p.view.outcomeText == nil && p.rig.controller.portOutcome == nil)
        p.rig.controller.turnPort(.usbA, on: true); await settle()
        await p.rig.switchReply(.usbA, false)
        await p.rig.clock.advance(PortControlPolicy.confirmationDeadline)
        #expect(p.view.outcomeText == "Desk: A1 and A2 is still off. Turn it on to restore power.")
        // A new operation clears it.
        p.rig.controller.turnPort(.c3, on: true); await settle()
        #expect(p.view.outcomeText == nil)
        await p.rig.clock.advance(PortControlPolicy.confirmationDeadline)
        #expect(p.view.outcomeText == "Desk: Couldn't confirm C3 turned on.")
        p.view.dismissOutcome()
        // Unanswered confirmation requests left readings stale; a fresh reply restores control.
        #expect(p.view.unavailableReason == "Readings are stale.")
        await detailReply(p.rig, syntheticDetails(faultBits: 0, switches: [.c4: true]))
        // A restart interrupted by a charger change: the outcome keeps its original
        // charger label and is not attached to the new charger's rows.
        await p.rig.pausedRestart(.c4)
        #expect(p.view.phaseText(.c4) == "On again in 5 s")
        await p.rig.controller.select(otherCharger); await settle()
        await detailReply(p.rig, syntheticDetails(faultBits: 0, switches: [.c4: false]))
        #expect(p.view.alias == "Synthetic Prime")
        #expect(p.view.outcomeText == "Desk: C4 may still be off. Check the charger and turn the port on if needed.")
        #expect(PortID.allCases.allSatisfy { p.view.rowPresentation($0).phase == nil && p.view.controls($0).status == nil })
        #expect(p.view.rowPresentation(.c4).secondaryText == "Off")
        // It stays above the empty state after sign-out.
        await p.rig.controller.signOut()
        #expect(p.view.emptyMessage == "Sign in to your Anker account")
        #expect(p.view.outcomeText == "Desk: C4 may still be off. Check the charger and turn the port on if needed.")
        await p.rig.finish()
    }
    @Test func outcomeWordingCoversEveryKind() {
        let context = PortOperationContext(account: UUID(), charger: "synthetic-charger", chargerLabel: "Synthetic Desk")
        func text(_ kind: PortOperationOutcomeKind, _ target: PortSwitch) -> String? {
            PanelView.outcomeMessage(PortOperationOutcome(context: context, operation: .restart, target: target, wantedOn: true, kind: kind, boundary: nil))
        }
        #expect(text(.confirmed, .c1) == nil)
        #expect(text(.offNotConfirmed, .c1) == "Couldn't confirm C1 turned off.")
        #expect(text(.stillOff, .usbA) == "A1 and A2 is still off. Turn it on to restore power.")
        #expect(text(.onNotConfirmed, .c4) == "Couldn't confirm C4 turned on.")
        #expect(text(.mayStillBeOff, .usbA) == "A1 and A2 may still be off. Check the charger and turn the port on if needed.")
    }
    @Test func announcementsFollowPhaseChangesAndOutcomesNotTheCountdown() async throws {
        let p = try await ControlPanel()
        #expect(p.view.portAnnouncement == nil && p.view.portAnnouncementKey == nil)
        p.rig.controller.restartPort(.c1); await settle()
        let off = p.view.portAnnouncementKey
        #expect(off != nil && p.view.portAnnouncement == "Turning off…")
        await p.rig.switchReply(.c1, false)
        let paused = p.view.portAnnouncementKey
        #expect(paused != off && p.view.portAnnouncement == "On again in 5 s")
        await p.rig.clock.advance(1)
        #expect(p.view.portAnnouncementKey == paused && p.view.portAnnouncement == "On again in 4 s")
        await p.rig.clock.advance(4)
        #expect(p.view.portAnnouncementKey != paused && p.view.portAnnouncement == "Turning on…")
        await p.rig.clock.advance(PortControlPolicy.confirmationDeadline)
        #expect(p.view.portAnnouncement == "Desk: Couldn't confirm C1 turned on.")
        p.view.dismissOutcome()
        #expect(p.view.portAnnouncementKey == nil)
        await p.rig.finish()
    }
    @Test func hostedPanelAnnouncesPhaseChangesAndOutcomes() async throws {
        let p = try await ControlPanel()
        var announced: [String] = []
        let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: 400, height: 600), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        defer { window.contentViewController = nil }
        var view = p.view
        view.announce = { announced.append($0) }
        window.contentViewController = NSHostingController(rootView: view)
        await pumpRunLoop()
        p.rig.controller.turnPort(.c2, on: false); await settle(); await pumpRunLoop()
        await p.rig.clock.advance(PortControlPolicy.confirmationDeadline); await pumpRunLoop()
        #expect(announced == ["Turning off…", "Desk: Couldn't confirm C2 turned off."])
        await p.rig.finish()
    }
    @Test func cancelNamingDelegatesToTheOwnerOrDisarmsBeforeCancellingTheEdit() async throws {
        let p = try await ControlPanel()
        p.detail.toggle(.c1, p.naming)
        let lamp = NamingTarget(charger: appCharger.serial, port: .c1, key: syntheticLamp)
        p.detail.beginEditing(); p.detail.edit("Synthetic Kept Draft", for: lamp, in: p.catalog.store.catalog)
        await p.press(.turnOff, .c1)
        // With an owner, the owner alone decides.
        var delegated = 0
        var owned = p.view
        owned.cancelAction = { delegated += 1 }
        owned.cancelNaming()
        #expect(delegated == 1 && p.detail.armed != nil && p.detail.draft?.text == "Synthetic Kept Draft" && p.detail.editing)
        // Standalone: disarming consumes the first Escape and keeps the naming state.
        p.view.cancelNaming()
        #expect(p.detail.armed == nil && p.detail.draft?.text == "Synthetic Kept Draft" && p.detail.editing)
        // With nothing armed it cancels the edit as before.
        p.view.cancelNaming()
        #expect(p.detail.draft == nil && !p.detail.editing)
        // An expired armed action is not disarmed by Escape: it cancels nothing armed.
        p.detail.endEditing(p.naming)
        await p.press(.turnOff, .c1); await p.rig.clock.advance(PortControlPolicy.confirmationWindow)
        #expect(!p.detail.disarm(in: p.rig.controller.portControlGenerations, available: true))
        await p.rig.finish()
    }
}
