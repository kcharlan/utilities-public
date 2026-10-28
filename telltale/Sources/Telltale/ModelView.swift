import Charts
import SwiftUI
import TelltaleCore

/// Spec section 9.2's model view, as the visual doc's dashboard wireframe and mockup: the big lamp
/// strip (with Collector), the alerts, Speed against usual, Prompt sizes beside Workload, and Events.
struct ModelView: View {
    let model: DashboardModel

    var body: some View {
        let snapshot = model.live.snapshot
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 8) {
                ForEach(snapshot.signals, id: \.self) { signal in
                    let color = snapshot.lamps[signal].flatMap { $0 }
                    DashboardLamp(
                        label: snapshot.labels[signal] ?? signal.rawValue.capitalized, symbol: LampStrip.symbol(signal),
                        color: color.map(Theme.color))
                }
            }
            if !snapshot.alerts.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(snapshot.alerts.enumerated()), id: \.offset) { _, alert in
                        AlertLine(color: Theme.nsColor(alert.color), text: alert.text)
                    }
                }
            }
            if let error = model.loadError ?? model.panel.actionError {
                AlertLine(color: Theme.red, text: error)
            }
            if let detail = model.detail {
                SpeedSection(model: model, detail: detail)
            }
            if let workload = model.workload {
                HStack(alignment: .top, spacing: 22) {
                    PromptSizes(workload: workload).frame(minWidth: 360, maxWidth: .infinity, alignment: .topLeading)
                    WorkloadGrid(workload: workload, loadLamp: snapshot.lamps[.load].flatMap { $0 }, calendar: model.calendar)
                        .frame(minWidth: 340, maxWidth: .infinity, alignment: .topLeading)
                }
            }
            EventList(model: model)
        }
    }
}

// MARK: Speed against usual

private struct SpeedSection: View {
    let model: DashboardModel
    let detail: ModelDetail

    var body: some View {
        let name = model.selectedModel?.name ?? ""
        let color = model.selectedModel?.color
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Speed against usual") {
                Picker("Time range", selection: Binding(get: { model.range }, set: { model.range = $0 })) {
                    ForEach(ChartRange.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented).labelsHidden().fixedSize()
            }
            HStack(alignment: .firstTextBaseline, spacing: 28) {
                Readout(
                    value: detail.lastHour.tps.map { String(Int($0.rounded())) } ?? "–", unit: "tok/s",
                    label: detail.lastHour.usualTPS.map { "Last hour, usual \(Int($0.rounded())) for this prompt size" } ?? "Last hour",
                    color: color, size: 34)
                Readout(
                    value: detail.lastHour.medianSeconds.map(DashboardFormat.seconds) ?? "–", unit: "s",
                    label: detail.lastHour.usualMedianSeconds.map { "Median response, usual \(DashboardFormat.seconds($0))" } ?? "Median response",
                    color: nil, size: 34)
            }
            SpeedChart(detail: detail)
                .frame(height: 220)
                .accessibilityLabel("Hourly \(name) speed relative to usual, \(detail.range.label)")
            Legend(items: [
                .swatch(Theme.color(.red), "Much slower"), .swatch(Theme.color(.amber), "Slower"), .swatch(Theme.swiftUI(Theme.usual), "Usual"),
                .swatch(Theme.color(.blue), "Faster"), .band("Provider incident"), .triangle("Failed turn"),
            ])
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(Copy.usualExplanation).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim))
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 8)
                if model.acceptingSince == nil {
                    Button("Accept as usual…") { model.beginAccept() }.buttonStyle(DashboardButtonStyle(quiet: true))
                }
            }
            if let since = model.acceptingSince {
                HStack(spacing: 8) {
                    Text("Usual since")
                    DatePicker("Usual since", selection: Binding(get: { since }, set: { model.acceptingSince = $0 }), in: ...model.now(), displayedComponents: .date)
                        .labelsHidden().fixedSize()
                    Button("Accept") { model.accept() }.buttonStyle(DashboardButtonStyle())
                    Button("Cancel") { model.cancelAccept() }.buttonStyle(DashboardButtonStyle(quiet: true))
                }
            }
            if let shift = detail.shift {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(Copy.shiftPrompt(model: name, percent: shift.typicalPercent, days: shift.days, direction: shift.direction))
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 8)
                    Button("Keep as abnormal") { model.keepAsAbnormal() }.buttonStyle(DashboardButtonStyle(quiet: true))
                }
            }
            if let confirmation = model.panel.confirmation {
                Text(confirmation.text).foregroundStyle(Theme.swiftUI(Theme.dim))
            }
            ForEach(notes, id: \.self) { note in
                Text(note).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim))
            }
        }
    }

    /// Learning, drift and missing-bucket notes (spec sections 7.1 and 8).
    private var notes: [String] {
        var notes: [String] = []
        switch detail.learning {
        case .cold(let days): notes.append(Copy.learning(days: days, of: BaselineEngine.activeDayCount))
        case .learning(let days, let of): notes.append(Copy.learning(days: days, of: of))
        case .ready: break
        }
        if let drift = detail.drift { notes.append(Copy.drift(percent: drift.percent, direction: drift.direction, acceptedOn: drift.acceptedOn)) }
        notes += detail.bucketGaps.map { Copy.noBucketHistory(bucket: $0) }
        return notes
    }
}

