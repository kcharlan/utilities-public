import Foundation
import Testing
import PrimeMonitorCore
@testable import PrimeMonitor

actor SyntheticProvider: CredentialProvider {
    var reads = 0
    var unavailable = false
    func fail() { unavailable = true }
    func succeed() { unavailable = false }
    func retrieve() async throws -> AnkerCredentials {
        reads += 1
        if unavailable { throw CredentialFailure.unavailable }
        return appCredentials
    }
}
@Suite @MainActor struct CredentialProviderTests {
    @Test func independentProviderCachesSessionAndFailedReloadRetainsIt() async throws {
        let provider = SyntheticProvider(), store = MemorySessionStore()
        store.replaceProvider(provider)
        let first = try #require(try await store.load())
        #expect(first.credentials == appCredentials)
        try store.save(.init(credentials: appCredentials, session: appSession))
        await provider.fail()
        #expect(try await store.load()?.session == appSession)
        await #expect(throws: CredentialFailure.unavailable) { try await store.load(reload: true) }
        #expect(try await store.load()?.session == appSession)
        store.replaceProvider(SyntheticProvider())
        #expect(try await store.load()?.session == nil)
        try store.delete()
        #expect(try await store.load() == nil)
    }
    @Test func initialFailureIsActionableAndNoSecretIsWrittenToState() async throws {
        let provider = SyntheticProvider(), store = MemorySessionStore()
        store.replaceProvider(provider); await provider.fail()
        await #expect(throws: CredentialFailure.unavailable) { try await store.load() }
        #expect(CredentialFailure.unavailable.message.contains("Retry"))
        let settings = OnePasswordConfiguration(item: "Synthetic item", vault: nil, country: "US")
        let state = AppState(charger: nil, closedInterval: .m1, credentials: settings.selection)
        let bytes = try JSONEncoder().encode(state)
        #expect(!String(decoding: bytes, as: UTF8.self).contains(appCredentials.password))
        #expect(!String(decoding: bytes, as: UTF8.self).contains(appSession.authToken))
        #expect(try JSONDecoder().decode(AppState.self, from: Data("{\"closedInterval\":60}".utf8)).credentials == nil)
    }
    @Test func syntheticProcessReadsPairPreservingWhitespace() async throws {
        let script = try SyntheticCLI("printf '%s' '[{\"id\":\"password\",\"value\":\"  synthetic password \\n\"},{\"purpose\":\"USERNAME\",\"value\":\"synthetic@example.invalid\"}]'")
        defer { script.remove() }
        let provider = OnePasswordProvider(configuration: .init(item: "-synthetic item", vault: "Synthetic vault", country: "US"), executable: script.url)
        let value = try await provider.retrieve()
        #expect(value.password == "  synthetic password \n")
        #expect(value.email == "synthetic@example.invalid")
    }
    @Test func malformedEmptyDuplicateAndFailureAreSanitized() async throws {
        for body in ["printf 'bad synthetic-private-output'", "printf '[]'", "printf '%s' '[{\"id\":\"username\",\"value\":\"u\"},{\"id\":\"password\",\"value\":\"\"}]'", "printf '%s' '[{\"id\":\"username\",\"value\":\"u\"},{\"id\":\"username\",\"value\":\"v\"}]'", "echo synthetic-private-error >&2; exit 7"] {
            let script = try SyntheticCLI(body); defer { script.remove() }
            let provider = OnePasswordProvider(configuration: .init(item: "Synthetic item", vault: nil, country: "US"), executable: script.url)
            do { _ = try await provider.retrieve(); Issue.record("Expected failure") }
            catch { #expect(error is CredentialFailure); #expect(!String(describing: error).contains("synthetic-private")) }
        }
    }
    @Test func timeoutCancellationAndMissingExecutable() async throws {
        let script = try SyntheticCLI("while :; do :; done")
        defer { script.remove() }
        let config = OnePasswordConfiguration(item: "Synthetic item", vault: nil, country: "US")
        let provider = OnePasswordProvider(configuration: config, executable: script.url, timeout: 0.05)
        await #expect(throws: CredentialFailure.timedOut) { try await provider.retrieve() }
        let pending = Task { try await OnePasswordProvider(configuration: config, executable: script.url).retrieve() }
        try await Task.sleep(for: .milliseconds(30)); pending.cancel()
        await #expect(throws: CancellationError.self) { try await pending.value }
        await #expect(throws: CredentialFailure.missingCLI) { try await OnePasswordProvider(configuration: config, executable: script.url.appendingPathExtension("absent")).retrieve() }
    }
}
struct SyntheticCLI {
    let url: URL
    init(_ body: String) throws {
        url = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-op-" + UUID().uuidString)
        try Data(("#!/bin/sh\n" + body + "\n").utf8).write(to: url)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: url.path(percentEncoded: false))
    }
    func remove() { try? FileManager.default.removeItem(at: url) }
}

