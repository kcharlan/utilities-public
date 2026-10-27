import Foundation
import Testing
import TelltaleCodex
import TelltaleTestSupport

@Suite struct ZstdReaderTests {
    // MARK: Helpers

    /// A private scratch directory, removed with `cleanup()`.
    final class Scratch {
        let directory: URL

        init() throws {
            directory = FileManager.default.temporaryDirectory
                .appending(path: "telltale-zstd-tests-\(UUID().uuidString)", directoryHint: .isDirectory)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        }

        func write(_ data: Data, named name: String = "rollout.jsonl.zst") throws -> URL {
            let url = directory.appending(path: name)
            try data.write(to: url)
            return url
        }

        func cleanup() {
            try? FileManager.default.removeItem(at: directory)
        }
    }

    static func fixture(_ name: String) throws -> URL {
        let url = Bundle.module.resourceURL?.appending(path: "Fixtures/compressed/\(name)")
        let resolved = try #require(url)
        #expect(FileManager.default.fileExists(atPath: resolved.path))
        return resolved
    }

    static func collect(_ file: URL, expectedSize: Int? = nil, startingAfterLine: Int = 0) throws -> [(Int, Data)] {
        let size = try expectedSize ?? Data(contentsOf: file).count
        var seen: [(Int, Data)] = []
        try ZstdReader.lines(of: file, expectedSize: size, startingAfterLine: startingAfterLine) { number, line in
            seen.append((number, line))
        }
        return seen
    }

    static func splitLines(_ data: Data) -> [Data] {
        var lines = data.split(separator: 0x0A, omittingEmptySubsequences: false).map { Data($0) }
        if lines.last?.isEmpty == true { lines.removeLast() }
        return lines
    }

    /// `count` distinct lines of exactly `width` bytes each, newline included.
    static func numberedLines(count: Int, width: Int) -> Data {
        var data = Data()
        for index in 0..<count {
            var line = Array("line \(index) ".utf8)
            while line.count < width - 1 { line.append(UInt8(ascii: "x")) }
            line.append(0x0A)
            data.append(contentsOf: line)
        }
        return data
    }

    // MARK: Tests

    @Test func readsRealCompressedFixture() throws {
        let plain = try Data(contentsOf: Self.fixture("synthetic_rollout.jsonl"))
        let expected = Self.splitLines(plain)
        #expect(expected.count == 13)
        let seen = try Self.collect(Self.fixture("synthetic_rollout.jsonl.zst"))
        #expect(seen.map(\.1) == expected)
        #expect(seen.map(\.0) == Array(1...13))
    }

