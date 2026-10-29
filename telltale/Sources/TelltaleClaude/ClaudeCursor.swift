import Foundation

struct ClaudeCursor: Codable {
    var files: [String: FileCursor] = [:]
}
struct FileCursor: Codable {
    var rootIndex: Int
    var offset: Int = 0
    var inode: UInt64 = 0
    var size: Int = 0
    var pendingInput: Date?
    var previousEnd: Date?
    var model: String?
    var sawUsage = false
    var sawAssistant: Bool?
    var sawUser: Bool?
    var sawTimestamp: Bool?
    var sawInvalidCompaction: Bool?
    var version: String?
}
