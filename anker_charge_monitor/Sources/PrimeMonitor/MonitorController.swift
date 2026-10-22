import Foundation
import Observation
import PrimeMonitorCore

/// Why port controls are unavailable (plan "Switch state and actions", "One
/// operation at a time").
enum PortControlBlock: Equatable, Sendable { case anotherPortChanging, disconnected, stale }

@MainActor @Observable final class MonitorController {
    private(set) var snapshot: ChargerSnapshot?
    /// The running port operation; the controller owns it, so closing the panel
    /// changes nothing. Nil once it finishes.
    private(set) var portOperation: PortOperation?
    /// The last operation's unconfirmed result ("Outcome lifetime"). A confirmed
    /// operation leaves none. It survives sign-out, charger change and
    /// authentication replacement.
    private(set) var portOutcome: PortOperationOutcome?
    private(set) var status: ConnectionStatus = .notConfigured
    private(set) var isStale = true
    private(set) var chargers: [ChargerInfo] = []
    private(set) var refreshing = false
    private(set) var displayTime: Date
    private(set) var appState: AppState
    private let backend: any ChargerBackend
    private let secrets: any SecretStore
    private let makeProvider: ((CredentialSelection) throws -> any CredentialProvider)?
    private var credentialTask: Task<Void, Never>?
    private var credentialGeneration = UUID()
    private var loadingCredentials = false
    private var draining: [UUID: Task<Void, Never>] = [:]
    private let state: StateStore
    private let events: SystemEvents
    private let now: () -> Date
    private let scheduler: any PollScheduler
    private var tracker: StalenessTracker
    private var canSave: Bool
    private var active: StoredSecrets?
    private var running = false
    private var stopping = false
    private var online = false
    private var asleep = false
    private var open = false
    private var restored = false
    private var backendReady = false
    private var connected = false
    private var wantsConnection = false
    private var terminal: ConnectionStatus?
    private var persistenceProblem: String?
    private var stateProblem: String?
    private var credentialProblem: String?
    private var presentationProblem: String? { stateProblem ?? persistenceProblem ?? credentialProblem }
    private var generation = UUID()
    private var connectionGeneration = UUID()
    private var selectionGeneration = UUID()
    private var pendingSelection: UUID?
    private var deliveryGeneration = UUID()
    private var forwarder: Task<Void, Never>?
    private var operation: Task<Void, Never>?
    private var connection: Task<Void, Never>?
    private var request: Task<Void, Never>?
    private var cleanup: Task<Void, Never>?
    private var poll: (any Cancellable)?
    private var tick: (any Cancellable)?
    private var refreshDeadline: Date?
    private struct PortEnding { let id: UUID; let task: Task<Void, Never> }
    /// Identifies the running operation; results of its publishes carry it.
    private var portOperationID: UUID?
    /// The one bounded ending attempt in progress; overlapping endings share it.
    private var portEnding: PortEnding?
    private var switchWrites: [UUID: Task<Void, Never>] = [:]
    /// Operation status requests and fence reads, apart from the polling `request`.
    private var portRequests: [UUID: Task<Void, Never>] = [:]
    /// Changes whenever the controller sees the link go down or come up.
    private var linkSession = UUID()
    var needsSetup: Bool { !secrets.configured }

