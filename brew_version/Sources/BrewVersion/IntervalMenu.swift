import SwiftUI
import BrewVersionCore

struct IntervalMenu: View {
    let controller: WatchController
    @State private var custom = false
    @State private var minutes = ""
    @State private var invalid = false
    var body: some View {
        Menu {
            ForEach(CheckInterval.presets, id: \.self) { interval in
                Button { controller.setInterval(interval) } label: {
                    if controller.state.interval == interval { Label(interval.label, systemImage: "checkmark") }
                    else { Text(interval.label) }
                }
            }
            Button("Custom…") { minutes = String(controller.state.interval.minutes); invalid = false; custom = true }
        } label: { Text("Every \(controller.state.interval.label)") }
        .disabled(!controller.canSave)
        .sheet(isPresented: $custom) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Check interval").font(.headline)
                TextField("Minutes", text: $minutes).accessibilityLabel("Minutes")
                if invalid { Text(CheckInterval.validationMessage()).foregroundStyle(.red) }
                HStack {
                    Button("Cancel") { custom = false }.keyboardShortcut(.cancelAction)
                    Spacer()
                    Button("Save") { save() }.keyboardShortcut(.defaultAction)
                }
            }.padding(20).frame(width: 290)
        }
    }
    private func save() {
        guard !minutes.isEmpty, minutes.utf8.allSatisfy({ (48...57).contains($0) }),
              let number = Int(minutes), let interval = CheckInterval(minutes: number) else { invalid = true; return }
        controller.setInterval(interval); custom = false
    }
}
