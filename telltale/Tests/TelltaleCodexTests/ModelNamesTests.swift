import Testing
import TelltaleCodex

@Suite struct ModelNamesTests {
    let names = ModelNames()

    @Test func displayName() {
        // Spec section 6.1: drop the vendor prefix and version, capitalize the rest.
        #expect(names.displayName(model: "gpt-6.1-sol") == "Sol")
        #expect(names.displayName(model: "gpt-6-astra") == "Astra")
        #expect(names.displayName(model: "gpt-5.1-codex-mini") == "Codex Mini")
        // Nothing left after dropping prefix and version: show the id itself.
        #expect(names.displayName(model: "gpt-5") == "gpt-5")
    }

    @Test func titleMatchNeedsFamilyAndVersion() {
        // Spec section 6.1's examples.
        #expect(names.incidentTitle("6.1 Sol Degraded Model Performance", names: "gpt-6.1-sol"))
        #expect(names.incidentTitle("GPT-6.1 Sol Codex", names: "gpt-6.1-sol"))
        // Case-insensitive.
        #expect(names.incidentTitle("elevated errors on gpt-6.1-SOL", names: "gpt-6.1-sol"))
        // Both are needed.
        #expect(!names.incidentTitle("Sol Degraded Model Performance", names: "gpt-6.1-sol"))
        #expect(!names.incidentTitle("6.1 Degraded Model Performance", names: "gpt-6.1-sol"))
        #expect(!names.incidentTitle("6.2 Sol Degraded Model Performance", names: "gpt-6.1-sol"))
        // Whole words and whole versions only (plan call): no match inside another word or number.
        #expect(!names.incidentTitle("Solar 6.1 outage", names: "gpt-6.1-sol"))
        #expect(!names.incidentTitle("16.1 Sol outage", names: "gpt-6.1-sol"))
        #expect(!names.incidentTitle("6.12 Sol outage", names: "gpt-6.1-sol"))
        // Every family word must appear.
        #expect(names.incidentTitle("GPT-5.1 Codex Mini errors", names: "gpt-5.1-codex-mini"))
        #expect(!names.incidentTitle("GPT-5.1 Codex errors", names: "gpt-5.1-codex-mini"))
        // With no family word left, the vendor word is the family.
        #expect(names.incidentTitle("GPT-5 elevated errors", names: "gpt-5"))
        #expect(!names.incidentTitle("GPT-5.1 elevated errors", names: "gpt-5"))
    }
}
