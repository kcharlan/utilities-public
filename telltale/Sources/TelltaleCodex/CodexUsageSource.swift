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
    /// Each database's last format problem and its file. A skip or read failure preserves it only
    /// for that file; a nil file in an older cursor preserves the verdict for the current file.
    public var threadHistoryProblem: String?
    public var logsProblem: String?
    public var threadHistoryProblemFile: String?
    public var logsProblemFile: String?
    public var threadHistoryModification: Date?
    public var logsModification: Date?
    public var threadHistoryReadFile: String?
    public var logsReadFile: String?

    public init(
        sessions: [String: SessionCursor] = [:], threadHistorySince: Date? = nil, logsAfterID: Int64? = nil,
        logsLastSeen: Date? = nil, threadHistoryProblem: String? = nil, logsProblem: String? = nil,
        threadHistoryProblemFile: String? = nil, logsProblemFile: String? = nil, threadHistoryModification: Date? = nil, logsModification: Date? = nil, threadHistoryReadFile: String? = nil, logsReadFile: String? = nil
    ) {
        self.sessions = sessions
        self.threadHistorySince = threadHistorySince
        self.logsAfterID = logsAfterID
        self.logsLastSeen = logsLastSeen
        self.threadHistoryProblem = threadHistoryProblem
        self.logsProblem = logsProblem
        self.threadHistoryProblemFile = threadHistoryProblemFile
        self.logsProblemFile = logsProblemFile
        self.threadHistoryModification = threadHistoryModification
        self.logsModification = logsModification
        self.threadHistoryReadFile = threadHistoryReadFile
        self.logsReadFile = logsReadFile
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
    private let snapshotDirectory: URL?
    private let snapshotClone: SnapshotClone

    public init(codexHome: URL, busyTimeout: Duration = .milliseconds(250), snapshotDirectory: URL? = nil, snapshotClone: SnapshotClone = .live) {
        self.codexHome = codexHome
        self.busyTimeout = busyTimeout
        self.snapshotDirectory = snapshotDirectory
        self.snapshotClone = snapshotClone
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
        var readProblems: [String] = []

        let cleanupError: (any Error)?
        do {
            if let snapshotDirectory { try ReadOnlySQLite.cleanSnapshots(snapshotDirectory) }
            cleanupError = nil
        } catch { cleanupError = error }
        readRollouts(previous: previous, backfillFrom: backfillFrom, next: &next, batch: &batch, problems: &problems, readProblems: &readProblems)

        let historyURL = ThreadHistorySource.database(codexHome: codexHome)
        let historyDate = historyURL.flatMap { try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate }
        let historyRequest = snapshotDirectory.map { SnapshotRequest(directory: $0, lastReadModification: previous?.threadHistoryModification, lastReadFile: previous?.threadHistoryReadFile, clone: snapshotClone) }
        let historyOutcome = Self.run("Codex failed turns") {
            if let cleanupError { throw cleanupError }
            guard let historyURL else { return [FailedTurnRecord]() }
            return try ThreadHistorySource.read(codexHome: codexHome,
                since: previous?.threadHistorySince.map(ThreadHistorySource.rescanStart(after:)) ?? backfillFrom,
                busyTimeout: busyTimeout, snapshot: historyRequest, selectedURL: historyURL)
        }
        switch historyOutcome {
        case .ok(let turns):
            batch.failedTurns = turns
            next.threadHistorySince = now
            next.threadHistoryProblem = nil
            next.threadHistoryProblemFile = nil
            next.threadHistoryModification = historyDate
            next.threadHistoryReadFile = historyURL?.lastPathComponent
        case .busy, .failure:
            if let file = next.threadHistoryProblemFile, file != historyURL?.lastPathComponent {
                next.threadHistoryProblem = nil
                next.threadHistoryProblemFile = nil
            }
            if let kept = next.threadHistoryProblem { problems.append(kept) }
            if case .failure(let text) = historyOutcome {
                next.threadHistoryModification = nil
                next.threadHistoryReadFile = nil
                readProblems.append(text)
            }
        case .problem(let text):
            problems.append(text)
            next.threadHistoryProblem = text
            next.threadHistoryProblemFile = historyURL?.lastPathComponent
            next.threadHistoryModification = historyDate
            next.threadHistoryReadFile = historyURL?.lastPathComponent
        }

        let logsURL = RetryLogSource.database(codexHome: codexHome)
        let logsDate = logsURL.flatMap { try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate }
        let logsRequest = snapshotDirectory.map { SnapshotRequest(directory: $0, lastReadModification: previous?.logsModification, lastReadFile: previous?.logsReadFile, clone: snapshotClone) }
        let logsOutcome = Self.run("Codex connection log") {
            if let cleanupError { throw cleanupError }
            guard let logsURL else { return (events: [ConnectionEventRecord](), maxID: previous?.logsAfterID ?? 0, oldestRetained: Optional<Date>.none) }
            return try RetryLogSource.read(codexHome: codexHome, afterID: previous?.logsAfterID ?? 0,
                busyTimeout: busyTimeout, snapshot: logsRequest, selectedURL: logsURL)
        }
        switch logsOutcome {
        case .ok(let read):
            batch.connectionEvents = read.events
            if let seen = previous?.logsLastSeen, let oldest = read.oldestRetained, oldest > seen {
                batch.connectionGaps.append(DateInterval(start: seen, end: oldest))
            }
            next.logsAfterID = read.maxID
            next.logsLastSeen = now
            next.logsProblem = nil
            next.logsProblemFile = nil
            next.logsModification = logsDate
            next.logsReadFile = logsURL?.lastPathComponent
        case .busy, .failure:
            if let file = next.logsProblemFile, file != logsURL?.lastPathComponent {
                next.logsProblem = nil
                next.logsProblemFile = nil
            }
            if let kept = next.logsProblem { problems.append(kept) }
            if case .failure(let text) = logsOutcome {
                next.logsModification = nil
                next.logsReadFile = nil
                readProblems.append(text)
            }
        case .problem(let text):
            problems.append(text)
            next.logsProblem = text
            next.logsProblemFile = logsURL?.lastPathComponent
            next.logsModification = logsDate
            next.logsReadFile = logsURL?.lastPathComponent
        }
        return IngestResult(batch: batch, cursor: next.encoded(), state: problems.first.map(SetupState.formatProblem) ?? readProblems.first.map(SetupState.readProblem) ?? .ready)
    }

    // MARK: Rollouts

    private func readRollouts(
        previous: CodexCursor?, backfillFrom: Date, next: inout CodexCursor, batch: inout IngestBatch, problems: inout [String], readProblems: inout [String]
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
                readProblems.append("Codex rollout \(file.sessionID): the \(file.compressed ? "compressed" : "plain") file couldn't be read")
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
        case failure(String)
    }

    /// A busy or closed file is skipped quietly (the caller reports the file's kept problem, if any);
    /// anything else that goes wrong is a problem naming `part`.
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
            return .failure("\(part): couldn't be read (\(error))")
        } catch {
            return .failure("\(part): couldn't be read")
        }
    }
}
