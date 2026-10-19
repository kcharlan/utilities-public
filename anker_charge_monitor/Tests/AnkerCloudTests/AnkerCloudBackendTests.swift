import Foundation
@preconcurrency import Security
import Testing
import PrimeMonitorCore
@testable import AnkerCloud

actor TestMQTTLink: MQTTLink {
    nonisolated let packets: AsyncThrowingStream<MQTTPacket, Error>
    nonisolated let input: AsyncThrowingStream<MQTTPacket, Error>.Continuation
    var sent: [MQTTPacket] = []
    var closed = false
    var automatic = true
    var connack: UInt8 = 0
    var suback: UInt8 = 0
    var stallOpen = false
    var interleave = false
    func interleaveMessages() { interleave = true }
    var openWait: CheckedContinuation<Void, Error>?
    var blockClose = false
    var closeStarted = false
    var closeWait: CheckedContinuation<Void, Never>?
    func holdClose() { blockClose = true }
    func releaseClose() { closeWait?.resume(); closeWait = nil }
    func configure(automatic: Bool = true, connack: UInt8 = 0, suback: UInt8 = 0, stallOpen: Bool = false) { self.automatic = automatic; self.connack = connack; self.suback = suback; self.stallOpen = stallOpen }
    init() { (packets, input) = AsyncThrowingStream.makeStream() }
    nonisolated func open(host: String, port: UInt16, identity: SecIdentity, rootCA: SecCertificate) async throws {
        #expect(host == "synthetic.invalid"); #expect(port == 8883)
        try await waitForOpen()
    }
    func waitForOpen() async throws {
        if stallOpen { try await withCheckedThrowingContinuation { openWait = $0 } }
    }
    func send(_ packet: MQTTPacket) async throws {
        sent.append(packet)
        if automatic {
            switch packet {
            case .connect: input.yield(.connack(returnCode: connack))
            case let .subscribe(id, topic):
                if interleave { input.yield(.publish(topic: topic, payload: Data())) }
                input.yield(.suback(id: id, code: suback))
            default: break
            }
        }
    }
    func close() async {
        closeStarted = true
        if blockClose { blockClose = false; await withCheckedContinuation { closeWait = $0 } }
        closed = true; openWait?.resume(throwing: MQTTConnectionError.closed); openWait = nil; input.finish()
    }
}

private actor MQTTTransport: HTTPTransport {
    var calls = 0
    var failures = 0
    func failNextRequest() { failures = 1 }
    let pem: (certificate: String, key: String)
    init(_ pem: (certificate: String, key: String)) { self.pem = pem }
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        calls += 1
        if failures > 0 { failures -= 1; throw URLError(.notConnectedToInternet) }
        let data: [String: Any] = ["user_id":"synthetic-user", "app_name":"anker_power", "thing_name":"synthetic-thing", "certificate_id":"synthetic-cert", "certificate_pem":pem.certificate, "private_key":pem.key, "aws_root_ca1_pem":pem.certificate, "endpoint_addr":"synthetic.invalid"]
        return (try JSONSerialization.data(withJSONObject: ["code":0,"data":data]), HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!)
    }
}
private let testCharger = ChargerInfo(serial: "synthetic-charger", model: "A2345", alias: "", name: "")
private let testSession = AccountSession(authToken: "synthetic-token", userID: "synthetic-user", expiresAt: .distantFuture, nickname: "")
private let testCredentials = AnkerCredentials(email: "synthetic@example.invalid", password: "synthetic-password", country: "US")
private final class IdentityTracker: @unchecked Sendable {
    private final class Reference { weak var value: TLSIdentity?; init(_ value: TLSIdentity) { self.value = value } }
    private let lock = NSLock()
    private var references: [Reference] = []
    func make(_ certificate: String, _ key: String) throws -> TLSIdentity {
        let identity = try TLSIdentity(certificatePEM: certificate, privateKeyPEM: key)
        lock.withLock { references.append(Reference(identity)) }
        return identity
    }
    var liveCount: Int { lock.withLock { references.filter { $0.value != nil }.count } }
}
@Suite(.serialized) struct AnkerCloudBackendTests {
private let identityTracker = IdentityTracker()
fileprivate func backend(_ link: TestMQTTLink, gate: SleepGate? = nil, transport: MQTTTransport? = nil, now: @escaping @Sendable () -> Date = { Date(timeIntervalSince1970: 1000) }) throws -> AnkerCloudBackend {
    let transport = try transport ?? MQTTTransport(syntheticIdentityPEM())
    let rest = AnkerRESTClient(transport: transport, timeZone: .gmt, now: { Date() }, sleep: { _ in }, random: { $0.lowerBound })
    return AnkerCloudBackend(rest: rest, makeIdentity: identityTracker.make, makeLink: { link }, now: now, sleep: { seconds in if let gate { await gate.sleep(seconds) } else { try? await Task.sleep(for: .seconds(seconds)) } })
}
@Test func connectSubscribesEachTopicAndRequestPublishes() async throws {
    let link = TestMQTTLink(), cloud = try backend(link)
    await cloud.restore(testSession, credentials: testCredentials)
    try await cloud.connect(to: testCharger)
    #expect(identityTracker.liveCount == 1)
    try await cloud.requestSnapshot()
    let sent = await link.sent
    #expect(sent.count == 4)
    guard case let .connect(clientID, keepAlive) = sent[0] else { Issue.record("missing CONNECT"); return }
    #expect(clientID.hasPrefix("synthetic-thing_")); #expect(keepAlive == 60)
    #expect(sent[1] == .subscribe(id: 1, topic: "cmd/anker_power/A2345/synthetic-charger/#"))
    #expect(sent[2] == .subscribe(id: 2, topic: "dt/anker_power/A2345/synthetic-charger/#"))
    guard case let .publish(topic, payload) = sent[3] else { Issue.record("missing request"); return }
    #expect(topic == "cmd/anker_power/A2345/synthetic-charger/req")
    #expect(MQTTEnvelope.frame(fromMessage: payload) == StatusRequest.frame(timestamp: 1000))
    await cloud.disconnect()
    #expect(await link.closed)
    #expect(await link.sent.last == .disconnect)
    #expect(identityTracker.liveCount == 0)
}
}

