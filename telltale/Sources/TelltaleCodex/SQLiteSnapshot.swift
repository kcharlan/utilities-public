import Darwin
import Foundation
import SQLite3

public struct SnapshotClone: Sendable {
    public var run: @Sendable (URL, URL) throws -> Void
    public init(_ run: @escaping @Sendable (URL, URL) throws -> Void) { self.run = run }
    public static let live = SnapshotClone { source, destination in
        guard clonefile(source.path, destination.path, UInt32(CLONE_NOFOLLOW)) == 0 else {
            throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
        }
    }
}

public struct SnapshotRequest: Sendable {
    public var directory: URL
    public var lastReadModification: Date?
    public var lastReadFile: String?
    public var clone: SnapshotClone

    public init(directory: URL, lastReadModification: Date?, lastReadFile: String?, clone: SnapshotClone) {
        self.directory = directory
        self.lastReadModification = lastReadModification
        self.lastReadFile = lastReadFile
        self.clone = clone
    }

    func needsRead(_ url: URL) -> Bool {
        guard lastReadFile == url.lastPathComponent, let lastReadModification,
              let current = try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate else { return true }
        return current != lastReadModification
    }
}

extension ReadOnlySQLite {
    private static func snapshotFailure(_ message: String) -> Failure {
        Failure(code: SQLITE_CANTOPEN, message: message, context: "reading a snapshot")
    }

    private static func ensureSnapshotRoot(_ root: URL) throws {
        var info = stat()
        if lstat(root.path, &info) != 0 {
            guard errno == ENOENT else { throw snapshotFailure("cannot inspect snapshot directory") }
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            guard lstat(root.path, &info) == 0 else { throw snapshotFailure("cannot inspect snapshot directory") }
        }
        guard (info.st_mode & S_IFMT) == S_IFDIR, (info.st_mode & 0o7777) == 0o700 else {
            throw snapshotFailure("insecure snapshot directory")
        }
    }

    static func cleanSnapshots(_ root: URL) throws {
        try ensureSnapshotRoot(root)
        let entries = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
        for entry in entries { try FileManager.default.removeItem(at: entry) }
    }

    public static func withSnapshot<T>(of url: URL, in directory: URL, busyTimeout: Duration, clone: SnapshotClone, _ body: (ReadOnlySQLite) throws -> T) throws -> T {
        try ensureSnapshotRoot(directory)
        var original = stat()
        guard lstat(url.path, &original) == 0, (original.st_mode & S_IFMT) == S_IFREG else {
            throw snapshotFailure("source is not a regular file")
        }
        let folder = directory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        var cleanupError: (any Error)?
        let result: Result<T, any Error> = {
            defer {
                do { try FileManager.default.removeItem(at: folder) }
                catch { cleanupError = error }
            }
            return Result {
                let copy = folder.appending(path: url.lastPathComponent)
                do { try clone.run(url, copy) } catch { throw Closed() }
                var after = stat()
                guard lstat(url.path, &after) == 0, after.st_dev == original.st_dev, after.st_ino == original.st_ino,
                      after.st_size == original.st_size, after.st_mtimespec.tv_sec == original.st_mtimespec.tv_sec,
                      after.st_mtimespec.tv_nsec == original.st_mtimespec.tv_nsec else { throw Busy() }
                var wal = stat()
                guard lstat(url.path + "-wal", &wal) != 0 && errno == ENOENT else { throw Busy() }
                let descriptor = Darwin.open(copy.path, O_RDWR | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
                guard descriptor >= 0 else { throw snapshotFailure("cannot open clone") }
                let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
                var info = stat()
                guard fstat(descriptor, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG, info.st_nlink == 1,
                      info.st_dev != original.st_dev || info.st_ino != original.st_ino else {
                    throw snapshotFailure("clone is an alias or not a regular file")
                }
                let header = try handle.read(upToCount: 100) ?? Data()
                guard header.count == 100, header.prefix(16) == Data("SQLite format 3\0".utf8), header[18] == 2, header[19] == 2 else {
                    throw snapshotFailure("invalid SQLite WAL header")
                }
                try handle.seek(toOffset: 18)
                try handle.write(contentsOf: Data([1, 1]))
                try handle.close()
                return try body(open(copy, busyTimeout: busyTimeout))
            }
        }()
        if let cleanupError { throw cleanupError }
        return try result.get()
    }
}
