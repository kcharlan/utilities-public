import Foundation
import Observation
import PrimeMonitorCore

/// The device a naming draft belongs to. A draft is never shown for, or
/// saved to, a different charger, port or reported USB vendor/product pair.
struct NamingTarget: Hashable {
    let charger: String?
    let port: PortID
    let key: DeviceKey
}

/// What naming actions consult: the current snapshot's identities, the
/// selected charger and the catalog store.
@MainActor struct NamingContext {
    let snapshot: ChargerSnapshot?
    let charger: String?
    let store: DeviceCatalogStore
    init(snapshot: ChargerSnapshot?, charger: String?, store: DeviceCatalogStore) {
        self.snapshot = snapshot
        self.charger = charger
        self.store = store
    }
    init(monitor: MonitorController, store: DeviceCatalogStore) {
        self.init(snapshot: monitor.snapshot, charger: monitor.appState.charger?.serial, store: store)
    }
    /// The nameable device currently reported at `port`: an identified USB-C device.
    func target(_ port: PortID) -> NamingTarget? {
        guard port.isUSBC, case let .identified(vendorID, productID, _, _)? = snapshot?.details?.identities[port] else { return nil }
        return NamingTarget(charger: charger, port: port, key: DeviceKey(vendorID: vendorID, productID: productID))
    }
}

/// A failed naming save. When the store already reports the same message as
/// its catalog problem, the panel shows that warning once and the field
/// only says the name was not saved.
struct NamingFailure: Equatable {
    let message: String
    let sharedWithCatalog: Bool
    var inlineText: String {
        sharedWithCatalog ? "Name not saved. Correct the device names file, then press Return to retry."
            : "Name not saved: \(message) Press Return to retry."
    }
}

extension PortOperationKind {
    /// Turn off and Restart cut power, so they arm on the first click and act on
    /// a second click of the same button; Turn on acts at once.
    var needsConfirmation: Bool { self != .turnOn }
}

/// A Turn off or Restart waiting for its confirming click (plan "Confirmation").
struct ArmedPortAction: Equatable {
    let target: PortSwitch
    let action: PortOperationKind
    /// The confirming click must come before this time.
    let expiry: Date
    /// The account, charger and connection it was armed under.
    let context: PortControlGenerations
}

/// Expanded-row, naming and port-confirmation state for the status panel.
/// StatusItemController owns it, so expansion, a pending draft and a failed save
/// survive snapshot replacement and closing the panel; closing disarms an armed
/// port action. The panel's controls call these methods.
@MainActor @Observable final class PortDetailState {
    struct Draft: Equatable {
        let target: NamingTarget
        var text: String
        var failure: NamingFailure?
    }
    private(set) var expanded: PortID?
    private(set) var draft: Draft?
    /// The naming field has focus.
    private(set) var editing = false
    /// Set by Escape before focus changes, so neither the field's end-of-editing
    /// value push nor the focus-loss save can restore or commit the draft.
    @ObservationIgnored private var cancelling = false
    /// The armed port action, as recorded; `armedAction(in:available:)` decides
    /// whether it can still be shown or confirmed.
    private(set) var armed: ArmedPortAction?
    /// The confirmation window's clock; tests and snapshots inject theirs.
    @ObservationIgnored var now: () -> Date = Date.init

    var dirty: Bool { draft != nil }

    // MARK: Port control confirmation

    /// The armed action while it can still be confirmed: unexpired, armed under
    /// these generations, with controls available. Otherwise it is disarmed in
    /// effect, even before `revalidate` clears it.
    func armedAction(in context: PortControlGenerations, available: Bool) -> ArmedPortAction? {
        guard available, let armed, armed.context == context, now() < armed.expiry else { return nil }
        return armed
    }
    /// A control click. Returns true when the action should dispatch now: Turn on,
    /// or the second click of the armed action under the same context. Any other
    /// click disarms; a first click of Turn off or Restart arms it. Unavailable
    /// controls dispatch nothing.
    func press(_ action: PortOperationKind, target: PortSwitch, in context: PortControlGenerations, available: Bool) -> Bool {
        let current = armedAction(in: context, available: available)
        disarm()
        guard available else { return false }
        guard action.needsConfirmation else { return true }
        if current?.target == target, current?.action == action { return true }
        armed = ArmedPortAction(target: target, action: action,
                                expiry: now().addingTimeInterval(PortControlPolicy.confirmationWindow), context: context)
        return false
    }
    /// Escape: disarms, and reports whether a confirmable action was armed. An
    /// expired or superseded one is already disarmed, so it does not consume Escape.
    func disarm(in context: PortControlGenerations, available: Bool) -> Bool {
        let confirmable = armedAction(in: context, available: available) != nil
        disarm()
        return confirmable
    }
    /// Closing the panel and changing the expanded row.
    func disarm() { if armed != nil { armed = nil } }
    /// Loss of control availability or a context change disarms for good, so the
    /// action does not return with availability inside its window.
    func revalidate(in context: PortControlGenerations, available: Bool) {
        if armed != nil, armedAction(in: context, available: available) == nil { armed = nil }
    }
    var editedKey: DeviceKey? { draft?.target.key }

