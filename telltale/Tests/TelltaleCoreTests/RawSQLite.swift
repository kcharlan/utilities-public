import Foundation
import SQLite3

/// A deliberately separate SQLite client for tests, so the files `Store` writes are
/// checked by something other than `Store`.
enum RawSQLite {
    struct Failure: Error, CustomStringConvertible {
        let description: String
    }

    /// Runs `sql` and returns every row as text; NULL becomes the string "NULL".
    @discardableResult
    static func rows(_ url: URL, _ sql: String) throws -> [[String]] {
        var db: OpaquePointer?
        guard sqlite3_open_v2(url.path, &db, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX, nil) == SQLITE_OK, let db else {
            throw Failure(description: "open failed: \(url.path)")
        }
        defer { sqlite3_close_v2(db) }
        sqlite3_busy_timeout(db, 5_000)
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &statement, nil) == SQLITE_OK, let statement else {
            throw Failure(description: "prepare failed: \(String(cString: sqlite3_errmsg(db)))")
        }
        defer { sqlite3_finalize(statement) }
        var result: [[String]] = []
        while true {
            let code = sqlite3_step(statement)
            if code == SQLITE_DONE { return result }
            guard code == SQLITE_ROW else { throw Failure(description: "step failed: \(String(cString: sqlite3_errmsg(db)))") }
            result.append((0..<sqlite3_column_count(statement)).map { column in
                sqlite3_column_text(statement, column).map { String(cString: $0) } ?? "NULL"
            })
        }
    }

    static func column(_ url: URL, _ sql: String) throws -> [String] {
        try rows(url, sql).map { $0[0] }
    }

    static func scalar(_ url: URL, _ sql: String) throws -> String {
        try column(url, sql).first ?? "NULL"
    }
}
