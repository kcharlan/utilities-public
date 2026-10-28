// Port: brew_version/Sources/BrewVersion/LoginItem.swift, LoginItem, fbd3e03.
// Adaptation: the status type is named `LoginStatus` so tests and harnesses never spell the system
// service; Telltale adds `applyAtLaunch` and `LaunchRecord` for spec section 3's Open at login, on
// by default, under ruling R32 (the default is applied once; launch never overrides a removal).
import Foundation
import Observation
import ServiceManagement
import TelltaleCore

typealias LoginStatus = SMAppService.Status

@MainActor protocol LoginService {
    var status: LoginStatus { get }
    func register() throws
    func unregister() throws
    func openSettings()
}
@MainActor private struct NativeLoginService: LoginService {
    var status: LoginStatus { SMAppService.mainApp.status }
    func register() throws { try SMAppService.mainApp.register() }
    func unregister() throws { try SMAppService.mainApp.unregister() }
    func openSettings() { SMAppService.openSystemSettingsLoginItems() }
}
@MainActor @Observable final class LoginItem {
    private let service: any LoginService
    private(set) var status: LoginStatus
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

    /// Spec section 3's launch behavior under ruling R32, applied by the installed copy only. Open
    /// at login's default (on) is applied once, at the first launch: if the stored setting is on
    /// and nothing is registered, register. Later launches never register, so a removal in System
    /// Settings > Login Items stands. Returns what the stored setting should hold to mirror the
    /// system (on while registered or waiting for approval), or nil when the status can't tell.
    func applyAtLaunch(openAtLogin: Bool, firstLaunch: Bool) -> Bool? {
        refresh()
        if firstLaunch, openAtLogin, status == .notRegistered { setEnabled(true) }
        switch status {
        case .enabled, .requiresApproval: return true
        case .notRegistered: return false
        default: return nil
        }
    }
}

/// Where the installed copy remembers that it applied Open at login's default (ruling R32). It
/// lives outside the database, which may not exist at the first launch (ruling R27).
@MainActor protocol LaunchRecord: AnyObject {
    var openAtLoginDefaultApplied: Bool { get set }
}

/// The boolean preferences `PreferencesLaunchRecord` reads and writes; the app passes its own
/// `UserDefaults`, tests an in-memory double.
protocol BoolPreferences: AnyObject {
    func bool(forKey key: String) -> Bool
    func set(_ value: Bool, forKey key: String)
}
extension UserDefaults: BoolPreferences {}

@MainActor final class PreferencesLaunchRecord: LaunchRecord {
    static let defaultAppliedKey = "\(TelltaleRelease.bundleIdentifier).openAtLoginDefaultApplied"
    private let preferences: any BoolPreferences
    init(preferences: any BoolPreferences) { self.preferences = preferences }
    var openAtLoginDefaultApplied: Bool {
        get { preferences.bool(forKey: Self.defaultAppliedKey) }
        set { preferences.set(newValue, forKey: Self.defaultAppliedKey) }
    }
}
