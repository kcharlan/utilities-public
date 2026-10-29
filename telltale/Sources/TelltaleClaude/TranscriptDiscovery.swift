import Foundation
import CryptoKit

struct TranscriptFile {
    var url: URL
    var key: String
    var rootIndex: Int
    var sessionID: String
    var subagent: Bool
    var inode: UInt64
    var size: Int
    var modified: Date
}

enum TranscriptDiscovery {
    static func hasRecentFilesOutsideLayout(roots: [URL], now: Date) -> Bool {
        for root in roots {
            guard let enumerator = FileManager.default.enumerator(atPath: root.appending(path: "projects").path) else { continue }
            for case let relative as String in enumerator {
                let url = root.appending(path: "projects").appending(path: relative)
                guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
                      attrs[.type] as? FileAttributeType == .typeRegular,
                      let modified = attrs[.modificationDate] as? Date else { continue }
                if now.timeIntervalSince(modified) < 86400 { return true }
            }
        }
        return false
    }
    static func files(roots: [URL]) -> [TranscriptFile] {
        var found: [TranscriptFile] = []
        for (index, root) in roots.enumerated() {
            let projects = root.appending(path: "projects", directoryHint: .isDirectory)
            guard let enumerator = FileManager.default.enumerator(atPath: projects.path) else { continue }
            for case let relative as String in enumerator {
                let url = projects.appending(path: relative)
                let parts = relative.split(separator: "/").map(String.init)
                let main = parts.count == 2 && url.pathExtension == "jsonl"
                let agent = parts.count == 4 && parts[2] == "subagents" && parts[3].hasPrefix("agent-") && url.pathExtension == "jsonl"
                guard main || agent, let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
                      attrs[.type] as? FileAttributeType == .typeRegular,
                      let inode = (attrs[.systemFileNumber] as? NSNumber)?.uint64Value,
                      let size = (attrs[.size] as? NSNumber)?.intValue,
                      let modified = attrs[.modificationDate] as? Date else { continue }
                let stem = url.deletingPathExtension().lastPathComponent
                // Retain root separation without persisting the project path in the cursor.
                found.append(TranscriptFile(url: url, key: "\(index)/" + SHA256.hash(data: Data(relative.utf8)).map { String(format: "%02x", $0) }.joined(), rootIndex: index,
                    sessionID: agent ? "\(parts[1])/\(stem)" : stem, subagent: agent,
                    inode: inode, size: size, modified: modified))
            }
        }
        return found.sorted { $0.key < $1.key }
    }
}
