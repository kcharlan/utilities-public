import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

/// Drives an `EpisodeMachine` with speed indexes at consecutive 5-minute points, judged by
/// `RuleSettings.defaults` (slower: fire ≤ 0.85 for 15 min, clear > 0.92 for 30 min, red ≤ 0.70).
struct MachineDriver {
    let start = Synth.local(2026, 9, 4, 9, 0)
    var rule = RuleSettings.defaults.slower
    var direction = Direction.slower
    var machine: EpisodeMachine
    /// The next point's index (0 is `start`).
    var next = 0
    /// Every transition, with the index of the point that produced it.
    var log: [(point: Int, transition: Transition)] = []

    init(rule: SpeedRule = RuleSettings.defaults.slower, direction: Direction = .slower) {
        self.rule = rule
        self.direction = direction
        machine = EpisodeMachine(
            firePoints: EvaluationPoints.count(forMinutes: rule.durationMinutes),
            clearPoints: EvaluationPoints.count(forMinutes: rule.clearMinutes),
            windowMinutes: SpeedIndex.windowMinutes, color: direction == .slower ? .amber : .blue)
    }

    func time(_ point: Int) -> Date { start.addingTimeInterval(Double(point) * 300) }

    /// Steps once per index (nil is an unknown point) and returns the transitions this call produced.
    @discardableResult
    mutating func feed(_ indexes: [Double?]) -> [(point: Int, transition: Transition)] {
        var produced: [(point: Int, transition: Transition)] = []
        for index in indexes {
            let conditions = rule.conditions(index: index, direction: direction)
            for transition in machine.step(at: time(next), trigger: conditions.trigger, clear: conditions.clear, red: conditions.red, idle: false) {
                produced.append((next, transition))
            }
            next += 1
        }
        log += produced
        return produced
    }

    @discardableResult
    mutating func idle() -> [Transition] {
        let transitions = machine.step(at: time(next), trigger: .unknown, clear: .unknown, red: .unknown, idle: true)
        log += transitions.map { (next, $0) }
        next += 1
        return transitions
    }

    func repeated(_ index: Double?, _ count: Int) -> [Double?] { Array(repeating: index, count: count) }
}

func transitions(_ log: [(point: Int, transition: Transition)]) -> [Transition] { log.map(\.transition) }
func points(_ log: [(point: Int, transition: Transition)]) -> [Int] { log.map(\.point) }

@Suite struct EpisodeMachineTests {
    @Test func firesAfterFirePoints() {
        var driver = MachineDriver()
        #expect(driver.feed([0.80, 0.80]).isEmpty)
        let fired = driver.feed([0.80])
        // 15 minutes is 3 consecutive points; onset is the first true point minus the 15-minute window.
        #expect(points(fired) == [2])
        #expect(transitions(fired) == [.fired(onset: driver.time(0).addingTimeInterval(-900), severity: .amber)])
        #expect(driver.machine.isOpen)
        #expect(driver.feed(driver.repeated(0.80, 5)).isEmpty)
    }

    @Test func nonGridDurationsRoundUpAndNeverFireEarly() {
        for minutes in 1...60 {
            let count = EvaluationPoints.count(forMinutes: minutes)
            // Never early: the points span at least the duration; never late by a whole point.
            #expect(count * 5 >= minutes && (count - 1) * 5 < minutes, "\(minutes) minutes")
        }
        // 7 minutes: 2 points. 3 minutes: 1 point. 12 minutes: 3 points.
        for (minutes, firePoint) in [(7, 1), (3, 0), (12, 2)] {
            var rule = RuleSettings.defaults.slower
            rule.durationMinutes = minutes
            var driver = MachineDriver(rule: rule)
            driver.feed(driver.repeated(0.80, 4))
            #expect(points(driver.log) == [firePoint], "\(minutes) minutes")
        }
        // A 7-minute clear needs 2 points within the band, not 1.
        var rule = RuleSettings.defaults.slower
        rule.clearMinutes = 7
        var driver = MachineDriver(rule: rule)
        driver.feed(driver.repeated(0.80, 3))
        #expect(driver.feed([0.95]).isEmpty)
        #expect(transitions(driver.feed([0.95])) == [.cleared])
    }

    @Test func unknownPointsHoldNotReset() {
        var driver = MachineDriver()
        #expect(driver.feed([0.80, nil, 0.80, nil, nil]).isEmpty)
        let fired = driver.feed([0.80])
        #expect(points(fired) == [5])
        #expect(transitions(fired) == [.fired(onset: driver.time(0).addingTimeInterval(-900), severity: .amber)])
        // Unknown points don't clear an open episode either.
        driver.feed([0.95, 0.95, nil, nil, 0.95, 0.95, nil, 0.95])
        #expect(points(driver.log) == [5])
        #expect(transitions(driver.feed([0.95])) == [.cleared])
    }

    @Test func falseResetsStreak() {
        var driver = MachineDriver()
        #expect(driver.feed([0.80, 0.80, 0.90, 0.80, 0.80]).isEmpty)
        let fired = driver.feed([0.80])
        // The streak restarted at point 3.
        #expect(transitions(fired) == [.fired(onset: driver.time(3).addingTimeInterval(-900), severity: .amber)])
    }

    @Test func clearsAfterClearPoints() {
        var driver = MachineDriver()
        driver.feed(driver.repeated(0.80, 3))
        // 30 minutes is 6 consecutive points above 0.92.
        #expect(driver.feed(driver.repeated(0.95, 5)).isEmpty)
        let cleared = driver.feed([0.95])
        #expect(transitions(cleared) == [.cleared])
        #expect(points(cleared) == [8])
        #expect(!driver.machine.isOpen)
        #expect(driver.machine.isAtRest)
    }