/// Hourly speed-index dots around the dashed usual line, incident bands and failed-turn markers.
private struct SpeedChart: View {
    let detail: ModelDetail

    var body: some View {
        let indices = detail.dots.map(\.index)
        let low = min(0.5, (indices.min() ?? 1) - 0.1)
        let high = max(1.5, (indices.max() ?? 1) + 0.1)
        let markerY = low + (high - low) * 0.04
        Chart {
            ForEach(Array(detail.incidents.enumerated()), id: \.offset) { _, incident in
                RectangleMark(xStart: .value("Start", incident.start), xEnd: .value("End", incident.end), yStart: .value("Low", low), yEnd: .value("High", high))
                    .foregroundStyle(Theme.color(.amber).opacity(0.1))
            }
            RuleMark(y: .value("Usual", 1.0))
                .foregroundStyle(Theme.swiftUI(Theme.dim))
                .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
            ForEach(detail.dots, id: \.hour) { dot in
                PointMark(x: .value("Hour", dot.hour), y: .value("Speed against usual", dot.index))
                    .symbolSize(22)
                    .foregroundStyle(dot.color.map(Theme.color) ?? Theme.swiftUI(Theme.usual))
            }
            ForEach(Array(detail.failures.enumerated()), id: \.offset) { _, failure in
                PointMark(x: .value("Failed turn", failure), y: .value("Marker", markerY))
                    .symbol(.triangle)
                    .symbolSize(36)
                    .foregroundStyle(Theme.color(.red))
            }
        }
        .chartXScale(domain: detail.interval.start...detail.interval.end)
        .chartYScale(domain: low...high)
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: detail.range == .twoWeeks ? 7 : 6)) { _ in
                AxisGridLine().foregroundStyle(Theme.swiftUI(Theme.housing))
                AxisValueLabel(format: detail.range.duration > 86_400 ? .dateTime.month(.abbreviated).day() : .dateTime.hour(.twoDigits(amPM: .omitted)).minute())
                    .font(Fonts.gauge(11, medium: false)).foregroundStyle(Theme.swiftUI(Theme.dim))
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: [0.5, 1.0, 1.5].filter { $0 >= low && $0 <= high }) { value in
                AxisGridLine().foregroundStyle(Theme.swiftUI(Theme.housing))
                AxisValueLabel { if let index = value.as(Double.self) { Text(String(format: "%.1f×", index)) } }
                    .font(Fonts.gauge(11, medium: false)).foregroundStyle(Theme.swiftUI(Theme.dim))
            }
        }
        .chartPlotStyle { $0.border(Theme.swiftUI(Theme.housing), width: 1) }
    }
}

