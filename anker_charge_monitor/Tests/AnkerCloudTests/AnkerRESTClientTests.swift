import Foundation
import PrimeMonitorCore
import Testing
@testable import AnkerCloud

final class RESTClock: @unchecked Sendable {
    private let lock = NSLock()
    private var date = Date(timeIntervalSince1970: 1_700_000_000)
    private var waits: [Double] = []
    private var draws: [ClosedRange<Int>] = []
    func now() -> Date { lock.withLock { date } }
    func advance(_ seconds: Double) { lock.withLock { date.addTimeInterval(seconds) } }
    func sleep(_ seconds: Double) async { lock.withLock { waits.append(seconds); date.addTimeInterval(seconds) } }
    func random(_ range: ClosedRange<Int>) -> Int { lock.withLock { draws.append(range); return 4 } }
    var sleeps: [Double] { lock.withLock { waits } }
    var ranges: [ClosedRange<Int>] { lock.withLock { draws } }
}

actor ScriptedREST: HTTPTransport {
    struct Reply: Sendable { var status = 200; var body = "{\"code\":0,\"data\":{\"data\":[]}}"; var elapsed: Double = 0; var timeout = false }
    var replies: [Reply]
    var requests: [URLRequest] = []
    var sentAt: [Date] = []
    let clock: RESTClock
    init(_ replies: [Reply], clock: RESTClock) { self.replies = replies; self.clock = clock }
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        requests.append(request)
        sentAt.append(clock.now())
        guard !replies.isEmpty else { throw AnkerError.malformed }
        let reply = replies.removeFirst()
        clock.advance(reply.elapsed)
        if reply.timeout { throw URLError(.timedOut) }
        return (Data(reply.body.utf8), HTTPURLResponse(url: request.url!, statusCode: reply.status, httpVersion: nil, headerFields: nil)!)
    }
}
let restCredentials = AnkerCredentials(email: "synthetic@example.invalid", password: "synthetic-password", country: "us")
func restoredSession(_ clock: RESTClock, remaining: Double = 1000, token: String = "synthetic-token") -> AccountSession {
    .init(authToken: token, userID: "synthetic-user", expiresAt: clock.now().addingTimeInterval(remaining), nickname: "Synthetic")
}
func loginReply(_ clock: RESTClock, token: String = "new-token") -> ScriptedREST.Reply {
    .init(body: "{\"code\":0,\"data\":{\"auth_token\":\"\(token)\",\"user_id\":\"synthetic-user\",\"token_expires_at\":\(clock.now().timeIntervalSince1970 + 10000),\"nick_name\":\"Synthetic\"}}")
}
func restClient(_ transport: any HTTPTransport, _ clock: RESTClock) -> AnkerRESTClient {
    AnkerRESTClient(transport: transport, timeZone: .gmt, now: { clock.now() }, sleep: { await clock.sleep($0) }, random: { clock.random($0) })
}

@Test func loginSendsBodyAndParsesSession() async throws {
    let clock = RESTClock(); let transport = ScriptedREST([loginReply(clock)], clock: clock)
    let client = restClient(transport, clock)
    let session = try await client.login(restCredentials)
    #expect(session.authToken == "new-token")
    #expect(session.nickname == "Synthetic")
    #expect(await client.session == session)
    let request = try #require(await transport.requests.first)
    #expect(request.url?.absoluteString == "https://ankerpower-api.anker.com/passport/login")
    #expect(request.httpMethod == "POST")
    #expect(request.timeoutInterval == 10)
    #expect(request.value(forHTTPHeaderField: "x-auth-token") == nil)
    let requestBody = try #require(request.httpBody)
    let body = try #require(JSONSerialization.jsonObject(with: requestBody) as? [String: Any])
    #expect(body["email"] as? String == restCredentials.email)
    #expect(body["ab"] as? String == "US")
    #expect(body["transaction"] as? String == "1700000000000")
    #expect(body["time_zone"] as? Int == 0)
    #expect(body["enc"] as? Int == 0)
    #expect((body["client_secret_info"] as? [String: String])?["public_key"]?.count == 130)
    #expect(body["password"] as? String != restCredentials.password)
}