    init(backend: any ChargerBackend, secrets: any SecretStore, state: StateStore, events: SystemEvents,
         now: @escaping () -> Date, scheduler: any PollScheduler,
         makeProvider: ((CredentialSelection) throws -> any CredentialProvider)? = nil) {
        self.backend = backend; self.secrets = secrets; self.state = state; self.events = events
        self.makeProvider = makeProvider
        self.now = now; self.scheduler = scheduler
        displayTime = now()
        let loaded = state.load(); appState = loaded.state; canSave = loaded.canSave
        stateProblem = loaded.problem
        if let configuration = loaded.state.credentials {
            do {
                guard let makeProvider else { throw CredentialFailure.unsupported }
                secrets.replaceProvider(try makeProvider(configuration), selection: configuration)
            } catch {
                secrets.replaceProvider(nil)
                status = .error("Couldn't configure the credential provider. Open Settings.")
            }
        } else if makeProvider != nil {
            secrets.replaceProvider(nil)
        }
        tracker = StalenessTracker(closed: loaded.state.closedInterval)
        if let problem = loaded.problem { status = .error(problem) }
    }
    func start() {
        guard !running, !stopping else { return }; running = true; generation = UUID()
        let expected = generation
        events.start { [weak self] in await self?.receive($0) }
        if secrets.configured, case .notConfigured = status { status = .connecting }
        loadingCredentials = true
        operation = Task { [weak self] in
            guard let self else { return }
            let saved: StoredSecrets
            do {
                guard let value = try await secrets.load() else {
                    if self.valid(expected) { self.loadingCredentials = false }
                    if self.valid(expected), case .connecting = self.status { self.status = .notConfigured }
                    return
                }
                saved = value
            } catch {
                if self.valid(expected) { self.loadingCredentials = false }
                if self.valid(expected) { self.status = .error(self.credentialMessage(error)) }
                return
            }
            guard self.valid(expected) else { return }
            self.loadingCredentials = false
            self.active = saved; self.scheduleTick()
            if let session = saved.session {
                await self.disconnect()
                guard self.valid(expected), await self.replaceForwarder(expected) else { return }
                await backend.restore(session, credentials: saved.credentials)
            }
            else { await self.authenticate(saved.credentials, cancelOperation: false); return }
            guard self.valid(expected) else { return }
            self.restored = true; self.backendReady = true; self.reconcile()
        }
    }
    func stop() async {
        // Normally already ended by `AppDelegate`; the disconnect below awaits it.
        endPortOperation(.quit)
        stopping = true
        pendingSelection = nil
        running = false; generation = UUID(); events.stop(); tick?.cancel(); tick = nil
        poll?.cancel(); poll = nil; refreshing = false; refreshDeadline = nil
        deliveryGeneration = UUID()
        let forwarding = forwarder; forwarder = nil; forwarding?.cancel()
        operation?.cancel(); let operation = operation; self.operation = nil
        credentialGeneration = UUID()
        credentialTask?.cancel(); let credentials = credentialTask; credentialTask = nil
        let draining = Array(draining.values)
        await disconnect(); await operation?.value; await credentials?.value; await forwarding?.value
        for task in draining { await task.value }
        loadingCredentials = false
        stopping = false
    }
    private func valid(_ expected: UUID) -> Bool { running && generation == expected && !Task.isCancelled }
    private var allowed: Bool { running && active != nil && restored && online && !asleep && terminal == nil && pendingSelection == nil }
    private func reconcile() {
        guard allowed, let charger = appState.charger, connection == nil, !connected else { return }
        let expected = generation, selected = selectionGeneration, attempt = UUID(), previousCleanup = cleanup; connectionGeneration = attempt
        status = presentationProblem.map { .error($0) } ?? .connecting
        connection = Task { [weak self, backend] in
            guard let self else { return }
            defer { self.releaseConnection(attempt) }
            await previousCleanup?.value
            guard self.valid(expected), self.allowed, self.connectionGeneration == attempt,
                  self.selectionGeneration == selected, self.appState.charger == charger else { return }
            if !self.backendReady, let saved = self.active, let session = saved.session {
                guard await self.replaceForwarder(expected) else { return }
                guard self.connectionGeneration == attempt, self.selectionGeneration == selected else { return }
                await backend.restore(session, credentials: saved.credentials)
                guard self.valid(expected), self.connectionGeneration == attempt, self.selectionGeneration == selected else { return }
                self.backendReady = true
            }
            guard self.valid(expected), self.allowed, self.connectionGeneration == attempt,
                  self.selectionGeneration == selected, self.appState.charger == charger else { return }
            do {
                self.wantsConnection = true
                try await backend.connect(to: charger)
                guard self.valid(expected), self.allowed, self.connectionGeneration == attempt,
                      self.selectionGeneration == selected, self.appState.charger == charger else { return }
                self.didConnect()
            } catch {
                guard self.valid(expected), self.connectionGeneration == attempt else { return }
                if self.terminal == nil { self.status = .error(self.presentationProblem ?? "Connection failed.") }
            }
        }
    }
    private func releaseConnection(_ attempt: UUID) {
        // A cancelled/aborted task must not retain the slot or clear a successor.
        if connectionGeneration == attempt { connection = nil }
    }
    private func disconnect() async {
        portLinkLost()
        connectionGeneration = UUID(); backendReady = false; wantsConnection = false; connected = false; poll?.cancel(); poll = nil
        refreshing = false; refreshDeadline = nil
        let oldConnection = connection, oldRequest = request
        connection = nil; request = nil; oldConnection?.cancel(); oldRequest?.cancel()
        let oldPortRequests = Array(portRequests.values), oldWrites = Array(switchWrites.values)
        for task in oldPortRequests { task.cancel() }
        // `cleanup` may be a bounded ending attempt: it runs on the old link first.
        let previous = cleanup, backend = backend
        let draining = Task {
            await previous?.value; await backend.disconnect()
            await oldConnection?.value; await oldRequest?.value
            for task in oldPortRequests + oldWrites { await task.value }
        }
        cleanup = draining; await draining.value
    }
    private func receive(_ event: SystemEvent) async {
        guard running else { return }
        switch event {
        case .sleep:
            asleep = true; await disconnect()
        case .wake:
            asleep = false
            if !online, terminal == nil, active != nil { status = presentationProblem.map { .error($0) } ?? .networkUnavailable }
            reconcile()
        case .network(let available):
            online = available
            if !available {
                if terminal == nil, active != nil { status = presentationProblem.map { .error($0) } ?? .networkUnavailable }
                await disconnect()
            } else { reconcile() }
        }
        updateStale()
    }
    private func receive(_ event: BackendEvent) {
        guard running, active != nil else { return }
        switch event {
        case .snapshot(let value, let mark):
            guard allowed, wantsConnection else { return }
            snapshot = value; tracker.replyReceived(at: now()); refreshing = false; refreshDeadline = nil
            // The operation first: a reply that finishes it may also clear its outcome.
            feedPort(.snapshot(value, mark))
            if let outcome = portOutcome, let context = portContext,
               outcome.isCleared(by: value, mark: mark, in: context) { portOutcome = nil }
        case .alive: break // An echo or heartbeat never satisfies a status request.
        case .sessionUpdated(let session):
            guard restored, active?.session?.userID == session.userID else { break }
            active?.session = session; persistSecrets()
        case .status(let value):
            switch value {
            case .sessionEnded, .signInFailed, .verificationRequired:
                endPortOperation(.terminalAuthentication)
                terminal = value; status = value; connected = false; poll?.cancel(); poll = nil
                refreshing = false; refreshDeadline = nil
            case .connected:
                guard allowed, wantsConnection else { break }
                didConnect()
            case .connecting, .error:
                guard allowed, wantsConnection else { break }
                portLinkLost(); connected = false; poll?.cancel(); poll = nil
                if presentationProblem == nil { status = value }
            default: break
            }
        }
        updateStale()
    }
    func panelOpened() { open = true; sendRequest(); schedulePoll(); updateStale() }
    func panelClosed() { open = false; schedulePoll(); updateStale() }
    func refreshNow() { sendRequest(spinner: true); updateStale() }
    private func didConnect() {
        guard !connected else { return }
        connected = true
        if presentationProblem == nil { status = .connected }
        sendRequest(); schedulePoll()
        linkSession = UUID(); refreshPortFences()
    }
    private func sendRequest(spinner: Bool = false) {
        guard allowed, connected, request == nil else { return }
        if spinner { refreshing = true; refreshDeadline = now().addingTimeInterval(PollPolicy.replyDeadline) }
        // Record before the await: a reply may arrive before publish completes.
        tracker.requestSent(at: now())
        let expected = generation, attempt = connectionGeneration
        request = Task { [weak self, backend] in
            do { try await backend.requestSnapshot() }
            catch {
                if let self, self.statusRequestFailed(expected, attempt) { self.refreshing = false }
            }
            guard let self, self.valid(expected), self.connectionGeneration == attempt else { return }
            self.request = nil; self.updateStale()
        }
    }
    private func statusRequestFailed(_ expected: UUID, _ attempt: UUID) -> Bool {
        guard valid(expected), connectionGeneration == attempt, terminal == nil else { return false }
        status = .error(presentationProblem ?? "Status request failed."); return true
    }
    private func schedulePoll() {
        poll?.cancel(); poll = nil
        guard allowed, connected, let interval = PollPolicy.interval(panelOpen: open, closed: appState.closedInterval, asleep: asleep) else { return }
        poll = scheduler.schedule(after: interval) { [weak self] in self?.sendRequest(); self?.schedulePoll() }
    }
    private func scheduleTick() {
        tick?.cancel()
        guard running, active != nil || portOperation != nil else { tick = nil; return }
        // The tick also drives port operation time ("Drive ticks through scheduleTick").
        tick = scheduler.schedule(after: 1) { [weak self] in self?.updateStale(); self?.feedPort(.tick); self?.scheduleTick() }
    }
    private func updateStale() {
        let current = now()
        // The existing one-second tick must invalidate age even when the
        // retained snapshot, connection status and stale Bool stay unchanged.
        displayTime = current
        isStale = tracker.isStale(snapshotAt: snapshot?.receivedAt, now: current)
        if let deadline = refreshDeadline, current >= deadline { refreshing = false; refreshDeadline = nil }
    }
    /// Editing is a context change, but does not request vault access. Invalidate
    /// synchronously and retain the superseded work until cleanup has joined it.
    func setCredentialSelection(_ configuration: CredentialSelection) {
        guard running, appState.credentials != configuration else { return }
        endPortOperation(.credentialSelectionEdit)
        generation = UUID(); credentialGeneration = UUID()
        let previousOperation = operation, previousCredentials = credentialTask
        retire(previousOperation); retire(previousCredentials); credentialTask = nil; loadingCredentials = false
        active = nil; restored = false; terminal = nil; persistenceProblem = nil; credentialProblem = nil
        snapshot = nil; chargers = []; secrets.replaceProvider(nil)
        appState.credentials = configuration; persistState()
        do {
            guard let makeProvider else { throw CredentialFailure.unsupported }
            secrets.replaceProvider(try makeProvider(configuration), selection: configuration)
            status = .error(presentationProblem ?? "Credential settings changed. Sign In using your vault to continue.")
        } catch { status = .error(credentialMessage(error)) }
        operation = Task { [weak self] in
            await self?.disconnect()
        }
    }
    private func retire(_ task: Task<Void, Never>?) {
        guard let task else { return }
        task.cancel()
        let id = UUID()
        draining[id] = Task { [weak self] in
            await task.value
            self?.draining[id] = nil
        }
    }
    /// Settings/composition supplies the adapter; authentication and cache lifetime
    /// do not depend on its process, wire format, or vault implementation.
    func connect(using configuration: CredentialSelection, reload: Bool = false) async {
        guard running else { return }
        endPortOperation(.authenticationReplacement)
        if loadingCredentials {
            retire(operation); operation = nil; loadingCredentials = false
        }
        setCredentialSelection(configuration)
        let expected = UUID(); credentialGeneration = expected
        retire(credentialTask)
        let previousOperation = operation
        status = presentationProblem.map { .error($0) } ?? .connecting
        let task = Task { [weak self] in
            guard let self else { return }
            await previousOperation?.value
            guard self.running, self.credentialGeneration == expected, !Task.isCancelled else { return }
            do {
                guard let saved = try await self.secrets.load(reload: reload) else { throw CredentialFailure.unavailable }
                guard self.running, self.credentialGeneration == expected, !Task.isCancelled else { return }
                await self.signIn(saved.credentials)
            } catch {
                guard self.running, self.credentialGeneration == expected, !Task.isCancelled else { return }
                let message = self.credentialMessage(error)
                self.credentialProblem = message; self.status = .error(message)
            }
        }
        credentialTask = task
        await task.value
        if credentialGeneration == expected { credentialTask = nil }
    }
    private func credentialMessage(_ error: any Error) -> String {
        (error as? CredentialFailure)?.message ?? "Couldn't retrieve credentials. Open and unlock your vault, then Retry."
    }
    func signIn(_ credentials: AnkerCredentials) async {
        await authenticate(credentials, cancelOperation: true)
    }
    private func authenticate(_ credentials: AnkerCredentials, cancelOperation: Bool) async {
        guard running else { return }
        endPortOperation(.authenticationReplacement)
        let expected = UUID(); generation = expected
        pendingSelection = nil
        // Invalidate acceptance before awaiting cleanup or delivery handover.
        active = nil; restored = false; terminal = nil; persistenceProblem = nil; credentialProblem = nil
        snapshot = nil; chargers = []; tracker = StalenessTracker(closed: appState.closedInterval); updateStale()
        if cancelOperation { operation?.cancel() }
        await disconnect()
        guard valid(expected), await replaceForwarder(expected) else { return }
        active = StoredSecrets(credentials: credentials, session: nil)
        status = presentationProblem.map { .error($0) } ?? .connecting
        do {
            let session = try await backend.signIn(credentials)
            guard valid(expected) else { return }
            active = .init(credentials: credentials, session: session); restored = true; backendReady = true
            persistSecrets(); scheduleTick(); await reloadChargers(); reconcile()
        } catch {
            guard valid(expected) else { return }
            // Terminal error classification crosses the Core event boundary.
            await Task.yield()
            if terminal == nil { status = .error("Sign-in failed. Open Settings.") }
        }
    }
    private func replaceForwarder(_ expected: UUID) async -> Bool {
        deliveryGeneration = UUID()
        let old = forwarder; forwarder = nil; old?.cancel(); await old?.value
        guard valid(expected) else { return false }
        let delivery = UUID(); deliveryGeneration = delivery
        let stream = await backend.subscribeToEvents()
        guard valid(expected), deliveryGeneration == delivery else { return false }
        forwarder = Task { [weak self] in
            for await event in stream {
                guard !Task.isCancelled else { return }
                guard let self, self.running, self.deliveryGeneration == delivery else { return }
                self.receive(event)
            }
        }
        return true
    }
    func signOut() async {
        endPortOperation(.signOut)
        let expected = UUID(); generation = expected
        credentialGeneration = UUID()
        let pendingCredentials = credentialTask; credentialTask = nil; pendingCredentials?.cancel()
        let pendingOperation = operation; operation = nil; pendingOperation?.cancel()
        let draining = Array(draining.values)
        do { try secrets.delete() } catch { status = .error("Couldn't clear account cache.") }
        appState.credentials = nil; persistState()
        pendingSelection = nil
        active = nil; restored = false; terminal = nil; persistenceProblem = nil; credentialProblem = nil
        deliveryGeneration = UUID()
        let old = forwarder; forwarder = nil; old?.cancel()
        tick?.cancel(); tick = nil
        await old?.value; await pendingCredentials?.value; await pendingOperation?.value
        for task in draining { await task.value }
        loadingCredentials = false
        guard generation == expected else { return }
        await disconnect()
        guard generation == expected else { return }
        snapshot = nil; chargers = []; tracker = StalenessTracker(closed: appState.closedInterval); updateStale()
        do { try secrets.delete(); status = presentationProblem.map { .error($0) } ?? .notConfigured }
        catch { status = .error("Couldn't clear account cache.") }
    }
    func signInAgain() async {
        guard terminal == .sessionEnded, let credentials = active?.credentials else { return }
        await signIn(credentials)
    }
    func reloadChargers() async {
        guard running, restored, terminal == nil else { return }; let expected = generation
        do {
            let values = try await backend.listChargers(); guard valid(expected) else { return }; chargers = values
        } catch {
            guard valid(expected) else { return }; await Task.yield()
            if terminal == nil { status = .error(presentationProblem ?? "Couldn't load chargers.") }
        }
    }
    func select(_ charger: ChargerInfo) async {
        guard running, restored, terminal == nil else { return }
        endPortOperation(.chargerChange)
        let expected = generation, selected = UUID(); selectionGeneration = selected
        pendingSelection = selected
        defer {
            if pendingSelection == selected {
                pendingSelection = nil
                reconcile()
            }
        }
        await disconnect(); guard valid(expected), selectionGeneration == selected else { return }
        appState.charger = charger; snapshot = nil; tracker = StalenessTracker(closed: appState.closedInterval)
        persistState(); updateStale()
    }
    func setClosedInterval(_ interval: ClosedInterval) {
        tracker.setClosedInterval(interval, at: now()); appState.closedInterval = interval
        persistState(); sendRequest(); schedulePoll(); updateStale()
    }
    func setMenuBarTextSize(_ size: MenuBarTextSize) {
        appState.menuBarTextSize = size; persistState()
    }
    private func persistSecrets() {
        guard let active else { return }
        do { try secrets.save(active); persistenceProblem = nil }
        catch { persistenceProblem = "Couldn't retain account session in memory."; status = .error(persistenceProblem!) }
    }
    private func persistState() {
        guard canSave else { stateProblem = "Saved state could not be preserved."; status = .error(stateProblem!); return }
        do { try state.save(appState); stateProblem = nil }
        catch { stateProblem = "Couldn't save settings."; status = .error(stateProblem!) }
    }
}

