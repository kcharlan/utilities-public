import Foundation
import Synchronization
import Testing
import UserNotifications
import TelltaleCore
@testable import Telltale

/// Controlled time for `CheckTiming`: pausing advances the clock instead of sleeping.
private final class FakeClock: Sendable {
    private let state = Mutex<(elapsed: TimeInterval, pauses: Int)>((0, 0))
    var pauses: Int { state.withLock { $0.pauses } }
    var elapsed: TimeInterval { state.withLock { $0.elapsed } }
    func timing(timeout: TimeInterval = 10, interval: TimeInterval = 1) -> CheckTiming {
        CheckTiming(
            elapsed: { self.state.withLock { $0.elapsed } },
            pause: { seconds in self.state.withLock { $0.elapsed += seconds; $0.pauses += 1 } },
            deliveryTimeout: timeout,
            pollInterval: interval)
    }
}

/// `UNNotification` has no public initializer, so a synthetic one is decoded from
/// an archive that carries only the keys the class reads (`request`, `date`).
@objc(TelltaleTestArchivedNotification) private final class ArchivedNotification: NSObject, NSSecureCoding {
    static var supportsSecureCoding: Bool { true }
    let request: UNNotificationRequest
    init(request: UNNotificationRequest) { self.request = request }
    required init?(coder: NSCoder) { nil }
    func encode(with coder: NSCoder) {
        coder.encode(request, forKey: "request")
        coder.encode(Date(), forKey: "date")
    }
}
private func deliveredNotification(for request: UNNotificationRequest) throws -> UNNotification {
    let archiver = NSKeyedArchiver(requiringSecureCoding: true)
    archiver.setClassName("UNNotification", for: ArchivedNotification.self)
    archiver.encode(ArchivedNotification(request: request), forKey: NSKeyedArchiveRootObjectKey)
    archiver.finishEncoding()
    let unarchiver = try NSKeyedUnarchiver(forReadingFrom: archiver.encodedData)
    unarchiver.requiresSecureCoding = true
    return try #require(unarchiver.decodeObject(of: UNNotification.self, forKey: NSKeyedArchiveRootObjectKey))
}

private struct SyntheticFailure: LocalizedError {
    var errorDescription: String? { "synthetic failure" }
}

@MainActor private final class FakeNotificationService: NotificationService {
    var status: UNAuthorizationStatus = .authorized
    var grantsRequest = true
    var authorizationFailure: (any Error)?
    var postFailure: (any Error)?
    /// Notifications from earlier checks that are still in Notification Center.
    var earlier: [UNNotification] = []
    /// The current request appears from poll number `deliverAfterPolls + 1`; nil never delivers it.
    var deliverAfterPolls: Int? = 0
    private(set) var authorizationRequests = 0
    private(set) var posted: [UNNotificationRequest] = []
    private(set) var polls = 0

    func authorizationStatus() async -> UNAuthorizationStatus { status }
    func requestAuthorization() async throws -> Bool {
        authorizationRequests += 1
        if let authorizationFailure { throw authorizationFailure }
        return grantsRequest
    }
    func post(_ request: UNNotificationRequest) async throws {
        if let postFailure { throw postFailure }
        posted.append(request)
    }
    func delivered() async -> [UNNotification] {
        polls += 1
        var result = earlier
        if let deliverAfterPolls, polls > deliverAfterPolls {
            result += try! posted.map(deliveredNotification(for:))
        }
        return result
    }
}

@MainActor private struct CheckRun {
    let exitCode: Int32
    let result: [String: Any]
    let clock: FakeClock
}
@MainActor private func run(_ service: FakeNotificationService, mode: String = "ui-not-running") async throws -> CheckRun {
    let directory = FileManager.default.temporaryDirectory.appending(path: "telltale-check-\(UUID().uuidString)", directoryHint: .isDirectory)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: directory) }
    let resultURL = directory.appending(path: "result.json", directoryHint: .notDirectory)
    let clock = FakeClock()
    let code = await NotificationCheck.run(service: service, resultURL: resultURL, mode: mode, timing: clock.timing())
    let object = try JSONSerialization.jsonObject(with: Data(contentsOf: resultURL))
    return CheckRun(exitCode: code, result: try #require(object as? [String: Any]), clock: clock)
}

@Suite @MainActor struct NotificationCheckTests {
    @Test func checkSucceedsWhenDelivered() async throws {
        let service = FakeNotificationService()
        let outcome = try await run(service, mode: "ui-running")
        #expect(outcome.exitCode == 0)
        #expect(outcome.result["authorization"] as? String == "authorized")
        #expect(outcome.result["posted"] as? Bool == true)
        #expect(outcome.result["delivered"] as? Bool == true)
        #expect(outcome.result["error"] is NSNull)
        #expect(outcome.result.keys.contains("bundle"))
        let request = try #require(service.posted.first)
        #expect(service.posted.count == 1)
        #expect(request.content.title == Copy.notificationCheckTitle)
        #expect(request.content.body == Copy.notificationCheckBody(mode: "ui-running"))
        #expect(service.authorizationRequests == 0)
    }

    @Test func undeterminedAuthorizationIsRequestedOnce() async throws {
        let service = FakeNotificationService()
        service.status = .notDetermined
        let outcome = try await run(service)
        #expect(outcome.exitCode == 0)
        #expect(service.authorizationRequests == 1)
        #expect(outcome.result["authorization"] as? String == "authorized")
    }

