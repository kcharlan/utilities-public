import Foundation

/// Ports anker-solix-api `session.py`, _wait_delay / request, and
/// `apitypes.py`, REQUEST_DELAY_DEF / ENDPOINT_LIMIT_DEF, commit 8a5222b.
/// `helpers.py`, RequestCounter.last_minute, retains a 62-second window.
/// A permit spans the transport await, so actor reentrancy cannot bypass gaps.
actor RequestThrottle {
    private let now: @Sendable () -> Date
    private let sleep: @Sendable (TimeInterval) async -> Void
    private var occupied = false
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private var lastResponse: Date?
    private var history: [(Date, String)] = []
    private var throttled: Set<String> = []

    init(now: @escaping @Sendable () -> Date, sleep: @escaping @Sendable (TimeInterval) async -> Void) {
        self.now = now
        self.sleep = sleep
    }

    func acquire(endpoint: String, delay: TimeInterval? = nil) async {
        if occupied { await withCheckedContinuation { waiters.append($0) } }
        else { occupied = true }
        if let delay, let lastResponse {
            let wait = max(0, delay - now().timeIntervalSince(lastResponse))
            if wait > 0 { await sleep(wait) }
        }
        let date = now()
        history.removeAll { date.timeIntervalSince($0.0) >= 62 }
        let same = history.filter { $0.1 == endpoint }
        let endpointDelay: TimeInterval
        if throttled.contains(endpoint), same.count >= 10, let oldest = same.first {
            endpointDelay = 65 - date.timeIntervalSince(oldest.0)
        } else { endpointDelay = 0 }
        let gap = lastResponse.map { 0.3 - date.timeIntervalSince($0) } ?? 0
        let wait = max(0, gap, endpointDelay)
        if wait > 0 { await sleep(wait) }
    }

    func finish(endpoint: String, status: Int?) {
        // Include transport failures: otherwise repeated timeouts evade rate limits.
        let date = now()
        lastResponse = date
        history.append((date, endpoint))
        if status == 429 { throttled.insert(endpoint) }
        release()
    }

    func release() {
        if waiters.isEmpty { occupied = false }
        else { waiters.removeFirst().resume() }
    }
}
