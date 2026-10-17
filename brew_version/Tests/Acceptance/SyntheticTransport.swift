import Foundation
import BrewVersionCore

actor SyntheticTransport: HTTPTransport {
    private var version = "1.0-synthetic"
    func advance() { version = "2.0-synthetic" }
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        if url.path == "/api/formula.json" {
            return .init(status: 200, body: Data("[{\"name\":\"synthetic-installed\",\"versions\":{\"stable\":\"2.0-synthetic\"}}]".utf8))
        }
        if url.path == "/api/cask.json" {
            return .init(status: 200, body: Data(#"[{"token":"synthetic-cask","version":"1.0-synthetic"}]"#.utf8))
        }
        guard ["synthetic-formula.json", "synthetic-installed.json"].contains(url.lastPathComponent), url.path.contains("/formula/") else {
            return .init(status: 404, body: Data())
        }
        let result = url.lastPathComponent == "synthetic-installed.json" ? "2.0-synthetic" : version
        return .init(status: 200, body: Data("{\"versions\":{\"stable\":\"\(result)\"},\"homepage\":\"https://example.invalid/synthetic\"}".utf8))
    }
}
