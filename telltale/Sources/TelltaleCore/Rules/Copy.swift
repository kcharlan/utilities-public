import Foundation

/// User-facing wording (visual design doc, "Copy rules"; the plan's Copy table). Callers use
/// these functions rather than literals. Times are `HH:mm` in the calendar passed in.
public enum Copy {
    // MARK: Speed rules (spec sections 7.2 and 7.3)

    public static func slowerFired(model: String, percent: Int, since: Date, calendar: Calendar) -> String {
        "\(model) is \(percent)% slower than usual for prompts this size. Since \(clock(since, calendar))."
    }
    /// Spec section 7.3's catch-up notice for an episode still open after a gap.
    public static func slowerCatchUp(model: String, percent: Int, since: Date, calendar: Calendar) -> String {
        "\(model) has been \(percent)% slower since \(clock(since, calendar))."
    }
    public static func slowerEscalated(model: String, percent: Int) -> String { "\(model) is now \(percent)% slower than usual." }
    /// Spec section 7.2's clear notice.
    public static func speedCleared(model: String) -> String { "\(model) is back to usual speed." }
    public static func fasterFired(model: String, percent: Int, since: Date, calendar: Calendar) -> String {
        "\(model) is \(percent)% faster than usual. Check that output isn't shallower. Since \(clock(since, calendar))."
    }
    public static func fasterCatchUp(model: String, percent: Int, since: Date, calendar: Calendar) -> String {
        "\(model) has been \(percent)% faster than usual since \(clock(since, calendar))."
    }

    // MARK: Large prompts

    /// The visual doc's panel alert, with the inclusive threshold ("at least").
    public static func largePromptsFired(count: Int, of: Int, tokens: Int) -> String {
        "\(count) of your last \(of) prompts were at least \(tokenCount(tokens)) tokens. A fresh session would speed things up."
    }
    public static let largePromptsCleared = "Prompt sizes are back to usual."

    // MARK: Failed turns

    /// `reasons` are display reasons (`failedTurnReason`); repeats are listed once.
    public static func failedTurns(count: Int, reasons: [String]) -> String {
        "\(count) \(count == 1 ? "turn" : "turns") failed: \(list(reasons))"
    }
    public static func failedTurnsCatchUp(count: Int, reasons: [String], since: Date, calendar: Calendar) -> String {
        "\(count) \(count == 1 ? "turn" : "turns") failed since \(clock(since, calendar)): \(list(reasons))"
    }
    public static func failedTurnsCleared(quietMinutes: Int) -> String { "No failed turns for \(quietMinutes) minutes." }
    /// Spec section 6.2's error codes in plain words; other codes display raw (plan call).
    public static func failedTurnReason(code: String) -> String {
        switch code {
        case "serverOverloaded": "model at capacity"
        case "cyberPolicy": "blocked by policy"
        default: code
        }
    }

    // MARK: Disconnects

    public static func disconnectsFired(count: Int, windowMinutes: Int) -> String {
        "\(count) disconnect or retry events in the last \(windowMinutes) minutes."
    }
    public static func disconnectsCatchUp(since: Date, calendar: Calendar) -> String { "Frequent disconnects since \(clock(since, calendar))." }
    public static let disconnectsCleared = "Connection is steady again."
    public static func connectionGap(from: Date, to: Date, calendar: Calendar) -> String {
        "Connection history incomplete from \(clock(from, calendar)) to \(clock(to, calendar))."
    }

    // MARK: Provider status

    public static func incidentFired(source: String, name: String) -> String { "\(source): \(name)." }
    public static func incidentCatchUp(source: String, name: String, since: Date, calendar: Calendar) -> String {
        "\(source): \(name). Open since \(clock(since, calendar))."
    }
    public static func incidentEscalated(source: String, name: String) -> String { "\(source): \(name) is now an outage." }
    public static func incidentCleared(source: String, name: String) -> String { "\(source) resolved: \(name)." }
    public static func statusPost(source: String, title: String) -> String { "\(source) posted: \(title)." }
    /// Spec section 10's unavailable state.
    public static func statusUnavailable(source: String, since: Date, calendar: Calendar) -> String {
        "\(source) status unavailable since \(clock(since, calendar))."
    }
    public static let componentMissing = "(not on the status page now)"

    // MARK: Usage limit

    public static func usageLimitFired(percent: Int, windowMinutes: Int, resets: Date?, calendar: Calendar) -> String {
        let used = "\(percent)% of the \(windowMinutes)-minute limit used."
        guard let resets else { return used }
        return "\(used) Resets at \(clock(resets, calendar))."
    }
    public static let usageLimitCleared = "Usage is back under the limit you set."

    // MARK: Baseline (spec sections 7.1 and 8)

