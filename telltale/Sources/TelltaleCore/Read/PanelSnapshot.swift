import Foundation

/// One registered usage source as the UI sees it (spec section 5), built from `Registry`.
public struct SourceSummary: Sendable {
    public var provider: ProviderID
    /// The usage source's display name ("Codex").
    public var name: String
    /// Its status source's display name ("OpenAI"), the Provider lamp's caption.
    public var statusName: String
    /// Its status source's id (`UsageSource.statusSourceID`): whose incidents its models' charts show.
    public var statusSourceID: String
    /// The lamps it can feed; the UI shows only these (spec section 5).
    public var signals: Set<Signal>
    public var naming: any ModelNaming
    public var dataFolder: URL?
    public var failureNoun: String
    public var supportedRules: Set<RuleID>

    public init(provider: ProviderID, name: String, statusName: String, statusSourceID: String, signals: Set<Signal>, naming: any ModelNaming, dataFolder: URL? = nil, failureNoun: String = "turn", supportedRules: Set<RuleID> = []) {
        self.provider = provider
        self.name = name
        self.statusName = statusName
        self.statusSourceID = statusSourceID
        self.signals = signals
        self.naming = naming
        self.dataFolder = dataFolder
        self.failureNoun = failureNoun
        self.supportedRules = supportedRules
    }
}

/// What the menu-bar panel and glyph show (spec section 9.1), read from the database in one
/// read transaction.
///
/// - Lamps: one per signal any registered source declares, plus Collector, lit in the most severe
///   color of the open episodes behind it (spec sections 5 and 7.4). Collector health lights
///   Collector red; the panel's strip leaves Collector out and shows it in the footer.
/// - Alerts: one per open episode, new before acknowledged, then by severity and recency.
///   Failed turns use counted membership; speed alerts use their worst value when usable, otherwise the latest event.
/// - Model rows: models with a response in the last `activeWindow`; tok/s and mix-matched usual
///   come from the current stored speed evaluation point; the sparkline is the stored points' median
///   tok/s over `activeWindow`, one value per 5-minute point.
public struct ArrivalNote: Sendable, Equatable {
    public var provider: ProviderID
    public var text: String
    public var firstModel: String?
}

public struct PanelSnapshot: Sendable, Equatable {
    public struct Alert: Sendable, Equatable, Hashable {
        public var color: LampColor
        public var text: String
        public var key: String
        public var detail: String?
        public var acknowledgedAt: Date?
        public var failedTurns: Int?
        public var threadID: String?

        public init(color: LampColor, text: String, key: String = "", detail: String? = nil, acknowledgedAt: Date? = nil, failedTurns: Int? = nil, threadID: String? = nil) {
            self.color = color
            self.text = text
            self.key = key
            self.detail = detail
            self.acknowledgedAt = acknowledgedAt
            self.failedTurns = failedTurns
            self.threadID = threadID
        }
    }

    public struct ModelRow: Sendable, Equatable, Hashable, Identifiable {
        /// `provider/model`, unique across sources.
        public var id: String
        public var provider: ProviderID
        public var providerName: String
        public var model: String
        /// The display name (`ModelNaming.displayName`).
        public var name: String
        public var tps: Double?
        public var usual: Double?
        /// Oldest first; nil where no point was stored.
        public var sparkline: [Double?]
        /// Thin data or learning (Copy).
        public var note: String?
        /// The most severe open slower or faster episode scoped to this model: the tok/s numeral and
        /// sparkline take its lamp color (the visual doc's mockup); nil while speed is usual.
        public var color: LampColor?

        public init(
            provider: ProviderID, model: String, name: String, tps: Double?, usual: Double?, sparkline: [Double?], note: String?,
            color: LampColor? = nil, providerName: String? = nil
        ) {
            self.id = "\(provider.rawValue)/\(model)"
            self.provider = provider
            self.providerName = providerName ?? provider.rawValue
            self.model = model
            self.name = name
            self.tps = tps
            self.usual = usual
            self.sparkline = sparkline
            self.note = note
            self.color = color
        }
    }

