import Foundation
import Observation
import PrimeMonitorCore

/// The device a naming draft belongs to. A draft is never shown for, or
/// saved to, a different charger, port or reported USB vendor/product pair.
struct NamingTarget: Equatable {
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

/// Expanded-row and naming state for the status panel. StatusItemController
/// owns it, so expansion, a pending draft and a failed save survive snapshot
/// replacement and closing the panel. The panel's controls call these methods.
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

    var dirty: Bool { draft != nil }
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
        if draft != nil, !commit(context), let pending = draft {
            expanded = pending.target.port
            return false
        }
        expanded = expanded == port ? nil : port
        return true
    }

    /// Escape: cancels a draft or an edit in progress and reports whether it
    /// did. With nothing to cancel the caller dismisses the panel.
    func cancelEditing(fieldFocused: Bool = false) -> Bool {
        guard editing || fieldFocused || draft != nil else { return false }
        if editing || fieldFocused { cancelling = true }
        draft = nil
        if editing { editing = false }
        return true
    }

    /// Closing the panel settles a pending edit; a failure stays visible on reopening.
    func settle(_ context: NamingContext) { commit(context) }
}
