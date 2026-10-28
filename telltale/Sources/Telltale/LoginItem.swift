// Port: brew_version/Sources/BrewVersion/LoginItem.swift, LoginItem, fbd3e03.
// Adaptation: NativeLoginService is internal so the composition root can name it; Telltale adds
// `applyAtLaunch` for spec section 3's Open at login, on by default.
import Observation
import ServiceManagement

@MainActor protocol LoginService {
    var status: SMAppService.Status { get }
    func register() throws
    func unregister() throws
    func openSettings()
}
@MainActor struct NativeLoginService: LoginService {
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

    /// Spec section 3's launch behavior, applied by the installed copy only: while the stored
    /// Open at login setting is on and nothing is registered, register. A registration that exists,
    /// enabled or waiting for approval in System Settings, is left as it is.
    func applyAtLaunch(openAtLogin: Bool) {
        refresh()
        guard openAtLogin, status == .notRegistered else { return }
        setEnabled(true)
    }
}