    /// Spec section 9.1: one row per model active in the last 3 hours, with a 3-hour sparkline.
    public static let activeWindow: TimeInterval = 3 * 3_600
    /// Number of stored five-minute points shown in the sparkline.
    public static let sparklinePoints = Int(activeWindow / EvaluationPoints.cadence)
    /// A model is offered a lasting-shift prompt while it was active within this many days.
    public static let shiftLookbackDays = ShiftDetector.runDays

    /// The newest successful collector run's end ("Checked HH:MM").
    public var checkedAt: Date?
    /// Admitted signals only; nil is unlit.
    public var lamps: [Signal: LampColor?]
    public var unacknowledged: [Signal: LampColor]
    /// Captions for the admitted signals; Provider uses the status source's name.
    public var labels: [Signal: String]
    public var alerts: [Alert]
    public var models: [ModelRow]
    public var arrivals: [ArrivalNote]
    public var shift: ShiftPrompt?
    /// The shift prompt in words (`Copy.shiftPrompt`), with the model's display name.
    public var shiftText: String?
    public var shiftName: String?
    /// The collector's own lamp (green while running), for the footer's dot.
    public var collector: LampState
    public var collectorAcknowledgedAt: Date?
    /// The collector-state line.
    public var footer: String

    public init(
        checkedAt: Date?, lamps: [Signal: LampColor?], labels: [Signal: String], alerts: [Alert], models: [ModelRow],
        shift: ShiftPrompt?, shiftText: String?, collector: LampState, footer: String, shiftName: String? = nil, arrivals: [ArrivalNote] = [],
        unacknowledged: [Signal: LampColor]? = nil, collectorAcknowledgedAt: Date? = nil
    ) {
        self.checkedAt = checkedAt
        self.lamps = lamps
        self.unacknowledged = unacknowledged ?? lamps.compactMapValues { $0 }
        self.labels = labels
        self.alerts = alerts
        self.models = models
        self.arrivals = arrivals
        self.shift = shift
        self.shiftText = shiftText
        self.shiftName = shiftName
        self.collector = collector
        self.collectorAcknowledgedAt = collectorAcknowledgedAt
        self.footer = footer
    }

    /// The admitted signals in strip order.
    public var signals: [Signal] { Signal.allCases.filter { lamps.keys.contains($0) } }

    /// The most severe lit lamp: the glyph's dot.
    public var mostSevere: LampColor? { lamps.values.compactMap { $0 }.max() }
    public var attention: LampColor? { unacknowledged.values.max() }
    public func isAcknowledged(_ signal: Signal) -> Bool { (lamps[signal] ?? nil) != nil && unacknowledged[signal] == nil }

    /// Before the collector has created the database: no rows and no checked time. Collector health
    /// still shows: a problem lights the Collector lamp red and becomes the footer, and the off
    /// line shows as is; otherwise (no report, or health's own waiting line) `footer`.
    public static func waiting(
        sources: [SourceSummary], health: CollectorHealthReport? = nil, footer: String = Copy.waitingForFirstRun
    ) -> PanelSnapshot {
        let admitted = admittedSignals(sources)
        var lamps = Dictionary(uniqueKeysWithValues: admitted.map { ($0, LampColor?.none) })
        if health?.lamp == .red { lamps[.collector] = .red }
        let line = health.flatMap { $0.problems.first ?? ($0.footer.isEmpty ? nil : $0.footer) } ?? footer
        return PanelSnapshot(
            checkedAt: nil, lamps: lamps, labels: labels(admitted, sources: sources), alerts: [], models: [], shift: nil, shiftText: nil,
            collector: health?.lamp ?? .unlit, footer: line)
    }

