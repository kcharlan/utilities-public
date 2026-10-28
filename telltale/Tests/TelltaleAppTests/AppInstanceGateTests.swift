// Port: anker_charge_monitor/Tests/PrimeMonitorAppTests/AppInstanceGateTests.swift, AppInstanceGateTests, 4f965e8.
// Adaptation: the scratch directory comes from TelltaleTestSupport; the gate file is named like
// `TelltalePaths.appLock`.
//
// Source tests at 4f965e8 -> destination tests:
// - decodedSpecialPathKeepsExclusiveLock -> decodedSpecialPathKeepsExclusiveLock
// - concurrentAcquisitionAndRelease -> concurrentAcquisitionAndRelease
// Telltale additions: gateUsesTheAppLockPath.
import Foundation
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

@Suite @MainActor struct AppInstanceGateTests {
    @Test func decodedSpecialPathKeepsExclusiveLock() throws {
        try withScratchDirectory { root in
            let directory = root.appending(path: "spaces % café/%2F", directoryHint: .isDirectory)
            let path = directory.appending(path: "app.lock", directoryHint: .notDirectory)
            let first = try AppInstanceGate.acquire(at: path)
            defer { first.release() }
            #expect(FileManager.default.fileExists(atPath: path.path(percentEncoded: false)))
            #expect(!FileManager.default.fileExists(atPath: path.path(percentEncoded: true)))
            #expect(throws: AppInstanceGateError.alreadyRunning) { try AppInstanceGate.acquire(at: path) }
            first.release()
            let second = try AppInstanceGate.acquire(at: path)
            second.release()
            #expect(try FileManager.default.contentsOfDirectory(atPath: directory.path(percentEncoded: false)) == ["app.lock"])
            #expect(try FileManager.default.contentsOfDirectory(atPath: root.path(percentEncoded: false)) == ["spaces % café"])
        }
    }
    @Test func concurrentAcquisitionAndRelease() throws {
        try withScratchDirectory { directory in
            let path = directory.appending(path: "app.lock", directoryHint: .notDirectory)
            let first = try AppInstanceGate.acquire(at: path)
            #expect(throws: AppInstanceGateError.alreadyRunning) { try AppInstanceGate.acquire(at: path) }
            first.release(); first.release()
            #expect(FileManager.default.fileExists(atPath: path.path(percentEncoded: false)))
            let second = try AppInstanceGate.acquire(at: path); second.release()
            let mode = try FileManager.default.attributesOfItem(atPath: path.path(percentEncoded: false))[.posixPermissions] as? Int
            #expect(mode == 0o600)
            #expect(throws: (any Error).self) { try AppInstanceGate.acquire(at: directory) }
            #expect(throws: (any Error).self) { try AppInstanceGate.acquire(at: path.appending(path: "bad", directoryHint: .notDirectory)) }
        }
    }
    @Test func gateUsesTheAppLockPath() throws {
        try withScratchDirectory { directory in
            let paths = TelltalePaths(home: directory.appending(path: "home", directoryHint: .isDirectory))
            let lease = try AppInstanceGate.acquire(at: paths.appLock)
            defer { lease.release() }
            #expect(throws: AppInstanceGateError.alreadyRunning) { try AppInstanceGate.acquire(at: paths.appLock) }
            // The gate makes the support directory private; it never creates the database.
            let mode = try FileManager.default.attributesOfItem(atPath: paths.appSupport.path)[.posixPermissions] as? Int
            #expect(mode == 0o700)
            #expect(!FileManager.default.fileExists(atPath: paths.database.path))
        }
    }
}
