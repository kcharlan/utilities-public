import Foundation
@preconcurrency import Security
import PrimeMonitorCore

/// Ports mqtt.py create_client/on_connect/on_message/cleanup (8a5222b).
/// Acknowledgment gates and bounded certificate refresh are app adaptations.
public actor AnkerCloudBackend: ChargerBackend {
    private nonisolated let subscriptions = EventSubscriptions()
    public nonisolated var events: AsyncStream<BackendEvent> { subscriptions.subscribe() }
    public func subscribeToEvents() -> AsyncStream<BackendEvent> { subscriptions.subscribe() }
    private let rest: AnkerRESTClient
    private let makeIdentity: @Sendable (String, String) throws -> TLSIdentity
    private let makeLink: @Sendable () -> any MQTTLink
    private let now: @Sendable () -> Date
    private let sleep: @Sendable (TimeInterval) async -> Void
    private var context = UUID()
    private var authenticationContext = UUID()
    private var authenticationSequence: UInt64 = 0
    private var forwarding: Task<Void, Never>?
    private var recovery: Task<Void, Error>?
    private var draining: Task<Void, Never>?
    private var attemptID = UUID()
    private var reader: Task<Void, Never>?
    private var deadline: Task<Void, Never>?
    private var keepalive: Task<Void, Never>?
    private var identity: TLSIdentity?
    private var link: (any MQTTLink)?
    private var inbox: MQTTInbox?
    private var info: MQTTInfo?
    private var charger: ChargerInfo?
    private var connected = false
    private var pingSentAt: Date?
    private var cleanup: (id: UUID, task: Task<Void, Never>)?
    /// Links in graceful cleanup; an abort closes them at once rather than waiting
    /// for their bounded DISCONNECT.
    private var gracefulCloses: [UUID: any MQTTLink] = [:]
    /// Receive order for port-command freshness: one epoch per connection attempt
    /// and one sequence step per received publish, monotonic across connections.
    private var epochCount: UInt64 = 0
    private var epoch: ConnectionEpoch?
    private var receiveSequence: UInt64 = 0
    private var lastInbound = Date.distantPast
    private var lastOutbound = Date.distantPast

    init(rest: AnkerRESTClient, makeIdentity: @escaping @Sendable (String, String) throws -> TLSIdentity = { try TLSIdentity(certificatePEM: $0, privateKeyPEM: $1) }, makeLink: @escaping @Sendable () -> any MQTTLink,
         now: @escaping @Sendable () -> Date, sleep: @escaping @Sendable (TimeInterval) async -> Void) {
        self.rest = rest; self.makeLink = makeLink; self.now = now; self.sleep = sleep
        self.makeIdentity = makeIdentity
    }
    private func emit(_ event: BackendEvent) { subscriptions.send(event) }
    public static func live() -> AnkerCloudBackend {
        let sleep: @Sendable (TimeInterval) async -> Void = { try? await Task.sleep(for: .seconds($0)) }
        return AnkerCloudBackend(rest: AnkerRESTClient(transport: URLSessionTransport(), timeZone: .current, now: { Date() }, sleep: sleep, random: { Int.random(in: $0) }), makeLink: { NWMQTTLink() }, now: { Date() }, sleep: sleep)
    }
    private func replaceAuthentication() -> UUID {
        authenticationSequence += 1
        authenticationContext = UUID()
        forwarding?.cancel()
        forwarding = nil
        return authenticationContext
    }
    private func establishAuthentication(_ expected: UUID, updates: AsyncStream<AccountSession>) {
        guard authenticationContext == expected else { return }
        forwarding = Task { [weak self] in
            for await session in updates {
                guard !Task.isCancelled else { return }
                await self?.forward(session, context: expected)
            }
        }
    }
    private func forward(_ session: AccountSession, context expected: UUID) {
        guard authenticationContext == expected else { return }
        emit(.sessionUpdated(session))
    }
    public func signIn(_ credentials: AnkerCredentials) async throws -> AccountSession {
        let expected = replaceAuthentication()
        let sequence = authenticationSequence
        let connectionContext = await stopMQTT()
        guard authenticationContext == expected, context == connectionContext else { throw CancellationError() }
        let prepared = try await rest.prepareAuthentication(credentials: credentials, restored: nil, sequence: sequence)
        establishAuthentication(expected, updates: prepared.updates)
        guard authenticationContext == expected, context == connectionContext else { throw CancellationError() }
        do {
            let session = try await rest.login(prepared: prepared)
            guard authenticationContext == expected else { throw CancellationError() }
            return session
        } catch {
            if authenticationContext == expected, context == connectionContext, !Task.isCancelled,
               let status = Self.terminalStatus(error) { emit(.status(status)) }
            throw error
        }
    }
    public func restore(_ session: AccountSession, credentials: AnkerCredentials) async {
        let expected = replaceAuthentication()
        let sequence = authenticationSequence
        let connectionContext = await stopMQTT()
        guard authenticationContext == expected, context == connectionContext else { return }
        guard let prepared = try? await rest.prepareAuthentication(credentials: credentials, restored: session, sequence: sequence) else { return }
        establishAuthentication(expected, updates: prepared.updates)
        guard authenticationContext == expected, context == connectionContext else { return }
    }
    public func listChargers() async throws -> [ChargerInfo] {
        let expected = authenticationContext, connectionContext = context
        do {
            let chargers = try await rest.listChargers()
            guard authenticationContext == expected, context == connectionContext else { throw CancellationError() }
            return chargers
        } catch {
            if authenticationContext == expected, context == connectionContext, !Task.isCancelled,
               let status = Self.terminalStatus(error) { emit(.status(status)) }
            throw error
        }
    }

    public func connect(to charger: ChargerInfo) async throws {
        let expected = await stopMQTT()
        try check(expected)
        self.charger = charger
        let task = Task { try await self.recover(context: expected, fetch: true) }
        recovery = task
        try await withTaskCancellationHandler { try await task.value } onCancel: { task.cancel(); Task { await self.cancelConnection(expected) } }
    }
    private func check(_ expected: UUID) throws {
        try Task.checkCancellation()
        guard context == expected else { throw CancellationError() }
    }
    private func cancelConnection(_ expected: UUID) async {
        guard context == expected else { return }; _ = await stopMQTT()
    }
    private func recover(context expected: UUID, fetch: Bool, delayBeforeFirst: Bool = false) async throws {
        var backoff = BackoffPolicy(), refreshed = false, fetch = fetch
        if delayBeforeFirst { await sleep(backoff.nextDelay()); try check(expected) }
        while true {
            try check(expected)
            emit(.status(.connecting))
            do {
                if fetch {
                    let fetched = try await rest.mqttInfo(); try check(expected); info = fetched; fetch = false
                }
                try await attempt(expected)
                try check(expected)
                connected = true; emit(.status(.connected))
                startKeepalive(expected)
                return
            } catch {
                guard context == expected, !Task.isCancelled else { throw CancellationError() }
                await cleanupAttempt()
                try check(expected)
                if let status = Self.terminalStatus(error) {
                    emit(.status(status))
                    throw error
                }
                emit(.status(.error("MQTT connection failed")))
                // Dispose old identity before refresh and before backoff.
                if info == nil {
                    // A failed initial REST fetch is not a certificate refresh.
                    fetch = true
                } else if !refreshed, Self.needsRefresh(error) {
                    refreshed = true
                    do { let fetched = try await rest.mqttInfo(); try check(expected); info = fetched }
                    catch {
                        try check(expected)
                        if let status = Self.terminalStatus(error) { emit(.status(status)); throw error }
                    }
                }
                await sleep(backoff.nextDelay()); try check(expected)
            }
        }
    }
    private static func terminalStatus(_ error: Error) -> ConnectionStatus? {
        switch error as? AnkerError {
        case .verificationRequired: .verificationRequired
        case .authorization, .kickedOut, .http(401), .http(403): .sessionEnded
        case .invalidCredentials: .signInFailed("Invalid credentials")
        case .retryExceeded: .signInFailed("Sign-in retry limit exceeded")
        default: nil
        }
    }
    private static func needsRefresh(_ error: Error) -> Bool {
        if let error = error as? MQTTConnectionError {
            switch error { case .subscription, .invalidCertificate: return false; default: return true }
        }
        return true
    }
    private func attempt(_ expected: UUID) async throws {
        guard let info, let charger else { throw MQTTConnectionError.closed }
        let identity = try makeIdentity(info.certificatePEM, info.privateKeyPEM)
        self.identity = identity
        let body = info.rootCAPEM.components(separatedBy: .newlines).filter { !$0.hasPrefix("-----") }.joined()
        guard let data = Data(base64Encoded: body), let root = SecCertificateCreateWithData(nil, data as CFData) else { throw MQTTConnectionError.invalidCertificate }
        attemptID = UUID(); let attempt = attemptID
        epochCount += 1; epoch = ConnectionEpoch(epochCount)
        let link = makeLink(), inbox = MQTTInbox(); self.link = link; self.inbox = inbox
        reader = Task { [weak self] in
            do { for try await packet in link.packets { await inbox.push(packet) }; await inbox.fail(MQTTConnectionError.closed) }
            catch { await inbox.fail(error) }
            await self?.dropped(expected, attempt: attempt)
        }
        deadline = Task { [sleep] in
            await sleep(15)
            guard !Task.isCancelled else { return }
            await inbox.fail(MQTTConnectionError.timeout); await link.close()
        }
        try await link.open(host: info.endpoint, port: 8883, identity: identity.identity, rootCA: root)
        try check(expected)
        try await link.send(.connect(clientID: info.thingName + String(format: "_%05d", Int.random(in: 0..<99999)), keepAlive: 60))
        guard case .connack(returnCode: 0) = try await nextControl(inbox, context: expected) else { throw MQTTConnectionError.refused }
        for (index, topic) in AnkerTopics.subscriptions(info: info, charger: charger).enumerated() {
            try check(expected)
            if index > 0 { await sleep(0.1); try check(expected) }
            let id = UInt16(index + 1)
            try await link.send(.subscribe(id: id, topic: topic))
            guard case .suback(id: id, code: 0) = try await nextControl(inbox, context: expected) else { throw MQTTConnectionError.subscription }
        }
        try check(expected); deadline?.cancel(); deadline = nil
        // The stream reader remains the inbox's producer; drain its buffered packets.
        keepalive = nil
        draining = Task { [weak self] in
            do { while !Task.isCancelled { let packet = try await inbox.next(); await self?.received(packet, context: expected, attempt: attempt) } }
            catch { await self?.dropped(expected, attempt: attempt) }
        }
    }
    private func nextControl(_ inbox: MQTTInbox, context expected: UUID) async throws -> MQTTPacket {
        let attempt = attemptID
        while true {
            let packet = try await inbox.next()
            try check(expected)
            guard attemptID == attempt else { throw CancellationError() }
            if case .publish = packet { received(packet, context: expected, attempt: attempt) }
            else { return packet }
        }
    }
    private func received(_ packet: MQTTPacket, context expected: UUID, attempt: UUID) {
        guard context == expected, attemptID == attempt, link != nil else { return }
        lastInbound = now()
        if packet == .pingresp { pingSentAt = nil }
        guard case let .publish(_, payload) = packet, let epoch else { return }
        // Take the receive position before decoding or queuing to subscribers.
        receiveSequence += 1
        let mark = ReceiveMark(connection: epoch, sequence: receiveSequence)
        let date = now(); emit(.alive(date))
        if let bytes = MQTTEnvelope.frame(fromMessage: payload), let frame = try? HexFrame.parse(bytes),
           let snapshot = PortDecoder.snapshot(from: frame, receivedAt: date) { emit(.snapshot(snapshot, mark)) }
    }
    private func startKeepalive(_ expected: UUID) {
        lastInbound = now(); lastOutbound = lastInbound
        keepalive = Task { [weak self, sleep] in
            while !Task.isCancelled {
                guard let delay = await self?.nextPingDelay(expected) else { return }
                await sleep(delay)
                guard !Task.isCancelled else { return }
                await self?.ping(expected)
            }
        }
    }
    private func nextPingDelay(_ expected: UUID) -> TimeInterval? {
        guard context == expected, connected else { return nil }
        let reference = pingSentAt ?? min(lastInbound, lastOutbound)
        return max(0, 60 - now().timeIntervalSince(reference))
    }
    private func ping(_ expected: UUID) async {
        guard context == expected, connected, let link else { return }
        guard nextPingDelay(expected) == 0 else { return }
        if pingSentAt != nil { await link.close(); return }
        pingSentAt = now(); lastOutbound = now(); lastInbound = lastOutbound
        do { try await link.send(.pingreq) } catch { await link.close() }
    }
    private func dropped(_ expected: UUID, attempt: UUID) async {
        guard context == expected, attemptID == attempt, connected else { return }
        connected = false; emit(.status(.error("MQTT connection lost")))
        await cleanupAttempt()
        guard context == expected else { return }
        recovery = Task {
            try await self.recover(context: expected, fetch: false, delayBeforeFirst: true)
        }
    }
    public func requestSnapshot() async throws {
        guard connected, let link, let info, let charger else { throw MQTTConnectionError.closed }
        let expected = context
        try await link.send(.publish(topic: AnkerTopics.publish(info: info, charger: charger), payload: MQTTEnvelope.statusRequest(info: info, charger: charger, timestamp: UInt32(clamping: Int64(now().timeIntervalSince1970)))))
        try check(expected)
        lastOutbound = now()
    }
    /// Published as `requestSnapshot` publishes (upstream `mqtt_device.py`
    /// `_send_mqtt_command` without its wait-for-state). The fence is read here, at
    /// write completion, on the connection the command was written to.
    public func setPortSwitch(_ target: PortSwitch, on: Bool) async throws -> PortCommandReceipt {
        guard connected, let link, let info, let charger, let epoch else { throw MQTTConnectionError.closed }
        let expected = context, attempt = attemptID
        let timestamp = UInt32(clamping: Int64(now().timeIntervalSince1970))
        let frame = PortSwitchCommand.frame(target: target, on: on, timestamp: timestamp)
        try await link.send(.publish(topic: AnkerTopics.publish(info: info, charger: charger),
                                     payload: MQTTEnvelope.command(info: info, charger: charger, frame: frame, timestamp: timestamp)))
        try check(expected)
        // A replacement connection in the same context must not adopt this write.
        guard attemptID == attempt, connected else { throw MQTTConnectionError.closed }
        lastOutbound = now()
        return PortCommandReceipt(fence: ReceiveMark(connection: epoch, sequence: receiveSequence))
    }
    public func commandFence() throws -> PortCommandReceipt {
        guard connected, link != nil, let epoch else { throw MQTTConnectionError.closed }
        return PortCommandReceipt(fence: ReceiveMark(connection: epoch, sequence: receiveSequence))
    }
    /// Revokes the context before its first await, then closes the current link
    /// without DISCONNECT. Closing resumes its pending sends with an error; links
    /// still in graceful cleanup are closed at once too. Authentication is kept.
    public func abortCommands() async {
        _ = await stopMQTT(abortive: true)
    }
    private func cleanupAttempt(abortive: Bool = false) async {
        let wasConnected = connected && !abortive
        let oldDeadline = deadline, oldKeepalive = keepalive
        attemptID = UUID(); draining?.cancel(); draining = nil; epoch = nil
        connected = false; deadline?.cancel(); deadline = nil; keepalive?.cancel(); keepalive = nil
        reader?.cancel(); reader = nil
        let oldLink = link, oldIdentity = identity, oldInbox = inbox
        link = nil; identity = nil; inbox = nil; pingSentAt = nil
        let previous = cleanup?.task, id = UUID()
        let expedite = abortive ? Array(gracefulCloses.values) : []
        if wasConnected, let oldLink { gracefulCloses[id] = oldLink }
        // Replacement callers must also await cleanup already in progress. This
        // prevents an actor reentry from opening a new link before the old closes.
        let task = Task {
            for link in expedite { await link.close() }
            await previous?.value
            await oldInbox?.fail(CancellationError())
            if wasConnected, let oldLink {
                // Bound graceful DISCONNECT so a blocked write cannot hold quit.
                let timeout = Task { [sleep] in
                    await sleep(1)
                    if !Task.isCancelled { await oldLink.close() }
                }
                try? await oldLink.send(.disconnect)
                timeout.cancel()
                await oldLink.close()
                await timeout.value
            } else {
                await oldLink?.close()
            }
            await oldDeadline?.value
            await oldKeepalive?.value
            // Keep the identity alive until link close and its timers finish.
            // ARC then releases the connection's in-memory Security objects.
            withExtendedLifetime(oldIdentity) {}
            self.finishedCleanup(id)
        }
        cleanup = (id, task)
        await task.value
    }
    private func finishedCleanup(_ id: UUID) {
        gracefulCloses[id] = nil
        if cleanup?.id == id { cleanup = nil }
    }

    private func stopMQTT(abortive: Bool = false) async -> UUID {
        context = UUID(); let expected = context; recovery?.cancel(); recovery = nil
        info = nil; charger = nil
        await cleanupAttempt(abortive: abortive)
        return expected
    }
    public func disconnect() async {
        let expected = replaceAuthentication()
        let sequence = authenticationSequence
        await rest.invalidateAuthentication(sequence: sequence)
        guard authenticationContext == expected else { return }
        let connectionContext = await stopMQTT()
        guard authenticationContext == expected, context == connectionContext else { return }
        // Explicit disconnect is a lifecycle action, not an authentication failure.
        // The controller owns sleep/network/sign-out presentation.
    }
}

/// Lazy independent queues: no unused compatibility stream accumulates events.
/// The synchronous getter and actor subscription share this one implementation.
private final class EventSubscriptions: @unchecked Sendable {
    private let lock = NSLock()
    private var outputs: [UUID: AsyncStream<BackendEvent>.Continuation] = [:]
    func subscribe() -> AsyncStream<BackendEvent> {
        let id = UUID(), (stream, output) = AsyncStream<BackendEvent>.makeStream()
        lock.withLock { outputs[id] = output }
        output.onTermination = { [weak self] _ in self?.remove(id) }
        return stream
    }
    private func remove(_ id: UUID) { _ = lock.withLock { outputs.removeValue(forKey: id) } }
    func send(_ event: BackendEvent) {
        let current = lock.withLock { Array(outputs.values) }
        for output in current { output.yield(event) }
    }
}
