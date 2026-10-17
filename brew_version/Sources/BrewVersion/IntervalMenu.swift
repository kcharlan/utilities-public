import SwiftUI
import BrewVersionCore

struct IntervalMenu: View {
    let controller: WatchController
    @State private var custom = false
    @State private var input = CustomIntervalInput()
    var body: some View {
        Menu {
            Picker("Check interval", selection: Binding(get: { controller.state.interval }, set: { controller.setInterval($0) })) {
                ForEach(IntervalSelection(current: controller.state.interval).options, id: \.self) { interval in
                    Text(interval.label).tag(interval)
                }
            }.pickerStyle(.inline)
            Button("Custom…") { input.minutes = String(controller.state.interval.minutes); input.invalid = false; custom = true }
        } label: { Text("Every \(controller.state.interval.label)") }
        .disabled(!controller.canSave)
        .sheet(isPresented: $custom) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Check interval").font(.headline)
                TextField("Minutes", text: $input.minutes).accessibilityLabel("Minutes")
                if input.invalid { Text(CheckInterval.validationMessage()).foregroundStyle(.red) }
                HStack {
                    Button("Cancel") { custom = false }.keyboardShortcut(.cancelAction)
                    Spacer()
                    Button("Save") { save() }.keyboardShortcut(.defaultAction)
                }
            }.padding(20).frame(width: 290)
        }
    }
    private func save() {
        if input.save(controller: controller) { custom = false }
    }
}
