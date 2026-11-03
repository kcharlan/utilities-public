import Foundation
import Testing
import TelltaleCore

private struct DescriptiveFailure: Error, CustomStringConvertible {
    var description: String { "synthetic description" }
}
private struct BothFailure: LocalizedError, CustomStringConvertible {
    var description: String { "synthetic description" }
    var errorDescription: String? { "synthetic localized description" }
}
private struct PlainFailure: Error {}
private final class SyntheticNSError: NSError, @unchecked Sendable {}

@Suite struct ReadFailureTests {
    @Test func precedence() {
        #expect(readFailureReason(DescriptiveFailure()) == "synthetic description")
        #expect(readFailureReason(BothFailure()) == "synthetic description")
        let ns = NSError(domain: "synthetic", code: 1, userInfo: [NSLocalizedDescriptionKey: "synthetic NSError"])
        let subclass = SyntheticNSError(domain: "synthetic", code: 2, userInfo: [NSLocalizedDescriptionKey: "synthetic subclass"])
        let cocoa = CocoaError(.fileReadNoPermission)
        let plain = PlainFailure()
        #expect(readFailureReason(ns) == ns.localizedDescription)
        #expect(readFailureReason(subclass) == subclass.localizedDescription)
        #expect(readFailureReason(cocoa) == cocoa.localizedDescription)
        #expect(readFailureReason(plain) == plain.localizedDescription)
    }
}
