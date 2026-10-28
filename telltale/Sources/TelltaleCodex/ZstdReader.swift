import CZstd
import Foundation

/// Why a compressed rollout could not be read.
public enum ZstdError: Error, Equatable, Sendable {
    /// The file holds fewer bytes than discovery recorded, or ends inside a frame.
    case truncated
    /// The decoder rejected the data (bad magic, damaged block, unsupported parameters).
    case corrupt(String)
    /// The file could not be opened or read, or the decoder could not allocate.
    case io(String)
}

/// Streams the lines of a Codex `.jsonl.zst` rollout without holding the decompressed file.
///
/// Both lessons from `colophon/docs/LESSONS_LEARNED.md` apply:
/// - A zero result from `ZSTD_decompressStream` means the frame is complete and flushed. At the
///   recorded end of the file the loop stops on it even when the output buffer is exactly full;
///   another decode with empty input would start waiting for a new frame and misreport a valid
///   file as truncated.
/// - Running out of bytes before the recorded size is unreadable even when the last decoded
///   frame was complete, because a file that shrank at a frame boundary would silently
///   undercount. The read boundary is checked on its own, not through the decoder's state.
public enum ZstdReader {
    /// Size of the decompression output buffer. Tests build frames that expand to exactly this
    /// many bytes (and multiples of it) to pin the end-of-frame handling.
    public static let outputBufferSize = 65_536
    /// Size of each read from the file. It exceeds `3 * outputBufferSize`, so a small frame is
    /// decoded from one read and its last decode call can fill the output buffer exactly.
    public static let inputBufferSize = 262_144

    /// Calls `body` with each line of the decompressed file, in order, without its newline.
    /// A final line without a newline is yielded too, because compressed rollouts are complete.
    ///
    /// - Parameters:
    ///   - file: the `.jsonl.zst` file.
    ///   - expectedSize: the size discovery recorded. Exactly that many bytes are read; bytes
    ///     appended later are ignored, and a shorter file throws `ZstdError.truncated`.
    ///   - startingAfterLine: lines numbered 1 through this value are skipped. Yielded lines keep
    ///     their original, 1-based numbers.
    ///   - body: receives `(lineNumber, line)`. An error it throws ends the read and propagates.
    public static func lines(
        of file: URL,
        expectedSize: Int,
        startingAfterLine: Int = 0,
        _ body: (_ lineNumber: Int, _ line: Data) throws -> Void
    ) throws {
        guard expectedSize >= 0 else { throw ZstdError.io("negative expected size") }
        let descriptor = open(file.path, O_RDONLY)
        guard descriptor >= 0 else {
            throw ZstdError.io("cannot open \(file.lastPathComponent): \(String(cString: strerror(errno)))")
        }
        defer { close(descriptor) }
        guard expectedSize > 0 else { return }  // Created but not yet written: no frames.

        guard let decoder = ZSTD_createDCtx() else { throw ZstdError.io("zstd decoder allocation failed") }
        defer { ZSTD_freeDCtx(decoder) }
        // Codex writes single-segment frames whose window equals the log size, so the default
        // 128 MiB window limit would reject large logs. Allow the decoder's maximum.
        let bounds = ZSTD_dParam_getBounds(ZSTD_d_windowLogMax)
        if ZSTD_isError(bounds.error) != 0 { throw failure(bounds.error, "setup") }
        let configured = ZSTD_DCtx_setParameter(decoder, ZSTD_d_windowLogMax, bounds.upperBound)
        if ZSTD_isError(configured) != 0 { throw failure(configured, "setup") }

        var splitter = LineSplitter(startingAfterLine: startingAfterLine)
        var input = [UInt8](repeating: 0, count: inputBufferSize)
        var output = [UInt8](repeating: 0, count: outputBufferSize)
        var inputSize = 0
        var inputPosition = 0
        var offset = 0
        var remaining = 1  // Nonzero until the decoder ends a frame and flushes it.

        while true {
            if inputPosition == inputSize && offset < expectedSize {
                let request = min(inputBufferSize, expectedSize - offset)
                let count = input.withUnsafeMutableBytes { pread(descriptor, $0.baseAddress, request, off_t(offset)) }
                if count < 0 { throw ZstdError.io("read failed: \(String(cString: strerror(errno)))") }
                if count == 0 { throw ZstdError.truncated }  // The file shrank after discovery.
                offset += count
                inputSize = count
                inputPosition = 0
            }
            var produced = 0
            let result: Int = input.withUnsafeBytes { inputBytes in
                output.withUnsafeMutableBytes { outputBytes in
                    var inBuffer = ZSTD_inBuffer(src: inputBytes.baseAddress, size: inputSize, pos: inputPosition)
                    var outBuffer = ZSTD_outBuffer(dst: outputBytes.baseAddress, size: outputBufferSize, pos: 0)
                    let status = ZSTD_decompressStream(decoder, &outBuffer, &inBuffer)
                    inputPosition = inBuffer.pos
                    produced = outBuffer.pos
                    return status
                }
            }
            if ZSTD_isError(result) != 0 { throw failure(result, "decode") }
            remaining = result
            if produced > 0 {
                try output.withUnsafeBytes { try splitter.feed(UnsafeRawBufferPointer(rebasing: $0[0..<produced]), body) }
            }
            // A completed frame is drained even when it exactly fills the output buffer.
            if inputPosition == inputSize && offset >= expectedSize && (remaining == 0 || produced < outputBufferSize) {
                break
            }
        }
        if remaining != 0 { throw ZstdError.truncated }  // The data ends inside a frame.
        try splitter.finish(body)
    }

