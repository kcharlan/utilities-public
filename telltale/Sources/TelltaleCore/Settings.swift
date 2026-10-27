import Foundation

/// A typed key in the `settings` table. `defaultValue` is returned when the key is absent
/// or its stored JSON no longer decodes.
public struct SettingKey<Value: Codable & Sendable>: Sendable {
    public let name: String
    public let defaultValue: Value

    public init(name: String, defaultValue: Value) {
        self.name = name
        self.defaultValue = defaultValue
    }
}

/// Dashboard appearance (spec section 9.4); the panel always follows the system.
public enum Appearance: String, Sendable, Equatable, Hashable, Codable, CaseIterable {
    case dark, light, system
}

/// Shared validation for the collector interval. The keys themselves are static members of
/// `SettingKey` (below), so callers write `store.value(.collectorEnabled)`.
public enum Settings {
    /// The collector interval range in minutes (spec section 9.3).
    public static let intervalRange = 1...60

    /// The shared interval validator (Settings and `LaunchAgentManager`): nil when valid.
    public static func intervalError(_ minutes: Int) -> String? {
        intervalRange.contains(minutes) ? nil : Copy.intervalError(min: intervalRange.lowerBound, max: intervalRange.upperBound)
    }
}

// MARK: - Keys (spec sections 3, 7.4, 9.3, 9.4)
//
// Static members of `SettingKey` in constrained extensions, so callers write
// `store.value(.collectorEnabled)` and later tasks add their own keys the same way.

extension SettingKey where Value == Bool {
    /// Whether the collector should be installed and running. On by default (plan Goal 1);
    /// Task 11 limits the automatic turn-on to the installed app.
    public static var collectorEnabled: SettingKey<Bool> { SettingKey(name: "collectorEnabled", defaultValue: true) }
    public static var openAtLogin: SettingKey<Bool> { SettingKey(name: "openAtLogin", defaultValue: true) }
}

extension SettingKey where Value == Int {
    /// Collector interval in minutes (spec section 9.3); validate with `Settings.intervalError`.
    public static var intervalMinutes: SettingKey<Int> { SettingKey(name: "intervalMinutes", defaultValue: 5) }
}

extension SettingKey where Value == RuleSettings {
    public static var rules: SettingKey<RuleSettings> { SettingKey(name: "rules", defaultValue: RuleSettings.defaults) }
}

extension SettingKey where Value == [String] {
    /// Spec section 7.4's watched-components defaults, matched against the status page's names.
    public static var watchedComponents: SettingKey<[String]> {
        SettingKey(name: "watchedComponents", defaultValue: ["CLI", "VS Code extension", "Codex in ChatGPT Desktop", "Codex API", "Codex Web", "Responses"])
    }
}

extension SettingKey where Value == Appearance {
    public static var appearance: SettingKey<Appearance> { SettingKey(name: "appearance", defaultValue: .dark) }
}

extension SettingKey where Value == Date? {
    /// Set by the app to ask the collector for "Rebuild from Codex logs" (spec section 7.3).
    public static var rebuildRequestedAt: SettingKey<Date?> { SettingKey(name: "rebuildRequestedAt", defaultValue: nil) }
    /// The end of the last completed backfill (Task 9).
    public static var backfillThrough: SettingKey<Date?> { SettingKey(name: "backfillThrough", defaultValue: nil) }
}

extension SettingKey where Value == String? {
    /// The last local day (`yyyy-MM-dd`) retention ran (Task 9).
    public static var lastPrunedDay: SettingKey<String?> { SettingKey(name: "lastPrunedDay", defaultValue: nil) }
}

// MARK: - Rule settings (spec section 7.4)

/// "Slower than usual" and "Faster than usual". `threshold` and `clearBand` are fractions of
/// usual: 0.15 fires at a speed index of 0.85 (or 1.15), and 0.08 clears within 8% of usual.
public struct SpeedRule: Sendable, Equatable, Hashable, Codable {
    public var enabled: Bool
    public var threshold: Double
    public var durationMinutes: Int
    public var clearBand: Double
    public var clearMinutes: Int
    public var notify: Bool
    public var notifyOnClear: Bool

