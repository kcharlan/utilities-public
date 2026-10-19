import Foundation
import Testing
@testable import AnkerCloud

@Test func throttleKeepsMinimumGapIncludingResponseTimeAndFailedAttempts() async throws {
    let clock = RESTClock()
    let transport = ScriptedREST([.init(elapsed: 2), .init(status: 500), .init()], clock: clock)
    let client = restClient(transport, clock)
    await client.restore(restoredSession(clock), credentials: restCredentials)
    _ = try await client.listChargers()
    await #expect(throws: AnkerError.http(500)) { try await client.listChargers() }
    _ = try await client.listChargers()
    #expect(abs(clock.sleeps.reduce(0,+) - 0.6) < 0.00001)
}

@Test func randomDelayStillAppliesMarkedEndpointLimit() async {
    let clock = RESTClock()
    let throttle = RequestThrottle(now: { clock.now() }, sleep: { await clock.sleep($0) })
    for index in 0..<10 {
        await throttle.acquire(endpoint: "synthetic")
        await throttle.finish(endpoint: "synthetic", status: index == 9 ? 429 : 200)
    }
    await throttle.acquire(endpoint: "synthetic", delay: 4)
    #expect(abs(clock.now().timeIntervalSince1970 - 1_700_000_065) < 0.00001)
    await throttle.finish(endpoint: "synthetic", status: 200)
}

@Test func overlappingRequestsKeepGlobalResponseGap() async throws {
    let clock = RESTClock()
    let transport = ScriptedREST(Array(repeating: .init(elapsed: 2), count: 12), clock: clock)
    let client = restClient(transport, clock)
    await client.restore(restoredSession(clock), credentials: restCredentials)
    try await withThrowingTaskGroup(of: Void.self) { group in
        for _ in 0..<12 { group.addTask { _ = try await client.listChargers() } }
        try await group.waitForAll()
    }
    let times = await transport.sentAt
    #expect(times.count == 12)
    for (first, second) in zip(times, times.dropFirst()) {
        #expect(second.timeIntervalSince(first) >= 2.29999)
    }
}

@Test func endpointWindowIncludesUpstreamTwoSecondMargin() async {
    let clock = RESTClock()
    let throttle = RequestThrottle(now: { clock.now() }, sleep: { await clock.sleep($0) })
    for index in 0..<10 {
        await throttle.acquire(endpoint: "synthetic")
        await throttle.finish(endpoint: "synthetic", status: index == 9 ? 429 : 200)
    }
    clock.advance(58.3) // Oldest attempt is 61 seconds old: still inside upstream's 62-second window.
    await throttle.acquire(endpoint: "synthetic")
    #expect(abs(clock.now().timeIntervalSince1970 - 1_700_000_065) < 0.00001)
    await throttle.finish(endpoint: "synthetic", status: 200)
}
