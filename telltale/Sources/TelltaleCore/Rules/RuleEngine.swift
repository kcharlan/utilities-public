import Foundation

/// The rules the collector evaluates (spec section 7.4). Collector health is the UI's (Task 10).
/// Raw values are stored in `episodes.rule` and `rule_state.rule`; the speed rules' values are
/// `EpisodeRow.slowerRule` and `EpisodeRow.fasterRule`.
public enum RuleID: String, Sendable, Hashable, Codable, CaseIterable {
    case slower
    case faster
    case largePrompts
    case failedTurns
    case disconnects
    case incident
    case usageLimit

    /// The rule's name in spec section 7.4's table, used as notification and event titles.
    public var title: String {
        switch self {
        case .slower: "Slower than usual"
        case .faster: "Faster than usual"
        case .largePrompts: "Large prompts"
        case .failedTurns: "Failed turns"
        case .disconnects: "Disconnects"
        case .incident: "Provider incident"
        case .usageLimit: "Usage limit"
        }
    }

    public static func speed(_ direction: Direction) -> RuleID { direction == .slower ? .slower : .faster }
}

/// A status source as the incident rule sees it. `providers` are the usage providers whose
/// recently used models its incident titles are matched against.
public struct RuleStatusSource: Sendable, Equatable {
    public var id: String
    public var displayName: String
    public var providers: [ProviderID]

    public init(id: String, displayName: String, providers: [ProviderID]) {
        self.id = id
        self.displayName = displayName
        self.providers = providers
    }
}

/// Something a rule did at an evaluation point: a transition, or failed turns counted while the
/// failed-turn episode is open (`transition` nil). `provider` is a usage provider id, or a status
/// source id for the incident rule; `scope` is a model, an incident id or `*`.
///
/// `message` is the event and fresh-notice wording; `catchUpMessage` is spec section 7.3's
/// wording for an episode still open after a gap (nil when the rule has none).
public struct RuleOutcome: Sendable, Equatable {
    public var at: Date
    public var rule: RuleID
    public var provider: String
    public var scope: String
    public var transition: Transition?
    public var failures: [FailedTurnRecord]
    public var episodeID: Int64
    public var title: String
    public var message: String
    public var catchUpMessage: String?

    public init(
        at: Date, rule: RuleID, provider: String, scope: String, transition: Transition?, failures: [FailedTurnRecord],
        episodeID: Int64, title: String, message: String, catchUpMessage: String?
    ) {
        self.at = at
        self.rule = rule
        self.provider = provider
        self.scope = scope
        self.transition = transition
        self.failures = failures
        self.episodeID = episodeID
        self.title = title
        self.message = message
        self.catchUpMessage = catchUpMessage
    }
}

/// Spec section 7's rule engine. It evaluates points in order and writes everything as
/// evaluated at the time: evaluation points with the usual in effect, episodes, an event per
/// transition (idle ends excepted: they are silent and have no wording) and each rule's state.
/// Notifications are `NotificationPolicy`'s job.
///
/// Plan calls where the spec leaves detail open:
/// - Scopes: speed and large prompts per model, incidents per incident id, failed turns,
///   disconnects and the usage limit per provider (`*`).
/// - Worst values: the extreme speed index, the peak large-prompt or disconnect count, the
///   episode's total failed turns, the peak impact rank for incidents (0 none, 1 degraded or
///   other, 2 partial outage, 3 full outage), and the peak percentage for the usage limit.
/// - Non-speed onsets: the earliest large prompt in the sample (after an idle end, the earliest
///   after it), the earliest counted failure
///   or disconnect, the incident's publication and the usage snapshot's time.
/// - Speed idleness counts responses with a throughput; large-prompt idleness counts any
///   response. While idle, a rule isn't judged, so its unchanged sample can't refire.
/// - After a large-prompt episode ends idle, only a large prompt ending after the idle end can
///   fire the next one; the old ones still in the last-`of` sample count toward it but can't
///   fire it alone.
/// - A failed turn counts at the first point evaluated at or after its completion (or start),
///   however late it was ingested. A connection event counts only while inside the window.
/// - A disconnect point whose window overlaps a recorded connection-history gap is unknown.
/// - The usage limit is unknown before its latest snapshot and clear once that snapshot's
///   window has reset. It has no lamp; its episodes are amber.
///
/// Not thread-safe: one engine per `Store`, sharing that store's `BaselineEngine`.
public final class RuleEngine {
    /// Spec section 7.2's idle end.
    public static let idleMinutes = 120
    /// Spec section 7.4: an incident title must name a model used in this many hours.
    public static let titleLookbackHours = 24