@Test func refreshBoundaryMatchesUpstream() async throws {
    for remaining in [59.999, 60, 61] {
        let clock = RESTClock()
        let transport = ScriptedREST(remaining < 60 ? [loginReply(clock), .init()] : [.init()], clock: clock)
        let client = restClient(transport, clock)
        await client.restore(restoredSession(clock, remaining: remaining), credentials: restCredentials)
        _ = try await client.listChargers()
        #expect(await transport.requests.count == (remaining < 60 ? 2 : 1))
    }
}

@Test func http401ReloginsOnceThenFails() async throws {
    for status in [401, 403] {
        let clock = RESTClock(); let transport = ScriptedREST([.init(status: status), loginReply(clock), .init(status: status)], clock: clock)
        let client = restClient(transport, clock)
        await client.restore(restoredSession(clock), credentials: restCredentials)
        await #expect(throws: AnkerError.http(status)) { try await client.listChargers() }
        #expect(await transport.requests.count == 3)
        let loginTransport = ScriptedREST([.init(status: status)], clock: clock)
        await #expect(throws: AnkerError.http(status)) { try await restClient(loginTransport, clock).login(restCredentials) }
        #expect(await loginTransport.requests.count == 1)
    }
}

@Test func bodyAuthErrorsDoNotRelogin() async throws {
    for code in [401,403,429,502,504,997,998,999,10000,10003,10004,10007,26050,26051,26052,26053,26054,26055,26070,26084,26108,26156,26161,31001,31003,100053,160003] {
        let clock = RESTClock(); let transport = ScriptedREST([.init(body: "{\"code\":\(code),\"msg\":\"synthetic\"}")], clock: clock)
        let client = restClient(transport, clock)
        await client.restore(restoredSession(clock), credentials: restCredentials)
        await #expect(throws: AnkerError.from(code: code, message: "synthetic")!) { try await client.listChargers() }
        #expect(await transport.requests.count == 1)
    }
}

@Test func invalidCredentialsNeverRetries() async throws {
    for code in [26108,26156] {
        let clock = RESTClock(); let transport = ScriptedREST([.init(body: "{\"code\":\(code)}")], clock: clock)
        await #expect(throws: AnkerError.invalidCredentials) { try await restClient(transport, clock).login(restCredentials) }
        #expect(await transport.requests.count == 1)
    }
}

@Test func busyAndServerErrorsRetryOnceWithRecordedRandomDelay() async throws {
    for reply in [ScriptedREST.Reply(body: "{\"code\":21105}"), .init(status: 502), .init(status: 504), .init(timeout: true)] {
        let clock = RESTClock(); let transport = ScriptedREST([reply, reply], clock: clock)
        let client = restClient(transport, clock)
        await client.restore(restoredSession(clock), credentials: restCredentials)
        do { _ = try await client.listChargers(); Issue.record("Expected final failure") } catch {}
        #expect(await transport.requests.count == 2)
        #expect(clock.ranges == [2...5])
        #expect(clock.sleeps.reduce(0,+) >= 4)
    }
}

@Test func http429RetriesOnceAndThrottlesEndpoint() async throws {
    let clock = RESTClock()
    let transport = ScriptedREST(Array(repeating: .init(), count: 9) + [.init(status: 429), .init(status: 429)], clock: clock)
    let client = restClient(transport, clock)
    await client.restore(restoredSession(clock), credentials: restCredentials)
    for _ in 0..<9 { _ = try await client.listChargers() }
    await #expect(throws: AnkerError.http(429)) { try await client.listChargers() }
    #expect(await transport.requests.count == 11)
    #expect(clock.now().timeIntervalSince1970 >= 1_700_000_065)
    #expect(clock.ranges.isEmpty)
}

