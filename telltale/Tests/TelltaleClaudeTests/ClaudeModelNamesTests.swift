import Testing
@testable import TelltaleClaude

@Suite struct ClaudeModelNamesTests {
    @Test func displayNames() {
        let names = ClaudeModelNames()
        #expect(names.displayName(model: "claude-opus-5-5") == "Opus 5.5")
        #expect(names.displayName(model: "claude-haiku-4-5-20251001") == "Haiku 4.5")
        #expect(names.displayName(model: "claude-opus-5-5[1m]") == "Opus 5.5 (1M)")
        #expect(names.displayName(model: "unknown") == "unknown")
    }
    @Test func titleVersionBoundary() {
        let names = ClaudeModelNames()
        #expect(names.incidentTitle("Claude Fable 5 and Claude Fable 5.1", names: "claude-fable-5"))
        #expect(!names.incidentTitle("Claude Fable 5.1", names: "claude-fable-5"))
    }
    @Test func titleDoesNotBorrowAnotherFamilyVersion() {
        let names = ClaudeModelNames()
        let title = "Elevated errors for Claude Opus 5.5 and Claude Sonnet 5.1"
        #expect(!names.incidentTitle(title, names: "claude-opus-5-1"))
        #expect(names.incidentTitle("Claude Opus 5.5 and Claude Opus 5.1", names: "claude-opus-5-1"))
    }
    @Test func allModelsPhrasesMatchAnyModel() {
        let names = ClaudeModelNames()
        #expect(!names.incidentTitle("Small models degraded", names: "claude-opus-5-5"))
        for title in ["Multiple models degraded", "Other models affected", "All models slow", "Claude services unavailable"] {
            #expect(names.incidentTitle(title, names: "claude-opus-5-5"))
        }
    }
    @Test func modelSpecificTitles() {
        let names = ClaudeModelNames()
        #expect(names.incidentTitleIsModelSpecific("Claude Mythos 5.1 issues"))
        #expect(!names.incidentTitleIsModelSpecific("All Claude models including Claude Mythos 5.1"))
    }
}
