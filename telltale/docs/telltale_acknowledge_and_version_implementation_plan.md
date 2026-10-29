# Telltale Implementation Plan: Acknowledgement, Version, and Follow-ups

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In one release:
- Let Kevin acknowledge alerts, so the menu-bar dot stops demanding attention for something he already knows about, and bring an alert back as new when something new happens.
- Show the app's version in the panel and the dashboard.
- Fix the follow-ups listed under **Design**.

**Architecture:** The behavior contracts are under **Design**; the task Interfaces define the implementation seams.

**Tech Stack:** See `Package.swift` and README "Requirements". The snapshot task uses Darwin's `clonefile(2)`.

**Spec:** [`telltale_design_spec.md`](telltale_design_spec.md) and [`telltale_visual_design.md`](telltale_visual_design.md). Each task's **Docs** list names the sections it amends.

## Starting point

Grounding revision: `b014620`. Re-check the symbols in each task's files against the execution checkout before starting the task.

Paths below are relative to `telltale/` unless explicitly identified as repository-root paths. This plan does not authorize implementation or commits. Record the starting working-tree status; execute a task's Commit section only if Kevin separately authorizes commits. See **After the plan** for merge and deployment authorization.

Run Git command blocks from the repository root; run build/test commands from `telltale/` unless a command names another directory.

## Design

### Follow-ups from the 0.2.1 release

These come from the 0.2.1 session's final report, which isn't in the repository, so each one is stated here.

| Follow-up | Implementation reference |
|---|---|
| Kept problem outlives its file; one-off read error notifies; busy-skip regression | Task 1's outcome table and named tests |
| Database closed indefinitely | **Reading a closed database** and Task 2 |
| Idle arrival note and idle sidebar snapshot | Task 8's `arrivalForAnIdleProviderSaysItIsIdle` and `Scene.sidebarIdle` |

### Items deferred by the reliability plan

See [`telltale_reliability_fixes_implementation_plan.md`](telltale_reliability_fixes_implementation_plan.md), Decision 4. Showing usual for an idle model stays out: Kevin ruled on 2026-10-29 that a dash is the accurate reading, and an old usual would suggest a value new runs might not uphold.

| Deferred item | Implementation reference |
|---|---|
| Read-failure wording | Task 3; apply it to SQLite failures and the file-read catches in `CodexUsageSource.readRollouts` and `ClaudeUsageSource.ingest` |
| Lookback cutoff | Task 4's `IngestBatch.droppingBefore` contract; keep failed turns on `Store.settleFailedTurns`' existing path |

### Reading a closed database

This section is the authoritative description; Task 2 implements it.

When a reader reports `ReadOnlySQLite.Closed`, compare the selected file with its last recorded read under Task 2's cursor rule. Use `ReadOnlySQLite.isClosedWAL` as evidence for attempting a clone, with its documented detection limits.
- **Unchanged:** skip the file through the existing closed-file path.
- **Changed, or never read:** the reader reads a snapshot.
  1. Record the main file's modification date and size.
  2. Require the selected source to be a regular file by `lstat`, then clone it with `clonefile(2)` to `<TelltalePaths.codexSnapshots>/<UUID>/<original file name>`. Create the snapshot root and per-read directories as real directories with mode 0700, on the same volume as Telltale's database. Keep the original basename for `snapshotUsesTheOriginalFileName`.
  3. If `-wal` exists beside the original, or its modification date or size changed, Codex touched the file during the clone. Discard the clone and treat the file as busy.
  4. Open the clone with `O_RDWR | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK`, then `fstat` the descriptor: require a regular file with a different device/inode pair from the original. Validate a complete SQLite header with WAL bytes before setting bytes 18 and 19 from 2 to 1 through this descriptor, so the clone reads as a rollback-journal database. Reject a symlink or alias before any header write. Wrap the descriptor in `FileHandle` rather than reopening its path for writing. The flag contract is `clonefile(2)`'s `CLONE_NOFOLLOW`; use the named symlink regression below as the write-safety gate.
  5. Open the clone with `ReadOnlySQLite.open`, read it, and remove the clone's directory.

`withSnapshot` uses deferred cleanup and propagates a cleanup failure as a read failure rather than silently leaving a clone. At ingest start, remove leftover clone directories inside the injected snapshot root; never follow their symlinks. If cleanup fails, report a read problem and do not create another clone. A clone-call failure takes the existing closed-file skip path, including cross-volume or unsupported-file-system failures.

Rejected alternatives:
- `immutable=1` on Codex's file. See repository-root `colophon/docs/LESSONS_LEARNED.md`, the read-only SQLite entry.
- A full copy, which costs the file's whole size in time and disk on every changed read.
- An alert only, which reports the gap without closing it.

### Acknowledgement

The model is a cockpit's master caution. Pressing it resets the attention signal, here the glyph's dot. The annunciators, here the lamp strip and the sidebar diamonds, stay lit while the condition holds. A new fault sets the attention signal again.

**What is acknowledged:**
- Each open episode, by `Acknowledgements.key`. `acknowledgementSurvivesANewEpisodeID` defines the required behavior when an episode is recreated with the same natural key; a rebuild that changes that key makes a new alert.
- The Collector health problem, separately, by `CollectorHealthReport.problemKeys`, under **Collector problem identity**.

**When an acknowledgement holds** (this table is authoritative; `Acknowledgements.holds` implements it):

| Alert | Holds while | Becomes new when |
|---|---|---|
| Failed turns (one episode per provider) | the episode's counted failures ≤ the count when acknowledged | another failure is counted, including one committed between render and click |
| Any rule | severity ≤ the severity when acknowledged | the severity rises |
| A new episode of the same rule and scope | never acknowledged | always new: its onset differs |
| Collector health | every current problem key is among the acknowledged keys | a problem with a new key appears |

An acknowledged alert doesn't come back on its own: a worse speed index at the same severity, or a larger worst value, isn't new.

**Failed-turn wording (bug fix):** Task 5's episode-loop rules and `failedTurnAlertCountsEveryFailureInTheEpisode` define the new read-time wording; see `RuleEngine.failedTurns` for the event-writing behavior it replaces in the alert read model.

**Glyph:**
- a filled dot in the most severe *new* color, among rules that have a lamp;
- otherwise, a 1.5 pt ring in the most severe lit color;
- otherwise, the plain template lens.

Accessibility appends " (acknowledged)" to a lamp lit only by acknowledged items.

**Panel and dashboard alert rows:**
- **Order:** new rows first, then acknowledged rows. Within each group, behave as `PanelSnapshot.load`'s existing sort does.
- **A new row:** a trailing `checkmark.circle` button, `Copy.acknowledge`.
- **An acknowledged row:**
  - a hollow diamond and secondary text;
  - `Copy.acknowledged` beneath it;
  - `checkmark.circle.fill`, `Copy.markAsNew`, which undoes the acknowledgement.
- **`Copy.acknowledgeAll`:** appears below the list when more than one rendered row is new, and acknowledges exactly the rows the view rendered.
- **The Collector health problem:** the same toggle in the panel footer, wherever `PanelModel.offersCollectorAcknowledgement` is true. An acknowledged problem draws the footer dot as a ring.

**Notifications:** keep `NotificationPolicy`'s posting behavior; implement Task 6's delivered-notification removal for acknowledgement actions, including the Collector action.

### Version

Use Task 8's view placement and `AppBundle.buildHelp` contract.

## Decisions (defaults; Kevin may override before execution)

- **Colors:** every alert color can be acknowledged, not only red.
- **Storage:** use Task 5's setting and Store interfaces; no schema change.
- **Collector acknowledgement limit:** Task 7 defines healthy-check clearing. A problem that clears and comes back with the same key while the app is quit stays acknowledged.
- **Events:** no acknowledgement events in the Events list.
- **Legacy failed-turn reasons:** use Task 5's canonical count even when an old episode has no recorded reason membership. Omit an unknown reason suffix instead of inferring it from settlement timestamps; retained event records stay unchanged.
- **Not added:** an Acknowledge action on the notification banner, and an About menu item.
- **Release:** 0.3.0, `CFBundleVersion` 5. Tasks refer to this decision for release values.
- **Collector problem identity:** any red job/run lamp or `needsRepair` adds `collector`, including a repair-only state with no problem message; source problems use `source.<source id>`. A transition among not-loaded, failing, overdue and repair-only stays acknowledged. A source problem introduces a different key. Source problem kinds for the same source share its key too.
- **Idle arrival wording:** `Copy.arrivalIdle` (copy table). This is a default; Kevin hasn't reviewed the wording.
- **Dropped kept problem:** a kept problem whose file is no longer Codex's current file is dropped. If it was confirmed and notified, its episode ends, and the "running again" notice follows when that notice is on. The problem described a file Codex no longer writes, so the notice is accurate.
- **Snapshots:** follow **Reading a closed database** without a full-copy fallback.
- **Read-problem since:** extend `CollectorRun.unavailableSince`'s same-kind rule to the new state; a change between format and read problems restarts the timestamp. Use the `providersFormatProblem` layout scene as the provider-state layout reference.
- **Read-problem rollback:** use `Store.sourceStateRows` in `Store+Ingest.swift`, `CollectorMonitor.readInputs` and `ProviderSummary.load` as the diagnosis references for incompatible stored-state decoding. Task 3's rollback instructions must identify the affected ingest, health and Settings provider-list paths and provide a command deleting only the incompatible `source_state` row. Keep this operational consequence in README beside `--rollback`, where the owner needs it to recover an old release.
- **Lookback everywhere:** apply Task 4's cutoff on every ingest, including catch-up runs. Keep evaluation bounded as `EvaluationPoints.after(_:through:earliest:)` does.
- **Rows already stored:** this release adds no cleanup of old stored records. Use `Retention.prune` in `Sources/TelltaleCore/Collector/Retention.swift` as the table-specific retention contract, including its handling of connection events. Whether to request a per-provider Rebuild under `Copy.providerRebuildConfirmation` after deployment is Kevin's call.

