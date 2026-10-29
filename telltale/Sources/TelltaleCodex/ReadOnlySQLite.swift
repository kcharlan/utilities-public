import Foundation
import SQLite3

/// A wrapper around `sqlite3_step`, so tests can inject the codes it returns.
public struct SQLiteStep: Sendable {
    public var run: @Sendable (OpaquePointer) -> Int32

    public init(_ run: @escaping @Sendable (OpaquePointer) -> Int32) { self.run = run }

    public static let live = SQLiteStep { sqlite3_step($0) }
}

/// A read-only connection to one of Codex's SQLite files (spec section 6, intro).
///
/// The file is opened with `mode=ro` and a short busy timeout. `SQLITE_BUSY` and `SQLITE_LOCKED`,
/// from any step, become `Busy`, so a caller skips the file and retries next run rather than
/// blocking Codex. A WAL database whose writer closed it, leaving no `-wal`, becomes `Closed` and
/// is skipped the same way. Read-only still joins SQLite's normal coordination: opening a WAL
/// database can create or update its `-shm` side file, so Telltale does not promise that Codex's
/// files are untouched at that level (Colophon's read-only SQLite lesson).
public final class ReadOnlySQLite {
    /// Another connection holds the file; skip it this run.
    public struct Busy: Error, Equatable, Sendable {}

    /// A WAL-mode database that has no `-wal` file beside it, so SQLite could not read it.
    ///
    /// When a writer closes a WAL database cleanly, upstream SQLite deletes `-wal` and `-shm`. The
    /// system SQLite then fails a `mode=ro` connection's first statement with `SQLITE_CANTOPEN`
    /// instead of reading the main file. `isClosedWAL` is the evidence: a WAL header and no `-wal`.
    /// It does not prove that no process has the database open, so a caller skips the file quietly,
    /// keeps its cursor and reads the file again next run, rather than reporting a format problem.
    public struct Closed: Error, Equatable, Sendable {}

    /// SQLite refused for a reason other than contention, or the file is not a plain file.
    public struct Failure: Error, Equatable, Sendable, CustomStringConvertible {
        public var code: Int32
        public var message: String
        public var context: String

        public var description: String { "SQLite error \(code) (\(message)) while \(context)" }
    }

    /// The file is readable but not shaped the way Telltale needs (spec section 6.5).
    public struct FormatProblem: Error, Equatable, Sendable, CustomStringConvertible {
        public var detail: String

        public var description: String { detail }
    }

    public enum Binding: Sendable {
        case integer(Int64)
        case text(String)
    }

    /// One result row. Valid only inside the closure that receives it.
    public struct Row {
        fileprivate let statement: OpaquePointer

        public func isNull(_ column: Int32) -> Bool { sqlite3_column_type(statement, column) == SQLITE_NULL }

        public func integer(_ column: Int32) -> Int64? {
            isNull(column) ? nil : sqlite3_column_int64(statement, column)
        }

        /// Text conversion can allocate, so a failed conversion is an error rather than absent text.
        public func text(_ column: Int32) throws -> String? {
            if isNull(column) { return nil }
            guard let bytes = sqlite3_column_text(statement, column) else {
                let db = sqlite3_db_handle(statement)
                throw Failure(code: sqlite3_errcode(db), message: "text conversion failed", context: "reading a column")
            }
            return String(cString: bytes)
        }
    }

    private let db: OpaquePointer
    private let step: SQLiteStep
    private let name: String
    private let url: URL

    private init(db: OpaquePointer, step: SQLiteStep, name: String, url: URL) {
        self.db = db
        self.step = step
        self.name = name
        self.url = url
    }

    deinit { sqlite3_close_v2(db) }

    /// Opens `url` read-only. Throws `Failure` unless it, and any `-wal`, `-shm` or `-journal`
    /// beside it, is a regular file: a FIFO with a database name would block the open past any
    /// busy timeout (Colophon's lesson).
    public static func open(
        _ url: URL, busyTimeout: Duration = .milliseconds(250), step: SQLiteStep = .live
    ) throws -> ReadOnlySQLite {
        let name = url.lastPathComponent
        try requireRegularFile(url.path, name: name, sidecar: false)
        for suffix in ["-wal", "-shm", "-journal"] {
            try requireRegularFile(url.path + suffix, name: name + suffix, sidecar: true)
        }
        let uri = "file:" + encode(url.path) + "?mode=ro"
        var handle: OpaquePointer?
        let code = sqlite3_open_v2(uri, &handle, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI | SQLITE_OPEN_FULLMUTEX, nil)
        guard code == SQLITE_OK, let handle else {
            let message = handle.map { String(cString: sqlite3_errmsg($0)) } ?? "out of memory"
            sqlite3_close_v2(handle)
            throw failure(code, message: message, context: "opening \(name)", url: url)
        }
        let seconds = max(0, busyTimeout.components.seconds)
        sqlite3_busy_timeout(handle, Int32(clamping: seconds * 1_000 + busyTimeout.components.attoseconds / 1_000_000_000_000_000))
        return ReadOnlySQLite(db: handle, step: step, name: name, url: url)
    }

