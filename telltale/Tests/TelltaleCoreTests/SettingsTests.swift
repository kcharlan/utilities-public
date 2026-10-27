import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct SettingsTests {
    @Test func absentKeyReturnsDefault() throws {
        try withScratchDirectory { directory in
            let store = try Store.open(directory.appending(path: "telltale.sqlite"), mode: .readWrite)
            #expect(try store.value(Settings.collectorEnabled) == true)
            #expect(try store.value(Settings.intervalMinutes) == 5)
            #expect(try store.value(Settings.rules) == RuleSettings.defaults)
            #expect(try store.value(Settings.watchedComponents) == [
                "CLI", "VS Code extension", "Codex in ChatGPT Desktop", "Codex API", "Codex Web", "Responses",
            ])
            #expect(try store.value(Settings.appearance) == .dark)
            #expect(try store.value(Settings.openAtLogin) == true)
            #expect(try store.value(Settings.rebuildRequestedAt) == nil)
            #expect(try store.value(Settings.backfillThrough) == nil)
            #expect(try store.value(Settings.lastPrunedDay) == nil)
        }
    }

    /// Spec section 7.4's table, restated literally. Speed thresholds and clear bands are
    /// fractions of usual: "speed index <= 0.85" is 0.15 slower and "> 0.92" is within 0.08.
    @Test func ruleDefaultsMatchSection74() {
        let rules = RuleSettings.defaults
        #expect(rules.slower == SpeedRule(enabled: true, threshold: 0.15, durationMinutes: 15, clearBand: 0.08, clearMinutes: 30, notify: true, notifyOnClear: true))
        #expect(rules.faster == SpeedRule(enabled: true, threshold: 0.15, durationMinutes: 15, clearBand: 0.08, clearMinutes: 30, notify: true, notifyOnClear: true))
        #expect(rules.largePrompts == LargePromptRule(enabled: true, inputTokens: 300_000, count: 3, of: 10, clearAtMost: 1, notify: true, notifyOnClear: false))
        #expect(rules.failedTurns == FailedTurnRule(enabled: true, quietMinutes: 30, coalesceMinutes: 15, notify: true, notifyOnClear: false))
        #expect(rules.disconnects == DisconnectRule(enabled: true, count: 3, windowMinutes: 60, notify: false, notifyOnClear: false))
        #expect(rules.incident == BasicRule(enabled: true, notify: true, notifyOnClear: true))
        #expect(rules.collectorHealth == BasicRule(enabled: true, notify: true, notifyOnClear: true))
        #expect(rules.usageLimit == UsageLimitRule(enabled: false, percent: 90, notify: false, notifyOnClear: false))
        #expect(rules.validationErrors().isEmpty)
    }

    @Test func roundTripsEveryKey() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "telltale.sqlite")
            var rules = RuleSettings.defaults
            rules.slower.threshold = 0.3
            rules.slower.durationMinutes = 7
            rules.largePrompts.of = 12
            rules.usageLimit.enabled = true
            rules.usageLimit.percent = 80.5
            let rebuild = Synthetic.at(12_345.678)
            let backfill = Synthetic.at(99_999)
            let writer = try Store.open(url, mode: .readWrite)
            try writer.set(Settings.collectorEnabled, false)
            try writer.set(Settings.intervalMinutes, 15)
            try writer.set(Settings.rules, rules)
            try writer.set(Settings.watchedComponents, ["Example component", "Other component"])
            try writer.set(Settings.appearance, .system)
            try writer.set(Settings.openAtLogin, false)
            try writer.set(Settings.rebuildRequestedAt, rebuild)
            try writer.set(Settings.backfillThrough, backfill)
            try writer.set(Settings.lastPrunedDay, "2026-01-02")

            let reader = try Store.open(url, mode: .readOnly)
            #expect(try reader.value(Settings.collectorEnabled) == false)
            #expect(try reader.value(Settings.intervalMinutes) == 15)
            #expect(try reader.value(Settings.rules) == rules)
            #expect(try reader.value(Settings.watchedComponents) == ["Example component", "Other component"])
            #expect(try reader.value(Settings.appearance) == .system)
            #expect(try reader.value(Settings.openAtLogin) == false)
            #expect(try reader.value(Settings.rebuildRequestedAt) == rebuild)
            #expect(try reader.value(Settings.backfillThrough) == backfill)
            #expect(try reader.value(Settings.lastPrunedDay) == "2026-01-02")

            // Clearing an optional key returns it to nil, and a later set replaces the earlier row.
            try writer.set(Settings.rebuildRequestedAt, nil)
            try writer.set(Settings.intervalMinutes, 20)
            #expect(try reader.value(Settings.rebuildRequestedAt) == nil)
            #expect(try reader.value(Settings.intervalMinutes) == 20)
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM settings WHERE key = 'intervalMinutes'") == "1")
        }
    }

    @Test func settingKeyNamesAreStableAndDistinct() {
        let names = [
            Settings.collectorEnabled.name, Settings.intervalMinutes.name, Settings.rules.name,
            Settings.watchedComponents.name, Settings.appearance.name, Settings.openAtLogin.name,
            Settings.rebuildRequestedAt.name, Settings.backfillThrough.name, Settings.lastPrunedDay.name,
        ]
        #expect(Set(names).count == names.count)
        #expect(names == [
            "collectorEnabled", "intervalMinutes", "rules", "watchedComponents", "appearance", "openAtLogin",
            "rebuildRequestedAt", "backfillThrough", "lastPrunedDay",
        ])
    }

    @Test func undecodableValueFallsBackToDefault() throws {
        try withScratchDirectory { directory in
            let store = try Store.open(directory.appending(path: "telltale.sqlite"), mode: .readWrite)
            try store.exec("INSERT INTO settings (key, value_json) VALUES ('intervalMinutes', '\"five\"')")
            try store.exec("INSERT INTO settings (key, value_json) VALUES ('rules', '{\"slower\": ')")
            try store.exec("INSERT INTO settings (key, value_json) VALUES ('appearance', '\"sepia\"')")
            try store.exec("INSERT INTO settings (key, value_json) VALUES ('collectorEnabled', '')")
            #expect(try store.value(Settings.intervalMinutes) == 5)
            #expect(try store.value(Settings.rules) == RuleSettings.defaults)
            #expect(try store.value(Settings.appearance) == .dark)
            #expect(try store.value(Settings.collectorEnabled) == true)
        }
    }

    @Test func clearBandMustBeStricterThanTrigger() {
        var rules = RuleSettings.defaults
        rules.slower.threshold = 0.2
        rules.slower.clearBand = 0.2
        #expect(rules.validationErrors() == [Copy.clearBandError])
        rules.slower.clearBand = 0.25
        #expect(rules.validationErrors() == [Copy.clearBandError])
        rules.slower.clearBand = 0.19
        #expect(rules.validationErrors().isEmpty)

        rules.faster.clearBand = rules.faster.threshold
        #expect(rules.validationErrors() == [Copy.clearBandError])
        rules.slower.clearBand = 0.5
        #expect(rules.validationErrors() == [Copy.clearBandError, Copy.clearBandError])
        // A clear band of a whole usual or more can never be stricter than a trigger below one.
        rules = .defaults
        rules.faster.clearBand = 1
        #expect(rules.validationErrors() == [Copy.clearBandError])
    }

    @Test func invalidRuleParametersAreRejected() {
        func field(_ name: String) -> [String] { [Copy.invalidRuleParameter(field: name)] }
        func check(_ label: String, _ expected: [String], sourceLocation: SourceLocation = #_sourceLocation, _ change: (inout RuleSettings) -> Void) {
            var rules = RuleSettings.defaults
            change(&rules)
            #expect(rules.validationErrors() == expected, Comment(rawValue: label), sourceLocation: sourceLocation)
        }

        for (name, keyPath) in [("Slower than usual", \RuleSettings.slower), ("Faster than usual", \RuleSettings.faster)] {
            for bad in [0, -0.1, 1, 1.5, .nan, .infinity, -.infinity] as [Double] {
                check("\(name) threshold \(bad)", field("\(name) threshold")) { $0[keyPath: keyPath].threshold = bad }
            }
            for bad in [0, -0.01, .nan, .infinity, -.infinity] as [Double] {
                check("\(name) clear band \(bad)", field("\(name) clear band")) { $0[keyPath: keyPath].clearBand = bad }
            }
            for bad in [0, -1] {
                check("\(name) duration \(bad)", field("\(name) duration")) { $0[keyPath: keyPath].durationMinutes = bad }
                check("\(name) clear duration \(bad)", field("\(name) clear duration")) { $0[keyPath: keyPath].clearMinutes = bad }
            }
            // Valid values off the five-minute grid are accepted (the engine rounds them up).
            check("\(name) off-grid durations", []) {
                $0[keyPath: keyPath].durationMinutes = 7
                $0[keyPath: keyPath].clearMinutes = 1
            }
        }

        for bad in [0, -5] {
            check("input tokens \(bad)", field("Large prompts input tokens")) { $0.largePrompts.inputTokens = bad }
            check("count \(bad)", field("Large prompts count")) { $0.largePrompts.count = bad }
            check("window \(bad)", field("Large prompts window")) { $0.largePrompts.of = bad }
        }
        check("count above window", field("Large prompts count")) { $0.largePrompts.count = 11 }
        check("count equal to window", []) { $0.largePrompts.count = 10 }
        check("clear level equal to count", field("Large prompts clear level")) { $0.largePrompts.clearAtMost = 3 }
        check("clear level above count", field("Large prompts clear level")) { $0.largePrompts.clearAtMost = 4 }
        check("negative clear level", field("Large prompts clear level")) { $0.largePrompts.clearAtMost = -1 }
        check("zero clear level", []) { $0.largePrompts.clearAtMost = 0 }

        for bad in [0, -1] {
            check("quiet minutes \(bad)", field("Failed turns quiet period")) { $0.failedTurns.quietMinutes = bad }
            check("coalesce minutes \(bad)", field("Failed turns notice spacing")) { $0.failedTurns.coalesceMinutes = bad }
            check("disconnect count \(bad)", field("Disconnects count")) { $0.disconnects.count = bad }
            check("disconnect window \(bad)", field("Disconnects window")) { $0.disconnects.windowMinutes = bad }
        }
        check("odd windows are fine", []) {
            $0.failedTurns.quietMinutes = 7
            $0.failedTurns.coalesceMinutes = 1
            $0.disconnects.windowMinutes = 45
        }

        for bad in [0, -1, 100.5, 101, .nan, .infinity, -.infinity] as [Double] {
            check("usage percent \(bad)", field("Usage limit percentage")) { $0.usageLimit.percent = bad }
        }
        check("usage percent 100", []) { $0.usageLimit.percent = 100 }
        check("usage percent fraction", []) { $0.usageLimit.percent = 0.5 }

        // Several problems are all reported, in rule order.
        check("two problems", field("Slower than usual duration") + field("Disconnects count")) {
            $0.slower.durationMinutes = 0
            $0.disconnects.count = 0
        }
    }

    @Test func intervalErrorOutsideOneToSixty() {
        let message = Copy.intervalError(min: 1, max: 60)
        #expect(message.contains("1") && message.contains("60"))
        #expect(Settings.intervalError(1) == nil)
        #expect(Settings.intervalError(5) == nil)
        #expect(Settings.intervalError(60) == nil)
        for bad in [0, -1, 61, 120, Int.min, Int.max] {
            #expect(Settings.intervalError(bad) == message, "interval \(bad)")
        }
    }
}