    public init(enabled: Bool, threshold: Double, durationMinutes: Int, clearBand: Double, clearMinutes: Int, notify: Bool, notifyOnClear: Bool) {
        self.enabled = enabled
        self.threshold = threshold
        self.durationMinutes = durationMinutes
        self.clearBand = clearBand
        self.clearMinutes = clearMinutes
        self.notify = notify
        self.notifyOnClear = notifyOnClear
    }
}

/// Fires when at least `count` of the model's last `of` responses had at least `inputTokens`
/// input tokens; clears at `clearAtMost` or fewer of the last `of`.
public struct LargePromptRule: Sendable, Equatable, Hashable, Codable {
    public var enabled: Bool
    public var inputTokens: Int
    public var count: Int
    public var of: Int
    public var clearAtMost: Int
    public var notify: Bool
    public var notifyOnClear: Bool

    public init(enabled: Bool, inputTokens: Int, count: Int, of: Int, clearAtMost: Int, notify: Bool, notifyOnClear: Bool) {
        self.enabled = enabled
        self.inputTokens = inputTokens
        self.count = count
        self.of = of
        self.clearAtMost = clearAtMost
        self.notify = notify
        self.notifyOnClear = notifyOnClear
    }
}

public struct FailedTurnRule: Sendable, Equatable, Hashable, Codable {
    public var enabled: Bool
    /// Minutes with no failure before the rule clears.
    public var quietMinutes: Int
    /// At most one notification per this many minutes.
    public var coalesceMinutes: Int
    public var notify: Bool
    public var notifyOnClear: Bool

    public init(enabled: Bool, quietMinutes: Int, coalesceMinutes: Int, notify: Bool, notifyOnClear: Bool) {
        self.enabled = enabled
        self.quietMinutes = quietMinutes
        self.coalesceMinutes = coalesceMinutes
        self.notify = notify
        self.notifyOnClear = notifyOnClear
    }
}

public struct DisconnectRule: Sendable, Equatable, Hashable, Codable {
    public var enabled: Bool
    public var count: Int
    public var windowMinutes: Int
    public var notify: Bool
    public var notifyOnClear: Bool

    public init(enabled: Bool, count: Int, windowMinutes: Int, notify: Bool, notifyOnClear: Bool) {
        self.enabled = enabled
        self.count = count
        self.windowMinutes = windowMinutes
        self.notify = notify
        self.notifyOnClear = notifyOnClear
    }
}

/// Rules with no parameters: provider incident and collector health.
public struct BasicRule: Sendable, Equatable, Hashable, Codable {
    public var enabled: Bool
    public var notify: Bool
    public var notifyOnClear: Bool

    public init(enabled: Bool, notify: Bool, notifyOnClear: Bool) {
        self.enabled = enabled
        self.notify = notify
        self.notifyOnClear = notifyOnClear
    }
}

public struct UsageLimitRule: Sendable, Equatable, Hashable, Codable {
    public var enabled: Bool
    /// Percent of the primary window used, in (0, 100].
    public var percent: Double
    public var notify: Bool
    public var notifyOnClear: Bool

    public init(enabled: Bool, percent: Double, notify: Bool, notifyOnClear: Bool) {
        self.enabled = enabled
        self.percent = percent
        self.notify = notify
        self.notifyOnClear = notifyOnClear
    }
}

public struct RuleSettings: Sendable, Equatable, Hashable, Codable {
    public var slower: SpeedRule
    public var faster: SpeedRule
    public var largePrompts: LargePromptRule
    public var failedTurns: FailedTurnRule
    public var disconnects: DisconnectRule
    public var incident: BasicRule
    public var collectorHealth: BasicRule
    public var usageLimit: UsageLimitRule

