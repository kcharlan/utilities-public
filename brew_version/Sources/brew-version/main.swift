import BrewVersionCLI
import BrewVersionCore
import Darwin
import Foundation

setvbuf(stdout, nil, _IOLBF, 0)
let prefixes = HomebrewPrefix.detectAll(candidates: [URL(fileURLWithPath: "/opt/homebrew"), URL(fileURLWithPath: "/usr/local")])
let environment = CLIEnvironment(
    transport: URLSessionTransport.standard(),
    writeOut: { print($0, terminator: "") },
    writeErr: { FileHandle.standardError.write(Data($0.utf8)) },
    now: Date.init,
    timestamp: strftimeTimestamp,
    sleep: { seconds in try? await Task.sleep(for: .seconds(seconds)) },
    taps: TapIndex.scan(prefixes: prefixes)
)
let status = await runCLI(Array(CommandLine.arguments.dropFirst()), environment: environment)
exit(status)