    public static func load(
        store: Store, baseline: BaselineEngine, health: CollectorHealthReport?, sources: [SourceSummary], now: Date, calendar: Calendar
    ) throws -> PanelSnapshot {
        try store.transaction {
            let admitted = admittedSignals(sources)
            var lamps = Dictionary(uniqueKeysWithValues: admitted.map { ($0, LampColor?.none) })
            let byProvider = Dictionary(sources.map { ($0.provider.rawValue, $0) }, uniquingKeysWith: { first, _ in first })

            var alerts: [(alert: Alert, at: Date, provider: String, model: String?)] = []
            var unacknowledged: [Signal: LampColor] = [:]
            let acknowledgements = try store.value(.alertAcknowledgements)
            // Open speed episodes by `provider/model`: the row's numeral and sparkline color.
            var speedColors: [String: LampColor] = [:]
            for episode in try store.openEpisodes() {
                guard let id = episode.id, let rule = RuleID(rawValue: episode.rule) else { continue }
                let color = LampColor(rawValue: episode.severity) ?? .amber
                let signal = rule.signal
                if rule == .incident {
                    // Incidents belong to a status source; the Provider lamp is admitted by any usage source declaring it.
                    guard admitted.contains(.provider) else { continue }
                } else {
                    guard let source = byProvider[episode.provider] else { continue }
                    if let signal, !source.signals.contains(signal) { continue }
                }
                if let signal { lamps[signal] = [lamps[signal] ?? nil, color].compactMap { $0 }.max() }
                if rule == .slower || rule == .faster {
                    let key = "\(episode.provider)/\(episode.scope)"
                    speedColors[key] = max(speedColors[key] ?? color, color)
                }
                let latest = try store.latestAlertEvent(episodeID: id)
                var text = latest?.body ?? rule.title
                if let source = byProvider[episode.provider],
                   (rule == .slower && episode.worstValue < 1 || rule == .faster && episode.worstValue > 1),
                   let percent = SpeedIndex.percent(episode.worstValue) {
                    let model = source.naming.displayName(model: episode.scope)
                    text = rule == .slower
                        ? Copy.slowerOpen(model: model, percent: percent, since: episode.onset, calendar: calendar)
                        : Copy.fasterOpen(model: model, percent: percent, since: episode.onset, calendar: calendar)
                }
                let key = Acknowledgements.key(episode)
                let ack = acknowledgements[key]
                var count: Int?
                var detailText: String?
                let membership = rule == .failedTurns ? try FailedTurnEpisodeDetail.decode(episode.detail) : nil
                if rule == .failedTurns, let total = Int(exactly: episode.worstValue), total >= 0, let source = byProvider[episode.provider] {
                    count = total
                    if let membership, membership.priorCount + membership.failures.count != total {
                        throw StoreError.invalidData("Failed-turn detail does not match total")
                    }
                    func reasons(_ range: Range<Int>) -> [String] {
                        (membership?.reasons(in: range) ?? []).map { Copy.failedTurnReason(code: $0) }
                    }
                    if let ack, let saved = ack.failedTurns, saved >= 0, total > saved {
                        text = Copy.failedTurnsBeyondAcknowledged(source: source.name, noun: source.failureNoun, count: total - saved, reasons: reasons(saved..<total), acknowledged: ack.at, calendar: calendar)
                        detailText = Copy.failedTurnsTotal(count: total, since: episode.onset, calendar: calendar)
                    } else {
                        text = Copy.failedTurnsOpen(source: source.name, noun: source.failureNoun, count: total, reasons: reasons(0..<total), since: episode.onset, calendar: calendar)
                    }
                }
                if rule != .incident, let source = byProvider[episode.provider], !text.hasPrefix("\(source.name): ") {
                    text = "\(source.name): \(text)"
                }
                let held = ack.map { Acknowledgements.holds($0, severity: color, failedTurns: count) } ?? false
                if held, let ack { detailText = Copy.acknowledged(at: ack.at, calendar: calendar) }
                if !held, let signal { unacknowledged[signal] = max(unacknowledged[signal] ?? color, color) }
                let thread = rule == .failedTurns ? NotificationPolicy.failedTurnsThreadID(provider: ProviderID(rawValue: episode.provider)) : NotificationPolicy.threadID(rule: rule, provider: episode.provider, scope: episode.scope)
                alerts.append((Alert(color: color, text: text, key: key, detail: detailText, acknowledgedAt: held ? ack?.at : nil, failedTurns: count, threadID: thread), latest?.at ?? episode.firedAt, episode.provider,
                               (rule == .slower || rule == .faster) ? episode.scope : nil))
            }
            alerts.sort {
                if ($0.alert.acknowledgedAt == nil) != ($1.alert.acknowledgedAt == nil) { return $0.alert.acknowledgedAt == nil }
                return ($0.alert.color, $0.at) > ($1.alert.color, $1.at)
            }
            let collectorAcknowledgement = try store.value(.collectorAcknowledgement)
            let collectorHeld = health.map { report in
                report.lamp == .red && collectorAcknowledgement.map { Acknowledgements.holds($0, keys: report.problemKeys) } == true
            } ?? false
            if health?.lamp == .red { lamps[.collector] = .red; if !collectorHeld { unacknowledged[.collector] = .red } }

            var rows: [ModelRow] = []
            var shift: ShiftPrompt?
            var shiftText: String?
            var shiftName: String?
            for source in sources {
                let models = try store.models(provider: source.provider)
                if let backfill = try store.backfill(unit: source.provider.rawValue), backfill.finishedAt == nil { continue }
                let active = try models.filter { try store.hasResponse(provider: source.provider, model: $0, after: now.addingTimeInterval(-activeWindow), through: now) }
                for model in active {
                    var modelRow = try row(store: store, baseline: baseline, source: source, model: model, now: now)
                    modelRow.color = speedColors[modelRow.id]
                    rows.append(modelRow)
                }
                guard shift == nil else { continue }
                let shiftSince = now.addingTimeInterval(-TimeInterval(shiftLookbackDays) * 86_400)
                for model in models {
                    guard try store.hasResponse(provider: source.provider, model: model, after: shiftSince, through: now) else { continue }
                    if let prompt = try ShiftDetector.prompt(provider: source.provider, model: model, statusSourceID: source.statusSourceID, at: now, store: store, calendar: calendar) {
                        shift = prompt
                        break
                    }
                }
            }

            for source in sources {
                var ids = rows.filter { $0.provider == source.provider }.map(\.model)
                if let shift, shift.provider == source.provider { ids.append(shift.model) }
                ids += alerts.filter { $0.provider == source.provider.rawValue }.compactMap(\.model)
                let names = DisplayNames.disambiguated(ids, naming: source.naming)
                for index in rows.indices where rows[index].provider == source.provider {
                    rows[index].name = names[rows[index].model] ?? rows[index].name
                }
                if let shift, shift.provider == source.provider {
                    shiftName = names[shift.model] ?? shift.model
                    shiftText = Copy.shiftPrompt(model: shiftName!, percent: shift.typicalPercent, days: shift.days, direction: shift.direction)
                }
                for index in alerts.indices where alerts[index].provider == source.provider.rawValue {
                    guard let model = alerts[index].model, let name = names[model] else { continue }
                    alerts[index].alert.text = DisplayNames.speedText(alerts[index].alert.text, base: source.naming.displayName(model: model), name: name, provider: source.name)
                }
            }

            let pending = try store.value(.pendingArrivals)
            let dismissed = try store.value(.dismissedArrivals)
            var arrivals: [ArrivalNote] = []
            for source in sources where pending.contains(source.provider.rawValue) && !dismissed.contains(source.provider.rawValue) {
                if let backfill = try store.backfill(unit: source.provider.rawValue), backfill.reason == .new && backfill.finishedAt == nil { continue }
                let models = try store.models(provider: source.provider)
                let names = DisplayNames.disambiguated(models, naming: source.naming)
                let recent = try ModelDetail.recentModels(store: store, provider: source.provider, now: now)
                let ready = try recent.filter { if case .cold = try baseline.learning(provider: source.provider, model: $0, at: now) { return false }; return true }
                let text = recent.isEmpty && !models.isEmpty
                    ? Copy.arrivalIdle(name: source.name, days: CollectorRun.lookbackDays)
                    : Copy.arrival(name: source.name, days: CollectorRun.lookbackDays, readyModels: ready.map { names[$0] ?? $0 })
                arrivals.append(ArrivalNote(provider: source.provider, text: text, firstModel: recent.first))
            }
            let checkedAt = try store.lastSucceededRunFinish()
            return PanelSnapshot(
                checkedAt: checkedAt, lamps: lamps, labels: labels(admitted, sources: sources), alerts: alerts.map(\.alert),
                models: rows, shift: shift, shiftText: shiftText, collector: health?.lamp ?? .unlit,
                footer: try footer(health: health, store: store), shiftName: shiftName, arrivals: arrivals, unacknowledged: unacknowledged,
                collectorAcknowledgedAt: collectorHeld ? collectorAcknowledgement?.at : nil)
        }
    }

