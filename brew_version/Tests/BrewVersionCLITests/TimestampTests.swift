import BrewVersionCLI
import Foundation
import Testing

struct TimestampTests {
    @Test func matchesDate() throws {
        let epoch = 1_700_000_000
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/date")
        process.arguments = ["-r", String(epoch), "+%Y-%m-%d %H:%M:%S %Z"]
        let output = Pipe()
        process.standardOutput = output
        try process.run()
        let expected = String(decoding: output.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        process.waitUntilExit()
        #expect(process.terminationStatus == 0)
        #expect(strftimeTimestamp(Date(timeIntervalSince1970: Double(epoch))) + "\n" == expected)
    }
}
