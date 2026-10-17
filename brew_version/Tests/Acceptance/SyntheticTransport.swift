import Foundation
import BrewVersionCore

actor SyntheticTransport: HTTPTransport {
    private var version = "1.0-synthetic"
    private var delayNext = false
    func advance() { version = "2.0-synthetic" }
    func delayNextLookup() { delayNext = true }
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        if url.path == "/api/formula.json" {
            return .init(status: 200, body: Data("[{\"name\":\"synthetic-installed\",\"versions\":{\"stable\":\"2.0-synthetic\"}},{\"name\":\"synthetic-formula\",\"versions\":{\"stable\":\"\(version)\"}},{\"name\":\"synthetic-shared\",\"versions\":{\"stable\":\"3.0-synthetic\"}}]".utf8))
        }
        if url.path == "/api/cask.json" {
            return .init(status: 200, body: Data(#"[{"token":"synthetic-cask","version":"1.0-synthetic"},{"token":"synthetic-shared","version":"4.0-synthetic"},{"token":"synthetic-fallback","version":"2.0-synthetic","auto_updates":true,"artifacts":[{"app":["Synthetic Missing.app"]}]}]"#.utf8))
        }
        if delayNext {
            delayNext = false
            try await Task.sleep(for: .seconds(2))
        }
        let name = url.deletingPathExtension().lastPathComponent
        if url.path.contains("/cask/") {
            if name == "synthetic-fallback" {
                return .init(status: 200, body: Data(#"{"version":"2.0-synthetic","auto_updates":true,"artifacts":[{"app":["Synthetic Missing.app"]}]}"#.utf8))
            }
            guard ["synthetic-shared", "synthetic-cask"].contains(name) else { return .init(status: 404, body: Data()) }
            let value = name == "synthetic-shared" ? "4.0-synthetic" : "1.0-synthetic"
            return .init(status: 200, body: Data("{\"version\":\"\(value)\"}".utf8))
        }
        guard ["synthetic-formula", "synthetic-installed", "synthetic-shared"].contains(name), url.path.contains("/formula/") else {
            return .init(status: 404, body: Data())
        }
        let result = name == "synthetic-installed" ? "2.0-synthetic" : (name == "synthetic-shared" ? "3.0-synthetic" : version)
        return .init(status: 200, body: Data("{\"versions\":{\"stable\":\"\(result)\"},\"homepage\":\"https://example.invalid/synthetic\"}".utf8))
    }
}
