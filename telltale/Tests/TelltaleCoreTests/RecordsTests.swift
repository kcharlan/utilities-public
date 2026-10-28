import Foundation
import Testing
@testable import TelltaleCore

@Suite struct RecordsTests {
    /// Spec section 6.1: throughput = output tokens / duration, only from 300 output tokens up.
    @Test func throughputNeedsAtLeast300OutputTokens() {
        let long = Synthetic.response(1, endingAt: 100, duration: 10, outputTokens: 300)
        #expect(long.duration == 10)
        #expect(long.throughput == 30)
        let short = Synthetic.response(2, endingAt: 100, duration: 10, outputTokens: 299)
        #expect(short.throughput == nil)
        #expect(short.duration == 10)
        let instant = Synthetic.response(3, endingAt: 100, duration: 0, outputTokens: 500)
        #expect(instant.throughput == nil)
        #expect(Synthetic.response(4, endingAt: 100, duration: 4, outputTokens: 1_000).throughput == 250)
    }

    @Test func incidentIsResolvedForResolvedOrPostmortem() {
        func incident(_ status: String) -> IncidentRecord {
            IncidentRecord(
                source: "example-status", id: "inc_synthetic_1", name: "Synthetic incident", status: status,
                publishedAt: Synthetic.at(0), updatedAt: Synthetic.at(60), link: URL(string: "https://status.example.com/incidents/1")!,
                history: [StatusChange(at: Synthetic.at(0), status: "investigating")], impacts: [])
        }
        for status in ["resolved", "postmortem"] { #expect(incident(status).isResolved, "\(status)") }
        for status in ["investigating", "identified", "monitoring", ""] { #expect(!incident(status).isResolved, "\(status)") }
    }

    @Test func providerIDEncodesAsPlainString() throws {
        #expect(ProviderID.codex.rawValue == "codex")
        let encoded = try JSONEncoder().encode([ProviderID.codex])
        #expect(String(decoding: encoded, as: UTF8.self) == "[\"codex\"]")
        #expect(try JSONDecoder().decode([ProviderID].self, from: encoded) == [.codex])
        #expect(Set([ProviderID.codex, ProviderID(rawValue: "codex")]).count == 1)
    }

    @Test func recordsRoundTripThroughCodable() throws {
        let incident = IncidentRecord(
            source: "example-status", id: "inc_synthetic_2", name: "Synthetic degradation", status: "monitoring",
            publishedAt: Synthetic.at(0), updatedAt: Synthetic.at(60), link: URL(string: "https://status.example.com/incidents/2")!,
            history: [StatusChange(at: Synthetic.at(0), status: "investigating"), StatusChange(at: Synthetic.at(30), status: "monitoring")],
            impacts: [ComponentImpact(componentID: "component_synthetic_1", status: "degraded_performance", start: Synthetic.at(0), end: nil)])
        let encoder = JSONEncoder()
        let decoder = JSONDecoder()
        #expect(try decoder.decode(IncidentRecord.self, from: encoder.encode(incident)) == incident)
        let response = Synthetic.response(1, endingAt: 100)
        #expect(try decoder.decode(ResponseRecord.self, from: encoder.encode(response)) == response)
        let states: [SetupState] = [.ready, .notSetUp("No data"), .formatProblem("Changed")]
        #expect(try decoder.decode([SetupState].self, from: encoder.encode(states)) == states)
        let signals: Set<Signal> = [.speed, .errors, .link, .provider, .load, .collector]
        #expect(try decoder.decode(Set<Signal>.self, from: encoder.encode(signals)) == signals)
    }
}
