import Foundation
import TelltaleCore

/// What the Codex source remembers between runs. The core persists it as opaque data.
public struct CodexCursor: Codable, Equatable, Sendable {
    /// Per session id (rollouts).
    public var sessions: [String: SessionCursor]
    /// When failed turns were last read in full; the next scan starts two hours before.
    public var threadHistorySince: Date?
    /// The highest log id read.
    public var logsAfterID: Int64?
    /// When the retry log was last read: anything pruned after that is a gap.
    public var logsLastSeen: Date?

    public init(
        sessions: [String: SessionCursor] = [:], threadHistorySince: Date? = nil, logsAfterID: Int64? = nil,
        logsLastSeen: Date? = nil
    ) {
        self.sessions = sessions
        self.threadHistorySince = threadHistorySince
        self.logsAfterID = logsAfterID
        self.logsLastSeen = logsLastSeen
    }

    /// Dates use `JSONEncoder`'s default, a Double that round-trips exactly. `needsRead` compares a
    /// compressed file's modification date with `==`, so a lossier form would re-read every
    /// compressed file on every run.
    public func encoded() -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return (try? encoder.encode(self)) ?? Data("{\"sessions\":{}}".utf8)
    }

    /// Nil data or data that does not decode starts over, as a first run.
    public static func decode(_ data: Data?) -> CodexCursor? {
        data.flatMap { try? JSONDecoder().decode(CodexCursor.self, from: $0) }
    }
}

/// The Codex usage source (spec section 6): rollouts for responses and the usage limit, the
/// thread-history database for failed turns, and the logs database for disconnects. The readers
/// run independently, so one failing does not hide the others' data.
public struct CodexUsageSource: UsageSource {
    public let codexHome: URL
    private let busyTimeout: Duration
    private let names = ModelNames()

    public init(codexHome: URL, busyTimeout: Duration = .milliseconds(250)) {
        self.codexHome = codexHome
        self.busyTimeout = busyTimeout
    }

    public var provider: ProviderID { .codex }
    public var dataFolder: URL { codexHome }
    public var displayName: String { "Codex" }
    public var statusSourceID: String { "openai" }
    public var signals: Set<Signal> { [.speed, .errors, .link, .provider, .load] }

    public func displayName(model: String) -> String { names.displayName(model: model) }
    public func incidentTitle(_ title: String, names model: String) -> Bool { names.incidentTitle(title, names: model) }

    public func ingest(cursor: Data?, backfillFrom: Date, now: Date) -> IngestResult {
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: codexHome.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            return IngestResult(
                batch: IngestBatch(), cursor: cursor ?? CodexCursor().encoded(),
                state: .notSetUp("Codex's data folder wasn't found."))
        }
        let previous = CodexCursor.decode(cursor)
        var next = previous ?? CodexCursor()
        var batch = IngestBatch()
        var problems: [String] = []

        readRollouts(previous: previous, backfillFrom: backfillFrom, next: &next, batch: &batch, problems: &problems)

        switch Self.run("Codex failed turns", {
            try ThreadHistorySource.read(
                codexHome: codexHome, since: previous?.threadHistorySince.map(ThreadHistorySource.rescanStart(after:)) ?? backfillFrom,
                busyTimeout: busyTimeout)
        }) {
        case .ok(let turns):
            batch.failedTurns = turns
            next.threadHistorySince = now
        case .busy: break
        case .problem(let text): problems.append(text)
        }

        switch Self.run("Codex connection log", {
            try RetryLogSource.read(codexHome: codexHome, afterID: previous?.logsAfterID ?? 0, busyTimeout: busyTimeout)
        }) {
        case .ok(let read):
            batch.connectionEvents = read.events
            if let seen = previous?.logsLastSeen, let oldest = read.oldestRetained, oldest > seen {
                batch.connectionGaps.append(DateInterval(start: seen, end: oldest))
            }
            next.logsAfterID = read.maxID
            next.logsLastSeen = now
        case .busy: break
        case .problem(let text): problems.append(text)
        }

        return IngestResult(batch: batch, cursor: next.encoded(), state: problems.first.map(SetupState.formatProblem) ?? .ready)
    }

    // MARK: Rollouts

    private func readRollouts(
        previous: CodexCursor?, backfillFrom: Date, next: inout CodexCursor, batch: inout IngestBatch, problems: inout [String]
    ) {
        var sessions: [String: SessionCursor] = [:]
        var newestLimit: UsageLimitSnapshot?
        var versionFile: (modified: Date, version: String)?
        for file in RolloutDiscovery.files(codexHome: codexHome) {
            let known = previous?.sessions[file.sessionID]
            // A session Telltale has not read stays unread when it is older than the backfill.
            if known == nil && file.modified < backfillFrom { continue }
            sessions[file.sessionID] = known
            guard RolloutParser.needsRead(file, cursor: known) else { continue }
            let parse: RolloutParse
            do {
                parse = try RolloutParser.parse(file: file, cursor: known)
            } catch {
                problems.append("Codex rollout \(file.sessionID): the \(file.compressed ? "compressed" : "plain") file couldn't be read")
                continue
            }
            sessions[file.sessionID] = parse.cursor
            batch.responses += parse.responses
            if let problem = parse.problem { problems.append(problem) }
            if let limit = parse.usageLimit, limit.at >= (newestLimit?.at ?? .distantPast) { newestLimit = limit }
            if let version = parse.cliVersion, file.modified >= (versionFile?.modified ?? .distantPast) {
                versionFile = (file.modified, version)
            }
        }
        // Entries for files that are gone are dropped by not being copied.
        next.sessions = sessions
        batch.usageLimit = newestLimit
        batch.sourceVersion = versionFile?.version
    }

    // MARK: Reader outcomes

    private enum Outcome<T> {
        case ok(T)
        case busy
        case problem(String)
    }

    /// A busy or closed file is skipped quietly; anything else that goes wrong is a problem naming `part`.
    private static func run<T>(_ part: String, _ body: () throws -> T) -> Outcome<T> {
        do {
            return .ok(try body())
        } catch is ReadOnlySQLite.Busy {
            return .busy
        } catch is ReadOnlySQLite.Closed {
            return .busy
        } catch let error as ReadOnlySQLite.FormatProblem {
            return .problem("\(part): \(error.detail)")
        } catch let error as ReadOnlySQLite.Failure {
            return .problem("\(part): couldn't be read (\(error))")
        } catch {
            return .problem("\(part): couldn't be read")
        }
    }
}
