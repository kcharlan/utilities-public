import Foundation

public enum DisplayNames {
    /// Rewrites the model position in known speed copy, including an older generated suffix.
    static func speedText(_ text: String, base: String, name: String, provider: String) -> String {
        for prefix in ["", "\(provider): "] {
            let start = prefix + base
            guard text.hasPrefix(start) else { continue }
            let rest = text.dropFirst(start.count)
            for verb in [" is ", " has been "] {
                guard let range = rest.range(of: verb) else { continue }
                let suffix = rest[..<range.lowerBound]
                guard suffix.isEmpty || (suffix.hasPrefix(" (") && suffix.hasSuffix(")")) else { continue }
                return prefix + name + rest[range.lowerBound...]
            }
        }
        return text
    }
    /// Disambiguate equal display names within the IDs shown together.
    public static func disambiguated(_ ids: [String], naming: any ModelNaming) -> [String: String] {
        let unique = Array(Set(ids)).sorted()
        var result = Dictionary(uniqueKeysWithValues: unique.map { ($0, naming.displayName(model: $0)) })
        let groups = Dictionary(grouping: unique, by: { result[$0]! })
        for (name, group) in groups where group.count > 1 {
            let pieces = group.map { $0.split(separator: "-", omittingEmptySubsequences: false).map(String.init) }
            var prefix = 0
            while pieces.allSatisfy({ $0.count > prefix && $0[prefix] == pieces[0][prefix] }) { prefix += 1 }
            var suffix = 0
            while pieces.allSatisfy({ $0.count > prefix + suffix && $0[$0.count - 1 - suffix] == pieces[0][pieces[0].count - 1 - suffix] }) { suffix += 1 }
            for (index, id) in group.enumerated() {
                let parts = pieces[index]
                let difference = parts[prefix..<(parts.count - suffix)].joined(separator: "-")
                result[id] = "\(name) (\(difference.isEmpty ? id : difference))"
            }
        }
        // A generated name may itself collide with an unrelated display name.
        var used: Set<String> = []
        for id in unique {
            let candidate = result[id]!
            if used.insert(candidate).inserted { continue }
            var number = 2
            var next = "\(candidate) (\(id))"
            while !used.insert(next).inserted {
                next = "\(candidate) (\(id), \(number))"
                number += 1
            }
            result[id] = next
        }
        return result
    }
}
