import SwiftUI
import PrimeMonitorCore

/// A port row's fault and connected-device text, shared by the row, its
/// accessibility label and the tests.
struct PortRowPresentation: Equatable {
    let port: PortID
    /// nil when the fault bits were not decoded: no fault claim is made.
    let fault: Bool?
    /// nil when the switch was not decoded: no off claim is made.
    let switchOn: Bool?
    /// The catalog label of the USB-C device reported at this port.
    let device: String?

    static func make(_ port: PortID, details: ChargerDetails?, catalog: DeviceCatalog) -> Self {
        let identity = port.isUSBC ? details?.identities[port] : nil
        return .init(port: port, fault: details?.fault(port), switchOn: details?.switchedOn(port),
                     device: identity.flatMap(catalog.label(for:)))
    }
    var faulted: Bool { fault == true }
    /// A3's USB-A bit is shared by both USB-A ports, so it names neither one.
    var faultText: String? { faulted ? (port.isUSBC ? "Fault reported" : "USB-A fault") : nil }
    /// Only a reported-off switch is worth a row; on is the expected state.
    var switchText: String? { switchOn == false ? "Off" : nil }
    var secondaryText: String? {
        let parts = [faultText, switchText, device].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}

struct PortRowView: View {
    let reading: PortReading
    var presentation: PortRowPresentation?
    var expanded = false

    /// Column widths fit the signed 16-bit wire extremes in the reading font;
    /// `numericColumnsFitWireExtremes` measures them.
    static let readingFontSize: CGFloat = 12
    static let deviceFontSize: CGFloat = 11
    static let spacing: CGFloat = 8
    static let labelWidth: CGFloat = 28
    static let powerWidth: CGFloat = 64
    static let voltageWidth: CGFloat = 61
    static let currentWidth: CGFloat = 61
    static let disclosureWidth: CGFloat = 10

    var dimmed: Bool { !reading.active }
    var faulted: Bool { presentation?.faulted == true }
    var power: String { DisplayFormatter.watts(centi: reading.powerCenti) }
    var voltage: String { DisplayFormatter.volts(milli: reading.voltageMilli) }
    var current: String { DisplayFormatter.amps(milli: reading.currentMilli) }
    var accessibilityValue: String { expanded ? "Expanded" : "Collapsed" }
    /// Known fault, switch and device information precede the readings.
    var accessibilityText: String {
        ([reading.port.label] + [presentation?.faultText, presentation?.switchText, presentation?.device].compactMap { $0 } + [power, voltage, current])
            .joined(separator: ", ")
    }
    var body: some View {
        HStack(spacing: Self.spacing) {
            Text(reading.port.label).fontWeight(.semibold)
                .foregroundStyle(faulted ? AnyShapeStyle(.red) : AnyShapeStyle(dimmed ? .secondary : .primary))
                .frame(width: Self.labelWidth, alignment: .leading)
            HStack(spacing: 3) {
                if let text = presentation?.secondaryText {
                    if faulted { Image(systemName: "exclamationmark.triangle") }
                    // Truncated in the row; the tooltip and accessibility label keep it whole.
                    Text(text).lineLimit(1).truncationMode(.tail).help(text)
                }
            }.font(.system(size: Self.deviceFontSize))
                .foregroundStyle(faulted ? AnyShapeStyle(.red) : AnyShapeStyle(.secondary))
                .frame(maxWidth: .infinity, alignment: .leading)
            Group {
                Text(power).frame(width: Self.powerWidth, alignment: .trailing)
                Text(voltage).frame(width: Self.voltageWidth, alignment: .trailing)
                Text(current).frame(width: Self.currentWidth, alignment: .trailing)
            }.foregroundStyle(dimmed ? .secondary : .primary)
            Image(systemName: expanded ? "chevron.down" : "chevron.right")
                .font(.system(size: 9, weight: .semibold)).foregroundStyle(.tertiary)
                .frame(width: Self.disclosureWidth)
        }.font(.system(size: Self.readingFontSize).monospacedDigit())
            .padding(.vertical, 7)
            .contentShape(Rectangle())
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(accessibilityText)
            .accessibilityValue(accessibilityValue)
    }
}
