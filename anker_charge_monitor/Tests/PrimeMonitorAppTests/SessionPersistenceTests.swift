import Foundation
import Testing
import PrimeMonitorCore
@testable import PrimeMonitor
@testable import AnkerCloud

private actor PersistenceTransport: HTTPTransport {
    var bodies: [(Int, String)]
    var paths: [String] = []
    var tokens: [String?] = []
    init(_ bodies: [(Int, String)]) { self.bodies = bodies }
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        paths.append(request.url!.path(percentEncoded: false)); tokens.append(request.value(forHTTPHeaderField: "x-auth-token"))
        guard !bodies.isEmpty else { throw AnkerError.malformed }
        let (status, body) = bodies.removeFirst()
        return (Data(body.utf8), HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!)
    }
}
@Suite @MainActor struct SessionPersistenceTests {
    @Test func refreshedSessionSurvivesControllerRestartInSameProcess() async throws {
        // No charger is selected, so this integration exercises real REST/backend
        // session forwarding without creating any MQTT identity or connection.
        for proactive in [true, false] {
            let directory = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-" + UUID().uuidString, directoryHint: .isDirectory)
            defer { try? FileManager.default.removeItem(at: directory) }
            let provider = SyntheticProvider(), secret = MemorySessionStore()
            let selection = CredentialSelection(provider: "synthetic", settings: ["item": "Synthetic account", "country": "US"])
            let state = StateStore(fileURL: directory.appending(path: "state.json"))
            try state.save(.init(charger: nil, closedInterval: .m1, credentials: selection))
            defer { try? secret.delete() }
            let date = Date(timeIntervalSince1970: 1_700_000_000)
            let old = AccountSession(authToken: "synthetic-old", userID: "synthetic-user", expiresAt: date.addingTimeInterval(proactive ? 30 : 10000), nickname: "")
            let empty = "{\"code\":0,\"data\":{\"data\":[]}}"
            let login = "{\"code\":0,\"data\":{\"auth_token\":\"synthetic-new\",\"user_id\":\"synthetic-user\",\"token_expires_at\":1700010000,\"nick_name\":\"Synthetic\"}}"
            let transport = PersistenceTransport((proactive ? [] : [(401, "{}")]) + [(200, login), (200, empty)])
            let rest = AnkerRESTClient(transport: transport, timeZone: .gmt, now: { date }, sleep: { _ in }, random: { $0.lowerBound })
            let backend = AnkerCloudBackend(rest: rest, makeLink: { fatalError("No MQTT connection expected") }, now: { date }, sleep: { _ in })
            let controller = MonitorController(backend: backend, secrets: secret, state: state, events: SystemEvents(sources: []), now: { date }, scheduler: ManualScheduler(), makeProvider: { _ in provider })
            #expect(try await secret.load()?.credentials == appCredentials)
            #expect(await provider.reads == 1)
            try secret.save(.init(credentials: appCredentials, session: old))
            controller.start(); await settle(); await controller.reloadChargers(); await settle()
            let loaded = try await secret.load(); let saved = try #require(loaded)
            #expect(saved.session?.authToken == "synthetic-new")
            #expect(saved.credentials == appCredentials)
            #expect(await transport.paths.filter { $0 == "/passport/login" }.count == 1)
            await controller.stop()
            await provider.fail()
            let restartedTransport = PersistenceTransport([(200, empty)])
            let restartedREST = AnkerRESTClient(transport: restartedTransport, timeZone: .gmt, now: { date }, sleep: { _ in }, random: { $0.lowerBound })
            let restartedBackend = AnkerCloudBackend(rest: restartedREST, makeLink: { fatalError("No MQTT connection expected") }, now: { date }, sleep: { _ in })
            let restarted = MonitorController(backend: restartedBackend, secrets: secret, state: state, events: SystemEvents(sources: []), now: { date }, scheduler: ManualScheduler(), makeProvider: { _ in provider })
            restarted.start(); await settle(); await restarted.reloadChargers()
            #expect(await provider.reads == 1)
            #expect(await restartedTransport.paths == ["/power_service/v1/app/get_relate_and_bind_devices"])
            #expect(await restartedTransport.tokens == ["synthetic-new"])
            await restarted.stop()
            // A new process constructs a new cache: retrieve from its independent
            // provider and authenticate again rather than restoring a disk token.
            let freshProvider = SyntheticProvider(), freshSecrets = MemorySessionStore()
            let freshTransport = PersistenceTransport([(200, login), (200, empty)])
            let freshREST = AnkerRESTClient(transport: freshTransport, timeZone: .gmt, now: { date }, sleep: { _ in }, random: { $0.lowerBound })
            let freshBackend = AnkerCloudBackend(rest: freshREST, makeLink: { fatalError("No MQTT connection expected") }, now: { date }, sleep: { _ in })
            let fresh = MonitorController(backend: freshBackend, secrets: freshSecrets, state: state, events: SystemEvents(sources: []), now: { date }, scheduler: ManualScheduler(), makeProvider: { _ in freshProvider })
            fresh.start(); await settle()
            #expect(await freshProvider.reads == 1)
            #expect(await freshTransport.paths == ["/passport/login", "/power_service/v1/app/get_relate_and_bind_devices"])
            await fresh.stop()
        }
    }
    @Test func authenticationFailuresReachControllerWithoutAnkerImportsInApp() async throws {
        for (body, expected) in [("{\"code\":26108}", ConnectionStatus.signInFailed("Invalid credentials")), ("{\"code\":26050}", .verificationRequired), ("{\"code\":100053}", .signInFailed("Sign-in retry limit exceeded"))] {
            let transport = PersistenceTransport([(200, body)])
            let rest = AnkerRESTClient(transport: transport, timeZone: .gmt, now: { Date() }, sleep: { _ in }, random: { $0.lowerBound })
            let backend = AnkerCloudBackend(rest: rest, makeLink: { fatalError() }, now: { Date() }, sleep: { _ in })
            let rig = try ControllerRig(configured: false)
            let controller = MonitorController(backend: backend, secrets: rig.secrets, state: StateStore(fileURL: rig.directory.appending(path: "state.json", directoryHint: .notDirectory)), events: SystemEvents(sources: [rig.events]), now: { Date() }, scheduler: rig.clock)
            controller.start(); await controller.signIn(appCredentials); await settle()
            #expect(controller.status == expected)
            await rig.events.send(.network(true)); await rig.events.send(.wake); await controller.signInAgain()
            #expect(await transport.paths == ["/passport/login"])
            #expect(controller.status == expected); await controller.stop(); await rig.finish()
        }
    }
}
