import Foundation
import PrimeMonitorCore

struct StoredSecrets: Equatable, Sendable {
    var credentials: AnkerCredentials
    var session: AccountSession?
}

/// Providers retrieve a coherent account pair. Sessions belong only to the cache.
protocol CredentialProvider: Sendable {
    func retrieve() async throws -> AnkerCredentials
}
/// Nonsecret provider settings. Only composition/settings interpret these keys;
/// the controller compares the complete selection as an opaque cache context.
struct CredentialSelection: Codable, Equatable, Sendable {
    var provider: String
    var settings: [String: String]
}
enum CredentialFailure: Error, Equatable {
    case missingCLI, unavailable, malformed, timedOut, outputLimit, unsupported
    var message: String {
        switch self {
        case .missingCLI: "Install the selected vault provider's CLI, then Retry."
        case .unavailable: "Open and unlock your vault, check integration and access permissions, then Retry."
        case .malformed: "Check the selected Login item's username and password fields, then Retry."
        case .timedOut: "Credential retrieval timed out. Open and unlock your vault, then Retry."
        case .outputLimit: "The credential response exceeded its limit. Check the Login item, then Retry."
        case .unsupported: "Select a supported credential provider, then Retry."
        }
    }
}
@MainActor protocol SecretStore {
    var configured: Bool { get }
    func load() async throws -> StoredSecrets?
    func load(reload: Bool) async throws -> StoredSecrets?
    func replaceProvider(_ provider: (any CredentialProvider)?, selection: CredentialSelection?)
    func save(_ value: StoredSecrets) throws
    func delete() throws
}
extension SecretStore {
    var configured: Bool { true }
    func load(reload: Bool) async throws -> StoredSecrets? { try await load() }
    func replaceProvider(_ provider: (any CredentialProvider)?) { replaceProvider(provider, selection: nil) }
}

/// No disk writes, Keychain access, or vault writes. Generation checks also reject
/// providers that ignore task cancellation and return after sign-out/reconfiguration.
@MainActor final class MemorySessionStore: SecretStore {
    private var provider: (any CredentialProvider)?
    private var selection: CredentialSelection?
    private var value: StoredSecrets?
    private var generation = UUID()
    var configured: Bool { provider != nil }
    func replaceProvider(_ provider: (any CredentialProvider)?, selection: CredentialSelection?) {
        // Reconstructing a controller is not a new account context. Preserve
        // credentials/session only when the full opaque selection matches.
        if let selection, selection == self.selection, provider != nil, self.provider != nil {
            self.provider = provider; return
        }
        generation = UUID(); value = nil; self.provider = provider; self.selection = selection
    }
    func load() async throws -> StoredSecrets? { try await load(reload: false) }
    func load(reload: Bool) async throws -> StoredSecrets? {
        if !reload, let value { return value }
        guard let provider else { return nil }
        generation = UUID()
        let expected = generation
        let credentials = try await provider.retrieve()
        try Task.checkCancellation()
        guard generation == expected else { throw CancellationError() }
        let candidate = StoredSecrets(credentials: credentials, session: nil)
        value = candidate; return candidate
    }
    func save(_ value: StoredSecrets) throws { self.value = value }
    func delete() throws { replaceProvider(nil) }
}
