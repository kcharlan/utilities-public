import Foundation
import Testing
@testable import BrewVersionCore

struct TapVersionDetectorTests {
    // Changing parser order, form decoding, filename stems or tag precedence
    // must fail against the independently generated Homebrew results.
    @Test func matchesHomebrewCorpus() throws {
        struct Corpus: Decodable {
            struct Parser: Decodable { let index: Int }
            struct Row: Decodable {
                let url: String
                let tag: String?
                let version: String?
                let parserIndex: Int?
            }
            let homebrewCommit: String
            let parsers: [Parser]
            let rows: [Row]
        }
        let url = try #require(Bundle.module.url(forResource: "tap-url-versions", withExtension: "json", subdirectory: "Fixtures"))
        let corpus = try JSONDecoder().decode(Corpus.self, from: Data(contentsOf: url))
        #expect(corpus.homebrewCommit == "3073d6a8c34f71da054b000cfdbb62594a07c969")
        #expect(Set(corpus.rows.compactMap(\.parserIndex)) == Set(corpus.parsers.map(\.index)))
        for row in corpus.rows {
            #expect(TapVersionDetector.detect(url: row.url, tag: row.tag) == row.version,
                    "URL: \(row.url), tag: \(row.tag ?? "nil"), parser: \(row.parserIndex.map(String.init) ?? "nil")")
        }
    }
}