@Test func listChargersFiltersToA2345() async throws {
    let clock = RESTClock()
    let body = "{\"code\":0,\"data\":{\"data\":[{\"device_sn\":\"synthetic-serial\",\"product_code\":\"A2345\",\"alias_name\":\"Desk\",\"device_name\":\"Prime\"},{\"device_sn\":\"other\",\"product_code\":\"A1340\"},{\"device_sn\":\"fallback\",\"device_pn\":\"A2345\"},{\"product_code\":\"A2345\"}]}}"
    let transport = ScriptedREST([.init(body: body)], clock: clock); let client = restClient(transport, clock)
    await client.restore(restoredSession(clock), credentials: restCredentials)
    #expect(try await client.listChargers() == [.init(serial: "synthetic-serial", model: "A2345", alias: "Desk", name: "Prime"), .init(serial: "fallback", model: "A2345", alias: "", name: "")])
    #expect(await transport.requests.first?.url?.path(percentEncoded: false) == "/power_service/v1/app/get_relate_and_bind_devices")
    let endpoint = try #require(await transport.requests.first?.url)
    #expect(endpoint.path(percentEncoded: true) == "/power_service/v1/app/get_relate_and_bind_devices")
    #expect(endpoint.host(percentEncoded: false) == "ankerpower-api.anker.com")
}

@Test func mqttInfoParsesWireKeysAndRejectsEmptyEndpoint() async throws {
    for endpoint in ["mqtt.example.invalid", ""] {
        let clock = RESTClock()
        let body = "{\"code\":0,\"data\":{\"user_id\":\"user\",\"app_name\":\"app\",\"thing_name\":\"thing\",\"certificate_id\":\"cert\",\"certificate_pem\":\"synthetic-cert\",\"private_key\":\"synthetic-key\",\"aws_root_ca1_pem\":\"synthetic-root\",\"endpoint_addr\":\"\(endpoint)\"}}"
        let transport = ScriptedREST([.init(body: body)], clock: clock); let client = restClient(transport, clock)
        await client.restore(restoredSession(clock), credentials: restCredentials)
        if endpoint.isEmpty { await #expect(throws: AnkerError.malformed) { try await client.mqttInfo() } }
        else { #expect(try await client.mqttInfo() == MQTTInfo(userID: "user", appName: "app", thingName: "thing", certificateID: "cert", certificatePEM: "synthetic-cert", privateKeyPEM: "synthetic-key", rootCAPEM: "synthetic-root", endpoint: endpoint)) }
    }
}

actor SuspendedREST: HTTPTransport {
    private var pending: [CheckedContinuation<(Data, HTTPURLResponse), Error>] = []
    private var requests: [URLRequest] = []
    private var observers: [(Int, CheckedContinuation<Void, Never>)] = []
    private var canceled = false
    private var cancellationObservers: [CheckedContinuation<Void, Never>] = []
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        requests.append(request)
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                pending.append(continuation)
                let ready = observers.filter { requests.count >= $0.0 }
                observers.removeAll { requests.count >= $0.0 }
                ready.forEach { $0.1.resume() }
            }
        } onCancel: {
            Task { await self.recordCancellation() }
        }
    }
    private func recordCancellation() {
        canceled = true
        cancellationObservers.forEach { $0.resume() }
        cancellationObservers.removeAll()
    }
    func waitForCancellation() async {
        if canceled { return }
        await withCheckedContinuation { cancellationObservers.append($0) }
    }
    func waitForRequests(_ count: Int) async {
        if requests.count >= count { return }
        await withCheckedContinuation { observers.append((count, $0)) }
    }
    func complete(_ reply: ScriptedREST.Reply) {
        let request = requests[requests.count - pending.count]
        pending.removeFirst().resume(returning: (Data(reply.body.utf8), HTTPURLResponse(url: request.url!, statusCode: reply.status, httpVersion: nil, headerFields: nil)!))
    }
    var count: Int { requests.count }
    var lastRequest: URLRequest? { requests.last }
}