    fileprivate let store: Store
    fileprivate let baseline: BaselineEngine
    fileprivate let calendar: Calendar
    fileprivate let naming: [ProviderID: any ModelNaming]

    public init(store: Store, baseline: BaselineEngine, calendar: Calendar, naming: [ProviderID: any ModelNaming]) {
        self.store = store
        self.baseline = baseline
        self.calendar = calendar
        self.naming = naming
    }

    /// Evaluates `points` after the last evaluated point, oldest first, and returns what
    /// happened in order. Writes go through `Store.transaction`, so they join the caller's
    /// transaction when there is one. A disabled rule isn't evaluated and writes nothing, except
    /// that at the first point evaluated while it is off its open episodes end silently with
    /// `ruleDisabled` and its state is dropped (no event, no outcome). While
    /// `statusAvailable` is false the incident rule isn't evaluated at all (spec section 10).
    @discardableResult
    public func evaluate(
        points: [Date], providers: [ProviderID], statusSources: [RuleStatusSource], settings: RuleSettings,
        watchedComponents: [String], statusAvailable: Bool
    ) throws -> [RuleOutcome] {
        let last = try store.lastEvaluatedPoint()
        let pending = Set(points).filter { point in last.map { point > $0 } ?? true }.sorted()
        guard let first = pending.first, let final = pending.last else { return [] }
        do {
            return try store.transaction {
                let pass = try EvaluationPass(
                    engine: self, settings: settings, first: first, final: final, providers: providers,
                    statusSources: statusAvailable && settings.incident.enabled ? statusSources : [],
                    watchedComponents: Set(watchedComponents))
                for point in pending { try pass.evaluate(at: point) }
                try pass.finish()
                try store.setLastEvaluatedPoint(final)
                return pass.outcomes
            }
        } catch {
            // Tables cached while the rolled-back episodes existed are no longer true.
            baseline.discardCache()
            throw error
        }
    }
}

// MARK: - One evaluation pass

private struct StateKey: Hashable {
    var rule: RuleID
    var provider: String
    var scope: String
}

/// What `rule_state` holds for one rule and scope.
private struct ScopeState: Codable {
    var machine: EpisodeMachine
    var episodeID: Int64?
    /// The most extreme value since the current streak began: the episode's worst value.
    var extreme: Double?
    /// Failed turns: the point at which the latest failure was counted.
    var lastFailureAt: Date?
    /// Large prompts: when the last episode ended idle. Until the sample holds no large prompt
    /// from before it, only a large prompt after it can fire a new episode (spec section 7.2:
    /// the next activity starts fresh).
    var idleEndedAt: Date?
}

/// How an episode's worst value accumulates.
private enum Worst {
    case lowest, highest, total

    func combine(_ old: Double?, _ value: Double) -> Double {
        guard let old else { return value }
        switch self {
        case .lowest: return min(old, value)
        case .highest: return max(old, value)
        case .total: return old + value
        }
    }
}

/// What a step needs beyond its conditions.
private struct StepContext {
    var direction: Direction?
    /// Replaces the machine's onset (non-speed rules).
    var onset: Date?
    var link: URL?
    var failures: [FailedTurnRecord] = []
    /// The event or fresh-notice wording and the catch-up wording for a transition, given the
    /// episode's onset.
    var messages: (Transition, Date) -> (message: String, catchUp: String?)
}

/// One model's responses for a pass, ordered by end time.
private struct Series {
    let responses: [ResponseRecord]
    private let ends: [Date]
    private let throughputEnds: [Date]

    init(_ responses: [ResponseRecord]) {
        self.responses = responses
        ends = responses.map(\.end)
        throughputEnds = responses.filter { $0.throughput != nil }.map(\.end)
    }

    /// Whether a response ends in `(start, end]`.
    func hasResponse(after start: Date, through end: Date, withThroughput: Bool) -> Bool {
        let list = withThroughput ? throughputEnds : ends
        let index = Self.firstIndex(in: list, after: start)
        return index < list.count && list[index] <= end
    }

    /// Responses ending in `(start, end]`.
    func window(after start: Date, through end: Date) -> ArraySlice<ResponseRecord> {
        responses[Self.firstIndex(in: ends, after: start)..<Self.firstIndex(in: ends, after: end)]
    }

