import BrewVersionCore
import BrewVersionCLI
import Testing

struct ArgumentsTests {
    @Test func table() {
        func run(_ names: [String] = ["x"], _ kind: KindPreference = .auto, _ interval: UInt32? = nil) -> CLICommand {
            .run(CLIOptions(kinds: kind, watchInterval: interval, packages: names.map { PackageName($0)! }))
        }
        let cases: [([String], CLICommand?)] = [
            ([], nil), (["synthetic-formula"], run(["synthetic-formula"])),
            (["--formula", "--cask", "x"], nil), (["--cask", "--cask", "x"], run(["x"], .cask)),
            (["--watch", "x"], run(["x"], .auto, 300)),
            (["--watch", "60", "x"], run(["x"], .auto, 60)),
            (["--watch=60", "x"], run(["x"], .auto, 60)),
            (["--watch", "0300", "x"], run(["x"], .auto, 300)),
            (["--watch", "-5", "x"], nil), (["--watch", "0", "x"], nil),
            (["--watch=", "x"], nil), (["--watch", "5x", "y"], nil),
            (["--watch", "1.5", "x"], nil), (["--watch", "4294967296", "x"], nil),
            (["-x"], nil), (["Synthetic"], nil), (["x", "--help"], .help),
            (["-h"], .help), (["--bogus", "--help"], nil), (["--version"], .version),
            (["--watch=0", "--help"], .help),
            (["--watch=0", "--watch", "x"], nil),
            (["--watch=0", "--watch=1", "x"], run(["x"], .auto, 1)),
            (["--watch", "4294967295", "x"], run(["x"], .auto, UInt32.max)),
            (["--watch", "+5", "x"], nil), (["x", "x"], run(["x", "x"])),
            (["--formula", "x", "--formula"], run(["x"], .formula))
        ]
        for (arguments, expected) in cases {
            #expect(parseArguments(arguments) == expected, "Arguments: \(arguments)")
        }
    }
}