@Test func acceptedLoginsAndRefreshesPublishSessionUpdatesEvenWhenOriginalRequestFails() async throws {
    let clock = RESTClock()
    let transport = ScriptedREST([loginReply(clock, token: "explicit"), loginReply(clock, token: "proactive"), .init(status: 500), .init(status: 403), loginReply(clock, token: "http-refresh"), .init(status: 500)], clock: clock)
    let client = restClient(transport, clock)
    var first = await client.sessionUpdates().makeAsyncIterator()
    var second = await client.sessionUpdates().makeAsyncIterator()
    _ = try await client.login(restCredentials)
    await client.restore(restoredSession(clock, remaining: 30), credentials: restCredentials)
    await #expect(throws: AnkerError.http(500)) { try await client.listChargers() }
    await #expect(throws: AnkerError.http(500)) { try await client.listChargers() }
    // Read only now: each subscriber buffers independently from registration.
    for token in ["explicit", "proactive", "http-refresh"] {
        #expect(await first.next()?.authToken == token)
        #expect(await second.next()?.authToken == token)
    }
    #expect(await client.session?.authToken == "http-refresh")
}

@Test func cancelingOneSessionSubscriberLeavesOtherSubscriberActive() async throws {
    let clock = RESTClock(); let transport = ScriptedREST([loginReply(clock)], clock: clock)
    let client = restClient(transport, clock)
    let canceled = await client.sessionUpdates()
    var active = await client.sessionUpdates().makeAsyncIterator()
    let waiting = Task { for await _ in canceled {} }
    waiting.cancel()
    await waiting.value
    _ = try await client.login(restCredentials)
    #expect(await active.next()?.authToken == "new-token")
}

@Test func staleExplicitAndAutomaticAuthenticationCannotReplaceRestoredAccount() async throws {
    for automatic in [false, true] {
        let clock = RESTClock(); let transport = SuspendedREST(); let client = restClient(transport, clock)
        var updates = await client.sessionUpdates().makeAsyncIterator()
        if automatic { await client.restore(restoredSession(clock, remaining: 0), credentials: restCredentials) }
        let old = Task {
            if automatic { _ = try await client.listChargers() }
            else { _ = try await client.login(restCredentials) }
        }
        await transport.waitForRequests(1)
        let replacement = restoredSession(clock, token: "replacement")
        let replacementCredentials = AnkerCredentials(email: "replacement@example.invalid", password: "replacement", country: "DE")
        await client.restore(replacement, credentials: replacementCredentials)
        await transport.complete(loginReply(clock, token: "obsolete"))
        await #expect(throws: CancellationError.self) { try await old.value }
        #expect(await client.session == replacement)
        let fresh = Task { try await client.login(replacementCredentials) }
        await transport.waitForRequests(2)
        #expect(await transport.lastRequest?.url?.host(percentEncoded: false) == "ankerpower-api-eu.anker.com")
        #expect(await transport.lastRequest?.value(forHTTPHeaderField: "country") == "DE")
        await transport.complete(loginReply(clock, token: "accepted"))
        _ = try await fresh.value
        #expect(await updates.next()?.authToken == "accepted")
    }
}

@Test func replacementLoginWinsAgainstObsoleteLoginCompletion() async throws {
    let clock = RESTClock(); let transport = SuspendedREST(); let client = restClient(transport, clock)
    var updates = await client.sessionUpdates().makeAsyncIterator()
    let old = Task { try await client.login(restCredentials) }
    await transport.waitForRequests(1)
    let replacement = Task { try await client.login(restCredentials) }
    // Replacing the context cancels the old authentication task. Wait for that
    // event rather than relying on scheduler yields or wall-clock sleeps.
    await transport.waitForCancellation()
    await transport.complete(loginReply(clock, token: "obsolete"))
    await transport.waitForRequests(2)
    await transport.complete(loginReply(clock, token: "accepted"))
    await #expect(throws: CancellationError.self) { try await old.value }
    #expect(try await replacement.value.authToken == "accepted")
    #expect(await updates.next()?.authToken == "accepted")
}

