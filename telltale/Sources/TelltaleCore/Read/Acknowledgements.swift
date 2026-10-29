import Foundation

public struct AlertAcknowledgement: Sendable, Equatable, Hashable, Codable {
    public var at: Date
    public var severity: LampColor
    public var failedTurns: Int?
    public init(at: Date, severity: LampColor, failedTurns: Int?) { self.at = at; self.severity = severity; self.failedTurns = failedTurns }
}
public struct CollectorAcknowledgement: Sendable, Equatable, Hashable, Codable {
    public var at: Date
    public var keys: [String]
    public init(at: Date, keys: [String]) { self.at = at; self.keys = keys }
}
extension SettingKey where Value == [String: AlertAcknowledgement] {
    public static var alertAcknowledgements: Self { Self(name: "alertAcknowledgements", defaultValue: [:]) }
}
extension SettingKey where Value == CollectorAcknowledgement? {
    public static var collectorAcknowledgement: Self { Self(name: "collectorAcknowledgement", defaultValue: nil) }
}
public enum Acknowledgements {
    public static func key(_ episode: EpisodeRow) -> String {
        "\(episode.rule)|\(episode.provider)|\(episode.scope)|\(Int(episode.onset.timeIntervalSince1970))"
    }
    public static func holds(_ ack: AlertAcknowledgement, severity: LampColor, failedTurns: Int?) -> Bool {
        guard severity <= ack.severity else { return false }
        if let failedTurns { guard let saved = ack.failedTurns, failedTurns <= saved else { return false } }
        return true
    }
    public static func holds(_ ack: CollectorAcknowledgement, keys: Set<String>) -> Bool {
        !keys.isEmpty && keys.isSubset(of: Set(ack.keys))
    }
}
extension Store {
    public func acknowledge(_ alerts: [PanelSnapshot.Alert], at: Date) throws {
        try transaction {
            var saved = try value(.alertAcknowledgements)
            for alert in alerts where !alert.key.isEmpty {
                saved[alert.key] = AlertAcknowledgement(at: at, severity: alert.color, failedTurns: alert.failedTurns)
            }
            let keys = Set(try openEpisodes().map(Acknowledgements.key))
            try set(.alertAcknowledgements, saved.filter { keys.contains($0.key) })
        }
    }
    public func markAsNew(key: String) throws {
        try transaction { var saved = try value(.alertAcknowledgements); saved.removeValue(forKey: key); try set(.alertAcknowledgements, saved) }
    }
}
