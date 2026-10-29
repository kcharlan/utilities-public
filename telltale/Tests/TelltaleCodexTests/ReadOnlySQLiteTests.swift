import Foundation
import SQLite3
import Testing
import TelltaleCodex
import TelltaleTestSupport

@Suite struct ReadOnlySQLiteTests {
    private static let origin = RolloutBuilder.defaultOrigin

    @Test func busyStepThrowsBusy() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home)
            try writer.addLog(at: Self.origin, body: "synthetic")
            // BUSY, LOCKED and an extended BUSY code (BUSY_SNAPSHOT, 517) all mean "skip this run".
            for code in [SQLITE_BUSY, SQLITE_LOCKED, SQLITE_BUSY | (2 << 8)] {
                let database = try ReadOnlySQLite.open(writer.url, step: SQLiteStep { _ in code })
                #expect(throws: ReadOnlySQLite.Busy.self) { try database.query("SELECT id FROM logs") { $0.integer(0) } }
            }
            // Any other failing code is a Failure, not Busy.
            let failing = try ReadOnlySQLite.open(writer.url, step: SQLiteStep { _ in SQLITE_IOERR })
            #expect(throws: ReadOnlySQLite.Failure.self) { try failing.query("SELECT id FROM logs") { $0.integer(0) } }
        }
    }

    @Test func readSucceedsWhileWriterHoldsTransaction() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home)
            let committed = try writer.addLog(at: Self.origin, body: "committed")
            try writer.beginImmediate()
            try writer.addLog(at: Self.origin, body: "uncommitted")

            let database = try ReadOnlySQLite.open(writer.url, busyTimeout: .milliseconds(20))
            let ids = try database.query("SELECT id FROM logs ORDER BY id") { $0.integer(0) }
            #expect(ids == [committed])
            try writer.commit()
            #expect(try database.query("SELECT COUNT(*) FROM logs") { $0.integer(0) } == [2])
        }
    }

    @Test func realLockOnRollbackJournalFileThrowsBusyQuickly() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home, journal: .delete)
            try writer.addLog(at: Self.origin, body: "synthetic")
            try writer.beginExclusive()
            let database = try ReadOnlySQLite.open(writer.url, busyTimeout: .milliseconds(20))
            #expect(throws: ReadOnlySQLite.Busy.self) { try database.query("SELECT id FROM logs") { $0.integer(0) } }
            try writer.commit()
            #expect(try database.query("SELECT id FROM logs") { $0.integer(0) }.count == 1)
        }
    }

    @Test func connectionIsReadOnly() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home)
            try writer.addLog(at: Self.origin, body: "synthetic")
            let database = try ReadOnlySQLite.open(writer.url)
            #expect(throws: ReadOnlySQLite.Failure.self) { try database.query("DELETE FROM logs") { _ in 0 } }
            #expect(throws: ReadOnlySQLite.Failure.self) { try database.query("CREATE TABLE extra (a)") { _ in 0 } }
            #expect(try database.query("SELECT COUNT(*) FROM logs") { $0.integer(0) } == [1])
        }
    }

    @Test func pathWithSpecialCharactersOpens() throws {
        try withScratchDirectory { home in
            let folder = home.appending(path: "a b?c#d%20e", directoryHint: .isDirectory)
            let writer = try CodexDatabase.logs(codexHome: folder)
            try writer.addLog(at: Self.origin, body: "synthetic")
            let database = try ReadOnlySQLite.open(writer.url)
            #expect(try database.query("SELECT COUNT(*) FROM logs") { $0.integer(0) } == [1])
        }
    }

    @Test func missingFileIsFailureNotCreated() throws {
        try withScratchDirectory { home in
            let url = home.appending(path: "logs_9.sqlite")
            #expect(throws: ReadOnlySQLite.Failure.self) { try ReadOnlySQLite.open(url) }
            #expect(!FileManager.default.fileExists(atPath: url.path))
        }
    }

    @Test func nonRegularFilesAreRefusedWithoutBlocking() throws {
        try withScratchDirectory { home in
            // A FIFO with a database name would block an open past any busy timeout.
            let fifo = home.appending(path: "thread_history_1.sqlite")
            #expect(mkfifo(fifo.path, 0o600) == 0)
            #expect(throws: ReadOnlySQLite.Failure.self) { try ReadOnlySQLite.open(fifo) }

            // The same goes for a sidecar.
            let writer = try CodexDatabase.logs(codexHome: home)
            let journal = writer.url.path + "-journal"
            #expect(mkfifo(journal, 0o600) == 0)
            #expect(throws: ReadOnlySQLite.Failure.self) { try ReadOnlySQLite.open(writer.url) }
        }
    }

    @Test func highestNumberedIsNumericAndStrict() throws {
        try withScratchDirectory { home in
            for name in [
                "logs_2.sqlite", "logs_10.sqlite", "logs_9.sqlite", "logs_11.sqlite-wal", "logs_x.sqlite", "logs_.sqlite",
                "logs_3.sqlite.bak", "other_99.sqlite"
            ] {
                try Data().write(to: home.appending(path: name))
            }
            #expect(ReadOnlySQLite.highestNumbered("logs", in: home)?.lastPathComponent == "logs_10.sqlite")
            #expect(ReadOnlySQLite.highestNumbered("thread_history", in: home) == nil)
            #expect(ReadOnlySQLite.highestNumbered("logs", in: home.appending(path: "absent")) == nil)
        }
    }

    @Test func requireColumnsNamesWhatIsMissing() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home, omitting: ["target", "ts_nanos"])
            let database = try ReadOnlySQLite.open(writer.url)
            try database.requireColumns(["id", "ts"], in: "logs")
            let problem = try #require(throws: ReadOnlySQLite.FormatProblem.self) {
                try database.requireColumns(["id", "ts_nanos", "target"], in: "logs")
            }
            #expect(problem.detail.contains("ts_nanos") && problem.detail.contains("target") && !problem.detail.contains("id,"))
            let noTable = try #require(throws: ReadOnlySQLite.FormatProblem.self) {
                try database.requireColumns(["a"], in: "absent")
            }
            #expect(noTable.detail.contains("absent"))
        }
    }

    // MARK: Closed WAL

    @Test func closedWALDatabaseThrowsClosedAndCreatesNothing() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.threadHistory(codexHome: home)
            try writer.addTurn(turn: 1, status: "inProgress", startedAt: Self.origin)
            try writer.finishTurn(turn: 1, status: "failed", errorJSON: nil, completedAt: Self.origin.addingTimeInterval(5))
            try writer.closeLikeCodex()
            let database = try ReadOnlySQLite.open(writer.url)
            #expect(throws: ReadOnlySQLite.Closed.self) {
                try database.requireColumns(ThreadHistorySource.columns, in: "thread_turns")
            }
            #expect(!FileManager.default.fileExists(atPath: writer.url.path + "-wal"))
            #expect(!FileManager.default.fileExists(atPath: writer.url.path + "-shm"))
        }
    }

    @Test func isClosedWALNeedsWALHeaderAndNoWALFile() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home)
            try writer.addLog(at: Self.origin, body: "synthetic")
            #expect(!ReadOnlySQLite.isClosedWAL(writer.url))  // still open: the -wal is there
            try writer.closeLikeCodex()
            #expect(ReadOnlySQLite.isClosedWAL(writer.url))

            // An empty -shm alone changes nothing.
            let shm = writer.url.path + "-shm"
            #expect(FileManager.default.createFile(atPath: shm, contents: Data()))
            #expect(ReadOnlySQLite.isClosedWAL(writer.url))
            try FileManager.default.removeItem(atPath: shm)

            // An empty -wal alone means the file is not closed, and reads succeed.
            let wal = writer.url.path + "-wal"
            #expect(FileManager.default.createFile(atPath: wal, contents: Data()))
            #expect(!ReadOnlySQLite.isClosedWAL(writer.url))
            let database = try ReadOnlySQLite.open(writer.url)
            #expect(try database.query("SELECT COUNT(*) FROM logs") { $0.integer(0) } == [1])
        }
    }

    @Test func rollbackJournalAndMissingFilesAreNotClosedWAL() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home, journal: .delete)
            try writer.addLog(at: Self.origin, body: "synthetic")
            #expect(!ReadOnlySQLite.isClosedWAL(writer.url))
            #expect(!ReadOnlySQLite.isClosedWAL(home.appending(path: "logs_9.sqlite")))
            let short = home.appending(path: "logs_8.sqlite")
            try Data(count: 10).write(to: short)
            #expect(!ReadOnlySQLite.isClosedWAL(short))
        }
    }

    @Test func unreadableClosedDatabaseIsStillAFailure() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home)
            try writer.addLog(at: Self.origin, body: "synthetic")
            try writer.closeLikeCodex()
            #expect(chmod(writer.url.path, 0o000) == 0)
            defer { chmod(writer.url.path, 0o600) }
            #expect(throws: ReadOnlySQLite.Failure.self) {
                let database = try ReadOnlySQLite.open(writer.url)
                _ = try database.query("SELECT id FROM logs") { $0.integer(0) }
            }
        }
    }
}

