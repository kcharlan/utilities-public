import AppKit
import SwiftUI

/// The clicked row owns native editing commands; the search field keeps its
/// normal text responder. No app-wide key monitor or delete command is installed.
struct WatchRowKeyboard: NSViewRepresentable {
    let focusRequest: UUID?
    let remove: () -> Void
    func makeNSView(context: Context) -> WatchRowKeyboardView {
        let view = WatchRowKeyboardView()
        // A rebuilt row must not replay an old click and steal search focus.
        view.focusRequest = focusRequest
        return view
    }
    func updateNSView(_ view: WatchRowKeyboardView, context: Context) {
        view.remove = remove
        if let focusRequest, view.focusRequest != focusRequest {
            view.focusRequest = focusRequest
            view.takeFocus()
        }
    }
}
@MainActor final class WatchRowKeyboardView: NSView {
    var remove: (() -> Void)?
    var focusRequest: UUID?
    override var acceptsFirstResponder: Bool { true }
    // The background must not intercept the row's buttons or SwiftUI click.
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    func takeFocus() { window?.makeFirstResponder(self) }
    override func keyDown(with event: NSEvent) {
        if [51, 117].contains(event.keyCode), event.modifierFlags.intersection([.command, .control, .option]).isEmpty {
            remove?()
        } else { super.keyDown(with: event) }
    }
    override func deleteBackward(_ sender: Any?) { remove?() }
    override func deleteForward(_ sender: Any?) { remove?() }
}