    public static let thinData = "Not enough recent responses to judge speed"
    public static func noBucketHistory(bucket: InputBucket) -> String { "Not enough history yet for \(bucket.label) prompts" }
    public static func learning(days: Int, of: Int) -> String { "Learning usual: \(days) of \(of) days" }
    public static func shiftPrompt(model: String, percent: Int, days: Int, direction: Direction) -> String {
        "\(model) has been about \(percent)% \(direction.rawValue) than usual for \(days) days. Accept as usual?"
    }
    /// Spec section 8's acceptance confirmation, with the signed percentage change.
    public static func acceptance(model: String, percent: Int) -> String {
        if percent == 0 { return "\(model)'s usual speed is unchanged." }
        return "\(model)'s usual speed is now \(abs(percent))% \(percent < 0 ? "lower" : "higher") than before."
    }
    /// The Undo event for an acceptance (controller ruling R11; not a Copy-table row).
    public static func baselineRestored(model: String) -> String { "Baseline restored for \(model)." }
    public static func drift(percent: Int, direction: Direction, acceptedOn: LocalDay) -> String {
        "Usual is \(percent)% \(direction.rawValue) than when you accepted it on \(monthDay(acceptedOn))."
    }
    public static func undoEarlierAcceptanceConfirmation(model: String) -> String {
        "Restore \(model)'s baseline from before this acceptance? Later acceptances for this model will also be undone."
    }

    // MARK: Settings and collector management

    public static func intervalError(min: Int, max: Int) -> String { "Choose an interval from \(min) to \(max) minutes" }
    public static let clearBandError = "The clear band must be stricter than the trigger"
    public static func invalidRuleParameter(field: String) -> String { "Choose a valid value for \(field)." }
    public static let notInAppBundle = "Run Telltale from Telltale.app to turn on the collector"
    public static let wrongBundle = "This copy of Telltale can't run the collector"
    public static func launchctlError(command: String, status: Int32, stderr: String) -> String {
        "Collector command \(command) failed (\(status)): \(stderr)"
    }
    /// The caller passes spec section 8's cold-start lookback.
    public static func rebuildConfirmation(days: Int) -> String {
        "Telltale will re-read the last \(days) days. Your accepted baselines are kept."
    }
    public static let collectorNotBuilt = "Collector not built yet"
    /// Spec section 9.3's footer while the collector is off by choice.
    public static let collectorOff = "Collector off. Turn it on to keep watching."

    // MARK: Collector health (spec sections 6.5, 7.4 and 9.3)

    /// Spec section 6.5's format-problem wording.
    public static func formatProblem(since: Date, calendar: Calendar) -> String {
        "Codex changed its log format. Telltale can't read responses since \(clock(since, calendar))."
    }
    public static let collectorNotLoaded = "Telltale's collector isn't loaded. Open the Collector view to turn it back on."
    /// `reason` is the run record's detail; a closing period is dropped so the sentence ends once.
    public static func collectorFailing(at: Date, reason: String, next: Date, calendar: Calendar) -> String {
        var reason = reason.trimmingCharacters(in: .whitespacesAndNewlines)
        if reason.hasSuffix(".") { reason.removeLast() }
        return "The collector failed at \(clock(at, calendar)): \(reason). Next try \(clock(next, calendar))."
    }
    public static func collectorOverdue(since: Date, calendar: Calendar) -> String {
        "The collector hasn't run since \(clock(since, calendar))."
    }
    public static let collectorRecovered = "Telltale's collector is running again."

    // MARK: Panel

    /// Spec section 9.1's quiet panel; also the quiet glyph's accessibility text.
    public static let nothingToReport = "Nothing to report."
    public static let waitingForFirstRun = "Waiting for the collector's first run."
    public static func databaseUnavailable(reason: String) -> String {
        "Telltale can't read its database: \(reason). Retrying automatically."
    }
    /// The panel header's last-successful-run time (visual doc's panel wireframe; not a Copy-table row).
    public static func checked(at date: Date, calendar: Calendar) -> String { "Checked \(clock(date, calendar))" }
    /// The footer while the collector is healthy (visual doc's panel wireframe; not a Copy-table row).
    public static func collectorRunning(minutes: Int) -> String { "Collector running, every \(minutes) min" }

    // MARK: Dashboard (spec sections 9.2 and 9.3; not Copy-table rows)