private actor EventLog {
    var statuses: [ConnectionStatus] = []
    var alive = 0, snapshots = 0, sessions = 0
    func append(_ event: BackendEvent) {
        switch event {
        case let .status(status): statuses.append(status)
        case .alive: alive += 1
        case .snapshot: snapshots += 1
        case .sessionUpdated: sessions += 1
        }
    }
}
private actor SleepGate {
    var delays: [Double] = []
    var waits: [Double: [UUID: CheckedContinuation<Void, Never>]] = [:]
    func sleep(_ delay: Double) async {
        delays.append(delay)
        if delay == 0.1 { return }
        let id = UUID()
        await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                if Task.isCancelled { continuation.resume() } else { waits[delay, default: [:]][id] = continuation }
            }
        } onCancel: { Task { await self.cancel(delay, id) } }
    }
    func cancel(_ delay: Double, _ id: UUID) { waits[delay]?.removeValue(forKey: id)?.resume() }
    func advance(_ delay: Double) { let pending = waits.removeValue(forKey: delay) ?? [:]; for c in pending.values { c.resume() } }
    func pending(_ delay: Double) -> Int { waits[delay]?.count ?? 0 }
}
private func eventually(_ predicate: @escaping () async -> Bool) async throws {
    for _ in 0..<2000 { if await predicate() { return }; try await Task.sleep(for: .milliseconds(1)) }
    Issue.record("condition did not become true"); throw MQTTConnectionError.timeout
}

