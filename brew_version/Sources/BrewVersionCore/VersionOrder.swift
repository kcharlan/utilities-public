import Foundation

/// Semantic port of Homebrew Version, tokens and token comparators at commit
/// 19fe946b9a257cb41ebb5cef5c592ba7923d1f3b, Library/Homebrew/version.rb.
/// Copyright and BSD redistribution terms: Resources/Homebrew-LICENSE.txt.
public enum VersionOrder {
    public static func compare(_ a: String, _ b: String) -> ComparisonResult {
        if a == b { return .orderedSame }
        let headA = a.range(of: #"\AHEAD(?:-.*)?\Z"#, options: .regularExpression) != nil
        let headB = b.range(of: #"\AHEAD(?:-.*)?\Z"#, options: .regularExpression) != nil
        if headA || headB { return result(headA == headB ? 0 : headA ? 1 : -1) }
        let left = tokens(a), right = tokens(b)
        let maximum = max(left.count, right.count)
        var l = 0, r = 0
        // Homebrew bounds this by the LEFT cursor, even when the right cursor
        // advances alone over zero tokens. This is intentionally asymmetric.
        while l < maximum {
            let x = l < left.count ? left[l] : .null
            let y = r < right.count ? right[r] : .null
            let comparison = x.compare(y)
            if comparison == 0 { l += 1; r += 1 }
            else if x.kind == .numeric && y.kind != .numeric {
                if x.compare(.null) > 0 { return .orderedDescending }
                l += 1
            } else if x.kind != .numeric && y.kind == .numeric {
                if y.compare(.null) > 0 { return .orderedAscending }
                r += 1
            } else { return result(comparison) }
        }
        return .orderedSame
    }

    private enum Kind: Int { case null, string, numeric, alpha, beta, pre, rc, patch, post }
    private struct Token {
        let kind: Kind
        let value: String
        static let null = Token(kind: .null, value: "")
        var revision: String {
            String(value.drop { !$0.isASCII || !$0.isNumber }.prefix { $0.isASCII && $0.isNumber })
        }
        func compare(_ other: Token) -> Int {
            if kind == .null {
                switch other.kind {
                case .null: return 0
                case .numeric: return number(other.value, "0") == 0 ? 0 : -1
                case .alpha, .beta, .pre, .rc: return 1
                default: return -1
                }
            }
            if kind == .numeric {
                if other.kind == .numeric { return number(value, other.value) }
                if other.kind == .null { return number(value, "0") == 0 ? 0 : 1 }
                return 1
            }
            if kind.rawValue >= Kind.alpha.rawValue && other.kind == kind {
                return number(revision, other.revision)
            }
            if kind.rawValue >= Kind.alpha.rawValue && other.kind.rawValue >= Kind.alpha.rawValue {
                // Patch/Post fall back to StringToken against each other.
                if !(kind == .patch && other.kind == .post || kind == .post && other.kind == .patch) {
                    return kind.rawValue < other.kind.rawValue ? -1 : 1
                }
            }
            if other.kind == .numeric { return -1 }
            if other.kind == .null { return -other.compare(self) }
            return value == other.value ? 0 : value.utf8.lexicographicallyPrecedes(other.value.utf8) ? -1 : 1
        }
    }
    // Keep union order and the PostToken wildcard exactly as upstream.
    private static let patterns: [(Kind, String)] = [
        (.alpha, "alpha[0-9]*|a[0-9]+"), (.beta, "beta[0-9]*|b[0-9]+"),
        (.pre, "pre[0-9]*"), (.rc, "rc[0-9]*"), (.patch, "p[0-9]*"),
        (.post, ".post[0-9]+"), (.numeric, "[0-9]+"), (.string, "[a-z]+")
    ]
    private static let scanner = try! NSRegularExpression(
        pattern: patterns.map { "(\($0.1))" }.joined(separator: "|"), options: .caseInsensitive)
    private static func tokens(_ value: String) -> [Token] {
        return scanner.matches(in: value, range: NSRange(value.startIndex..., in: value)).map { match in
            let raw = String(value[Range(match.range, in: value)!])
            let kind = patterns.indices.first { match.range(at: $0 + 1).location != NSNotFound }
                .map { patterns[$0].0 } ?? .string
            return Token(kind: kind, value: raw)
        }
    }
    private static func number(_ a: String, _ b: String) -> Int {
        let x = a.drop { $0 == "0" }, y = b.drop { $0 == "0" }
        if x.count != y.count { return x.count < y.count ? -1 : 1 }
        return x == y ? 0 : x.utf8.lexicographicallyPrecedes(y.utf8) ? -1 : 1
    }
    private static func result(_ value: Int) -> ComparisonResult {
        value == 0 ? .orderedSame : value < 0 ? .orderedAscending : .orderedDescending
    }
}
