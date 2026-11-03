import Foundation
import Testing
import TelltaleCore
import TelltaleTestSupport

@Suite(.serialized) struct LineReaderLargeLineTests {
    @Test func readsPlainLineLargerThanFormerCap() throws {
        try withScratchDirectory { directory in
            let file = directory.appending(path: "synthetic.jsonl")
            let large = Data(repeating: 120, count: LargeLogSizes.line)
            let content = large + Data("\nshort\n".utf8)
            try content.write(to: file)
            var seen = [Data]()
            let end = try LineReader.completeLines(of: file, from: 0) { seen.append(Data($0)) }
            #expect(seen == [large, Data("short".utf8)])
            #expect(end == content.count)
        }
    }
    @Test func holdsUnfinishedLargeLine() throws {
        try withScratchDirectory { directory in
            let file = directory.appending(path: "synthetic.jsonl")
            try (Data("prefix\n".utf8) + Data(repeating: 120, count: LargeLogSizes.line)).write(to: file)
            var seen = [Data]()
            let end = try LineReader.completeLines(of: file, from: 7) { seen.append(Data($0)) }
            #expect(seen.isEmpty)
            #expect(end == 7)
        }
    }
    @Test(arguments: [0, 1]) func rebasesSearchAfterConsumedPrefix(alignment: Int) throws {
        try withScratchDirectory { directory in
            let file = directory.appending(path: "synthetic.jsonl")
            let prefix = Data(repeating: 112, count: (1 << 20) - 1 + alignment)
            let large = Data(repeating: 120, count: LargeLogSizes.line)
            let tail = Data("unfinished".utf8)
            let content = prefix + Data([10]) + large + Data("\n\nshort\n".utf8) + tail
            try content.write(to: file)
            var seen = [Data]()
            let end = try LineReader.completeLines(of: file, from: 0) { seen.append(Data($0)) }
            #expect(seen == [prefix, large, Data(), Data("short".utf8)])
            #expect(end == content.count - tail.count)
        }
    }
    @Test func resumesUnfinishedLargeLineFromNonzeroOffset() throws {
        try withScratchDirectory { directory in
            let file = directory.appending(path: "synthetic.jsonl")
            let large = Data(repeating: 120, count: LargeLogSizes.line)
            try (Data("prefix\n".utf8) + large).write(to: file)
            var seen = [Data]()
            let offset = try LineReader.completeLines(of: file, from: 0) { seen.append(Data($0)) }
            #expect(offset == 7)
            #expect(seen == [Data("prefix".utf8)])
            let handle = try FileHandle(forWritingTo: file)
            try handle.seekToEnd()
            try handle.write(contentsOf: Data("\nshort\n".utf8))
            try handle.close()
            seen.removeAll()
            let end = try LineReader.completeLines(of: file, from: offset) { seen.append(Data($0)) }
            #expect(seen == [large, Data("short".utf8)])
            #expect(end == 7 + large.count + 7)
            seen.removeAll()
            #expect(try LineReader.completeLines(of: file, from: end) { seen.append(Data($0)) } == end)
            #expect(seen.isEmpty)
        }
    }
}
