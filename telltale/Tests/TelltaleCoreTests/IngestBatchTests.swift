import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct IngestBatchTests {
    @Test func batchDropsRecordsFromBeforeTheCutoff() {
        let cutoff = Date(timeIntervalSince1970: 1_800_000_000)
        let old = cutoff.addingTimeInterval(-1)
        var synth = Synth()
        let responses = [synth.response(throughput: 40, end: old), synth.response(throughput: 40, end: cutoff)]
        let compactions = [old, cutoff].enumerated().map { index, at in
            CompactionRecord(provider: .codex, lineID: "synthetic-\(index)", sessionID: "synthetic", agentID: nil,
                             at: at, trigger: .auto, tokensBefore: 100, tokensAfter: nil, duration: nil, precomputed: false)
        }
        let events = [old, cutoff].enumerated().map { index, at in
            ConnectionEventRecord(provider: .codex, sourceID: "synthetic-\(index)", at: at, kind: .retry, detail: "synthetic")
        }
        let failure = FailedTurnRecord(provider: .codex, threadID: "synthetic", turnID: "synthetic", startedAt: old,
                                       errorCode: "synthetic", message: "synthetic")
        let gap = DateInterval(start: old, duration: 1)
        let limit = UsageLimitSnapshot(provider: .codex, at: old, usedPercent: 20, windowMinutes: 60)
        var batch = IngestBatch(responses: responses, compactions: compactions, failedTurns: [failure], connectionEvents: events,
                                connectionGaps: [gap], usageLimit: limit, sourceVersion: "synthetic", excludedServerToolResponses: 4)
        batch.excludedClientErrors = 5
        batch.invalidCompactions = 6
        let result = batch.droppingBefore(cutoff)
        #expect(result.dropped == 3)
        #expect(result.batch.responses == [responses[1]])
        #expect(result.batch.compactions == [compactions[1]])
        #expect(result.batch.connectionEvents == [events[1]])
        #expect(result.batch.failedTurns == [failure])
        #expect(result.batch.connectionGaps == [gap])
        #expect(result.batch.usageLimit == limit)
        #expect(result.batch.sourceVersion == "synthetic")
        #expect(result.batch.excludedServerToolResponses == 4)
        #expect(result.batch.excludedClientErrors == 5)
        #expect(result.batch.invalidCompactions == 6)
    }
}