    /// The field's text: the draft bound to this exact target, otherwise the
    /// saved name. Catalog reloads therefore never replace a pending draft.
    func text(for target: NamingTarget, in catalog: DeviceCatalog) -> String {
        if let draft, draft.target == target { return draft.text }
        return catalog.devices[target.key] ?? ""
    }
    func failure(for target: NamingTarget) -> NamingFailure? {
        draft?.target == target ? draft?.failure : nil
    }

    func edit(_ text: String, for target: NamingTarget, in catalog: DeviceCatalog) {
        guard !cancelling else { return }
        if let current = draft, current.target == target {
            if current.text != text { draft?.text = text }
            return
        }
        // AppKit echoes the displayed value; that is not an edit.
        guard text != (catalog.devices[target.key] ?? "") else { return }
        draft = Draft(target: target, text: text)
    }

    func beginEditing() {
        cancelling = false
        if !editing { editing = true }
    }
    /// Focus loss saves, unless Escape cancelled first.
    func endEditing(_ context: NamingContext) {
        if editing { editing = false }
        if cancelling { cancelling = false; return }
        commit(context)
    }

    /// Return, focus loss, closing and row switching all save here. A draft
    /// whose device is no longer reported at its port is discarded rather than
    /// written for a device the panel no longer shows. Returns false when a
    /// save failed; the draft and its inline error remain for retry.
    @discardableResult func commit(_ context: NamingContext) -> Bool {
        guard let pending = draft else { return true }
        guard context.target(pending.target.port) == pending.target else { draft = nil; return true }
        let store = context.store
        guard DeviceCatalog.normalizedName(pending.text) != store.catalog.devices[pending.target.key] else { draft = nil; return true }
        do {
            try store.setName(pending.text, for: pending.target.key)
            draft = nil
            return true
        } catch {
            let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            draft?.failure = NamingFailure(message: message, sharedWithCatalog: store.problem == message)
            return false
        }
    }

    /// The row control. Leaving the edited row settles its draft first; when
    /// that save fails the edited row stays expanded with its draft.
    @discardableResult func toggle(_ port: PortID, _ context: NamingContext) -> Bool {
        // A row control click is a change of the expanded row: it disarms.
        disarm()
        if draft != nil, !commit(context), let pending = draft {
            expanded = pending.target.port
            return false
        }
        expanded = expanded == port ? nil : port
        // Any change of expansion removes the field; end editing now rather
        // than after SwiftUI's later disappearance callback.
        fieldRemoved()
        return true
    }

    /// The naming field left the view (row change, device replaced or gone,
    /// charger changed, signed out). A removed field may report no focus loss,
    /// and a stale editing state made the next Escape cancel nothing instead of
    /// dismissing. Ends editing without saving; the draft keeps its binding.
    func fieldRemoved() {
        cancelling = false
        if editing { editing = false }
    }

    /// Escape: cancels an edit in progress or a draft shown for its device,
    /// including a failed draft whose field is not focused, and reports whether
    /// it did. With nothing visible to cancel the caller dismisses the panel; a
    /// draft whose device is no longer reported is then settled (discarded) by
    /// closing. Without a context every draft counts as shown.
    func cancelEditing(fieldFocused: Bool = false, context: NamingContext? = nil) -> Bool {
        let draftShown = draft.map { pending in context.map { $0.target(pending.target.port) == pending.target } ?? true } ?? false
        guard editing || fieldFocused || draftShown else { return false }
        if editing || fieldFocused { cancelling = true }
        draft = nil
        if editing { editing = false }
        return true
    }

    /// Closing the panel settles a pending edit; a failure stays visible on reopening.
    func settle(_ context: NamingContext) { commit(context) }
}
