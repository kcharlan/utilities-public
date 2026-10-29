# Telltale Reliability Fixes (0.2.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop false "Codex changed its log format" Collector health notices, and the "running again" notice that follows each one, and keep the dashboard sidebar to recently used models.

**Architecture:**
- Closed WAL handling: see **Skip a closed WAL database**.
- Format-problem notifications: see **Apply the format-problem policy**.
- Sidebar and arrival: see **Keep the sidebar to recently used models**.

**Tech Stack:** See `Package.swift` and README "Requirements".

**Spec:** [`telltale_design_spec.md`](telltale_design_spec.md) §6, §6.5, §7.4, §9.2 and §9.3. There is no separate design doc; Diagnosis and Alternatives considered below are the design input.

## Diagnosis

- The closed-WAL behavior is reproduced by Colophon's `test_sqlite_closed_wal.c`; see `colophon/docs/LESSONS_LEARNED.md`, "Read-only SQLite uses normal coordination" and "Codex's SQLite deletes `-wal` and `-shm`". The proposed Telltale regressions are `closedWALDatabaseThrowsClosedAndCreatesNothing` and `isClosedWALNeedsWALHeaderAndNoWALFile`.
- A transient format problem caused by reopening between the failed read and side-file check is covered by `formatProblemFromOneRunShowsButDoesNotNotify`.
- Current model selection and retention are defined by `ModelDetail.models`, `Store.models(provider:)` and `Retention`. Idle readouts and panel membership follow `ModelDetail.Readout.lastHour` and `PanelSnapshot.activeWindow`.

## Alternatives considered for closed-WAL handling

| Option | Outcome |
|---|---|
| Skip a closed WAL database and retry next run | **Chosen.** See the closed-WAL policy below. |
| Open with `immutable=1` | Rejected. See `colophon/docs/LESSONS_LEARNED.md`, "Read-only SQLite uses normal coordination". |
| Open read-write | Rejected: conflicts with spec §6's read-only contract. |
| Vendor upstream SQLite | Rejected: adds a dependency and may create side files; see Colophon's closed-WAL test and lessons. Read-only directories still require handling. |

## Global Constraints

- Public repository: fixtures and test names stay conspicuously synthetic. This plan and every doc change describe behavior, never the owner's activity, times, counts or log text.
- Read-only contract: spec §6 intro, as amended by the closed-WAL change.
- Test commands. A filtered run is `mkdir -p .build/tmp && TMPDIR="$PWD/.build/tmp/" tools/check_no_temp_leaks.sh swift test -Xswiftc -warnings-as-errors --filter '<pattern>'` from `telltale/`, run under the same guard and flags as `make test` (`Makefile`, targets `test` and `test-suite`). Every task ends with `make test` passing before its commit.
- Version declarations: `TelltaleRelease.version` (`Sources/TelltaleCore/Release.swift`), `CFBundleShortVersionString` and `CFBundleVersion` (`Resources/Info.plist`), the version in `README.md`'s Purpose, and the pinned expectation in `Tests/TelltaleCoreTests/ReleaseTests.swift`. Bump to the version in this plan's title and increment `CFBundleVersion`.
- Deployment is outside this plan: Kevin authorizes it separately, from merged `main` only.

## Decisions (defaults; Kevin may override before execution)

1. **Closed-WAL policy:** Skip quietly like `ReadOnlySQLite.Busy`, retaining the cursor. Resume according to `CodexUsageSource.ingest`; source pruning can cause gaps. No new collector-log field is added.
2. **Format-problem policy:** Require consecutive collector reports before notifying; the lamp and panel message appear on the first. This delays a real notification by one collector interval and covers the race in `formatProblemFromOneRunShowsButDoesNotNotify`.
3. **The sidebar window is 14 days** (`ChartRange.twoWeeks`). A provider whose models all fall outside it shows `Copy.noRecentModels`.
4. **Not in this plan:** showing usual for an idle model; dropping backfilled lines older than the backfill lookback; giving SQLite failures that aren't format changes their own wording. Colophon is handled in its own session.
5. **This plan doc is committed with the closed-WAL change**, after sanitization.

