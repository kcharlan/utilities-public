import Foundation

/// Runs `body` with a fresh, empty directory under the system temporary
/// directory and removes it afterwards, so tests never touch a real home.
public func withScratchDirectory<T>(_ body: (URL) throws -> T) throws -> T {
    let directory = try makeScratchDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    return try body(directory)
}

/// The `async` form of `withScratchDirectory`, for tests that await inside the body. The body runs
/// in the caller's isolation, so main-actor tests can use it.
public func withAsyncScratchDirectory<T>(
    isolation: isolated (any Actor)? = #isolation, _ body: (URL) async throws -> T
) async throws -> T {
    let directory = try makeScratchDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    return try await body(directory)
}

private func makeScratchDirectory() throws -> URL {
    let directory = FileManager.default.temporaryDirectory
        .appending(path: "telltale-tests-\(UUID().uuidString)", directoryHint: .isDirectory)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    return directory
}
