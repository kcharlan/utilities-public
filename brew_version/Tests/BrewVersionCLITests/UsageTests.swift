import BrewVersionCLI
import Foundation
import Testing

struct UsageTests {
    @Test func expectedHelp() throws {
        let url = Bundle.module.url(forResource: "expected-help", withExtension: "txt", subdirectory: "Fixtures")!
        #expect(usageText + "\n" == (try String(contentsOf: url, encoding: .utf8)))
        #expect(usageText.contains("  --version          Show the brew-version version."))
        #expect(usageText.contains("  1  Lookup error"))
        #expect(!usageText.contains("Requires curl and jq"))
    }
}