    public init(
        slower: SpeedRule, faster: SpeedRule, largePrompts: LargePromptRule, failedTurns: FailedTurnRule,
        disconnects: DisconnectRule, incident: BasicRule, collectorHealth: BasicRule, usageLimit: UsageLimitRule
    ) {
        self.slower = slower
        self.faster = faster
        self.largePrompts = largePrompts
        self.failedTurns = failedTurns
        self.disconnects = disconnects
        self.incident = incident
        self.collectorHealth = collectorHealth
        self.usageLimit = usageLimit
    }

    /// Spec section 7.4's table. Values it doesn't state are plan calls: failed turns and
    /// disconnects don't notify on clear, collector health does, and the usage limit is
    /// off and silent.
    public static let defaults = RuleSettings(
        slower: SpeedRule(enabled: true, threshold: 0.15, durationMinutes: 15, clearBand: 0.08, clearMinutes: 30, notify: true, notifyOnClear: true),
        faster: SpeedRule(enabled: true, threshold: 0.15, durationMinutes: 15, clearBand: 0.08, clearMinutes: 30, notify: true, notifyOnClear: true),
        largePrompts: LargePromptRule(enabled: true, inputTokens: 300_000, count: 3, of: 10, clearAtMost: 1, notify: true, notifyOnClear: false),
        failedTurns: FailedTurnRule(enabled: true, quietMinutes: 30, coalesceMinutes: 15, notify: true, notifyOnClear: false),
        disconnects: DisconnectRule(enabled: true, count: 3, windowMinutes: 60, notify: false, notifyOnClear: false),
        incident: BasicRule(enabled: true, notify: true, notifyOnClear: true),
        collectorHealth: BasicRule(enabled: true, notify: true, notifyOnClear: true),
        usageLimit: UsageLimitRule(enabled: false, percent: 90, notify: false, notifyOnClear: false))

    /// Messages for every invalid parameter, in rule order; empty when the settings are usable.
    /// Callers reject invalid values before saving or evaluating them.
    public func validationErrors() -> [String] {
        var errors: [String] = []
        func invalid(_ field: String) { errors.append(Copy.invalidRuleParameter(field: field)) }

        for (name, rule) in [("Slower than usual", slower), ("Faster than usual", faster)] {
            let thresholdValid = rule.threshold.isFinite && rule.threshold > 0 && rule.threshold < 1
            if !thresholdValid { invalid("\(name) threshold") }
            if rule.durationMinutes <= 0 { invalid("\(name) duration") }
            if !(rule.clearBand.isFinite && rule.clearBand > 0) {
                invalid("\(name) clear band")
            } else if thresholdValid, rule.clearBand >= rule.threshold {
                // Spec section 7.2: the clear band must be stricter than the trigger.
                errors.append(Copy.clearBandError)
            }
            if rule.clearMinutes <= 0 { invalid("\(name) clear duration") }
        }

        if largePrompts.inputTokens <= 0 { invalid("Large prompts input tokens") }
        if largePrompts.count <= 0 || (largePrompts.of > 0 && largePrompts.count > largePrompts.of) { invalid("Large prompts count") }
        if largePrompts.of <= 0 { invalid("Large prompts window") }
        if largePrompts.clearAtMost < 0 || (largePrompts.count > 0 && largePrompts.clearAtMost >= largePrompts.count) {
            invalid("Large prompts clear level")
        }

        if failedTurns.quietMinutes <= 0 { invalid("Failed turns quiet period") }
        if failedTurns.coalesceMinutes <= 0 { invalid("Failed turns notice spacing") }
        if disconnects.count <= 0 { invalid("Disconnects count") }
        if disconnects.windowMinutes <= 0 { invalid("Disconnects window") }

        if !(usageLimit.percent.isFinite && usageLimit.percent > 0 && usageLimit.percent <= 100) { invalid("Usage limit percentage") }
        return errors
    }
}