## Global Constraints

- **Public repository:**
  - Fixtures and test names stay conspicuously synthetic.
  - This plan and every doc change describe behavior, never the owner's activity, times, counts, file sizes or log text.
- **Codex SQLite access:** behave as `ReadOnlySQLite.open` and `codexFilesAreNotModified` do. Preserve the read-only coordination contract in repository-root `colophon/docs/LESSONS_LEARNED.md`; additionally assert that clone reads create no side files beside the closed fixture.
- **App writes:** behave as `UserActions.write` and `Store.Mode.readWriteExisting` do under ruling R27.
- **Test isolation:** follow `check_test_isolation.sh`; inject scratch paths for clone tests.
- **Test commands:**
  - A filtered run is `mkdir -p .build/tmp && TMPDIR="$PWD/.build/tmp/" tools/check_no_temp_leaks.sh swift test -Xswiftc -warnings-as-errors --filter '<pattern>'` from `telltale/`.
  - Every task ends with `make test` passing before its commit.
- **Version declarations:** update `Sources/TelltaleCore/Release.swift`'s `TelltaleRelease.version`, `Resources/Info.plist`'s `CFBundleShortVersionString` and `CFBundleVersion`, README's Purpose, and `ReleaseTests.infoPlistMatchesRelease`'s pinned version. Historical results, earlier plans, and cursor-compatibility comments retain their original versions. Use `git grep -n '0\.2\.1' -- telltale` to inspect remaining references, not as a replacement list.
- **Copy:** sentence case; define the templates below in `CopyTests` using synthetic fixtures, with times through `Copy.clock`. Exact new templates belong here because the implementation needs wording beyond the existing Copy API.
- **Lessons:** every bug-fix task adds a dated entry to `../docs/lessons_learned.md` that names its regression tests.
- **Deployment:** see **After the plan**.

| `Copy` member | Text |
|---|---|
| `acknowledge` | `Acknowledge` |
| `acknowledgeAll` | `Acknowledge all` |
| `markAsNew` | `Mark as new` |
| `acknowledged(at:calendar:)` | `Acknowledged {clock(at)}` |
| `failedTurnsOpen(source:noun:count:reasons:since:calendar:)` | `{source}: {count} {inflected noun} failed since {clock(since)}: {reasons}` |
| `failedTurnsBeyondAcknowledged(source:noun:count:reasons:acknowledged:calendar:)` | `{source}: {count} more {inflected noun} failed than you acknowledged at {clock(acknowledged)}: {reasons}` |
| `failedTurnsTotal(count:since:calendar:)` | `{count} failed since {clock(since)}` |
| `readProblem(source:since:calendar:)` | `Telltale can't read {source}'s logs since {clock(since)}. Open the Collector view to see the error.` |
| `versionLine` | `"\(TelltaleRelease.displayName) \(TelltaleRelease.version)"` |
| `arrivalIdle(name:days:)` | `Telltale now watches {name}. It read {days} days of history; none of its models responded in the last {sidebar-window days} days.` (`days` comes from `CollectorRun.lookbackDays`; derive the window from `ModelDetail.sidebarWindow`, as `noRecentModels` does) |

Singular forms and known reasons follow `Copy.failedTurns(source:noun:count:reasons:)` and `Copy.failedTurnReason(code:)`. Omit the colon and reason suffix when reasons are unknown or empty, under **Legacy failed-turn reasons**.

## Review Focus

- Clone races: `snapshotIsDiscardedWhenTheWriterReopens` and `snapshotIsDiscardedWhenTheFileChangesDuringTheClone`, under **Reading a closed database**.
- Kept-verdict precedence: `readFailureLeavesAnEarlierFormatProblemKept`, under Task 1's outcome table.
- Render/click race: `failureCountedDuringAcknowledgeComesBackNew`, under the acknowledgement hold table.
- Rendered-row scope: `acknowledgeAllCoversOnlyTheAlertsShown`, under **Panel and dashboard alert rows**.
- Collector problem identity: `collectorAcknowledgementFollowsProblemKeys` and `collectorProblemKindsShareAcknowledgement`, under the **Collector problem identity** decision.

---

### Task 1: Keep Codex database verdicts accurate

**Files:**
- Modify: `Sources/TelltaleCodex/CodexUsageSource.swift`:
  - `CodexCursor`: new optional fields and the doc comment.
  - `Outcome`: a `failure(String)` case.
  - `run(_:_:)`: `FormatProblem` maps to `.problem`; `Failure` and other errors map to `.failure`.
  - `ingest`: the `switch`es over `Outcome`.
- Modify: `Sources/TelltaleCodex/ThreadHistorySource.swift` and `Sources/TelltaleCodex/RetryLogSource.swift`: `database(codexHome:)`, used by `read` and by the source.
- Test: `Tests/TelltaleCodexTests/CodexUsageSourceTests.swift`
- Docs:
  - Spec §6 intro: the kept-verdict paragraph gains the file rule and the format-only rule.
  - `../docs/lessons_learned.md`.

**Interfaces:**
- Produces:
  - `CodexCursor.threadHistoryProblemFile: String?` and `logsProblemFile: String?`: the database file's `lastPathComponent` when its problem was kept; nil in cursors 0.2.1 wrote. Add them to `init` with nil defaults.
  - `public static func ThreadHistorySource.database(codexHome: URL) -> URL?` and `RetryLogSource.database(codexHome: URL) -> URL?`: extract each reader's `ReadOnlySQLite.highestNumbered` call; behave as that call does.

- [ ] **Step 1: Write the failing tests** in `CodexUsageSourceTests`, built as `closedDatabaseKeepsItsFormatProblem` is:

```swift
@Test func keptProblemIsDroppedWhenCodexMovesToANewFile() throws {
    // thread_history_1 missing error_json → a format problem kept with its file name.
    // Create a valid thread_history_2 and closeLikeCodex() it → the skipped run's state is .ready, and
    // threadHistoryProblem and threadHistoryProblemFile are nil.
}
@Test func keptProblemWithoutAFileStaysWithTheCurrentFile() throws {
    // Encode a cursor with threadHistoryProblem "Codex failed turns: synthetic" and no file name;
    // with the database closed, the run's state is .formatProblem("Codex failed turns: synthetic").
}
@Test func transientReadFailureIsNotKept() throws {
    // Close the database like Codex, then set mode 000: the run reports a problem containing "couldn't be read",
    // and threadHistoryProblem stays nil. Restore 0o600 (in a defer as well): the next run is .ready.
}
@Test func readFailureLeavesAnEarlierFormatProblemKept() throws {
    // A kept format problem, then one run with mode 000: the run's state is the kept format problem,
    // and the cursor still holds the problem and its file.
}
@Test func busyDatabaseKeepsItsFormatProblem() throws {
    // A kept format problem, then the file held busy as in busyReaderKeepsItsCursor: the run reports the kept problem.
}
@Test func readFailureAfterFileChangeDropsTheOldFormatProblem() throws {
    // Keep a problem for the selected database, then select a newer-numbered unreadable file:
    // clear the old problem and its file, report only the new read failure, and retry next run.
}
```

- [ ] **Step 2: Run them and confirm they fail**

Run the filtered command with pattern `CodexUsageSourceTests`.
- **First:** the build fails on `threadHistoryProblemFile`.
- **After stubbing the fields:** confirm `keptProblemIsDroppedWhenCodexMovesToANewFile`, `transientReadFailureIsNotKept` and `readFailureLeavesAnEarlierFormatProblemKept` fail for the behavior each names.
- `keptProblemWithoutAFileStaysWithTheCurrentFile` and `busyDatabaseKeepsItsFormatProblem` are preservation checks.

- [ ] **Step 3: Implement**

| Outcome | Effect |
|---|---|
| `.ok` | Clear the kept problem and its file |
| `.problem(text)` | Report `text`; keep `text` and the file name |
| `.failure(text)` | Apply the `.busy` file-validity rule, including clearing a mismatched kept problem; report any surviving kept problem before `text`. Never keep the read failure |
| `.busy` | Report the kept problem only when its file is nil or equals `database(codexHome:)?.lastPathComponent`; otherwise clear the kept problem and its file |

- [ ] **Step 4: Run the Codex suites, then the full suite**

Run the filtered command with pattern `TelltaleCodexTests`; expect PASS. Then `make test`.