// MARK: Prompt sizes and workload

private struct PromptSizes: View {
    let workload: Workload

    private struct Bar: Identifiable {
        var bucket: InputBucket
        var series: String
        var share: Double
        var id: String { "\(bucket.rawValue)-\(series)" }
    }

    var body: some View {
        let bars = workload.histogram.flatMap { [Bar(bucket: $0.bucket, series: "Last 3 hours", share: $0.now), Bar(bucket: $0.bucket, series: "Usual", share: $0.usual)] }
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Prompt sizes", aside: "Last 3 hours against usual")
            Chart(bars) { bar in
                BarMark(x: .value("Prompt size", bar.bucket.label), y: .value("Share", bar.share))
                    .foregroundStyle(by: .value("Series", bar.series))
                    .position(by: .value("Series", bar.series))
            }
            .chartForegroundStyleScale(["Last 3 hours": Theme.swiftUI(Theme.readout), "Usual": Theme.swiftUI(Theme.unlitIcon)])
            .chartLegend(.hidden)
            .chartYAxis {
                AxisMarks(position: .leading, values: [0, 0.25, 0.5, 0.75, 1]) { value in
                    AxisGridLine().foregroundStyle(Theme.swiftUI(Theme.housing))
                    AxisValueLabel { if let share = value.as(Double.self) { Text(DashboardFormat.percent(share)) } }
                        .font(Fonts.gauge(11, medium: false)).foregroundStyle(Theme.swiftUI(Theme.dim))
                }
            }
            .chartXAxis {
                AxisMarks { _ in
                    AxisValueLabel().font(Fonts.gauge(11, medium: false)).foregroundStyle(Theme.swiftUI(Theme.dim))
                }
            }
            .chartYScale(domain: 0...1)
            .frame(height: 170)
            .accessibilityLabel("Prompt-size histogram, last 3 hours against usual")
            Legend(items: [.swatch(Theme.swiftUI(Theme.readout), "Last 3 hours"), .swatch(Theme.swiftUI(Theme.unlitIcon), "Usual")])
        }
    }
}

private struct WorkloadGrid: View {
    let workload: Workload
    let loadLamp: LampColor?
    let calendar: Calendar

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Workload", aside: "Last 3 hours, usual in gray")
            Grid(alignment: .leading, horizontalSpacing: 22, verticalSpacing: 12) {
                GridRow {
                    measure(workload.medianPrompt, format: DashboardFormat.tokens, label: "Median prompt", color: loadLamp)
                    measure(workload.responsesPerHour, format: DashboardFormat.whole, label: "Responses an hour")
                }
                GridRow {
                    measure(workload.activeSessions, format: DashboardFormat.sessions, label: "Active sessions")
                    measure(workload.cachedShare, format: DashboardFormat.percent, label: "Cached input")
                }
                GridRow {
                    measure(workload.reasoningShare, format: DashboardFormat.percent, label: "Reasoning share of output")
                    measure(workload.subagentShare, format: DashboardFormat.percent, label: "Responses from subagents")
                }
            }
            if !workload.effortMix.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text(mix(\.now)).font(Fonts.gauge(15)).monospacedDigit()
                    Text("Effort mix, usual \(mix(\.usual))").font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim))
                }
            }
            if let limit = workload.usageLimit {
                VStack(alignment: .leading, spacing: 2) {
                    Text(DashboardFormat.percent(limit.usedPercent / 100)).font(Fonts.gauge(22))
                    Text(limitLabel(limit)).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim))
                }
            }
        }
    }

    private func measure(_ measure: Workload.Measure, format: (Double) -> String, label: String, color: LampColor? = nil) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                Text(measure.now.map(format) ?? "–").font(Fonts.gauge(22))
                    .foregroundStyle(measure.now != nil ? color.map(Theme.color) ?? Theme.swiftUI(Theme.readout) : Theme.swiftUI(Theme.dim))
                Text("usual \(measure.usual.map(format) ?? "–")").font(Fonts.gauge(15, medium: false)).foregroundStyle(Theme.swiftUI(Theme.dim))
            }
            Text(label).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim))
        }
        .accessibilityElement(children: .combine)
    }

    private func mix(_ side: KeyPath<Workload.EffortShare, Double>) -> String {
        workload.effortMix.filter { $0[keyPath: side] > 0 }
            .map { "\($0.effort ?? "default") \(DashboardFormat.percent($0[keyPath: side]))" }
            .joined(separator: " · ")
    }

    private func limitLabel(_ limit: UsageLimitSnapshot) -> String {
        let window = limit.windowMinutes % 60 == 0 ? "\(limit.windowMinutes / 60)-hour" : "\(limit.windowMinutes)-minute"
        guard let resets = limit.resetsAt else { return "Of the \(window) usage limit" }
        return "Of the \(window) usage limit, resets \(Copy.clock(resets, calendar))"
    }
}

