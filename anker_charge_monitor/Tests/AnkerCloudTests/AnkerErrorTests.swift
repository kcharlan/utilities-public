import Testing
@testable import AnkerCloud

@Test func everyUpstreamErrorCodeMaps() {
    let message = "synthetic upstream message"
    // Complete ERRORS table from errors.py:92–121, baseline 8a5222b.
    let cases: [(Int, AnkerError)] = [
        (401, .authorization), (403, .authorization), (429, .throttled),
        (502, .connect), (504, .connect), (997, .connect), (998, .network), (999, .server),
        (10000, .code(10000, message)), (10003, .code(10003, message)),
        (10004, .code(10004, message)), (10007, .code(10007, message)), (21105, .busy),
        (26050, .verificationRequired), (26051, .verificationRequired), (26052, .verificationRequired),
        (26053, .verificationRequired), (26054, .verificationRequired), (26055, .verificationRequired),
        (26070, .code(26070, message)), (26084, .kickedOut),
        (26108, .invalidCredentials), (26156, .invalidCredentials), (26161, .code(26161, message)),
        (31001, .code(31001, message)), (31003, .code(31003, message)),
        (100053, .retryExceeded), (160003, .code(160003, message))
    ]
    for (code, expected) in cases {
        #expect(AnkerError.from(code: code, message: message) == expected)
    }
}

@Test func unknownHighCodesPreserveCodeAndMessageAndLowCodesAreNotErrors() {
    for code in [10001, 26056, 999_999, Int.max] {
        #expect(AnkerError.from(code: code, message: "synthetic detail") == .code(code, "synthetic detail"))
    }
    for code in [Int.min, -1, 0, 1, 200, 400, 500, 522, 996, 1000, 9999] {
        #expect(AnkerError.from(code: code, message: "synthetic detail") == nil)
    }
}