@Suite struct SQLiteSnapshotTests {
    @Test func snapshotReadsAClosedDatabaseAndLeavesNothing() throws {
        try withScratchDirectory { home in
            let source = home.appending(path: "source")
            let root = home.appending(path: "snapshots")
            let writer = try CodexDatabase.logs(codexHome: source)
            try writer.addLog(at: RolloutBuilder.defaultOrigin, body: "synthetic")
            try writer.closeLikeCodex()
            let before = try FileSnapshot.take(source)
            let rows = try ReadOnlySQLite.withSnapshot(of: writer.url, in: root, busyTimeout: .milliseconds(250), clone: .live) {
                try $0.query("SELECT COUNT(*) FROM logs") { $0.integer(0) }
            }
            #expect(rows == [1])
            #expect(try FileSnapshot.take(source) == before)
            #expect(try FileManager.default.contentsOfDirectory(atPath: root.path).isEmpty)
            let mode = try #require(FileManager.default.attributesOfItem(atPath: root.path)[.posixPermissions] as? Int)
            #expect(mode == 0o700)
            #expect(!FileManager.default.fileExists(atPath: writer.url.path + "-wal"))
            #expect(!FileManager.default.fileExists(atPath: writer.url.path + "-shm"))
        }
    }
}

extension SQLiteSnapshotTests {
    private struct SyntheticError: Error {}

