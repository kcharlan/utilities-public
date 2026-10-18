import Foundation
import Testing
@testable import BrewVersionCore

struct PackageNameTests {
    static let accepted = ["synthetic-formula", "python@3.13", "a", "g++", "x.y_z-1"]
    static let rejected = ["", "Synthetic", "-x", "@x", "a b", "a/b", ".x", "a\n"]

    @Test func validation() {
        for raw in Self.accepted { #expect(PackageName(raw)?.rawValue == raw) }
        for raw in Self.rejected { #expect(PackageName(raw) == nil) }
    }

    @Test func decodingValidatesName() throws {
        for raw in Self.accepted {
            let data = try JSONEncoder().encode(raw)
            #expect(try JSONDecoder().decode(PackageName.self, from: data).description == raw)
        }
        for raw in Self.rejected {
            let data = try JSONEncoder().encode(raw)
            let error = #expect(throws: DecodingError.self) { try JSONDecoder().decode(PackageName.self, from: data) }
            #expect(error.map(invalidNameError) == true)
            let nested = try JSONSerialization.data(withJSONObject: [
                "etag": "synthetic-etag", "listing": ["name": raw, "kind": "formula", "version": "1", "revision": 0,
                "autoUpdates": false, "appNames": []]
            ])
            let nestedError = #expect(throws: DecodingError.self) { try JSONDecoder().decode(CachedListing.self, from: nested) }
            #expect(nestedError.map(invalidNameError) == true)
        }
    }

    private var invalidNameError: (any Error) -> Bool {
        { if case DecodingError.dataCorrupted = $0 { true } else { false } }
    }

    @Test func preferences() {
        #expect(KindPreference.auto.candidates == [.formula, .cask])
        #expect(KindPreference.auto.label == "formula cask")
        #expect(KindPreference(.formula) == .formula)
        #expect(KindPreference(.cask).candidates == [.cask])
        #expect(KindPreference.formula.label == "formula")
        #expect(KindPreference.cask.label == "cask")
    }
}