extension AnkerCloudBackendTests {
@Test func publishDuringSubscribeDoesNotRejectAcknowledgment() async throws {
    let link = TestMQTTLink(), gate = SleepGate(), log = EventLog()
    await link.interleaveMessages()
    let cloud = try backend(link, gate: gate)
    let events = Task { for await event in cloud.events { await log.append(event) } }
    defer { events.cancel() }
    await cloud.restore(testSession, credentials: testCredentials)
    let connecting = Task { try await cloud.connect(to: testCharger) }
    do { try await eventually { await log.statuses.contains(.connected) } }
    catch { await cloud.disconnect(); _ = try? await connecting.value; throw error }
    try await connecting.value
    #expect(await log.alive == 2)
    await cloud.disconnect()
}

@Test func connectedWaitsForEveryAcknowledgment() async throws {
    let link = TestMQTTLink(), cloud = try backend(link), log = EventLog()
    await link.configure(automatic: false)
    let events = Task { for await event in cloud.events { await log.append(event) } }
    defer { events.cancel() }
    await cloud.restore(testSession, credentials: testCredentials)
    let connecting = Task { try await cloud.connect(to: testCharger) }
    try await eventually { await link.sent.count == 1 }
    #expect(await log.statuses == [.connecting])
    link.input.yield(.connack(returnCode: 0))
    try await eventually { await link.sent.count == 2 }
    #expect(await log.statuses == [.connecting])
    link.input.yield(.suback(id: 1, code: 0))
    try await eventually { await link.sent.count == 3 }
    #expect(await log.statuses == [.connecting])
    link.input.yield(.suback(id: 2, code: 0))
    try await connecting.value
    try await eventually { await log.statuses.last == .connected }
    await cloud.disconnect()
}

@Test func failedSubackReportsErrorAndDisconnectStopsRecovery() async throws {
    let link = TestMQTTLink(), gate = SleepGate(), cloud = try backend(link, gate: gate), log = EventLog()
    await link.configure(suback: 0x80)
    let events = Task { for await event in cloud.events { await log.append(event) } }
    defer { events.cancel() }
    await cloud.restore(testSession, credentials: testCredentials)
    let connecting = Task { try await cloud.connect(to: testCharger) }
    try await eventually { await gate.pending(1) == 1 }
    #expect(await link.closed)
    #expect(identityTracker.liveCount == 0)
    #expect(await log.statuses.contains { if case .error = $0 { true } else { false } })
    #expect(await log.statuses.contains(.connected) == false)
    await cloud.disconnect()
    do { try await connecting.value; Issue.record("cancelled connect succeeded") } catch is CancellationError { }
    #expect(await gate.pending(15) == 0)
}

@Test(arguments: ["open", "connack", "suback"])
func connectTimesOut(stage: String) async throws {
    let link = TestMQTTLink(), gate = SleepGate(), transport = MQTTTransport(try syntheticIdentityPEM())
    let cloud = try backend(link, gate: gate, transport: transport), log = EventLog()
    let events = Task { for await event in cloud.events { await log.append(event) } }
    defer { events.cancel() }
    await link.configure(automatic: false, stallOpen: stage == "open")
    await cloud.restore(testSession, credentials: testCredentials)
    let connecting = Task { try await cloud.connect(to: testCharger) }
    try await eventually { await gate.pending(15) == 1 }
    if stage != "open" { try await eventually { await link.sent.count == 1 } }
    if stage == "suback" {
        link.input.yield(.connack(returnCode: 0))
        try await eventually { await link.sent.count == 2 }
    }
    await gate.advance(15)
    try await eventually { await gate.pending(1) == 1 }
    #expect(await link.closed)
    #expect(await transport.calls == 2)
    #expect(await gate.delays.filter { $0 == 15 } == [15])
    #expect(await log.statuses.contains { if case .error = $0 { true } else { false } })
    await cloud.disconnect()
    do { try await connecting.value; Issue.record("timed out connect succeeded") } catch is CancellationError { }
    #expect(identityTracker.liveCount == 0)
}

@Test func echoBadFrameThenReplyPreservesSession() async throws {
    let link = TestMQTTLink(), cloud = try backend(link), log = EventLog()
    let events = Task { for await event in cloud.events { await log.append(event) } }
    defer { events.cancel() }
    await cloud.restore(testSession, credentials: testCredentials)
    try await cloud.connect(to: testCharger)
    try await cloud.requestSnapshot()
    guard case let .publish(topic, echo) = await link.sent.last else { Issue.record("request absent"); return }
    link.input.yield(.publish(topic: topic, payload: echo))
    try await eventually { await log.alive == 1 }
    #expect(await log.snapshots == 0)
    link.input.yield(.publish(topic: topic, payload: Data("broken".utf8)))
    let fixture = try String(contentsOf: Bundle.module.url(forResource: "synthetic_0a00_frames", withExtension: "txt", subdirectory: "Fixtures")!, encoding: .utf8)
    let line = try #require(fixture.split(separator: "\n").first { !$0.hasPrefix("#") })
    let chars = Array(line)
    let bytes = stride(from: 0, to: chars.count, by: 2).compactMap { UInt8(String(chars[$0...($0 + 1)]), radix: 16) }
    let nested = try JSONSerialization.data(withJSONObject: ["data": Data(bytes).base64EncodedString()])
    let payload = try JSONSerialization.data(withJSONObject: ["payload": String(decoding: nested, as: UTF8.self)])
    link.input.yield(.publish(topic: "dt/synthetic/param_info", payload: payload))
    try await eventually { await log.snapshots == 1 }
    #expect(await log.alive == 3)
    #expect(await log.snapshots == 1)
    #expect(await log.statuses.last == .connected)
    await cloud.disconnect()
}

@Test func missingPingrespDropsLink() async throws {
    let link = TestMQTTLink(), gate = SleepGate(), time = MQTTTestTime()
    let cloud = try backend(link, gate: gate, now: { time.now() })
    await cloud.restore(testSession, credentials: testCredentials)
    try await cloud.connect(to: testCharger)
    try await eventually { await gate.pending(60) == 1 }
    time.advance(60); await gate.advance(60)
    try await eventually { await link.sent.contains(.pingreq) }
    try await eventually { await gate.pending(60) == 1 }
    time.advance(60); await gate.advance(60)
    try await eventually { await link.closed }
    await cloud.disconnect()
}
}