@Test func loginErrorsNeverRetryEvenTransientErrors() async throws {
    for reply in [ScriptedREST.Reply(status: 429), .init(status: 502), .init(status: 504), .init(timeout: true), .init(body: "{\"code\":21105}")] {
        let clock = RESTClock(); let transport = ScriptedREST([reply], clock: clock)
        do { _ = try await restClient(transport, clock).login(restCredentials); Issue.record("Expected failed login") } catch {}
        #expect(await transport.requests.count == 1)
        #expect(clock.ranges.isEmpty)
    }
}

@Test func malformedSessionsAreNeverAccepted() async throws {
    for data in ["{}", "{\"auth_token\":\"token\",\"user_id\":\"user\"}", "{\"auth_token\":\"\",\"user_id\":\"user\",\"token_expires_at\":42}"] {
        let clock = RESTClock(); let transport = ScriptedREST([.init(body: "{\"code\":0,\"data\":\(data)}")], clock: clock)
        let client = restClient(transport, clock)
        await #expect(throws: AnkerError.malformed) { try await client.login(restCredentials) }
        #expect(await client.session == nil)
    }
}

@Test func timezoneHeaderFreezesConstructionOffsetWhileLoginUsesCurrentOffset() async throws {
    let clock = RESTClock() // November: standard time in New York.
    let transport = ScriptedREST([loginReply(clock)], clock: clock)
    let zone = try #require(TimeZone(identifier: "America/New_York"))
    let client = AnkerRESTClient(transport: transport, timeZone: zone, now: { clock.now() }, sleep: { await clock.sleep($0) }, random: { clock.random($0) })
    clock.advance(240 * 86400) // July: daylight saving time.
    _ = try await client.login(restCredentials)
    let request = try #require(await transport.requests.first)
    #expect(request.value(forHTTPHeaderField: "timezone") == "GMT-05:00")
    let bytes = try #require(request.httpBody)
    let body = try #require(JSONSerialization.jsonObject(with: bytes) as? [String: Any])
    #expect(body["time_zone"] as? Int == -14_400_000)
}

@Test func atomicReplacementRelayRejectsAnOldAcceptedLogin() async throws {
    let clock = RESTClock(), transport = SuspendedREST(); let client = restClient(transport, clock)
    let oldLogin = Task { try await client.login(restCredentials) }
    await transport.waitForRequests(1)
    let prepared = try await client.prepareAuthentication(credentials: restCredentials, restored: restoredSession(clock), sequence: 2)
    var replacementRelay = prepared.updates.makeAsyncIterator()
    await transport.complete(loginReply(clock, token: "synthetic-obsolete")); _ = await oldLogin.result
    let newLogin = Task { try await client.login(prepared: prepared) }
    await transport.waitForRequests(2)
    await transport.complete(loginReply(clock, token: "synthetic-current")); _ = try await newLogin.value
    #expect(await replacementRelay.next()?.authToken == "synthetic-current")
}

@Test func orderedRESTPreparationRejectsLateObsoleteSetupAndPreparedLogin() async throws {
    let clock = RESTClock(), transport = SuspendedREST(); let client = restClient(transport, clock)
    let current = try await client.prepareAuthentication(credentials: restCredentials, restored: restoredSession(clock, token: "synthetic-current"), sequence: 2)
    await #expect(throws: CancellationError.self) {
        _ = try await client.prepareAuthentication(credentials: restCredentials, restored: restoredSession(clock, token: "synthetic-old"), sequence: 1)
    }
    #expect(await client.session?.authToken == "synthetic-current")
    _ = try await client.prepareAuthentication(credentials: restCredentials, restored: restoredSession(clock, token: "synthetic-newer"), sequence: 3)
    await #expect(throws: CancellationError.self) { _ = try await client.login(prepared: current) }
    #expect(await transport.count == 0)
    #expect(await client.session?.authToken == "synthetic-newer")
    await client.invalidateAuthentication(sequence: 4)
    await #expect(throws: CancellationError.self) {
        _ = try await client.prepareAuthentication(credentials: restCredentials, restored: restoredSession(clock), sequence: 3)
    }
    #expect(await client.session == nil)
}