    @Test func snapshotNeedsACloneAndCleansUpAfterErrors() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home.appending(path: "source"))
            try writer.closeLikeCodex()
            let root = home.appending(path: "snapshots")
            #expect(throws: ReadOnlySQLite.Closed.self) {
                try ReadOnlySQLite.withSnapshot(of: writer.url, in: root, busyTimeout: .zero, clone: SnapshotClone { _, _ in throw SyntheticError() }) { _ in 0 }
            }
            #expect(throws: SyntheticError.self) {
                try ReadOnlySQLite.withSnapshot(of: writer.url, in: root, busyTimeout: .zero, clone: .live) { _ -> Int in throw SyntheticError() }
            }
            #expect(try FileManager.default.contentsOfDirectory(atPath: root.path).isEmpty)
        }
    }

    @Test func snapshotDiscardsAChangedOriginal() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home.appending(path: "source"))
            try writer.closeLikeCodex()
            let root = home.appending(path: "snapshots")
            let clone = SnapshotClone { source, target in
                try SnapshotClone.live.run(source, target)
                try FileManager.default.setAttributes([.modificationDate: Date(timeIntervalSince1970: 42)], ofItemAtPath: source.path)
            }
            #expect(throws: ReadOnlySQLite.Busy.self) {
                try ReadOnlySQLite.withSnapshot(of: writer.url, in: root, busyTimeout: .zero, clone: clone) { _ in 0 }
            }
            #expect(try FileManager.default.contentsOfDirectory(atPath: root.path).isEmpty)
        }
    }

    @Test func snapshotRejectsAliasesAndInsecureRoots() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home.appending(path: "source"))
            try writer.closeLikeCodex()
            let root = home.appending(path: "snapshots")
            let before = try Data(contentsOf: writer.url)
            let other = try CodexDatabase.logs(codexHome: home.appending(path: "other"))
            try other.closeLikeCodex()
            let otherURL = other.url
            let otherBefore = try Data(contentsOf: otherURL)
            for clone in [SnapshotClone({ _, target in try FileManager.default.linkItem(at: otherURL, to: target) }),
                          SnapshotClone({ source, target in try FileManager.default.linkItem(at: source, to: target) }),
                          SnapshotClone({ source, target in try FileManager.default.createSymbolicLink(at: target, withDestinationURL: source) })] {
                #expect(throws: ReadOnlySQLite.Failure.self) {
                    try ReadOnlySQLite.withSnapshot(of: writer.url, in: root, busyTimeout: .zero, clone: clone) { _ in 0 }
                }
                #expect(try Data(contentsOf: writer.url) == before)
                #expect(try Data(contentsOf: other.url) == otherBefore)
            }
            #expect(chmod(root.path, 0o755) == 0)
            defer { chmod(root.path, 0o700) }
            #expect(throws: ReadOnlySQLite.Failure.self) {
                try ReadOnlySQLite.withSnapshot(of: writer.url, in: root, busyTimeout: .zero, clone: .live) { _ in 0 }
            }
        }
    }
}

