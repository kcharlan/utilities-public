// Port: BrewVersion/Sources/BrewVersion/LoginItem.swift, LoginItem, 579ebb7.
// Adaptation: MonitorController and interim checkpoint content replace BV watches/notifications; no custom interval.
import Observation
import ServiceManagement

@MainActor protocol LoginService {
    var status: SMAppService.Status { get }
    func register() throws
    func unregister() throws
    func openSettings()
}
@MainActor private struct NativeLoginService: LoginService {
    var status: SMAppService.Status { SMAppService.mainApp.status }
    func register() throws { try SMAppService.mainApp.register() }
    func unregister() throws { try SMAppService.mainApp.unregister() }
    func openSettings() { SMAppService.openSystemSettingsLoginItems() }
}
@MainActor @Observable final class LoginItem {
    private let service: any LoginService
    private(set) var status: SMAppService.Status
    private(set) var error: String?
    init(service: any LoginService = NativeLoginService()) { self.service = service; status = service.status }
    var enabled: Bool { status == .enabled || status == .requiresApproval }
    var requiresApproval: Bool { status == .requiresApproval }
    var description: String {
        switch status {
        case .enabled: "Enabled"
        case .requiresApproval: "Approval required in System Settings"
        case .notRegistered: "Off"
        case .notFound: "App service unavailable"
        @unknown default: "Unknown status"
        }
    }
    func refresh() { status = service.status }
    func openSettings() { service.openSettings() }
    func setEnabled(_ enabled: Bool) {
        do {
            if enabled { try service.register() } else { try service.unregister() }
            error = nil
        } catch { self.error = error.localizedDescription }
        refresh()
    }
}
