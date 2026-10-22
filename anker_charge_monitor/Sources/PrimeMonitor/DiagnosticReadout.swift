import Foundation
import PrimeMonitorCore


@MainActor enum DiagnosticReadout {
    static func lines(_ snapshot: ChargerSnapshot) -> [String] {
        let ports = PortID.allCases.map { port in
            guard let reading = snapshot.readings.first(where: { $0.port == port }) else { return "\(port.label): unavailable" }
            return "\(port.label): active=\(reading.active); reported=\(DisplayFormatter.watts(centi: reading.powerCenti)); voltage=\(DisplayFormatter.volts(milli: reading.voltageMilli)); current=\(DisplayFormatter.amps(milli: reading.currentMilli))"
        }
        return ports + ["Total: reported=\(DisplayFormatter.watts(centi: snapshot.totalPowerCenti))"] + detailLines(snapshot.details)
    }

    /// Owner-gate evidence: decoded detail beside the verbatim payloads it came from.
    private static func detailLines(_ details: ChargerDetails?) -> [String] {
        guard let details else { return ["Details: unavailable"] }
        let faults = details.faultBits.map { bits in
            let ports = PortID.usbC.map { "\($0.label) fault=\(details.fault($0) == true)" }
            return (["Fault bits: 0x\(hex(bits))", "over-temperature=\(details.overTemperature == true)"]
                + ports + ["USB-A fault=\(details.fault(.a1) == true)"]).joined(separator: "; ")
        } ?? "Fault bits: unavailable"
        let identities = PortID.usbC.map { port in
            "\(port.label) identity: " + identity(details.identities[port])
        }
        // One line per target; the two USB-A ports have the one switch.
        let targets = PortID.usbC.map { ($0.label, PortSwitch($0)) } + [("USB-A", PortSwitch.usbA)]
        let switches = targets.map { label, target in
            "\(label) switch: " + (details.switches[target].map { $0 ? "on" : "off" } ?? "unavailable")
        }
        let raw = ChargerDetails.fieldIDs.map { id in
            "Raw \(hex(id)): " + (details.rawFields[id].map { $0.isEmpty ? "empty" : $0.map(hex).joined(separator: " ") } ?? "unavailable")
        }
        return [faults, "Identity support: \(details.identitySupport.map(String.init) ?? "unavailable")"] + identities + switches + raw
    }

    private static func identity(_ identity: PortIdentity?) -> String {
        switch identity {
        case nil: "unavailable"
        case .nothingAttached: "nothing attached"
        case .identifying: "identifying"
        case let .identified(vendorID, productID, brandClass, modelCode):
            "vendor=0x\(hex(vendorID)); product=0x\(hex(productID)); class=\(brandClass.map(String.init) ?? "unavailable"); model code=\(modelCode.map(String.init) ?? "unavailable")"
        }
    }

    private static func hex(_ value: some FixedWidthInteger) -> String { DisplayFormatter.hex(value) }
}