    private static func failure(_ code: Int, _ step: String) -> ZstdError {
        if ZSTD_getErrorCode(code) == ZSTD_error_memory_allocation {
            return .io("zstd \(step) allocation failed")
        }
        return .corrupt("zstd \(step) failed: \(String(cString: ZSTD_getErrorName(code)))")
    }
}

/// Splits decoded bytes into numbered lines. Lines at or before `startingAfterLine` are counted
/// but never buffered or yielded.
private struct LineSplitter {
    let startingAfterLine: Int
    private var pending = Data()
    private var completedLines = 0
    private var hasPartialLine = false

    init(startingAfterLine: Int) {
        self.startingAfterLine = startingAfterLine
    }

    mutating func feed(_ bytes: UnsafeRawBufferPointer, _ body: (Int, Data) throws -> Void) throws {
        guard let base = bytes.baseAddress else { return }
        var start = 0
        while start < bytes.count {
            let rest = bytes.count - start
            if let found = memchr(base + start, 0x0A, rest) {
                let length = found - UnsafeMutableRawPointer(mutating: base + start)
                try complete(UnsafeRawBufferPointer(start: base + start, count: length), body)
                start += length + 1
            } else {
                // The rest of this chunk starts, or continues, a line that is not finished yet.
                hasPartialLine = true
                if completedLines >= startingAfterLine {
                    pending.append(UnsafeBufferPointer(start: (base + start).assumingMemoryBound(to: UInt8.self), count: rest))
                }
                return
            }
        }
    }

    /// Yields a final line that has no newline.
    mutating func finish(_ body: (Int, Data) throws -> Void) throws {
        guard hasPartialLine else { return }
        try complete(UnsafeRawBufferPointer(start: nil, count: 0), body)
    }

    private mutating func complete(_ tail: UnsafeRawBufferPointer, _ body: (Int, Data) throws -> Void) throws {
        completedLines += 1
        hasPartialLine = false
        defer { pending.removeAll(keepingCapacity: true) }
        guard completedLines > startingAfterLine else { return }
        pending.append(contentsOf: tail)
        try body(completedLines, pending)
    }
}
