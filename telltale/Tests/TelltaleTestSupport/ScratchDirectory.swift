import Foundation

/// Runs `body` with a fresh, empty directory under the system temporary
/// directory and removes it afterwards, so tests never touch a real home.
public func withScratchDirectory<T>(_ body: (URL) throws -> T) throws -> T {
    let directory = FileManager.default.temporaryDirectory
        .appending(path: "telltale-tests-\(UUID().uuidString)", directoryHint: .isDirectory)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: directory) }
    return try body(directory)
}
