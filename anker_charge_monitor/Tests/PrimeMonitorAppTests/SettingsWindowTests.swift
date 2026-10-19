// Port: BV NativeActionsTests.settingsWindowOpensOnActiveSpace and
// settingsReuseRefreshAndLoginApprovalAction, 579ebb7. Credential form replaces BV rows.
import AppKit
import ServiceManagement
import Testing
@testable import PrimeMonitor

@MainActor final class LoginServiceStub: LoginService {
    var status: SMAppService.Status = .notRegistered
    var fail = false
    var settingsOpened = false
    func register() throws { if fail { throw CocoaError(.fileWriteUnknown) }; status = .requiresApproval }
    func unregister() throws { status = .notRegistered }
    func openSettings() { settingsOpened = true }
}
@MainActor struct SettingsWindowTests {
    @Test func settingsWindowOpensOnActiveSpace() throws {
        let rig = try ControllerRig(configured: false)
        defer { try? FileManager.default.removeItem(at: rig.directory) }
        var windows: [NSWindow] = []
        let settings = SettingsWindowController(controller: rig.controller, login: LoginItem(service: LoginServiceStub()), activate: {}, present: { windows.append($0) })
        settings.show()
        #expect(windows.first?.collectionBehavior.contains(.moveToActiveSpace) == true)
        #expect(windows.first?.collectionBehavior.contains(.canJoinAllSpaces) == false)
        #expect((windows.first?.contentLayoutRect.height ?? 0) >= 581)
    }
    @Test func settingsReuseRefreshAndLoginApprovalAction() throws {
        let rig = try ControllerRig(configured: false)
        defer { try? FileManager.default.removeItem(at: rig.directory) }
        let service = LoginServiceStub()
        let actualLogin = LoginItem(service: service)
        var windows: [NSWindow] = [], activations = 0
        let settings = SettingsWindowController(controller: rig.controller, login: actualLogin, activate: { activations += 1 }, present: { windows.append($0) })
        settings.setAppearance(NSAppearance(named: .darkAqua)); settings.show(); settings.show()
        #expect(windows[0].contentLayoutRect.height >= 400 && windows[0].contentLayoutRect.width == 460)
        #expect(windows[0].contentMinSize.height >= 400)
        windows[0].contentView?.layoutSubtreeIfNeeded()
        let scrolls = windows[0].contentView.map(nativeScrollViews) ?? []
        #expect(!scrolls.isEmpty && (scrolls.first?.frame.height ?? 0) > 300)
        #expect(windows[0].effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua)
        settings.setAppearance(NSAppearance(named: .aqua))
        #expect(windows[0].effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .aqua)
        #expect(windows[0] === windows[1] && !windows[0].isReleasedWhenClosed && activations == 2)
        actualLogin.setEnabled(true); #expect(actualLogin.requiresApproval)
        actualLogin.openSettings(); #expect(service.settingsOpened)
        service.status = .enabled; settings.windowDidBecomeKey(Notification(name: NSWindow.didBecomeKeyNotification))
        #expect(actualLogin.description == "Enabled")
        service.fail = true; actualLogin.setEnabled(true); #expect(actualLogin.error != nil)
        actualLogin.setEnabled(false); #expect(!actualLogin.enabled && actualLogin.error == nil)
    }
}
@MainActor private func nativeScrollViews(_ view: NSView) -> [NSScrollView] {
    (view as? NSScrollView).map { [$0] } ?? view.subviews.flatMap(nativeScrollViews)
}
