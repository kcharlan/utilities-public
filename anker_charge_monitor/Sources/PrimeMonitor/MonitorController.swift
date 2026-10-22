import Foundation
import Observation
import PrimeMonitorCore

@MainActor @Observable final class MonitorController {
    private(set) var snapshot: ChargerSnapshot?
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
        connectionGeneration = UUID(); backendReady = false; wantsConnection = false; connected = false; poll?.cancel(); poll = nil
        refreshing = false; refreshDeadline = nil
        let oldConnection = connection, oldRequest = request
        connection = nil; request = nil; oldConnection?.cancel(); oldRequest?.cancel()
        let previous = cleanup, backend = backend
        let draining = Task {
            await previous?.value; await backend.disconnect()
            await oldConnection?.value; await oldRequest?.value
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
        case .snapshot(let value, _):
            guard allowed, wantsConnection else { return }
            snapshot = value; tracker.replyReceived(at: now()); refreshing = false; refreshDeadline = nil
        case .alive: break // An echo or heartbeat never satisfies a status request.
        case .sessionUpdated(let session):
            guard restored, active?.session?.userID == session.userID else { break }
            active?.session = session; persistSecrets()
        case .status(let value):
            switch value {
            case .sessionEnded, .signInFailed, .verificationRequired:
                terminal = value; status = value; connected = false; poll?.cancel(); poll = nil
                refreshing = false; refreshDeadline = nil
            case .connected:
                guard allowed, wantsConnection else { break }
                didConnect()
            case .connecting, .error:
                guard allowed, wantsConnection else { break }
                connected = false; poll?.cancel(); poll = nil
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
                if let self, self.valid(expected), self.connectionGeneration == attempt, self.terminal == nil {
                    self.status = .error(self.presentationProblem ?? "Status request failed."); self.refreshing = false
                }
            }
            guard let self, self.valid(expected), self.connectionGeneration == attempt else { return }
            self.request = nil; self.updateStale()
        }
    }
    private func schedulePoll() {
        poll?.cancel(); poll = nil
        guard allowed, connected, let interval = PollPolicy.interval(panelOpen: open, closed: appState.closedInterval, asleep: asleep) else { return }
        poll = scheduler.schedule(after: interval) { [weak self] in self?.sendRequest(); self?.schedulePoll() }
    }
    private func scheduleTick() {
        tick?.cancel()
        guard running, active != nil else { tick = nil; return }
        tick = scheduler.schedule(after: 1) { [weak self] in self?.updateStale(); self?.scheduleTick() }
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