private final class MQTTTestTime: @unchecked Sendable {
    private let lock = NSLock()
    private var date = Date(timeIntervalSince1970: 1000)
    func now() -> Date { lock.withLock { date } }
    func advance(_ seconds: Double) { lock.withLock { date += seconds } }
}

extension AnkerCloudBackendTests {
@Test func trafficDefersPingAndPingrespKeepsConnection() async throws {
    let link = TestMQTTLink(), gate = SleepGate(), time = MQTTTestTime(), log = EventLog()
    let cloud = try backend(link, gate: gate, now: { time.now() })
    let events = Task { for await event in cloud.events { await log.append(event) } }
    defer { events.cancel() }
    await cloud.restore(testSession, credentials: testCredentials)
    try await cloud.connect(to: testCharger)
    try await eventually { await gate.pending(60) == 1 }
    time.advance(30)
    try await cloud.requestSnapshot()
    link.input.yield(.publish(topic: "dt/synthetic", payload: Data()))
    try await eventually { await log.alive == 1 }
    time.advance(30); await gate.advance(60)
    try await eventually { await gate.pending(30) == 1 }
    #expect(await link.sent.contains(.pingreq) == false)
    time.advance(30); await gate.advance(30)
    try await eventually { await link.sent.contains(.pingreq) }
    link.input.yield(.pingresp)
    link.input.yield(.publish(topic: "dt/synthetic", payload: Data()))
    try await eventually { await log.alive == 2 }
    try await eventually { await gate.pending(60) == 1 }
    time.advance(60); await gate.advance(60)
    try await eventually { await link.sent.filter { $0 == .pingreq }.count == 2 }
    #expect(await link.closed == false)
    await cloud.disconnect()
}
}