## Review Focus

- Reopening race: `formatProblemFromOneRunShowsButDoesNotNotify`.
- Unreadable main file: `unreadableClosedDatabaseIsStillAFailure`.
- Window boundary: `recentModelsUseTheSidebarWindow`.
- A hidden model opened from an alert uses its disambiguated name: `hiddenModelOpensUnderItsDisambiguatedName`.
- Transition from not set up to format problem: `notSetUpThenFormatProblemRestartsUnavailableSince`.

---

### Task 1: Skip a closed WAL database

**Files:**
- Modify: `Sources/TelltaleCodex/ReadOnlySQLite.swift`: new error, detection in `open` and in the instance's failure path, doc comments.
- Modify: `Sources/TelltaleCodex/CodexUsageSource.swift`: `run(_:_:)` and the comment above it. Also the `Throws` doc comment on `ThreadHistorySource.read`; `RetryLogSource.read` refers to it and needs no edit.
- Modify: `Tests/TelltaleTestSupport/CodexDatabases.swift`
- Test: `Tests/TelltaleCodexTests/ReadOnlySQLiteTests.swift`, `Tests/TelltaleCodexTests/CodexUsageSourceTests.swift`
- Docs: spec §6 intro; `README.md` "How the collector runs"; `../docs/lessons_learned.md`; this plan

**Interfaces:**
- Produces: `public struct ReadOnlySQLite.Closed: Error, Equatable, Sendable {}` and `public static func ReadOnlySQLite.isClosedWAL(_ url: URL) -> Bool`.
- Produces (test support): `public func CodexDatabase.closeLikeCodex() throws` and `public static func CodexDatabase.reopen(_ url: URL) throws -> CodexDatabase`.

- [ ] **Step 1: Add the fixture methods**

`closeLikeCodex()` turns `SQLITE_FCNTL_PERSIST_WAL` off (value 0) on `"main"` with `sqlite3_file_control`, then closes the connection. Afterwards it throws `Failure(description:)` if `-wal` or `-shm` still exists. Make the handle optional so `deinit` doesn't close it twice, and make every write after the close throw `Failure(description: "closed")`. `reopen(_:)` opens an existing file read-write without `SQLITE_OPEN_CREATE` and reads its column set with `PRAGMA table_info`, so a test can write again after a close. Update the type's doc comment.

- [ ] **Step 2: Write the failing tests in `ReadOnlySQLiteTests`**

```swift
@Test func closedWALDatabaseThrowsClosedAndCreatesNothing() throws {
    try withScratchDirectory { home in
        let writer = try CodexDatabase.threadHistory(codexHome: home)
        // One synthetic failed turn with addTurn then finishTurn(status: "failed", ...), as ThreadHistorySourceTests does.
        try writer.closeLikeCodex()
        let database = try ReadOnlySQLite.open(writer.url)
        #expect(throws: ReadOnlySQLite.Closed.self) { try database.requireColumns(ThreadHistorySource.columns, in: "thread_turns") }
        #expect(!FileManager.default.fileExists(atPath: writer.url.path + "-wal"))
        #expect(!FileManager.default.fileExists(atPath: writer.url.path + "-shm"))
    }
}

@Test func isClosedWALNeedsWALHeaderAndNoWALFile() throws {
    // WAL writer still open → false. After closeLikeCodex → true.
    // Then an empty -shm only → true; an empty -wal only → false (and a read succeeds).
    // Rollback-journal file (journal: .delete), no -wal → false. Missing file → false.
}

@Test func unreadableClosedDatabaseIsStillAFailure() throws {
    // WAL file closed like Codex, then mode 000 (restore 0o600 in a defer before the scratch is removed):
    // opening it or its first query throws ReadOnlySQLite.Failure, not Closed.
}
```

- [ ] **Step 3: Run them and confirm they fail**

