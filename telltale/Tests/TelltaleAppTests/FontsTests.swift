import AppKit
import Testing
import TelltaleTestSupport
@testable import Telltale

/// Spec section 9.2: Barlow Semi Condensed is bundled and registered at launch. The fonts in the
/// source tree are the ones `make release` copies into the bundle.
@MainActor @Suite(.serialized) struct FontsTests {
    static let directory = TestPaths.packageRoot.appending(path: "Resources/Fonts", directoryHint: .isDirectory)

    /// The PostScript names listed in `Resources/Fonts/SOURCE.md`'s table.
    static func listedPostScriptNames() throws -> [String] {
        let text = try String(contentsOf: directory.appending(path: "SOURCE.md"), encoding: .utf8)
        return text.split(separator: "\n").compactMap { line -> String? in
            let cells = line.split(separator: "|", omittingEmptySubsequences: false).map { $0.trimmingCharacters(in: .whitespaces) }
            guard cells.count > 3, cells[1].hasSuffix(".ttf"), !cells[2].isEmpty else { return nil }
            return cells[2]
        }
    }

    @Test func registersBundledFonts() throws {
        let names = try Self.listedPostScriptNames()
        #expect(names == [Fonts.regular, Fonts.medium])
        var logged: [String] = []
        #expect(Fonts.register(from: Self.directory, log: { logged.append($0) }))
        // Registering again (a second window, a relaunch in tests) is not a failure.
        #expect(Fonts.register(from: Self.directory, log: { logged.append($0) }))
        #expect(logged.isEmpty)
        for name in names {
            let font = try #require(NSFont(name: name, size: 20), "\(name) did not resolve")
            #expect(font.fontName == name)
        }
        #expect(Fonts.isAvailable)
    }

    @Test func missingFontsFallBackToTheSystemFontAndLog() throws {
        try withScratchDirectory { directory in
            var logged: [String] = []
            #expect(!Fonts.register(from: directory.appending(path: "Missing", directoryHint: .isDirectory), log: { logged.append($0) }))
            #expect(logged.count == 1)
            try Data("not a font".utf8).write(to: directory.appending(path: "Broken.ttf"))
            logged = []
            #expect(!Fonts.register(from: directory, log: { logged.append($0) }))
            #expect(logged.count == 1 && logged[0].contains("Broken.ttf"))
        }
    }
}