    /// Responses ending at or before `end`.
    func through(_ end: Date) -> ArraySlice<ResponseRecord> { responses[..<Self.firstIndex(in: ends, after: end)] }

    /// The index of the first element later than `date`.
    private static func firstIndex(in list: [Date], after date: Date) -> Int {
        var low = 0
        var high = list.count
        while low < high {
            let middle = (low + high) / 2
            if list[middle] <= date { low = middle + 1 } else { high = middle }
        }
        return low
    }
}

private struct SourceIncidents {
    var source: RuleStatusSource
    var watchedIDs: Set<String>
    var incidents: [(record: IncidentRecord, resolvedAt: Date?)]
}

private final class EvaluationPass {
    private let store: Store
    private let baseline: BaselineEngine
    private let calendar: Calendar
    private let naming: [ProviderID: any ModelNaming]
    private let settings: RuleSettings
    private let providers: [ProviderID]
    /// The first instant preloaded responses cover: a day before the first point, for incident titles.
    private let preloadStart: Date

    private(set) var outcomes: [RuleOutcome] = []
    private var states: [StateKey: ScopeState] = [:]
    private var storedKeys: Set<StateKey> = []
    private var touchedKeys: Set<StateKey> = []
    private var openEpisodes: [Int64: EpisodeRow] = [:]
    private var worstChanged: Set<Int64> = []
    private var points: [EvalPointRow] = []
    private var series: [ProviderID: [(model: String, series: Series)]] = [:]
    private var olderResponses: [String: [ResponseRecord]] = [:]
    private var failures: [ProviderID: [FailedTurnRecord]] = [:]
    private var connections: [ProviderID: [ConnectionEventRecord]] = [:]
    private var connectionGaps: [ProviderID: [DateInterval]] = [:]
    /// Whether open episodes of disabled rules have been ended this pass.
    private var disabledRulesSettled = false
    private var usage: [ProviderID: UsageLimitSnapshot] = [:]
    private var sources: [SourceIncidents] = []

    init(
        engine: RuleEngine, settings: RuleSettings, first: Date, final: Date, providers: [ProviderID],
        statusSources: [RuleStatusSource], watchedComponents: Set<String>
    ) throws {
        store = engine.store
        baseline = engine.baseline
        calendar = engine.calendar
        naming = engine.naming
        self.settings = settings
        self.providers = providers
        preloadStart = first.addingTimeInterval(-TimeInterval(RuleEngine.titleLookbackHours * 3_600))

        for rule in RuleID.allCases {
            for row in try store.ruleStates(rule: rule.rawValue) {
                let key = StateKey(rule: rule, provider: row.provider, scope: row.scope)
                var state: ScopeState
                do {
                    state = try StoreJSON.decode(ScopeState.self, from: row.json)
                } catch {
                    throw StoreError.invalidData("Unreadable rule state for \(rule.rawValue) \(row.provider) \(row.scope)")
                }
                // Edited durations apply to streaks in progress.
                let current = Self.machine(for: rule, settings: settings)
                state.machine.firePoints = current.firePoints
                state.machine.clearPoints = current.clearPoints
                state.machine.windowMinutes = current.windowMinutes
                states[key] = state
                storedKeys.insert(key)
            }
        }
        for episode in try store.openEpisodes() {
            if let id = episode.id { openEpisodes[id] = episode }
        }

        let failed = settings.failedTurns.enabled ? try store.unevaluatedFailedTurns(through: final) : []
        for provider in providers {
            let modelRules: Set<RuleID> = [.slower, .faster, .largePrompts]
            let stated = Set(states.keys.filter { $0.provider == provider.rawValue && modelRules.contains($0.rule) }.map(\.scope))
            var list: [(model: String, series: Series)] = []
            for model in Set(try store.models(provider: provider)).union(stated).sorted() {
                let responses = try store.responses(provider: provider, model: model, endingIn: preloadStart...final)
                if !responses.isEmpty || stated.contains(model) { list.append((model, Series(responses))) }
            }
            series[provider] = list
            failures[provider] = failed.filter { $0.provider == provider }
            if settings.disconnects.enabled {
                let window = TimeInterval(settings.disconnects.windowMinutes * 60)
                connections[provider] = try store.connectionEvents(provider: provider, in: first.addingTimeInterval(-window)...final)
                    .filter { $0.kind != .reconnect }
                connectionGaps[provider] = try store.connectionGaps(
                    provider: provider, overlapping: DateInterval(start: first.addingTimeInterval(-window), end: final))
            }
            if settings.usageLimit.enabled { usage[provider] = try store.usageLimit(provider: provider) }
        }

        for source in statusSources {
            let watchedIDs = Set(try store.components(source: source.id).filter { watchedComponents.contains($0.name) }.map(\.id))
            let incidents = try store.incidents(source: source.id, overlapping: DateInterval(start: .distantPast, end: final))
                .map { (record: $0, resolvedAt: $0.resolvedAt) }
                .filter { incident in
                    incident.resolvedAt.map { $0 > first } ?? true
                        || states[StateKey(rule: .incident, provider: source.id, scope: incident.record.id)] != nil
                }
            sources.append(SourceIncidents(source: source, watchedIDs: watchedIDs, incidents: incidents))
        }
    }

