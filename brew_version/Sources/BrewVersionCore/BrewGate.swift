import Darwin
import Foundation

public struct BrewOutput: Sendable {
    public let exitCode: Int32
    public let stdout: Data
    public let stderr: Data
    public let seconds: Double
    public init(exitCode: Int32, stdout: Data, stderr: Data, seconds: Double) {
        self.exitCode = exitCode; self.stdout = stdout; self.stderr = stderr; self.seconds = seconds
    }
}
public protocol BrewRunning: Sendable {
    func run(_ arguments: [String], environment: [String: String], timeout: TimeInterval) async throws -> BrewOutput
}
public struct BrewConfirmation: Sendable {
    public var listings: [PackageName: Listing] = [:]
    public var problem: String?
    public init(listings: [PackageName: Listing] = [:], problem: String? = nil) {
        self.listings = listings; self.problem = problem
    }
}
public protocol BrewConfirming: Sendable {
    var isAvailable: Bool { get }
    func confirm(_ candidates: [Listing]) async -> BrewConfirmation
}
public extension BrewConfirming { var isAvailable: Bool { true } }

public struct BrewGate: BrewConfirming {
    private let runner: any BrewRunning
    private let log: any EventLogging
    private let executable: URL?
    private let apiCacheDirectory: URL?
    public init(runner: any BrewRunning, log: any EventLogging, apiCacheDirectory: URL?) {
        self.runner = runner; self.log = log; self.apiCacheDirectory = apiCacheDirectory; executable = nil
    }
    private init(runner: any BrewRunning, log: any EventLogging, apiCacheDirectory: URL?, executable: URL) {
        self.runner = runner; self.log = log; self.apiCacheDirectory = apiCacheDirectory; self.executable = executable
    }
    public var isAvailable: Bool { executable.map { FileManager.default.isExecutableFile(atPath: $0.path) } ?? true }
    public var executablePath: String? { executable?.path }
    public static func live(prefixes: [HomebrewPrefix], home: URL, log: any EventLogging) -> BrewGate? {
        guard let path = prefixes.map({ $0.root.appendingPathComponent("bin/brew") }).first(where: { FileManager.default.isExecutableFile(atPath: $0.path) }) else { return nil }
        return BrewGate(runner: ProcessBrewRunner(executable: path), log: log,
                        apiCacheDirectory: home.appendingPathComponent("Library/Caches/Homebrew/api"), executable: path)
    }
    public func confirm(_ candidates: [Listing]) async -> BrewConfirmation {
        var result = BrewConfirmation()
        let environment: [String: String] = [:]
        let updateStart = Date()
        do {
            let output = try await runner.run(["update"], environment: environment, timeout: 180)
            log.record("gate.update", updateFields(output, timedOut: false))
            if output.exitCode != 0 { result.problem = message(output.stderr, fallback: "brew update failed.") }
        } catch {
            result.problem = String(error.localizedDescription.prefix(200))
            if case BrewRunnerError.timeout(let output) = error {
                result.problem = message(output.stderr, fallback: "brew timed out.")
                log.record("gate.update", updateFields(output, timedOut: true))
            } else {
                log.record("gate.update", ["ms": .int(milliseconds(Date().timeIntervalSince(updateStart))), "timedOut": .bool(false), "error": .string(result.problem ?? "")])
            }
        }
        for candidate in candidates {
            var env = environment; env["HOMEBREW_NO_AUTO_UPDATE"] = "1"
            let start = Date()
            do {
                let output = try await runner.run(["info", "--json=v2", candidate.kind == .formula ? "--formula" : "--cask", candidate.name.rawValue], environment: env, timeout: 30)
                var fields: [String: LogValue] = ["name": .string(candidate.name.rawValue), "announced": .string(ReleaseID(candidate).displayVersion), "covered": .bool(false), "exit": .int(Int(output.exitCode)), "ms": .int(milliseconds(output.seconds))]
                guard output.exitCode == 0,
                      let json = (try? JSONSerialization.jsonObject(with: output.stdout)) as? [String: Any],
                      let items = json[candidate.kind == .formula ? "formulae" : "casks"] as? [[String: Any]], let first = items.first,
                      let data = try? JSONSerialization.data(withJSONObject: first),
                      let listing = try? Listing.decode(data, kind: candidate.kind, name: candidate.name) else {
                    fields["error"] = .string(message(output.stderr, fallback: "Couldn't read brew info."))
                    log.record("gate.info", fields)
                    if result.problem == nil { result.problem = message(output.stderr, fallback: "Couldn't read brew info.") }
                    continue
                }
                result.listings[candidate.name] = listing
                let covered = brewCovers(listing, announced: candidate)
                fields["brew"] = .string(ReleaseID(listing).displayVersion); fields["covered"] = .bool(covered)
                log.record("gate.info", fields)
                if !covered, result.problem == nil {
                    result.problem = "Homebrew has not listed the announced release yet."
                }
            } catch {
                var fields: [String: LogValue] = ["name": .string(candidate.name.rawValue), "announced": .string(ReleaseID(candidate).displayVersion), "covered": .bool(false), "ms": .int(milliseconds(Date().timeIntervalSince(start))), "error": .string(String(error.localizedDescription.prefix(200)))]
                if case BrewRunnerError.timeout(let output) = error {
                    fields["exit"] = .int(Int(output.exitCode)); fields["ms"] = .int(milliseconds(output.seconds)); fields["timedOut"] = .bool(true)
                    fields["error"] = .string(message(output.stderr, fallback: "brew timed out."))
                }
                if result.problem == nil, case .string(let message) = fields["error"] { result.problem = message }
                log.record("gate.info", fields)
            }
        }
        recordCache()
        return result
    }
    private func milliseconds(_ seconds: Double) -> Int { Int(max(0, seconds) * 1000) }
    private func updateFields(_ output: BrewOutput, timedOut: Bool) -> [String: LogValue] {
        let lines = String(decoding: output.stdout, as: UTF8.self).components(separatedBy: .newlines).filter { !$0.isEmpty }
        return ["exit": .int(Int(output.exitCode)), "ms": .int(milliseconds(output.seconds)), "timedOut": .bool(timedOut), "summary": .string(String((lines.last ?? "").prefix(200))), "error": .string(message(output.stderr, fallback: timedOut ? "brew timed out." : ""))]
    }
    private func recordCache() {
        guard let directory = apiCacheDirectory?.appendingPathComponent("internal"),
              let files = try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.fileSizeKey, .contentModificationDateKey]) else { return }
        for file in files where file.lastPathComponent.hasPrefix("packages.") && file.lastPathComponent.hasSuffix(".jws.json") {
            guard let metadata = try? file.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey]), let size = metadata.fileSize, let modified = metadata.contentModificationDate else { continue }
            var fields: [String: LogValue] = ["file": .string(file.lastPathComponent), "bytes": .int(size), "modified": .string(ISO8601DateFormatter().string(from: modified))]
            if let handle = try? FileHandle(forReadingFrom: URL(fileURLWithPath: file.path + ".etag")) {
                defer { try? handle.close() }
                let data = (try? handle.read(upToCount: 4097)) ?? Data()
                if data.count <= 4096 {
                    fields["etag"] = .string(String(String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines).prefix(200)))
                }
            }
            log.record("gate.cache", fields)
        }
    }
    private func message(_ data: Data, fallback: String) -> String {
        let first = String(decoding: data, as: UTF8.self).components(separatedBy: .newlines).first ?? ""
        return first.isEmpty ? fallback : String(first.prefix(200))
    }
}

