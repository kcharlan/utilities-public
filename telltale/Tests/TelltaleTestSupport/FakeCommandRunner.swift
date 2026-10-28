import Foundation
import Synchronization
import TelltaleCore

/// A `CommandRunner` that never starts a process: it records each call and answers from the
/// results set per subcommand (the first argument, such as `bootstrap` or `print`). Unscripted
/// subcommands succeed with empty output. Tests use it so they never run the system `launchctl`.
public final class FakeCommandRunner: CommandRunner, Sendable {
    public struct Call: Sendable, Equatable, CustomStringConvertible {
        public let executable: String
        public let arguments: [String]

        public init(executable: String, arguments: [String]) {
            self.executable = executable
            self.arguments = arguments
        }

        public var description: String { ([executable] + arguments).joined(separator: " ") }
    }

    private struct State {
        var calls: [Call] = []
        var results: [String: CommandResult] = [:]
        var failures: [String: any Error] = [:]
        var observer: (@Sendable (Call) -> Void)?
    }

    private let state = Mutex(State())

    public init() {}

    /// Every call so far, in order.
    public var calls: [Call] { state.withLock { $0.calls } }

    /// Answers every later call whose first argument is `subcommand` with `result`.
    public func respond(to subcommand: String, with result: CommandResult) {
        state.withLock { $0.results[subcommand] = result }
    }

    /// Makes every later call whose first argument is `subcommand` throw `error`.
    public func fail(_ subcommand: String, with error: any Error) {
        state.withLock { $0.failures[subcommand] = error }
    }

    /// Runs `observer` at each call, before it is answered (for example, to check a file exists then).
    public func observe(_ observer: @escaping @Sendable (Call) -> Void) {
        state.withLock { $0.observer = observer }
    }

    public func run(_ executable: String, _ arguments: [String]) throws -> CommandResult {
        let call = Call(executable: executable, arguments: arguments)
        let (observer, failure, result) = state.withLock { state in
            state.calls.append(call)
            let key = arguments.first ?? ""
            return (state.observer, state.failures[key], state.results[key])
        }
        observer?(call)
        if let failure { throw failure }
        return result ?? CommandResult(status: 0, stdout: "", stderr: "")
    }
}
