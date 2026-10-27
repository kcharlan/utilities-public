import Foundation
import TelltaleCore

/// Codex model names (spec section 6.1, Model names). Model ids look like `gpt-6.1-sol`:
/// a vendor word, a version and a family.
public struct ModelNames: ModelNaming {
    public init() {}

    /// The id without its vendor word and version, each remaining word capitalized:
    /// `gpt-6.1-sol` is "Sol". When nothing would remain, the id itself.
    public func displayName(model: String) -> String {
        let parts = Parts(model)
        guard !parts.family.isEmpty else { return model }
        return parts.family.map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined(separator: " ")
    }

    /// True when the title holds every family word and the version, case-insensitive, each as a
    /// whole word or number (plan call: "Solar" is not "Sol", "16.1" is not "6.1"). A model with no
    /// family word left uses its vendor word as the family; one with no version never matches.
    public func incidentTitle(_ title: String, names model: String) -> Bool {
        let parts = Parts(model)
        guard let version = parts.version else { return false }
        let family = parts.family.isEmpty ? parts.vendor.map { [$0] } ?? [] : parts.family
        guard !family.isEmpty else { return false }
        let lowered = title.lowercased()
        return Self.contains(lowered, version.lowercased()) && family.allSatisfy { Self.contains(lowered, $0.lowercased()) }
    }

    /// `gpt-6.1-sol`: vendor `gpt`, version `6.1`, family `[sol]`.
    private struct Parts {
        var vendor: String?
        var version: String?
        var family: [String] = []

        init(_ model: String) {
            let words = model.split(separator: "-").map(String.init)
            var rest = words[...]
            // A vendor word is the first word when a version follows it.
            if words.count >= 2, !Self.isVersion(words[0]), Self.isVersion(words[1]) {
                vendor = words[0]
                rest = rest.dropFirst()
            }
            for word in rest {
                if Self.isVersion(word) {
                    if version == nil { version = word }
                } else {
                    family.append(word)
                }
            }
        }

        /// Digits, optionally dotted: `6`, `6.1`.
        static func isVersion(_ word: String) -> Bool {
            !word.isEmpty && word.split(separator: ".", omittingEmptySubsequences: false)
                .allSatisfy { !$0.isEmpty && $0.allSatisfy(\.isASCII) && $0.allSatisfy(\.isNumber) }
        }
    }

    /// Whether `needle` occurs in `text` with no letter or digit touching it, and not continued by
    /// a dotted number (so `6.1` does not match inside `6.12` or `6.1.2`).
    private static func contains(_ text: String, _ needle: String) -> Bool {
        var searchStart = text.startIndex
        while let range = text.range(of: needle, range: searchStart..<text.endIndex) {
            let before = range.lowerBound > text.startIndex ? text[text.index(before: range.lowerBound)] : nil
            let after = range.upperBound < text.endIndex ? text[range.upperBound] : nil
            let afterNext = after != nil && text.index(after: range.upperBound) < text.endIndex
                ? text[text.index(after: range.upperBound)] : nil
            let touchesBefore = before.map { $0.isLetter || $0.isNumber || ($0 == "." && needle.first?.isNumber == true) } ?? false
            let touchesAfter = after.map { $0.isLetter || $0.isNumber } ?? false
            let continuesNumber = after == "." && afterNext?.isNumber == true
            if !touchesBefore && !touchesAfter && !continuesNumber { return true }
            searchStart = text.index(after: range.lowerBound)
        }
        return false
    }
}