    func evaluate(at point: Date) throws {
        if !disabledRulesSettled {
            try endDisabledRuleEpisodes(at: point)
            disabledRulesSettled = true
        }
        for provider in providers {
            for (model, series) in series[provider] ?? [] {
                try speed(provider: provider, model: model, series: series, at: point)
                try largePrompts(provider: provider, model: model, series: series, at: point)
            }
            try failedTurns(provider: provider, at: point)
            try disconnects(provider: provider, at: point)
            try usageLimit(provider: provider, at: point)
        }
        for source in sources { try incidents(source, at: point) }
    }

    /// Writes worst values, rule state and evaluation points.
    func finish() throws {
        for id in worstChanged.sorted() {
            if let episode = openEpisodes[id] { try store.updateEpisode(episode) }
        }
        for key in touchedKeys.sorted(by: { ($0.rule.rawValue, $0.provider, $0.scope) < ($1.rule.rawValue, $1.provider, $1.scope) }) {
            if let state = states[key] {
                try store.setRuleState(rule: key.rule.rawValue, provider: key.provider, scope: key.scope, json: try StoreJSON.encode(state))
            } else if storedKeys.contains(key) {
                try store.deleteRuleState(rule: key.rule.rawValue, provider: key.provider, scope: key.scope)
            }
        }
        try store.insertEvalPoints(points)
    }

    /// Ends every open episode of a disabled rule at `point` with `ruleDisabled` and drops that
    /// rule's state. Silent: no event and no outcome, so nothing notifies. Otherwise an open speed
    /// episode would keep excluding the model's responses from usual for as long as the rule
    /// stays off, and its lamp would stay lit.
    private func endDisabledRuleEpisodes(at point: Date) throws {
        let disabled = Set(RuleID.allCases.filter { !settings.notifications(for: $0).enabled })
        guard !disabled.isEmpty else { return }
        for (id, var episode) in openEpisodes.sorted(by: { $0.key < $1.key }) {
            guard let rule = RuleID(rawValue: episode.rule), disabled.contains(rule) else { continue }
            let key = StateKey(rule: rule, provider: episode.provider, scope: episode.scope)
            episode.endedAt = point
            episode.endReason = EpisodeRow.EndReason.ruleDisabled
            if states[key]?.episodeID == id, let extreme = states[key]?.extreme { episode.worstValue = extreme }
            try store.updateEpisode(episode)
            openEpisodes[id] = nil
            worstChanged.remove(id)
            if rule == .slower || rule == .faster { baseline.discardCache() }
        }
        for key in states.keys where disabled.contains(key.rule) {
            states[key] = nil
            touchedKeys.insert(key)
        }
    }

    // MARK: Rules

    private func speed(provider: ProviderID, model: String, series: Series, at point: Date) throws {
        let directions = Direction.allCases.filter { speedRule($0).enabled }
        guard !directions.isEmpty else { return }
        let idleSince = point.addingTimeInterval(-TimeInterval(RuleEngine.idleMinutes * 60))
        let display = displayName(provider: provider, model: model)
        guard series.hasResponse(after: idleSince, through: point, withThroughput: true) else {
            for direction in directions {
                try step(key(.speed(direction), provider, model), at: point, conditions: .unknown, idle: true, value: nil,
                         worst: .lowest, context: speedContext(direction, display: display, index: nil))
            }
            return
        }

        let table = try baseline.usual(provider: provider, model: model, at: point)
        let windowStart = point.addingTimeInterval(-TimeInterval(SpeedIndex.windowMinutes * 60))
        let reading = SpeedIndex.at(point, responses: Array(series.window(after: windowStart, through: point)), usual: table.usual(for:))
        let cold = table.activeDays < BaselineEngine.coldStartDays
        points.append(EvalPointRow(
            provider: provider, model: model, at: point, speedIndex: reading.index, mixUsual: reading.mixUsual,
            medianTPS: reading.medianTPS, samples: reading.samples, state: cold ? .cold : reading.index == nil ? .thin : .known))

        let index = cold ? nil : reading.index
        for direction in directions {
            try step(
                key(.speed(direction), provider, model), at: point,
                conditions: speedRule(direction).conditions(index: index, direction: direction), idle: false, value: index,
                worst: direction == .slower ? .lowest : .highest, context: speedContext(direction, display: display, index: index))
        }
    }