public struct ProcessBrewRunner: BrewRunning {
    public let executable: URL
    public init(executable: URL) { self.executable = executable }
    public func run(_ arguments: [String], environment: [String: String], timeout: TimeInterval) async throws -> BrewOutput {
        try await Task.detached { try runSync(arguments, environment: environment, timeout: timeout) }.value
    }
    private func runSync(_ arguments: [String], environment: [String: String], timeout: TimeInterval) throws -> BrewOutput {
        let process = Process(), stdout = Pipe(), stderr = Pipe()
        process.executableURL = executable; process.arguments = arguments
        var env = ProcessInfo.processInfo.environment
        env["HOMEBREW_NO_COLOR"] = "1"; env["HOMEBREW_NO_ENV_HINTS"] = "1"
        env.merge(environment) { _, override in override }
        process.environment = env; process.standardInput = FileHandle.nullDevice
        process.standardOutput = stdout; process.standardError = stderr
        process.currentDirectoryURL = URL(fileURLWithPath: "/")
        let start = Date()
        try process.run()
        let handles = [stdout.fileHandleForReading, stderr.fileHandleForReading]
        defer { handles.forEach { try? $0.close() } }
        for handle in handles { _ = fcntl(handle.fileDescriptor, F_SETFL, fcntl(handle.fileDescriptor, F_GETFL) | O_NONBLOCK) }
        var data = [Data(), Data()]
        var terminatedAt: Date?, timedOut = false
        repeat {
            drain(handles, into: &data)
            if process.isRunning && !timedOut && Date().timeIntervalSince(start) >= timeout {
                timedOut = true; terminatedAt = Date(); process.terminate()
            }
            if process.isRunning, let terminatedAt, Date().timeIntervalSince(terminatedAt) >= 5 { kill(process.processIdentifier, SIGKILL) }
            if process.isRunning { Thread.sleep(forTimeInterval: 0.01) }
        } while process.isRunning
        // A fast process may exit between the last drain and isRunning check.
        // Read only currently available bytes; descendants may retain the pipes.
        drain(handles, into: &data)
        process.waitUntilExit()
        if timedOut { throw BrewRunnerError.timeout(BrewOutput(exitCode: process.terminationStatus, stdout: data[0], stderr: data[1], seconds: Date().timeIntervalSince(start))) }
        return BrewOutput(exitCode: process.terminationStatus, stdout: data[0], stderr: data[1], seconds: Date().timeIntervalSince(start))
    }
    private func drain(_ handles: [FileHandle], into data: inout [Data]) {
        for (index, handle) in handles.enumerated() {
            var buffer = [UInt8](repeating: 0, count: 16384)
            for _ in 0..<32 {
                let count = read(handle.fileDescriptor, &buffer, buffer.count)
                guard count > 0 else { break }
                let keep = min(count, max(0, 256 * 1024 - data[index].count))
                if keep > 0 { data[index].append(contentsOf: buffer.prefix(keep)) }
            }
        }
    }
}
public enum BrewRunnerError: LocalizedError {
    case timeout(BrewOutput)
    public var errorDescription: String? { "brew timed out." }
}
