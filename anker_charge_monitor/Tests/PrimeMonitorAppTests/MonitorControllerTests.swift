import Foundation
import Testing
import PrimeMonitorCore
@testable import PrimeMonitor

let appCredentials = AnkerCredentials(email: "synthetic@example.invalid", password: "synthetic-password", country: "US")
let appSession = AccountSession(authToken: "synthetic-token", userID: "synthetic-user", expiresAt: .distantFuture, nickname: "")
let appCharger = ChargerInfo(serial: "synthetic-charger", model: "A2345", alias: "Desk", name: "Prime")

@MainActor final class MemorySecrets: SecretStore {
    var value: StoredSecrets?
    var failSave = false
    private var provider: (any CredentialProvider)?
    var configured: Bool { value != nil || provider != nil }
    init(_ value: StoredSecrets? = nil) { self.value = value }
    func load() throws -> StoredSecrets? { value }
    func replaceProvider(_ provider: (any CredentialProvider)?, selection: CredentialSelection?) { self.provider = provider; value = nil }
    func save(_ value: StoredSecrets) throws { if failSave { throw CocoaError(.fileWriteUnknown) }; self.value = value }
    func delete() throws { value = nil }
}
actor AppBackend: ChargerBackend {
    final class Output: @unchecked Sendable {
        private let lock = NSLock()
        private var channels: [UUID: AsyncStream<BackendEvent>.Continuation] = [:]
        private var latest: AsyncStream<BackendEvent>.Continuation?
        var current: AsyncStream<BackendEvent>.Continuation { lock.withLock { latest! } }
        func subscribe() -> AsyncStream<BackendEvent> {
            let id = UUID(), (stream, channel) = AsyncStream<BackendEvent>.makeStream()
            lock.withLock { channels[id] = channel; latest = channel }
            channel.onTermination = { [weak self] _ in self?.remove(id) }
            return stream
        }
        private func remove(_ id: UUID) { _ = lock.withLock { channels.removeValue(forKey: id) } }
        func yield(_ event: BackendEvent) {
            let current = lock.withLock { Array(channels.values) }
            for channel in current { channel.yield(event) }
        }
        // Synthetic receive order, as AnkerCloudBackend keeps it: a new epoch per
        // connect and one sequence step per reply, monotonic across connections.
        private var epoch: UInt64 = 0
        private var sequence: UInt64 = 0
        func connected() { lock.withLock { epoch += 1 } }
        /// The receipt fence a command written now would carry.
        var fence: ReceiveMark { lock.withLock { ReceiveMark(connection: ConnectionEpoch(epoch), sequence: sequence) } }
        /// Delivers a reply at the next receive position and returns that position.
        @discardableResult func snapshot(_ value: ChargerSnapshot) -> ReceiveMark {
            let mark = lock.withLock { sequence += 1; return ReceiveMark(connection: ConnectionEpoch(epoch), sequence: sequence) }
            yield(.snapshot(value, mark))
            return mark
        }
    }
    nonisolated let output = Output()
    nonisolated var events: AsyncStream<BackendEvent> { output.subscribe() }
    var log: [String] = []
    var connectedChargers: [ChargerInfo] = []
    var session = appSession
    var holdConnection = false
    var connectionWait: CheckedContinuation<Void, Never>?
    var holdDisconnect = false
    var disconnectWait: CheckedContinuation<Void, Never>?
    func blockConnection() { holdConnection = true }
    func releaseConnection() { connectionWait?.resume(); connectionWait = nil }
    func blockDisconnection() { holdDisconnect = true }
    func releaseDisconnection() { disconnectWait?.resume(); disconnectWait = nil }
    func subscribeToEvents() async -> AsyncStream<BackendEvent> { output.subscribe() }
    func signIn(_ credentials: AnkerCredentials) async throws -> AccountSession { log.append("login"); return session }
    func restore(_ session: AccountSession, credentials: AnkerCredentials) async { log.append("restore") }
    func listChargers() async throws -> [ChargerInfo] { log.append("list"); return [appCharger] }
    func connect(to charger: ChargerInfo) async throws {
        connectedChargers.append(charger); log.append("connect"); linkUp = true; output.connected(); output.yield(.status(.connected))
        if holdConnection { holdConnection = false; await withCheckedContinuation { connectionWait = $0 } }
    }
    var holdRequest = false
    private var requestWait: CheckedContinuation<Void, Never>?
    /// Holds the next status request in flight until `releaseRequest()`.
    func blockRequest() { holdRequest = true }
    func releaseRequest() { requestWait?.resume(); requestWait = nil }
    func requestSnapshot() async throws {
        log.append("request")
        if holdRequest { holdRequest = false; await withCheckedContinuation { requestWait = $0 } }
    }
    /// Synthetic switch commands are recorded, never sent anywhere. `switchChargers`
    /// records the charger connected when each write was attempted.
    var switchCommands: [(target: PortSwitch, on: Bool)] = []
    var switchChargers: [String?] = []
    /// A synthetic link: up from `connect`, down after `disconnect` or `abortCommands`.
    private(set) var linkUp = false
    private var holdSwitches = false, failSwitches = false, holdFences = false, failFences = false
    private var switchWaits: [CheckedContinuation<Bool, Never>] = []
    private var fenceWaits: [CheckedContinuation<Bool, Never>] = []
    var heldSwitchWrites: Int { switchWaits.count }
    var heldFences: Int { fenceWaits.count }
    struct LinkClosed: Error {}
    /// Holds every later switch write until released, or until the link closes.
    func blockSwitches() { holdSwitches = true }
    func failSwitchWrites(_ fail: Bool = true) { failSwitches = fail }
    /// Completes held writes; their receipts take the fence at completion.
    func releaseSwitches() { holdSwitches = false; finish(&switchWaits, completed: true) }
    func blockFences() { holdFences = true }
    func failFenceReads(_ fail: Bool = true) { failFences = fail }
    func releaseFences() { holdFences = false; finish(&fenceWaits, completed: true) }
    private func finish(_ waits: inout [CheckedContinuation<Bool, Never>], completed: Bool) {
        let held = waits; waits = []
        for wait in held { wait.resume(returning: completed) }
    }
    /// Closing the link resumes pending writes with an error, as NWMQTTLink does.
    private func closeLink() { linkUp = false; finish(&switchWaits, completed: false); finish(&fenceWaits, completed: false) }
    func setPortSwitch(_ target: PortSwitch, on: Bool) async throws -> PortCommandReceipt {
        switchCommands.append((target, on)); switchChargers.append(connectedChargers.last?.serial); log.append("switch")
        guard linkUp, !failSwitches else { throw LinkClosed() }
        if holdSwitches { guard await withCheckedContinuation({ switchWaits.append($0) }) else { throw LinkClosed() } }
        guard linkUp else { throw LinkClosed() }
        return PortCommandReceipt(fence: output.fence)
    }
    func commandFence() async throws -> PortCommandReceipt {
        log.append("fence")
        guard linkUp, !failFences else { throw LinkClosed() }
        if holdFences { guard await withCheckedContinuation({ fenceWaits.append($0) }) else { throw LinkClosed() } }
        guard linkUp else { throw LinkClosed() }
        return PortCommandReceipt(fence: output.fence)
    }
    func abortCommands() async { log.append("abort"); closeLink() }
    func disconnect() async {
        log.append("disconnect"); closeLink()
        if holdDisconnect { holdDisconnect = false; await withCheckedContinuation { disconnectWait = $0 } }
        releaseConnection()
    }
}
@MainActor final class TestEvents: SystemEventSource {
    var handler: (@MainActor @Sendable (SystemEvent) async -> Void)?
    var stopped = false
    func start(_ handler: @escaping @MainActor @Sendable (SystemEvent) async -> Void) { self.handler = handler; stopped = false }
    func stop() { stopped = true; handler = nil }
    func send(_ event: SystemEvent) async { await handler?(event) }
}
@MainActor final class ManualScheduler: PollScheduler {
    final class Entry: Cancellable {
        let at: Date
        let fire: @MainActor () -> Void
        var cancelled = false
        init(at: Date, fire: @escaping @MainActor () -> Void) { self.at = at; self.fire = fire }
        func cancel() { cancelled = true }
    }
    var date = Date(timeIntervalSince1970: 1000)
    var entries: [Entry] = []
    func schedule(after delay: TimeInterval, _ fire: @escaping @MainActor () -> Void) -> any Cancellable {
        let entry = Entry(at: date.addingTimeInterval(delay), fire: fire); entries.append(entry); return entry
    }
    func advance(_ seconds: TimeInterval) async {
        let target = date.addingTimeInterval(seconds)
        while let entry = entries.filter({ !$0.cancelled && $0.at <= target }).min(by: { $0.at < $1.at }) {
            entry.cancelled = true; date = entry.at; entry.fire(); await settle()
        }
        date = target; await settle()
    }
}
@MainActor func settle() async { for _ in 0..<100 { await Task.yield() } }
@MainActor final class ControllerRig {
    let backend = AppBackend(), secrets: MemorySecrets, events = TestEvents(), clock = ManualScheduler()
    let directory = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
    let controller: MonitorController
    init(configured: Bool = true) throws {
        secrets = MemorySecrets(configured ? .init(credentials: appCredentials, session: appSession) : nil)
        let store = StateStore(fileURL: directory.appending(path: "state.json", directoryHint: .notDirectory))
        if configured { try store.save(.init(charger: appCharger, closedInterval: .m1)) }
        controller = MonitorController(backend: backend, secrets: secrets, state: store, events: SystemEvents(sources: [events]), now: { [clock] in clock.date }, scheduler: clock)
    }
    func start() async { controller.start(); await events.send(.network(true)); await settle() }
    func finish() async { await controller.stop(); try? FileManager.default.removeItem(at: directory) }
    func reply() async { backend.output.snapshot(.init(receivedAt: clock.date, readings: [])); await settle() }
}

