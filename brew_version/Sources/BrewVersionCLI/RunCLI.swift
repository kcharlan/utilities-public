import BrewVersionCore
import Foundation

public struct CLIEnvironment {
    public var transport: any HTTPTransport
    public var taps: TapIndex
    public var writeOut: (String) -> Void
    public var writeErr: (String) -> Void
    public var now: () -> Date
    public var timestamp: (Date) -> String
    public var sleep: (UInt32) async -> Void

    public init(transport: any HTTPTransport, writeOut: @escaping (String) -> Void,
                writeErr: @escaping (String) -> Void, now: @escaping () -> Date,
                timestamp: @escaping (Date) -> String, sleep: @escaping (UInt32) async -> Void,
                taps: TapIndex = .empty) {
        self.transport = transport
        self.taps = taps
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
        let resolver = PackageResolver(client: HomebrewClient(transport: environment.transport),
                                       tapClient: TapClient(transport: environment.transport), taps: environment.taps)
        var baseline: [String] = []
        var resolvedNames: [PackageName] = []
        while true {
            for (index, package) in options.packages.enumerated() {
                let listing: Listing
                do {
                    if index < resolvedNames.count {
                        listing = try await resolver.lookup(resolvedNames[index], kinds: options.kinds)
                    } else if package.tap == nil {
                        listing = try await resolver.resolveBare(package, kinds: options.kinds)
                    } else {
                        listing = try await resolver.lookup(package, kinds: options.kinds)
                    }
                } catch let error as LookupError {
                    environment.writeErr(error.cliMessage + "\n")
                    return 1
                } catch {
                    environment.writeErr(LookupError.unreachable(package).cliMessage + "\n")
                    return 1
                }
                let version = listing.version
                if options.watchInterval != nil {
                    if resolvedNames.count <= index { resolvedNames.append(listing.name) }
                    let name = resolvedNames[index]
                    let timestamp = environment.timestamp(environment.now())
                    if baseline.count <= index { baseline.append(version) }
                    if version != baseline[index] {
                        environment.writeOut("\(timestamp) \(name): \(version) (changed from \(baseline[index]))\n")
                        return 0
                    }
                    environment.writeOut("\(timestamp) \(name): \(version)\n")
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
