import Foundation
import TelltaleCore

public struct ClaudeModelNames: ModelNaming {
    public init() {}

    private func parts(_ model: String) -> (String, String, String?)? {
        let pattern = #"^claude-([a-z]+)-([0-9]+(?:-[0-9]+)*?)(?:-[0-9]{8})?(?:\[([^]]+)\])?$"#
        guard let re = try? NSRegularExpression(pattern: pattern),
              let match = re.firstMatch(in: model, range: NSRange(model.startIndex..., in: model)),
              let family = Range(match.range(at: 1), in: model), let version = Range(match.range(at: 2), in: model) else { return nil }
        let variant = Range(match.range(at: 3), in: model).map { String(model[$0]) }
        return (String(model[family]), String(model[version]).replacingOccurrences(of: "-", with: "."), variant)
    }

    public func displayName(model: String) -> String {
        guard let (family, version, variant) = parts(model) else { return model }
        return "\(family.capitalized) \(version)" + (variant.map { " (\($0.uppercased()))" } ?? "")
    }

    private func isBroad(_ title: String) -> Bool {
        title.range(of: #"(?i)\b(?:multiple models|other models|all models|all claude models|claude services)\b"#, options: .regularExpression) != nil
    }

    public func incidentTitle(_ title: String, names model: String) -> Bool {
        if isBroad(title) { return true }
        guard let (family, version, _) = parts(model) else { return false }
        let pattern = #"(?i)(?<![a-z0-9])"# + NSRegularExpression.escapedPattern(for: family) + #"(?![a-z0-9])(?:(?!\bclaude\s+[a-z]+\b)[^0-9])*?(?<![0-9.])"# + NSRegularExpression.escapedPattern(for: version) + #"(?![0-9]|\.[0-9])"#
        return title.range(of: pattern, options: .regularExpression) != nil
    }

    public func incidentTitleIsModelSpecific(_ title: String) -> Bool {
        if isBroad(title) { return false }
        return title.range(of: #"\bClaude\s+[A-Z][a-z]+\s+\d"#, options: .regularExpression) != nil
    }
}
