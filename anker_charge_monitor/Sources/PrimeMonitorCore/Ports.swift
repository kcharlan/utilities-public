import Foundation

public struct PortReading: Equatable, Sendable {
    public let port: PortID
    public let active: Bool
    public let voltageMilli: Int
    public let currentMilli: Int
    public let powerCenti: Int

    public init(port: PortID, active: Bool, voltageMilli: Int, currentMilli: Int, powerCenti: Int) {
        self.port = port
        self.active = active
        self.voltageMilli = voltageMilli
        self.currentMilli = currentMilli
        self.powerCenti = powerCenti
    }
}

public struct ChargerSnapshot: Equatable, Sendable {
    public let receivedAt: Date
    public let readings: [PortReading]

    public init(receivedAt: Date, readings: [PortReading]) {
        self.receivedAt = receivedAt
        self.readings = PortID.allCases.flatMap { port in readings.filter { $0.port == port } }
    }

    public var totalPowerCenti: Int { readings.reduce(0) { $0 + $1.powerCenti } }
}
