import Foundation
import PrimeMonitorCore

struct AppState: Codable, Equatable {
    var charger: ChargerInfo?
    var closedInterval: ClosedInterval
    var credentials: CredentialSelection? = nil
    /// Optional so state saved before 0.2.0 decodes; nil means the default size.
    var menuBarTextSize: MenuBarTextSize? = nil
    static let initial = AppState(charger: nil, closedInterval: .default)
}
struct StateLoad {
    let state: AppState
    let problem: String?
    let canSave: Bool
}

/// Port of BrewVersionCore/WatchState.swift, WatchStore load/save at 579ebb7.
/// Keeps corrupt-file quarantine and private atomic replacement semantics.
struct StateStore {
    let fileURL: URL
    init(fileURL: URL) { self.fileURL = fileURL }
    init() {
        fileURL = FileManager.default.homeDirectoryForCurrentUser
            .appending(path: "Library/Application Support/Prime Monitor/state.json", directoryHint: .notDirectory)
    }
    func load() -> StateLoad {
        guard FileManager.default.fileExists(atPath: fileURL.path(percentEncoded: false)) else { return .init(state: .initial, problem: nil, canSave: true) }
        do { return .init(state: try JSONDecoder().decode(AppState.self, from: Data(contentsOf: fileURL)), problem: nil, canSave: true) }
        catch {
            var quarantine = fileURL.appendingPathExtension("bad")
            while FileManager.default.fileExists(atPath: quarantine.path(percentEncoded: false)) {
                quarantine = URL(filePath: fileURL.path(percentEncoded: false) + ".bad-" + UUID().uuidString, directoryHint: .notDirectory)
            }
            do {
                try FileManager.default.moveItem(at: fileURL, to: quarantine)
                return .init(state: .initial, problem: "Unreadable saved state was set aside as \(quarantine.lastPathComponent).", canSave: true)
            } catch { return .init(state: .initial, problem: "Couldn't set aside unreadable saved state.", canSave: false) }
        }
    }
    func save(_ state: AppState) throws {
        let directory = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path(percentEncoded: false))
        let temporary = directory.appending(path: ".state-\(UUID().uuidString).tmp", directoryHint: .notDirectory)
        defer { try? FileManager.default.removeItem(at: temporary) }
        guard FileManager.default.createFile(atPath: temporary.path(percentEncoded: false), contents: nil, attributes: [.posixPermissions: 0o600]) else { throw CocoaError(.fileWriteUnknown) }
        try JSONEncoder().encode(state).write(to: temporary)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path(percentEncoded: false))
        guard rename(temporary.path(percentEncoded: false), fileURL.path(percentEncoded: false)) == 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
    }
}