private final class LinkFactory: @unchecked Sendable {
    let lock = NSLock()
    let links: [TestMQTTLink]
    var index = 0
    init(_ links: [TestMQTTLink]) { self.links = links }
    func make() -> any MQTTLink { lock.withLock { let link = links[min(index, links.count - 1)]; index += 1; return link } }
}
extension AnkerCloudBackendTests {
@Test func initialMetadataFailureDoesNotConsumeCertificateRefresh() async throws {
    let links = [TestMQTTLink(), TestMQTTLink()], gate = SleepGate()
    await links[0].configure(connack: 5)
    let transport = MQTTTransport(try syntheticIdentityPEM()), factory = LinkFactory(links)
    await transport.failNextRequest()
    let rest = AnkerRESTClient(transport: transport, timeZone: .gmt, now: { Date() }, sleep: { _ in }, random: { $0.lowerBound })
    let cloud = AnkerCloudBackend(rest: rest, makeIdentity: identityTracker.make, makeLink: { factory.make() }, now: { Date() }, sleep: { await gate.sleep($0) })
    await cloud.restore(testSession, credentials: testCredentials)
    let connecting = Task { try await cloud.connect(to: testCharger) }
    try await eventually { await gate.pending(1) == 1 }
    await gate.advance(1)
    try await eventually { await gate.pending(2) == 1 }
    #expect(await transport.calls == 3)
    await gate.advance(2)
    try await connecting.value
    await cloud.disconnect()
}

@Test func obsoleteRestoreCannotReplaceNewerAccountAfterSlowClose() async throws {
    let link = TestMQTTLink(), transport = MQTTTransport(try syntheticIdentityPEM())
    let rest = AnkerRESTClient(transport: transport, timeZone: .gmt, now: { Date() }, sleep: { _ in }, random: { $0.lowerBound })
    let cloud = AnkerCloudBackend(rest: rest, makeIdentity: identityTracker.make, makeLink: { link }, now: { Date() }, sleep: { try? await Task.sleep(for: .seconds($0)) })
    await cloud.restore(testSession, credentials: testCredentials)
    try await cloud.connect(to: testCharger)
    await link.holdClose()
    let old = Task { await cloud.restore(testSession, credentials: testCredentials) }
    try await eventually { await link.closeStarted }
    #expect(identityTracker.liveCount == 1, "Keep the old identity alive through link close")
    let newer = AccountSession(authToken: "synthetic-newer", userID: "synthetic-newer", expiresAt: .distantFuture, nickname: "")
    let replacement = Task { await cloud.restore(newer, credentials: testCredentials) }
    // Let both replacement calls contend while the old link owns its close gate.
    for _ in 0..<20 { await Task.yield() }
    await link.releaseClose()
    await old.value
    await replacement.value
    #expect(await rest.session == newer)
    await cloud.disconnect()
    #expect(identityTracker.liveCount == 0)
}

@Test func refusedConnackRefetchesOnceAcrossThreeFailuresThenSuccess() async throws {
    let links = (0..<4).map { _ in TestMQTTLink() }, gate = SleepGate()
    for link in links.prefix(3) { await link.configure(connack: 5) }
    let transport = MQTTTransport(try syntheticIdentityPEM()), factory = LinkFactory(links)
    let rest = AnkerRESTClient(transport: transport, timeZone: .gmt, now: { Date() }, sleep: { _ in }, random: { $0.lowerBound })
    let cloud = AnkerCloudBackend(rest: rest, makeIdentity: identityTracker.make, makeLink: { factory.make() }, now: { Date() }, sleep: { await gate.sleep($0) })
    await cloud.restore(testSession, credentials: testCredentials)
    let connecting = Task { try await cloud.connect(to: testCharger) }
    for delay in [1.0, 2, 4] {
        try await eventually { await gate.pending(delay) == 1 }
        #expect(await links[Int(log2(delay))].closed)
        #expect(identityTracker.liveCount == 0)
        await gate.advance(delay)
    }
    try await connecting.value
    #expect(await transport.calls == 2)
    #expect(await gate.delays.filter { [1.0,2,4,8].contains($0) } == [1,2,4])
    await cloud.disconnect()
    #expect(await links[3].closed)
    #expect(identityTracker.liveCount == 0)
}

@Test func dropReconnectsWithoutRefetch() async throws {
    let links = [TestMQTTLink(), TestMQTTLink()], gate = SleepGate()
    let transport = MQTTTransport(try syntheticIdentityPEM()), factory = LinkFactory(links)
    let rest = AnkerRESTClient(transport: transport, timeZone: .gmt, now: { Date() }, sleep: { _ in }, random: { $0.lowerBound })
    let cloud = AnkerCloudBackend(rest: rest, makeIdentity: identityTracker.make, makeLink: { factory.make() }, now: { Date() }, sleep: { await gate.sleep($0) })
    await cloud.restore(testSession, credentials: testCredentials)
    try await cloud.connect(to: testCharger)
    links[0].input.finish()
    try await eventually { await gate.pending(1) == 1 }
    await gate.advance(1)
    try await eventually { await links[1].sent.count == 3 }
    #expect(await transport.calls == 1)
    await cloud.disconnect()
}

@Test func laterDropBackoffContinuesAfterFirstFailedReconnect() async throws {
    let links = [TestMQTTLink(), TestMQTTLink(), TestMQTTLink()], gate = SleepGate()
    await links[1].configure(connack: 5)
    let transport = MQTTTransport(try syntheticIdentityPEM()), factory = LinkFactory(links)
    let rest = AnkerRESTClient(transport: transport, timeZone: .gmt, now: { Date() }, sleep: { _ in }, random: { $0.lowerBound })
    let cloud = AnkerCloudBackend(rest: rest, makeIdentity: identityTracker.make, makeLink: { factory.make() }, now: { Date() }, sleep: { await gate.sleep($0) })
    await cloud.restore(testSession, credentials: testCredentials)
    try await cloud.connect(to: testCharger)
    links[0].input.finish()
    try await eventually { await gate.pending(1) == 1 }
    await gate.advance(1)
    do { try await eventually { await gate.pending(2) == 1 } }
    catch { await cloud.disconnect(); throw error }
    await gate.advance(2)
    try await eventually { await links[2].sent.count == 3 }
    #expect(await gate.delays.filter { [1.0,2,4].contains($0) } == [1,2])
    #expect(await transport.calls == 2)
    await cloud.disconnect()
}

@Test func sessionUpdatesArriveWithoutMQTTConnection() async throws {
    let transport = MQTTLoginTransport()
    let rest = AnkerRESTClient(transport: transport, timeZone: .gmt, now: { Date(timeIntervalSince1970: 1000) }, sleep: { _ in }, random: { $0.lowerBound })
    let cloud = AnkerCloudBackend(rest: rest, makeIdentity: identityTracker.make, makeLink: { TestMQTTLink() }, now: { Date() }, sleep: { _ in })
    let log = EventLog()
    let events = Task { for await event in cloud.events { await log.append(event) } }
    defer { events.cancel() }
    _ = try await cloud.signIn(testCredentials)
    try await eventually { await log.sessions == 1 }
    #expect(await log.statuses.isEmpty)
    await cloud.disconnect()
}

@Test func restoredContextForwardsLaterRefreshWithoutMQTT() async throws {
    let rest = AnkerRESTClient(transport: MQTTLoginTransport(), timeZone: .gmt, now: { Date(timeIntervalSince1970: 1000) }, sleep: { _ in }, random: { $0.lowerBound })
    let cloud = AnkerCloudBackend(rest: rest, makeIdentity: identityTracker.make, makeLink: { TestMQTTLink() }, now: { Date() }, sleep: { _ in })
    let log = EventLog()
    let events = Task { for await event in cloud.events { await log.append(event) } }
    defer { events.cancel() }
    let expired = AccountSession(authToken: "synthetic-expired", userID: "synthetic-user", expiresAt: .distantPast, nickname: "")
    await cloud.restore(expired, credentials: testCredentials)
    #expect(try await cloud.listChargers().isEmpty)
    try await eventually { await log.sessions == 1 }
    #expect(await log.statuses.isEmpty)
    await cloud.disconnect()
    _ = try await rest.login(testCredentials)
    #expect(await log.sessions == 1)
}
}
private actor MQTTLoginTransport: HTTPTransport {
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let body = request.url!.path(percentEncoded: false).hasSuffix("passport/login") ? "{\"code\":0,\"data\":{\"auth_token\":\"synthetic-token\",\"user_id\":\"synthetic-user\",\"token_expires_at\":99999}}" : "{\"code\":0,\"data\":{\"data\":[]}}"
        return (Data(body.utf8), HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!)
    }
}