    private func speedContext(_ direction: Direction, display: String, index: Double?) -> StepContext {
        let percent = index.map { Int((abs($0 - 1) * 100).rounded()) } ?? 0
        let calendar = calendar
        return StepContext(direction: direction) { transition, onset in
            switch (transition, direction) {
            case (.fired, .slower):
                (Copy.slowerFired(model: display, percent: percent, since: onset, calendar: calendar),
                 Copy.slowerCatchUp(model: display, percent: percent, since: onset, calendar: calendar))
            case (.fired, .faster):
                (Copy.fasterFired(model: display, percent: percent, since: onset, calendar: calendar),
                 Copy.fasterCatchUp(model: display, percent: percent, since: onset, calendar: calendar))
            case (.escalated, _):
                (Copy.slowerEscalated(model: display, percent: percent),
                 Copy.slowerCatchUp(model: display, percent: percent, since: onset, calendar: calendar))
            case (.cleared, _): (Copy.speedCleared(model: display), nil)
            case (.idleEnded, _): ("", nil)
            }
        }
    }

    private func largePrompts(provider: ProviderID, model: String, series: Series, at point: Date) throws {
        let rule = settings.largePrompts
        guard rule.enabled else { return }
        let key = key(.largePrompts, provider, model)
        let messages: (Transition, Date) -> (message: String, catchUp: String?) = { transition, _ in ("", nil) }
        let idleSince = point.addingTimeInterval(-TimeInterval(RuleEngine.idleMinutes * 60))
        guard series.hasResponse(after: idleSince, through: point, withThroughput: false) else {
            try step(key, at: point, conditions: .unknown, idle: true, value: nil, worst: .highest, context: StepContext(messages: messages))
            return
        }
        // The model's last `of` responses, however long ago (spec section 7.4).
        var sample = Array(series.through(point).suffix(rule.of))
        if sample.count < rule.of {
            sample = Array((try older(provider: provider, model: model, limit: rule.of) + sample).suffix(rule.of))
        }
        guard !sample.isEmpty else {
            try step(key, at: point, conditions: .unknown, idle: false, value: nil, worst: .highest, context: StepContext(messages: messages))
            return
        }
        let large = sample.filter { $0.inputTokens >= rule.inputTokens }
        // After an idle end, the old large prompts still in the sample can't fire on their own.
        let idleEndedAt = states[key]?.idleEndedAt
        let fresh = idleEndedAt.map { end in large.filter { $0.end > end } } ?? large
        let staleRemain = fresh.count < large.count
        let conditions = SpeedConditions(
            trigger: Tri(large.count >= rule.count && !fresh.isEmpty), clear: Tri(large.count <= rule.clearAtMost), red: .false)
        let fired = Copy.largePromptsFired(count: large.count, of: rule.of, tokens: rule.inputTokens)
        try step(key, at: point, conditions: conditions, idle: false, value: Double(large.count), worst: .highest,
                 context: StepContext(onset: fresh.map(\.end).min()) { transition, _ in
                     switch transition {
                     case .fired, .escalated: (fired, fired)
                     case .cleared: (Copy.largePromptsCleared, nil)
                     case .idleEnded: ("", nil)
                     }
                 }) { state in
            // Once no large prompt from before the idle end is left, the restriction can't matter.
            if !staleRemain { state.idleEndedAt = nil }
        }
    }

