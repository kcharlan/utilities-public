import Foundation
import Synchronization

/// A finished command's exit status and output.
public struct CommandResult: Sendable, Equatable {
    public var status: Int32
    public var stdout: String
    public var stderr: String

    public init(status: Int32, stdout: String, stderr: String) {
        self.status = status
        self.stdout = stdout
        self.stderr = stderr
    }
}

public enum CommandRunnerError: Error, Equatable, Sendable, LocalizedError {
    case launchFailed(executable: String, reason: String)
    case timedOut(executable: String, seconds: TimeInterval)

    public var errorDescription: String? {
        switch self {
        case .launchFailed(let executable, let reason): "Couldn't run \(executable): \(reason)"
        case .timedOut(let executable, let seconds): "\(executable) didn't finish within \(seconds.formatted()) seconds"
        }
    }
}

/// Runs an external command and waits for it. `LaunchAgentManager` reaches `launchctl` only through
/// this, so tests inject a fake and never run the system's.
public protocol CommandRunner: Sendable {
    func run(_ executable: String, _ arguments: [String]) throws -> CommandResult
}

/// Runs commands with `Process`, reading stdout and stderr as they arrive so a large output can't
/// stall the child. A command still running after `timeout` seconds is terminated (then killed)
/// and reported as `timedOut`.
public struct ProcessRunner: CommandRunner {
    public let timeout: TimeInterval

    public init(timeout: TimeInterval = 10) {
        self.timeout = timeout
    }

    public func run(_ executable: String, _ arguments: [String]) throws -> CommandResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardInput = FileHandle.nullDevice
        let outputs = [Pipe(), Pipe()]
        process.standardOutput = outputs[0]
        process.standardError = outputs[1]
        let exited = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in exited.signal() }
        do {
            try process.run()
        } catch {
            throw CommandRunnerError.launchFailed(executable: executable, reason: error.localizedDescription)
        }

        let collected = CollectedOutput()
        let reads = DispatchGroup()
        for (index, pipe) in outputs.enumerated() {
            let handle = pipe.fileHandleForReading
            DispatchQueue.global().async(group: reads) {
                collected.store(handle.readDataToEndOfFile(), at: index)
            }
        }

        let deadline = DispatchTime.now() + timeout
        guard exited.wait(timeout: deadline) == .success else {
            process.terminate()
            if exited.wait(timeout: .now() + 1) == .timedOut {
                kill(process.processIdentifier, SIGKILL)
                exited.wait()
            }
            _ = reads.wait(timeout: .now() + 1)
            throw CommandRunnerError.timedOut(executable: executable, seconds: timeout)
        }
        // A descendant that inherited the pipes could hold them open after the command exits.
        guard reads.wait(timeout: max(deadline, .now() + 1)) == .success else {
            throw CommandRunnerError.timedOut(executable: executable, seconds: timeout)
        }
        let output = collected.data
        return CommandResult(
            status: process.terminationStatus, stdout: String(decoding: output[0], as: UTF8.self),
            stderr: String(decoding: output[1], as: UTF8.self))
    }
}

/// Stdout and stderr, filled in by the reader threads.
private final class CollectedOutput: Sendable {
    private let state = Mutex([Data(), Data()])
    var data: [Data] { state.withLock { $0 } }
    func store(_ data: Data, at index: Int) { state.withLock { $0[index] = data } }
}
