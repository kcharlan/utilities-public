import Foundation
import Testing
@testable import AnkerCloud

/// Stands in for NWConnection beneath the real NWMQTTLink: it holds every write's
/// completion, as a connection with a stalled socket would, and delivers late
/// completions on the link's queue as NWConnection does.
private final class HeldConnection: MQTTByteConnection, @unchecked Sendable {
    private let lock = NSLock()
    private let queue: DispatchQueue
    private var completions: [@Sendable (Error?) -> Void] = []
    private var writes: [Data] = []
    private var cancels = 0
    init(queue: DispatchQueue) { self.queue = queue }
    func transmit(_ data: Data, completion: @escaping @Sendable (Error?) -> Void) {
        lock.withLock { writes.append(data); completions.append(completion) }
    }
    func cancel() { lock.withLock { cancels += 1 } }
    var heldCount: Int { lock.withLock { completions.count } }
    var writeCount: Int { lock.withLock { writes.count } }
    var cancelCount: Int { lock.withLock { cancels } }
    /// Completes the oldest held write on the link's queue and waits until it ran.
    func complete(_ error: Error?) {
        let completion = lock.withLock { completions.isEmpty ? nil : completions.removeFirst() }
        queue.sync { completion?(error) }
    }
}

private final class Outcomes: @unchecked Sendable {
    private let lock = NSLock()
    private var results: [String] = []
    func record(_ result: String) { lock.withLock { results.append(result) } }
    var all: [String] { lock.withLock { results } }
}

private func waitUntil(_ predicate: () -> Bool) async throws {
    for _ in 0..<2000 { if predicate() { return }; try await Task.sleep(for: .milliseconds(1)) }
    Issue.record("condition did not become true"); throw MQTTConnectionError.timeout
}

private func send(_ link: NWMQTTLink, recording outcomes: Outcomes) -> Task<Void, Never> {
    Task {
        do { try await link.send(.pingreq); outcomes.record("sent") }
        catch MQTTConnectionError.closed { outcomes.record("closed") }
        catch { outcomes.record("other") }
    }
}

@Suite struct MQTTLinkDisposalTests {
    @Test func completedWriteResumesItsSendOnce() async throws {
        let queue = DispatchQueue(label: "test.link"), connection = HeldConnection(queue: queue)
        let link = NWMQTTLink(queue: queue, attached: connection), outcomes = Outcomes()
        let sending = send(link, recording: outcomes)
        try await waitUntil { connection.heldCount == 1 }
        connection.complete(nil)
        await sending.value
        #expect(outcomes.all == ["sent"])
        await link.close()
        #expect(connection.cancelCount == 1)
    }

    @Test func failedWriteThrowsItsError() async throws {
        let queue = DispatchQueue(label: "test.link"), connection = HeldConnection(queue: queue)
        let link = NWMQTTLink(queue: queue, attached: connection), outcomes = Outcomes()
        let sending = send(link, recording: outcomes)
        try await waitUntil { connection.heldCount == 1 }
        connection.complete(URLError(.networkConnectionLost))
        await sending.value
        #expect(outcomes.all == ["other"])
        await link.close()
    }

    /// The held writes outlive any deadline: only close can end them. Their tasks
    /// are never cancelled, so the sends return because close disposed of them.
    @Test func closeResumesHeldSendsOnceAndLateCallbacksAreInert() async throws {
        let queue = DispatchQueue(label: "test.link"), connection = HeldConnection(queue: queue)
        let link = NWMQTTLink(queue: queue, attached: connection), outcomes = Outcomes()
        let first = send(link, recording: outcomes), second = send(link, recording: outcomes)
        try await waitUntil { connection.heldCount == 2 }
        try await Task.sleep(for: .milliseconds(20))
        #expect(outcomes.all.isEmpty, "Held writes must stay pending until disposed")
        await link.close()
        // close returns only after resuming every pending send.
        try await waitUntil { outcomes.all.count == 2 }
        await first.value; await second.value
        #expect(outcomes.all == ["closed", "closed"])
        #expect(connection.cancelCount == 1)
        // NWConnection may still call back after cancellation, with or without an
        // error. Each late callback must not resume a continuation again (a second
        // resume traps) and must not change any outcome.
        connection.complete(nil)
        connection.complete(URLError(.cancelled))
        #expect(outcomes.all == ["closed", "closed"])
        // A send after close never reaches the connection.
        await send(link, recording: outcomes).value
        #expect(outcomes.all == ["closed", "closed", "closed"])
        #expect(connection.writeCount == 2)
        // A repeated close is harmless.
        await link.close()
        #expect(connection.cancelCount == 1)
    }
}