    private func failedTurns(provider: ProviderID, at point: Date) throws {
        let rule = settings.failedTurns
        guard rule.enabled else { return }
        let queue = failures[provider] ?? []
        let split = queue.firstIndex { ($0.completedAt ?? $0.startedAt) > point } ?? queue.count
        let batch = Array(queue[..<split])
        failures[provider] = Array(queue[split...])

        let key = key(.failedTurns, provider, "*")
        let lastFailure = batch.isEmpty ? states[key]?.lastFailureAt : point
        let quiet = lastFailure.map { point.timeIntervalSince($0) >= TimeInterval(rule.quietMinutes * 60) } ?? true
        let conditions = batch.isEmpty
            ? SpeedConditions(trigger: .false, clear: Tri(quiet), red: .false)
            : SpeedConditions(trigger: .true, clear: .false, red: .true)
        let reasons = batch.map { Copy.failedTurnReason(code: $0.errorCode) }
        let message = Copy.failedTurns(count: batch.count, reasons: reasons)
        let context = StepContext(onset: batch.map(\.startedAt).min(), failures: batch) { transition, _ in
            switch transition {
            case .fired, .escalated: (message, nil)
            case .cleared: (Copy.failedTurnsCleared(quietMinutes: rule.quietMinutes), nil)
            case .idleEnded: ("", nil)
            }
        }
        let (transitions, episodeID) = try step(
            key, at: point, conditions: conditions, idle: false, value: batch.isEmpty ? nil : Double(batch.count), worst: .total,
            context: context) { $0.lastFailureAt = lastFailure }
        if !batch.isEmpty {
            try store.markEvaluated(batch, at: point)
            // Failures while the episode is already open are outcomes too, for coalesced notices.
            if !transitions.contains(where: { if case .fired = $0 { true } else { false } }), let episodeID {
                outcomes.append(RuleOutcome(
                    at: point, rule: .failedTurns, provider: provider.rawValue, scope: "*", transition: nil, failures: batch,
                    episodeID: episodeID, title: RuleID.failedTurns.title, message: message, catchUpMessage: nil))
            }
        }
    }

    private func disconnects(provider: ProviderID, at point: Date) throws {
        let rule = settings.disconnects
        guard rule.enabled else { return }
        let windowStart = point.addingTimeInterval(-TimeInterval(rule.windowMinutes * 60))
        let counted = (connections[provider] ?? []).filter { $0.at > windowStart && $0.at <= point }
        // A window the connection log no longer fully covered can't be counted (spec section 6.3).
        let incomplete = (connectionGaps[provider] ?? []).contains { $0.start < point && $0.end > windowStart }
        let conditions = incomplete
            ? SpeedConditions.unknown
            : SpeedConditions(trigger: Tri(counted.count >= rule.count), clear: Tri(counted.count < rule.count), red: .false)
        let calendar = calendar
        try step(key(.disconnects, provider, "*"), at: point, conditions: conditions, idle: false, value: incomplete ? nil : Double(counted.count),
                 worst: .highest, context: StepContext(onset: counted.first?.at) { transition, onset in
                     switch transition {
                     case .fired, .escalated:
                         (Copy.disconnectsFired(count: counted.count, windowMinutes: rule.windowMinutes),
                          Copy.disconnectsCatchUp(since: onset, calendar: calendar))
                     case .cleared: (Copy.disconnectsCleared, nil)
                     case .idleEnded: ("", nil)
                     }
                 })
    }

    private func usageLimit(provider: ProviderID, at point: Date) throws {
        let rule = settings.usageLimit
        guard rule.enabled else { return }
        let key = key(.usageLimit, provider, "*")
        guard let snapshot = usage[provider], snapshot.at <= point else {
            try step(key, at: point, conditions: .unknown, idle: false, value: nil, worst: .highest,
                     context: StepContext { _, _ in ("", nil) })
            return
        }
        let conditions: SpeedConditions
        if let resets = snapshot.resetsAt, resets <= point {
            conditions = SpeedConditions(trigger: .false, clear: .true, red: .false)
        } else {
            conditions = SpeedConditions(
                trigger: Tri(snapshot.usedPercent >= rule.percent), clear: Tri(snapshot.usedPercent < rule.percent), red: .false)
        }
        let fired = Copy.usageLimitFired(
            percent: Int(snapshot.usedPercent.rounded()), windowMinutes: snapshot.windowMinutes, resets: snapshot.resetsAt, calendar: calendar)
        try step(key, at: point, conditions: conditions, idle: false, value: snapshot.usedPercent, worst: .highest,
                 context: StepContext(onset: snapshot.at) { transition, _ in
                     switch transition {
                     case .fired, .escalated: (fired, fired)
                     case .cleared: (Copy.usageLimitCleared, nil)
                     case .idleEnded: ("", nil)
                     }
                 })
    }