// MARK: - Port control
// Contracts: docs/port_control_implementation_plan.md "Design decisions". The Core
// `PortOperation` decides; this extension feeds it events and executes its actions.
extension MonitorController {
    var portControlBlock: PortControlBlock? {
        if portOperation != nil || portEnding != nil { return .anotherPortChanging }
        guard allowed, connected, appState.charger != nil else { return .disconnected }
        return isStale ? .stale : nil
    }
    /// Starts a plain turn-off or turn-on. Returns false, doing nothing, while
    /// `portControlBlock` is set.
    @discardableResult func turnPort(_ target: PortSwitch, on: Bool) -> Bool {
        startPortOperation(on ? .turnOn : .turnOff, target)
    }
    /// Starts a restart: off, the policy pause, then on. Returns false, doing
    /// nothing, while `portControlBlock` is set.
    @discardableResult func restartPort(_ target: PortSwitch) -> Bool { startPortOperation(.restart, target) }
    func dismissPortOutcome() { portOutcome = nil }
    /// Quit: ends any operation (a restart attempts "on" against the current link)
    /// and returns when that bounded attempt, or one already in progress, is over.
    func endPortOperation() async { await endPortOperation(.quit)?.value }

    private var portContext: PortOperationContext? {
        appState.charger.map { PortOperationContext(account: generation, charger: $0.serial, chargerLabel: $0.label) }
    }
    private func startPortOperation(_ kind: PortOperationKind, _ target: PortSwitch) -> Bool {
        guard portControlBlock == nil, let context = portContext else { return false }
        portOutcome = nil; portOperationID = UUID()
        portOperation = PortOperation(kind, target: target, context: context)
        // The tick already runs while signed in; start it only if it does not.
        if tick == nil { scheduleTick() }
        feedPort(.requested)
        return true
    }
    private func feedPort(_ event: PortOperationEvent) {
        guard var operation = portOperation else { return }
        let actions = operation.handle(event, at: now())
        if operation != portOperation { portOperation = operation }
        for action in actions {
            switch action {
            case .publish(let target, let on, let id): publishSwitch(target, on: on, id: id)
            case .requestStatus: requestOperationStatus()
            case .finish(let outcome): finishPortOperation(outcome)
            case .endingPublish: break // Only `.ending` emits it; see endPortOperation(_:).
            }
        }
    }
    private func finishPortOperation(_ outcome: PortOperationOutcome) {
        portOperation = nil; portOperationID = nil
        portOutcome = outcome.kind == .confirmed ? nil : outcome
        // No publish completed: take a fence now so later evidence can clear it.
        if portOutcome != nil, outcome.boundary == nil { refreshPortFences() }
    }
    private func publishSwitch(_ target: PortSwitch, on: Bool, id: PortPublishID) {
        let operation = portOperationID, expected = generation, attempt = connectionGeneration
        let selected = selectionGeneration, write = UUID()
        switchWrites[write] = Task { [weak self, backend] in
            let event: PortOperationEvent
            do { event = .published(try await backend.setPortSwitch(target, on: on), id: id) }
            catch { event = .publishFailed(id: id) }
            guard let self else { return }
            self.switchWrites[write] = nil
            guard self.running, self.generation == expected, self.connectionGeneration == attempt,
                  self.selectionGeneration == selected, self.portOperationID == operation else { return }
            self.feedPort(event)
        }
    }
    /// Independent of polling: an in-flight poll never absorbs it. Recorded with
    /// the staleness tracker as `sendRequest` records polls.
    private func requestOperationStatus() {
        guard allowed, connected else { return }
        tracker.requestSent(at: now())
        let expected = generation, attempt = connectionGeneration, id = UUID()
        portRequests[id] = Task { [weak self, backend] in
            var failed = false
            do { try await backend.requestSnapshot() } catch { failed = true }
            guard let self else { return }
            self.portRequests[id] = nil
            if failed { _ = self.statusRequestFailed(expected, attempt) }
        }
    }
    /// Sleep, network loss or a dropped link: the operation suspends publishing.
    private func portLinkLost() {
        linkSession = UUID()
        if portOperation?.isSuspended == false { feedPort(.disconnected) }
    }
    /// After a (re)connection, or for an outcome without a boundary: read the
    /// backend fence, then resume a suspended operation from it and move the
    /// outcome's clearing boundary onto this connection.
    private func refreshPortFences() {
        guard allowed, connected, let context = portContext else { return }
        let resume = portOperation?.isSuspended == true
        let outcome = portOutcome?.context.isSameOrigin(as: context) == true
        guard resume || outcome else { return }
        let expected = generation, link = linkSession, operation = portOperationID, id = UUID()
        portRequests[id] = Task { [weak self, backend] in
            let fence = try? await backend.commandFence()
            guard let self else { return }
            self.portRequests[id] = nil
            guard let fence, self.valid(expected), self.connected, self.linkSession == link,
                  let context = self.portContext else { return }
            self.portOutcome?.replaceBoundary(with: fence, in: context)
            if resume, self.portOperationID == operation, self.portOperation?.isSuspended == true {
                self.feedPort(.reconnected(fence))
            }
        }
    }
    /// Ends the running operation for a context change. Synchronously finishes it
    /// (blocking new dispatch) and captures the old link before the caller
    /// invalidates anything. A restart's ending "on" write runs in a bounded task,
    /// serialized after in-flight switch writes, that becomes `cleanup`: the
    /// caller's disconnect, and so any replacement connection, waits for it.
    /// Overlapping endings share that task.
    @discardableResult
    private func endPortOperation(_ reason: PortOperationEndingReason) -> Task<Void, Never>? {
        guard var operation = portOperation else { return portEnding?.task }
        let reachable = allowed && connected, attempt = connectionGeneration
        let actions = operation.handle(.ending(reason), at: now())
        portOperation = operation
        var write: (target: PortSwitch, on: Bool)?
        for action in actions {
            switch action {
            case .endingPublish(let target, let on): write = (target, on)
            case .finish(let outcome): finishPortOperation(outcome)
            case .publish, .requestStatus: break // `.ending` never starts a phase.
            }
        }
        guard reachable, let write else { return portEnding?.task }
        let id = UUID(), previous = cleanup, writes = Array(switchWrites.values), backend = backend
        let attemptWrite = Task {
            await previous?.value
            for task in writes { await task.value }
            guard !Task.isCancelled else { return }
            _ = try? await backend.setPortSwitch(write.target, on: write.on)
        }
        let task = Task {
            let expired = await self.expires(attemptWrite, after: PortControlPolicy.exitAttemptTimeout)
            if expired {
                // Revoke the old command context, close its link and drain its sends;
                // the cancelled attempt can no longer write.
                attemptWrite.cancel(); await backend.abortCommands(); await attemptWrite.value
            }
            self.endedPortOperation(id, aborted: expired, recover: reason != .quit, attempt: attempt)
        }
        portEnding = PortEnding(id: id, task: task); cleanup = task
        return task
    }
    /// True when the scheduler deadline passes before `work` finishes.
    private func expires(_ work: Task<Void, Never>, after seconds: TimeInterval) async -> Bool {
        let race = DeadlineRace()
        return await withCheckedContinuation { continuation in
            race.continuation = continuation
            let timer = scheduler.schedule(after: seconds) { race.finish(expired: true) }
            Task { await work.value; timer.cancel(); race.finish(expired: false) }
        }
    }
    private func endedPortOperation(_ id: UUID, aborted: Bool, recover: Bool, attempt: UUID) {
        if portEnding?.id == id { portEnding = nil }
        // The abort left the backend without a link. When no context change has
        // replaced this connection (a failed reload, say), reconnect through the
        // ordinary cleanup path; stop() joins the retained task.
        guard aborted, recover, running, !stopping, connectionGeneration == attempt else { return }
        let recovery = UUID()
        draining[recovery] = Task { [weak self] in
            await self?.disconnect(); self?.reconcile()
            self?.draining[recovery] = nil
        }
    }
}

@MainActor private final class DeadlineRace {
    var continuation: CheckedContinuation<Bool, Never>?
    func finish(expired: Bool) { continuation?.resume(returning: expired); continuation = nil }
}
