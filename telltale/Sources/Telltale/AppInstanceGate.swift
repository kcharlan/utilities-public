// Port: anker_charge_monitor/Sources/PrimeMonitor/AppInstanceGate.swift, AppInstanceGate and AppInstanceLease, 4f965e8.
// Adaptation: the composition root passes `TelltalePaths.appLock`; the collector (`--collect`)
// takes no gate, since it runs beside the app.
import Foundation
import Darwin

enum AppInstanceGateError: Error, Equatable { case alreadyRunning }
@MainActor final class AppInstanceLease {
    private var relinquish: (@MainActor () -> Void)?
    init(release: @escaping @MainActor () -> Void) { relinquish = release }
    func release() { let action = relinquish; relinquish = nil; action?() }
}
@MainActor enum AppInstanceGate {
    static func acquire(at path: URL) throws -> AppInstanceLease {
        let directory = path.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let fd = open(path.path(percentEncoded: false), O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        guard fchmod(fd, 0o600) == 0 else { let code = errno; close(fd); throw POSIXError(POSIXErrorCode(rawValue: code) ?? .EIO) }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            let code = errno; close(fd)
            if code == EWOULDBLOCK { throw AppInstanceGateError.alreadyRunning }
            throw POSIXError(POSIXErrorCode(rawValue: code) ?? .EIO)
        }
        return AppInstanceLease { _ = flock(fd, LOCK_UN); close(fd) }
    }
}