// MARK: Events

private struct EventList: View {
    let model: DashboardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Events", aside: "Kept indefinitely")
            if model.feed.isEmpty {
                Text("No events yet.").foregroundStyle(Theme.swiftUI(Theme.dim))
            }
            ForEach(model.feed) { event in
                VStack(spacing: 0) {
                    Rectangle().fill(Theme.swiftUI(Theme.housing)).frame(height: 1)
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(DashboardFormat.when(event.at, now: model.now(), calendar: model.calendar))
                            .font(Fonts.gauge(13, medium: false)).foregroundStyle(Theme.swiftUI(Theme.dim))
                            .frame(width: 96, alignment: .leading)
                        HStack(alignment: .firstTextBaseline, spacing: 7) {
                            Diamond(color: event.color.map(Theme.color) ?? Theme.swiftUI(Theme.usual))
                            Text(Self.kindLabel(event)).lineLimit(1)
                        }
                        .frame(width: 136, alignment: .leading)
                        Text(Self.text(event)).fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        trailing(event)
                    }
                    .padding(.vertical, 6)
                }
            }
        }
        .alert(
            "Undo this acceptance?",
            isPresented: Binding(get: { model.pendingUndo != nil }, set: { if !$0 { model.cancelUndo() } }),
            presenting: model.pendingUndo
        ) { _ in
            Button("Undo", role: .destructive) { model.confirmUndo() }
            Button("Cancel", role: .cancel) { model.cancelUndo() }
        } message: { event in
            Text(event.undoConfirmation ?? "")
        }
    }

    @ViewBuilder private func trailing(_ event: FeedEvent) -> some View {
        if event.undoableEpochID != nil {
            Button("Undo") { model.requestUndo(event) }.buttonStyle(DashboardButtonStyle(quiet: true))
        } else if let undone = event.undoneAt {
            Text("Undone \(DashboardFormat.when(undone, now: model.now(), calendar: model.calendar))")
                .font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim))
        } else if let link = event.link {
            Link("Status page", destination: link).font(.system(size: 12))
        }
    }

    static func kindLabel(_ event: FeedEvent) -> String {
        switch event.kind {
        case .slowdown: "Slowdown"
        case .speedup: "Speedup"
        case .largePrompts: "Large prompts"
        case .failedTurns: "Failed turns"
        case .disconnects: "Disconnects"
        case .incident: "Incident"
        case .usageLimit: "Usage limit"
        case .cleared: "Cleared"
        case .ended: "Ended"
        case .statusPost: "Status post"
        case .baselineAccepted: "Accepted as usual"
        case .baselineUndone: "Baseline restored"
        case .historyGap: "History gap"
        case .collectorFailed: "Collector"
        case .other: event.title
        }
    }

    /// The entry's words: its body, led by its title where the kind alone doesn't say what happened.
    static func text(_ event: FeedEvent) -> String {
        let body = event.body.trimmingCharacters(in: .whitespacesAndNewlines)
        switch event.kind {
        case .cleared, .ended, .other:
            return body.isEmpty ? event.title : "\(event.title). \(body)"
        default:
            return body.isEmpty ? event.title : body
        }
    }
}

