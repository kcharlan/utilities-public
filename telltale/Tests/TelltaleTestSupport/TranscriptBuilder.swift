import Foundation

/// Synthetic transcripts contain no user content or real identifiers.
public enum TranscriptBuilder {
    public static let placeholder = "SYNTHETIC CONTENT MUST NEVER BE STORED"
    public static func line(_ object: [String: Any]) throws -> String {
        String(decoding: try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]), as: UTF8.self) + "\n"
    }
    public static func user(_ timestamp: String) throws -> String {
        try line(["type": "user", "timestamp": timestamp, "message": ["content": placeholder]])
    }
    public static func assistant(_ timestamp: String, id: String = "msg_synthetic_01", output: Int = 300,
                                 usageExtra: [String: Any] = [:], extra: [String: Any] = [:]) throws -> String {
        var usage: [String: Any] = ["input_tokens": 10, "output_tokens": output]
        usage.merge(usageExtra) { _, new in new }
        var line: [String: Any] = ["type": "assistant", "timestamp": timestamp, "requestId": "req_synthetic_01",
            "message": ["id": id, "model": "claude-opus-5-5", "usage": usage, "content": placeholder]]
        line.merge(extra) { _, new in new }
        return try self.line(line)
    }
    public static func file(root: URL, name: String = "00000000-0000-4000-8000-000000000001.jsonl", text: String) throws -> URL {
        let directory = root.appending(path: "projects/-Users-example-project")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appending(path: name)
        try text.write(to: url, atomically: true, encoding: .utf8)
        return url
    }
}
