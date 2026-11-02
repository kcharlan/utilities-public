import Foundation
import Testing
import TelltaleCore
import TelltaleTestSupport

@Suite struct LineReaderLimitsTests {
    @Test func rejectsUnboundedPlainLine() throws {
        try withScratchDirectory { directory in
            let file = directory.appending(path: "synthetic.jsonl")
            try Data(repeating: 120, count: 16 * 1024 * 1024 + 1).write(to: file)
            #expect(throws: (any Error).self) { try LineReader.completeLines(of: file, from: 0) { _ in } }
        }
    }
}
