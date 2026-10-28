import Darwin
import Foundation

/// The collector's log (spec section 4, Storage: `~/Library/Logs/Telltale/collector.log`,
/// rotated at 5 MB, 3 kept). Each line is an ISO 8601 time in `timeZone`, a space and the
/// message. Before a write that would take the file past `maxBytes`, the file becomes
/// `collector.log.1`, older archives shift up, and anything past `collector.log.<keep>` is
/// deleted, so at most `keep` archives exist beside the current file (plan call: "3 kept" counts
/// archives).
///
/// Logging is best effort: a write that fails is dropped, never thrown, so the log can't fail a
/// run. Lines from overlapping processes (a skipped run) append with `O_APPEND`.
public struct CollectorLog: Sendable {
    public static let defaultMaxBytes = 5 * 1_024 * 1_024
    public static let defaultKeep = 3

    public let url: URL
    public let maxBytes: Int
    public let keep: Int
    public let timeZone: TimeZone

    public init(url: URL, maxBytes: Int = CollectorLog.defaultMaxBytes, keep: Int = CollectorLog.defaultKeep, timeZone: TimeZone = .current) {
        self.url = url
        self.maxBytes = maxBytes
        self.keep = max(0, keep)
        self.timeZone = timeZone
    }

    /// `collector.log.<number>`.
    public func archive(_ number: Int) -> URL {
        url.deletingLastPathComponent().appending(path: "\(url.lastPathComponent).\(number)", directoryHint: .notDirectory)
    }

    public func write(_ message: String, at date: Date) {
        let line = Data("\(Date.ISO8601FormatStyle(timeZone: timeZone).format(date)) \(message)\n".utf8)
        if let size = try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int, size > 0, size + line.count > maxBytes {
            rotate()
        }
        let descriptor = open(url.path, O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { return }
        defer { close(descriptor) }
        line.withUnsafeBytes { bytes in
            var offset = 0
            while offset < bytes.count {
                let written = Darwin.write(descriptor, bytes.baseAddress! + offset, bytes.count - offset)
                if written < 0 {
                    if errno == EINTR { continue }
                    return
                }
                offset += written
            }
        }
    }

    private func rotate() {
        let files = FileManager.default
        guard keep > 0 else {
            try? files.removeItem(at: url)
            return
        }
        try? files.removeItem(at: archive(keep))
        for number in stride(from: keep - 1, through: 1, by: -1) {
            try? files.moveItem(at: archive(number), to: archive(number + 1))
        }
        try? files.moveItem(at: url, to: archive(1))
    }
}
