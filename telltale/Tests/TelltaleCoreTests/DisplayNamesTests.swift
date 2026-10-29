import Testing
@testable import TelltaleCore

private struct CollisionNaming: ModelNaming {
    func displayName(model: String) -> String { model.hasPrefix("synthetic-model-") ? "Example" : model }
    func incidentTitle(_ title: String, names model: String) -> Bool { false }
}

@Suite struct DisplayNamesTests {
    @Test func collidingNamesGainTheDifference() {
        let names = DisplayNames.disambiguated(["synthetic-model-alpha", "synthetic-model-beta"], naming: CollisionNaming())
        #expect(names["synthetic-model-alpha"] == "Example (alpha)")
        #expect(names["synthetic-model-beta"] == "Example (beta)")
    }

    @Test func distinctNamesAreUnchanged() {
        let names = DisplayNames.disambiguated(["synthetic-model-alpha", "Sample"], naming: CollisionNaming())
        #expect(names["synthetic-model-alpha"] == "Example")
        #expect(names["Sample"] == "Sample")
    }
}

private struct AdversarialNaming: ModelNaming {
    func displayName(model: String) -> String {
        switch model {
        case "x-a", "x-b": "Example"
        case "other": "Example (a)"
        case "third": "Example (x-a)"
        default: "Example (Example (a))"
        }
    }
    func incidentTitle(_ title: String, names model: String) -> Bool { false }
}

@Test func generatedNamesRemainUnique() {
    let ids = ["x-a", "x-b", "other", "third", "fourth"]
    let names = DisplayNames.disambiguated(ids, naming: AdversarialNaming())
    #expect(Set(names.values).count == ids.count)
}

@Test func differingLengthIDsRemainDistinct() {
    let ids = ["synthetic-model", "synthetic-model-alpha"]
    let names = DisplayNames.disambiguated(ids, naming: FeedAllSameNaming())
    #expect(Set(names.values).count == 2)
    #expect(names["synthetic-model-alpha"] == "Example (alpha)")
}

private struct FeedAllSameNaming: ModelNaming {
    func displayName(model: String) -> String { "Example" }
    func incidentTitle(_ title: String, names model: String) -> Bool { false }
}