    @Test func readsMultiFrameFile() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let first = Self.numberedLines(count: 40, width: 100)
        let second = Self.numberedLines(count: 25, width: 77)
        let third = Data("tail in third frame\n".utf8)
        let file = try scratch.write(
            StoredZstdFrame.encode(first, blockSize: 1000)
                + StoredZstdFrame.encode(second, blockSize: 4096)
                + StoredZstdFrame.encode(third, blockSize: 5))
        let seen = try Self.collect(file)
        #expect(seen.map(\.1) == Self.splitLines(first + second + third))
        #expect(seen.map(\.0) == Array(1...66))
    }

    /// The Colophon end-of-frame regression: a frame whose output exactly fills the output
    /// buffer (once, and a whole number of times) is complete, not truncated.
    @Test(arguments: [1, 2, 3])
    func exactOutputBufferSizedExpansionIsNotTruncated(multiple: Int) throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let total = ZstdReader.outputBufferSize * multiple
        let content = Self.numberedLines(count: total / 64, width: 64)
        #expect(content.count == total)
        let file = try scratch.write(StoredZstdFrame.encode(content, blockSize: StoredZstdFrame.maxBlockSize))
        let seen = try Self.collect(file)
        #expect(seen.map(\.1) == Self.splitLines(content))

        // The same boundary when the frame is followed by another frame.
        let followed = try scratch.write(
            StoredZstdFrame.encode(content, blockSize: 4096) + StoredZstdFrame.encode(Data("next\n".utf8), blockSize: 16),
            named: "followed.jsonl.zst")
        let seenFollowed = try Self.collect(followed)
        #expect(seenFollowed.last?.1 == Data("next".utf8))
        #expect(seenFollowed.count == total / 64 + 1)
    }

    @Test func truncatedFrameThrowsTruncated() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let content = Self.numberedLines(count: 200, width: 100)
        let whole = StoredZstdFrame.encode(content, blockSize: 4096)
        for cut in [whole.count - 1, whole.count / 2, 8] {
            let file = try scratch.write(whole.prefix(cut), named: "cut-\(cut).jsonl.zst")
            #expect(throws: ZstdError.truncated) {
                try ZstdReader.lines(of: file, expectedSize: cut) { _, _ in }
            }
        }
    }

    @Test func shrinkAfterDiscoveryThrowsTruncated() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let first = StoredZstdFrame.encode(Self.numberedLines(count: 10, width: 50), blockSize: 100)
        let second = StoredZstdFrame.encode(Self.numberedLines(count: 10, width: 60), blockSize: 100)
        let recordedSize = first.count + second.count
        // The file shrinks to exactly the first frame: a complete, valid prefix.
        let file = try scratch.write(first)
        #expect(throws: ZstdError.truncated) {
            try ZstdReader.lines(of: file, expectedSize: recordedSize) { _, _ in }
        }
        // With the size it really has, the same file is readable.
        let seen = try Self.collect(file, expectedSize: first.count)
        #expect(seen.count == 10)
    }

    @Test func fileGrowingAfterDiscoveryIsReadOnlyToRecordedSize() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let first = StoredZstdFrame.encode(Data("one\ntwo\n".utf8), blockSize: 100)
        let second = StoredZstdFrame.encode(Data("three\n".utf8), blockSize: 100)
        let file = try scratch.write(first + second)
        let seen = try Self.collect(file, expectedSize: first.count)
        #expect(seen.map(\.1) == [Data("one".utf8), Data("two".utf8)])
    }

    @Test func corruptMagicThrowsCorrupt() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        var bytes = StoredZstdFrame.encode(Data("hello\n".utf8), blockSize: 16)
        bytes[0] = 0x00
        let file = try scratch.write(bytes)
        do {
            try ZstdReader.lines(of: file, expectedSize: bytes.count) { _, _ in }
            Issue.record("expected a corrupt error")
        } catch let error as ZstdError {
            guard case .corrupt = error else {
                Issue.record("expected .corrupt, got \(error)")
                return
            }
        }
    }

    @Test func startingAfterLineSkipsLines() throws {
        let file = try Self.fixture("synthetic_rollout.jsonl.zst")
        let plain = Self.splitLines(try Data(contentsOf: Self.fixture("synthetic_rollout.jsonl")))
        let seen = try Self.collect(file, startingAfterLine: 10)
        #expect(seen.map(\.0) == [11, 12, 13])
        #expect(seen.map(\.1) == Array(plain[10...]))
        #expect(try Self.collect(file, startingAfterLine: 13).isEmpty)
        #expect(try Self.collect(file, startingAfterLine: 99).isEmpty)
    }

    @Test func finalLineWithoutNewlineIsYielded() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let content = Data("first\nsecond\nno newline at the end".utf8)
        let file = try scratch.write(StoredZstdFrame.encode(content, blockSize: 7))
        let seen = try Self.collect(file)
        #expect(seen.map(\.1) == [Data("first".utf8), Data("second".utf8), Data("no newline at the end".utf8)])
        #expect(seen.map(\.0) == [1, 2, 3])
    }

    @Test func emptyLinesKeepTheirNumbers() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let file = try scratch.write(StoredZstdFrame.encode(Data("a\n\nb\n".utf8), blockSize: 2))
        let seen = try Self.collect(file)
        #expect(seen.map(\.0) == [1, 2, 3])
        #expect(seen.map(\.1) == [Data("a".utf8), Data(), Data("b".utf8)])
    }

    @Test func emptyAndZeroSizedInputsYieldNoLines() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let emptyFrame = try scratch.write(StoredZstdFrame.encode(Data(), blockSize: 16))
        #expect(try Self.collect(emptyFrame).isEmpty)
        let zeroBytes = try scratch.write(Data(), named: "zero.jsonl.zst")
        #expect(try Self.collect(zeroBytes, expectedSize: 0).isEmpty)
    }

    @Test func missingFileThrowsIO() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let missing = scratch.directory.appending(path: "missing.jsonl.zst")
        do {
            try ZstdReader.lines(of: missing, expectedSize: 10) { _, _ in }
            Issue.record("expected an I/O error")
        } catch let error as ZstdError {
            guard case .io = error else {
                Issue.record("expected .io, got \(error)")
                return
            }
        }
    }

    @Test func bodyErrorsPropagate() throws {
        struct Stop: Error {}
        let file = try Self.fixture("synthetic_rollout.jsonl.zst")
        let size = try Data(contentsOf: file).count
        var calls = 0
        #expect(throws: Stop.self) {
            try ZstdReader.lines(of: file, expectedSize: size) { _, _ in
                calls += 1
                if calls == 3 { throw Stop() }
            }
        }
        #expect(calls == 3)
    }
}