@Test func tlsTrustRequiresSuppliedRootAndMatchingHostname() throws {
    func certificate(_ pem: String) throws -> SecCertificate {
        let body = pem.components(separatedBy: .newlines).filter { !$0.hasPrefix("-----") }.joined()
        let data = try #require(Data(base64Encoded: body))
        return try #require(SecCertificateCreateWithData(nil, data as CFData))
    }
    let cert = try certificate(syntheticIdentityPEM(commonName: "synthetic.invalid").certificate)
    let other = try certificate(syntheticIdentityPEM(commonName: "other.invalid").certificate)
    func trust() throws -> SecTrust {
        var trust: SecTrust?
        #expect(SecTrustCreateWithCertificates(cert, SecPolicyCreateBasicX509(), &trust) == errSecSuccess)
        let result = try #require(trust)
        SecTrustSetNetworkFetchAllowed(result, false)
        return result
    }
    #expect(try NWMQTTLink.evaluate(trust(), host: "synthetic.invalid", root: cert))
    #expect(try NWMQTTLink.evaluate(trust(), host: "wrong.invalid", root: cert) == false)
    #expect(try NWMQTTLink.evaluate(trust(), host: "synthetic.invalid", root: other) == false)
}

extension AnkerCloudBackendTests {
@Test func terminalAuthenticationStopsRecovery() async throws {
    let rest = AnkerRESTClient(transport: RejectedMQTTTransport(), timeZone: .gmt, now: { Date() }, sleep: { _ in }, random: { $0.lowerBound })
    let gate = SleepGate(), log = EventLog()
    let cloud = AnkerCloudBackend(rest: rest, makeIdentity: identityTracker.make, makeLink: { TestMQTTLink() }, now: { Date() }, sleep: { await gate.sleep($0) })
    let events = Task { for await event in cloud.events { await log.append(event) } }
    defer { events.cancel() }
    await cloud.restore(testSession, credentials: testCredentials)
    let connecting = Task { try await cloud.connect(to: testCharger) }
    do {
        try await eventually { await log.statuses.contains(.verificationRequired) }
    } catch {
        await cloud.disconnect()
        _ = try? await connecting.value
        throw error
    }
    do { try await connecting.value; Issue.record("verification rejected connect succeeded") }
    catch { #expect(error as? AnkerError == .verificationRequired) }
    #expect(await gate.pending(1) == 0)
    await cloud.disconnect()
}
}
private actor RejectedMQTTTransport: HTTPTransport {
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        (Data("{\"code\":26050,\"data\":{}}".utf8), HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!)
    }
}

private enum TerminalHTTPFailure: String, CaseIterable, Sendable {
    case unauthorized, forbidden, lockout
    var error: AnkerError {
        switch self {
        case .unauthorized: .http(401)
        case .forbidden: .http(403)
        case .lockout: .retryExceeded
        }
    }
    var status: ConnectionStatus {
        switch self {
        case .unauthorized, .forbidden: .sessionEnded
        case .lockout: .signInFailed("Sign-in retry limit exceeded")
        }
    }
}

