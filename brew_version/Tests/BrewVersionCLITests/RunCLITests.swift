import BrewVersionCLI
@testable import BrewVersionCore
import Foundation
import Testing

private actor StubTransport: HTTPTransport {
    struct Reply: Sendable {
        let path: String
        let status: Int
        let body: String
    }
    var replies: [Reply]
    var newlyAvailable: Reply?
    init(_ replies: [Reply]) { self.replies = replies }
    func makeAvailable(_ reply: Reply) { newlyAvailable = reply }
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        if let reply = newlyAvailable, url.path == reply.path {
            return HTTPResponse(status: reply.status, body: Data(reply.body.utf8))
        }
        guard !replies.isEmpty else {
            Issue.record("Unexpected request: \(url)")
            throw URLError(.badServerResponse)
        }
        let next = replies.removeFirst()
        #expect(url.path == next.path)
        #expect(ifNoneMatch == nil)
        return HTTPResponse(status: next.status, body: Data(next.body.utf8))
    }
}

private final class Recording {
    var out = ""
    var err = ""
    var sleeps: [UInt32] = []
    func environment(_ replies: [StubTransport.Reply], taps: TapIndex = .empty) -> CLIEnvironment {
        CLIEnvironment(transport: StubTransport(replies), writeOut: { self.out += $0 },
                       writeErr: { self.err += $0 }, now: { Date(timeIntervalSince1970: 0) },
                       timestamp: { _ in "T" }, sleep: { self.sleeps.append($0) }, taps: taps)
    }
}