Run the filtered command from Global Constraints with pattern `ReadOnlySQLiteTests`.
Expected: a compile failure naming `Closed` and `isClosedWAL`.

- [ ] **Step 4: Implement**

`isClosedWAL(_:)` is true only when the file's bytes at offsets 18 and 19 are both `2` (read the first 20 bytes; any read failure is false) and no file exists at `url.path + "-wal"`. The instance keeps its URL. In `open`'s failure and in the instance's query failure path, after the existing `Busy` mapping: when `code & 0xFF == SQLITE_CANTOPEN` and `isClosedWAL(url)`, throw `Closed()`. The `Closed` doc comment describes the observed evidence and retry policy without claiming it proves that no process has the database open.

- [ ] **Step 5: Write the failing source-level test in `CodexUsageSourceTests`**

Model it on `busyReaderKeepsItsCursor`:

```swift
@Test func closedDatabasesAreSkippedQuietlyAndReadAfterReopening() throws {
    // Ingest initial rows; save the cursor. Write additional unread rows to both databases, then close both writers.
    // The skipped run returns .ready with empty batches and unchanged threadHistorySince, logsAfterID and logsLastSeen;
    // no -wal file is created. Reopen both databases and assert the unread rows are recovered.
}
```

- [ ] **Step 6: Map `Closed` in `CodexUsageSource.run`**

Catch `ReadOnlySQLite.Closed` beside `ReadOnlySQLite.Busy`, returning `.busy`. Update the comment above `run` to "A busy or closed file is skipped quietly".

- [ ] **Step 7: Run the Codex suites, then the full suite**

Run the filtered command with pattern `TelltaleCodexTests`. Expected: PASS, including `busyStepThrowsBusy` and `codexFilesAreNotModified`. Then run `make test` under Global Constraints.

- [ ] **Step 8: Update the docs**

- Spec §6 intro: document the closed-WAL policy and its detection limits. A missing `-wal` alone does not prove that no process has the database open.
- README "How the collector runs": link to the spec's closed-WAL policy.
- `../docs/lessons_learned.md`: a dated entry, "Read-only SQLite can't open a WAL database its writer closed". It covers the CANTOPEN-at-first-statement symptom, the system SQLite's persistent-WAL default hiding it from fixtures, and the `closeLikeCodex()` fixture; reference Colophon's closed-WAL lesson for other-reader behavior.

- [ ] **Step 9: Commit**

```bash
git add telltale/Sources/TelltaleCodex/ReadOnlySQLite.swift telltale/Sources/TelltaleCodex/CodexUsageSource.swift telltale/Sources/TelltaleCodex/ThreadHistorySource.swift telltale/Tests/TelltaleTestSupport/CodexDatabases.swift telltale/Tests/TelltaleCodexTests/ReadOnlySQLiteTests.swift telltale/Tests/TelltaleCodexTests/CodexUsageSourceTests.swift telltale/docs/telltale_design_spec.md telltale/docs/telltale_reliability_fixes_implementation_plan.md telltale/README.md docs/lessons_learned.md
git commit -m "Skip databases matching the closed WAL failure" -m "Handle the closed WAL failure like a busy file, preserve the cursor, and add regression coverage for retrying unread rows. Add the reliability fixes plan."
```

### Task 2: Apply the format-problem policy

**Files:**
- Modify: `Sources/TelltaleCore/Collector/CollectorRun.swift`: the `setSourceState` call in the ingest loop.
- Modify: `Sources/TelltaleCore/Launchd/CollectorHealth.swift`: `evaluate`'s `notify`, and the "Notify when on and:" doc comment on `CollectorHealth`.
- Test: `Tests/TelltaleCoreTests/CollectorHealthTests.swift`, `Tests/TelltaleCoreTests/CollectorRunTests.swift`, `Tests/TelltaleAppTests/CollectorMonitorTests.swift`
- Docs: spec §6.5 (the format-problem paragraph), spec §7.4 (the Collector health row), `README.md` "Collector management and health", `../docs/lessons_learned.md`