- [ ] **Step 5: Update the docs** listed under Files, then commit:

```bash
git add telltale/Sources/TelltaleCodex/CodexUsageSource.swift telltale/Sources/TelltaleCodex/ThreadHistorySource.swift telltale/Sources/TelltaleCodex/RetryLogSource.swift telltale/Tests/TelltaleCodexTests/CodexUsageSourceTests.swift telltale/docs/telltale_design_spec.md telltale/docs/telltale_acknowledge_and_version_implementation_plan.md docs/lessons_learned.md
git commit -m "Keep only current-file format problems across Codex skips" -m "<what changed and why; add this plan>"
```

### Task 2: Read closed Codex databases from a snapshot

**Files:**
- Create: `Sources/TelltaleCodex/SQLiteSnapshot.swift`: `SnapshotClone`, `SnapshotRequest` and `ReadOnlySQLite.withSnapshot`.
- Modify: `Sources/TelltaleCodex/ThreadHistorySource.swift` and `Sources/TelltaleCodex/RetryLogSource.swift`: `read` gains `snapshot: SnapshotRequest? = nil`.
- Modify: `Sources/TelltaleCodex/CodexUsageSource.swift`:
  - `init` gains `snapshotDirectory: URL? = nil, snapshotClone: SnapshotClone = .live`.
  - `ingest` applies **Reading a closed database** and **Cursor read rule** through each reader's request.
- Modify: `Sources/TelltaleCore/Paths.swift`: `codexSnapshots` (`appSupport/codex-snapshots`).
- Modify: `Sources/Telltale/Registry.swift`: pass `paths.codexSnapshots`.
- Test: `Tests/TelltaleCodexTests/ReadOnlySQLiteTests.swift`, `Tests/TelltaleCodexTests/CodexUsageSourceTests.swift`, `Tests/TelltaleCoreTests/ReleaseTests.swift` and `Tests/Acceptance/AcceptanceServiceTests.swift`
- Docs:
  - Spec §6 intro: replace the closed-database skip policy with the **Reading a closed database** contract and its detection limits. Write the rules into the maintained spec; the spec must remain usable after this plan is archived.
  - Spec §11: move the clone lifecycle and failure policy from **Reading a closed database** into the maintained privacy contract.
  - README:
    - "How the collector runs": add `codex-snapshots` to the write locations.
    - "Native acceptance": add the check in Step 5.
    - "Results": a "Not yet run" entry.
  - `../docs/lessons_learned.md`.

**Interfaces:**
- Consumes: Task 1's `database(codexHome:)` and cursor fields.
- Produces:
  - `public struct SnapshotClone: Sendable { public var run: @Sendable (URL, URL) throws -> Void; public init(_:); public static let live }`. Behave as `SQLiteStep` does for dependency injection. `live` calls `clonefile(source, destination, CLONE_NOFOLLOW)` and throws on a nonzero result.
  - `public struct SnapshotRequest: Sendable { public var directory: URL; public var lastReadModification: Date?; public var lastReadFile: String?; public var clone: SnapshotClone }`.
  - `public static func ReadOnlySQLite.withSnapshot<T>(of url: URL, in directory: URL, busyTimeout: Duration, clone: SnapshotClone, _ body: (ReadOnlySQLite) throws -> T) throws -> T`. Implement the lifecycle and failure mapping in **Reading a closed database**.
  - **Cursor read rule:** add optional `threadHistoryModification: Date?`, `logsModification: Date?`, `threadHistoryReadFile: String?` and `logsReadFile: String?`, with nil init defaults. Record the selected original file's name and pre-read modification date for `.ok` or `.problem`; `.busy` preserves the previous read stamp and `.failure` clears it. A date suppresses cloning only for the same selected file; a missing or mismatched file name requires a clone. Clearing the stamp on failure permits retry even after a prior successful read with the same date.

- [ ] **Step 1: Write the failing tests**

In `ReadOnlySQLiteTests`, use a `CodexDatabase` fixture closed by `closeLikeCodex()` and a scratch snapshot directory:

```swift
@Test func snapshotReadsAClosedDatabaseAndLeavesNothing() throws {
    // withSnapshot reads the fixture's rows; FileSnapshot.take(home) is unchanged; no -wal or -shm beside the
    // original; the snapshot directory is empty afterwards and has mode 0700.
}
@Test func snapshotUsesTheOriginalFileName() throws {
    // Through a database missing a column, withSnapshot's FormatProblem detail equals a direct read's on the same file.
}
@Test func snapshotIsDiscardedWhenTheWriterReopens() throws {
    // A SnapshotClone that runs .live, then CodexDatabase.reopen(url) and writes a row (creating -wal):
    // throws Busy; the directory is empty.
}
@Test func snapshotIsDiscardedWhenTheFileChangesDuringTheClone() throws {
    // A SnapshotClone that runs .live, then sets the original's modification date forward a second (no -wal):
    // throws Busy; the directory is empty.
}
@Test func snapshotNeedsAClone() throws {
    // A SnapshotClone that throws: withSnapshot throws Closed; the directory is empty.
}
@Test func snapshotIsRemovedWhenTheReadThrows() throws {
    // body throws a synthetic error: it propagates and the directory is empty.
}
@Test func snapshotRejectsSymlinksAndAliasesBeforeWriting() throws {
    // A symlink source, then injected clone results that are a symlink or hard link to the original:
    // no header write occurs; FileSnapshot of the original and link targets is unchanged; cleanup stays in its root.
}
@Test func snapshotRootRejectsSymlinksAndInsecureModes() throws {
    // Existing root is a symlink or has a mode other than 0700: reject before cleanup/clone;
    // preserve an outside sentinel and restore fixture permissions in defer.
}
```

In `CodexUsageSourceTests`, build these as `closedDatabasesAreSkippedQuietlyAndReadAfterReopening` is:

```swift
@Test func closedDatabasesChangedSinceTheLastReadAreReadFromASnapshot() throws {
    // Ingest; write more rows to both databases; close both like Codex; ingest with a snapshot directory:
    // the new failed turn and connection event are in the batch, the state is .ready, Codex's files are unchanged
    // (FileSnapshot), and no -wal or -shm was created.
}
@Test func unchangedClosedDatabaseIsSkippedWithoutASnapshot() throws {
    // Close, ingest once (one snapshot), ingest again with a counting SnapshotClone: zero clones; state .ready.
}
@Test func unchangedClosedDatabaseWithAFormatProblemIsNotClonedAgain() throws {
    // A closed database missing error_json: the first ingest clones and reports the problem; the second clones
    // nothing and reports the kept problem.
}
@Test func leftoverSnapshotsAreRemoved() throws {
    // A stray directory in the snapshot directory is gone after one ingest.
}
@Test func snapshotCleanupFailurePreventsAnotherClone() throws {
    // Make the synthetic root non-writable with a leftover inside (restore permissions in defer):
    // report a read failure, retain the read cursor, and do not invoke clone.
}
@Test func rotatedClosedDatabaseWithTheSameDateIsRead() throws {
    // Read a fixture; select a newer-numbered closed fixture with the same modification date:
    // its unread rows are returned rather than skipped.
}
@Test func failedSnapshotReadIsRetriedWithoutAFileChange() throws {
    // Read successfully, close, then chmod the original to 000 (restore in defer): the next ingest fails.
    // Restore its mode without changing its modification date; retry clones and reads because the stamp was cleared.
}
```

Extend `ReleaseTests.pathsDeriveFromInjectedHome` with the exact derived `codexSnapshots` path and `AcceptanceServiceTests.pathsStayInsideTheSyntheticHome` with that URL in its enumerated path list. These checks test the new runtime path's placement; clone permission and cleanup checks belong in `ReadOnlySQLiteTests`.

Keep `closedDatabasesAreSkippedQuietlyAndReadAfterReopening` and `closedDatabaseKeepsItsFormatProblem` as preservation checks for the default initializer.

- [ ] **Step 2: Run them and confirm they fail**

Run the filtered command with pattern `ReadOnlySQLiteTests|CodexUsageSourceTests`. Expect the build to fail on `withSnapshot`, `SnapshotClone` and `snapshotDirectory`.

- [ ] **Step 3: Implement**

- `withSnapshot` follows **Reading a closed database**. Use `FileHandle` to write the header bytes; validate existing roots and reject symlinks before cleanup or use.
- In each reader's `read`, catch `ReadOnlySQLite.Closed` from the open or the first statement. When `snapshot` is set and **Cursor read rule** requires a read, rerun the query body inside `withSnapshot`. Otherwise rethrow. Select the database URL once per reader attempt, and use that same selection for the query, request comparison and cursor metadata.
- Apply **Cursor read rule** in the source.

- [ ] **Step 4: Run the Codex and integration suites, then the full suite**

Run the filtered command with pattern `TelltaleCodexTests|TelltaleIntegrationTests`; expect PASS. Then `make test`.

- [ ] **Step 5: Update the docs** listed under Files. Add this installed-release check to Native acceptance:
- After Codex quits with recent activity, the next collector run logs no format problem.
- `~/Library/Application Support/Telltale/codex-snapshots` is empty afterwards.
- No `-wal` or `-shm` appears beside the closed Codex databases.

