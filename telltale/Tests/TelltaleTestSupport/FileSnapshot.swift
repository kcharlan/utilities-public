import CryptoKit
import Foundation

/// The comparison contract for "Codex's files are not modified" (spec section 6: all reads are
/// read-only): every regular file under a directory except SQLite's `-wal` and `-shm` side
/// files, keyed by its path below the directory, with its size, modification date and a SHA-256
/// of its contents. Two equal snapshots mean no file was added, removed, rewritten or touched.
public enum FileSnapshot {
    public struct Failure: Error, CustomStringConvertible {
        public let description: String
    }

    public static func take(_ directory: URL) throws -> [String: String] {
        guard let enumerator = FileManager.default.enumerator(at: directory, includingPropertiesForKeys: [.isRegularFileKey]) else {
            throw Failure(description: "can't enumerate \(directory.lastPathComponent)")
        }
        var result: [String: String] = [:]
        for case let url as URL in enumerator {
            guard (try url.resourceValues(forKeys: [.isRegularFileKey])).isRegularFile == true else { continue }
            if url.lastPathComponent.hasSuffix("-wal") || url.lastPathComponent.hasSuffix("-shm") { continue }
            let data = try Data(contentsOf: url)
            guard let modified = try url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate else {
                throw Failure(description: "no modification date for \(url.lastPathComponent)")
            }
            let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            result[String(url.path.dropFirst(directory.path.count))] = "\(data.count) \(modified.timeIntervalSinceReferenceDate) \(digest)"
        }
        return result
    }
}