/// Exercises the real REST client's bounded reauthentication, rather than
/// throwing a test error directly across the HTTP transport boundary.
private actor TerminalRecoveryTransport: HTTPTransport {
    let failure: TerminalHTTPFailure
    let failRefresh: Bool
    let successfulInfo: MQTTTransport
    private(set) var metadataCalls = 0
    private(set) var loginCalls = 0
    init(failure: TerminalHTTPFailure, failRefresh: Bool, successfulInfo: MQTTTransport) {
        self.failure = failure; self.failRefresh = failRefresh; self.successfulInfo = successfulInfo
    }
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let body: Data
        var status = 200
        if request.url!.path(percentEncoded: false).hasSuffix("passport/login") {
            loginCalls += 1
            body = Data("{\"code\":0,\"data\":{\"auth_token\":\"synthetic-renewed\",\"user_id\":\"synthetic-user\",\"token_expires_at\":9999999999}}".utf8)
        } else {
            metadataCalls += 1
            if failRefresh && metadataCalls == 1 { return try await successfulInfo.send(request) }
            switch failure {
            case .unauthorized: status = 401; body = Data()
            case .forbidden: status = 403; body = Data()
            case .lockout: body = Data("{\"code\":100053,\"data\":{}}".utf8)
            }
        }
        return (body, HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!)
    }
}

extension AnkerCloudBackendTests {
@Test(arguments: [false, true], TerminalHTTPFailure.allCases)
fileprivate func exhaustedAuthorizationAndLockoutStopRecovery(failRefresh: Bool, failure: TerminalHTTPFailure) async throws {
    let transport = TerminalRecoveryTransport(failure: failure, failRefresh: failRefresh, successfulInfo: MQTTTransport(try syntheticIdentityPEM()))
    let rest = AnkerRESTClient(transport: transport, timeZone: .gmt, now: { Date() }, sleep: { _ in }, random: { $0.lowerBound })
    let link = TestMQTTLink(), gate = SleepGate(), log = EventLog()
    await link.configure(connack: 5)
    let cloud = AnkerCloudBackend(rest: rest, makeIdentity: identityTracker.make, makeLink: { link }, now: { Date() }, sleep: { await gate.sleep($0) })
    let events = Task { for await event in cloud.events { await log.append(event) } }
    defer { events.cancel() }
    await cloud.restore(testSession, credentials: testCredentials)
    let connecting = Task { try await cloud.connect(to: testCharger) }
    do {
        try await eventually {
            if await log.statuses.contains(failure.status) { return true }
            return await gate.pending(1) == 1
        }
    } catch {
        await cloud.disconnect(); _ = await connecting.result; throw error
    }
    let stopped = await log.statuses.contains(failure.status)
    #expect(stopped)
    #expect(await gate.delays.filter { [1.0, 2, 4].contains($0) }.isEmpty)
    // On the red implementation, cancel the unwanted recovery instead of
    // leaving a suspended connect or synthetic identity after a failed test.
    if !stopped { await cloud.disconnect() }
    let outcome = await connecting.result
    switch outcome {
    case .success: Issue.record("terminal auth failure unexpectedly connected")
    case let .failure(error): #expect(error as? AnkerError == failure.error)
    }
    let expectedMetadataCalls = (failRefresh ? 1 : 0) + (failure == .lockout ? 1 : 2)
    let expectedLoginCalls = failure == .lockout ? 0 : 1
    #expect(await transport.metadataCalls == expectedMetadataCalls)
    #expect(await transport.loginCalls == expectedLoginCalls)
    #expect(await link.sent.count == (failRefresh ? 1 : 0))
    #expect(identityTracker.liveCount == 0)
    await cloud.disconnect()
    #expect(await transport.metadataCalls == expectedMetadataCalls)
    #expect(await transport.loginCalls == expectedLoginCalls)
    #expect(await gate.pending(1) == 0)
}
}

@Test func explicitDisconnectDoesNotTerminateAuthentication() async throws {
    let cloud = try AnkerCloudBackendTests().backend(TestMQTTLink()), log = EventLog()
    let consumer = Task { for await event in cloud.events { await log.append(event) } }
    defer { consumer.cancel() }
    await cloud.restore(testSession, credentials: testCredentials)
    await cloud.disconnect()
    for _ in 0..<100 { await Task.yield() }
    #expect(await !log.statuses.contains(.sessionEnded))
}