Record it separately from 0.2.1's closed-database check.

- [ ] **Step 6: Commit**

```bash
git add <each modified source and test file listed under Files> telltale/docs/telltale_design_spec.md telltale/README.md docs/lessons_learned.md
git commit -m "Read closed Codex databases through an APFS clone" -m "<what changed and why; replaces the suggested closed-database alert>"
```

### Task 3: Word read failures as read failures

**Files:**
- Modify: `Sources/TelltaleCore/Records.swift`: `SetupState.readProblem(String)`.
- Modify: `Sources/TelltaleCore/Collector/CollectorRun.swift`:
  - `unavailableSince` implements the **Read-problem since** decision.
  - `describe` logs `read problem: <detail>`.
- Modify: `Sources/TelltaleCore/Launchd/CollectorHealth.swift`: extend the format-problem branch of `CollectorHealth.evaluate` to `.readProblem`, using `Copy.readProblem` for that kind.
- Modify: `Sources/TelltaleCore/Read/ProviderSummary.swift`: add `State.readProblem(since: Date)`; behave as the `.formatProblem` branch does for stored-state mapping.
- Modify: `Sources/TelltaleCore/Rules/Copy.swift`: `readProblem(source:since:calendar:)`. `providerState` handles the new case.
- Modify: `Sources/TelltaleCodex/CodexUsageSource.swift`:
  - `ingest` collects format and read problems separately. `.failure` outcomes and `readRollouts`' `catch` produce read problems.
  - The state is the first format problem, else the first read problem, else `.ready`.
- Modify: `Sources/TelltaleClaude/ClaudeUsageSource.swift`: the transcript `catch` records a read problem; a format problem in the same ingest wins.
- Modify: every `switch` over `SetupState` or `ProviderSummary.State` that the compiler reports as non-exhaustive.
- Test:
  - `Tests/TelltaleCoreTests/`: `RecordsTests.swift`, `CopyTests.swift`, `CollectorHealthTests.swift`, `ProviderSummaryTests.swift`, `CollectorRunTests.swift`
  - `Tests/TelltaleCodexTests/CodexUsageSourceTests.swift`
  - `Tests/TelltaleClaudeTests/ClaudeUsageSourceTests.swift`
- Docs:
  - Spec §6.5: a "Read problems" paragraph covering the shared notification policy, the precedence, and the "Read-problem since" decision.
  - Spec §7.4: the Collector health row's condition covers a format or read problem.
  - Spec §9.4: the provider state line can show `Copy.readProblem`.
  - README's deployment section, beside `--rollback`: the "Read-problem rollback" decision, with the `sqlite3` command that deletes one `source_state` row by `source`.
  - `../docs/lessons_learned.md`.

**Interfaces:**
- Consumes: Task 1's `.failure` outcome.
- Produces: `SetupState.readProblem(String)`, `ProviderSummary.State.readProblem(since: Date)` and `Copy.readProblem(source: String, since: Date, calendar: Calendar) -> String`.

- [ ] **Step 1: Write the failing tests**

```swift
// RecordsTests
@Test func readProblemRoundTrips()  // JSON encode and decode .readProblem("Synthetic read failure")

// CopyTests: a CopyCase for readProblem matching the copy table; providerState(.readProblem(since:)) gives the same text.

// CollectorHealthTests, built as formatProblemLightsRed and formatProblemFromOneRunShowsButDoesNotNotify
@Test func readProblemLightsRedWithItsOwnWording()   // problems contains Copy.readProblem(source: "Example", ...)
@Test func readProblemFromOneRunShowsButDoesNotNotify()
@Test func noticeNamesTheConfirmedReadProblem()

// ProviderSummaryTests
@Test func readProblemRowGivesAReadProblemState()

// CollectorRunTests, with FakeUsageSource's next state
@Test func readProblemKeepsItsSinceAcrossRuns()       // two runs with .readProblem: unavailableSince is the first run's time
@Test func movingFromFormatToReadProblemRestartsSince()

// CodexUsageSourceTests
@Test func formatProblemOutranksAReadProblem()        // a database missing error_json plus a broken .zst rollout → .formatProblem

// ClaudeUsageSourceTests
@Test func unreadableTranscriptIsAReadProblem()       // a transcript file with mode 000 (restored in a defer) → .readProblem
```

Find expectations to update with `rg -n 'formatProblem' Tests`, inspecting each fixture to distinguish read failures from format failures. Apply this task's precedence contract rather than changing every match. Include Task 1's regression tests in that inspection and name changed expectations with their reasons in the commit body.

- [ ] **Step 2: Run them and confirm they fail**

Run the filtered command with pattern `RecordsTests|CopyTests|CollectorHealthTests|ProviderSummaryTests|CollectorRunTests|CodexUsageSourceTests|ClaudeUsageSourceTests`. Expect the build to fail on `readProblem`.

- [ ] **Step 3: Implement** as specified under Files.

- [ ] **Step 4: Run the full suite**: `make test`. Expected: PASS.

- [ ] **Step 5: Update the docs** listed under Files, then commit:

```bash
git add <each modified source and test file listed under Files> telltale/docs/telltale_design_spec.md telltale/README.md docs/lessons_learned.md
git commit -m "Word source read failures as read problems, not format changes" -m "<what changed and why; the tests whose expected state changed>"
```

### Task 4: Apply the lookback cutoff to the filtered batch fields

**Files:**
- Modify: `Sources/TelltaleCore/Plugins.swift`: `IngestBatch.droppingBefore(_:)`.
- Modify: `Sources/TelltaleCore/Collector/CollectorRun.swift`: `ingest(_:backfillFrom:calendar:)` applies `droppingBefore` before its transaction. When rows are dropped, write `"\(source.displayName): skipped \(n) record(s) from before the lookback"`; behave as the existing settlement log call does for logging.
- Modify: `Tests/TelltaleCoreTests/CollectorRunTests.swift`: remove `FakeUsageSource.ingest`'s `response.end >= backfillFrom` filter so the collector regression tests exercise the production cutoff.
- Create: `Tests/TelltaleCoreTests/IngestBatchTests.swift`.
- Test: `Tests/TelltaleCoreTests/CollectorRunTests.swift` and `Tests/TelltaleIntegrationTests/CollectorIntegrationTests.swift`
- Docs:
  - Spec §7.3 "Backfill" and §8 "Cold start": state the cutoff and preserved-field contract from `IngestBatch.droppingBefore` below.
  - `../docs/lessons_learned.md`.

**Interfaces:**
- Produces: `public func IngestBatch.droppingBefore(_ cutoff: Date) -> (batch: IngestBatch, dropped: Int)`. It keeps:
  - responses with `end >= cutoff`;
  - compactions and connection events with `at >= cutoff`;
  - every other field unchanged.

- [ ] **Step 1: Write the failing tests**

```swift
// IngestBatchTests
@Test func batchDropsRecordsFromBeforeTheCutoff() {
    // A response ending a second before the cutoff and one ending at it, and the same for a compaction and a
    // connection event: the earlier three are dropped (dropped == 3); failed turns, gaps, the usage limit and
    // the version are unchanged.
}

// CollectorRunTests, built as rssOnlyPostsOutsideTheLookbackAreNotRecorded
@Test func linesFromBeforeTheLookbackAreNotStored() async throws {
    // FakeUsageSource (without its own filter) returns a response, a compaction and a connection event from
    // 31 days before now, and one of each from an hour before now: only the recent ones are stored;
    // ProviderSummary's oldestResponse is the recent response's end; the log has the skipped line with 3.
}
@Test func catchUpAfterTheLookbackKeepsOnlyRecentLines() async throws {
    // A run, then a run 35 days later whose source returns responses from 33 days and 1 day before it:
    // only the 1-day response is stored, and the run succeeds.
}

// CollectorIntegrationTests, with its session(start:firstEnd:runs:) and write(_:through:) helpers
@Test func coldStartReadsOnlyLinesInsideTheLookback() async throws {
    // One rollout whose first response is 40 days before the run and whose last is 1 day before it:
    // after the first run, responses holds only the responses inside the lookback.
}
```

- [ ] **Step 2: Run them and confirm they fail**

Run the filtered command with pattern `IngestBatchTests|CollectorRunTests|CollectorIntegrationTests`.
- **First:** the build fails on `droppingBefore`.
- **After stubbing it to return the batch unchanged:** confirm the tests `linesFromBeforeTheLookbackAreNotStored`, `catchUpAfterTheLookbackKeepsOnlyRecentLines` and `coldStartReadsOnlyLinesInsideTheLookback` fail because old rows are stored.

- [ ] **Step 3: Implement** as specified under Files and Interfaces.

- [ ] **Step 4: Run the full suite**: `make test`.

Investigate any changed existing-test outcome after removing the fake's filter. Change a fixture only when it violates the cutoff contract, with the reason documented; preserve assertions that reveal a production defect.

- [ ] **Step 5: Update the docs** listed under Files, then commit:

```bash
git add telltale/Sources/TelltaleCore/Plugins.swift telltale/Sources/TelltaleCore/Collector/CollectorRun.swift telltale/Tests/TelltaleCoreTests/IngestBatchTests.swift telltale/Tests/TelltaleCoreTests/CollectorRunTests.swift telltale/Tests/TelltaleIntegrationTests/CollectorIntegrationTests.swift telltale/docs/telltale_design_spec.md docs/lessons_learned.md
git commit -m "Apply the ingest batch lookback filter" -m "<what changed and why; the fake's filter removal>"
```

### Task 5: Acknowledgement state and the snapshot's judgement

**Files:**
- Create: `Sources/TelltaleCore/Read/Acknowledgements.swift`: the record types, their settings keys, `Acknowledgements`, and the `Store` write extension.
- Create: `Sources/TelltaleCore/Rules/FailedTurnEpisodeDetail.swift`: the typed counted-failure detail described under Interfaces.
- Modify: `Sources/TelltaleCore/Rules/RuleEngine.swift`: persist counted membership in `failedTurns` using the existing evaluation transaction and episode-update path.
- Modify: `Sources/TelltaleCore/Read/PanelSnapshot.swift`:
  - `Alert`'s fields and init;
  - `unacknowledged`, `attention` and `isAcknowledged`;
  - the episode loop and the sort in `load`;
  - the failed-turn wording;
  - decode failed-turn episode detail beside the episode's canonical total;
  - the type's doc comment.
- Modify: `Sources/TelltaleCore/Rules/NotificationPolicy.swift`: extract `threadID(rule:provider:scope:)` and use it in `notice(_:kind:body:)`.
- Modify: `Sources/TelltaleCore/Store/Store+Rules.swift`: document `EpisodeRow.detail`'s typed use for failed-turn episodes; retain its existing storage interface.
- Modify: `Sources/TelltaleCore/Rules/Copy.swift`: the failed-turn and acknowledgement members in the copy table.
- Test: `Tests/TelltaleCoreTests/PanelSnapshotTests.swift`, `RuleEngineTests.swift`, `CollectorRunTests.swift`, `CopyTests.swift`, `NotificationPolicyTests.swift`
- Docs:
  - Spec §7.2: the counted-membership contract from Task 5's collector rules. Spec §7.4: failed-turn wording and **Legacy failed-turn reasons**, under the table.
  - Spec §9.1: move the **Acknowledgement** behavior contract into an "Acknowledging" bullet group in the maintained spec, including the hold table. State the rules there rather than linking readers back to this implementation plan.
  - Visual doc "Menu-bar glyph" and "Panel": the ring, the hollow diamond and the row order.
  - `../docs/lessons_learned.md`: the stale failed-turn wording.

**Interfaces:**
- Produces:
  - `public struct FailedTurnEpisodeDetail: Codable, Sendable, Equatable` in `EpisodeRow.detail`: `priorCount: Int` for counted failures predating membership recording, and ordered `failures: [Failure]`. Nested public `Failure: Codable, Sendable, Equatable` stores `turnID: String` and `errorCode: String`. Supply public initializers, `encoded() throws -> Data`, `decode(_ data: Data?) throws -> Self?` (nil data means legacy), and `reasons(in range: Range<Int>) -> [String]?`. The range indexes the episode's counted failures; return nil if any requested member lies in `priorCount`, otherwise return the recorded codes. Validate nonnegative counts, valid ranges and unique IDs; malformed non-nil data is a stored-data error, not a legacy record. Store through the existing `EpisodeRow.detail` interface, without a schema change.
  - `public struct AlertAcknowledgement: Sendable, Equatable, Hashable, Codable { public var at: Date; public var severity: LampColor; public var failedTurns: Int? }`, with a memberwise public init.
  - `public struct CollectorAcknowledgement: Sendable, Equatable, Hashable, Codable { public var at: Date; public var keys: [String] }`, with a memberwise public init.
  - `SettingKey.alertAcknowledgements: SettingKey<[String: AlertAcknowledgement]>` (name `alertAcknowledgements`, default `[:]`) and `SettingKey.collectorAcknowledgement: SettingKey<CollectorAcknowledgement?>` (name `collectorAcknowledgement`, default nil).
  - `public enum Acknowledgements`:
    - `static func key(_ episode: EpisodeRow) -> String`: rule, provider, scope and onset in whole Unix seconds, joined by `|`.
    - `static func holds(_ ack: AlertAcknowledgement, severity: LampColor, failedTurns: Int?) -> Bool` and `static func holds(_ ack: CollectorAcknowledgement, keys: Set<String>) -> Bool`. Each implements its row of the Design hold table. The collector form is false for empty `keys`.
  - `extension Store { public func acknowledge(_ alerts: [PanelSnapshot.Alert], at: Date) throws; public func markAsNew(key: String) throws }`. Each runs in one transaction. `acknowledge` records each alert's `color` and `failedTurns`, ignores alerts with an empty `key`, and then drops keys that aren't among `openEpisodes()`' keys.
  - `PanelSnapshot.Alert` gains `key: String`, `detail: String?`, `acknowledgedAt: Date?`, `failedTurns: Int?` and `threadID: String?`. Its init is `init(color:text:key: String = "", detail: String? = nil, acknowledgedAt: Date? = nil, failedTurns: Int? = nil, threadID: String? = nil)`.
  - `PanelSnapshot.unacknowledged: [Signal: LampColor]`:
    - The init parameter is `unacknowledged: [Signal: LampColor]? = nil`. Nil derives attention from the lit lamps; preserve the expectations in `StatusIconTests`.
    - Also add `public var attention: LampColor?`, the max of `unacknowledged`.
    - Also add `public func isAcknowledged(_ signal: Signal) -> Bool`: true when the lamp is lit and absent from `unacknowledged`.
  - `public static func NotificationPolicy.threadID(rule: RuleID, provider: String, scope: String) -> String`; behave as `notice(_:kind:body:)`'s thread construction does. Retain `failedTurnsThreadID(provider:)` for that rule.

- [ ] **Step 1: Write the failing tests**

In `PanelSnapshotTests`, behave as `Panel.episode` and `withRules` do for fixture setup. Give its fixture helper explicit `onset:`, `worstValue:` and `detail:` parameters. Use the real rule engine for membership/settlement regressions; direct UI fixtures must seed consistent typed detail. Preserve the event-body fallback for fixtures without a valid canonical total.

```swift
@Test func failedTurnAlertCountsEveryFailureInTheEpisode() throws {
    // Episode onset 09:10; 2 turns counted at 09:10 and 1 at 09:25, all serverOverloaded:
    // text == Copy.failedTurnsOpen(source: "Codex", noun: "turn", count: 3, reasons: [...], since: 09:10, ...),
    // failedTurns == 3, threadID == NotificationPolicy.failedTurnsThreadID(provider: "codex").
    // A fixture without a valid integer failed-turn total keeps its event body (redOutranksAmberInAlertOrder).
}
@Test func settledFailuresAtTheEpisodeBoundaryAreNotCounted() throws {
    // On a cadence-aligned cutoff, upsert old failures completed before cutoff and fresh failures completing at cutoff.
    // Include a fresh long-running turn whose start precedes cutoff. Settle old turns, then evaluate at cutoff
    // through RuleEngine so episode.firedAt equals cutoff. The displayed count, reasons and saved acknowledgement
    // include only the fresh turns. Advance the cutoff on the next run, ingest another old arrival and settle it,
    // then count another fresh turn while the episode remains open. The delta, total, membership and reasons
    // still exclude every settled row, including the newly settled arrival.
}
@Test func legacyFailedTurnEpisodeKeepsItsCountWithoutInventingReasons() throws {
    // A valid canonical count and nil detail: Copy.failedTurnsOpen uses that count without a reason suffix.
    // Acknowledge it, then count a fresh failure through RuleEngine: its new reason is known and its delta is exact.
}
@Test func acknowledgedAlertStaysListedButLeavesAttention() throws {
    // Red failed turns and amber slower; acknowledge the failed-turn alert at 09:30 through Store.acknowledge:
    // alerts[0] is the amber alert; alerts[1].acknowledgedAt == 09:30 and detail == Copy.acknowledged(at: 09:30, ...);
    // lamps[.errors] == .red; unacknowledged == [.speed: .amber]; attention == .amber; isAcknowledged(.errors).
}
@Test func failureCountedDuringAcknowledgeComesBackNew() throws {
    // 2 counted; acknowledge an Alert whose failedTurns is 2; a 3rd is counted at a point before the acknowledgement time:
    // acknowledgedAt == nil; text == Copy.failedTurnsBeyondAcknowledged(... count: 1 ...);
    // detail == Copy.failedTurnsTotal(count: 3, ...); attention == .red.
}
@Test func escalationBringsAnAcknowledgedAlertBack() throws {
    // Acknowledge an amber slower episode, then escalate it as redOutranksAmberInAlertOrder does → new, attention == .red.
}
@Test func acknowledgementSurvivesANewEpisodeID() throws {
    // Acknowledge, end the episode, insert an identical open row (same rule, provider, scope, onset) → acknowledged.
}
@Test func newEpisodeAfterClearIsNew() throws {
    // Acknowledge, end the episode, open one with a later onset → new; acknowledge() prunes the old key from the stored map.
}
@Test func alertWithoutALampNeverLightsTheGlyph() throws {
    // A usageLimit episode alone: one alert, attention == nil, mostSevere == nil.
}
```