@Suite @MainActor struct MonitorControllerTests {
    @Test func startWithoutSecretsIsNotConfigured() async throws {
        let rig = try ControllerRig(configured: false); await rig.start()
        #expect(rig.controller.status == .notConfigured); #expect(await rig.backend.log.isEmpty); await rig.finish()
    }
    @Test func startRestoresCachedSessionWithoutLogin() async throws {
        let rig = try ControllerRig(); await rig.start()
        #expect(await rig.backend.log.contains("restore")); #expect(await !rig.backend.log.contains("login")); #expect(rig.controller.status == .connected); await rig.finish()
    }
    @Test func panelOpenPollsEveryFiveAndRequestsImmediately() async throws {
        let rig = try ControllerRig(); await rig.start(); let before = await rig.backend.log.filter { $0 == "request" }.count
        rig.controller.panelOpened(); await settle()
        #expect(await rig.backend.log.filter { $0 == "request" }.count == before + 1)
        await rig.clock.advance(4); #expect(await rig.backend.log.filter { $0 == "request" }.count == before + 1)
        await rig.clock.advance(1); #expect(await rig.backend.log.filter { $0 == "request" }.count == before + 2); await rig.finish()
    }
    @Test func panelClosedUsesClosedInterval() async throws {
        let rig = try ControllerRig(); await rig.start(); rig.controller.panelOpened(); await settle(); rig.controller.panelClosed()
        let before = await rig.backend.log.filter { $0 == "request" }.count
        await rig.clock.advance(59); #expect(await rig.backend.log.filter { $0 == "request" }.count == before)
        await rig.clock.advance(1); #expect(await rig.backend.log.filter { $0 == "request" }.count == before + 1); await rig.finish()
    }
    @Test func closedPanelGoesStaleWithoutEvents() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.reply()
        // No new requests can add missed replies: suspend the network; inbound traffic remains absent.
        await rig.events.send(.network(false)); await rig.clock.advance(130)
        #expect(!rig.controller.isStale)
        await rig.clock.advance(1); #expect(rig.controller.isStale); await rig.finish()
    }
    @Test func echoDoesNotCountAsReply() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.reply(); rig.controller.panelOpened(); await settle()
        await rig.clock.advance(5); rig.backend.output.yield(.alive(rig.clock.date)); await settle()
        await rig.clock.advance(10); #expect(rig.controller.isStale); await rig.finish()
    }
    @Test func sleepCancelsPollingAndDisconnects() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.events.send(.sleep)
        let before = await rig.backend.log.filter { $0 == "request" }.count
        await rig.clock.advance(120); #expect(await rig.backend.log.last == "disconnect"); #expect(await rig.backend.log.filter { $0 == "request" }.count == before); await rig.finish()
    }
    @Test func wakeRequestsImmediately() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.events.send(.sleep); await rig.events.send(.network(false)); await rig.events.send(.wake)
        let before = await rig.backend.log.filter { $0 == "connect" }.count
        #expect(rig.controller.status == .networkUnavailable)
        await rig.events.send(.network(true)); await settle()
        #expect(await rig.backend.log.filter { $0 == "connect" }.count == before + 1); #expect(await rig.backend.log.last == "request"); await rig.finish()
    }
    @Test func networkLossShowsErrorAndStopsPublishing() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.events.send(.network(false))
        #expect(rig.controller.status == .networkUnavailable)
        let before = await rig.backend.log.filter { $0 == "request" }.count
        rig.controller.refreshNow(); await rig.clock.advance(120)
        #expect(await rig.backend.log.filter { $0 == "request" }.count == before); await rig.finish()
    }
    @Test func intervalChangeRequestsImmediately() async throws {
        let rig = try ControllerRig(); await rig.start(); let before = await rig.backend.log.filter { $0 == "request" }.count
        rig.controller.setClosedInterval(.s30); await settle()
        #expect(await rig.backend.log.filter { $0 == "request" }.count == before + 1); #expect(rig.controller.appState.closedInterval == .s30); await rig.finish()
    }
    @Test func refreshSpinnerStopsAtReplyOrDeadline() async throws {
        let rig = try ControllerRig(); await rig.start(); rig.controller.refreshNow(); await settle(); #expect(rig.controller.refreshing)
        await rig.reply(); #expect(!rig.controller.refreshing)
        rig.controller.refreshNow(); await settle(); await rig.clock.advance(9); #expect(rig.controller.refreshing)
        await rig.clock.advance(1); #expect(!rig.controller.refreshing); await rig.finish()
    }
    @Test func sessionEndedOffersSignInAgainAndInvalidCredentialsDoesNot() async throws {
        for terminal in [ConnectionStatus.sessionEnded, .signInFailed("Invalid credentials"), .verificationRequired] {
            let rig = try ControllerRig(); await rig.start(); rig.backend.output.yield(.status(terminal)); await settle()
            await rig.events.send(.network(false)); await rig.events.send(.network(true)); await rig.events.send(.wake); await settle()
            #expect(rig.controller.status == terminal)
            let before = await rig.backend.log.filter { $0 == "connect" }.count
            await rig.clock.advance(300); #expect(await rig.backend.log.filter { $0 == "connect" }.count == before)
            await rig.controller.signInAgain(); #expect(await rig.backend.log.filter { $0 == "login" }.count == (terminal == .sessionEnded ? 1 : 0)); await rig.finish()
        }
    }
    @Test func signInSavesSessionToSecrets() async throws {
        let rig = try ControllerRig(configured: false); await rig.start(); await rig.controller.signIn(appCredentials)
        #expect(rig.secrets.value == .init(credentials: appCredentials, session: appSession)); #expect(rig.controller.chargers == [appCharger]); await rig.finish()
    }
    @Test func sessionUpdateSaveFailureIsVisible() async throws {
        let rig = try ControllerRig(); await rig.start(); rig.secrets.failSave = true
        rig.backend.output.yield(.sessionUpdated(appSession)); await settle()
        guard case .error = rig.controller.status else { Issue.record("Expected persistence error"); await rig.finish(); return }
        await rig.finish()
    }
    @Test func lateSessionUpdateAfterSignOutOrAccountReplacementIsIgnored() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.controller.signOut()
        rig.backend.output.yield(.sessionUpdated(appSession)); await settle(); #expect(rig.secrets.value == nil)
        await rig.controller.signIn(appCredentials)
        let obsolete = AccountSession(authToken: "old", userID: "different-user", expiresAt: .distantFuture, nickname: "")
        rig.backend.output.yield(.sessionUpdated(obsolete)); await settle(); #expect(rig.secrets.value?.session == appSession); await rig.finish()
    }
    @Test func signOutDeletesSecretsAndDisconnects() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.controller.signOut()
        #expect(rig.secrets.value == nil); #expect(rig.controller.status == .notConfigured); #expect(await rig.backend.log.last == "disconnect"); await rig.finish()
        #expect(rig.events.stopped); #expect(rig.clock.entries.allSatisfy { $0.cancelled })
    }
}

