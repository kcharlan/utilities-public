import Foundation

/// One registered usage source as the UI sees it (spec section 5), built from `Registry`.
public struct SourceSummary: Sendable {
    public var provider: ProviderID
    /// The usage source's display name ("Codex").
    public var name: String
    /// Its status source's display name ("OpenAI"), the Provider lamp's caption.
    public var statusName: String
    /// The lamps it can feed; the UI shows only these (spec section 5).
    public var signals: Set<Signal>
    public var naming: any ModelNaming

    public init(provider: ProviderID, name: String, statusName: String, signals: Set<Signal>, naming: any ModelNaming) {
        self.provider = provider
        self.name = name
        self.statusName = statusName
        self.signals = signals
        self.naming = naming
    }
}

/// What the menu-bar panel and glyph show (spec section 9.1), read from the database in one
/// read transaction.
///
/// - Lamps: one per signal any registered source declares, plus Collector, lit in the most severe
///   color of the open episodes behind it (spec sections 5 and 7.4). Collector health lights
///   Collector red; the panel's strip leaves Collector out and shows it in the footer.
/// - Alerts: one per open episode, worded by its latest fired or escalated event, red before amber
///   before blue and newest first within a color. With several sources the text names the source
///   (incident wording already names its status page).
/// - Model rows: models with a response in the last `activeWindow`; tok/s is the median
///   throughput over the last `rateWindow` (plan call: the dashboard's last-hour readout) and usual
///   is `mixUsual` over the same responses; the sparkline is the stored evaluation points' median
///   tok/s over `activeWindow`, one value per 5-minute point.
public struct PanelSnapshot: Sendable, Equatable {
    public struct Alert: Sendable, Equatable, Hashable {
        public var color: LampColor
        public var text: String

        public init(color: LampColor, text: String) {
            self.color = color
            self.text = text
        }
    }

    public struct ModelRow: Sendable, Equatable, Hashable, Identifiable {
        /// `provider/model`, unique across sources.
        public var id: String
        public var provider: ProviderID
        public var model: String
        /// The display name (`ModelNaming.displayName`).
        public var name: String
        public var tps: Double?
        public var usual: Double?
        /// Oldest first; nil where no point was stored.
        public var sparkline: [Double?]
        /// Thin data or learning (Copy).
        public var note: String?

        public init(
            provider: ProviderID, model: String, name: String, tps: Double?, usual: Double?, sparkline: [Double?], note: String?
        ) {
            self.id = "\(provider.rawValue)/\(model)"
            self.provider = provider
            self.model = model
            self.name = name
            self.tps = tps
            self.usual = usual
            self.sparkline = sparkline
            self.note = note
        }
    }

    /// Spec section 9.1: one row per model active in the last 3 hours, with a 3-hour sparkline.
    public static let activeWindow: TimeInterval = 3 * 3_600
    /// The window the row's tok/s and usual are computed over (plan call).
    public static let rateWindow: TimeInterval = 3_600
    public static let sparklinePoints = Int(activeWindow / EvaluationPoints.cadence)
    /// A model is offered a lasting-shift prompt while it was active within this many days.
    public static let shiftLookbackDays = ShiftDetector.runDays

    /// The newest successful collector run's end ("Checked HH:MM").
    public var checkedAt: Date?
    /// Admitted signals only; nil is unlit.
    public var lamps: [Signal: LampColor?]
    /// Captions for the admitted signals; Provider uses the status source's name.
    public var labels: [Signal: String]
    public var alerts: [Alert]
    public var models: [ModelRow]
    public var shift: ShiftPrompt?
    /// The shift prompt in words (`Copy.shiftPrompt`), with the model's display name.
    public var shiftText: String?
    /// The collector's own lamp (green while running), for the footer's dot.
    public var collector: LampState
    /// The collector-state line.
    public var footer: String

    public init(
        checkedAt: Date?, lamps: [Signal: LampColor?], labels: [Signal: String], alerts: [Alert], models: [ModelRow],
        shift: ShiftPrompt?, shiftText: String?, collector: LampState, footer: String
    ) {
        self.checkedAt = checkedAt
        self.lamps = lamps
        self.labels = labels
        self.alerts = alerts
        self.models = models
        self.shift = shift
        self.shiftText = shiftText
        self.collector = collector
        self.footer = footer
    }

    /// The admitted signals in strip order.
    public var signals: [Signal] { Signal.allCases.filter { lamps.keys.contains($0) } }

    /// The most severe lit lamp: the glyph's dot.
    public var mostSevere: LampColor? { lamps.values.compactMap { $0 }.max() }

