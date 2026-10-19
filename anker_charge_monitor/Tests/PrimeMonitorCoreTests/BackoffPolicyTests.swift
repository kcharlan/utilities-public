import Testing
import PrimeMonitorCore

@Test func backoffDoublesToCapAndResets() {
    var backoff = BackoffPolicy()
    #expect((0..<9).map { _ in backoff.nextDelay() } == [1, 2, 4, 8, 16, 32, 64, 120, 120])
    backoff.reset()
    #expect(backoff.nextDelay() == 1)
    #expect(backoff.nextDelay() == 2)
}
