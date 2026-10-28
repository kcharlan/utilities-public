import Foundation

/// Spec section 7.1's input-size buckets (input tokens): < 50k, 50–100k, 100–200k, 200–300k, 300k+.
/// Each lower edge belongs to the bucket it starts.
public enum InputBucket: String, Sendable, Hashable, Codable, CaseIterable {
    case under50k, from50k, from100k, from200k, from300k

    public init(inputTokens: Int) {
        switch inputTokens {
        case ..<50_000: self = .under50k
        case ..<100_000: self = .from50k
        case ..<200_000: self = .from100k
        case ..<300_000: self = .from200k
        default: self = .from300k
        }
    }

    /// The bucket's name in "Not enough history yet for {label} prompts" (spec section 8).
    public var label: String {
        switch self {
        case .under50k: "under 50k"
        case .from50k: "50–100k"
        case .from100k: "100–200k"
        case .from200k: "200–300k"
        case .from300k: "300k+"
        }
    }
}