private final class CLITapFixture {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-synthetic-cli-taps-\(UUID().uuidString)")
    init(_ taps: [String] = ["synthetic-owner/homebrew-synthetic-tap"], kind: PackageKind = .formula) throws {
        for name in taps {
            let tap = root.appendingPathComponent("Library/Taps/\(name)")
            let config = tap.appendingPathComponent(".git/config")
            try FileManager.default.createDirectory(at: config.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data("[remote \"origin\"]\n url = https://github.com/\(name).git\n".utf8).write(to: config)
            let file = tap.appendingPathComponent("\(kind == .formula ? "Formula/synthetic-tool" : "Casks/synthetic-app").rb")
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data("# synthetic fixture\n".utf8).write(to: file)
        }
    }
    deinit { try? FileManager.default.removeItem(at: root) }
    var index: TapIndex { TapIndex.scan(prefixes: [HomebrewPrefix(root: root)]) }
}

struct RunCLITests {
    private func tap(_ version: String, repository: String = "homebrew-synthetic-tap",
                     file: String = "Formula/synthetic-tool") -> StubTransport.Reply {
        .init(path: "/synthetic-owner/\(repository)/HEAD/\(file).rb", status: 200, body: "version \"\(version)\"")
    }
    private var missingOfficial: [StubTransport.Reply] {
        [.init(path: "/api/formula/synthetic-tool.json", status: 404, body: ""),
         .init(path: "/api/cask/synthetic-tool.json", status: 404, body: "")]
    }
    private func formula(_ version: String, _ name: String = "synthetic-formula") -> StubTransport.Reply {
        .init(path: "/api/formula/\(name).json", status: 200, body: #"{"versions":{"stable":"\#(version)"}}"#)
    }
    @Test func singlePackagePrintsVersionOnly() async {
        let record = Recording()
        #expect(await runCLI(["synthetic-formula"], environment: record.environment([formula("1.2.3")])) == 0)
        #expect(record.out == "1.2.3\n")
        #expect(record.err.isEmpty)
    }
    @Test func multiplePackagesPrefixNames() async {
        let record = Recording()
        let replies = [formula("1.2.3"),
                       StubTransport.Reply(path: "/api/formula/synthetic-cask.json", status: 404, body: ""),
                       .init(path: "/api/cask/synthetic-cask.json", status: 200, body: #"{"version":"4.5,6"}"#)]
        #expect(await runCLI(["synthetic-formula", "synthetic-cask"], environment: record.environment(replies)) == 0)
        #expect(record.out == "synthetic-formula: 1.2.3\nsynthetic-cask: 4.5,6\n")
        #expect(record.err.isEmpty)
    }
    @Test func errorAfterFirstPackage() async {
        let record = Recording()
        let replies = [formula("1.2.3"), StubTransport.Reply(path: "/api/formula/synthetic-error.json", status: 503, body: "")]
        #expect(await runCLI(["synthetic-formula", "synthetic-error"], environment: record.environment(replies)) == 1)
        #expect(record.out == "synthetic-formula: 1.2.3\n")
        #expect(record.err == LookupError.http(status: 503, PackageName("synthetic-error")!).cliMessage + "\n")
    }
    @Test func invalidArgumentsPrintUsageToStderr() async {
        let record = Recording()
        #expect(await runCLI(["--bogus"], environment: record.environment([])) == 2)
        #expect(record.err == usageText + "\n")
        #expect(record.out.isEmpty)
    }
    @Test func helpAndVersion() async {
        for (argument, expected) in [("--help", usageText + "\n"), ("--version", "brew-version \(BrewVersionRelease.version)\n")] {
            let record = Recording()
            #expect(await runCLI([argument], environment: record.environment([])) == 0)
            #expect(record.out == expected)
            #expect(record.err.isEmpty)
        }
    }
    @Test func untappedFullName() async {
        let record = Recording()
        #expect(await runCLI(["synthetic-owner/synthetic-tap/synthetic-tool"], environment: record.environment([])) == 1)
        #expect(record.out.isEmpty)
        #expect(record.err == "Error: synthetic-owner/synthetic-tap is not tapped.\n")
    }
    @Test func fullTapNamePrintsVersion() async throws {
        let fixture = try CLITapFixture(), record = Recording()
        #expect(await runCLI(["synthetic-owner/synthetic-tap/synthetic-tool"],
                             environment: record.environment([tap("4.5.6")], taps: fixture.index)) == 0)
        #expect(record.out == "4.5.6\n")
        #expect(record.err.isEmpty)
    }
    @Test func fullTapCaskPrintsVersion() async throws {
        let fixture = try CLITapFixture(kind: .cask), record = Recording()
        #expect(await runCLI(["--cask", "synthetic-owner/synthetic-tap/synthetic-app"],
                             environment: record.environment([tap("7.8", file: "Casks/synthetic-app")], taps: fixture.index)) == 0)
        #expect(record.out == "7.8\n")
        #expect(record.err.isEmpty)
    }
    @Test func bareNameFallsBackToTap() async throws {
        let fixture = try CLITapFixture(), record = Recording()
        #expect(await runCLI(["synthetic-tool"],
                             environment: record.environment(missingOfficial + [tap("4.5.6")], taps: fixture.index)) == 0)
        #expect(record.out == "4.5.6\n")
        #expect(record.err.isEmpty)
    }
    @Test func ambiguousBareNameExplains() async throws {
        let fixture = try CLITapFixture(["synthetic-owner/homebrew-synthetic-tap", "synthetic-other/homebrew-synthetic-tap"])
        let record = Recording()
        #expect(await runCLI(["synthetic-tool"], environment: record.environment(missingOfficial, taps: fixture.index)) == 1)
        #expect(record.out.isEmpty)
        #expect(record.err == "Error: synthetic-tool matches several taps: synthetic-other/synthetic-tap/synthetic-tool, synthetic-owner/synthetic-tap/synthetic-tool. Use the full name.\n")
    }
    @Test func watchWorksForTapNames() async throws {
        let fixture = try CLITapFixture(), record = Recording()
        #expect(await runCLI(["--watch=60", "synthetic-owner/synthetic-tap/synthetic-tool"],
                             environment: record.environment([tap("4.5.6"), tap("9.0.1")], taps: fixture.index)) == 0)
        #expect(record.out == "T synthetic-owner/synthetic-tap/synthetic-tool: 4.5.6\nT synthetic-owner/synthetic-tap/synthetic-tool: 9.0.1 (changed from 4.5.6)\n")
        #expect(record.sleeps == [60])
        #expect(record.err.isEmpty)
    }
    @Test func bareWatchKeepsResolvedIdentity() async throws {
        let fixture = try CLITapFixture(), record = Recording()
        let transport = StubTransport(missingOfficial + [tap("4.5.6"), tap("9.0.1")])
        var environment = record.environment([], taps: fixture.index)
        environment.transport = transport
        environment.sleep = { seconds in
            record.sleeps.append(seconds)
            // A new official package becomes available between polls.
            await transport.makeAvailable(self.formula("7.8", "synthetic-tool"))
        }
        #expect(await runCLI(["--watch=60", "synthetic-tool"], environment: environment) == 0)
        #expect(record.out == "T synthetic-owner/synthetic-tap/synthetic-tool: 4.5.6\nT synthetic-owner/synthetic-tap/synthetic-tool: 9.0.1 (changed from 4.5.6)\n")
        #expect(record.sleeps == [60])
        #expect(record.err.isEmpty)
    }
    @Test func bareWatchSourceLossIsAnError() async throws {
        let fixture = try CLITapFixture(), record = Recording()
        let missing = StubTransport.Reply(path: "/synthetic-owner/homebrew-synthetic-tap/HEAD/Formula/synthetic-tool.rb", status: 404, body: "")
        #expect(await runCLI(["--watch=60", "synthetic-tool"],
                             environment: record.environment(missingOfficial + [tap("4.5.6"), missing], taps: fixture.index)) == 1)
        #expect(record.out == "T synthetic-owner/synthetic-tap/synthetic-tool: 4.5.6\n")
        #expect(record.err == "Error: synthetic-owner/synthetic-tap/synthetic-tool not found in synthetic-owner/synthetic-tap.\n")
        #expect(record.sleeps == [60])
    }
    @Test func officialWatchDoesNotFallBackToTap() async throws {
        let fixture = try CLITapFixture(), record = Recording()
        #expect(await runCLI(["--watch=60", "synthetic-tool"],
                             environment: record.environment([formula("4.5.6", "synthetic-tool")] + missingOfficial, taps: fixture.index)) == 1)
        #expect(record.out == "T synthetic-tool: 4.5.6\n")
        #expect(record.err == "Error: synthetic-tool not found in Homebrew (formula cask).\n")
        #expect(record.sleeps == [60])
    }
    @Test func watchPreservesCanonicalPackageName() async throws {
        let fixture = try CLITapFixture(["synthetic-owner/homebrew-homebrew-synthetic-tap"]), record = Recording()
        let replies = [tap("4.5.6", repository: "homebrew-homebrew-synthetic-tap"),
                       tap("9.0.1", repository: "homebrew-homebrew-synthetic-tap")]
        #expect(await runCLI(["--watch=60", "synthetic-owner/homebrew-homebrew-synthetic-tap/synthetic-tool"],
                             environment: record.environment(replies, taps: fixture.index)) == 0)
        #expect(record.out == "T synthetic-owner/homebrew-synthetic-tap/synthetic-tool: 4.5.6\nT synthetic-owner/homebrew-synthetic-tap/synthetic-tool: 9.0.1 (changed from 4.5.6)\n")
        #expect(record.err.isEmpty)
    }
    @Test func watchStopsOnChange() async {
        let record = Recording()
        #expect(await runCLI(["--watch", "60", "synthetic-formula"],
                             environment: record.environment([formula("1.0.0"), formula("1.0.1")])) == 0)
        #expect(record.out == "T synthetic-formula: 1.0.0\nT synthetic-formula: 1.0.1 (changed from 1.0.0)\n")
        #expect(record.sleeps == [60])
        #expect(record.err.isEmpty)
    }
    @Test func watchStopsOnLookupError() async {
        let record = Recording()
        let replies = [formula("1.0.0"), StubTransport.Reply(path: "/api/formula/synthetic-formula.json", status: 503, body: "")]
        #expect(await runCLI(["--watch=60", "synthetic-formula"], environment: record.environment(replies)) == 1)
        #expect(record.out == "T synthetic-formula: 1.0.0\n")
        #expect(record.err == "Error: Homebrew returned HTTP 503 for synthetic-formula.\n")
        #expect(record.sleeps == [60])
    }
    @Test func lookupWithoutDependencyTools() async throws {
        if ProcessInfo.processInfo.environment["BREW_VERSION_ISOLATED_TEST"] == "1" {
            let record = Recording()
            #expect(ProcessInfo.processInfo.environment["PATH"] == "/synthetic-no-tools")
            #expect(await runCLI(["synthetic-formula"], environment: record.environment([formula("1.2.3")])) == 0)
            #expect(record.out == "1.2.3\n")
            #expect(record.err.isEmpty)
            print("synthetic isolated lookup completed")
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: CommandLine.arguments[0])
        // Current SwiftPM loads a Mach-O test bundle with a helper executable;
        // retain that bundle path as well as supporting standalone test runners.
        process.arguments = Array(CommandLine.arguments.dropFirst()) + ["--filter", "RunCLITests/lookupWithoutDependencyTools"]
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = "/synthetic-no-tools"
        environment["BREW_VERSION_ISOLATED_TEST"] = "1"
        process.environment = environment
        let output = Pipe()
        process.standardOutput = output
        process.standardError = output
        try process.run()
        let text = String(decoding: output.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        process.waitUntilExit()
        #expect(process.terminationStatus == 0, "\(text)")
        #expect(text.contains("synthetic isolated lookup completed"), "\(text)")
    }
}
