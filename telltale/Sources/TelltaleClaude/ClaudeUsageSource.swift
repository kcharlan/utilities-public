import Foundation
import TelltaleCore

public struct ClaudeUsageSource: UsageSource {
    public let roots: [URL]
    private let names = ClaudeModelNames()
    public init(roots: [URL]) { precondition(!roots.isEmpty); self.roots = roots }
    public var provider: ProviderID { .claude }
    public var dataFolder: URL { roots[0] }
    public var displayName: String { "Claude Code" }
    public var statusSourceID: String { "anthropic" }
    public var signals: Set<Signal> { [.speed, .errors, .link, .provider, .load] }
    public var supportedRules: Set<RuleID> { Set(RuleID.allCases).subtracting([.largePrompts]) }
    public var failureNoun: String { "request" }
    public func displayName(model: String) -> String { names.displayName(model: model) }
    public func incidentTitle(_ title: String, names model: String) -> Bool { names.incidentTitle(title, names: model) }
    public func incidentTitleIsModelSpecific(_ title: String) -> Bool { names.incidentTitleIsModelSpecific(title) }

    public func ingest(cursor: Data?, backfillFrom: Date, now: Date) -> IngestResult {
        let old = cursor.flatMap { try? JSONDecoder().decode(ClaudeCursor.self, from: $0) } ?? ClaudeCursor()
        guard roots.contains(where: { root in
            var isDirectory: ObjCBool = false
            return FileManager.default.fileExists(atPath: root.appending(path: "projects").path, isDirectory: &isDirectory) && isDirectory.boolValue
        }) else {
            return IngestResult(batch: IngestBatch(), cursor: cursor ?? Data("{\"files\":{}}".utf8), state: .notSetUp("Claude Code's data folder wasn't found."))
        }
        var next = ClaudeCursor()
        var batch = IngestBatch()
        var problem: String?
        let files = TranscriptDiscovery.files(roots: roots)
        for file in files {
            var previous = old.files[file.key]
            if previous == nil && file.modified < backfillFrom { continue }
            if let known = previous, known.inode != file.inode || known.offset > file.size { previous = nil }
            let start = previous ?? FileCursor(rootIndex: file.rootIndex)
            next.files[file.key] = start
            do {
                let parsed = try TranscriptParser.parse(file: file, cursor: start, now: now)
                next.files[file.key] = parsed.cursor
                batch.responses += parsed.responses
                batch.excludedServerToolResponses += parsed.excluded
                batch.failedTurns += parsed.failed
                batch.connectionEvents += parsed.retries
                batch.compactions += parsed.compactions
                batch.excludedClientErrors += parsed.clientErrors
                batch.invalidCompactions += parsed.invalidCompactions
                if let limit = parsed.limit, batch.usageLimit == nil || limit.at > batch.usageLimit!.at { batch.usageLimit = limit }
                if let version = parsed.cursor.version, TranscriptParser.newer(version, than: batch.sourceVersion) { batch.sourceVersion = version }
                if parsed.cursor.sawInvalidCompaction == true || parsed.cursor.sawAssistant == true && !parsed.cursor.sawUsage ||
                    (now.timeIntervalSince(file.modified) < 86400 && parsed.cursor.sawUser == true && parsed.cursor.sawAssistant == true && parsed.cursor.sawTimestamp != true) {
                    problem = "Claude Code changed its log format."
                }
            } catch { problem = "Claude Code transcript couldn't be read." }
        }
        batch.failedTurns = Array(Dictionary(batch.failedTurns.map { ($0.turnID, $0) }, uniquingKeysWith: { first, _ in first }).values)
        if !files.contains(where: { now.timeIntervalSince($0.modified) < 86400 }) && TranscriptDiscovery.hasRecentFilesOutsideLayout(roots: roots, now: now) { problem = "Claude Code changed its log format." }
        let encoded = (try? JSONEncoder().encode(next)) ?? Data("{\"files\":{}}".utf8)
        return IngestResult(batch: batch, cursor: encoded, state: problem.map(SetupState.formatProblem) ?? .ready)
    }
}