    @Test func outsideBandButPastTriggerDoesNotClear() {
        var driver = MachineDriver()
        driver.feed(driver.repeated(0.80, 3))
        // 0.90 no longer triggers (> 0.85) but isn't inside the clear band (> 0.92).
        #expect(driver.feed(driver.repeated(0.90, 24)).isEmpty)
        #expect(driver.machine.isOpen)
        // A point outside the band resets a clear streak.
        #expect(driver.feed(driver.repeated(0.95, 5) + [0.90] + driver.repeated(0.95, 5)).isEmpty)
        #expect(transitions(driver.feed([0.95])) == [.cleared])
    }

    @Test func flappingAroundThresholdProducesOneEpisode() {
        var driver = MachineDriver()
        // Two hours flapping across both the trigger and the clear band.
        let flapping: [Double?] = (0..<24).map { $0.isMultiple(of: 2) ? 0.80 : 0.95 }
        driver.feed(driver.repeated(0.80, 3) + flapping + driver.repeated(0.95, 6))
        #expect(transitions(driver.log) == [.fired(onset: driver.time(0).addingTimeInterval(-900), severity: .amber), .cleared])
    }

    @Test func idleEndsSilently() {
        var driver = MachineDriver()
        driver.feed(driver.repeated(0.80, 3))
        #expect(driver.idle() == [.idleEnded])
        #expect(!driver.machine.isOpen)
        #expect(driver.idle().isEmpty)
        #expect(driver.machine.isAtRest)
    }

    @Test func nextActivityAfterIdleStartsFreshEpisode() {
        var driver = MachineDriver()
        driver.feed(driver.repeated(0.80, 5))
        driver.idle()
        // A fresh streak is needed; the episode's earlier points don't count.
        #expect(driver.feed([0.80, 0.80]).isEmpty)
        let fired = driver.feed([0.80])
        #expect(transitions(fired) == [.fired(onset: driver.time(6).addingTimeInterval(-900), severity: .amber)])

        // A partial streak doesn't survive idleness either.
        var partial = MachineDriver()
        partial.feed([0.80, 0.80])
        partial.idle()
        #expect(partial.feed([0.80, 0.80]).isEmpty)
        #expect(partial.feed([0.80]).count == 1)
    }

    @Test func fireAtRedIsOneTransition() {
        var driver = MachineDriver()
        // 0.60 is past 2× the threshold (≤ 0.70) for the whole duration.
        driver.feed(driver.repeated(0.60, 12))
        #expect(transitions(driver.log) == [.fired(onset: driver.time(0).addingTimeInterval(-900), severity: .red)])
        #expect(driver.machine.severity == .red)
    }

    @Test func escalatesOnceWhenRedArrivesLater() {
        var driver = MachineDriver()
        driver.feed(driver.repeated(0.80, 3))
        #expect(driver.feed([0.60, 0.60]).isEmpty)
        let escalated = driver.feed([0.60])
        #expect(transitions(escalated) == [.escalated])
        #expect(points(escalated) == [5])
        #expect(driver.machine.severity == .red)
        // Later red streaks in the same episode stay silent.
        #expect(driver.feed([0.80] + driver.repeated(0.60, 6)).isEmpty)
        // A broken red streak doesn't escalate: amber, red, red, amber, red, red.
        var broken = MachineDriver()
        broken.feed(broken.repeated(0.80, 3) + [0.60, 0.60, 0.80, 0.60, 0.60])
        #expect(transitions(broken.log).count == 1)
    }

    @Test func onsetIsFirstTruePointMinusWindow() {
        var driver = MachineDriver()
        driver.feed([0.95, nil, 0.80, 0.80, nil, 0.80])
        #expect(transitions(driver.log) == [.fired(onset: driver.time(2).addingTimeInterval(-15 * 60), severity: .amber)])

        // A machine without a window (non-speed rules) dates onset at the first true point.
        var machine = EpisodeMachine(firePoints: 1, clearPoints: 1, windowMinutes: 0)
        let at = Synth.local(2026, 9, 4, 9, 5)
        #expect(machine.step(at: at, trigger: .true, clear: .false, red: .false, idle: false) == [.fired(onset: at, severity: .amber)])
    }

    @Test func fasterUsesBlueAndNeverEscalates() {
        var driver = MachineDriver(rule: RuleSettings.defaults.faster, direction: .faster)
        driver.feed(driver.repeated(1.70, 10) + driver.repeated(1.05, 6))
        #expect(transitions(driver.log) == [.fired(onset: driver.time(0).addingTimeInterval(-900), severity: .blue), .cleared])
    }

    @Test func stateRoundTripsThroughJSON() throws {
        var driver = MachineDriver()
        driver.feed([0.80, 0.80])
        let data = try JSONEncoder().encode(driver.machine)
        driver.machine = try JSONDecoder().decode(EpisodeMachine.self, from: data)
        #expect(transitions(driver.feed([0.80])) == [.fired(onset: driver.time(0).addingTimeInterval(-900), severity: .amber)])
    }

    @Test func lampColorsOrderBySeverity() {
        // Spec section 7.4: red, amber, blue; the most severe compares greatest.
        #expect(LampColor.blue < LampColor.amber && LampColor.amber < LampColor.red)
        #expect([LampColor.blue, .red, .amber].max() == .red)
        #expect(LampColor.allCases.map(\.rawValue) == ["red", "amber", "blue"])
    }
}
