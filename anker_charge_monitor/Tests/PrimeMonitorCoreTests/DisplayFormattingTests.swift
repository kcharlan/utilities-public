import Testing
@testable import PrimeMonitorCore

@Test func formatterShowsFieldResolutionAndNeverMore() {
    #expect(DisplayFormatter.watts(centi: 456) == "4.56 W")
    #expect(DisplayFormatter.watts(centi: 0) == "0.00 W")
    #expect(DisplayFormatter.volts(milli: 12345) == "12.345 V")
    #expect(DisplayFormatter.amps(milli: 20) == "0.020 A")
    #expect(DisplayFormatter.amps(milli: -5) == "-0.005 A")
    #expect(DisplayFormatter.watts(centi: -456) == "-4.56 W")
    #expect(DisplayFormatter.amps(milli: Int.min) == "-9223372036854775.808 A")
}
@Test func wattsAcceptsACompactUnitSeparator() {
    #expect(DisplayFormatter.watts(centi: 448, separator: "\u{2009}") == "4.48\u{2009}W")
    #expect(DisplayFormatter.watts(centi: -5, separator: "") == "-0.05W")
}
@Test func menuBarTextSizesRunFromTenToTheSystemMenuBarSize() {
    #expect(MenuBarTextSize.allCases.map(\.pointSize) == [10, 11, 12, 13])
    #expect(MenuBarTextSize.default == .pt13)
}
@Test func ageReadsInWholeUnits() {
    #expect(DisplayFormatter.age(3) == "3 s ago" && DisplayFormatter.age(125) == "2 min ago")
    #expect(DisplayFormatter.age(59.9) == "59 s ago")
    #expect(DisplayFormatter.age(60) == "1 min ago")
}
