import Foundation

public enum LineReader {
    /// Returns the offset after the last complete line. Read errors propagate to the caller.
    public static func completeLines(of url: URL, from offset: Int, _ body: (Data) -> Void) throws -> Int {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let size = try handle.seekToEnd()
        var consumed = UInt64(exactly: offset).map { $0 <= size } == true ? offset : 0
        try handle.seek(toOffset: UInt64(consumed))
        var buffer = Data()
        var search = buffer.startIndex
        while let chunk = try handle.read(upToCount: 1 << 20), !chunk.isEmpty {
            buffer.append(chunk)
            var lineStart = buffer.startIndex
            while let newline = buffer[search...].firstIndex(of: 0x0A) {
                body(buffer[lineStart..<newline])
                consumed += newline - lineStart + 1
                lineStart = newline + 1
                search = lineStart
            }
            // Bytes up to endIndex have been searched, including any unfinished line.
            search = buffer.endIndex
            let searchedRemainder = search - lineStart
            buffer.removeSubrange(buffer.startIndex..<lineStart)
            // Data can retain nonzero indices after removal; rebase against its actual start.
            search = buffer.startIndex + searchedRemainder
        }
        return consumed
    }
}
