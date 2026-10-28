import Foundation
import Testing
@testable import PrimeMonitor

@Suite @MainActor struct AppInstanceGateTests {
    @Test func decodedSpecialPathKeepsExclusiveLock() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-" + UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        let directory = root.appending(path: "spaces % café/%2F", directoryHint: .isDirectory)
        let path = directory.appending(path: "instance.lock", directoryHint: .notDirectory)
        let first = try AppInstanceGate.acquire(at: path)
        defer { first.release() }
        #expect(FileManager.default.fileExists(atPath: path.path(percentEncoded: false)))
        #expect(!FileManager.default.fileExists(atPath: path.path(percentEncoded: true)))
        #expect(throws: AppInstanceGateError.alreadyRunning) { try AppInstanceGate.acquire(at: path) }
        first.release()
        let second = try AppInstanceGate.acquire(at: path)
        second.release()
        #expect(try FileManager.default.contentsOfDirectory(atPath: directory.path(percentEncoded: false)) == ["instance.lock"])
        #expect(try FileManager.default.contentsOfDirectory(atPath: root.path(percentEncoded: false)) == ["spaces % café"])
    }
    @Test func concurrentAcquisitionAndRelease() throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-" + UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: directory) }
        let path = directory.appending(path: "instance.lock", directoryHint: .notDirectory)
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