**Interfaces:**
- Consumes: `SourceStateRow.unavailableSince` and `updatedAt` as `CollectorRun` writes them.
- Produces: no new API.

- [ ] **Step 1: Write the failing tests**

`CollectorHealthTests`:

```swift
@Test func formatProblemFromOneRunShowsButDoesNotNotify() {
    let state = SourceStateRow(source: "codex", state: .formatProblem("synthetic"), unavailableSince: Health.at(9, 20), updatedAt: Health.at(9, 20))
    let runs = [Health.run(1, Health.at(9, 15), .succeeded), Health.run(2, Health.at(9, 20), .succeeded)]
    let report = Health.evaluate(runs: runs, states: [state], now: Health.at(9, 21))
    #expect(report.problems == ["codex changed its log format. Telltale can't read codex responses since 09:20."])
    #expect(report.lamp == .red)
    #expect(!report.notify)
}
```

Retain `formatProblemLightsRed` as a regression.

`CollectorRunTests`, beside `sourceProblemDoesNotStopOtherSources`:

```swift
@Test func notSetUpThenFormatProblemRestartsUnavailableSince() async throws {
    // A FakeUsageSource that is notSetUp at run 1 (t1) → unavailableSince == t1.
    // formatProblem at run 2 (t2) → t2. formatProblem again at run 3 → still t2. Ready at run 4 → nil.
}
```

`CollectorMonitorTests`, following `postsRecoveredWhenGone`:

```swift
@Test func oneRunFormatProblemPostsNothing() async throws {
    // Store a format-problem source state whose unavailableSince equals updatedAt; check twice, a minute apart;
    // store it ready; check again → the recording notifier holds no posts and collectorHealthNotice stays nil.
}
```

- [ ] **Step 2: Run them and confirm they fail**

Run the filtered command with pattern `CollectorHealthTests|CollectorRunTests|CollectorMonitorTests`.
Expected: each new test fails on its first assertion that differs (`notify` is true; `unavailableSince` keeps t1; posts are recorded).

- [ ] **Step 3: Implement**

`CollectorRun` writes `unavailableSince` as follows:
- nil when the new state is `.ready`;
- `previous?.unavailableSince ?? now` when the previous row's state is the same case as the new one (`.notSetUp` or `.formatProblem`, ignoring the text);
- `now` otherwise.

`CollectorHealth.evaluate` still lists every format problem in `problems`. Only a row whose `updatedAt` is later than `unavailableSince ?? updatedAt` counts toward `notify`. Update the doc comment to refer to the format-problem policy in the spec.

- [ ] **Step 4: Run the suites, then the full suite**

Run the filtered command with pattern `TelltaleCoreTests|TelltaleAppTests`. Expected: PASS, including `formatProblemUsesTheSourcesName` and `ProviderSummaryTests`. Then `make test` passes.

- [ ] **Step 5: Update the docs**

- Spec §6.5: document the format-problem policy; refer to it from the Collector health row in §7.4 and README "Collector management and health".
- `../docs/lessons_learned.md`: record the incorrect unavailable start time on a transition between unavailable states and the regression that protects it.

- [ ] **Step 6: Commit**

```bash
git add telltale/Sources/TelltaleCore/Collector/CollectorRun.swift telltale/Sources/TelltaleCore/Launchd/CollectorHealth.swift telltale/Tests/TelltaleCoreTests/CollectorHealthTests.swift telltale/Tests/TelltaleCoreTests/CollectorRunTests.swift telltale/Tests/TelltaleAppTests/CollectorMonitorTests.swift telltale/docs/telltale_design_spec.md telltale/README.md docs/lessons_learned.md
git commit -m "Apply the format problem notification policy" -m "Avoid transient format notices and correct the start time when a source changes unavailable states."
```

### Task 3: Keep the sidebar to recently used models and release

