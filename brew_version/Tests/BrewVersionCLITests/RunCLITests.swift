import BrewVersionCLI
import BrewVersionCore
import Foundation
import Testing

private actor StubTransport: HTTPTransport {
    struct Reply: Sendable {
        let path: String
        let status: Int
        let body: String
    }
    var replies: [Reply]
    init(_ replies: [Reply]) { self.replies = replies }
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
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
    func environment(_ replies: [StubTransport.Reply]) -> CLIEnvironment {
        CLIEnvironment(transport: StubTransport(replies), writeOut: { self.out += $0 },
                       writeErr: { self.err += $0 }, now: { Date(timeIntervalSince1970: 0) },
                       timestamp: { _ in "T" }, sleep: { self.sleeps.append($0) })
    }
}

struct RunCLITests {
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
