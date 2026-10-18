import SwiftUI
import BrewVersionCore

struct IntervalMenu: View {
    let controller: WatchController
    var openCustom: () -> Void = {}
    var body: some View {
        Menu {
            Picker("Check interval", selection: Binding(get: { controller.state.interval }, set: { controller.setInterval($0) })) {
                ForEach(IntervalSelection(current: controller.state.interval).options, id: \.self) { interval in
                    Text(interval.label).tag(interval)
                }
            }.pickerStyle(.inline)
            Button("Custom…", action: openCustom)
        } label: { Label(shortIntervalLabel(controller.state.interval), systemImage: "timer") }
            .menuStyle(.borderlessButton).fixedSize().controlSize(.small).disabled(!controller.canSave)
            .accessibilityLabel("Check every \(controller.state.interval.label)")
    }
}
func shortIntervalLabel(_ interval: CheckInterval) -> String {
    interval.minutes % 60 == 0 ? "Every \(interval.label)" : "Every \(interval.minutes) min"
}
