import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct CollectorLogTests {
    static let at = Date(timeIntervalSince1970: 1_767_225_600)

    @Test func defaultsFollowTheStorageTable() {
        let log = CollectorLog(url: URL(fileURLWithPath: "/nonexistent-synthetic/collector.log"))
        #expect(log.maxBytes == 5 * 1_024 * 1_024)
        #expect(log.keep == 3)
    }

    @Test func rotatesAtMaxBytesKeepingConfiguredCount() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "collector.log")
            let log = CollectorLog(url: url, maxBytes: 200, keep: 2, timeZone: TimeZone(identifier: "UTC")!)
            for number in 1...40 { log.write("synthetic line \(number)", at: Self.at) }

            let files = try FileManager.default.contentsOfDirectory(atPath: directory.path).sorted()
            #expect(files == ["collector.log", "collector.log.1", "collector.log.2"])
            for name in files {
                let size = try #require(try FileManager.default.attributesOfItem(atPath: directory.appending(path: name).path)[.size] as? Int)
                #expect(size <= 200, "\(name) is \(size) bytes")
            }
            let current = try String(contentsOf: url, encoding: .utf8)
            #expect(current.hasSuffix("2026-01-01T00:00:00Z synthetic line 40\n"))
            // The newest archive holds the lines just before the current file's first line.
            let newestArchive = try String(contentsOf: log.archive(1), encoding: .utf8)
            let firstCurrent = try #require(current.split(separator: "\n").first)
            let lastArchived = try #require(newestArchive.split(separator: "\n").last)
            let number = { (line: Substring) in Int(line.split(separator: " ").last!)! }
            #expect(number(lastArchived) + 1 == number(firstCurrent))
        }
    }

    @Test func keepZeroDiscardsTheFullFile() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "collector.log")
            let log = CollectorLog(url: url, maxBytes: 60, keep: 0)
            for number in 1...10 { log.write("synthetic line \(number)", at: Self.at) }
            let files = try FileManager.default.contentsOfDirectory(atPath: directory.path)
            #expect(files == ["collector.log"])
        }
    }

    @Test func writeIntoAMissingDirectoryIsIgnored() {
        let log = CollectorLog(url: URL(fileURLWithPath: "/nonexistent-synthetic/collector.log"))
        log.write("synthetic", at: Self.at)  // Logging never throws or traps.
    }
}