**Files:**
- Modify: `Sources/TelltaleCore/Read/ModelDetail.swift`: `models(store:provider:)` and its doc comment, plus a new recent read.
- Modify: `Sources/Telltale/DashboardView.swift`: `SidebarGroup.State`, `DashboardModel.loadSidebar`, `DashboardModel.selectedModel`'s fallback, and `DashboardSidebar`'s state switch.
- Modify: `Sources/TelltaleCore/Read/PanelSnapshot.swift`: the arrival-note loop.
- Modify: `Sources/TelltaleCore/Rules/Copy.swift`: beside `noResponsesYet`.
- Modify: every item in Global Constraints → Version declarations.
- Modify: `Tests/TelltaleAppTests/DashboardWorld.swift`: an optional `sources:` initializer parameter defaulting to `PanelWorld.sources`.
- Test: `Tests/TelltaleCoreTests/ModelDetailTests.swift`, `Tests/TelltaleCoreTests/PanelSnapshotTests.swift`, `Tests/TelltaleAppTests/DashboardWindowTests.swift`
- Docs: spec §9.2 (the sidebar sentence); README "Dashboard" (the sidebar sentence) and "Results"

**Interfaces:**
- Produces:
  - `public static let ModelDetail.sidebarWindow: TimeInterval`, set to the sidebar window in Decisions.
  - `public static func ModelDetail.recentModels(store: Store, provider: ProviderID, now: Date) throws -> [String]`, sorted and a subset of `models`.
  - `public static let Copy.noRecentModels`, with copy stating the sidebar window in Decisions.
  - `DashboardModel.SidebarGroup.State.idle`.
- Consumes: the internal `Store.hasResponse(provider:model:after:through:)` in `PanelSnapshot.swift`. Reuse it; don't add SQL.

- [ ] **Step 1: Write the failing read-model tests**

`ModelDetailTests`:

```swift
@Test func recentModelsUseTheSidebarWindow() throws {
    // Exercise the exclusive lower boundary and a response just inside it.
    #expect(try ModelDetail.recentModels(store: store, provider: .codex, now: now) == [Synth.otherModel])
    #expect(try ModelDetail.models(store: store, provider: .codex) == [Synth.model, Synth.otherModel])
}
```

`PanelSnapshotTests`, beside and set up as `arrivalNamesModelsPastColdStart`:

```swift
@Test func arrivalOpensTheFirstRecentModel() throws {
    // Add a stale model that sorts before the recent model; assert the note selects and names only the recent model.
}
```

- [ ] **Step 2: Write the failing dashboard tests in `DashboardWindowTests`**

Each test seeds with `PanelWorld.seed` and adds older responses through `Store.open(world.paths.database, mode: .readWrite)` with noncolliding IDs; set up the fixture in the test code. See `Store.upsert(responses:)` for collision behavior.

```swift
@Test func sidebarHidesModelsUnusedOutsideTheWindow() throws {
    // Seed a stale and a recent model; assert the sidebar and default section select the recent one.
}
@Test func sidebarShowsIdleWhenNoModelIsRecent() throws {
    // Advance world.clock beyond the sidebar window; assert the codex group's state is .idle.
}
@Test func hiddenModelOpensUnderItsDisambiguatedName() throws {
    // Use a test-local ModelNaming with colliding names as in AppSyntheticNaming. Select a stale model;
    // assert its detail opens with the full-list disambiguated name.
}
```

- [ ] **Step 3: Run them and confirm they fail**

Run the filtered command with pattern `ModelDetailTests|PanelSnapshotTests|DashboardWindowTests`.
Expected: a compile failure naming `recentModels`, `sidebarWindow`, `.idle` and the `sources:` parameter.

- [ ] **Step 4: Implement**

