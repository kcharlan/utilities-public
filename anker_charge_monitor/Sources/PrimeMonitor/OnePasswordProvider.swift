import Foundation
import Darwin
import PrimeMonitorCore

struct OnePasswordConfiguration: Codable, Equatable, Sendable {
    var item: String
    var vault: String?
    var country: String
    var selection: CredentialSelection {
        var values = ["item": item, "country": country]
        if let vault, !vault.isEmpty { values["vault"] = vault }
        return .init(provider: "onePassword", settings: values)
    }
    init(item: String, vault: String?, country: String) {
        self.item = item; self.vault = vault; self.country = country
    }
    init?(selection: CredentialSelection) {
        guard selection.provider == "onePassword", let item = selection.settings["item"], let country = selection.settings["country"] else { return nil }
        self.init(item: item, vault: selection.settings["vault"], country: country)
    }
}

/// The only component that knows CLI arguments and 1Password field JSON.
struct OnePasswordProvider: CredentialProvider {
    let configuration: OnePasswordConfiguration
    let executable: URL?
    let timeout: TimeInterval
    init(configuration: OnePasswordConfiguration, executable: URL? = nil, timeout: TimeInterval = 20) {
        self.configuration = configuration; self.timeout = timeout
        self.executable = executable ?? ["/opt/homebrew/bin/op", "/usr/local/bin/op"]
            .first(where: { FileManager.default.isExecutableFile(atPath: $0) }).map { URL(filePath: $0) }
    }
    func retrieve() async throws -> AnkerCredentials {
        guard let executable, FileManager.default.isExecutableFile(atPath: executable.path(percentEncoded: false)) else { throw CredentialFailure.missingCLI }
        guard !configuration.item.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !configuration.country.isEmpty else { throw CredentialFailure.malformed }
        var arguments = ["--cache=false", "item", "get", "--fields", "label=username,label=password", "--format", "json", "--reveal"]
        if let vault = configuration.vault, !vault.isEmpty { arguments += ["--vault", vault] }
        arguments += ["--", configuration.item]
        let bytes: Data
        do { bytes = try await CredentialProcess.read(executable: executable, arguments: arguments, timeout: timeout) }
        catch is CancellationError { throw CancellationError() }
        catch let failure as CredentialFailure { throw failure }
        catch { throw CredentialFailure.unavailable }
        struct Field: Decodable { let id: String?; let purpose: String?; let label: String?; let value: String? }
        guard String(data: bytes, encoding: .utf8) != nil,
              let fields = try? JSONDecoder().decode([Field].self, from: bytes) else { throw CredentialFailure.malformed }
        var username: String?, password: String?
        for field in fields {
            let keys = [field.id, field.purpose, field.label].compactMap { $0?.lowercased() }
            let user = keys.contains("username"), pass = keys.contains("password")
            guard !(user && pass) else { throw CredentialFailure.malformed }
            if user { guard username == nil, let value = field.value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw CredentialFailure.malformed }; username = value }
            if pass { guard password == nil, let value = field.value, !value.isEmpty else { throw CredentialFailure.malformed }; password = value }
        }
        guard let username, let password else { throw CredentialFailure.malformed }
        return .init(email: username, password: password, country: configuration.country)
    }
}