actor GatedCredentialProvider: CredentialProvider {
    var entered = false
    private var continuation: CheckedContinuation<AnkerCredentials, Never>?
    private var entryWaiters: [CheckedContinuation<Void, Never>] = []
    func retrieve() async throws -> AnkerCredentials {
        entered = true
        return await withCheckedContinuation {
            continuation = $0
            for waiter in entryWaiters { waiter.resume() }
            entryWaiters.removeAll()
        }
    }
    func waitUntilEntered() async {
        if entered { return }
        await withCheckedContinuation { entryWaiters.append($0) }
    }
    func release() { continuation?.resume(returning: appCredentials); continuation = nil }
}
actor OrderedCredentialProvider: CredentialProvider {
    private var waits: [Int: CheckedContinuation<AnkerCredentials, Never>] = [:]
    var reads = 0
    func retrieve() async throws -> AnkerCredentials {
        let id = reads; reads += 1
        return await withCheckedContinuation { waits[id] = $0 }
    }
    func release(_ id: Int, _ value: AnkerCredentials) { waits.removeValue(forKey: id)?.resume(returning: value) }
}
@Suite @MainActor struct CredentialControllerTests {
    private let selection = CredentialSelection(provider: "synthetic", settings: ["account": "first"])
    private func make(_ rig: ControllerRig, store: MemorySessionStore, provider: any CredentialProvider) throws -> MonitorController {
        let state = StateStore(fileURL: rig.directory.appending(path: "state.json"))
        try state.save(.init(charger: appCharger, closedInterval: .m1, credentials: selection))
        return MonitorController(backend: rig.backend, secrets: store, state: state, events: SystemEvents(sources: [rig.events]), now: { rig.clock.date }, scheduler: rig.clock, makeProvider: { _ in provider })
    }
    @Test func pendingStartupIsLoadingAndStopJoinsLateProviderWithoutRestoring() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = GatedCredentialProvider()
        let controller = try make(rig, store: store, provider: provider)
        controller.start(); #expect(controller.status == .connecting)
        await settle(); #expect(await provider.entered)
        var stopped = false
        let stop = Task { await controller.stop(); stopped = true }
        await settle(); #expect(!stopped)
        await provider.release(); await stop.value
        #expect(await rig.backend.log.filter { $0 == "login" || $0 == "restore" }.isEmpty)
        await rig.finish()
    }
    @Test func signOutInvalidatesPendingReadAndSavedSelectionBeforeAwait() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = GatedCredentialProvider()
        let controller = try make(rig, store: store, provider: provider)
        controller.start(); await settle()
        let out = Task { await controller.signOut() }; await settle()
        #expect(controller.appState.credentials == nil); #expect(!store.configured)
        await provider.release(); await out.value
        #expect(try await store.load() == nil); #expect(controller.status == .notConfigured)
        #expect(StateStore(fileURL: rig.directory.appending(path: "state.json")).load().state.credentials == nil)
        #expect(await rig.backend.log.filter { $0 == "login" || $0 == "restore" }.isEmpty)
        await controller.stop(); await rig.finish()
    }
    @Test func sameSelectionReloadFailureKeepsWorkingCacheAndVisibleWarning() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = SyntheticProvider()
        let controller = try make(rig, store: store, provider: provider)
        controller.start(); await rig.events.send(.network(true)); await settle()
        #expect(controller.status == .connected)
        await provider.fail(); await controller.connect(using: selection, reload: true)
        #expect(try await store.load()?.session == appSession)
        guard case .error(let warning) = controller.status else { Issue.record("Expected reload warning"); await controller.stop(); await rig.finish(); return }
        #expect(warning.contains("Retry"))
        await rig.events.send(.network(false)); await rig.events.send(.network(true)); await settle()
        #expect(controller.status == .error(warning))
        await controller.stop(); await rig.finish()
    }
    @Test func editingSelectionInvalidatesCacheWithoutRetrievalUntilSignIn() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = SyntheticProvider()
        let controller = try make(rig, store: store, provider: provider)
        controller.start(); await settle()
        #expect(try await store.load()?.session == appSession)
        let next = CredentialSelection(provider: "synthetic", settings: ["account": "edited"])
        controller.setCredentialSelection(next)
        await settle()
        #expect(controller.appState.credentials == next)
        #expect(await provider.reads == 1)
        #expect(await rig.backend.log.filter { $0 == "login" }.count == 1)
        await controller.connect(using: next)
        #expect(await provider.reads == 2)
        #expect(await rig.backend.log.filter { $0 == "login" }.count == 2)
        await controller.stop(); await rig.finish()
    }
    @Test func replacementInvalidatesPendingAccountAndIndependentProviderCanRetry() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), old = GatedCredentialProvider(), replacement = SyntheticProvider()
        let state = StateStore(fileURL: rig.directory.appending(path: "state.json"))
        try state.save(.init(charger: appCharger, closedInterval: .m1, credentials: selection))
        let next = CredentialSelection(provider: "another-synthetic", settings: ["account": "second"])
        let controller = MonitorController(backend: rig.backend, secrets: store, state: state, events: SystemEvents(sources: [rig.events]), now: { rig.clock.date }, scheduler: rig.clock, makeProvider: { if $0.provider == "synthetic" { return old }; return replacement })
        controller.start(); await settle()
        let change = Task { await controller.connect(using: next) }; await settle()
        #expect(controller.appState.credentials == next)
        await old.release(); await change.value
        #expect(await rig.backend.log.filter { $0 == "login" }.count == 1)
        #expect(await replacement.reads == 1)
        #expect(try await store.load()?.session == appSession)
        await controller.stop(); await rig.finish()
    }
    @Test func unavailableStartupReturnsCredentialFailureAndExplicitRetrySucceeds() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = SyntheticProvider()
        await provider.fail()
        let controller = try make(rig, store: store, provider: provider)
        #expect(await LiveCheck.run(controller: controller, acquireLease: { AppInstanceLease {} }, timeout: 1, output: { _ in }) == 5)
        #expect(await rig.backend.log.filter { $0 == "login" }.isEmpty)
        controller.start(); await settle()
        await provider.succeed()
        await controller.connect(using: selection)
        #expect(await rig.backend.log.filter { $0 == "login" }.count == 1)
        #expect(controller.appState.credentials == selection)
        await controller.stop(); await rig.finish()
    }
    @Test func pendingLiveCheckTimesOutThenJoinsBeforeReleasingLease() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = GatedCredentialProvider()
        let controller = try make(rig, store: store, provider: provider)
        // Establish the blocked read before starting the timeout. Concurrent
        // AppKit initialization can exceed the old 50ms scheduling assumption;
        // releasing a provider which has not entered yet loses the signal.
        controller.start(); await provider.waitUntilEntered()
        var released = false, returned = false, timedOut = false
        var timeoutWaiter: CheckedContinuation<Void, Never>?
        let task = Task {
            let code = await LiveCheck.run(controller: controller, acquireLease: { AppInstanceLease { released = true } }, timeout: 0.02, output: {
                #expect($0 == "Timed out waiting for charger readings.")
                timedOut = true; timeoutWaiter?.resume(); timeoutWaiter = nil
            })
            returned = true; return code
        }
        await withCheckedContinuation {
            if timedOut { $0.resume() } else { timeoutWaiter = $0 }
        }
        #expect(!released); #expect(!returned)
        await provider.release(); #expect(await task.value == 3); #expect(released)
        #expect(await rig.backend.log.filter { $0 == "login" || $0 == "restore" }.isEmpty)
        await rig.finish()
    }
    @Test func sameSelectionReloadOvertakesPendingStartupWithoutOldCacheAcceptance() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = OrderedCredentialProvider()
        let controller = try make(rig, store: store, provider: provider)
        let fresh = AnkerCredentials(email: "fresh@example.invalid", password: "synthetic-fresh", country: "US")
        controller.start(); await settle(); #expect(await provider.reads == 1)
        let reload = Task { await controller.connect(using: selection, reload: true) }; await settle()
        let count = await provider.reads
        #expect(count == 2)
        if count == 1 { await provider.release(0, appCredentials); await settle() }
        await provider.release(1, fresh); await reload.value
        await provider.release(0, appCredentials); await settle()
        #expect(try await store.load()?.credentials == fresh)
        #expect(try await store.load()?.session == appSession)
        #expect(await rig.backend.log.filter { $0 == "login" }.count == 1)
        await controller.stop(); await rig.finish()
    }
    @Test func cacheRejectsOlderSameProviderCandidateAfterNewerSessionWasSaved() async throws {
        let provider = OrderedCredentialProvider(), store = MemorySessionStore()
        store.replaceProvider(provider)
        let old = Task { try await store.load() }; await settle()
        let fresh = Task { try await store.load(reload: true) }; await settle()
        await provider.release(1, appCredentials); _ = try await fresh.value
        try store.save(.init(credentials: appCredentials, session: appSession))
        await provider.release(0, appCredentials)
        await #expect(throws: CancellationError.self) { try await old.value }
        #expect(try await store.load()?.session == appSession)
    }
    @Test func settingsSaveFailureSurvivesAuthenticationAndSignOut() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = SyntheticProvider()
        let controller = MonitorController(backend: rig.backend, secrets: store, state: StateStore(fileURL: URL(filePath: "/dev/null/synthetic-state.json")), events: SystemEvents(sources: [rig.events]), now: { rig.clock.date }, scheduler: rig.clock, makeProvider: { _ in provider })
        controller.start(); await controller.connect(using: selection)
        #expect(controller.status == .error("Couldn't save settings."))
        await controller.signOut()
        #expect(controller.status == .error("Couldn't save settings."))
        await controller.stop(); await rig.finish()
    }
    @Test(arguments: ["item", "vault", "country", "provider"])
    func reconstructedControllerRejectsCachedSessionForDifferentSelection(_ changedField: String) async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), firstProvider = SyntheticProvider(), nextProvider = SyntheticProvider()
        let first = try make(rig, store: store, provider: firstProvider)
        first.start(); await settle()
        #expect(try await store.load()?.session == appSession)
        await first.stop(); await nextProvider.fail()
        var changed = selection
        if changedField == "provider" { changed.provider = "other-synthetic" }
        else { changed.settings[changedField] = "different-synthetic" }
        let state = StateStore(fileURL: rig.directory.appending(path: "state.json"))
        try state.save(.init(charger: appCharger, closedInterval: .m1, credentials: changed))
        let replacement = MonitorController(backend: rig.backend, secrets: store, state: state, events: SystemEvents(sources: []), now: { rig.clock.date }, scheduler: rig.clock, makeProvider: { _ in nextProvider })
        replacement.start(); await settle()
        #expect(await nextProvider.reads == 1)
        #expect(replacement.status == .error(CredentialFailure.unavailable.message))
        #expect(await rig.backend.log.filter { $0 == "login" }.count == 1)
        #expect(await rig.backend.log.filter { $0 == "restore" }.isEmpty)
        await replacement.stop(); await rig.finish()
    }
    @Test(arguments: [false, true])
    func reconstructionWithoutUsableFactoryCannotRestoreAnotherSelection(_ throwsFactory: Bool) async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = SyntheticProvider()
        let first = try make(rig, store: store, provider: provider)
        first.start(); await settle(); await first.stop()
        let state = StateStore(fileURL: rig.directory.appending(path: "state.json"))
        let changed = CredentialSelection(provider: "unsupported-synthetic", settings: [:])
        try state.save(.init(charger: appCharger, closedInterval: .m1, credentials: changed))
        let factory: ((CredentialSelection) throws -> any CredentialProvider)? = throwsFactory ? { _ in throw CredentialFailure.unsupported } : nil
        let replacement = MonitorController(backend: rig.backend, secrets: store, state: state, events: SystemEvents(sources: []), now: { rig.clock.date }, scheduler: rig.clock, makeProvider: factory)
        replacement.start(); await settle()
        #expect(!store.configured)
        #expect(await rig.backend.log.filter { $0 == "restore" }.isEmpty)
        #expect(replacement.status == .error("Couldn't configure the credential provider. Open Settings."))
        await replacement.stop(); await rig.finish()
    }
    @Test func reconstructionWithRemovedSelectionClearsSharedCache() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = SyntheticProvider()
        let first = try make(rig, store: store, provider: provider)
        first.start(); await settle(); await first.stop()
        let state = StateStore(fileURL: rig.directory.appending(path: "state.json"))
        try state.save(.initial)
        let replacement = MonitorController(backend: rig.backend, secrets: store, state: state, events: SystemEvents(sources: []), now: { rig.clock.date }, scheduler: rig.clock, makeProvider: { _ in provider })
        replacement.start(); await settle()
        #expect(!store.configured); #expect(replacement.status == .notConfigured)
        #expect(await provider.reads == 1)
        #expect(await rig.backend.log.filter { $0 == "restore" }.isEmpty)
        await replacement.stop(); await rig.finish()
    }
}

