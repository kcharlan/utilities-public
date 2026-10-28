import Foundation

/// Builds valid zstd frames out of raw (stored) blocks, so tests control exact sizes without
/// a compressor. Output is a real frame: magic, a 128 KiB window, raw blocks, no checksum.
public enum StoredZstdFrame {
    /// Largest block a frame with the 128 KiB window used here may carry.
    public static let maxBlockSize = 128 * 1024

    /// One frame holding `data` in raw blocks of at most `blockSize` bytes (`1...maxBlockSize`).
    /// Empty `data` produces a frame with one empty last block.
    public static func encode(_ data: Data, blockSize: Int) -> Data {
        precondition((1...maxBlockSize).contains(blockSize), "blockSize must be 1...\(maxBlockSize)")
        var frame = Data([0x28, 0xB5, 0x2F, 0xFD])  // magic 0xFD2FB528, little endian
        frame.append(0x00)  // descriptor: no content size, no checksum, no dictionary
        frame.append(0x38)  // window descriptor: exponent 7 over 1 KiB = 128 KiB
        var start = data.startIndex
        repeat {
            let end = min(start + blockSize, data.endIndex)
            let size = end - start
            let isLast = end == data.endIndex
            // Block header: bit 0 last, bits 1-2 type (0 = raw), bits 3-23 size.
            let header = UInt32(size) << 3 | (isLast ? 1 : 0)
            frame.append(contentsOf: [UInt8(header & 0xFF), UInt8((header >> 8) & 0xFF), UInt8((header >> 16) & 0xFF)])
            frame.append(data[start..<end])
            start = end
        } while start < data.endIndex
        return frame
    }
}