    /// Before the collector has created the database: nothing lit, no rows, no checked time.
    public static func waiting(sources: [SourceSummary], footer: String = Copy.waitingForFirstRun) -> PanelSnapshot {
        let admitted = admittedSignals(sources)
        return PanelSnapshot(
            checkedAt: nil, lamps: Dictionary(uniqueKeysWithValues: admitted.map { ($0, LampColor?.none) }),
            labels: labels(admitted, sources: sources), alerts: [], models: [], shift: nil, shiftText: nil, collector: .unlit,
            footer: footer)
    }

    public static func load(
        store: Store, baseline: BaselineEngine, health: CollectorHealthReport?, sources: [SourceSummary], now: Date, calendar: Calendar
    ) throws -> PanelSnapshot {
        try store.transaction {
            let admitted = admittedSignals(sources)
            var lamps = Dictionary(uniqueKeysWithValues: admitted.map { ($0, LampColor?.none) })
            let byProvider = Dictionary(sources.map { ($0.provider.rawValue, $0) }, uniquingKeysWith: { first, _ in first })

            var alerts: [(alert: Alert, at: Date)] = []
            for episode in try store.openEpisodes() {
                guard let id = episode.id, let rule = RuleID(rawValue: episode.rule) else { continue }
                let color = LampColor(rawValue: episode.severity) ?? .amber
                let signal = signal(for: rule)
                if rule == .incident {
                    // Incidents belong to a status source; the Provider lamp is admitted by any usage source declaring it.
                    guard admitted.contains(.provider) else { continue }
                } else {
                    guard let source = byProvider[episode.provider] else { continue }
                    if let signal, !source.signals.contains(signal) { continue }
                }
                if let signal { lamps[signal] = [lamps[signal] ?? nil, color].compactMap { $0 }.max() }
                let latest = try store.latestAlertEvent(episodeID: id)
                var text = latest?.body ?? rule.title
                if sources.count > 1, rule != .incident, let source = byProvider[episode.provider] {
                    text = "\(source.name): \(text)"
                }
                alerts.append((Alert(color: color, text: text), latest?.at ?? episode.firedAt))
            }
            alerts.sort { ($0.alert.color, $0.at) > ($1.alert.color, $1.at) }
            if health?.lamp == .red { lamps[.collector] = .red }

            var rows: [ModelRow] = []
            var shift: ShiftPrompt?
            var shiftText: String?
            for source in sources {
                let models = try store.models(provider: source.provider)
                for model in models {
                    guard try store.hasResponse(provider: source.provider, model: model, after: now.addingTimeInterval(-activeWindow), through: now) else { continue }
                    rows.append(try row(store: store, baseline: baseline, source: source, model: model, now: now))
                }
                guard shift == nil else { continue }
                let shiftSince = now.addingTimeInterval(-TimeInterval(shiftLookbackDays) * 86_400)
                for model in models {
                    guard try store.hasResponse(provider: source.provider, model: model, after: shiftSince, through: now) else { continue }
                    if let prompt = try ShiftDetector.prompt(provider: source.provider, model: model, at: now, store: store, calendar: calendar) {
                        shift = prompt
                        shiftText = Copy.shiftPrompt(
                            model: source.naming.displayName(model: model), percent: prompt.typicalPercent, days: prompt.days,
                            direction: prompt.direction)
                        break
                    }
                }
            }

            let checkedAt = try store.recentRuns(limit: 20, includingSkipped: false).first { $0.outcome == .succeeded }?.finishedAt
            return PanelSnapshot(
                checkedAt: checkedAt, lamps: lamps, labels: labels(admitted, sources: sources), alerts: alerts.map(\.alert),
                models: rows, shift: shift, shiftText: shiftText, collector: health?.lamp ?? .unlit,
                footer: try footer(health: health, store: store))
        }
    }

    // MARK: Parts

    /// The lamp a rule lights; the usage limit has none (spec section 7.4).
    public static func signal(for rule: RuleID) -> Signal? {
        switch rule {
        case .slower, .faster: .speed
        case .largePrompts: .load
        case .failedTurns: .errors
        case .disconnects: .link
        case .incident: .provider
        case .usageLimit: nil
        }
    }

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
        let recent = try store.responses(provider: source.provider, model: model, endingIn: now.addingTimeInterval(-rateWindow)...now)
            .filter { $0.throughput != nil }
        let table = try baseline.usual(provider: source.provider, model: model, at: now)

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
            tps: median(recent.compactMap(\.throughput)), usual: mixUsual(recent, table: table), sparkline: sparkline, note: note)
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
    /// The newest `ruleFired` or `ruleEscalated` event of an episode: an open episode's alert wording.
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
