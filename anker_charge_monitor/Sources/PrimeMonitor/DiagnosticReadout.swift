import Foundation
import PrimeMonitorCore


@MainActor enum DiagnosticReadout {
    static func lines(_ snapshot: ChargerSnapshot) -> [String] {
        let ports = PortID.allCases.map { port in
            guard let reading = snapshot.readings.first(where: { $0.port == port }) else { return "\(port.label): unavailable" }
            return "\(port.label): active=\(reading.active); reported=\(DisplayFormatter.watts(centi: reading.powerCenti)); voltage=\(DisplayFormatter.volts(milli: reading.voltageMilli)); current=\(DisplayFormatter.amps(milli: reading.currentMilli))"
        }
        return ports + ["Total: reported=\(DisplayFormatter.watts(centi: snapshot.totalPowerCenti))"]
    }
}