@Suite @MainActor struct ControllerLifecycleTests {
    @Test func connectedEventAndConnectReturnDoNotDoublePublish() async throws {
        let rig = try ControllerRig(); await rig.backend.blockConnection(); await rig.start()
        #expect(await rig.backend.log.filter { $0 == "request" }.count == 1)
        await rig.backend.releaseConnection(); await settle()
        #expect(await rig.backend.log.filter { $0 == "request" }.count == 1)
        await rig.finish()
    }
    @Test func stopWaitsForDisconnectAndStopsForwarding() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.reply()
        await rig.backend.blockDisconnection()
        var stopped = false
        let stopping = Task { await rig.controller.stop(); stopped = true }
        await settle(); #expect(!stopped); #expect(rig.events.stopped)
        await rig.backend.releaseDisconnection(); await stopping.value; #expect(stopped)
        let previous = rig.controller.snapshot
        rig.backend.output.snapshot(.init(receivedAt: .distantFuture, readings: [])); await settle()
        #expect(rig.controller.snapshot == previous)
        #expect(rig.clock.entries.allSatisfy { $0.cancelled })
        await rig.finish()
    }
    @Test func connectionRequestsExactlyOnceAndRecoversImmediately() async throws {
        let rig = try ControllerRig(); await rig.start()
        #expect(await rig.backend.log.filter { $0 == "request" }.count == 1)
        rig.backend.output.yield(.status(.error("dropped"))); await settle()
        rig.backend.output.yield(.status(.connected)); await settle()
        #expect(await rig.backend.log.filter { $0 == "request" }.count == 2)
        await rig.finish()
    }
    @Test func selectionPersistsAndReplacesSnapshot() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.reply()
        let other = ChargerInfo(serial: "synthetic-other", model: "A2345", alias: "Other", name: "Prime")
        await rig.controller.select(other); await settle()
        #expect(rig.controller.snapshot == nil)
        #expect(StateStore(fileURL: rig.directory.appending(path: "state.json", directoryHint: .notDirectory)).load().state.charger == other)
        #expect(await rig.backend.log.filter { $0 == "connect" }.count == 2)
        await rig.finish()
    }
}

