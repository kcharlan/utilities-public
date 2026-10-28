import Foundation
import TelltaleCore

/// Conspicuously synthetic records for the store tests (fixture conventions: session
/// ids `00000000-0000-4000-8000-0000000000NN`, response ids `resp_synthetic_NN`).
enum Synthetic {
    /// 2026-01-01 00:00:00 UTC, an arbitrary fixed origin.
    static let origin = Date(timeIntervalSince1970: 1_767_225_600)
    static let otherProvider = ProviderID(rawValue: "example.provider")

    static func at(_ seconds: TimeInterval) -> Date { origin.addingTimeInterval(seconds) }

    static func response(
        _ number: Int,
        provider: ProviderID = .codex,
        model: String = "example-model-1.0",
        endingAt end: TimeInterval,
        duration: TimeInterval = 10,
        outputTokens: Int = 500
    ) -> ResponseRecord {
        ResponseRecord(
            provider: provider, model: model, effort: "medium", serviceTier: nil,
            sessionID: String(format: "00000000-0000-4000-8000-%012ld", number), isSubagent: false,
            turnID: "turn_synthetic_\(number)", responseID: "resp_synthetic_\(number)",
            start: at(end - duration), end: at(end),
            inputTokens: 1_000, cachedInputTokens: 200, outputTokens: outputTokens, reasoningTokens: nil)
    }

    static func failedTurn(_ number: Int, message: String = "synthetic failure", completed: Bool = false) -> FailedTurnRecord {
        FailedTurnRecord(
            provider: .codex, threadID: "thread_synthetic_\(number)", turnID: "turn_synthetic_\(number)",
            startedAt: at(Double(number) * 60), completedAt: completed ? at(Double(number) * 60 + 5) : nil,
            model: "example-model-1.0", errorCode: "serverOverloaded", message: message)
    }
}
