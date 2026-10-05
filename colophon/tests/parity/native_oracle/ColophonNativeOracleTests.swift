import Foundation
import XCTest
@testable import CodexBarCore

/// Maintainer exporter. This calls the unmodified app cache path; it does not
/// select files, rebuild reports, or price rows. Run only through the guard.
final class ColophonNativeOracleTests: XCTestCase {
    /// Separate synthetic regression, never invoked by the acceptance exporter.
    func testSyntheticCountsAndWindow() async throws {
        let environment = ProcessInfo.processInfo.environment
        let fakeHome = try XCTUnwrap(environment["CFFIXED_USER_HOME"])
        let codexHome = try XCTUnwrap(environment["CODEX_HOME"])
        let inputURL = URL(fileURLWithPath: fakeHome).appendingPathComponent("native-input.json")
        let input = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: inputURL)) as? [String: Any])
        let expected = try XCTUnwrap(input["syntheticExpectedInputTokens"] as? [String: Int])
        XCTAssertGreaterThanOrEqual(expected.count, 2)
        XCTAssertTrue(expected.keys.allSatisfy { $0.hasPrefix("synthetic-") })
        let now = Date(timeIntervalSince1970: try XCTUnwrap(input["nowUnixMs"] as? NSNumber).doubleValue / 1000)
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(identifier: try XCTUnwrap(input["bucket_tz"] as? String)))
        let fetcher = CostUsageFetcher(calendar: calendar)
        let allLoaded = await fetcher.loadCachedCodexTokenSnapshotForScopedHome(
            now: now, codexHomePath: codexHome, historyDays: CostReportingPeriod.allTime.days(now: now, calendar: calendar),
            includePiSessions: false, includeProjectAndSessionBreakdowns: true, calendar: calendar)
        let all = try XCTUnwrap(allLoaded)
        XCTAssertEqual(Set(all.sessions.map(\.sessionID)), Set(expected.keys))
        for session in all.sessions {
            XCTAssertEqual(session.inputTokens, expected[session.sessionID])
        }
        let todayLoaded = await fetcher.loadCachedCodexTokenSnapshotForScopedHome(
            now: now, codexHomePath: codexHome, historyDays: 1, includePiSessions: false,
            includeProjectAndSessionBreakdowns: true, calendar: calendar)
        let today = try XCTUnwrap(todayLoaded)
        XCTAssertTrue(today.sessions.isEmpty, "synthetic historical sessions must be omitted from today's window")
    }

    func testExportScopedSnapshot() async throws {
        let environment = ProcessInfo.processInfo.environment
        let fakeHome = try XCTUnwrap(environment["CFFIXED_USER_HOME"])
        let codexHome = try XCTUnwrap(environment["CODEX_HOME"])
        let inputURL = URL(fileURLWithPath: fakeHome).appendingPathComponent("native-input.json")
        let input = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: inputURL)) as? [String: Any])
        let zone = try XCTUnwrap(input["bucket_tz"] as? String)
        let nowMillis = try XCTUnwrap(input["nowUnixMs"] as? NSNumber)
        let now = Date(timeIntervalSince1970: nowMillis.doubleValue / 1000)
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(identifier: zone))
        let days = CostReportingPeriod.allTime.days(now: now, calendar: calendar)
        let cacheRoot = URL(fileURLWithPath: fakeHome).appendingPathComponent("Library/Caches/CodexBar")
        let options = CostUsageScanner.Options(
            codexSessionsRoot: URL(fileURLWithPath: codexHome).appendingPathComponent("sessions"),
            cacheRoot: cacheRoot, calendar: calendar)
        let roots = CostUsageScanner.codexSessionsRoots(options: options)
        let range = CostUsageScanner.CostUsageDayRange(
            since: CostReportingPeriod.rolling(days: days).bounds(now: now, calendar: calendar).lowerBound,
            until: now, calendar: calendar)
        let cache = CostUsageScanner.codexCache(
            CostUsageStore(cacheRoot: cacheRoot).syncLoadCodexCache(calendar: calendar, loadTokenSnapshots: false),
            scopedTo: roots)
        let fileFacts = cache.files.sorted { $0.key < $1.key }.map { path, usage -> [String: Any] in
            var single = CostUsageCache()
            single.files[path] = usage
            return ["path": path, "sessionID": usage.sessionId as Any? ?? NSNull(),
                "parentID": usage.forkedFromId as Any? ?? NSNull(),
                "unresolvedMissingParent": CostUsageScanner.isUnresolvedMissingParentFork(usage),
                "hasBilledTokens": CostUsageScanner.codexFileHasBilledTokens(usage),
                "unmeteredDays": CostUsageScanner.unresolvedForkUnmeteredCounts(cache: single, range: range)]
        }
        let loaded = await CostUsageFetcher(calendar: calendar).loadCachedCodexTokenSnapshotForScopedHome(
            now: now, codexHomePath: codexHome, historyDays: days, includePiSessions: false,
            includeProjectAndSessionBreakdowns: true, calendar: calendar)
        var result: [String: Any] = ["available": loaded != nil, "sessions": [:], "daily": [], "projects": [],
            "historyCoverageIsEstablished": NSNull(), "historyScanIsPartial": NSNull(),
            "bucket_tz": zone, "nowUnixMs": nowMillis, "historyDays": days, "fileFacts": fileFacts]
        if let loaded {
            let snapshot = loaded.reporting(.allTime)
            var sessions: [String: Any] = [:]
            for session in snapshot.sessions {
                XCTAssertNil(sessions[session.sessionID], "native snapshot emitted duplicate IDs")
                sessions[session.sessionID] = [
                    "sessionID": session.sessionID,
                    "lastActivityUnixMs": Int64(session.lastActivity.timeIntervalSince1970 * 1000),
                    "inputTokens": session.inputTokens as Any? ?? NSNull(),
                    "cachedInputTokens": session.cachedInputTokens as Any? ?? NSNull(),
                    "outputTokens": session.outputTokens as Any? ?? NSNull(),
                    "reasoningTokens": session.reasoningTokens as Any? ?? NSNull(),
                    "totalTokens": session.totalTokens as Any? ?? NSNull(),
                    "requestCount": session.requestCount as Any? ?? NSNull(),
                    "costUSD": session.costUSD as Any? ?? NSNull(),
                    "projectPath": session.projectPath as Any? ?? NSNull(),
                    "modelBreakdowns": try Self.json(session.modelBreakdowns)]
            }
            result["sessions"] = sessions
            result["daily"] = try Self.json(snapshot.daily)
            result["projects"] = try snapshot.projects.map { project -> [String: Any] in
                ["path": project.path as Any? ?? NSNull(),
                 "totalTokens": project.totalTokens as Any? ?? NSNull(),
                 "totalCostUSD": project.totalCostUSD as Any? ?? NSNull(),
                 "daily": try Self.json(project.daily)]
            }
            result["historyCoverageIsEstablished"] = snapshot.historyCoverageIsEstablished
            result["historyScanIsPartial"] = snapshot.historyScanIsPartial
        }
        let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print("NATIVE_ORACLE_JSON:" + String(decoding: data, as: UTF8.self))
    }

    private static func json(_ value: some Encodable) throws -> Any {
        try JSONSerialization.jsonObject(with: JSONEncoder().encode(value))
    }
}
