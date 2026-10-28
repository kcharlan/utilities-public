import AppKit
import SwiftUI
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

/// Spec section 9.2's model view through its model: Accept as usual (section 8's picker contract)
/// and Undo from the event list (section 8's Undo contract), written through `UserActions`.
@MainActor @Suite(.serialized) struct ModelViewTests {
    static let now = Synth.local(2026, 9, 17, 12)

    /// Sep 1–14 at 40 tok/s, then Sep 15–17 at 30 tok/s inside a slower episode each day; a finished
    /// run at `now`. With `cleared` false the episodes end idle, so no lasting-shift prompt shows.
    private func seed(_ paths: TelltalePaths, shift: Bool) throws {
        let store = try Store.open(paths.database, mode: .readWrite)
        var synth = Synth()
        for day in 1...14 { try store.upsert(responses: synth.responses(20, throughput: 40, from: Synth.local(2026, 9, day, 9))) }
        for day in 15...17 {
            try store.upsert(responses: synth.responses(10, throughput: 30, from: Synth.local(2026, 9, day, 9)))
            if shift {
                try store.insertEpisode(EpisodeRow(
                    rule: RuleID.slower.rawValue, provider: ProviderID.codex.rawValue, scope: Synth.model, direction: .slower,
                    onset: Synth.local(2026, 9, day, 8, 50), firedAt: Synth.local(2026, 9, day, 9, 5), endedAt: Synth.local(2026, 9, day, 9, 30),
                    endReason: EpisodeRow.EndReason.cleared, severity: LampColor.amber.rawValue, worstValue: 0.75))
            }
        }
        let run = try store.beginRun(at: Self.now.addingTimeInterval(-60))
        try store.finishRun(run, at: Self.now.addingTimeInterval(-56), outcome: .succeeded)
    }

    private func currentEpoch(_ paths: TelltalePaths) throws -> BaselineEpoch? {
        let store = try Store.open(paths.database, mode: .readOnly)
        return try BaselineEngine(store: store, calendar: Synth.newYork).currentEpoch(provider: .codex, model: Synth.model)
    }