@Suite @MainActor struct AccountReplacementTests {
    @Test func obsoleteSignOutCannotDeleteReplacementAccount() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.backend.blockDisconnection()
        let outgoing = Task { await rig.controller.signOut() }; await settle()
        let incoming = Task { await rig.controller.signIn(appCredentials) }; await settle()
        await rig.backend.releaseDisconnection(); await incoming.value; await outgoing.value
        #expect(rig.secrets.value?.session == appSession)
        #expect(rig.controller.status != .notConfigured)
        await rig.finish()
    }
    @Test func signInReplacementClearsPreviousReadings() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.reply()
        await rig.controller.signIn(appCredentials)
        #expect(rig.controller.snapshot == nil); #expect(rig.controller.isStale)
        await rig.finish()
    }
}

@Suite @MainActor struct DeliveryAndSelectionRaceTests {
    @Test func queuedOldSameUserEventsCannotCrossAuthenticationReplacement() async throws {
        for signOutFirst in [false, true] {
            let rig = try ControllerRig(); await rig.start()
            // Retain the old delivery queue, as if a backend had already emitted
            // these events but the consumer had not yet been scheduled.
            let oldQueue = rig.backend.output.current
            if signOutFirst { await rig.controller.signOut() }
            await rig.controller.signIn(appCredentials); await settle()
            let currentStatus = rig.controller.status
            let obsolete = AccountSession(authToken: "synthetic-obsolete", userID: appSession.userID, expiresAt: .distantFuture, nickname: "")
            oldQueue.yield(.sessionUpdated(obsolete)); oldQueue.yield(.status(.sessionEnded)); await settle()
            #expect(rig.secrets.value?.session == appSession)
            #expect(rig.controller.status == currentStatus)
            // New-context delivery remains usable after the handover.
            let accepted = AccountSession(authToken: "synthetic-accepted", userID: appSession.userID, expiresAt: .distantFuture, nickname: "")
            rig.backend.output.yield(.sessionUpdated(accepted)); await settle()
            #expect(rig.secrets.value?.session == accepted)
            await rig.finish()
        }
    }
    @Test func overlappingSelectionsConnectOnlyTheLatestPersistedCharger() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.backend.blockDisconnection()
        let a = ChargerInfo(serial: "synthetic-A", model: "A2345", alias: "A", name: "Prime")
        let b = ChargerInfo(serial: "synthetic-B", model: "A2345", alias: "B", name: "Prime")
        let first = Task { await rig.controller.select(a) }; await settle()
        let second = Task { await rig.controller.select(b) }; await settle()
        await rig.backend.releaseDisconnection(); await first.value; await second.value; await settle()
        #expect(rig.controller.appState.charger == b)
        #expect(StateStore(fileURL: rig.directory.appending(path: "state.json", directoryHint: .notDirectory)).load().state.charger == b)
        #expect(await rig.backend.connectedChargers.last == b)
        #expect(await !rig.backend.connectedChargers.contains(a))
        await rig.finish()
    }
}

