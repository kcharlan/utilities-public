// Port: BrewVersion LoginItem coverage in NativeActionsTests, 579ebb7.
import ServiceManagement
import Testing
@testable import PrimeMonitor
@MainActor struct LoginItemTests {
    @Test func requiresApproval() {
        let service = LoginServiceStub()
        let subject = LoginItem(service: service)
        #expect(!subject.enabled)
        subject.setEnabled(true)
        #expect(subject.enabled && subject.requiresApproval)
        subject.openSettings(); #expect(service.settingsOpened)
        service.status = .enabled; subject.refresh()
        #expect(subject.enabled && !subject.requiresApproval)
        service.fail = true; subject.setEnabled(true); #expect(subject.error != nil)
        subject.setEnabled(false); #expect(!subject.enabled && subject.error == nil)
        service.status = .notFound; subject.refresh(); #expect(subject.description == "App service unavailable")
    }
}