    // MARK: Parts

    static func admittedSignals(_ sources: [SourceSummary]) -> Set<Signal> {
        sources.reduce(into: Set<Signal>([.collector])) { $0.formUnion($1.signals) }
    }

    static func labels(_ signals: Set<Signal>, sources: [SourceSummary]) -> [Signal: String] {
        let statusNames = Set(sources.filter { $0.signals.contains(.provider) }.map(\.statusName))
        return Dictionary(uniqueKeysWithValues: signals.map { signal in
            let label = switch signal {
            case .speed: "Speed"
            case .errors: "Errors"
            case .link: "Link"
            case .provider: statusNames.count == 1 ? statusNames.first ?? "Status" : "Status"
            case .load: "Load"
            case .collector: "Collector"
            }
            return (signal, label)
        })
    }

    private static func row(store: Store, baseline: BaselineEngine, source: SourceSummary, model: String, now: Date) throws -> ModelRow {
        let last = EvaluationPoints.after(nil, through: now, earliest: now.addingTimeInterval(-EvaluationPoints.cadence)).last ?? now
        let first = last.addingTimeInterval(-EvaluationPoints.cadence * Double(sparklinePoints - 1))
        let points = try store.evalPoints(provider: source.provider, model: model, in: first...last)
        let byTime = Dictionary(points.map { ($0.at, $0) }, uniquingKeysWith: { _, newer in newer })
        let sparkline = (0..<sparklinePoints).map { byTime[first.addingTimeInterval(EvaluationPoints.cadence * Double($0))]?.medianTPS }

        // The newest point within the speed window says whether speed can be judged now.
        let current = points.last.flatMap { now.timeIntervalSince($0.at) <= TimeInterval(SpeedIndex.windowMinutes * 60) ? $0 : nil }
        var note: String?
        if current?.state == .thin {
            note = Copy.thinData
        } else {
            switch try baseline.learning(provider: source.provider, model: model, at: now) {
            case .cold(let days): note = Copy.learning(days: days, of: BaselineEngine.activeDayCount)
            case .learning(let days, let of): note = Copy.learning(days: days, of: of)
            case .ready: note = nil
            }
        }
        return ModelRow(
            provider: source.provider, model: model, name: source.naming.displayName(model: model),
            tps: current?.medianTPS, usual: current?.medianTPS == nil ? nil : current?.mixUsual, sparkline: sparkline, note: note, providerName: source.name)
    }

