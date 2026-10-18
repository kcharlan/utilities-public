import BrewVersionCore

public enum CLICommand: Equatable {
    case help, version, run(CLIOptions)
}

public struct CLIOptions: Equatable {
    public var kinds: KindPreference
    public var watchInterval: UInt32?
    public var packages: [PackageName]

    public init(kinds: KindPreference, watchInterval: UInt32?, packages: [PackageName]) {
        self.kinds = kinds
        self.watchInterval = watchInterval
        self.packages = packages
    }
}

public func parseArguments(_ arguments: [String]) -> CLICommand? {
    var kinds = KindPreference.auto
    var watching = false
    var interval = "300"
    var packages: [PackageName] = []
    var index = 0
    while index < arguments.count {
        let argument = arguments[index]
        switch argument {
        case "--help", "-h": return .help
        case "--version": return .version
        case "--formula", "--cask":
            let requested: KindPreference = argument == "--formula" ? .formula : .cask
            guard kinds == .auto || kinds == requested else { return nil }
            kinds = requested
        case "--watch":
            watching = true
            if index + 1 < arguments.count {
                let next = arguments[index + 1]
                let prefix = next.hasPrefix("-") ? next.dropFirst() : next[...]
                if let first = prefix.utf8.first, (48...57).contains(first) {
                    interval = next
                    index += 1
                }
            }
        default:
            if argument.hasPrefix("--watch=") {
                watching = true
                interval = String(argument.dropFirst("--watch=".count))
            } else {
                guard let name = PackageName(argument) else { return nil }
                packages.append(name)
            }
        }
        index += 1
    }
    guard !packages.isEmpty, !interval.isEmpty,
          interval.utf8.allSatisfy({ (48...57).contains($0) }),
          let seconds = UInt32(interval), seconds > 0 else { return nil }
    return .run(CLIOptions(kinds: kinds, watchInterval: watching ? seconds : nil, packages: packages))
}
