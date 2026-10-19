import SwiftUI

// Port: BV SettingsView.swift, InlineWarning, 579ebb7. Keep recovery text
// vertically unconstrained when the owned panel proposes a short viewport.
struct InlineWarning: View {
    let message: String
    var body: some View {
        Label {
            Text(message).fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: "exclamationmark.triangle.fill")
        }.font(.system(size: 11)).foregroundStyle(.red)
            .frame(maxWidth: .infinity, alignment: .leading)
            .textSelection(.enabled).help(message)
    }
}
