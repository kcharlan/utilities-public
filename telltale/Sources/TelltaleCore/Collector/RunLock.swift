import Darwin
import Foundation

public struct RunLockError: Error, Equatable, Sendable, LocalizedError {
    public var operation: String
    public var path: String
    public var code: Int32

    public var errorDescription: String? {
        "Couldn't \(operation) the collector lock \(path): \(String(cString: strerror(code)))"
    }
}

/// Spec section 4's overlap guard: an exclusive, non-blocking `flock` on `collector.lock`, held
/// for the life of this object. The kernel drops the lock if the process dies, so a crashed run
/// never blocks the next one. The file itself stays; only the lock matters.
public final class RunLock: Sendable {
    private let descriptor: Int32

    private init(descriptor: Int32) { self.descriptor = descriptor }

    deinit {
        flock(descriptor, LOCK_UN)
        close(descriptor)
    }

    /// Takes the lock, creating the file (mode 0600) when needed. Returns nil when another run
    /// holds it; throws when the file can't be opened or locked for another reason.
    public static func acquire(_ url: URL) throws -> RunLock? {
        let descriptor = open(url.path, O_RDWR | O_CREAT | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { throw RunLockError(operation: "open", path: url.path, code: errno) }
        while flock(descriptor, LOCK_EX | LOCK_NB) != 0 {
            let code = errno
            if code == EINTR { continue }
            close(descriptor)
            if code == EWOULDBLOCK { return nil }
            throw RunLockError(operation: "lock", path: url.path, code: code)
        }
        return RunLock(descriptor: descriptor)
    }
}
