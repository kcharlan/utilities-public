import Foundation
import Darwin
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import TelltaleClaude

@Suite struct ClaudeUsageSourceTests {
    @Test func malformedUsageRemainsFormatProblemAfterReplay() throws {
        try withScratchDirectory { root in
            let line = try TranscriptBuilder.line(["type": "assistant", "timestamp": "2026-01-01T00:00:00Z", "message": ["id": "msg_synthetic_01", "model": "claude-opus-5-5", "usage": ["output_tokens": "not-a-number"]]])
            _ = try TranscriptBuilder.file(root: root, text: line)
            let source = ClaudeUsageSource(roots: [root])
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            if case .formatProblem = first.state {} else { Issue.record("Expected format problem on initial read") }
            let replay = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            if case .formatProblem = replay.state {} else { Issue.record("Expected format problem on replay") }
        }
    }
    @Test func invalidCompactionsRemainFormatProblemAfterReplay() throws {
        for metadata: [String: Any] in [["preTokens": 100], ["trigger": "auto"]] {
            try withScratchDirectory { root in
                let line = try TranscriptBuilder.line(["type": "system", "subtype": "compact_boundary", "timestamp": "2026-01-01T00:00:00Z", "uuid": "compact-synthetic-01", "compactMetadata": metadata])
                _ = try TranscriptBuilder.file(root: root, text: line)
                let source = ClaudeUsageSource(roots: [root])
                let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
                #expect(first.batch.invalidCompactions == 1 && first.batch.compactions.isEmpty)
                if case .formatProblem = first.state {} else { Issue.record("Expected format problem on initial read") }
                let replay = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
                #expect(replay.batch.invalidCompactions == 0)
                if case .formatProblem = replay.state {} else { Issue.record("Expected format problem on replay") }
            }
        }
    }
    @Test func recentFilesOutsideLayoutAreFormatProblem() throws {
        try withScratchDirectory { root in
            let projects = root.appending(path: "projects")
            try FileManager.default.createDirectory(at: projects, withIntermediateDirectories: true)
            try "SYNTHETIC".write(to: projects.appending(path: "synthetic.jsonl"), atomically: true, encoding: .utf8)
            let result = ClaudeUsageSource(roots: [root]).ingest(cursor: nil, backfillFrom: .distantPast, now: Date())
            if case .formatProblem = result.state {} else { Issue.record("Expected format problem") }
        }
    }
    @Test func oldMatchingFileDoesNotMaskRecentLayoutDrift() throws {
        try withScratchDirectory { root in
            let old = try TranscriptBuilder.file(root: root, text: TranscriptBuilder.user("2026-01-01T00:00:00Z"))
            try FileManager.default.setAttributes([.modificationDate: Date().addingTimeInterval(-172800)], ofItemAtPath: old.path)
            try "SYNTHETIC".write(to: root.appending(path: "projects/new-layout.jsonl"), atomically: true, encoding: .utf8)
            let result = ClaudeUsageSource(roots: [root]).ingest(cursor: nil, backfillFrom: .distantPast, now: Date())
            if case .formatProblem = result.state {} else { Issue.record("Expected format problem") }
        }
    }
    @Test func discoveryRejectsNonRegularFiles() throws {
        try withScratchDirectory { root in
            let dir = root.appending(path: "projects/-Users-example-project")
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let fifo = dir.appending(path: "fifo-synthetic.jsonl")
            #expect(mkfifo(fifo.path, 0o600) == 0)
            try FileManager.default.createDirectory(at: dir.appending(path: "directory-synthetic.jsonl"), withIntermediateDirectories: true)
            let external = root.appending(path: "external-synthetic.jsonl")
            try "SYNTHETIC".write(to: external, atomically: true, encoding: .utf8)
            try FileManager.default.createSymbolicLink(at: dir.appending(path: "link-synthetic.jsonl"), withDestinationURL: external)
            #expect(TranscriptDiscovery.files(roots: [root]).isEmpty)
        }
    }
    @Test func discoveryUsesActualProjectsRoot() throws {
        try withScratchDirectory { home in
            let root = home.appending(path: "synthetic-root")
            let target = home.appending(path: "synthetic-target")
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: target.appending(path: "projects"), withIntermediateDirectories: true)
            try FileManager.default.createSymbolicLink(at: root.appending(path: "projects"), withDestinationURL: target)
            let text = try TranscriptBuilder.user("2026-01-01T00:00:00Z")
            try text.write(to: target.appending(path: "projects/00000000-0000-4000-8000-000000000001.jsonl"), atomically: true, encoding: .utf8)
            let ignored = target.appending(path: "tool-results/projects/copied")
            try FileManager.default.createDirectory(at: ignored, withIntermediateDirectories: true)
            try text.write(to: ignored.appending(path: "00000000-0000-4000-8000-000000000002.jsonl"), atomically: true, encoding: .utf8)
            let found = TranscriptDiscovery.files(roots: [root])
            #expect(found.count == 1)
            #expect(found.first?.sessionID == "00000000-0000-4000-8000-000000000001")
        }
    }
    @Test func missingProjectsIsNotSetUp() throws {
        try withScratchDirectory { root in
            let result = ClaudeUsageSource(roots: [root]).ingest(cursor: nil, backfillFrom: .distantPast, now: Date())
            #expect(result.state == .notSetUp("Claude Code's data folder wasn't found."))
        }
    }
    @Test func projectsMustBeDirectory() throws {
        try withScratchDirectory { root in
            try "SYNTHETIC".write(to: root.appending(path: "projects"), atomically: true, encoding: .utf8)
            let result = ClaudeUsageSource(roots: [root]).ingest(cursor: nil, backfillFrom: .distantPast, now: Date())
            #expect(result.state == .notSetUp("Claude Code's data folder wasn't found."))
        }
    }
    @Test func incompleteMessageResumesNextRun() throws {
        try withScratchDirectory { root in
            let lines = try TranscriptBuilder.user("2026-01-01T00:00:00Z") + TranscriptBuilder.assistant("2026-01-01T00:00:05Z")
            _ = try TranscriptBuilder.file(root: root, text: lines)
            let source = ClaudeUsageSource(roots: [root])
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Date())
            #expect(first.batch.responses.isEmpty)
            let state = try JSONDecoder().decode(ClaudeCursor.self, from: first.cursor)
            #expect(state.files.values.first?.sawUsage == false)
            let second = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            #expect(second.batch.responses.count == 1)
            #expect(second.batch.responses.first?.outputTokens == 300)
        }
    }
    @Test func twoRootsDontCollideAndCursorHidesPaths() throws {
        try withScratchDirectory { home in
            let a = home.appending(path: "synthetic-a"), b = home.appending(path: "synthetic-b")
            let text = try TranscriptBuilder.user("2026-01-01T00:00:00Z") + TranscriptBuilder.assistant("2026-01-01T00:00:05Z")
            _ = try TranscriptBuilder.file(root: a, text: text)
            _ = try TranscriptBuilder.file(root: b, text: text)
            let source = ClaudeUsageSource(roots: [a, b])
            let result = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            #expect(result.batch.responses.count == 2)
            #expect(result.batch.responses[0].responseID == result.batch.responses[1].responseID)
            let cursor = try JSONDecoder().decode(ClaudeCursor.self, from: result.cursor)
            #expect(cursor.files.count == 2)
            #expect(!String(decoding: result.cursor, as: UTF8.self).contains("Users-example"))
            let again = source.ingest(cursor: result.cursor, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            #expect(again.batch.responses.isEmpty)
        }
    }
    @Test func replacedFileRereads() throws {
        try withScratchDirectory { root in
            let text = try TranscriptBuilder.user("2026-01-01T00:00:00Z") + TranscriptBuilder.assistant("2026-01-01T00:00:05Z")
            let file = try TranscriptBuilder.file(root: root, text: text)
            let source = ClaudeUsageSource(roots: [root])
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            try FileManager.default.removeItem(at: file)
            _ = try TranscriptBuilder.file(root: root, text: text)
            let next = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            #expect(next.batch.responses.count == 1)
        }
    }
    @Test func oldFileWithoutCursorIsSkippedOnBackfill() throws {
        try withScratchDirectory { root in
            let text = try TranscriptBuilder.user("2026-01-01T00:00:00Z") + TranscriptBuilder.assistant("2026-01-01T00:00:05Z")
            _ = try TranscriptBuilder.file(root: root, text: text)
            let result = ClaudeUsageSource(roots: [root]).ingest(cursor: nil, backfillFrom: Date().addingTimeInterval(60), now: Date().addingTimeInterval(180))
            #expect(result.batch.responses.isEmpty)
        }
    }
}