@Test func signInAndDiscoveryEmitTerminalCoreStatus() async throws {
    for (reply, expected) in [(ScriptedREST.Reply(body: "{\"code\":26108}"), ConnectionStatus.signInFailed("Invalid credentials")),
                              (.init(body: "{\"code\":26050}"), .verificationRequired),
                              (.init(body: "{\"code\":100053}"), .signInFailed("Sign-in retry limit exceeded")),
                              (.init(status: 401), .sessionEnded), (.init(status: 403), .sessionEnded)] {
        for discovery in [false, true] {
            let clock = RESTClock()
            let transport = ScriptedREST(discovery && (reply.status == 401 || reply.status == 403) ? [reply, loginReply(clock), reply] : [reply], clock: clock)
            let cloud = AnkerCloudBackend(rest: restClient(transport, clock), makeLink: { TestMQTTLink() }, now: { clock.now() }, sleep: { _ in })
            let log = EventLog()
            let consumer = Task { for await event in cloud.events { await log.append(event) } }
            defer { consumer.cancel() }
            if discovery { await cloud.restore(testSession, credentials: testCredentials) }
            do {
                if discovery { _ = try await cloud.listChargers() } else { _ = try await cloud.signIn(testCredentials) }
                Issue.record("Expected authentication failure")
            } catch {}
            for _ in 0..<100 { await Task.yield() }
            #expect(await log.statuses == [expected])
            await cloud.disconnect()
        }
    }
}

@Test func obsoleteAuthenticationFailuresDoNotEmitIntoReplacement() async throws {
    for discovery in [false, true] {
        let clock = RESTClock(), transport = SuspendedREST()
        let cloud = AnkerCloudBackend(rest: restClient(transport, clock), makeLink: { TestMQTTLink() }, now: { clock.now() }, sleep: { _ in })
        let log = EventLog()
        let consumer = Task { for await event in cloud.events { await log.append(event) } }
        defer { consumer.cancel() }
        if discovery { await cloud.restore(testSession, credentials: testCredentials) }
        let obsolete = Task {
            if discovery { _ = try await cloud.listChargers() } else { _ = try await cloud.signIn(testCredentials) }
        }
        await transport.waitForRequests(1)
        await cloud.restore(testSession, credentials: testCredentials)
        await transport.complete(.init(body: "{\"code\":26108}"))
        _ = await obsolete.result
        for _ in 0..<100 { await Task.yield() }
        #expect(await log.statuses.isEmpty)
        await cloud.disconnect()
    }
}

@Test func eventSubscriptionsAreFreshNonReplayingAndIndependent() async throws {
    let clock = RESTClock()
    let transport = ScriptedREST([.init(body: "{\"code\":26108}"), .init(body: "{\"code\":26050}"), .init(body: "{\"code\":100053}")], clock: clock)
    let cloud = AnkerCloudBackend(rest: restClient(transport, clock), makeLink: { TestMQTTLink() }, now: { clock.now() }, sleep: { _ in })
    _ = try? await cloud.signIn(testCredentials) // No subscriber: nothing is retained.
    var old = cloud.events.makeAsyncIterator()
    _ = try? await cloud.signIn(testCredentials) // Queued only for the old subscriber.
    await cloud.disconnect()
    var current = await cloud.subscribeToEvents().makeAsyncIterator()
    _ = try? await cloud.signIn(testCredentials)
    guard case .status(.verificationRequired) = await old.next() else { Issue.record("Old queue lost its first event"); return }
    guard case .status(.signInFailed("Sign-in retry limit exceeded")) = await current.next() else { Issue.record("New queue replayed an obsolete event"); return }
    guard case .status(.signInFailed("Sign-in retry limit exceeded")) = await old.next() else { Issue.record("Subscribers did not independently receive the new event"); return }
    await cloud.disconnect()
}

private actor AcceptedSessionLog {
    var tokens: [String] = []
    func append(_ event: BackendEvent) {
        if case .sessionUpdated(let session) = event { tokens.append(session.authToken) }
    }
}
@Test func disconnectAndReplacementDoNotRelaySuspendedOldRESTLogin() async throws {
    let clock = RESTClock(), transport = SuspendedREST(); let rest = restClient(transport, clock)
    let cloud = AnkerCloudBackend(rest: rest, makeLink: { TestMQTTLink() }, now: { clock.now() }, sleep: { _ in })
    await cloud.restore(testSession, credentials: testCredentials)
    let obsolete = Task { try await rest.login(testCredentials) }
    await transport.waitForRequests(1)
    await cloud.disconnect()
    let stream = await cloud.subscribeToEvents(), log = AcceptedSessionLog()
    let consumer = Task { for await event in stream { await log.append(event) } }
    defer { consumer.cancel() }
    await cloud.restore(testSession, credentials: testCredentials)
    await transport.complete(loginReply(clock, token: "synthetic-obsolete"))
    await #expect(throws: CancellationError.self) { _ = try await obsolete.value }
    let accepted = Task { try await rest.login(testCredentials) }
    await transport.waitForRequests(2)
    await transport.complete(loginReply(clock, token: "synthetic-current")); _ = try await accepted.value
    try await eventually { await log.tokens == ["synthetic-current"] }
    #expect(await log.tokens == ["synthetic-current"])
    await cloud.disconnect()
}