    /// True when `url` starts with a WAL header (bytes 18 and 19 are both 2; a rollback-journal file
    /// has 1) and has no `-wal` beside it. Failing to read the header is false.
    public static func isClosedWAL(_ url: URL) -> Bool {
        guard !FileManager.default.fileExists(atPath: url.path + "-wal"),
            let handle = try? FileHandle(forReadingFrom: url)
        else { return false }
        defer { try? handle.close() }
        guard let header = try? handle.read(upToCount: 20), header.count == 20 else { return false }
        return header[header.startIndex + 18] == 2 && header[header.startIndex + 19] == 2
    }

    /// The highest-numbered `<prefix>_N.sqlite` in `directory` (spec sections 6.2 and 6.3), if any.
    public static func highestNumbered(_ prefix: String, in directory: URL) -> URL? {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: directory.path)) ?? []
        let best = names.compactMap { name -> (Int, String)? in
            guard name.hasPrefix(prefix + "_"), name.hasSuffix(".sqlite") else { return nil }
            let digits = name.dropFirst(prefix.count + 1).dropLast(".sqlite".count)
            guard !digits.isEmpty, digits.allSatisfy(\.isASCII), digits.allSatisfy(\.isNumber), let number = Int(digits) else {
                return nil
            }
            return (number, name)
        }.max { $0.0 < $1.0 }
        return best.map { directory.appending(path: $0.1) }
    }

    /// Runs `sql` and maps each row. Statement text is always a Telltale constant.
    public func query<T>(_ sql: String, _ bindings: [Binding] = [], _ map: (Row) throws -> T) throws -> [T] {
        var statement: OpaquePointer?
        let prepared = sqlite3_prepare_v2(db, sql, -1, &statement, nil)
        guard prepared == SQLITE_OK, let statement else {
            throw Self.failure(prepared, message: String(cString: sqlite3_errmsg(db)), context: "preparing a statement on \(name)", url: url)
        }
        defer { sqlite3_finalize(statement) }
        for (index, binding) in bindings.enumerated() {
            let position = Int32(index + 1)
            let code: Int32
            switch binding {
            case .integer(let value): code = sqlite3_bind_int64(statement, position, value)
            case .text(let value): code = sqlite3_bind_text(statement, position, value, -1, Self.transient)
            }
            guard code == SQLITE_OK else {
                throw Self.failure(code, message: String(cString: sqlite3_errmsg(db)), context: "binding on \(name)", url: url)
            }
        }
        var rows: [T] = []
        while true {
            let code = step.run(statement)
            if code == SQLITE_ROW {
                rows.append(try map(Row(statement: statement)))
            } else if code == SQLITE_DONE {
                return rows
            } else {
                throw Self.failure(code, message: String(cString: sqlite3_errmsg(db)), context: "reading \(name)", url: url)
            }
        }
    }

    /// Runs `body` inside one read transaction, so its queries see the same snapshot.
    public func readTransaction<T>(_ body: () throws -> T) throws -> T {
        _ = try query("BEGIN") { _ in 0 }
        defer { _ = try? query("COMMIT") { _ in 0 } }
        return try body()
    }

    /// Throws `FormatProblem` unless `table` exists with every one of `columns`.
    public func requireColumns(_ columns: [String], in table: String) throws {
        let present = Set(try query("PRAGMA table_info(\(table))") { try $0.text(1)?.lowercased() }.compactMap { $0 })
        if present.isEmpty { throw FormatProblem(detail: "\(name) has no \(table) table") }
        let missing = columns.filter { !present.contains($0.lowercased()) }
        if !missing.isEmpty {
            throw FormatProblem(detail: "\(name) table \(table) is missing \(missing.count == 1 ? "column" : "columns") \(missing.joined(separator: ", "))")
        }
    }

    // MARK: Private

    private static let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    private static func failure(_ code: Int32, message: String, context: String, url: URL) -> any Error {
        let primary = code & 0xFF
        if primary == SQLITE_BUSY || primary == SQLITE_LOCKED { return Busy() }
        if primary == SQLITE_CANTOPEN && isClosedWAL(url) { return Closed() }
        return Failure(code: code, message: message, context: context)
    }

    private static func encode(_ path: String) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "/-._~")
        return path.addingPercentEncoding(withAllowedCharacters: allowed) ?? path
    }

    /// A missing file passes here; opening it reports that. Anything present must be regular.
    private static func requireRegularFile(_ path: String, name: String, sidecar: Bool) throws {
        var info = stat()
        let found = sidecar ? lstat(path, &info) : stat(path, &info)
        if found != 0 { return }
        guard (info.st_mode & S_IFMT) == S_IFREG else {
            throw Failure(code: SQLITE_CANTOPEN, message: "not a regular file", context: "opening \(name)")
        }
    }
}
