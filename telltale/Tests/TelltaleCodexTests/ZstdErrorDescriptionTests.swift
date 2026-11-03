import Testing
import TelltaleCodex
import TelltaleCore

@Suite struct ZstdErrorDescriptionTests {
    @Test func descriptionsPreserveReasons() {
        let cases: [(ZstdError, String)] = [(.truncated, "truncated"), (.corrupt("synthetic corruption"), "synthetic corruption"), (.io("synthetic I/O"), "synthetic I/O")]
        for (error, reason) in cases {
            #expect(error.description.contains(reason))
            #expect(readFailureReason(error) == error.description)
            #expect(error.description.contains("compressed"))
        }
    }
}