In `CopyTests`, add a `CopyCase` for each copy-table member this task adds, singular and plural, including unknown/empty reason suffixes.

In `RuleEngineTests`, add `failedTurnDetailsRecordOnlyCountedBatches`: verify detail on fire and later batches, a new Store/engine after relaunch, exclusion of settled old arrivals across advancing cutoffs, and atomic rollback if recording detail fails. In `CollectorRunTests`, add `rebuildRecreatesFailedTurnDetails` using the existing rebuild fixture path; assert that replay records the counted batches and that acknowledgement matching still follows the natural key. These tests cover the collector write side, beyond the panel-read regression.

In `NotificationPolicyTests`:
- `threadID(rule: .slower, provider: "codex", scope: Synth.model)` equals the `threadID` of the notice that `notice(_:kind:body:)` builds for that episode.
- An existing episode notice's `threadID` is unchanged.

Update `slowEpisodeLightsSpeedAmber`'s whole-`Alert` expectation to include `key` and `threadID`. `Alert` now identifies its episode; say so in the commit body.

- [ ] **Step 2: Run them and confirm they fail**

Run the filtered command with pattern `PanelSnapshotTests|CopyTests|NotificationPolicyTests`. Expect the build to fail on `Acknowledgements`, `acknowledge`, `unacknowledged`, `attention` and the new `Copy` members.

- [ ] **Step 3: Implement**

In `load`'s episode loop:
- **Collector membership:** in `RuleEngine.failedTurns`, after `step` returns the open episode and for a nonempty counted batch, decode its detail or initialize it with `priorCount = canonicalTotal - batch.count`. Append that batch's turn IDs and error codes in evaluation order. Require `priorCount + failures.count == canonicalTotal`, where `canonicalTotal` comes from the episode's `Worst.total` value; do not count raw rows again. Update the in-memory `openEpisodes` entry and add its ID to `worstChanged` so `finish()` persists detail together with `markEvaluated`, the episode total and rule state in the existing transaction. Do not record settled rows. This write-side association is required because evaluation timestamps cannot distinguish counted failures from settlement across runs.
- **Lookup:** compute the key and look up the acknowledgement. For `.failedTurns`, take `Int(exactly: episode.worstValue)` as the canonical count and decode `FailedTurnEpisodeDetail`. Read reasons by counted-index range from that detail, never by querying `evaluated_at`. A valid legacy total with nil detail uses **Legacy failed-turn reasons**; an invalid total keeps the event-body fallback and leaves `failedTurns` nil. Validate a decoded detail's count against the canonical total.
- **Failed-turn wording:**
  - For a valid count, word the alert with `Copy.failedTurnsOpen`, using `episode.onset` as "since" and the source's `name` and `failureNoun`.
  - When an acknowledgement has a saved failed-turn count and the current count exceeds it, use the positive difference as `n`, word with `Copy.failedTurnsBeyondAcknowledged` using that counted-index range's reasons, and put `Copy.failedTurnsTotal` in the alert's `detail`. With no saved count, use the open wording instead.
  - For other wording, behave as `PanelSnapshot.load`'s source-prefix code does.
- **`unacknowledged`:** takes each new alert's color under its rule's signal (rules with a signal only). A red Collector lamp is added here unacknowledged; Task 7 makes it acknowledgeable.
- **Sort:** implement Design's **Panel and dashboard alert rows** order.
- **`waiting`:** passes nil for `unacknowledged`.

- [ ] **Step 4: Run the suites, then the full suite**

Run the filtered command with pattern `TelltaleCoreTests`; expect PASS. Then `make test`.

- [ ] **Step 5: Update the docs** listed under Files, then commit:

```bash
git add <each modified source and test file listed under Files> telltale/docs/telltale_design_spec.md telltale/docs/telltale_visual_design.md docs/lessons_learned.md
git commit -m "Judge open alerts against stored acknowledgements" -m "<what changed and why; the failed-turn wording fix; the Alert equality change>"
```

### Task 6: Acknowledge from the panel and dashboard, and the ring glyph

**Files:**
- Modify: `Sources/Telltale/UserActions.swift`: `acknowledge(_:)` and `markAsNew(key:)`.
- Modify: `Sources/Telltale/UserNotifier.swift`: `NotificationService.removeDelivered(identifiers:)`, `NativeNotificationService`'s implementation (`center.removeDeliveredNotifications(withIdentifiers:)`), and `UserNotifier.removeDelivered(threadIDs:)`.
- Modify: `Sources/Telltale/PanelView.swift`: `PanelModel.acknowledge(_:)` and `markAsNew(_:)`, the alert rows, Acknowledge all, and a shared `AlertAcknowledgeButton` view.
- Modify: `Sources/Telltale/ModelView.swift` (the alert list) and `Sources/Telltale/DashboardView.swift` (`AlertLine` gains an optional trailing accessory and a hollow state).
- Modify: `Sources/Telltale/StatusIcon.swift`: `image(for:)` and `accessibility(for:)`.
- Modify: the `NotificationService` conformers in the tests:
  - `NotificationServiceStub` in `Tests/TelltaleAppTests/UserNotifierTests.swift` (it records the removed identifiers);
  - `Tests/TelltaleAppTests/CollectorMonitorTests.swift`;
  - `Tests/TelltaleAppTests/NotificationCheckTests.swift`;
  - `Tests/Snapshots/Snapshots.swift`;
  - `Tests/Acceptance/AcceptanceApp.swift`.
  - Fix any other conformer the compiler reports.
- Test: `Tests/TelltaleAppTests/StatusIconTests.swift`, `PanelViewTests.swift`, `UserNotifierTests.swift`, `ModelViewTests.swift`
- Docs: README "Menu bar and panel" and "Dashboard": acknowledging, the ring, and Mark as new.

**Interfaces:**
- Consumes: Task 5's `Store.acknowledge(_:at:)`, `Store.markAsNew(key:)`, `PanelSnapshot.attention`, `isAcknowledged(_:)`, `Alert.key`, `acknowledgedAt` and `threadID`, and its `Copy` members.
- Produces:
  - `UserActions.acknowledge(_ alerts: [PanelSnapshot.Alert]) throws` and `UserActions.markAsNew(key: String) throws`, through `write`.
  - `PanelModel.acknowledge(_ alerts: [PanelSnapshot.Alert])`: write through `perform`; after success invoke the notification-removal interface below using `Set(alerts.compactMap(\.threadID))`. Do not remove notifications on a failed write.
  - `PanelModel.markAsNew(_ alert: PanelSnapshot.Alert)`.
  - `NotificationService.removeDelivered(identifiers: [String])`.
  - `UserNotifier.removeDelivered(threadIDs: Set<String>) async`: removes the delivered requests whose `content.threadIdentifier` is in the set.

- [ ] **Step 1: Write the failing tests**

In `StatusIconTests`:

```swift
@Test func acknowledgedLampsDrawARing() throws {
    // snapshot(lamps: [.errors: .red], unacknowledged: [:]): red pixels exist, all in the dot's square,
    // and the square's centre pixel isn't red (a ring, not a disc), in darkAqua and aqua.
}
@Test func newAlertFillsTheDotInItsColorOverAnAcknowledgedRed() throws {
    // lamps [.errors: .red, .speed: .amber], unacknowledged [.speed: .amber] → amber pixels, no red pixels.
}
@Test func accessibilityMarksAcknowledgedLamps() {
    // lamps [.errors: .red, .speed: .amber], unacknowledged [.speed: .amber]
    // → "Telltale: Speed amber, Errors red (acknowledged)."
}
```

Give `StatusIconTests.snapshot(_:)` an optional `unacknowledged:` parameter; preserve the existing call sites and expectations.

In `PanelViewTests`, use `PanelWorld`:

```swift
@Test func acknowledgeAndMarkAsNewRoundTrip() throws {
    // PanelWorld.addAlert, reload, acknowledge(snapshot.alerts): after reload the alert's acknowledgedAt is set
    // and attention is nil; markAsNew restores attention == .amber. Neither creates a missing database
    // (as actionsNeverCreateTheDatabase checks).
}
@Test func acknowledgeAllCoversOnlyTheAlertsShown() throws {
    // Take snapshot.alerts; insert a second open episode with a different scope ("synthetic-second-model") and onset,
    // as addAlert inserts its episode; acknowledge(the taken alerts) and reload: the second episode's alert is new.
}
```

In `UserNotifierTests`:

```swift
@Test func removeDeliveredMatchesThreadIdentifiers() async {
    // The stub delivers requests in threads "failedTurns.codex", "slower.codex.example" and "collectorHealth";
    // removeDelivered(threadIDs: ["failedTurns.codex"]) removes only the first one's identifier.
}
```

In `ModelViewTests`: the model view lays out with an acknowledged alert, following the file's existing layout assertions.

- [ ] **Step 2: Run them and confirm they fail**

Run the filtered command with pattern `StatusIconTests|PanelViewTests|UserNotifierTests|ModelViewTests`. Expect the build to fail on `unacknowledged`, `acknowledge`, `markAsNew` and `removeDelivered`.