/// One worker owns the process and both nonblocking readers until it has reaped
/// the child. Cancellation only signals that worker; no detached reader survives.
private enum CredentialProcess {
    private final class Cancellation: @unchecked Sendable {
        private let lock = NSLock()
        private var cancelled = false
        func cancel() { lock.withLock { cancelled = true } }
        var isCancelled: Bool { lock.withLock { cancelled } }
    }
    static func read(executable: URL, arguments: [String], timeout: TimeInterval) async throws -> Data {
        let cancellation = Cancellation()
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                DispatchQueue.global(qos: .userInitiated).async {
                    do { continuation.resume(returning: try run(executable, arguments, timeout, cancellation)) }
                    catch { continuation.resume(throwing: error) }
                }
            }
        } onCancel: { cancellation.cancel() }
    }
    private static func run(_ executable: URL, _ arguments: [String], _ timeout: TimeInterval, _ cancellation: Cancellation) throws -> Data {
        let process = Process(), stdout = Pipe(), stderr = Pipe()
        process.executableURL = executable; process.arguments = arguments
        // Desktop integration only. Do not inherit OP_SESSION_*, Connect,
        // service-account, alternate config, or account-selection overrides.
        let inherited = ProcessInfo.processInfo.environment
        process.environment = inherited.filter { ["HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "PATH"].contains($0.key) }
            .merging(["OP_BIOMETRIC_UNLOCK_ENABLED": "true"]) { _, value in value }
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = stdout; process.standardError = stderr
        let handles = [stdout.fileHandleForReading, stderr.fileHandleForReading]
        defer { for handle in handles { try? handle.close() }; try? stdout.fileHandleForWriting.close(); try? stderr.fileHandleForWriting.close() }
        for handle in handles {
            let flags = fcntl(handle.fileDescriptor, F_GETFL)
            guard flags >= 0, fcntl(handle.fileDescriptor, F_SETFL, flags | O_NONBLOCK) >= 0 else { throw CredentialFailure.unavailable }
        }
        guard !cancellation.isCancelled else { throw CancellationError() }
        do { try process.run() } catch { throw CredentialFailure.unavailable }
        try? stdout.fileHandleForWriting.close(); try? stderr.fileHandleForWriting.close()
        let deadline = ContinuousClock.now.advanced(by: .seconds(max(0, timeout)))
        var output = Data(), count = 0
        var failure: (any Error)?
        var killedAt: ContinuousClock.Instant?
        repeat {
            if failure == nil {
                if cancellation.isCancelled { failure = CancellationError() }
                else if ContinuousClock.now >= deadline { failure = CredentialFailure.timedOut }
            }
            if failure != nil, process.isRunning {
                if killedAt == nil { process.terminate(); killedAt = .now }
                else if ContinuousClock.now >= killedAt!.advanced(by: .milliseconds(200)) { _ = Darwin.kill(process.processIdentifier, SIGKILL) }
            }
            for (index, handle) in handles.enumerated() {
                do {
                    if let bytes = try availableBytes(handle), !bytes.isEmpty {
                        count += bytes.count
                        if count > 131072 { failure = failure ?? CredentialFailure.outputLimit }
                        else if index == 0 { output.append(bytes) }
                    }
                } catch {
                    failure = failure ?? CredentialFailure.unavailable
                }
            }
            if !process.isRunning { break }
            Thread.sleep(forTimeInterval: 0.005)
        } while true
        process.waitUntilExit()
        if cancellation.isCancelled { throw CancellationError() }
        if let failure { throw failure }
        guard process.terminationStatus == 0 else { throw CredentialFailure.unavailable }
        // Drain remaining buffered output after exit, still under the same bound.
        for (index, handle) in handles.enumerated() {
            while let bytes = try availableBytes(handle), !bytes.isEmpty {
                count += bytes.count
                guard count <= 131072 else { throw CredentialFailure.outputLimit }
                if index == 0 { output.append(bytes) }
            }
        }
        return output
    }
    private static func availableBytes(_ handle: FileHandle) throws -> Data? {
        // Foundation's filling read(upToCount:) can consume a fragment before
        // throwing EAGAIN. POSIX read preserves the actual partial byte count.
        var buffer = [UInt8](repeating: 0, count: 8192)
        let count = buffer.withUnsafeMutableBytes { Darwin.read(handle.fileDescriptor, $0.baseAddress, $0.count) }
        if count > 0 { return Data(buffer.prefix(count)) }
        if count == 0 || errno == EAGAIN || errno == EWOULDBLOCK { return nil }
        if errno == EINTR { return nil }
        throw CredentialFailure.unavailable
    }
}
