import Observation
import ServiceManagement

@MainActor @Observable final class LoginItem {
    private(set) var status = SMAppService.mainApp.status
    private(set) var error: String?
    var enabled: Bool { status == .enabled || status == .requiresApproval }
    var description: String {
        switch status {
        case .enabled: "Enabled"
        case .requiresApproval: "Approval required in System Settings"
        case .notRegistered: "Off"
        case .notFound: "App service unavailable"
        @unknown default: "Unknown status"
        }
    }
    func refresh() { status = SMAppService.mainApp.status }
    func setEnabled(_ enabled: Bool) {
        do {
            if enabled { try SMAppService.mainApp.register() }
            else { try SMAppService.mainApp.unregister() }
            error = nil
        } catch { self.error = error.localizedDescription }
        refresh()
    }
}