@Suite @MainActor struct RestoreDeliveryTests {
    @Test func reconnectRestoreHandsOverItsDeliveryQueue() async throws {
        let rig = try ControllerRig(); await rig.start()
        let previous = rig.backend.output.current
        await rig.events.send(.sleep); await rig.events.send(.wake); await settle()
        let obsolete = AccountSession(authToken: "synthetic-before-wake", userID: appSession.userID, expiresAt: .distantFuture, nickname: "")
        previous.yield(.sessionUpdated(obsolete)); previous.yield(.status(.sessionEnded)); await settle()
        #expect(rig.secrets.value?.session == appSession)
        #expect(rig.controller.status == .connected)
        rig.backend.output.yield(.status(.sessionEnded)); await settle()
        #expect(rig.controller.status == .sessionEnded)
        await rig.finish()
    }
}

@Suite @MainActor struct SelectionStatusRaceTests {
    @Test func queuedConnectedStatusDuringCleanupCannotPreventReplacementConnection() async throws {
        let rig = try ControllerRig(); await rig.start(); await rig.backend.blockDisconnection()
        let old = rig.backend.output.current
        let replacement = ChargerInfo(serial: "synthetic-replacement", model: "A2345", alias: "Replacement", name: "Prime")
        let selecting = Task { await rig.controller.select(replacement) }; await settle()
        old.yield(.status(.connected)); await settle()
        await rig.backend.releaseDisconnection(); await selecting.value; await settle()
        #expect(await rig.backend.connectedChargers.last == replacement)
        #expect(rig.controller.appState.charger == replacement)
        await rig.finish()
    }
}

@Suite @MainActor struct SelectionSystemEventRaceTests {
    @Test func systemEventsDuringSelectionCleanupCannotCaptureOldChargerOrWedgeLaterRetry() async throws {
        for event in [SystemEvent.network(true), .wake] {
            let rig = try ControllerRig(); await rig.start(); await rig.backend.blockDisconnection()
            let replacement = ChargerInfo(serial: "synthetic-system-event", model: "A2345", alias: "New", name: "Prime")
            let selecting = Task { await rig.controller.select(replacement) }; await settle()
            await rig.events.send(event); await settle()
            await rig.backend.releaseDisconnection(); await selecting.value; await settle()
            #expect(rig.controller.appState.charger == replacement)
            #expect(StateStore(fileURL: rig.directory.appending(path: "state.json", directoryHint: .notDirectory)).load().state.charger == replacement)
            #expect(await rig.backend.connectedChargers.last == replacement)
            await rig.events.send(.network(true)); await rig.events.send(.wake); await settle()
            #expect(await rig.backend.connectedChargers.last == replacement)
            #expect(rig.controller.status == .connected)
            await rig.finish()
        }
    }
}
