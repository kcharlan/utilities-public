import Foundation
import Testing
import TelltaleCodex
import TelltaleTestSupport

@Suite struct RolloutDiscoveryTests {
    @Test func findsBothSuffixesInSessionsAndArchive() throws {
        try withScratchDirectory { home in
            var urls: [String: URL] = [:]
            for (session, compressed, archived) in [(1, false, false), (2, true, false), (3, false, true), (4, true, true)] {
                var builder = RolloutBuilder(session: session)
                builder.sessionMeta()
                urls[builder.sessionID] = compressed
                    ? try builder.writeCompressed(codexHome: home, archived: archived)
                    : try builder.writePlain(codexHome: home, archived: archived)
            }
            // Not rollouts: wrong prefix, wrong suffix, and a rollout nested too deep in the archive.
            let day = RolloutBuilder().directory(codexHome: home)
            try Data("{}\n".utf8).write(to: day.appending(path: "notes-\(RolloutBuilder.sessionID(5)).jsonl"))
            try Data("{}\n".utf8).write(to: day.appending(path: "rollout-2026-01-01T00-00-00-\(RolloutBuilder.sessionID(6)).json"))
            let nested = home.appending(path: "archived_sessions/extra", directoryHint: .isDirectory)
            try FileManager.default.createDirectory(at: nested, withIntermediateDirectories: true)
            try Data("{}\n".utf8).write(to: nested.appending(path: "rollout-2026-01-01T00-00-00-\(RolloutBuilder.sessionID(7)).jsonl"))

            let files = RolloutDiscovery.files(codexHome: home)
            #expect(files.map(\.sessionID).sorted() == (1...4).map(RolloutBuilder.sessionID))
            for file in files {
                let expected = try #require(urls[file.sessionID])
                #expect(file.url.standardizedFileURL.path == expected.standardizedFileURL.path)
                #expect(file.compressed == expected.lastPathComponent.hasSuffix(".jsonl.zst"))
                let attributes = try FileManager.default.attributesOfItem(atPath: expected.path)
                #expect(file.size == (attributes[.size] as? Int))
                #expect(file.modified == (attributes[.modificationDate] as? Date))
            }
        }
    }

    @Test func prefersPlainWhenBothExist() throws {
        try withScratchDirectory { home in
            var builder = RolloutBuilder(session: 1)
            builder.sessionMeta()
            builder.turnContext(at: 1, model: "gpt-6.1-sol")
            let plain = try builder.writePlain(codexHome: home)
            try builder.writeCompressed(codexHome: home)
            // The same session archived and compressed: the live plain file still wins.
            try builder.writeCompressed(codexHome: home, archived: true)

            let files = RolloutDiscovery.files(codexHome: home)
            #expect(files.count == 1)
            #expect(files.first?.compressed == false)
            #expect(files.first?.url.standardizedFileURL.path == plain.standardizedFileURL.path)
        }
    }

    @Test func sessionIDFromFilenameUUID() throws {
        try withScratchDirectory { home in
            // The filename is the identity, whatever session_meta says.
            var builder = RolloutBuilder(session: 12)
            builder.record("session_meta", at: 0, payload: ["id": RolloutBuilder.sessionID(99)])
            try builder.writeCompressed(codexHome: home)
            let day = builder.directory(codexHome: home)
            try Data("{}\n".utf8).write(to: day.appending(path: "rollout-2026-01-01T00-00-00-not-a-session-uuid.jsonl"))

            let files = RolloutDiscovery.files(codexHome: home)
            #expect(files.map(\.sessionID) == [RolloutBuilder.sessionID(12)])
        }
    }

    @Test func missingCodexHomeFindsNothing() throws {
        try withScratchDirectory { home in
            #expect(RolloutDiscovery.files(codexHome: home.appending(path: "absent")).isEmpty)
        }
    }
}