- [ ] **Step 3: Implement**

- **Glyph:**
  - Draw the filled dot for `attention`.
  - Otherwise, when `mostSevere` is set, draw Design's ring using `NSBezierPath(ovalIn: dot.insetBy(dx: 0.75, dy: 0.75))`.
  - Behave as `StatusIcon.image(for:)` does for dot geometry and clearing.
- **Accessibility:** follows the Glyph rule in Design.
- **Rows:** follow Design's row rules.
  - Draw the hollow diamond by stroking the row's diamond shape at 1.5 pt in the lamp color.
  - The button is borderless and 13 pt, with `.help` and `.accessibilityLabel` from its `Copy` member.
  - Acknowledge all is a borderless 11 pt button, right-aligned under the list; follow Design for its eligibility and arguments.
  - Behave as `AlertLine.body` does for displaying `detail`.

- [ ] **Step 4: Run the suites, then the full suite**

Run the filtered command with pattern `TelltaleAppTests`; expect PASS. Then `make test`.

- [ ] **Step 5: Update the README** sections listed under Files, then commit:

```bash
git add <each modified source and test file listed under Files> telltale/README.md
git commit -m "Acknowledge alerts from the panel and dashboard" -m "<what changed and why>"
```

### Task 7: Acknowledge the Collector health problem, and show acknowledgement in the harnesses

**Files:**
- Modify: `Sources/TelltaleCore/Launchd/CollectorHealth.swift`: `CollectorHealthReport.problemKeys: Set<String>`, filled by `CollectorHealth.evaluate` under **Collector problem identity**. Add an init parameter defaulting to `[]` so existing synthetic report constructors still compile; acknowledgement fixtures pass explicit keys.
- Modify: `Sources/TelltaleCore/Read/PanelSnapshot.swift`: `collectorAcknowledgedAt: Date?` (an init parameter, default nil). `load` sets it from `.collectorAcknowledgement` when `health?.lamp == .red` and `Acknowledgements.holds(_:keys: health.problemKeys)`. An acknowledged Collector is left out of `unacknowledged`.
- Modify: `Sources/Telltale/CollectorMonitor.swift`: in `check()`, after `assess()`, delete a stored collector acknowledgement through `.readWriteExisting` only when `report.lamp != .red`. `StoreError.notInitialized` means there's nothing to clear. A read/assessment failure does not clear it.
- Modify: `Sources/Telltale/UserActions.swift`: `acknowledgeCollector(keys:)` and `markCollectorAsNew()`.
- Modify: `Sources/Telltale/PanelView.swift`:
  - `PanelModel` gains `canAcknowledgeCollector: Bool` (an init parameter, default false), `offersCollectorAcknowledgement` and the Collector actions.
  - Route the Collector action through Task 6's notification-removal contract with `CollectorMonitor.threadID`.
  - The footer implements the Collector row contract in **Panel and dashboard alert rows**.
- Modify: `Sources/Telltale/AppDelegate.swift`: pass `isInstalledCopy` to `PanelModel`.
- Modify: `Sources/Telltale/LiveStore.swift`: expose `hasReadableDatabase`, initially false. Set it true after `PanelSnapshot.load` succeeds and false in each open/read failure branch, including `.waiting`; a stale retained snapshot does not keep writes enabled.
- Modify: `Tests/Acceptance/SyntheticEnvironment.swift`: a new `Scene.acknowledged`. Start from `.alerting` and acknowledge its alerts; add a red failed-turn episode whose counted failures exceed its saved acknowledgement. Define synthetic counts in the seed and derive harness expectations from that seed's records.
- Modify: `Tests/Snapshots/Snapshots.swift`:
  - Add `.acknowledged` to `states`.
  - In `expect`, check the acknowledged seed alerts, the re-armed failed-turn row, and `attention == .red`, using the scene seed's records.
  - Add the scene's light and dark PNGs to the total in the `pngs.count` guard and its message, and to the panel line of the "Validated … PNGs" output, naming the scene.
  - Handle the new case in every exhaustive `Scene` switch the compiler reports.
- Modify: `Tests/Acceptance/AcceptanceServiceTests.swift`:
  - Add `.acknowledged` to `seededScenesBuildTheirPanels`' loop as well as its switch, using the scene seed's records to assert acknowledgement and attention.
  - The expected failed-turn text in the red-alert test becomes `Copy.failedTurnsOpen` for the rows `addRedAlert` seeds.
- Modify: `Tests/ReleaseChecks/check_harnesses.sh`: update the panel-scene counter for the new scene's appearances.
- Modify: `Tests/Acceptance/AcceptanceApp.swift`:
  - `addRedAlert` stores the counted failed-turn records and typed episode detail corresponding to its synthetic fixture, using error code `synthetic failure` and the episode's fire time. Share the seeding helper with `Scene.acknowledged`.
  - A new "Add failed turn" button appends a synthetic counted record, reason membership and total to the open failed-turn episode in a transaction. When none is open, it creates one with `addRedAlert`.
- Test: `Tests/TelltaleCoreTests/PanelSnapshotTests.swift` and `CollectorHealthTests.swift`; `Tests/TelltaleAppTests/CollectorMonitorTests.swift`, `PanelViewTests.swift` and `LiveStoreTests.swift`
- Docs:
  - Spec §9.1 and §9.3: the collector acknowledgement, the problem keys, when it is offered, how a healthy check clears it, and the "Collector acknowledgement limit" decision.
  - Spec §13: add the acknowledged panel scene to the snapshot list.
  - README "Build and test": the panel PNG count and the `make snapshots` scene list.
  - The repository-root `agents.md`, Validation Matrix, Telltale's Snapshots entry: the PNG count and the scene list.
  - README "Native acceptance": the checks in Step 5.
  - README "Results": "Not yet run" entries for the release (Decisions).

**Interfaces:**
- Consumes: Task 5's `CollectorAcknowledgement`, `.collectorAcknowledgement` and `Acknowledgements.holds(_:keys:)`; Task 6's footer and row views.
- Produces:
  - `CollectorHealthReport.problemKeys`;
  - `PanelSnapshot.collectorAcknowledgedAt`;
  - `UserActions.acknowledgeCollector(keys: [String]) throws` and `UserActions.markCollectorAsNew() throws`;
  - `PanelModel.canAcknowledgeCollector`;
  - `PanelModel.offersCollectorAcknowledgement: Bool`: `canAcknowledgeCollector && store.hasReadableDatabase && store.snapshot.collector == .red`. Do not use `checkedAt` as a proxy for database availability.

- [ ] **Step 1: Write the failing tests**

In `CollectorHealthTests`:

```swift
@Test func problemKeysNameTheCollectorAndEachSource() {
    // Not loaded → ["collector"]; a format problem for source "example" → ["source.example"]; both → both.
}
@Test func repairOnlyRedCollectorHasAProblemKey() {
    // Use missingPlistWhileEnabledIsRed's fixtures, including the mismatched executable:
    // repair-only red receives ["collector"] despite an empty problems list; no notification condition is added.
}
```

In `PanelSnapshotTests`:

```swift
@Test func collectorAcknowledgementFollowsProblemKeys() throws {
    // A stored acknowledgement of ["collector"]:
    // - health red with a collector-failing problem → acknowledged, attention == nil;
    // - the same health one interval later (different "Next try" text) → still acknowledged;
    // - add a source problem (key "source.example") → collectorAcknowledgedAt == nil, attention == .red.
}
@Test func collectorProblemKindsShareAcknowledgement() throws {
    // Acknowledge the not-loaded report; replace it with failing and overdue reports:
    // it stays acknowledged under Collector problem identity.
}
@Test func repairOnlyRedCollectorCanStayAcknowledged() throws {
    // A repair-only health report and stored ["collector"] acknowledgement:
    // collectorAcknowledgedAt is set and the Collector is absent from unacknowledged.
}
```

In `CollectorMonitorTests`, following `postsRecoveredWhenGone`:

```swift
@Test func collectorAcknowledgementClearsWhenHealthy() async throws {
    // Store an acknowledgement and exercise check() against the authoritative clearing rule in Files,
    // including repair-only red with no problem text, green, off, and an assessment failure.
}
```

In `PanelViewTests`:

```swift
@Test func collectorAcknowledgementNeedsTheInstalledCopyAndADatabase() throws {
    // With a red Collector lamp read from the database: canAcknowledgeCollector false → offers false; true → true.
    // The initialized DB contains only failed runs, so checkedAt is nil: offers true for the installed copy.
    // Missing/uninitialized DBs and read failures (including a stale retained snapshot) → offers false.
}
@Test func acknowledgingTheCollectorRemovesItsNotifications() async throws {
    // A delivered "collectorHealth" request: acknowledging the collector removes it.
}
```

In `LiveStoreTests`, cover `hasReadableDatabase` after reading a database with no successful run, after removal or an open/read failure, and after recovery.

- [ ] **Step 2: Run them and confirm they fail**

Run the filtered command with pattern `CollectorHealthTests|PanelSnapshotTests|CollectorMonitorTests|PanelViewTests`. Expect the build to fail on `problemKeys`, `collectorAcknowledgedAt`, `acknowledgeCollector` and `canAcknowledgeCollector`.