private final class ReopenedWriter: @unchecked Sendable {
    var writer: CodexDatabase?
}

extension SQLiteSnapshotTests {
    @Test func snapshotIsDiscardedWhenTheWriterReopens() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home.appending(path: "source"))
            try writer.closeLikeCodex()
            let root = home.appending(path: "snapshots")
            let reopened = ReopenedWriter()
            let clone = SnapshotClone { source, target in
                try SnapshotClone.live.run(source, target)
                reopened.writer = try CodexDatabase.reopen(source)
                try reopened.writer?.addLog(at: RolloutBuilder.defaultOrigin, body: "synthetic")
            }
            #expect(throws: ReadOnlySQLite.Busy.self) {
                try ReadOnlySQLite.withSnapshot(of: writer.url, in: root, busyTimeout: .zero, clone: clone) { _ in 0 }
            }
            #expect(try FileManager.default.contentsOfDirectory(atPath: root.path).isEmpty)
            withExtendedLifetime(reopened) {}
        }
    }

    @Test func snapshotUsesOriginalFileName() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home.appending(path: "source"), omitting: ["target"])
            let direct = try #require(throws: ReadOnlySQLite.FormatProblem.self) {
                try ReadOnlySQLite.open(writer.url).requireColumns(RetryLogSource.columns, in: "logs")
            }
            try writer.closeLikeCodex()
            let problem = try #require(throws: ReadOnlySQLite.FormatProblem.self) {
                try ReadOnlySQLite.withSnapshot(of: writer.url, in: home.appending(path: "snapshots"), busyTimeout: .zero, clone: .live) {
                    try $0.requireColumns(RetryLogSource.columns, in: "logs")
                }
            }
            #expect(problem == direct)
        }
    }

    @Test func snapshotRejectsSymlinkSourceAndRoot() throws {
        try withScratchDirectory { home in
            let writer = try CodexDatabase.logs(codexHome: home.appending(path: "source"))
            try writer.closeLikeCodex()
            let before = try Data(contentsOf: writer.url)
            let sourceLink = home.appending(path: "source-link")
            try FileManager.default.createSymbolicLink(at: sourceLink, withDestinationURL: writer.url)
            let root = home.appending(path: "snapshots")
            #expect(throws: ReadOnlySQLite.Failure.self) {
                try ReadOnlySQLite.withSnapshot(of: sourceLink, in: root, busyTimeout: .zero, clone: .live) { _ in 0 }
            }
            let outside = home.appending(path: "outside")
            try FileManager.default.createDirectory(at: outside, withIntermediateDirectories: false)
            let sentinel = outside.appending(path: "sentinel")
            try Data("synthetic".utf8).write(to: sentinel)
            try FileManager.default.removeItem(at: root)
            try FileManager.default.createSymbolicLink(at: root, withDestinationURL: outside)
            #expect(throws: ReadOnlySQLite.Failure.self) {
                try ReadOnlySQLite.withSnapshot(of: writer.url, in: root, busyTimeout: .zero, clone: .live) { _ in 0 }
            }
            #expect(try Data(contentsOf: writer.url) == before)
            #expect(FileManager.default.fileExists(atPath: sentinel.path))
        }
    }
}
