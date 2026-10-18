import BrewVersionCore
import Foundation

public struct CLIEnvironment {
    public var transport: any HTTPTransport
    public var writeOut: (String) -> Void
    public var writeErr: (String) -> Void
    public var now: () -> Date
    public var timestamp: (Date) -> String
    public var sleep: (UInt32) async -> Void

    public init(transport: any HTTPTransport, writeOut: @escaping (String) -> Void,
                writeErr: @escaping (String) -> Void, now: @escaping () -> Date,
                timestamp: @escaping (Date) -> String, sleep: @escaping (UInt32) async -> Void) {
        self.transport = transport
        self.writeOut = writeOut
        self.writeErr = writeErr
        self.now = now
        self.timestamp = timestamp
        self.sleep = sleep
    }
}

public func runCLI(_ arguments: [String], environment: CLIEnvironment) async -> Int32 {
    guard let command = parseArguments(arguments) else {
        environment.writeErr(usageText + "\n")
        return 2
    }
    switch command {
    case .help:
        environment.writeOut(usageText + "\n")
        return 0
    case .version:
        environment.writeOut("brew-version \(BrewVersionRelease.version)\n")
        return 0
    case .run(let options):
        let client = HomebrewClient(transport: environment.transport)
        var baseline: [String] = []
        while true {
            for (index, package) in options.packages.enumerated() {
                let version: String
                do {
                    version = try await client.lookup(package, kinds: options.kinds).version
                } catch let error as LookupError {
                    environment.writeErr(error.cliMessage + "\n")
                    return 1
                } catch {
                    environment.writeErr(LookupError.unreachable(package).cliMessage + "\n")
                    return 1
                }
                if options.watchInterval != nil {
                    let timestamp = environment.timestamp(environment.now())
                    if baseline.count <= index { baseline.append(version) }
                    if version != baseline[index] {
                        environment.writeOut("\(timestamp) \(package): \(version) (changed from \(baseline[index]))\n")
                        return 0
                    }
                    environment.writeOut("\(timestamp) \(package): \(version)\n")
                } else if options.packages.count > 1 {
                    environment.writeOut("\(package): \(version)\n")
                } else {
                    environment.writeOut(version + "\n")
                }
            }
            guard let seconds = options.watchInterval else { return 0 }
            await environment.sleep(seconds)
        }
    }
}