- [ ] **Step 3: Implement** as specified under Files.

- [ ] **Step 4: Run the suites, the full suite, then the harnesses**

1. Run the filtered command with pattern `TelltaleCoreTests|TelltaleAppTests`.
2. Run `make test`.
3. Run `make snapshots`, then inspect `acknowledged-light.png` and `acknowledged-dark.png`:
   - the new red row comes first, with its `Copy.failedTurnsTotal` detail;
   - the seed's acknowledged rows follow **Panel and dashboard alert rows**;
   - Acknowledge all follows that section's eligibility rule.
4. Look at every other PNG for regressions.
5. Remove the snapshot directory with the command `make snapshots` printed.

- [ ] **Step 5: Update the docs** listed under Files. Add these Native acceptance checks, run on the acceptance bundle:
- First acknowledge the existing alerts, then **Add red alert** and ✓ on it. Check the glyph against **Glyph**, the row against **Panel and dashboard alert rows**, and VoiceOver against the accessibility contract.
- **Add failed turn**: the dot fills red again, and the row shows `Copy.failedTurnsBeyondAcknowledged`.
- Exercise Acknowledge all and Mark as new against the **Panel and dashboard alert rows** contract.
- Quit and reopen: the acknowledgements are kept.
- Installed release only, owner-run, because it is a real launchd change:
  - Acknowledge existing rule alerts before testing the Collector-only glyph. Boot out the collector job and acknowledge the Collector problem; verify the footer and glyph against their Design contracts.
  - Wait past a collector interval: the not-loaded problem stays acknowledged. This scenario does not test changing footer text; use `collectorAcknowledgementFollowsProblemKeys` for a failed-run report whose next-try text changes.
  - Repair the job: the acknowledgement is gone at the next check.

- [ ] **Step 6: Commit**

```bash
git add <each modified file listed under Files> agents.md
git commit -m "Acknowledge Collector health and cover acknowledgement in the harnesses" -m "<what changed and why; the harness PNG count change>"
```

### Task 8: Show the version, fix the idle arrival note, add the idle sidebar scene, and release

**Files:**
- Modify: `Sources/TelltaleCore/Rules/Copy.swift`: `versionLine` and `arrivalIdle(name:days:)`.
- Modify: `Sources/TelltaleCore/Read/PanelSnapshot.swift`: in the arrival loop, use `Copy.arrivalIdle` when `recent` is empty and `models` isn't.
- Create: `Sources/Telltale/AppBundle.swift`: `enum AppBundle { static func buildHelp(info: [String: Any]?) -> String? }`. It returns `"Build \(CFBundleVersion)"` when the dictionary has a non-empty `CFBundleVersion`, otherwise nil. The views pass `Bundle.main.infoDictionary`.
- Modify: `Sources/Telltale/PanelView.swift`: the footer's bottom row puts `Copy.versionLine` at the left (11 pt, `.tertiary`), with `.help` from `AppBundle.buildHelp` and the accessibility identifier `version`.
- Modify: `Sources/Telltale/DashboardView.swift`: `DashboardSidebar` pins the same line under its `Spacer` (11 pt, `Theme.dim`, horizontal padding like the group captions), with the same help and identifier.
- Modify: `Tests/Acceptance/SyntheticEnvironment.swift`: a new `Scene.sidebarIdle`, using `twoSources`. Codex is as in `.dashboard`. Claude's only model last responded before `ModelDetail.sidebarWindow`, counted back from the scene's now.
- Modify: `Tests/Snapshots/Snapshots.swift`:
  - Add `.sidebarIdle` to `dashboardStates`, selecting the Codex model, with `twoSources` (the `sources` choice in `makeDashboard`).
  - Give it the PNG name `sidebar-idle` in `renderDashboards`' name switch.
  - In `expectDashboard`, require the Claude group's state to be `.idle`.
  - Add its light and dark PNGs to the `pngs.count` total, its message, and the dashboard "Validated … PNGs" line, naming the scene.
- Modify: `Tests/Acceptance/AcceptanceServiceTests.swift`: its `Scene` switch gains `.sidebarIdle` among the scenes that aren't panel snapshots.
- Modify: `Tests/ReleaseChecks/check_harnesses.sh`: update the dashboard-scene counter for the new scene's appearances.
- Modify: every item in Global Constraints' Version declarations, to the release (Decisions).
- Test:
  - `Tests/TelltaleCoreTests/`: `CopyTests.swift`, `ReleaseTests.swift`, `PanelSnapshotTests.swift`
  - `Tests/TelltaleAppTests/`: `AppBundleTests.swift` (new), `PanelViewTests.swift`, `DashboardWindowTests.swift`
- Docs:
  - README: Purpose; "Menu bar and panel" (the version and the arrival note); "Dashboard"; "Build and test" (the dashboard PNG count and the scene list).
  - The repository-root `agents.md`, Telltale's Snapshots entry: the PNG count and the scene list.
  - Spec §9.1 (the footer and the arrival note), §9.2 (the sidebar) and §13 (the idle sidebar scene).
  - Visual doc: "Panel" (the mockup's bottom row) and "Dashboard window" (the sidebar foot).
  - `../docs/lessons_learned.md`: the arrival note that claimed learning for idle models.

- [ ] **Step 1: Write the failing tests**

- `CopyTests`: `Copy.versionLine` matches the copy table, and `arrivalIdle` matches the copy table.
- `ReleaseTests`: change the pinned version to the release (Decisions); the commit body says this is the release bump.

In `PanelSnapshotTests`, set up as `arrivalOpensTheFirstRecentModel`:

```swift
@Test func arrivalForAnIdleProviderSaysItIsIdle() throws {
    // A pending arrival whose provider's only model last responded before the sidebar window:
    // the note's text == Copy.arrivalIdle(name: "Codex", days: CollectorRun.lookbackDays), and firstModel == nil.
}
```

`AppBundleTests`:

```swift
@Test func buildHelpNamesTheBuildNumber()  // injected nonempty synthetic build string → "Build {string}"; [:], nil and empty string → nil
```

`PanelViewTests` and `DashboardWindowTests`:

```swift
@Test func panelFooterFitsWithVersion()      // retain fixed-width/content-height assertions with the version row
@Test func dashboardSidebarFitsWithVersion() // retain window size and sidebar layout assertions with the version row
```

Follow the testing boundary documented in `PanelViewTests.rendersNothingToReportWhenQuiet`. `CopyTests` checks the version value; `AppBundleTests` checks help. Retain panel/dashboard layout checks and verify rendered text in the maintained PNGs. Add an owner-run VoiceOver check to Native acceptance for the footer and sidebar. The identifier is a live accessibility aid, not an offscreen test hook.

- [ ] **Step 2: Run them and confirm they fail**

Run the filtered command with pattern `CopyTests|ReleaseTests|PanelSnapshotTests|AppBundleTests|PanelViewTests|DashboardWindowTests`.
- **First:** the build fails on `versionLine`, `arrivalIdle` and `AppBundle`.
- **Then:** the pinned release expectation fails until the source version changes. PNG inspection and Native acceptance validate the visible text and VoiceOver.

- [ ] **Step 3: Implement** as specified under Files.

- [ ] **Step 4: Full verification (every category; report each result)**

From `telltale/`:

```bash
make test
make release
make snapshots
make acceptance
build/release/Telltale.app/Contents/MacOS/Telltale --synthetic-unknown-flag; echo "exit $?"
```

Expected results:
- **`make test`:** passes.
- **`make release`:** builds a signed app whose `CFBundleShortVersionString` and `CFBundleVersion` match the release (Decisions).
- **`make snapshots`:**
  - Every panel PNG shows `Copy.versionLine` at the bottom left, and every dashboard PNG shows it at the foot of the sidebar.
  - `sidebar-idle-light.png` and `sidebar-idle-dark.png` show Claude as `Copy.noRecentModels`.
  - Inspect every PNG.
- **`make acceptance`:** passes its service tests.
- **The last command:** exits 2.
- **Cleanup:** remove the snapshot and acceptance homes with the commands they printed.

Apply repository-root `agents.md`'s **Testing Scope** and **Validation Matrix**, including **Static deployment/fleet audit tooling**, to the actual changed file set. Use that matrix for consumer-suite requirements if implementation scope expands.

- [ ] **Step 5: Commit**

Compare `git status --short` with the status recorded before execution. Account for this task's changes against Files and preserve unrelated pre-existing changes. Stage only the authorized task files.

```bash
git commit -m "Show the version, word the idle arrival note, and prepare the release" -m "<what changed and why; the pinned ReleaseTests expectation is the release bump; the dashboard PNG count rises for the idle sidebar scene>"
```

## After the plan

Merging to `main` and deploying each need separate authorization from Kevin. Deploy only from merged `main`.
- **After deploying:** check that the installed app's panel and sidebar read `Copy.versionLine` and agree with `CFBundleShortVersionString`.
- **Then:** run every README "Native acceptance" check whose "Results" entry says "Not yet run", and record each result separately.
- **Optional:** a per-provider Rebuild (Decisions, "Rows already stored") is Kevin's call.
