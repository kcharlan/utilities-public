import Foundation

/// One session's rollout file, as discovery found it.
public struct RolloutFile: Sendable, Equatable, Hashable {
    public var url: URL
    /// The UUID in the filename (spec section 6.1, Identity and resume).
    public var sessionID: String
    /// True for `.jsonl.zst`.
    public var compressed: Bool
    public var size: Int
    public var modified: Date

    public init(url: URL, sessionID: String, compressed: Bool, size: Int, modified: Date) {
        self.url = url
        self.sessionID = sessionID
        self.compressed = compressed
        self.size = size
        self.modified = modified
    }
}

/// Finds Codex rollouts (spec section 6.1, Files):
/// `sessions/YYYY/MM/DD/rollout-*.jsonl[.zst]` and `archived_sessions/rollout-*.jsonl[.zst]`.
public enum RolloutDiscovery {
    /// One file per session, sorted by path. When a session has both a plain and a compressed
    /// file, the plain one wins: Codex may still be writing the compressed copy (plan call).
    /// Missing or unreadable directories contribute nothing.
    public static func files(codexHome: URL) -> [RolloutFile] {
        var directories: [URL] = []
        let sessions = codexHome.appending(path: "sessions", directoryHint: .isDirectory)
        for year in subdirectories(of: sessions) {
            for month in subdirectories(of: year) {
                directories += subdirectories(of: month)
            }
        }
        directories.append(codexHome.appending(path: "archived_sessions", directoryHint: .isDirectory))

        var chosen: [String: RolloutFile] = [:]
        for directory in directories {
            for file in rollouts(in: directory) {
                if let existing = chosen[file.sessionID], !prefer(file, over: existing) { continue }
                chosen[file.sessionID] = file
            }
        }
        return chosen.values.sorted { $0.url.path < $1.url.path }
    }

    private static let plainSuffix = ".jsonl"
    private static let compressedSuffix = ".jsonl.zst"
    private static let uuidLength = 36

    /// Plain beats compressed; between two of the same kind, the larger has more of the session.
    private static func prefer(_ candidate: RolloutFile, over existing: RolloutFile) -> Bool {
        if candidate.compressed != existing.compressed { return !candidate.compressed }
        return candidate.size > existing.size
    }

    private static func contents(of directory: URL) -> [URL] {
        (try? FileManager.default.contentsOfDirectory(
            at: directory, includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey, .fileSizeKey, .contentModificationDateKey],
            options: [.skipsHiddenFiles])) ?? []
    }

    private static func subdirectories(of directory: URL) -> [URL] {
        contents(of: directory).filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }
    }

    private static func rollouts(in directory: URL) -> [RolloutFile] {
        contents(of: directory).compactMap { url in
            let name = url.lastPathComponent
            guard name.hasPrefix("rollout-") else { return nil }
            let compressed = name.hasSuffix(compressedSuffix)
            guard compressed || name.hasSuffix(plainSuffix) else { return nil }
            let stem = name.dropLast(compressed ? compressedSuffix.count : plainSuffix.count)
            guard stem.count >= "rollout-".count + uuidLength else { return nil }
            let sessionID = String(stem.suffix(uuidLength))
            guard UUID(uuidString: sessionID) != nil else { return nil }
            guard let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey, .contentModificationDateKey]),
                values.isRegularFile == true, let size = values.fileSize, let modified = values.contentModificationDate
            else { return nil }
            return RolloutFile(url: url, sessionID: sessionID, compressed: compressed, size: size, modified: modified)
        }
    }
}
