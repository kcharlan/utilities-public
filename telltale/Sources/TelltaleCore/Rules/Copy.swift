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
        "\(model) has been \(percent)% slower than usual for prompts this size since \(clock(since, calendar))."
    }
    public static func slowerEscalated(model: String, percent: Int) -> String { "\(model) is now \(percent)% slower than usual for prompts this size." }
    /// Spec section 7.2's clear notice.
    public static func speedCleared(model: String) -> String { "\(model) is back to usual speed." }
    public static func fasterFired(model: String, percent: Int, since: Date, calendar: Calendar) -> String {
        "\(model) is \(percent)% faster than usual for prompts this size. Check that output isn't shallower. Since \(clock(since, calendar))."
    }
    public static func fasterCatchUp(model: String, percent: Int, since: Date, calendar: Calendar) -> String {
        "\(model) has been \(percent)% faster than usual for prompts this size since \(clock(since, calendar))."
    }

    public static func slowerReversed(model: String, percent: Int, since: Date, calendar: Calendar) -> String {
        "\(model) is \(percent)% slower than usual for prompts this size, after running faster. Since \(clock(since, calendar))."
    }
    public static func fasterReversed(model: String, percent: Int, since: Date, calendar: Calendar) -> String {
        "\(model) is \(percent)% faster than usual for prompts this size, after running slower. Check that output isn't shallower. Since \(clock(since, calendar))."
    }
    public static func slowerOpen(model: String, percent: Int, since: Date, calendar: Calendar) -> String {
        "\(model) has been up to \(percent)% slower than usual for prompts this size since \(clock(since, calendar))."
    }
    public static func fasterOpen(model: String, percent: Int, since: Date, calendar: Calendar) -> String {
        "\(model) has been up to \(percent)% faster than usual for prompts this size since \(clock(since, calendar)). Check that output isn't shallower."
    }

    // MARK: Large prompts

    /// The visual doc's panel alert, with the inclusive threshold ("at least").
    public static func largePromptsFired(count: Int, of: Int, tokens: Int) -> String {
        "\(count) of your last \(of) prompts were at least \(tokenCount(tokens)) tokens. A fresh session would speed things up."
    }
    public static let largePromptsCleared = "Prompt sizes are back to usual."

    // MARK: Failed turns

    public static let acknowledge = "Acknowledge"
    public static let acknowledgeAll = "Acknowledge all"
    public static let markAsNew = "Mark as new"
    public static func acknowledged(at: Date, calendar: Calendar) -> String { "Acknowledged \(clock(at, calendar))" }
    private static func reasonSuffix(_ reasons: [String]) -> String { reasons.isEmpty ? "" : ": \(list(reasons))" }
    public static func failedTurnsOpen(source: String, noun: String, count: Int, reasons: [String], since: Date, calendar: Calendar) -> String {
        "\(source): \(count) \(noun)\(count == 1 ? "" : "s") failed since \(clock(since, calendar))\(reasonSuffix(reasons))"
    }
    public static func failedTurnsBeyondAcknowledged(source: String, noun: String, count: Int, reasons: [String], acknowledged: Date, calendar: Calendar) -> String {
        "\(source): \(count) more \(noun)\(count == 1 ? "" : "s") failed than you acknowledged at \(clock(acknowledged, calendar))\(reasonSuffix(reasons))"
    }
    public static func failedTurnsTotal(count: Int, since: Date, calendar: Calendar) -> String { "\(count) failed since \(clock(since, calendar))" }

    /// `reasons` are display reasons (`failedTurnReason`); repeats are listed once.
    public static func failedTurns(count: Int, reasons: [String]) -> String {
        "\(count) \(count == 1 ? "turn" : "turns") failed: \(list(reasons))"
    }
    public static func failedTurns(source: String, noun: String, count: Int, reasons: [String]) -> String {
        "\(source): \(count) \(noun)\(count == 1 ? "" : "s") failed: \(list(reasons))"
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
        case "overloaded": "model overloaded"
        case "serverError": "server error"
        case "timeout": "request timed out"
        case "connection": "connection failed"
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
    public static func rebuildConfirmation(days: Int, providers: [String]) -> String {
        "Telltale will re-read the last \(days) days of logs for \(providers.joined(separator: ", ")). Your accepted baselines are kept."
    }
    public static func providerState(_ state: ProviderSummary.State, name: String, calendar: Calendar) -> String {
        switch state {
        case .normal: "Reading normally."
        case .notSetUp(let reason): reason
        case .formatProblem(let since): formatProblem(source: name, since: since, calendar: calendar)
        case .readProblem(let since): readProblem(source: name, since: since, calendar: calendar)
        case .backfilling(let started): "Reading \(CollectorRun.lookbackDays) days of history, started \(clock(started, calendar)). No notifications are sent for it."
        case .rebuildRequested(let at): "Rebuild requested at \(clock(at, calendar)). Waiting for the collector."
        }
    }
    public static func providerDate(_ date: Date, calendar: Calendar) -> String {
        let parts = calendar.dateComponents([.year, .month, .day], from: date)
        let months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return String(format: "%@ %02d, %04d", months[max(0, min(11, (parts.month ?? 1) - 1))], parts.day ?? 1, parts.year ?? 0)
    }
    public static func providerVersion(name: String, version: String, seen: Date, calendar: Calendar) -> String {
        "\(name) \(version) last seen at \(clock(seen, calendar))."
    }
    public static func providerHistory(oldest: Date, finished: Date?, calendar: Calendar) -> String {
        "History from \(providerDate(oldest, calendar: calendar))." + (finished.map { " Read in full \(providerDate($0, calendar: calendar))." } ?? "")
    }
    public static func providerRebuildConfirmation(name: String, others: [String], days: Int, cutoff: Date, calendar: Calendar) -> String {
        let other = others.isEmpty ? "" : " \(others.joined(separator: ", ")) \(others.count == 1 ? "isn't" : "aren't") touched and \(others.count == 1 ? "keeps" : "keep") watching."
        return "Telltale will re-read the last \(days) days of \(name) logs. \(name) speed history before \(providerDate(cutoff, calendar: calendar)) is removed.\(other) Accepted baselines are kept, and no notifications are sent for the history it reads."
    }
    public static func providerAdded(name: String, days: Int) -> String {
        "Telltale now watches \(name). It read \(days) days of history and sent no notifications for it."
    }
    public static func historyRebuilt(name: String, days: Int) -> String {
        "\(name) history rebuilt from \(days) days of logs."
    }
    public static let collectorNotBuilt = "Collector not built yet"
    /// Spec section 9.3's footer while the collector is off by choice.
    public static let collectorOff = "Collector off. Turn it on to keep watching."

    // MARK: Collector health (spec sections 6.5, 7.4 and 9.3)

    /// Spec section 6.5's format-problem wording.
    public static func formatProblem(since: Date, calendar: Calendar) -> String {
        "Codex changed its log format. Telltale can't read responses since \(clock(since, calendar))."
    }
    public static func formatProblem(source: String, since: Date, calendar: Calendar) -> String {
        "\(source) changed its log format. Telltale can't read \(source) responses since \(clock(since, calendar))."
    }
    public static func readProblem(source: String, since: Date, calendar: Calendar) -> String {
        "Telltale can't read \(source)'s logs since \(clock(since, calendar)). Open the Collector view to see the error."
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
    /// Ruling R30: before the first run there is no database to store the off choice in.
    public static let collectorTurnOffAfterFirstRun = "You can turn the collector off after its first run."
    /// Settings before the first run: there is no database to store a change in yet (ruling R27).
    public static let settingsAfterFirstRun = "You can change settings after the collector's first run."
    public static let settingsAfterUpgrade = "Telltale is updating its data. Try again after the collector's next run."

    public static func compactionsFired(count: Int, windowMinutes: Int, blocked: TimeInterval?) -> String {
        var result = "\(count) automatic compactions in the last \(windowMinutes) minutes. Fresh sessions or subagents would keep more context."
        if let blocked {
            let seconds = Int(blocked.rounded())
            let duration = seconds >= 60 ? "\(seconds / 60) min \(seconds % 60) s" : "\(seconds) s"
            result += " They held sessions for \(duration)."
        }
        return result
    }

    public static func compactionsCleared(windowMinutes: Int) -> String {
        "No automatic compactions in the last \(windowMinutes) minutes."
    }
    /// Settings that change launchd or login-item state, in a copy that isn't the installed app (R24).
    public static let settingsInstalledCopyOnly = "Only Telltale in Applications can change this."
    /// Ruling R16 in Settings: the stored rules don't decode or validate, so the defaults apply.
    public static let storedRulesUnusable = "The saved rules couldn't be used, so Telltale is using the defaults shown here."
    /// Settings' interval, committed while the collector view runs another change; the draft stays.
    public static let collectorChangeRunning = "Another collector change is still running. Try again in a moment."
    /// A collector change whose launchd step failed after its setting was stored, and whose setting
    /// couldn't be put back either (final review M8).
    public static func collectorChangePartial(reason: String, restoreReason: String) -> String {
        "\(reason) The setting couldn't be put back (\(restoreReason)), so the change is only partly applied."
    }
    /// Ruling R16's reason when the stored rules no longer decode (the collector log and Settings).
    public static let storedRulesUndecodable = "The stored rules couldn't be read."
    /// The watched-components checklist before the collector has stored the status page's list.
    public static let componentsNotLoaded = "The status page's components appear here after the collector reads it."
    /// The collector view's schedule line (the mockup's "Every 5 minutes, also at login").
    public static func collectorSchedule(minutes: Int) -> String {
        minutes == 1 ? "Every minute, also at login" : "Every \(minutes) minutes, also at login"
    }
    /// The collector view's last-run line: "12:40, failed after 0.4 s". A `running` record past the
    /// schedule limit (`CollectorHealth.isStranded`) reads "12:40, interrupted".
    public static func collectorLastRun(
        at start: Date, outcome: RunOutcome, seconds: TimeInterval?, calendar: Calendar, stranded: Bool = false
    ) -> String {
        let duration = seconds.map { String(format: "%.1f s", max(0, $0)) }
        let detail = switch (outcome, duration) {
        case (.succeeded, let duration?): "succeeded in \(duration)"
        case (.failed, let duration?): "failed after \(duration)"
        case (.running, _) where stranded: CollectorRun.interruptedDetail
        case (.running, _): "running"
        default: outcome.rawValue
        }
        return "\(clock(start, calendar)), \(detail)"
    }
    /// The sidebar entry of a provider whose source isn't set up (spec section 9.2).
    public static let notSetUp = "Not set up"
    /// The sidebar entry of a set-up provider with no stored responses yet.
    public static let noResponsesYet = "No responses yet"
    /// The sidebar entry of a provider whose models all last responded before the sidebar window.
    public static let noRecentModels = "No responses in the last \(Int(ModelDetail.sidebarWindow / 86_400)) days"

    // MARK: Notifications

    /// A banner's title says what happened before anything else, since a banner can't be colored and
    /// its body often says it last. An alert leads with the lamp that lit, in that lamp's color.
    public static func alertTitle(_ rule: String, lamp: LampColor) -> String {
        let glyph = switch lamp {
        case .red: "🔴"
        case .amber: "🟠"
        case .blue: "🔵"
        }
        return "\(glyph) \(rule)"
    }
    /// A clear leads with a colorless check and the word: dark cockpit, no green "OK" (visual design
    /// doc), and a different shape, not only a different color, from an alert's lamp.
    public static func clearedTitle(_ rule: String) -> String { "✓ Cleared: \(rule)" }

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

    public static func arrival(name: String, days: Int, readyModels: [String]) -> String {
        let usual = readyModels.isEmpty ? "usual speeds are still being learned" : "usual speeds are ready for \(list(readyModels))"
        return "Telltale now watches \(name). It read \(days) days of history; \(usual)."
    }
    public static let versionLine = "\(TelltaleRelease.displayName) \(TelltaleRelease.version)"
    public static func arrivalIdle(name: String, days: Int) -> String {
        let window = Int(ModelDetail.sidebarWindow / 86_400)
        return "Telltale now watches \(name). It read \(days) days of history; none of its models responded in the last \(window) days."
    }

    // Port: brew_version/Sources/BrewVersion/UserNotifier.swift, failureMessage, fbd3e03.
    private static func failureMessage(_ context: String, error: any Error) -> String {
        let detail = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        let separator = detail.last.map { ".!?…。！？".contains($0) } == true ? " " : ". "
        return "\(context): \(detail)\(separator)Retry notifications."
    }
}