    @Test func acceptFlowCallsUserActionsWithChosenDate() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory, now: Self.now)
            try seed(world.paths, shift: false)
            world.live.reload()
            let model = world.model
            model.select(.model(.codex, Synth.model))
            #expect(model.detail?.shift == nil)

            // With no lasting shift the picker starts on today (plan call); Cancel writes nothing.
            model.beginAccept()
            #expect(model.acceptingSince == Synth.local(2026, 9, 17))
            model.cancelAccept()
            #expect(model.acceptingSince == nil)
            #expect(try currentEpoch(world.paths) == nil)

            model.beginAccept()
            model.acceptingSince = Synth.local(2026, 9, 15, 14, 30)
            model.accept()
            #expect(model.acceptingSince == nil && model.panel.actionError == nil)
            let epoch = try #require(try currentEpoch(world.paths))
            #expect(epoch.since == LocalDay(year: 2026, month: 9, day: 15))
            #expect(epoch.createdAt == Self.now)
        }
    }

    @Test func acceptPickerDefaultsToTheShiftsFirstDay() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory, now: Self.now)
            try seed(world.paths, shift: true)
            world.live.reload()
            world.model.select(.model(.codex, Synth.model))
            #expect(world.model.detail?.shift?.firstDay == LocalDay(year: 2026, month: 9, day: 15))
            world.model.beginAccept()
            #expect(world.model.acceptingSince == Synth.local(2026, 9, 15))
        }
    }

    @Test func acceptConfirmationUsesAcceptanceCopy() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory, now: Self.now)
            try seed(world.paths, shift: true)
            world.live.reload()
            world.model.select(.model(.codex, Synth.model))
            world.model.beginAccept()
            world.model.accept()
            let confirmation = try #require(world.model.panel.confirmation)
            // The stored event carries the same percentage; the confirmation uses the display name.
            let store = try Store.open(world.paths.database, mode: .readOnly)
            let feed = try EventFeed.load(store: store, limit: 10, naming: { _, model in model == Synth.model ? "Example" : model }, calendar: Synth.newYork)
            let accepted = try #require(feed.first { $0.kind == .baselineAccepted })
            #expect(confirmation.text == accepted.body)
            #expect(confirmation.text.hasPrefix("Example's usual speed is now ") && confirmation.text.hasSuffix(" than before."))
            #expect(confirmation.epochID == accepted.undoableEpochID)
            // The dashboard's own event list shows the acceptance with Undo.
            #expect(world.model.feed.first?.kind == .baselineAccepted && world.model.feed.first?.undoableEpochID == confirmation.epochID)
        }
    }

    @Test func undoButtonCallsUndo() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory, now: Self.now)
            try seed(world.paths, shift: true)
            world.live.reload()
            let model = world.model
            model.select(.model(.codex, Synth.model))

            // Two acceptances: undoing the newest needs no confirmation.
            model.beginAccept()
            model.accept()
            world.clock.now = Self.now.addingTimeInterval(60)
            model.beginAccept()
            model.acceptingSince = Synth.local(2026, 9, 16)
            model.accept()
            let newest = try #require(model.feed.first { $0.kind == .baselineAccepted })
            let older = try #require(model.feed.last { $0.kind == .baselineAccepted })
            #expect(newest.undoableEpochID != older.undoableEpochID)

            // The older one asks first, with the confirmation copy; Cancel leaves it in place.
            world.clock.now = Self.now.addingTimeInterval(120)
            model.requestUndo(older)
            #expect(model.pendingUndo?.id == older.id)
            #expect(model.pendingUndo?.undoConfirmation == Copy.undoEarlierAcceptanceConfirmation(model: "Example"))
            model.cancelUndo()
            #expect(model.pendingUndo == nil)
            #expect(try currentEpoch(world.paths)?.id == newest.undoableEpochID)

            model.requestUndo(newest)
            #expect(model.pendingUndo == nil && model.panel.actionError == nil)
            #expect(try currentEpoch(world.paths)?.id == older.undoableEpochID)
            let undone = try #require(model.feed.first { $0.id == newest.id })
            #expect(undone.undoableEpochID == nil && undone.undoneAt == Self.now.addingTimeInterval(120))

            model.requestUndo(try #require(model.feed.first { $0.id == older.id }))
            #expect(model.pendingUndo == nil)
            #expect(try currentEpoch(world.paths) == nil)
        }
    }

    /// Closing the alert clears its binding (`cancelUndo`) before or after the Undo button's
    /// action runs, so the confirmed event comes from the alert, not from `pendingUndo`.
    @Test func confirmedUndoSurvivesTheAlertClosingFirst() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory, now: Self.now)
            try seed(world.paths, shift: true)
            world.live.reload()
            let model = world.model
            model.select(.model(.codex, Synth.model))
            model.beginAccept()
            model.accept()
            world.clock.now = Self.now.addingTimeInterval(60)
            model.beginAccept()
            model.acceptingSince = Synth.local(2026, 9, 16)
            model.accept()
            let older = try #require(model.feed.last { $0.kind == .baselineAccepted })

            world.clock.now = Self.now.addingTimeInterval(120)
            model.requestUndo(older)
            let presented = try #require(model.pendingUndo)
            model.cancelUndo()
            model.confirmUndo(presented)
            #expect(model.pendingUndo == nil && model.panel.actionError == nil)
            #expect(try currentEpoch(world.paths) == nil)
        }
    }

    /// R31 and incident scoping: the dashboard's shift prompt links to the incidents in its period,
    /// and the chart's bands come only from the model's own status source.
    @Test func shiftPromptLinksIncidentsAndBandsAreScoped() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory, now: Self.now)
            try seed(world.paths, shift: true)
            var other = PanelWorld.incident(published: Synth.local(2026, 9, 16, 14), id: "inc_synthetic_08")
            other.source = "example-other-status"
            try Store.open(world.paths.database, mode: .readWrite).upsert(incidents: [PanelWorld.incident(published: Synth.local(2026, 9, 16, 10)), other])
            world.live.reload()
            world.model.select(.model(.codex, Synth.model))
            #expect(world.model.shiftIncidents.map(\.id) == ["inc_synthetic_07"])
            #expect(world.model.detail?.incidents == [DateInterval(start: Synth.local(2026, 9, 16, 10), end: Synth.local(2026, 9, 16, 11))])
        }
    }

    @Test func modelViewLaysOutAtTheWindowWidth() throws {
        try withScratchDirectory { directory in
            let world = try DashboardWorld(directory, now: Self.now)
            try seed(world.paths, shift: true)
            world.live.reload()
            world.model.select(.model(.codex, Synth.model))
            #expect(world.model.workload != nil && world.model.detail != nil)
            let host = NSHostingView(rootView: DashboardView(model: world.model).frame(width: 1100, height: 760))
            host.frame = NSRect(x: 0, y: 0, width: 1100, height: 760)
            host.layoutSubtreeIfNeeded()
            #expect(host.fittingSize.width == 1100)
        }
    }
}