@Suite struct CredentialProcessBoundaryTests {
    @Test func fragmentedStdoutDoesNotLoseBytesBeforeProcessExit() async throws {
        let script = try SyntheticCLI("""
        printf '%s' '[{"id":"username","value":"synthetic@example.invalid"},'
        /bin/sleep 0.05
        printf '%s' '{"id":"password","value":"synthetic-password"}]'
        """)
        defer { script.remove() }
        let result = try await OnePasswordProvider(configuration: .init(item: "Synthetic item", vault: nil, country: "US"), executable: script.url).retrieve()
        #expect(result == appCredentials)
    }
    @Test func exactArgumentsEnvironmentAndLeadingDashItem() async throws {
        let script = try SyntheticCLI("""
        for expected in '--cache=false' 'item' 'get' '--fields' 'label=username,label=password' '--format' 'json' '--reveal' '--vault' 'Synthetic vault' '--' '-synthetic item'; do
            [ "$1" = "$expected" ] || exit 43
            shift
        done
        [ "$#" -eq 0 ] || exit 44
        [ "${OP_BIOMETRIC_UNLOCK_ENABLED}" = 'true' ] || exit 45
        [ "${OP_SERVICE_ACCOUNT_TOKEN+x}" != x ] || exit 46
        [ "${OP_CONNECT_TOKEN+x}" != x ] || exit 47
        [ "${OP_CONNECT_HOST+x}" != x ] || exit 48
        printf '%s' '[{"label":"username","value":"synthetic@example.invalid"},{"label":"password","value":"synthetic-password"}]'
        """)
        defer { script.remove() }
        let credentials = try await OnePasswordProvider(configuration: .init(item: "-synthetic item", vault: "Synthetic vault", country: "US"), executable: script.url).retrieve()
        #expect(credentials == appCredentials)
    }
    @Test func outputLimitInvalidUTF8AndCancellationBeforeSpawn() async throws {
        let config = OnePasswordConfiguration(item: "Synthetic item", vault: nil, country: "US")
        let flood = try SyntheticCLI("while :; do printf 'synthetic-output-over-limit'; printf 'synthetic-error-over-limit' >&2; done")
        defer { flood.remove() }
        await #expect(throws: CredentialFailure.outputLimit) { try await OnePasswordProvider(configuration: config, executable: flood.url).retrieve() }
        let invalid = try SyntheticCLI("printf '\\377'")
        defer { invalid.remove() }
        await #expect(throws: CredentialFailure.malformed) { try await OnePasswordProvider(configuration: config, executable: invalid.url).retrieve() }
        let cancelled = Task { try await OnePasswordProvider(configuration: config, executable: flood.url).retrieve() }
        cancelled.cancel()
        await #expect(throws: CancellationError.self) { try await cancelled.value }
    }
    @Test func timeoutAndCancellationJoinTERMResistantChild() async throws {
        for cancel in [true, false] {
            let marker = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-child-" + UUID().uuidString)
            defer { try? FileManager.default.removeItem(at: marker) }
            let script = try SyntheticCLI("trap '' TERM\nprintf '%s' \"$$\" > '\(marker.path(percentEncoded: false))'\nwhile :; do :; done")
            defer { script.remove() }
            let config = OnePasswordConfiguration(item: "Synthetic item", vault: nil, country: "US")
            // A loaded parallel suite can take over 0.5s to start the child shell,
            // and a timeout that fires first kills it before it reports its PID.
            // Only cancellation may end the cancel case.
            let timeout: TimeInterval = cancel ? 60 : 2
            let task = Task { try await OnePasswordProvider(configuration: config, executable: script.url, timeout: timeout).retrieve() }
            let deadline = ContinuousClock.now.advanced(by: .seconds(5))
            // The shell creates the marker before printf writes the PID: wait for content.
            var written: Int32?
            while written == nil, ContinuousClock.now < deadline {
                written = (try? String(contentsOf: marker, encoding: .utf8)).flatMap { Int32($0) }
                if written == nil { try await Task.sleep(for: .milliseconds(5)) }
            }
            let pid = try #require(written)
            if cancel {
                task.cancel()
                await #expect(throws: CancellationError.self) { try await task.value }
            } else { await #expect(throws: CredentialFailure.timedOut) { try await task.value } }
            #expect(Darwin.kill(pid, 0) == -1); #expect(errno == ESRCH)
        }
    }
}
