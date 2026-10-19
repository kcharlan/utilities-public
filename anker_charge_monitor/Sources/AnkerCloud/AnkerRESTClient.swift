import Foundation
import PrimeMonitorCore

public struct MQTTInfo: Equatable, Sendable {
    public let userID: String
    public let appName: String
    public let thingName: String
    public let certificateID: String
    public let certificatePEM: String
    public let privateKeyPEM: String
    public let rootCAPEM: String
    public let endpoint: String

    public init(userID: String, appName: String, thingName: String, certificateID: String,
                certificatePEM: String, privateKeyPEM: String, rootCAPEM: String, endpoint: String) {
        self.userID = userID; self.appName = appName; self.thingName = thingName
        self.certificateID = certificateID; self.certificatePEM = certificatePEM
        self.privateKeyPEM = privateKeyPEM; self.rootCAPEM = rootCAPEM; self.endpoint = endpoint
    }
}

/// Ports anker-solix-api `session.py`, async_authenticate / request /
/// get_user_mqtt_info, and `apibase.py`, get_bind_devices, commit 8a5222b.
/// App deviations: one HTTP reauthentication per request; only A2345 discovery;
/// accepted sessions publish to independent subscribers, guarded by account context.
public actor AnkerRESTClient {
    public private(set) var session: AccountSession?
    private let transport: any HTTPTransport
    private let timeZone: TimeZone
    private let headerTimeZone: TimeZone
    private let now: @Sendable () -> Date
    private let random: @Sendable (ClosedRange<Int>) -> Int
    private let throttle: RequestThrottle
    private var credentials: AnkerCredentials?
    private var context = UUID()
    private var backendPreparationSequence: UInt64 = 0
    private var authentication: (id: UUID, task: Task<AccountSession, Error>)?
    private var subscribers: [UUID: AsyncStream<AccountSession>.Continuation] = [:]
    private static let loginEndpoint = "passport/login"

    public init(transport: any HTTPTransport, timeZone: TimeZone,
                now: @escaping @Sendable () -> Date,
                sleep: @escaping @Sendable (TimeInterval) async -> Void,
                random: @escaping @Sendable (ClosedRange<Int>) -> Int) {
        self.transport = transport; self.timeZone = timeZone; self.now = now; self.random = random
        headerTimeZone = TimeZone(secondsFromGMT: timeZone.secondsFromGMT(for: now()))!
        throttle = RequestThrottle(now: now, sleep: sleep)
    }

    public func sessionUpdates() -> AsyncStream<AccountSession> {
        let id = UUID()
        let (stream, continuation) = AsyncStream<AccountSession>.makeStream()
        subscribers[id] = continuation
        continuation.onTermination = { [weak self] _ in
            Task { await self?.removeSubscriber(id) }
        }
        return stream
    }

    private func removeSubscriber(_ id: UUID) { subscribers[id] = nil }

    /// Internal backend relay capability. Invalidation and subscription happen
    /// in one actor turn; an old login cannot enter the new relay between them.
    struct PreparedAuthentication: Sendable {
        fileprivate let context: UUID
        let updates: AsyncStream<AccountSession>
    }
    /// One backend owns this REST client. Its monotonically increasing sequence
    /// is assigned before its first await; late actor messages cannot replace a
    /// newer REST context. Network login is deliberately outside this short phase.
    func prepareAuthentication(credentials: AnkerCredentials, restored: AccountSession?, sequence: UInt64) throws -> PreparedAuthentication {
        guard sequence > backendPreparationSequence else { throw CancellationError() }
        backendPreparationSequence = sequence
        replaceContext(credentials)
        session = restored
        return PreparedAuthentication(context: context, updates: sessionUpdates())
    }
    func login(prepared: PreparedAuthentication) async throws -> AccountSession {
        try await authenticate(context: prepared.context)
    }
    func invalidateAuthentication(sequence: UInt64) {
        guard sequence > backendPreparationSequence else { return }
        backendPreparationSequence = sequence
        replaceContext(nil)
    }

    public func restore(_ session: AccountSession, credentials: AnkerCredentials) {
        replaceContext(credentials)
        self.session = session
    }

    public func login(_ credentials: AnkerCredentials) async throws -> AccountSession {
        replaceContext(credentials)
        return try await authenticate(context: context)
    }

    private func replaceContext(_ credentials: AnkerCredentials?) {
        context = UUID()
        authentication?.task.cancel()
        authentication = nil
        session = nil
        self.credentials = credentials
    }

    private func checkContext(_ expected: UUID) throws {
        try Task.checkCancellation()
        guard context == expected else { throw CancellationError() }
    }

    private func authenticate(context expected: UUID) async throws -> AccountSession {
        try checkContext(expected)
        if let authentication { return try await authentication.task.value }
        guard let credentials else { throw AnkerError.authorization }
        let id = UUID()
        let task = Task { try await self.performLogin(credentials, context: expected) }
        authentication = (id, task)
        do {
            let accepted = try await task.value
            try checkContext(expected)
            if authentication?.id == id { authentication = nil }
            return accepted
        } catch {
            if authentication?.id == id { authentication = nil }
            throw error
        }
    }

    private func performLogin(_ credentials: AnkerCredentials, context expected: UUID) async throws -> AccountSession {
        let body = try RequestBuilder.loginBody(credentials: credentials, crypto: LoginCrypto(), now: now(), timeZone: timeZone)
        let data = try await send(endpoint: Self.loginEndpoint, body: body, context: expected, login: true)
        guard let token = data["auth_token"] as? String, !token.isEmpty,
              let user = data["user_id"] as? String, !user.isEmpty,
              let expiry = data["token_expires_at"] as? Double, expiry.isFinite, expiry > 0 else { throw AnkerError.malformed }
        let accepted = AccountSession(authToken: token, userID: user, expiresAt: Date(timeIntervalSince1970: expiry), nickname: data["nick_name"] as? String ?? "")
        try checkContext(expected)
        session = accepted
        for continuation in subscribers.values { continuation.yield(accepted) }
        return accepted
    }

    public func listChargers() async throws -> [ChargerInfo] {
        let data = try await request(endpoint: "power_service/v1/app/get_relate_and_bind_devices")
        guard let devices = data["data"] as? [[String: Any]] else { throw AnkerError.malformed }
        return devices.compactMap { device in
            guard let serial = device["device_sn"] as? String, !serial.isEmpty else { return nil }
            let model = device["product_code"] as? String ?? device["device_pn"] as? String ?? ""
            guard model == "A2345" else { return nil }
            return ChargerInfo(serial: serial, model: model, alias: device["alias_name"] as? String ?? "", name: device["device_name"] as? String ?? "")
        }
    }

    public func mqttInfo() async throws -> MQTTInfo {
        let data = try await request(endpoint: "app/devicemanage/get_user_mqtt_info")
        func string(_ key: String) throws -> String {
            guard let value = data[key] as? String else { throw AnkerError.malformed }
            return value
        }
        let endpoint = try string("endpoint_addr")
        guard !endpoint.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw AnkerError.malformed }
        return try MQTTInfo(userID: string("user_id"), appName: string("app_name"), thingName: string("thing_name"),
                            certificateID: string("certificate_id"), certificatePEM: string("certificate_pem"),
                            privateKeyPEM: string("private_key"), rootCAPEM: string("aws_root_ca1_pem"), endpoint: endpoint)
    }

    private func request(endpoint: String) async throws -> [String: Any] {
        let expected = context
        if session == nil || session!.expiresAt.timeIntervalSince(now()) < 60 {
            _ = try await authenticate(context: expected)
        }
        return try await send(endpoint: endpoint, body: Data("{}".utf8), context: expected, login: false)
    }

    private func send(endpoint: String, body: Data, context expected: UUID, login: Bool) async throws -> [String: Any] {
        var reauthenticated = false
        var retriedBusy = false
        var retriedServer = false
        var retriedRateLimit = false
        var delay: TimeInterval?
        while true {
            try checkContext(expected)
            await throttle.acquire(endpoint: endpoint, delay: delay)
            do { try checkContext(expected) } catch { await throttle.release(); throw error }
            guard let credentials else { await throttle.release(); throw AnkerError.authorization }
            var request = URLRequest(url: AnkerRegion.baseURL(country: credentials.country).appending(path: endpoint, directoryHint: .notDirectory), timeoutInterval: 10)
            request.httpMethod = "POST"
            request.httpBody = body
            request.allHTTPHeaderFields = RequestBuilder.headers(country: credentials.country, timeZone: headerTimeZone, session: login ? nil : session)
            let bytes: Data
            let status: Int
            do {
                let response = try await transport.send(request)
                bytes = response.0; status = response.1.statusCode
                await throttle.finish(endpoint: endpoint, status: status)
            } catch {
                await throttle.finish(endpoint: endpoint, status: nil)
                try checkContext(expected)
                if (error as? URLError)?.code == .timedOut {
                    if !login && !retriedServer {
                        retriedServer = true; delay = TimeInterval(random(2...5)); continue
                    }
                    throw AnkerError.http(522)
                }
                throw error
            }
            try checkContext(expected)
            delay = nil
            if status == 401 || status == 403 {
                guard !login, !reauthenticated else { throw AnkerError.http(status) }
                reauthenticated = true
                _ = try await authenticate(context: expected)
                continue
            }
            if status == 429, !login, !retriedRateLimit {
                retriedRateLimit = true; continue
            }
            if [502, 504, 522].contains(status), !login, !retriedServer {
                retriedServer = true; delay = TimeInterval(random(2...5)); continue
            }
            guard (200..<300).contains(status) else { throw AnkerError.http(status) }
            guard let envelope = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any],
                  let code = envelope["code"] as? Int else { throw AnkerError.malformed }
            if let error = AnkerError.from(code: code, message: envelope["msg"] as? String ?? "") {
                if error == .busy, !login, !retriedBusy {
                    retriedBusy = true; delay = TimeInterval(random(2...5)); continue
                }
                throw error
            }
            guard let data = envelope["data"] as? [String: Any] else { throw AnkerError.malformed }
            return data
        }
    }
}
