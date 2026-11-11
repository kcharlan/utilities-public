import Foundation

public enum LogValue: Sendable, Equatable, Encodable, ExpressibleByStringLiteral, ExpressibleByIntegerLiteral, ExpressibleByFloatLiteral, ExpressibleByBooleanLiteral, ExpressibleByArrayLiteral {
    case string(String), int(Int), double(Double), bool(Bool), list([String])
    public init(stringLiteral value: String) { self = .string(value) }
    public init(integerLiteral value: Int) { self = .int(value) }
    public init(floatLiteral value: Double) { self = .double(value) }
    public init(booleanLiteral value: Bool) { self = .bool(value) }
    public init(arrayLiteral elements: String...) { self = .list(elements) }
    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        func limited(_ value: String) -> String { value.count > 500 ? String(value.prefix(500)) + "…" : value }
        switch self {
        case .string(let value): try container.encode(limited(value))
        case .int(let value): try container.encode(value)
        case .double(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .list(let values): try container.encode(values.map(limited))
        }
    }
}
public protocol EventLogging: Sendable { func record(_ event: String, _ fields: [String: LogValue]) }
public struct NoEventLog: EventLogging {
    public init() {}
    public func record(_ event: String, _ fields: [String: LogValue]) {}
}
public final class EventLog: EventLogging, @unchecked Sendable {
    public let fileURL: URL
    private let directory: URL, maxBytes: Int, archives: Int
    private let now: @Sendable () -> Date
    private let queue = DispatchQueue(label: "BrewVersion.EventLog")
    private let lock = NSLock()
    private var error: String?
    public var lastWriteError: String? { lock.withLock { error } }
    public init(directory: URL, maxBytes: Int = 2_000_000, archives: Int = 2, now: @escaping @Sendable () -> Date = Date.init) {
        self.directory = directory; self.fileURL = directory.appendingPathComponent("events.jsonl")
        self.maxBytes = maxBytes; self.archives = max(0, archives); self.now = now
        queue.async { self.perform { try self.prepare(); try self.rotateIfNeeded() } }
    }
    public func record(_ event: String, _ fields: [String: LogValue]) {
        let timestamp = now()
        queue.async {
            self.perform {
                let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                var object = fields; object["t"] = .string(formatter.string(from: timestamp)); object["event"] = .string(event)
                let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
                var data = try encoder.encode(object); data.append(10)
                try self.prepare(); try self.rotateIfNeeded()
                if !FileManager.default.fileExists(atPath: self.fileURL.path) {
                    guard FileManager.default.createFile(atPath: self.fileURL.path, contents: nil, attributes: [.posixPermissions: 0o600]) else { throw CocoaError(.fileWriteUnknown) }
                }
                let handle = try FileHandle(forWritingTo: self.fileURL); defer { try? handle.close() }
                try handle.seekToEnd(); try handle.write(contentsOf: data)
            }
        }
    }
    public func flush() async { await withCheckedContinuation { continuation in queue.async { continuation.resume() } } }
    private func perform(_ operation: () throws -> Void) {
        do { try operation() } catch { lock.withLock { self.error = error.localizedDescription } }
    }
    private func prepare() throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    }
    private func rotateIfNeeded() throws {
        let fm = FileManager.default
        guard let size = try? fm.attributesOfItem(atPath: fileURL.path)[.size] as? Int, size >= maxBytes else { return }
        if archives == 0 { try fm.removeItem(at: fileURL); return }
        let last = directory.appendingPathComponent("events.\(archives).jsonl")
        if fm.fileExists(atPath: last.path) { try fm.removeItem(at: last) }
        if archives > 1 {
            for index in stride(from: archives - 1, through: 1, by: -1) {
                let source = directory.appendingPathComponent("events.\(index).jsonl")
                if fm.fileExists(atPath: source.path) { try fm.moveItem(at: source, to: directory.appendingPathComponent("events.\(index + 1).jsonl")) }
            }
        }
        try fm.moveItem(at: fileURL, to: directory.appendingPathComponent("events.1.jsonl"))
    }
}