// MARK: Pieces

/// A big readout: the value in Barlow, its unit small and Dim, and a Dim label under it.
private struct Readout: View {
    let value: String
    let unit: String
    let label: String
    let color: LampColor?
    let size: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(value).font(Fonts.gauge(size)).foregroundStyle(color.map(Theme.color) ?? Theme.swiftUI(Theme.readout))
                Text(unit).font(Fonts.gauge(15, medium: false)).foregroundStyle(Theme.swiftUI(Theme.dim))
            }
            Text(label).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim))
        }
        .accessibilityElement(children: .combine)
    }
}

private struct Legend: View {
    enum Item: Hashable {
        case swatch(Color, String)
        case band(String)
        case triangle(String)
    }

    let items: [Item]

    var body: some View {
        HStack(spacing: 14) {
            ForEach(items, id: \.self) { item in
                HStack(spacing: 5) {
                    switch item {
                    case .swatch(let color, _):
                        RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 10, height: 10)
                    case .band:
                        RoundedRectangle(cornerRadius: 2).fill(Theme.color(.amber).opacity(0.1))
                            .overlay { RoundedRectangle(cornerRadius: 2).strokeBorder(Theme.color(.amber).opacity(0.6), style: StrokeStyle(lineWidth: 1, dash: [2, 2])) }
                            .frame(width: 10, height: 10)
                    case .triangle:
                        Image(systemName: "triangle.fill").font(.system(size: 8)).foregroundStyle(Theme.color(.red))
                    }
                    Text(Self.title(item))
                }
            }
        }
        .font(.system(size: 12))
        .foregroundStyle(Theme.swiftUI(Theme.dim))
        .accessibilityElement(children: .combine)
    }

    private static func title(_ item: Item) -> String {
        switch item {
        case .swatch(_, let title), .band(let title), .triangle(let title): title
        }
    }
}

/// The dashboard's number and time formats: English, tabular, as the visual doc's mockup.
enum DashboardFormat {
    static func seconds(_ value: Double) -> String { String(format: "%.1f", value) }
    static func whole(_ value: Double) -> String { String(Int(value.rounded())) }
    static func sessions(_ value: Double) -> String { value < 10 && value != value.rounded() ? String(format: "%.1f", value) : whole(value) }
    static func percent(_ share: Double) -> String { "\(Int((share * 100).rounded()))%" }

    /// 286000 is "286k", 1200000 is "1.2M", under 1000 in full.
    static func tokens(_ value: Double) -> String {
        switch value {
        case 1_000_000...: String(format: "%.1fM", value / 1_000_000)
        case 1_000...: "\(Int((value / 1_000).rounded()))k"
        default: whole(value)
        }
    }

    /// "Today 08:10", "Yesterday 08:10" or "Sep 15 08:10".
    static func when(_ date: Date, now: Date, calendar: Calendar) -> String {
        let clock = Copy.clock(date, calendar)
        if calendar.isDate(date, inSameDayAs: now) { return "Today \(clock)" }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: yesterday) {
            return "Yesterday \(clock)"
        }
        let months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        let parts = calendar.dateComponents([.month, .day], from: date)
        return "\(months[((parts.month ?? 1) - 1).clamped(to: 0...11)]) \(parts.day ?? 1) \(clock)"
    }
}

private extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self { min(max(self, range.lowerBound), range.upperBound) }
}