    private func incidents(_ data: SourceIncidents, at point: Date) throws {
        let source = data.source
        let calendar = calendar
        for (incident, resolvedAt) in data.incidents where incident.publishedAt <= point {
            let key = key(.incident, source.id, incident.id)
            let open = resolvedAt.map { $0 > point } ?? true
            let started = incident.impacts.filter { $0.start <= point }
            let watched = started.filter { data.watchedIDs.contains($0.componentID) }
            let isOpenEpisode = states[key]?.machine.isOpen == true
            // A title only matters while the incident could still fire.
            let relevant = !watched.isEmpty || (open && !isOpenEpisode && titleNamesRecentModel(incident.name, source: source, at: point))
            let active = (watched.isEmpty ? started : watched).filter { $0.end.map { $0 > point } ?? true }
            let rank = active.map { Self.rank($0.status) }.max() ?? 0
            let conditions = SpeedConditions(trigger: Tri(open && relevant), clear: Tri(!open), red: Tri(rank >= 2))
            try step(key, at: point, conditions: conditions, idle: false, value: Double(rank), worst: .highest,
                     context: StepContext(onset: incident.publishedAt, link: incident.link) { transition, onset in
                         let name = incident.name
                         switch transition {
                         case .fired:
                             return (Copy.incidentFired(source: source.displayName, name: name),
                                     Copy.incidentCatchUp(source: source.displayName, name: name, since: onset, calendar: calendar))
                         case .escalated:
                             return (Copy.incidentEscalated(source: source.displayName, name: name),
                                     Copy.incidentCatchUp(source: source.displayName, name: name, since: onset, calendar: calendar))
                         case .cleared: return (Copy.incidentCleared(source: source.displayName, name: name), nil)
                         case .idleEnded: return ("", nil)
                         }
                     })
        }
    }

    // MARK: Stepping and recording

    /// Steps one rule's machine and records its transitions: the episode row, an event, and an
    /// outcome. Returns the transitions and the scope's episode id after the step (or the one
    /// just ended).
    @discardableResult
    private func step(
        _ key: StateKey, at point: Date, conditions: SpeedConditions, idle: Bool, value: Double?, worst: Worst,
        context: StepContext, prepare: (inout ScopeState) -> Void = { _ in }
    ) throws -> (transitions: [Transition], episodeID: Int64?) {
        var state = states[key] ?? ScopeState(machine: Self.machine(for: key.rule, settings: settings))
        prepare(&state)
        if !idle, let value, state.machine.isOpen || conditions.trigger == .true {
            state.extreme = worst.combine(state.extreme, value)
        }
        // Non-speed rules date onset from their own events rather than the machine's window.
        let transitions = state.machine.step(at: point, trigger: conditions.trigger, clear: conditions.clear, red: conditions.red, idle: idle)
            .map { transition -> Transition in
                guard case .fired(_, let severity) = transition, let onset = context.onset else { return transition }
                return .fired(onset: onset, severity: severity)
            }
        var episodeID = state.episodeID
        let speed = key.rule == .slower || key.rule == .faster

        for transition in transitions {
            switch transition {
            case .fired(let onset, let severity):
                var episode = EpisodeRow(
                    rule: key.rule.rawValue, provider: key.provider, scope: key.scope, direction: context.direction,
                    onset: onset, firedAt: point, severity: severity.rawValue, worstValue: state.extreme ?? value ?? 0)
                let id = try store.insertEpisode(episode)
                episode.id = id
                openEpisodes[id] = episode
                state.episodeID = id
                episodeID = id
                // A speed episode changes which responses feed usual (spec section 8).
                if speed { baseline.discardCache() }
                try record(transition, key: key, at: point, episode: episode, context: context, kind: EventKind.ruleFired)
            case .escalated:
                guard let id = state.episodeID, var episode = openEpisodes[id] else { continue }
                episode.severity = LampColor.red.rawValue
                episode.worstValue = state.extreme ?? episode.worstValue
                try store.updateEpisode(episode)
                openEpisodes[id] = episode
                try record(transition, key: key, at: point, episode: episode, context: context, kind: EventKind.ruleEscalated)
            case .cleared, .idleEnded:
                guard let id = state.episodeID, var episode = openEpisodes[id] else { continue }
                episode.endedAt = point
                episode.endReason = transition == .cleared ? EpisodeRow.EndReason.cleared : EpisodeRow.EndReason.idleEnded
                episode.worstValue = state.extreme ?? episode.worstValue
                try store.updateEpisode(episode)
                openEpisodes[id] = nil
                worstChanged.remove(id)
                state.episodeID = nil
                if transition == .idleEnded, key.rule == .largePrompts { state.idleEndedAt = point }
                if speed { baseline.discardCache() }
                try record(transition, key: key, at: point, episode: episode, context: context,
                           kind: transition == .cleared ? EventKind.ruleCleared : nil)
            }
        }

        if state.machine.isOpen, let id = state.episodeID, let extreme = state.extreme, openEpisodes[id]?.worstValue != extreme {
            openEpisodes[id]?.worstValue = extreme
            worstChanged.insert(id)
        }
        if state.machine.isAtRest && state.episodeID == nil && state.idleEndedAt == nil {
            states[key] = nil
        } else {
            states[key] = state
        }
        touchedKeys.insert(key)
        return (transitions, episodeID)
    }

