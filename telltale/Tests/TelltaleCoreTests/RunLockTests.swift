import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct RunLockTests {
    @Test func secondAcquireWhileHeldReturnsNil() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "collector.lock")
            let first = try RunLock.acquire(url)
            #expect(first != nil)
            // flock locks belong to the open file description, so a second open in the same process
            // contends exactly as a second collector process would.
            #expect(try RunLock.acquire(url) == nil)
            withExtendedLifetime(first) {}
        }
    }

    @Test func releasedOnDeinit() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "collector.lock")
            var held = try RunLock.acquire(url)
            #expect(held != nil)
            #expect(try RunLock.acquire(url) == nil)
            held = nil
            let again = try RunLock.acquire(url)
            #expect(again != nil)
            withExtendedLifetime((held, again)) {}
        }
    }

    @Test func missingDirectoryThrows() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "absent/collector.lock")
            #expect(throws: RunLockError.self) { _ = try RunLock.acquire(url) }
        }
    }
}