    /// A problem first, then the off or first-run line, else the running line.
    private static func footer(health: CollectorHealthReport?, store: Store) throws -> String {
        guard let health else { return "" }
        if let problem = health.problems.first { return problem }
        if !health.footer.isEmpty { return health.footer }
        return Copy.collectorRunning(minutes: Settings.usableInterval(try store.value(.intervalMinutes)))
    }
}

extension Store {
    /// The newest `ruleFired` or `ruleEscalated` event of an episode: the fallback wording for an open episode.
    /// Other kinds (status posts, baseline events, `connectionHistoryIncomplete` gaps) carry no
    /// episode and never match.
    func latestAlertEvent(episodeID: Int64) throws -> (at: Date, body: String)? {
        try query("""
            SELECT at, body FROM events WHERE episode_id = ? AND kind IN (?, ?) ORDER BY at DESC, id DESC LIMIT 1
            """, [.int(episodeID), .text(EventKind.ruleFired), .text(EventKind.ruleEscalated)]) { (at: $0.date(0), body: $0.text(1)) }.first
    }

    /// Whether the model has a response ending in `(after, through]`.
    func hasResponse(provider: ProviderID, model: String, after: Date, through: Date) throws -> Bool {
        try !query("""
            SELECT 1 FROM responses WHERE provider = ? AND model = ? AND end_at > ? AND end_at <= ? LIMIT 1
            """, [.text(provider.rawValue), .text(model), .date(after), .date(through)]) { _ in true }.isEmpty
    }
}