    /// Spec section 8's usual, as the speed section explains it (the mockup's sentence, with the
    /// whole baseline key).
    public static let usualExplanation =
        "Usual is the median of the last 14 active days for the same prompt size, effort and service tier, leaving out flagged hours."
    /// An episode that ended silently (spec section 7.2's idle end), in the Events list.
    public static let episodeEndedIdle = "Ended with no recent responses to judge."
    /// An episode its rule's switch ended (ruling R13), in the Events list.
    public static let episodeEndedRuleOff = "Ended because the rule was turned off."
    /// A streak of failed collector runs in the Events list; `reason` is the last run's detail.
    public static func collectorRunsFailed(count: Int, from: Date, to: Date, reason: String, calendar: Calendar) -> String {
        var reason = reason.trimmingCharacters(in: .whitespacesAndNewlines)
        if reason.hasSuffix(".") { reason.removeLast() }
        if reason.isEmpty { reason = "no detail recorded" }
        return count == 1
            ? "The collector run at \(clock(from, calendar)) failed: \(reason)."
            : "\(count) collector runs failed from \(clock(from, calendar)) to \(clock(to, calendar)): \(reason)."
    }
    /// Ruling R24: a copy that isn't the installed app shows the collector but doesn't manage it.
    public static let collectorManagedByInstalledCopy = "Only Telltale in Applications can turn the collector on or off, or repair it."
    /// The collector view's schedule line (the mockup's "Every 5 minutes, also at login").
    public static func collectorSchedule(minutes: Int) -> String {
        minutes == 1 ? "Every minute, also at login" : "Every \(minutes) minutes, also at login"
    }
    /// The collector view's last-run line: "12:40, failed after 0.4 s".
    public static func collectorLastRun(at start: Date, outcome: RunOutcome, seconds: TimeInterval?, calendar: Calendar) -> String {
        let duration = seconds.map { String(format: "%.1f s", max(0, $0)) }
        let detail = switch (outcome, duration) {
        case (.succeeded, let duration?): "succeeded in \(duration)"
        case (.failed, let duration?): "failed after \(duration)"
        case (.running, _): "running"
        default: outcome.rawValue
        }
        return "\(clock(start, calendar)), \(detail)"
    }
    /// The sidebar entry of a provider whose source isn't set up (spec section 9.2).
    public static let notSetUp = "Not set up"
    /// The sidebar entry of a set-up provider with no stored responses yet.
    public static let noResponsesYet = "No responses yet"

    // MARK: Notifications

    public static let notificationCheckTitle = "Telltale notification check"
    public static func notificationCheckBody(mode: String) -> String { "Notification check: \(mode)" }
    /// Reported when a check's request posted but never appeared among delivered notifications.
    public static func notificationCheckNotDelivered(seconds: Int) -> String {
        "The notification was posted but not delivered within \(seconds) seconds."
    }
    public static let testNotificationTitle = notificationCheckTitle
    public static let testNotificationBody = "This is a test notification from Telltale. Click to open the panel."

    public static let notificationsDenied = "Notifications are off. Allow Telltale in System Settings, then retry notifications."
    // Port: brew_version/Sources/BrewVersion/UserNotifier.swift, lastError, fbd3e03.
    public static let notificationRetryPending = "A notification is waiting to be retried. Retry notifications."
    public static func notificationAuthorizationFailure(error: any Error) -> String {
        failureMessage("Notification authorization failed", error: error)
    }
    public static func notificationPostFailure(error: any Error) -> String {
        failureMessage("Couldn't post notification", error: error)
    }

    // MARK: Formatting

    /// `HH:mm` in `calendar`'s time zone.
    public static func clock(_ date: Date, _ calendar: Calendar) -> String {
        let parts = calendar.dateComponents([.hour, .minute], from: date)
        return String(format: "%02ld:%02ld", parts.hour ?? 0, parts.minute ?? 0)
    }

    /// "Oct 12": English month abbreviations regardless of locale, like the rest of the copy.
    private static func monthDay(_ day: LocalDay) -> String {
        let months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        let month = (1...12).contains(day.month) ? months[day.month - 1] : String(day.month)
        return "\(month) \(day.day)"
    }

    /// 300000 is "300k" and 1000000 is "1M"; other values are written in full.
    private static func tokenCount(_ tokens: Int) -> String {
        if tokens > 0, tokens.isMultiple(of: 1_000_000) { return "\(tokens / 1_000_000)M" }
        if tokens > 0, tokens.isMultiple(of: 1_000) { return "\(tokens / 1_000)k" }
        return String(tokens)
    }

    /// Distinct items in first-seen order, comma-separated.
    private static func list(_ items: [String]) -> String {
        var seen: Set<String> = []
        return items.filter { seen.insert($0).inserted }.joined(separator: ", ")
    }

    // Port: brew_version/Sources/BrewVersion/UserNotifier.swift, failureMessage, fbd3e03.
    private static func failureMessage(_ context: String, error: any Error) -> String {
        let detail = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        let separator = detail.last.map { ".!?…。！？".contains($0) } == true ? " " : ". "
        return "\(context): \(detail)\(separator)Retry notifications."
    }
}