    @Test func checkFailsWhenAuthorizationDenied() async throws {
        let service = FakeNotificationService()
        service.status = .denied
        let outcome = try await run(service)
        #expect(outcome.exitCode != 0)
        #expect(outcome.result["authorization"] as? String == "denied")
        #expect(outcome.result["posted"] as? Bool == false)
        #expect(outcome.result["delivered"] as? Bool == false)
        let error = try #require(outcome.result["error"] as? String)
        #expect(error == Copy.notificationsDenied)
        #expect(error.contains("Telltale") && error.contains("System Settings"))
        #expect(service.posted.isEmpty)
    }

    @Test func declinedPromptIsReportedAsDenied() async throws {
        let service = FakeNotificationService()
        service.status = .notDetermined
        service.grantsRequest = false
        let outcome = try await run(service)
        #expect(outcome.exitCode != 0)
        #expect(outcome.result["authorization"] as? String == "denied")
        #expect(outcome.result["error"] as? String == Copy.notificationsDenied)
        #expect(service.posted.isEmpty)
    }

    @Test func authorizationFailureIsReported() async throws {
        let service = FakeNotificationService()
        service.status = .notDetermined
        service.authorizationFailure = SyntheticFailure()
        let outcome = try await run(service)
        #expect(outcome.exitCode != 0)
        #expect(outcome.result["error"] as? String == Copy.notificationAuthorizationFailure(error: SyntheticFailure()))
        #expect(outcome.result["posted"] as? Bool == false)
        #expect(service.posted.isEmpty)
    }

    @Test func postFailureIsReported() async throws {
        let service = FakeNotificationService()
        service.postFailure = SyntheticFailure()
        let outcome = try await run(service)
        #expect(outcome.exitCode != 0)
        #expect(outcome.result["posted"] as? Bool == false)
        #expect(outcome.result["delivered"] as? Bool == false)
        #expect(outcome.result["error"] as? String == Copy.notificationPostFailure(error: SyntheticFailure()))
        #expect(service.polls == 0)
    }

    @Test func checkFailsWhenNotDelivered() async throws {
        let service = FakeNotificationService()
        service.deliverAfterPolls = nil
        let outcome = try await run(service)
        #expect(outcome.exitCode != 0)
        #expect(outcome.result["posted"] as? Bool == true)
        #expect(outcome.result["delivered"] as? Bool == false)
        #expect(outcome.result["error"] as? String == Copy.notificationCheckNotDelivered(seconds: 10))
        // Polling stopped at the injected deadline rather than running unbounded.
        #expect(outcome.clock.elapsed >= 10)
        #expect(outcome.clock.pauses == 10)
    }

    @Test func olderDeliveredCheckDoesNotSatisfyCurrentRequest() async throws {
        let service = FakeNotificationService()
        // Same title and body as the current check, but a different request identifier.
        let content = UNMutableNotificationContent()
        content.title = Copy.notificationCheckTitle
        content.body = Copy.notificationCheckBody(mode: "ui-not-running")
        service.earlier = [try deliveredNotification(for: UNNotificationRequest(identifier: "earlier-check", content: content, trigger: nil))]
        service.deliverAfterPolls = nil
        let outcome = try await run(service)
        #expect(outcome.exitCode != 0)
        #expect(outcome.result["delivered"] as? Bool == false)
        #expect(service.polls > 1)
    }

    @Test func deliveryCanArriveAfterPostReturns() async throws {
        let service = FakeNotificationService()
        service.deliverAfterPolls = 3
        let outcome = try await run(service)
        #expect(outcome.exitCode == 0)
        #expect(outcome.result["delivered"] as? Bool == true)
        #expect(service.polls == 4)
        #expect(outcome.clock.pauses == 3)
    }

    @Test func freshRequestIdentifierPerInvocation() async throws {
        let first = FakeNotificationService(), second = FakeNotificationService()
        _ = try await run(first)
        _ = try await run(second)
        #expect(try #require(first.posted.first).identifier != (try #require(second.posted.first)).identifier)
    }
}

@Suite struct LaunchCommandTests {
    @Test func parsesNotificationCheckArguments() {
        let command = LaunchCommand.parse(["Telltale", "--notification-check", "--result", "/tmp/r.json", "--mode", "ui-running"])
        #expect(command == .notificationCheck(result: URL(fileURLWithPath: "/tmp/r.json"), mode: "ui-running"))
    }

    @Test func notificationCheckNeedsResultAndMode() {
        #expect(LaunchCommand.parse(["Telltale", "--notification-check", "--mode", "x"]) == .usageError)
        #expect(LaunchCommand.parse(["Telltale", "--notification-check", "--result", "/tmp/r.json"]) == .usageError)
    }

    @Test func parsesCollectAndDefault() {
        #expect(LaunchCommand.parse(["Telltale", "--collect"]) == .collect)
        #expect(LaunchCommand.parse(["Telltale"]) == .app)
    }

    // A launchd typo must never open the UI.
    @Test func unrecognizedArgumentsAreAUsageError() {
        #expect(LaunchCommand.parse(["Telltale", "--colect"]) == .usageError)
        #expect(LaunchCommand.parse(["Telltale", "--collect", "--extra"]) == .usageError)
        #expect(LaunchCommand.parse(["Telltale", "--collect", "--collect"]) == .usageError)
        #expect(LaunchCommand.parse(["Telltale", "stray"]) == .usageError)
        #expect(LaunchCommand.parse(["Telltale", "--notification-check", "--result", "/tmp/r.json", "--mode", "x", "--extra"]) == .usageError)
    }

    @Test func usageErrorExitsTwoWithEveryForm() {
        #expect(LaunchCommand.usageExitCode == 2)
        #expect(LaunchCommand.usage.contains("Telltale --collect"))
        #expect(LaunchCommand.usage.contains("Telltale --notification-check --result <path> --mode <name>"))
    }
}