    /// Appends the outcome and, unless `kind` is nil (an idle end), the event.
    private func record(_ transition: Transition, key: StateKey, at point: Date, episode: EpisodeRow, context: StepContext, kind: String?) throws {
        guard let id = episode.id else { return }
        let (message, catchUp) = context.messages(transition, episode.onset)
        if let kind {
            try store.insertEvent(EventRow(
                at: point, kind: kind, provider: key.provider, scope: key.scope, title: key.rule.title, body: message,
                episodeID: id, link: context.link))
        }
        outcomes.append(RuleOutcome(
            at: point, rule: key.rule, provider: key.provider, scope: key.scope, transition: transition,
            failures: transition == .cleared || transition == .idleEnded ? [] : context.failures, episodeID: id,
            title: key.rule.title, message: message, catchUpMessage: catchUp))
    }

    // MARK: Helpers

    private func key(_ rule: RuleID, _ provider: ProviderID, _ scope: String) -> StateKey {
        StateKey(rule: rule, provider: provider.rawValue, scope: scope)
    }

    private func key(_ rule: RuleID, _ provider: String, _ scope: String) -> StateKey {
        StateKey(rule: rule, provider: provider, scope: scope)
    }

    private func speedRule(_ direction: Direction) -> SpeedRule { direction == .slower ? settings.slower : settings.faster }

    private func displayName(provider: ProviderID, model: String) -> String {
        naming[provider]?.displayName(model: model) ?? model
    }

    /// The model's responses ending before the preloaded range, newest `limit`, oldest first.
    private func older(provider: ProviderID, model: String, limit: Int) throws -> [ResponseRecord] {
        let cacheKey = "\(provider.rawValue)\u{0}\(model)"
        if let cached = olderResponses[cacheKey] { return cached }
        let responses = try store.responses(provider: provider, model: model, before: preloadStart, limit: limit)
        olderResponses[cacheKey] = responses
        return responses
    }

    /// Spec section 7.4: the title names a model of one of the source's providers that was used
    /// in the last 24 hours.
    private func titleNamesRecentModel(_ title: String, source: RuleStatusSource, at point: Date) -> Bool {
        let since = point.addingTimeInterval(-TimeInterval(RuleEngine.titleLookbackHours * 3_600))
        for provider in source.providers {
            guard let naming = naming[provider] else { continue }
            for (model, series) in series[provider] ?? [] where series.hasResponse(after: since, through: point, withThroughput: false) {
                if naming.incidentTitle(title, names: model) { return true }
            }
        }
        return false
    }

    static func machine(for rule: RuleID, settings: RuleSettings) -> EpisodeMachine {
        switch rule {
        case .slower, .faster:
            let speed = rule == .slower ? settings.slower : settings.faster
            return EpisodeMachine(
                firePoints: EvaluationPoints.count(forMinutes: speed.durationMinutes),
                clearPoints: EvaluationPoints.count(forMinutes: speed.clearMinutes),
                windowMinutes: SpeedIndex.windowMinutes, color: rule == .slower ? .amber : .blue)
        case .failedTurns:
            return EpisodeMachine(firePoints: 1, clearPoints: 1, windowMinutes: 0, color: .red)
        case .largePrompts, .disconnects, .incident, .usageLimit:
            return EpisodeMachine(firePoints: 1, clearPoints: 1, windowMinutes: 0, color: .amber)
        }
    }

    /// An impact status's rank for an incident's worst value and severity.
    static func rank(_ status: String) -> Int {
        switch status {
        case "full_outage": 3
        case "partial_outage": 2
        default: 1
        }
    }
}
