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

    // MARK: Lines that span decode chunks

    /// Widths that don't divide the output buffer put chunk boundaries in the middle of lines, so
    /// the carry-over of a partial line is exercised, with `startingAfterLine` on both sides of it.
    @Test func linesSpanningOutputChunksAreAssembled() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let width = 1000
        #expect(ZstdReader.outputBufferSize % width != 0)
        let content = Self.numberedLines(count: 330, width: width)  // 330,000 bytes: five-plus chunks.
        let expected = Self.splitLines(content)
        let file = try scratch.write(StoredZstdFrame.encode(content, blockSize: 4096))
        // The first output boundary (byte 65,536) falls inside line 66; the second inside line 132.
        let firstSpanning = ZstdReader.outputBufferSize / width + 1
        #expect(firstSpanning == 66)

        for skip in [0, 1, firstSpanning - 1, firstSpanning, firstSpanning + 1, 131, 132, 133, 329, 330] {
            let seen = try Self.collect(file, startingAfterLine: skip)
            #expect(seen.map(\.0) == Array((skip + 1)..<331), "line numbers after skipping \(skip)")
            #expect(seen.map(\.1) == Array(expected[skip...]), "line contents after skipping \(skip)")
        }
    }

    @Test func oneLineLongerThanSeveralOutputChunksIsAssembled() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let long = Data(repeating: UInt8(ascii: "L"), count: ZstdReader.outputBufferSize * 2 + 4321)
        let content = Data("before\n".utf8) + long + Data("\nafter\n".utf8)
        let file = try scratch.write(StoredZstdFrame.encode(content, blockSize: 30_000))
        let seen = try Self.collect(file)
        #expect(seen.map(\.0) == [1, 2, 3])
        #expect(seen.map(\.1) == [Data("before".utf8), long, Data("after".utf8)])
        // Skipping the long line neither yields it nor disturbs the lines around it.
        let skipped = try Self.collect(file, startingAfterLine: 2)
        #expect(skipped.map(\.0) == [3])
        #expect(skipped.map(\.1) == [Data("after".utf8)])
    }

    // MARK: Inputs larger than one read

    /// About 600 KiB of stored blocks: three reads, with frame data (and a block) split across them.
    static func largeFrame() -> (content: Data, frame: Data) {
        let content = numberedLines(count: 6000, width: 100)
        let frame = StoredZstdFrame.encode(content, blockSize: 100_000)
        return (content, frame)
    }

    @Test func fileLargerThanOneReadIsReadAcrossSeveralReads() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let (content, frame) = Self.largeFrame()
        #expect(frame.count > 2 * ZstdReader.inputBufferSize)
        let file = try scratch.write(frame)
        let seen = try Self.collect(file)
        #expect(seen.map(\.1) == Self.splitLines(content))
        #expect(seen.map(\.0) == Array(1...6000))

        // Several frames, the second starting inside the second read.
        let second = Self.numberedLines(count: 500, width: 90)
        let multi = try scratch.write(
            StoredZstdFrame.encode(Data(content.prefix(200_000)), blockSize: 65_536)
                + frame
                + StoredZstdFrame.encode(second, blockSize: 70_000),
            named: "multi.jsonl.zst")
        let multiSeen = try Self.collect(multi)
        let expectedLines = Self.splitLines(Data(content.prefix(200_000)) + content + second)
        #expect(multiSeen.map(\.1) == expectedLines)
    }

    @Test func truncationBeyondTheFirstReadThrowsTruncated() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let (_, frame) = Self.largeFrame()
        let cut = ZstdReader.inputBufferSize + 40_000
        #expect(cut < frame.count)
        // Recorded size equals the (cut) file: the data ends inside the frame.
        let insideFrame = try scratch.write(frame.prefix(cut), named: "inside.jsonl.zst")
        #expect(throws: ZstdError.truncated) {
            try ZstdReader.lines(of: insideFrame, expectedSize: cut) { _, _ in }
        }
        // Recorded size is the full size but the file was cut after the first read:
        // the second read returns nothing.
        #expect(throws: ZstdError.truncated) {
            try ZstdReader.lines(of: insideFrame, expectedSize: frame.count) { _, _ in }
        }
    }

    @Test func shrinkAtFrameBoundaryBeyondTheFirstReadThrowsTruncated() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let (content, frame) = Self.largeFrame()
        let tail = StoredZstdFrame.encode(Data("tail\n".utf8), blockSize: 16)
        let file = try scratch.write(frame)  // The tail frame vanished after discovery.
        #expect(frame.count > ZstdReader.inputBufferSize)
        #expect(throws: ZstdError.truncated) {
            try ZstdReader.lines(of: file, expectedSize: frame.count + tail.count) { _, _ in }
        }
        // Read at its real size, the same file is complete.
        #expect(try Self.collect(file).count == Self.splitLines(content).count)
    }

    // MARK: Damage after a valid frame

    @Test func corruptSecondFrameThrowsCorrupt() throws {
        let scratch = try Scratch()
        defer { scratch.cleanup() }
        let good = StoredZstdFrame.encode(Self.numberedLines(count: 20, width: 40), blockSize: 100)
        var badMagic = StoredZstdFrame.encode(Data("second\n".utf8), blockSize: 16)
        badMagic[1] = 0x00
        // A block of reserved type 3 inside an otherwise valid second frame.
        var badBlock = StoredZstdFrame.encode(Data("second\n".utf8), blockSize: 16)
        badBlock[6] |= 0b110  // block header low byte: type bits 1-2 = 3
        for damaged in [badMagic, badBlock] {
            let bytes = good + damaged
            let file = try scratch.write(bytes, named: "damaged-\(damaged.hashValue).jsonl.zst")
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
    }
}
