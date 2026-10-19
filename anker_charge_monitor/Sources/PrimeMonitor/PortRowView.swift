import SwiftUI
import PrimeMonitorCore

struct PortRowView: View {
    let reading: PortReading
    var dimmed: Bool { !reading.active }
    var power: String { DisplayFormatter.watts(centi: reading.powerCenti) }
    var voltage: String { DisplayFormatter.volts(milli: reading.voltageMilli) }
    var current: String { DisplayFormatter.amps(milli: reading.currentMilli) }
    var accessibilityText: String { "\(reading.port.label), \(power), \(voltage), \(current)" }
    var body: some View {
        HStack(spacing: 12) {
            Text(reading.port.label).fontWeight(.semibold).frame(width: 28, alignment: .leading)
            Spacer(minLength: 0)
            Text(power).frame(width: 80, alignment: .trailing)
            Text(voltage).frame(width: 80, alignment: .trailing)
            Text(current).frame(width: 72, alignment: .trailing)
        }.font(.system(size: 12).monospacedDigit())
            .foregroundStyle(dimmed ? .secondary : .primary)
            .padding(.vertical, 7)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(accessibilityText)
    }
}