- `recentModels` keeps the models in `store.models(provider:)` for which `hasResponse(after: now - sidebarWindow, through: now)` is true. `models`'s doc comment drops "the dashboard sidebar" and says it is the full list used for names, rules and events.
- `loadSidebar` reads both lists at `now()`. Names still come from `DisplayNames.disambiguated` over the full list; rows come from the recent list. A recent list that is empty while the full list isn't makes the state `.idle`.
- `DashboardSidebar` renders `.idle` as `dimmed(Copy.noRecentModels)`, following the backfilling condition on `.empty`.
- `selectedModel`'s fallback names the model with `live.disambiguatedName(provider:model:)` instead of `live.displayName(provider:model:)`.
- The arrival note takes its ready-model list and `firstModel` from `recentModels`, using the snapshot's `now`, and its names from the full list.
- `RuleEngine`, `LiveStore.disambiguatedName` and the panel's model rows keep `models(provider:)`.

- [ ] **Step 5: Run the suites**

Run the filtered command with pattern `TelltaleCoreTests|TelltaleAppTests`. Expected: PASS.

- [ ] **Step 6: Bump the version and update the docs**

- Apply every item in Global Constraints → Version declarations; explain the pinned expectation change in the commit body.
- Spec §9.2: document the sidebar window and `Copy.noRecentModels`; link to it from README "Dashboard".
- README "Native acceptance": add distinct installed-release checks for the closed-WAL scenario and for a stale model being absent from the sidebar; keep private evidence outside the repository. Add separately reportable "Not yet run" Results entries for these installed checks.

- [ ] **Step 7: Full verification (every category; report each result)**

From `telltale/`:

```bash
make test
make release
make snapshots
make acceptance
build/release/Telltale.app/Contents/MacOS/Telltale --synthetic-unknown-flag; echo "exit $?"
```

Expected results:
- `make test` passes as specified under Global Constraints.
- `make release` builds a signed app whose `CFBundleShortVersionString` and `CFBundleVersion` match Global Constraints → Version declarations.
- `make snapshots`: inspect every printed PNG against the maintained scenes and the sidebar policy.
- `make acceptance` passes its service tests. Remove the snapshot and acceptance homes using their printed commands.
- The last command follows `TelltaleMain`'s usage-error behavior and exits 2.

From the repository root, run all commands in AGENTS.md's **Static deployment/fleet audit tooling** validation entry, including `tools/tests/deploy_telltale.test.mjs`; require each to pass. The changed source, resources and tests are deployment build inputs (`tools/deploy_telltale.mjs`). If the static audit or its child runner also changes, run Market Atlas's complete suites as required by the validation matrix; report any unmet gate rather than replacing it with synthetic tests.

- [ ] **Step 8: Commit**

```bash
git add telltale/Sources/TelltaleCore/Read/ModelDetail.swift telltale/Sources/Telltale/DashboardView.swift telltale/Sources/TelltaleCore/Read/PanelSnapshot.swift telltale/Sources/TelltaleCore/Rules/Copy.swift telltale/Sources/TelltaleCore/Release.swift telltale/Resources/Info.plist telltale/Tests/TelltaleAppTests/DashboardWorld.swift telltale/Tests/TelltaleAppTests/DashboardWindowTests.swift telltale/Tests/TelltaleCoreTests/ModelDetailTests.swift telltale/Tests/TelltaleCoreTests/PanelSnapshotTests.swift telltale/Tests/TelltaleCoreTests/ReleaseTests.swift telltale/docs/telltale_design_spec.md telltale/README.md
git commit -m "Limit the sidebar to recent models and release" -m "Apply the sidebar policy while preserving full-list naming and update the pinned ReleaseTests expectation for the release."
```

Before committing, run `git status --short` and confirm that nothing outside the list is left modified or untracked from this task.

## After the plan

With separate authorization for Git actions and deployment, merge to `main`, deploy per Global Constraints, and run the installed-release checks added to the README. For the closed-WAL check:
- Avoid a Colophon scan during the check; see the closed-WAL lesson linked in Diagnosis.
- Leave Codex idle until `~/.codex/thread_history_1.sqlite-wal` is absent.
- Confirm that the next collector run logs no format problem and that no Collector health notification follows. Record the check separately from the sidebar check; this observation alone does not establish the cause of an earlier incident.
