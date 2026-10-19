public struct ChargerInfo: Equatable, Codable, Sendable {
    public let serial: String
    public let model: String
    public let alias: String
    public let name: String

    public init(serial: String, model: String, alias: String, name: String) {
        self.serial = serial
        self.model = model
        self.alias = alias
        self.name = name
    }
}
