# Telltale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Telltale design spec's first release.

**Architecture and stack:** Follow spec §4 and §13. Task 1 declares the package targets.

**Spec:** [`telltale_design_spec.md`](telltale_design_spec.md), approved 2026-10-27. Visual rules: [`telltale_visual_design.md`](telltale_visual_design.md) and [`mockups/telltale_mockups.html`](mockups/telltale_mockups.html). These references apply throughout. Section references (§n) point into the spec. Where this plan and the spec conflict, the spec wins, except for the deviations listed under Global Constraints.

**Read first (every implementer):**
- The repository's `AGENTS.md` (mirrored by `CLAUDE.md`), especially Public Repository, Release Versions, Testing Scope and the Validation Matrix.
- `brew_version/README.md`, section "Settings and native acceptance gates".
- `docs/lessons_learned.md`: every `## 2026-10-17` entry about status items, reused windows, notifications, login items or Settings windows. Find them with `grep -n '^## 2026-10-17' docs/lessons_learned.md`.
- PKM knowledge entry #253 (the macOS 27 status-item technique; spec §9.1). Read it with `pkm_get_entity`.
- `colophon/docs/LESSONS_LEARNED.md`: the entries on zstd streaming, EOF before the snapshot size, and read-only SQLite. Find them with `grep -n -i 'zstd\|read-only sqlite' colophon/docs/LESSONS_LEARNED.md`.

## Global Constraints

- **Toolchain.** Match `anker_charge_monitor/Package.swift` and `anker_charge_monitor/Makefile`: the same swift-tools version, platform, language mode and warnings-as-errors build flags.
- **Dependencies.** Follow §13's dependency policy.
- **Identifiers and version:** use §3's Identifiers table. Swift callers use `TelltaleRelease`; release tests compare the separately maintained plist and deploy-tool contract to it.
- **Paths and retention:** use §4's Storage and retention tables and §9.3's plist path. Put derived runtime URLs in `TelltalePaths`; retention constants belong to Task 9's `Retention`.
- **Codex access.** Follow spec §6 and the read-only SQLite entry in `colophon/docs/LESSONS_LEARNED.md`.
- **Metadata only.** Follow §6.1 "Never read" and §11 for content, network and privacy.
- **Synthetic data.** Follow §11 and the repository's Public Repository rules. Fixture conventions: `com.example.*`, session ids `00000000-0000-4000-8000-0000000000NN`, response ids `resp_synthetic_NN`.
- **Test isolation.** Follow §13's integration isolation contract. Inject executable URLs and the installed-app URL as well as paths and runners. Task 1's scanner is a targeted guard; review runtime calls and harness wiring too.
- **Status item.** Use the §9.1 port contract.
- **Ports.** Use the port-header format in `anker_charge_monitor/Sources/PrimeMonitor/StatusItemController.swift`.

  Take the commit from `git log -1 --format=%h -- <source path>` at the time you port. Port tests from the source's own test file, or from Anker's port of it where Anker added one.
- **Look.** Colors, type and copy follow the visual design doc's Color, Type and Copy rules sections.
- **Validation order.** A task's final validation follows its final test-relevant edit, including harnesses. Apply the repository Testing Scope to documentation-only result recording. Task steps use the named validation commands below; filtered Swift runs are for red/green only.
- **Commits.** Apply `AGENTS.md`'s Git and Public Repository rules to each conditional commit step.
- **Deviations from the spec, approved by Kevin on 2026-10-27:**
  - **Signing.** Release signing uses a stable identity, as `anker_charge_monitor` does (its README, section "Signing and installation"), not spec §13's "ad-hoc signed".
  - **Deploy tool.** It's modeled on `tools/deploy_anker_charge_monitor.mjs` (app-only), not spec §13's `deploy_brew_version.mjs`.

## Review Focus

| Risk | Acceptance tests to inspect |
|---|---|
| Mid-append rollout | Task 4 `partialTrailingLineIsDeferredNotFailed` |
| Malformed status fetch | Task 6 `malformedFetchKeepsStoredIncidentsOpen`; Task 8 `unavailableStatusSourceDoesNotClearIncidentEpisode` |
| Long catch-up gap | Task 9 `twentyDayGapCatchUpIsBoundedAndQuiet` |
| Calendar transitions | Task 7 `activeDaysAcrossFallBackCountOnce`; Task 8 `evaluationPointsAcrossDSTAreContiguous` |
| Non-installed collector launch | Task 10's bundle-refusal tests; Task 11 `launchDoesNotAutoEnableOutsideApplications` |

---

## File locations

Each task's Files list gives its paths; paths are relative to the repository root. Keep `AGENTS.md` and `CLAUDE.md` mirrored when updating their Validation Matrix.

## Validation commands

The bold names below are command references used by task steps and by the README/Validation Matrix entries they request. Run from the repository root.

| Name | Command |
|---|---|
| **Full suite** | `make -C telltale test` |
| **Release** | `make -C telltale release` |
| **Snapshots** | `make -C telltale snapshots` |
| **Acceptance build** | `make -C telltale acceptance` |

---

### Task 1: Package scaffold and the notification-identity spike (gate)

Spec §4 requires this spike before anything is built on the one-executable design. **If any spike check fails, stop and report to Kevin.** The §4 fallback then becomes a plan amendment he approves. Don't build it speculatively.

**Files:**
- Create: `telltale/{Package.swift, Makefile, README.md, Resources/Info.plist}`.
- Create: `telltale/Sources/TelltaleCore/{Release.swift, Paths.swift, Rules/Copy.swift}` (the Copy rows needed by this task; later tasks extend the same type).
- Create: `telltale/Sources/Telltale/{TelltaleMain.swift, UserNotifier.swift, NotificationCheck.swift}`.
- Create: `telltale/tools/{resolve_signing_identity.sh, install.sh, notification_check.sh}`.
- Create: `telltale/Tests/TelltaleTestSupport/TestPaths.swift`, `telltale/Tests/TelltaleCoreTests/ReleaseTests.swift`, `telltale/Tests/TelltaleAppTests/NotificationCheckTests.swift`.
- Create: `telltale/Tests/ReleaseChecks/{check_bundle.sh, check_test_isolation.sh, test_check_test_isolation.sh, test_notification_check.sh}`.
- Create: scaffold Swift/C files for the targets declared in Step 3 and synthetic fixture-directory READMEs for resource targets.
- Modify: `AGENTS.md` and `CLAUDE.md` (a Validation Matrix entry for `telltale`), and root `README.md` (a Projects At A Glance line).

**Interfaces:**
- Produces:
  - `public enum TelltaleRelease`: static `version`, `displayName`, `bundleIdentifier` and `collectorLabel`, initialized from the §3 Identifiers table.
  - `public struct TelltalePaths: Sendable, Equatable` with `appSupport`, `database`, `lock`, `appLock`, `logDirectory`, `log`, `launchAgents`, `codexHome` (all `URL`), plus:
    - `public init(home: URL, codexHome: URL? = nil)`, which derives every path from `home`;
    - `public static func live(environment: [String: String] = ProcessInfo.processInfo.environment) -> TelltalePaths`. It uses the real home directory, and `CODEX_HOME` when it's set **(plan call, matching Codex's own variable)**.
    - `appLock` is `appSupport/app.lock`, for Task 11's instance gate **(plan call)**.
  - `@MainActor protocol NotificationService` and `NativeNotificationService`, ported from `brew_version/Sources/BrewVersion/UserNotifier.swift`. Task 11 ports the `UserNotifier` class. Add `func delivered() async -> [UNNotification]` to the service protocol and native adapter.
  - `@MainActor NotificationCheck.run(service: any NotificationService, resultURL: URL, mode: String, timing: CheckTiming = .live) async -> Int32`:
    - it posts a notification using `Copy.notificationCheckTitle` and `Copy.notificationCheckBody(mode:)`;
    - it writes JSON `{authorization, posted, delivered, bundle, error}`;
    - it returns 0 only when the request posted in this invocation is found among `delivered()`, matched by a fresh request identifier. Poll delivery with an injected clock/deadline so asynchronous delivery can settle within the runner's timeout.
    - `CheckTiming` supplies elapsed monotonic time, an async pause and a delivery timeout; `.live` starts a fresh clock per invocation and leaves time inside the script's timeout for result writing. Tests inject controlled elapsed time and pauses.
  - `TestPaths` (test support): `packageRoot: URL`, derived from `#filePath`, and `plistDictionary(at:) throws -> [String: Any]`.
- `TelltaleMain` dispatches on `CommandLine.arguments`:
  - `--notification-check --result <path> --mode <name>` runs `NotificationCheck`;
  - `--collect` exits 0 with `Copy.collectorNotBuilt` until Task 9;
  - no arguments runs a placeholder app (`.accessory`). It requests notification authorization, then shows a small window that reports the result, with a Quit button. It keeps running until quit. Task 11 replaces it.

- [ ] **Step 1: Write the failing tests**

Create the manifest and compilable target scaffolds described under Step 3's `Package.swift` entry before the red run; leave the tested production interfaces unimplemented. This makes the red result an undefined-interface failure rather than a missing-manifest or empty-target error.

`ReleaseTests`:
- `infoPlistMatchesRelease`: compare `Resources/Info.plist` to `TelltaleRelease` and the §3 bundle contract through `TestPaths`; compare the minimum OS to Anker's plist.
- `pathsDeriveFromInjectedHome`: assert the spec's runtime paths are rooted under an injected synthetic home; keep the concrete paths in the test.
- `codexHomeHonorsEnvironment`: assert a synthetic `CODEX_HOME` override is honored; keep the concrete path in the test.

`NotificationCheckTests` (fake service):
- `checkSucceedsWhenDelivered`.
- `checkFailsWhenAuthorizationDenied`, with `error` naming Telltale's notification setting.
- `checkFailsWhenNotDelivered`.
- `olderDeliveredCheckDoesNotSatisfyCurrentRequest`.
- `deliveryCanArriveAfterPostReturns`.

`test_notification_check.sh` uses a temporary fake app and a fake `launchctl` in its private `PATH`. It runs the documented relative-app invocation, reads the plist captured by the fake, and asserts that `ProgramArguments[0]` is the absolute executable path. The fake writes a synthetic result so cleanup also runs. It never invokes the system launchctl.

`check_test_isolation.sh [root]` scans Swift files with `rg --glob '*.swift'`; the default root is this package's `Tests/`, resolved relative to the script. A root argument lets `test_check_test_isolation.sh` exercise temporary fixture trees. The checker exits 1 and prints `file:line` for these patterns (exit 1 from `rg` means no matches; exit 2 is a checker failure):
- `TelltalePaths\.live\(\)`: a call with no injected environment.
- `homeDirectoryForCurrentUser`.
- `NSHomeDirectory\(`.
- `~/\.codex`, `~/Library`, or `"/Users/`.

Keep `/bin/launchctl` literals in fake-runner expectations; never execute them in tests. This is a review check, not a grep exception. Test the scanner against temporary synthetic Swift files that contain each forbidden pattern and against permitted injected-path examples; the shell checker and its fixtures aren't scan inputs.

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'ReleaseTests|NotificationCheckTests'`
Expected: compile failure (`TelltaleRelease`, `TelltalePaths` and `NotificationCheck` are undefined).

- [ ] **Step 3: Implement the package and scaffold**

- **`Package.swift`.** Declare every target now; later tasks add files and adjust settings within these targets:
  - library products `TelltaleCore`, `TelltaleCodex`, `TelltaleOpenAIStatus`, and executable `Telltale`;
  - target `CZstd`, holding one placeholder `.c` file until Task 2;
  - `TelltaleCodex` depends on `TelltaleCore` and `CZstd`;
  - `TelltaleOpenAIStatus` depends on `TelltaleCore`;
  - `Telltale` depends on `TelltaleCore`, `TelltaleCodex` and `TelltaleOpenAIStatus`;
  - a non-product target `TelltaleTestSupport` at `Tests/TelltaleTestSupport`, depending on `TelltaleCore` and `CZstd`;
  - test targets `TelltaleCoreTests`, `TelltaleCodexTests` (with `Fixtures`), `TelltaleOpenAIStatusTests` (with `Fixtures`), `TelltaleAppTests` (depends on `Telltale`) and `TelltaleIntegrationTests` (all libraries). Each also depends on `TelltaleTestSupport`.
  - Give each target a compilable source file in this task; use an empty Swift declaration for future implementation targets and a comment-only Swift file for future test targets. Create fixture directories with synthetic README files before declaring their resources. Replace placeholders when their task adds real sources.
- **`Makefile`.** Port `anker_charge_monitor/Makefile`. Telltale differences:
  - `test` retains the source's Swift test flags, then runs every script in `Tests/ReleaseChecks/`;
  - `release` builds `build/release/Telltale.app`;
  - omit Anker's `Resources/device_catalog.json` copy from the release recipe and its `live-check` target/phony entry; Telltale's notification spike uses the script below;
  - `install deploy` calls `node ../tools/deploy_telltale.mjs` (Task 14).
- **Scripts.** Port `tools/resolve_signing_identity.sh`, `tools/install.sh` and `Tests/ReleaseChecks/check_bundle.sh` from `anker_charge_monitor`. Telltale differences:
  - rename product, executable, bundle, runtime and test-only environment identifiers;
  - Telltale has no legacy app name: omit the legacy-name migration branch and the call to Anker's `check_rename.sh`, retaining current-name installation, upgrade and recovery coverage;
  - omit Anker's device-catalog resource checks; that resource has no Telltale counterpart;
  - move the source's maintained-snapshot runtime block into Task 11's `check_harnesses.sh` when the harness exists. Task 1's `check_bundle.sh` does not invoke an undefined future target. Preserve the signing, release-assembly and installer checks that operate on the Task 1 bundle.
- **`notification_check.sh <app> <mode>`.**
  - Resolve `<app>` against the caller's working directory to an absolute bundle path and validate its executable before writing the plist. Encode arguments as plist strings, preserving spaces.
  - It writes a one-shot plist, labeled `local.utilities.telltale.notification-check`, into a fresh `mktemp -d` directory. The plist runs the resolved absolute executable with `--notification-check --result <tmp>/result.json --mode <mode>` and `RunAtLoad`.
  - It bootstraps the plist into `gui/$UID`, waits up to 20 s for the result, prints it, boots it out, and removes the temporary directory.
  - It never touches `~/Library/LaunchAgents`.
- **Docs.** README sections: Purpose, Requirements, Build and test, Signing (pointing at Anker's README section), and Spike results. The Validation Matrix entry `telltale` lists **Full suite** and **Release**. Later tasks add lines.

- [ ] **Step 4: Run the full suite**

Run: **Full suite**.
Expected: every Swift test passes, and each release-check script exits 0.

- [ ] **Step 5: Build the signed bundle**

Run: **Release**.
Expected: the source resolver's signing and verification gates pass. Report a resolver failure; the approved signing deviation governs identity choice.

- [ ] **Step 6: Run the spike (needs Kevin's go-ahead: it posts real notifications and loads a temporary launchd job)**

1. Open `telltale/build/release/Telltale.app`, grant notification permission, then Quit.
2. Run `telltale/tools/notification_check.sh telltale/build/release/Telltale.app ui-not-running`.
   Expected: `posted` and `delivered` are true, `bundle` is `TelltaleRelease.bundleIdentifier`, and Kevin sees a banner from **Telltale**.
3. Open the app again and leave its window open. Run the script with `ui-running`. Same expectation. Then Quit.

Record each result (date, macOS build, JSON, Kevin's visual confirmation) in the README's "Spike results". On any failure, stop and report.

- [ ] **Step 7: Commit** `Scaffold Telltale and verify launchd notification identity`

---

### Task 2: Vendored zstd and the streaming reader

**Files:**
- Create: `telltale/Sources/CZstd/**`. Copy `colophon/vendor/zstd/` byte for byte, and add `include/czstd.h`, a shim that includes `../zstd.h` and `../zstd_errors.h`.
- Modify: `telltale/Package.swift` (`CZstd` `cSettings`), `telltale/Makefile`, `telltale/README.md` (third-party notice).
- Create: `telltale/Sources/TelltaleCodex/ZstdReader.swift`, `telltale/Tests/TelltaleTestSupport/StoredZstdFrame.swift`, `telltale/Tests/TelltaleCodexTests/ZstdReaderTests.swift`.
- Create: `telltale/Tests/TelltaleCodexTests/Fixtures/compressed/{synthetic_rollout.jsonl, synthetic_rollout.jsonl.zst, README.md}`, `telltale/Tests/ReleaseChecks/check_vendor.sh`.

**Interfaces:**
- Consumes: the `CZstd` target (Task 1).
- Produces:
  - `ZstdReader.lines(of file: URL, expectedSize: Int, startingAfterLine: Int = 0, _ body: (_ lineNumber: Int, _ line: Data) throws -> Void) throws`.
    - `expectedSize` is the size discovery recorded. The reader reads exactly that many bytes, and throws `.truncated` when the file holds fewer.
    - It throws `ZstdError.truncated`, `.corrupt(String)` or `.io(String)`.
  - `ZstdReader.outputBufferSize` (a static constant, for the regression test).
  - `StoredZstdFrame.encode(_ data: Data, blockSize: Int) -> Data` (test support). It builds valid frames from raw blocks, so tests control exact sizes without a compressor.
- `cSettings`: the defines named on the `compiled:` line of `Sources/CZstd/VERSION`.

- [ ] **Step 1: Write the failing tests**

`ZstdReaderTests`:
- `readsRealCompressedFixture`: lines equal the plain fixture's lines.
- `readsMultiFrameFile`.
- `exactOutputBufferSizedExpansionIsNotTruncated`: the Colophon end-of-frame regression.
- `truncatedFrameThrowsTruncated`.
- `shrinkAfterDiscoveryThrowsTruncated`: record the size, cut the file at a frame boundary, then read with the recorded size.
- `corruptMagicThrowsCorrupt`.
- `startingAfterLineSkipsLines`: line numbers keep their original values.
- `finalLineWithoutNewlineIsYielded`: compressed files are complete.

`check_vendor.sh` recomputes the sha256 of every file listed in `Sources/CZstd/VERSION`, mapping `lib/` paths to the target layout. It fails on a mismatch, and on any `.c` or `.h` file that isn't listed (the shim excepted).

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter ZstdReaderTests`
Expected: compile failure.

- [ ] **Step 3: Vendor and implement**

- Create the compressed fixture with `zstd -19`. Record the command and each fixture file's digest in the fixture README.
- Implement streaming decode as the Colophon zstd lessons require.

- [ ] **Step 4: Run the tests and the full suite**

Run: the Step 2 command, then **Full suite**.
Expected: all pass, including `check_vendor.sh`.

- [ ] **Step 5: Commit** `Vendor zstd decompression for Telltale's rollout reader`

---

### Task 3: Records, plugin protocols, settings and the store

**Files:**
- Create: `telltale/Sources/TelltaleCore/{Records.swift, Plugins.swift, Settings.swift}`, `telltale/Sources/TelltaleCore/Store/{Store, Schema, Store+Ingest, Store+Runs}.swift`.
- Test: `telltale/Tests/TelltaleCoreTests/{StoreTests, SettingsTests, IngestStoreTests}.swift`.

**Interfaces:**
- **Records** (all `Sendable, Equatable, Codable`):
  - `ProviderID`: a `RawRepresentable` String, with `static let codex`.
  - `ResponseRecord { provider, model: String, effort: String?, serviceTier: String?, sessionID: String, isSubagent: Bool, turnID: String?, responseID: String, start: Date, end: Date, inputTokens: Int, cachedInputTokens: Int, outputTokens: Int, reasoningTokens: Int? }`:
    - `duration` and optional `throughput` follow §6.1's definitions.
  - `FailedTurnRecord { provider, threadID, turnID, startedAt: Date, completedAt: Date?, model: String?, errorCode: String, message: String }`.
  - `ConnectionKind { disconnect, retry, reconnect }`; `ConnectionEventRecord { provider, sourceID: String, at: Date, kind, detail: String, retries: Int?, maxRetries: Int? }`.
  - `UsageLimitSnapshot { provider, at: Date, usedPercent: Double, windowMinutes: Int, resetsAt: Date? }`.
  - `SetupState { ready, notSetUp(String), formatProblem(String) }`.
  - `Signal { speed, errors, link, provider, load, collector }`. The UI labels `provider` with the status source's name.
  - `StatusComponent { id, name }`; `ComponentImpact { componentID, status: String, start: Date, end: Date? }`; `StatusChange { at: Date, status: String }`.
  - `IncidentRecord { source, id, name, status: String, publishedAt: Date, updatedAt: Date, link: URL, history: [StatusChange], impacts: [ComponentImpact] }`, with `isResolved`, which is true for status `resolved` or `postmortem`.
  - `RSSItem { title: String, link: URL, publishedAt: Date }`.
- **Plugins.swift:**
  ```swift
  public protocol ModelNaming: Sendable {
      func displayName(model: String) -> String
      func incidentTitle(_ title: String, names model: String) -> Bool
  }
  public struct IngestBatch: Sendable { public var responses: [ResponseRecord] = []; public var failedTurns: [FailedTurnRecord] = []
      public var connectionEvents: [ConnectionEventRecord] = []; public var connectionGaps: [DateInterval] = []
      public var usageLimit: UsageLimitSnapshot?; public var sourceVersion: String? }
  public struct IngestResult: Sendable { public var batch: IngestBatch; public var cursor: Data; public var state: SetupState }
  public protocol UsageSource: ModelNaming {
      var provider: ProviderID { get }; var displayName: String { get }; var statusSourceID: String { get }
      var signals: Set<Signal> { get }
      func ingest(cursor: Data?, backfillFrom: Date, now: Date) -> IngestResult   // problems go in `state`
  }
  public enum StatusFetch: Sendable {
      case full(components: [StatusComponent], incidents: [IncidentRecord])
      case rssOnly([RSSItem])                       // summary failed; RSS answered (Task 6)
  }
  public protocol StatusSource: Sendable {
      var id: String { get }; var displayName: String { get }
      func fetch(known: [IncidentRecord]) async throws -> StatusFetch
  }
  ```
- **Settings.swift:**
  - `SettingKey<Value: Codable & Sendable>` with `name` and `defaultValue`.
  - `Settings.intervalError(_ minutes: Int) -> String?` validates the §9.3 interval range and returns `Copy.intervalError(min:max:)` with those bounds on failure. `LaunchAgentManager` and Settings use this validator.
  - Keys:

    | Key | Type | Default |
    |---|---|---|
    | `collectorEnabled` | Bool | true **(plan call: Goal 1; Task 11 limits auto turn-on to the installed app)** |
    | `intervalMinutes` | Int | 5 (§9.3) |
    | `rules` | `RuleSettings` | `.defaults` |
    | `watchedComponents` | [String] | the §7.4 watched-components defaults |
    | `appearance` | `Appearance { dark, light, system }` | `.dark` (§9.4) |
    | `openAtLogin` | Bool | true (§3) |
    | `rebuildRequestedAt` | Date? | nil |
    | `backfillThrough` | Date? | nil (Task 9) |
    | `lastPrunedDay` | String? | nil (Task 9) |

    Task 10 adds `collectorHealthNotice`, because its value type lives there.
  - `RuleSettings` has one struct per §7.4 rule:
    - `SpeedRule { enabled, threshold, durationMinutes, clearBand, clearMinutes, notify, notifyOnClear }` for `slower` and `faster`;
    - `LargePromptRule { enabled, inputTokens, count, of, clearAtMost, notify, notifyOnClear }`;
    - `FailedTurnRule { enabled, quietMinutes, coalesceMinutes, notify, notifyOnClear }`;
    - `DisconnectRule { enabled, count, windowMinutes, notify, notifyOnClear }`;
    - `BasicRule { enabled, notify, notifyOnClear }` for `incident` and `collectorHealth`;
    - `UsageLimitRule { enabled, percent, notify, notifyOnClear }`.

    `RuleSettings.defaults` takes every value §7.4 states. Speed thresholds and clear bands are stored as fractions of usual. **Plan calls** for values §7.4 doesn't state:
    - failed turns and disconnects have `notifyOnClear` false (large prompts use §7.4's stated clear-notice default);
    - large prompts fire and clear at the first point where the condition holds, since §7.4 gives a count and no duration;
    - `collectorHealth.notifyOnClear` is true.
    - `usageLimit.notifyOnClear` is false.
  - `RuleSettings.validationErrors() -> [String]` returns `Copy.clearBandError` when a speed rule's `clearBand >= threshold` (§7.2).
    - Require finite speed fractions with `0 < clearBand < threshold < 1`; positive whole-minute durations, quiet/coalescing windows and disconnect windows; positive input-token and count parameters; `count <= of`, `0 <= clearAtMost < count`; and a finite usage-limit percentage in `(0, 100]` **(plan call on editable ranges)**. Reject invalid values before saving or evaluating; use the Copy validation row with the field's display name.
- **Store:**
  ```swift
  public final class Store {   // one per thread; not Sendable
      public enum Mode: Sendable { case readOnly, readWrite }
      public static func open(_ url: URL, mode: Mode, busyTimeout: Duration = .seconds(5)) throws -> Store
      public func transaction<T>(_ body: () throws -> T) throws -> T          // BEGIN IMMEDIATE … COMMIT
      public func value<V>(_ key: SettingKey<V>) throws -> V                  // default when absent or undecodable
      public func set<V>(_ key: SettingKey<V>, _ value: V) throws
  }
  ```
  - `readWrite` creates the directory, enables WAL and foreign keys, and migrates to `user_version` 1 inside `BEGIN IMMEDIATE`, so concurrent first opens are safe.
  - `readOnly` never migrates. It throws `StoreError.notInitialized` when `user_version` is 0.
- **`Store+Ingest`:**
  - `upsert(responses:) -> Int` implements §6.1's duplicate-response rule.
  - `upsert(failedTurns:)`: a later update wins, and `evaluated_at` is kept (Task 8).
  - `upsert(connectionEvents:)`.
  - `setUsageLimit(_:)`, `usageLimit(provider:)`.
  - `cursor(_:)`, `setCursor(_:_:)`.
  - `sourceState(_:)`, `setSourceState(_:)`, using `SourceStateRow { source, state: SetupState, version: String?, unavailableSince: Date?, updatedAt: Date }`.
  - `responses(provider:model:endingIn: ClosedRange<Date>)`, ordered by end.
- **`Store+Runs`:**
  - `beginRun(at:) -> Int64`;
  - `finishRun(_:at:outcome:detail:)`;
  - `recentRuns(limit:) -> [CollectorRunRecord]`, newest first. `CollectorRunRecord` is `{ id, startedAt, finishedAt: Date?, outcome: RunOutcome, detail }`, and `RunOutcome` is `running`, `succeeded`, `failed` or `skipped`.

**Schema v1** (`Schema.swift`; times are REAL Unix seconds; extra indexes are the builder's call; §4 lists what must be held):

| Table | Columns (PK first) |
|---|---|
| `responses` | provider, response_id; model, effort, service_tier, session_id, is_subagent, turn_id, start_at, end_at, input_tokens, cached_input_tokens, output_tokens, reasoning_tokens. Indexes (provider, model, end_at) and (turn_id) |
| `failed_turns` | provider, turn_id; thread_id, started_at, completed_at, model, error_code, message, evaluated_at |
| `connection_events` | provider, source_id; at, kind, detail, retries, max_retries |
| `status_components` | source, component_id; name |
| `incidents` | source, incident_id; name, status, published_at, updated_at, link, history_json, impacts_json |
| `usage_limits` | provider; at, used_percent, window_minutes, resets_at |
| `eval_points` | provider, model, at; speed_index, mix_usual_tps, median_tps, samples, state |
| `rule_state` | rule, provider, scope; json |
| `episodes` | id; rule, provider, scope, direction, onset_at, fired_at, ended_at, end_reason, severity, worst_value, detail_json |
| `events` | id; at, kind, provider, scope, title, body, episode_id, epoch_id, link, undone_at |
| `baseline_epochs` | id; provider, model, since_day, created_at, undone_at, before_json, after_json |
| `shift_dismissals` | provider, model, direction, first_day; dismissed_at |
| `collector_runs` | id; started_at, finished_at, outcome, detail |
| `cursors` | source; data |
| `source_state` | source; state_json, version, unavailable_since, updated_at |
| `settings` | key; value_json |

- [ ] **Step 1: Write the failing tests**

`StoreTests`:
- `readWriteOpenCreatesWALDatabaseAtVersion1`: every table in Schema v1 exists.
- `readOnlyOpenOfMissingDatabaseThrowsNotInitialized`.
- `readOnlyConnectionCannotWrite`.
- `concurrentFirstOpensMigrateOnce`.
- `writerDuringOpenTransactionWaitsWithinBusyTimeout`: hold a transaction on one connection, release it before the configured timeout, and assert the second connection's write succeeds. Keep timing values in the test.

`SettingsTests`:
- `absentKeyReturnsDefault`: `RuleSettings.defaults` matches every §7.4 value.
- `roundTripsEveryKey`.
- `undecodableValueFallsBackToDefault`.
- `clearBandMustBeStricterThanTrigger`.
- `invalidRuleParametersAreRejected`: exercise zero, negative, non-finite and inconsistent values for the parameter domains above; valid non-grid durations remain accepted.
- `intervalErrorOutsideOneToSixty`: exercise the §9.3 range boundaries and values outside them.

`IngestStoreTests`:
- `duplicateResponseKeepsLongerDuration`: exercise order independence.
- `failedTurnUpdateReplacesButKeepsEvaluatedAt`.
- `cursorRoundTrip`.
- `responsesQueryFiltersByModelAndRange`.
- `runRecordsListNewestFirst`.

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'StoreTests|SettingsTests|IngestStoreTests'`
Expected: compile failure.

- [ ] **Step 3: Implement** with the `SQLite3` C API and prepared statements.

- [ ] **Step 4: Run the tests and the full suite**

Run: the Step 2 command, then **Full suite**.
Expected: all pass.

- [ ] **Step 5: Commit** `Add Telltale's records, plugin protocols, settings and store`

---

### Task 4: Codex rollout ingestion

**Files:**
- Create: `telltale/Sources/TelltaleCodex/{RolloutDiscovery, RolloutParser, RolloutCursor, ModelNames}.swift`, `telltale/Tests/TelltaleTestSupport/RolloutBuilder.swift`.
- Test: `telltale/Tests/TelltaleCodexTests/{RolloutParserTests, RolloutDiscoveryTests, ModelNamesTests}.swift`.

**Interfaces:**
- Consumes: `ZstdReader` (Task 2); the Task 3 records.
- Produces:
  - `RolloutDiscovery.files(codexHome: URL) -> [RolloutFile]`, where `RolloutFile` is `{ url, sessionID, compressed: Bool, size: Int, modified: Date }`.
    - Discovery follows §6.1's Files entry.
    - Prefer a plain file over its compressed sibling **(plan call)**: compression may still be in progress.
  - `struct SessionCursor: Codable, Equatable { lastOrdinal: Int?; byteOffset: Int?; compressedSize: Int?; compressedModified: Date?; pendingStart: Date?; lastUsageEnd: Date?; model: String?; effort: String?; serviceTier: String?; isSubagent: Bool; historyStartOrdinal: Int?; sawTurn: Bool; sawUsage: Bool }`:
    - `lastOrdinal` nil means nothing has been processed yet;
    - `byteOffset` applies to plain files;
    - `compressedSize` and `compressedModified` apply to `.zst` files.
  - `RolloutParser.parse(file: RolloutFile, cursor: SessionCursor?) throws -> RolloutParse`, where `RolloutParse` is `{ responses, usageLimit: UsageLimitSnapshot?, cliVersion: String?, cursor: SessionCursor, problem: String? }`.
  - `RolloutParser.needsRead(_ file: RolloutFile, cursor: SessionCursor?) -> Bool`. It's false for a `.zst` whose size and modification date equal the cursor's.
  - `ModelNames: ModelNaming`, implementing §6.1's Model names contract.

**Parsing.** §6.1 is normative: its Records used table, Response start rule, Throughput and Never read. Additions:
- **Ordinals.** Ordinals start at 0. Process ordinals greater than `lastOrdinal`, or all of them when it's nil. Skip ordinals below `historyStartOrdinal`.
- **Service tier.** Use the §6.1 Records used entry and §8's missing-tier convention.
- **Model required.** A `token_usage_record` with no model yet emits nothing.
- **Plain files.** Read from `byteOffset`, and process only lines ending in `\n`. Set `byteOffset` just after the last complete line.
- **Handoff.** Follow §6.1's plain-to-compressed cursor rule.
- **Format problems** (§6.5), **(plan call on the thresholds)**:
  - at least 50 lines with `sawTurn` and no `token_usage_record`;
  - a `token_usage_record` missing `response_id` or `usage.output_tokens`.

- [ ] **Step 1: Write the failing tests** (synthetic sessions from `RolloutBuilder`; ordinals start at 0)

`RolloutParserTests`:
- `responseStartIsLatestInputEventSincePreviousUsage`.
- `firstUsageWithoutInputOrPreviousUsageEmitsNothing`.
- `startFallsBackToPreviousUsageEnd`.
- `subThresholdDurationsAreDropped`: exercise the §6.1 duration cutoff.
- `throughputOnlyFromThreeHundredOutputTokens`: exercise the §6.1 output-token cutoff.
- `modelAndEffortFollowLatestTurnContext`.
- `serviceTierFollowsThreadSettingsApplied`: a tier change mid-file applies to later responses only, and a file with no such event gives nil.
- `ordinalZeroSessionMetaIsRead`: a fresh cursor processes ordinal 0, so `isSubagent` and `cliVersion` are set.
- `subagentFromParentThreadOrForkedFrom`.
- `historyStartOrdinalSkipsCopiedPrefix`.
- `cursorResumesMidResponse`.
- `partialTrailingLineIsDeferredNotFailed` (Review Focus: Mid-append rollout).
- `plainToCompressedHandoffResumesByOrdinal`: resume a partially processed plain file from its compressed replacement, retaining the processed-prefix boundary and avoiding duplicate responses. Keep ordinal values in the test.
- `unchangedCompressedFileIsNotReread`.
- `usageLimitSnapshotFromTokenCount`.
- `missingTokenUsageRecordsIsFormatProblem`.
- `malformedUsageRecordIsFormatProblem`.
- `noContentFieldsAreRetained`: keep a synthetic content marker in the test fixture and assert it is absent from the returned metadata.

`RolloutDiscoveryTests`:
- `findsBothSuffixesInSessionsAndArchive`.
- `prefersPlainWhenBothExist`.
- `sessionIDFromFilenameUUID`.

`ModelNamesTests`:
- `displayName`: covers each §6.1 example.
- `titleMatchNeedsFamilyAndVersion`: assert §6.1's Model names contract.

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'Rollout|ModelNames'`
Expected: compile failure.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests and the full suite**

Run: the Step 2 command, then **Full suite**.
Expected: all pass.

- [ ] **Step 5: Commit** `Parse Codex rollouts into Telltale response records`

---

### Task 5: Codex failed turns, disconnects and the composed source

**Files:**
- Create: `telltale/Sources/TelltaleCodex/{ReadOnlySQLite, ThreadHistorySource, RetryLogSource, CodexUsageSource}.swift`, `telltale/Tests/TelltaleTestSupport/CodexDatabases.swift`.
- Test: `telltale/Tests/TelltaleCodexTests/{ReadOnlySQLiteTests, ThreadHistorySourceTests, RetryLogSourceTests, CodexUsageSourceTests}.swift`.

**Interfaces:**
- Consumes: the Task 3 records and protocols; the Task 4 parser, discovery and `ModelNames`.
- Produces:
  - `ReadOnlySQLite.open(_ url: URL, busyTimeout: Duration = .milliseconds(250), step: SQLiteStep = .live) throws -> ReadOnlySQLite`, following §6's SQLite access contract:
    - `SQLiteStep` is an injectable wrapper around `sqlite3_step`, for fault tests;
    - `SQLITE_BUSY` and `SQLITE_LOCKED` throw `ReadOnlySQLite.Busy`.
  - `ThreadHistorySource.read(codexHome:, since: Date) throws -> [FailedTurnRecord]`. It follows §6.2, and leaves `model` nil; Task 8 attributes the model.
  - `RetryLogSource.read(codexHome:, afterID: Int64) throws -> (events: [ConnectionEventRecord], maxID: Int64, oldestRetained: Date?)`. It follows §6.3. Classification **(plan call)**:
    - the §6.3 websocket-limit message is `.reconnect`;
    - text containing "stream disconnected" or "Connection reset" is `.disconnect`;
    - anything else is `.retry`.
  - `public struct CodexUsageSource: UsageSource`:
    - `init(codexHome: URL)`;
    - `provider` is `.codex`, and `displayName` is "Codex";
    - naming through `ModelNames`;
    - `statusSourceID` is "openai";
    - signals: speed, errors, link, provider, load.
    - Its `ingest`:
      - runs each reader independently;
      - its cursor is JSON `{ sessions: [sessionID: SessionCursor], threadHistorySince, logsAfterID, logsLastSeen }`;
      - parses only files where `needsRead` is true, and drops session entries whose files no longer exist;
      - on a nil cursor, takes rollouts modified at or after `backfillFrom`, and failed turns since `backfillFrom`;
      - puts the newest usage-limit snapshot and `cliVersion` in the batch.
    - A `Busy` skips that reader and keeps its cursor.
    - **Gap.** When `oldestRetained` is later than `logsLastSeen`, add that interval to `connectionGaps` (§6.3).
    - **State.** The first reader problem becomes `formatProblem`, naming the part. A missing `codexHome` is `notSetUp`.

- [ ] **Step 1: Write the failing tests** (`CodexDatabases` creates WAL-mode databases with Codex's column names, like the real files)

`ReadOnlySQLiteTests`:
- `busyStepThrowsBusy`: an injected `step` returns `SQLITE_BUSY`.
- `readSucceedsWhileWriterHoldsTransaction`: in WAL mode, another connection holding `BEGIN IMMEDIATE` doesn't block or fail the read.

`ThreadHistorySourceTests`:
- `failedRowsBecomeFailedTurns`.
- `nonFailedRowsIgnored`.
- `rescansLastTwoHours` (§6.2).
- `highestNumberedDatabaseWins`.
- `missingColumnIsFormatProblem`.

`RetryLogSourceTests`:
- `parsesRetriesAndError`.
- `classifiesWebsocketLimitAsReconnect`.
- `classifiesResetAsDisconnect`.
- `onlyWarnRetryRowsRead`.
- `incrementalByID`.
- `reportsOldestRetainedRow`.

`CodexUsageSourceTests`:
- `composesAllReaders`.
- `rolloutFailureStillReturnsFailedTurns`.
- `busyReaderKeepsItsCursor`.
- `gapRecordedWhenLogRetentionPassedCursor`.
- `missingCodexHomeIsNotSetUp`.
- `unchangedCompressedFilesAreSkipped`.
- `vanishedSessionCursorIsDropped`.
- `codexFilesAreNotModified`: compare the tree before and after an ingest, excluding SQLite `-wal` and `-shm` side files (see Global Constraints).

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'ReadOnlySQLite|ThreadHistory|RetryLog|CodexUsageSource'`
Expected: compile failure.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests and the full suite**

Run: the Step 2 command, then **Full suite**.
Expected: all pass.

- [ ] **Step 5: Commit** `Read Codex failed turns and disconnects for Telltale`

---

### Task 6: OpenAI status source

**Files:**
- Create: `telltale/Sources/TelltaleOpenAIStatus/{StatusClient, StatusDecoding, RSSFallback, OpenAIStatusSource}.swift`, `telltale/Sources/TelltaleCore/Store/Store+Status.swift`.
- Test: `telltale/Tests/TelltaleOpenAIStatusTests/{StatusDecodingTests, OpenAIStatusSourceTests}.swift`, `telltale/Tests/TelltaleCoreTests/StatusStoreTests.swift`.
- Fixtures: hand-written to the §10 field shapes, with synthetic ids and names. Don't copy live responses: `summary_incident.json`, `summary_quiet.json`, `incident_detail.json`, `feed.rss`, `error_page.html`.

**Interfaces:**
- Consumes: the Task 3 status records and protocols.
- Produces:
  - `protocol HTTPTransport: Sendable { func get(_ url: URL) async throws -> (Data, HTTPURLResponse) }` and `URLSessionTransport`. Timeout 15 s; the user agent names Telltale and `TelltaleRelease.version`.
  - `public struct OpenAIStatusSource: StatusSource`, with `init(transport:, base: URL)`, `id` "openai" and `displayName` "OpenAI". Its `fetch(known:)` follows §10. Additions:
    - also fetch a stored-open incident missing from `ongoing_incidents` to check for resolution;
    - when the summary itself fails, it fetches `feed.rss`. It returns `.rssOnly` if that decodes, and throws otherwise.
  - `StatusDecoding.summary(_:)`, `.incident(_:)` and `.rss(_:)`. Non-JSON or missing fields throw `StatusError.unexpectedPayload`.
  - Store:
    - `replace(components:source:)`, `upsert(incidents:)`;
    - `openIncidents(source:)`, `incidents(source:overlapping:)`, `components(source:)`;
    - `recordRSSItems(_:source:) -> [RSSItem]`. It stores new items as `statusPost` events, deduplicated by link, and returns the new ones.
  - `OpenAIStatusSource.apply(_ result: Result<StatusFetch, any Error>, sourceID: String, store: Store, now: Date) throws -> Bool`, which returns whether incident data is available:
    - `.full`: stores the data, clears `unavailableSince`, and returns true;
    - `.rssOnly`: records the RSS items, sets `unavailableSince` if it isn't set, and returns false;
    - a failure: sets `unavailableSince` if it isn't set and returns false. Incidents are untouched.

    **Plan call:** RSS items give no reliable open or resolved state, so they appear in Events but never light or clear the lamp.

- [ ] **Step 1: Write the failing tests**

`StatusDecodingTests`:
- `decodesOngoingIncidentsAndComponents`.
- `decodesIncidentDetailHistoryAndImpacts`.
- `decodesRSS`.
- `htmlPageThrowsUnexpectedPayload`.
- `missingSummaryThrows`.

`OpenAIStatusSourceTests` (a fake transport records URLs):
- `fetchesDetailOnlyForNewChangedOrVanished`.
- `neverRequestsLegacySummaryJSON`: no request path contains `/api/v2/`.
- `rssFillsTitleWhenDetailFails`.
- `summaryFailureFallsBackToRSS`.
- `malformedFetchKeepsStoredIncidentsOpen` (Review Focus: Malformed status fetch): an `error_page.html` success-status response, with RSS failing too. `apply` returns false, the stored open incident is unchanged, and `unavailableSince` is `now`.

`StatusStoreTests`:
- `upsertReplacesByID`.
- `overlappingQueryUsesImpactTimes`.
- `rssItemsDedupeByLink`.

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'StatusDecoding|OpenAIStatusSource|StatusStore'`
Expected: compile failure.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests and the full suite**

Run: the Step 2 command, then **Full suite**.
Expected: all pass.

- [ ] **Step 5: Commit** `Fetch OpenAI status incidents for Telltale`

---

### Task 7: Baseline engine

**Files:**
- Create: `telltale/Sources/TelltaleCore/Baseline/{InputBucket, Usual, BaselineEngine, ShiftDetector}.swift`, `telltale/Sources/TelltaleCore/Store/{Store+Baseline, Store+Rules}.swift`, `telltale/Tests/TelltaleTestSupport/Synth.swift`.
- Test: `telltale/Tests/TelltaleCoreTests/{BaselineTests, ShiftDetectorTests}.swift`.

**Interfaces:**
- Consumes: `Store`, responses and incidents (Tasks 3 and 6).
- Produces:
  - `public enum Direction: String, Codable, Sendable { case slower, faster }`.
  - `Store+Rules` (Task 8 extends it):
    - `EpisodeRow { id: Int64?, rule: String, provider, scope: String, direction: Direction?, onset, firedAt, endedAt: Date?, endReason: String?, severity: String, worstValue: Double, detail: Data? }`;
    - `insertEpisode`, `updateEpisode`, `speedEpisodes(provider:model:)`;
    - `EventRow { at, kind, provider, scope, title, body, episodeID: Int64?, epochID: Int64?, link: URL?, undoneAt: Date? }` and `insertEvent`.
  - `InputBucket`, one case per §7.1 input-size bucket. It has `init(inputTokens:)` and a `label`.
  - `LocalDay { year, month, day }`, with `init(_ date:, calendar:)` and `start(in:)`.
  - `UsualKey { effort: String?, serviceTier: String?, bucket: InputBucket }` (§8).
  - `UsualTable { medians: [UsualKey: Double]; samples: [UsualKey: Int]; activeDays: Int; epochID: Int64? }`. `usual(for: ResponseRecord) -> Double?` is nil below §8's bucket minimum.
  - `BaselineEngine(store:, calendar:)`:
    - `usual(provider:model:at:) -> UsualTable` follows the algorithm below. Cache by provider, model, its computed cutoff and effective epoch id; an engine recreated in a later collector run computes the same cutoff from stored action times;
    - `activeDays(provider:model:before:from:) -> [LocalDay]`;
    - `learning(provider:model:at:) -> Learning`: `.cold(days:)`, `.learning(days:of:)` or `.ready`, by §8's cold-start thresholds;
    - `currentEpoch(provider:model:) -> BaselineEpoch?`, where `BaselineEpoch` is `{ id, provider, model, since: LocalDay, createdAt, undoneAt: Date?, before: UsualTable, after: UsualTable }`;
    - `accept(provider:model:since:at:) -> Acceptance`, where `Acceptance` is `{ epochID, percentChange: Int }`. It writes a `baselineAccepted` event;
    - `undo(epochID:at:)` restores the epoch preceding the selected acceptance. In a transaction, mark that acceptance and any later live acceptances for the same provider/model undone at the action time, mark their acceptance events undone, and append a `baselineUndone` event referencing the selected acceptance **(plan call for out-of-order Undo)**. Other models' epochs are untouched;
    - `drift(provider:model:at:) -> Drift?`, where `Drift` is `{ percent: Int, direction: Direction, acceptedOn: LocalDay }`.
  - `mixUsual(_ responses:, table:) -> Double?`, the §8 mix-matched usual.
  - `ShiftDetector`:
    - `prompt(provider:model:at:store:calendar:) -> ShiftPrompt?`, where `ShiftPrompt` is `{ direction, firstDay: LocalDay, days: Int, typicalPercent: Int, incidentIDs: [String] }`;
    - `keepAsAbnormal(_:at:store:)`.

**Usual algorithm** (normative; it implements §8 and §7.3's fixed history):
```
usual(model, evaluation instant P):
  H       = start of P's sampling hour
  action  = latest created_at or undone_at for this model at or before P, if any
  cutoff  = max(H, action ?? H)
  epoch   = newest epoch for model with created_at <= P and (undone_at is nil or undone_at > P)
  days    = the most recent active days (§8 count) for model with responses ending before cutoff,
            restricted to days >= epoch.since when there is an epoch
  sample  = responses for model ending before cutoff on those days, with throughput non-nil,
            EXCLUDING a response whose end lies in a speed episode span [onset, end ?? cutoff)
                      and whose episode fired at or before cutoff
            UNLESS epoch exists and response.end >= start(epoch.since)
                   and episode.firedAt < epoch.created_at        // accepted episodes now count as normal
  medians = median(throughput) per UsualKey; keys below the §8 bucket minimum have no usual
```

Action times are persisted in `baseline_epochs`, so this algorithm does not depend on a prior process's cache. Rebuild uses those dated records to select epochs and cutoffs at each historical evaluation instant. Store the acceptance's before/after tables using this algorithm immediately before/after its transaction; Undo history remains represented by the dated undo fields and events.

**Other rules** (each is a plan call where §8 leaves the detail open):
- **Comparison sample:** the model's responses from its most recent 3 active days, restricted to data earlier than the action/evaluation instant.
- **`percentChange`:** over the comparison sample, the median of `after.usual(r) / before.usual(r) − 1`, rounded.
- **Drift:** the current table against the epoch's `after`, mix-matched over the comparison sample. It's nil with no epoch, or when its absolute value is under 5%.
- **Shift prompt** (§8 "Lasting shift prompt"):
  - Days without qualifying responses don't break the run.
  - A dismissed run, keyed by direction and `firstDay`, stays dismissed until a clear in that direction after `dismissed_at`, followed by a new run that starts after that clear.
  - `typicalPercent` is the median of the run's episode `worst_value` deviations.
  - `incidentIDs` are the incidents that overlap the run.
- **After Accept,** `learning` counts only the new epoch's active days. With fewer than §8's cold-start minimum, speed rules stay quiet until there are enough.

- [ ] **Step 1: Write the failing tests** (calendar `America/New_York`; `Synth` places responses)

`BaselineTests`:
- `bucketEdges`: each §7.1 edge value, and the value just below it.
- `usualKeyedByEffortAndServiceTier`: changing effort or tier independently separates medians in the same bucket.
- `bucketBelowMinimumHasNoUsual`.
- `onlyMostRecentActiveDaysCount`.
- `inactiveDaysDoNotCount`.
- `responsesInsideSpeedEpisodesAreExcluded`.
- `largePromptEpisodesDoNotExclude`.
- `onlyEarlierDataIsUsed`.
- `acceptStartsEpochFromSinceDay`: seed a lasting slowdown excluded by episodes; accept from its first day and assert its responses now contribute to usual and the reported percentage. Keep rates and expected arithmetic in the test.
- `undoRestoresPreviousEpoch`.
- `undoEarlierAcceptanceRestoresItsPredecessor`: include later acceptances for the selected model and an independent model; assert the selected model returns to its predecessor and the independent model is unchanged.
- `midHourAcceptAndUndoAffectNextEvaluation`: evaluate before and after each action in the same sampling hour, and assert the earlier stored point is unchanged while the later point uses the new effective table.
- `midHourActionSurvivesNewEngine`: recreate the engine and reopen the store after Accept and after Undo; assert the next evaluation in that hour uses the same effective table as the original engine.
- `episodesAfterAcceptanceStillExcluded`.
- `coldThenLearningThenReady`.
- `acceptWithRecentSinceDateIsColdUntilEnoughDays`.
- `driftReportedAgainstAcceptedUsual`: exercise values on each side of Task 7's drift threshold.
- `mixUsualMatchesRecentMix`.
- `activeDaysAcrossFallBackCountOnce` (Review Focus: Calendar transitions): place responses across a fall-back day, including the repeated local hour, and assert they occupy the same active day. Keep timestamps in the test.

`ShiftDetectorTests`:
- `consecutiveActiveDaysPrompt`.
- `gapDayWithoutActivityDoesNotBreakRun`.
- `oppositeDirectionBreaksRun`.
- `keepAsAbnormalSuppressesUntilClearAndNewRun`.
- `promptListsOverlappingIncidents`.

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'BaselineTests|ShiftDetectorTests'`
Expected: compile failure.

- [ ] **Step 3: Implement** per the algorithm. Task 9 discards the cache at the start of each run.

- [ ] **Step 4: Run the tests and the full suite**

Run: the Step 2 command, then **Full suite**.
Expected: all pass.

- [ ] **Step 5: Commit** `Compute Telltale's per-model usual speed with accepted epochs`

---

### Task 8: Rule engine, notification policy and copy

**Files:**
- Create: `telltale/Sources/TelltaleCore/Rules/{EvaluationPoints, SpeedIndex, EpisodeMachine, RuleEngine, NotificationPolicy}.swift`.
- Modify: `telltale/Sources/TelltaleCore/Rules/Copy.swift` (created in Task 1, extended in Task 3).
- Modify: `telltale/Sources/TelltaleCore/Store/Store+Rules.swift`.
- Test: `telltale/Tests/TelltaleCoreTests/{EvaluationPointsTests, SpeedIndexTests, EpisodeMachineTests, RuleEngineTests, NotificationPolicyTests, CopyTests}.swift`.

**Interfaces:**
- Consumes: Task 7 (`BaselineEngine`, `mixUsual`, `ShiftDetector`); Store accessors (Tasks 3 and 6); `RuleSettings`; `ModelNaming` (Task 3).
- Produces:
  - `LampColor: String, Codable, Comparable { red, amber, blue }`, ordered by §7.4's severity order.
  - `EvaluationPoints.after(_ last: Date?, through now: Date, earliest: Date) -> [Date]` uses §7.1's cadence, aligned on epoch seconds.
  - `SpeedIndex.at(_ point:, responses:, usual: (ResponseRecord) -> Double?) -> SpeedReading`, where `SpeedReading` is `{ index: Double?, mixUsual: Double?, medianTPS: Double?, samples: Int }`. It follows §7.1, including the thin-data minimum.
  - `EpisodeMachine` (Codable, stored in `rule_state`):
    - parameters `{ firePoints, clearPoints, windowMinutes }`;
    - `step(at:trigger:clear:red:idle:) -> [Transition]`, where `Tri` is true, false or unknown;
    - `Transition` is `fired(onset:severity:)`, `escalated`, `cleared` or `idleEnded`.
  - Store additions:
    - `eval_points` and `rule_state` accessors;
    - `unevaluatedFailedTurns(through:) -> [FailedTurnRecord]`, with the model attributed by joining `turn_id` to `responses` (§6.2), and `markEvaluated(_:at:)`;
    - `connectionEvents(in:)`, `openEpisodes()`.
  - `RuleEngine(store:, baseline:, calendar:, naming: [ProviderID: any ModelNaming])`:
    - `evaluate(points:, providers:, settings: RuleSettings, watchedComponents:, statusAvailable: Bool) throws -> [RuleOutcome]`;
    - `RuleOutcome` is `{ at, rule: RuleID, provider, scope, transition: Transition?, failures: [FailedTurnRecord], episodeID: Int64 }`;
    - `RuleID` has one case per §7.4 rule except collector health, which the UI owns (Task 10);
    - it writes eval points (known and unknown), episodes, events and rule state.
  - `NotificationPolicy.select(_ outcomes:, latestPoint:, intervalMinutes:, settings:, mode: EvalMode, lastFailureNotice: Date?) -> [PendingNotification]`:
    - `EvalMode` is `live` or `backfill`;
    - `PendingNotification` is `{ id, title, body, threadID }`;
    - the most recent failed-turn notice time is kept in `rule_state`.
  - `Copy`: one static function per row of the Copy table below. Times are `HH:mm` in the injected calendar's time zone. A display name comes from `ModelNaming.displayName`.

**Copy table.** This table defines new wording where a source reference cannot supply it; style follows the visual doc's Copy rules. Braced names are formatted function arguments, not literal text. Put the rows needed by a task into `Copy.swift` in that task; Task 8 adds the rule rows. Existing wording specified by the spec is referenced instead of copied. `CopyTests` holds synthetic argument values and expected formatted strings, including changed rule settings.

| Function | Text |
|---|---|
| `slowerFired(model:percent:since:)` | "{model} is {percent}% slower than usual for prompts this size. Since {since}." |
| `slowerCatchUp(model:percent:since:)` | Use §7.3's open-episode catch-up wording, substituting the arguments. |
| `slowerEscalated(model:percent:)` | "{model} is now {percent}% slower than usual." |
| `speedCleared(model:)` | Use §7.2's clear wording with the model's display name. |
| `fasterFired(model:percent:since:)` | "{model} is {percent}% faster than usual. Check that output isn't shallower. Since {since}." |
| `fasterCatchUp(model:percent:since:)` | "{model} has been {percent}% faster than usual since {since}." |
| `largePromptsFired(count:of:tokens:)` | Use the visual doc's panel alert wording, substituting the configured threshold and counts; use "at least" to match the inclusive trigger. |
| `largePromptsCleared` | "Prompt sizes are back to usual." |
| `failedTurns(count:reasons:)` | "{count} turn failed: {reasons}" for singular, "{count} turns failed: {reasons}" otherwise. |
| `failedTurnsCatchUp(count:reasons:since:)` | "{count} turn failed since {since}: {reasons}" for singular, "{count} turns failed since {since}: {reasons}" otherwise. |
| `failedTurnsCleared(quietMinutes:)` | "No failed turns for {quietMinutes} minutes." |
| `disconnectsFired(count:windowMinutes:)` | "{count} disconnect or retry events in the last {windowMinutes} minutes." |
| `disconnectsCatchUp(since:)` | "Frequent disconnects since {since}." |
| `disconnectsCleared` | "Connection is steady again." |
| `incidentFired(source:name:)` | "{source}: {name}." |
| `incidentCatchUp(source:name:since:)` | "{source}: {name}. Open since {since}." |
| `incidentEscalated(source:name:)` | "{source}: {name} is now an outage." |
| `incidentCleared(source:name:)` | "{source} resolved: {name}." |
| `statusPost(source:title:)` | "{source} posted: {title}." |
| `statusUnavailable(source:since:)` | Use §10's unavailable-state wording with the source name and time. |
| `usageLimitFired(percent:windowMinutes:resets:)` | "{percent}% of the {windowMinutes}-minute limit used. Resets at {resets}." Omit the reset sentence when `resets` is nil. |
| `usageLimitCleared` | "Usage is back under the limit you set." |
| `thinData` | §7.1's thin-data wording. |
| `noBucketHistory(bucket:)` | §8's insufficient-history wording with the bucket label. |
| `learning(days:of:)` | §8's learning wording with the day counts. |
| `shiftPrompt(model:percent:days:direction:)` | §8's lasting-shift wording, substituting model, percentage, days and direction. |
| `acceptance(model:percent:)` | §8's acceptance confirmation with the model and signed percentage change; choose "lower" or "higher" from its sign. |
| `drift(percent:direction:acceptedOn:)` | §8's drift wording with the arguments. |
| `connectionGap(from:to:)` | "Connection history incomplete from {from} to {to}." |
| `intervalError(min:max:)` | "Choose an interval from {min} to {max} minutes". |
| `clearBandError` | "The clear band must be stricter than the trigger". |
| `invalidRuleParameter(field:)` | "Choose a valid value for {field}." |
| `notInAppBundle` | "Run Telltale from Telltale.app to turn on the collector". |
| `wrongBundle` | "This copy of Telltale can't run the collector". |
| `launchctlError(command:status:stderr:)` | "Collector command {command} failed ({status}): {stderr}". |
| `rebuildConfirmation(days:)` | "Telltale will re-read the last {days} days. Your accepted baselines are kept." The caller uses §8's cold-start lookback. |
| `componentMissing` | "(not on the status page now)". |
| `nothingToReport` | §9.1's quiet-panel wording; also used for the quiet glyph's accessibility text. |
| `waitingForFirstRun` | "Waiting for the collector's first run." |
| `databaseUnavailable(reason:)` | "Telltale can't read its database: {reason}. Retrying automatically." |
| `notificationCheckTitle` | "Telltale notification check". |
| `notificationCheckBody(mode:)` | "Notification check: {mode}". |
| `testNotificationTitle` | Use `notificationCheckTitle`. |
| `testNotificationBody` | "This is a test notification from Telltale. Click to open the panel." |
| `notificationsDenied` | "Notifications are off. Allow Telltale in System Settings, then retry notifications." |
| `notificationRetryPending` | Use the pending-notification retry wording from Brew Version's `UserNotifier.lastError`. |
| `notificationAuthorizationFailure(error:)` | Use Brew Version's `UserNotifier.requestAuthorization` error context and `failureMessage` formatting. |
| `notificationPostFailure(error:)` | Use Brew Version's `UserNotifier.post` error context and `failureMessage` formatting. |
| `undoEarlierAcceptanceConfirmation(model:)` | "Restore {model}'s baseline from before this acceptance? Later acceptances for this model will also be undone." |
| `collectorNotBuilt` | "Collector not built yet". |
| `failedTurnReason(code:)` | `serverOverloaded`: "model at capacity"; `cyberPolicy`: "blocked by policy"; other codes display raw (plan call). |
| `collectorOff` | §9.3's off footer. |
| `formatProblem(since:)` | §6.5's format-problem wording with the time. |
| `collectorNotLoaded` | "Telltale's collector isn't loaded. Open the Collector view to turn it back on." |
| `collectorFailing(at:reason:next:)` | "The collector failed at {at}: {reason}. Next try {next}." |
| `collectorOverdue(since:)` | "The collector hasn't run since {since}." |
| `collectorRecovered` | "Telltale's collector is running again." |

Collectors and UI callers use these functions; tests for configurable windows exercise non-default settings. Task 10 implements the collector-health rows.

**Rule mechanics.** Use the §7.1 evaluation cadence. For a positive duration, compute the required point count by rounding `durationMinutes / cadenceMinutes` up, with a minimum of 1 **(plan call for durations between grid boundaries)**. Apply the same conversion to clear durations; other rules use their condition directly.

Use §7.4's per-rule trigger, clear, lamp and sample definitions with `RuleSettings` in place of defaults. Speed fractions convert to index boundaries by `1 ± fraction`. Scope slower, faster and large prompts by model, incidents by incident id, and failed turns, disconnects and usage limit by `*`. Incident title attribution uses `ModelNaming`; failed-turn attribution uses the Store join above. Missing speed readings and an empty large-prompt sample produce unknown. Idle ending follows §7.2 separately from sample selection.

- **Machine.**
  - Implement §7.1 and §7.2 for streaks, unknowns, onset, clearing and idle ending. Use the point-count conversion above for speed rules; count-based rules act at the point their condition holds, as the Task 3 defaults specify.
  - Track a separate red streak of `firePoints`; at initial fire it determines severity. A red fire emits `fired` without a separate `escalated`. A later qualifying red streak emits `escalated` once.
  - False resets a trigger streak; idle ending resets its machine. Non-speed onset uses the rule's own event/window context rather than the speed window **(plan call)**.
- **Failed turns.**
  - Each point evaluates the turns from `unevaluatedFailedTurns(through: p)`, then marks them evaluated.
  - A failed turn ingested late, in a later run, is still counted, at the first point evaluated after its ingest.
  - The outcome carries those failures.
  - **Late connection events** count only while they fall inside the rule's window **(plan call)**.
- **Status unavailable** (`statusAvailable == false`): the incident rule isn't stepped.
- **Speed points** read `usual` at `p`, using Task 7's effective-table selection. `learning == .cold` makes speed triggers unknown.
- **Notification policy:**
  - Follow §7.3 for backfill and catch-up, and §7.4's notification toggles. For its age boundary, an outcome is *fresh* when `latestPoint − at ≤ intervalMinutes·60`. Choose the Copy table's `…Fired` or `…CatchUp` row from that classification.
  - **Failed-turn coalescing:**
    - Unnotified failures accumulate.
    - At a fresh outcome with failures, the policy notifies with the accumulated count if no failed-turn notice went out in the last `coalesceMinutes`.
    - Otherwise the failures wait. They're sent at the first point after the window ends, with their count.
  - The policy respects each rule's `enabled` and `notify`. A disabled rule is not evaluated and writes nothing.
  - Every transition writes an `events` row with its copy, whether or not it notifies.

- [ ] **Step 1: Write the failing tests** (§7.4 defaults unless stated; `Synth` responses; calendar `America/New_York`)

`EvaluationPointsTests`:
- `pointsOnFiveMinuteBoundaries`.
- `afterLastPointExclusive`.
- `cappedAtEarliest`.
- `evaluationPointsAcrossDSTAreContiguous` (Review Focus: Calendar transitions): span a fall-back transition and assert adjacent points follow the §7.1 cadence without a skipped or repeated instant. Keep timestamps in the test.

`SpeedIndexTests`:
- `medianOfRatiosInTrailingWindow`.
- `belowMinimumSamplesIsUnknown`.
- `responsesWithoutUsualAreLeftOut`.
- `shortResponsesIgnored`.

`EpisodeMachineTests` (thresholds and clear bands at the `RuleSettings.defaults` values):
- `firesAfterFirePoints`.
- `nonGridDurationsRoundUpAndNeverFireEarly`: verify durations below a cadence and between cadence boundaries.
- `unknownPointsHoldNotReset`.
- `falseResetsStreak`.
- `clearsAfterClearPoints`.
- `outsideBandButPastTriggerDoesNotClear`: an index between the trigger and the clear band keeps the episode open.
- `flappingAroundThresholdProducesOneEpisode`.
- `idleEndsSilently`.
- `nextActivityAfterIdleStartsFreshEpisode`.
- `fireAtRedIsOneTransition`: red throughout gives one `fired(severity: .red)` and no `escalated`.
- `escalatesOnceWhenRedArrivesLater`.
- `onsetIsFirstTruePointMinusWindow`.

`RuleEngineTests`:
- `slowerFiresAndStoresPointsWithUsual`.
- `fasterFiresBlue`.
- `bothDirectionsAreSeparateEpisodes`.
- `coldModelStaysQuiet`.
- `largePromptsFiresAndClears`.
- `largePromptSelectionUsesLastResponsesAcrossTimeGap`: selection follows §7.4 while idle end remains a separate episode transition.
- `failedTurnLampHoldsForQuietWindow`.
- `failedTurnModelJoinedFromResponses`.
- `lateIngestedFailedTurnIsCounted`: ingest a failure after its event-time point was evaluated; count it at the next evaluated point.
- `disconnectsCountsExcludeReconnect`.
- `incidentOnWatchedComponentFires`.
- `incidentTitleNamingRecentModelFires`.
- `incidentRedForOutageImpact`.
- `incidentResolvedClears`.
- `unavailableStatusSourceDoesNotClearIncidentEpisode` (Review Focus: Malformed status fetch).
- `disabledRuleWritesNothing`.
- `historyStoresUsualInEffectAtTheTime`: after a later Accept, the stored `mix_usual_tps` is unchanged.

`NotificationPolicyTests`:
- `backfillNeverNotifies`.
- `freshFireUsesFiredCopy`.
- `transitionExactlyOneIntervalOldIsFresh`.
- `openEpisodeFromGapUsesCatchUpCopy`.
- `episodeClosedInsideGapIsSilent`.
- `staleClearAndEscalationAreSilent`.
- `clearRespectsNotifyOnClear`.
- `failedTurnsCoalesce`: seed failures before and after the initial notice; assert counts from the accumulated failures and silence until the configured coalescing window expires. Keep timestamps and expected counts in the test.
- `notifyOffRuleStillWritesEvents`.

`CopyTests`: a case per Copy table row, with synthetic inputs and expected text held in the test. Include `failedTurnsClearedUsesConfiguredQuietMinutes` and `disconnectsFiredUsesConfiguredWindow` with edited settings.

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'EvaluationPoints|SpeedIndex|EpisodeMachine|RuleEngine|NotificationPolicy|CopyTests'`
Expected: compile failure.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests and the full suite**

Run: the Step 2 command, then **Full suite**.
Expected: all pass.

- [ ] **Step 5: Replay real data (manual; nothing is committed).**
  - In the session scratchpad, create a SwiftPM package that depends on `telltale` by path.
  - It ingests Kevin's real `~/.codex` read-only, through `CodexUsageSource`, into a temporary database, then replays Oct 13–27 with `RuleEngine` in backfill mode.
  - **Pass:** every anomaly in spec §12 appears as an episode on its listed day, in its listed direction.
  - A missing or extra episode is reported to Kevin before Task 9 begins. It's a finding to investigate, not a reason to retune defaults.
  - Report the episode list without session ids.

- [ ] **Step 6: Commit** `Evaluate Telltale alert rules into episodes and notifications`

---

### Task 9: Collector run (`Telltale --collect`)

**Files:**
- Create: `telltale/Sources/TelltaleCore/Collector/{CollectorRun, RunLock, CollectorLog, Retention}.swift`, `telltale/Sources/Telltale/{CollectorEntry, Registry}.swift`.
- Modify: `telltale/Sources/Telltale/TelltaleMain.swift`.
- Test: `telltale/Tests/TelltaleCoreTests/{RunLockTests, CollectorLogTests, RetentionTests, CollectorRunTests}.swift`, `telltale/Tests/TelltaleIntegrationTests/CollectorIntegrationTests.swift`.

**Interfaces:**
- Consumes: Tasks 3–8; `NotificationService` (Task 1).
- Produces:
  - `RunLock.acquire(_ url: URL) throws -> RunLock?` implements §4's lock contract. It returns nil when the lock is held, and releases on deinit.
  - `CollectorLog(url:, maxBytes:, keep:)`, with defaults from §4 "Storage", and `write(_:at:)`. It rotates before a write that would exceed `maxBytes`.
  - `Retention.prune(store:, now:)` applies §4's retention table; `lastPrunedDay` limits work to once per local day.
  - `CollectorRun(paths:, sources: [any UsageSource], statusSources: [any StatusSource], notifier: any NotificationPosting, calendar:, now:, hooks: RunHooks = .none)`:
    - `run() async -> RunReport`, where `RunReport` is `{ outcome, exitCode: Int32, detail, notificationsPosted: Int }`;
    - `RunHooks.afterChunkCommit: ((Int) throws -> Void)?` is a test-only fault hook;
    - `public protocol NotificationPosting: Sendable { func post(_: PendingNotification) async throws }`. The executable adapts `NativeNotificationService` to it.
  - `Registry.usageSources(paths:)` and `Registry.statusSources()`: the single registration list (§5).

**Run order** (normative):
1. Create the directories and acquire `RunLock`; follow §4 on a held lock, recording the attempt as `skipped`.
2. `beginRun`, then read settings. If `rebuildRequestedAt` is set, apply the Rebuild table below, set `backfillThrough = now`, and clear the request. On a cold start (no evaluated point and no `backfillThrough`), also set `backfillThrough = now`.
3. Compute `backfillFrom` using §8's cold-start lookback. Ingest each usage source with it. Upsert the batch, store the cursor and source state, and record each gap as a `connectionHistoryIncomplete` event. One source's problem never stops another.
4. Fetch and apply each status source (Task 6's `apply`).
5. Evaluate points from the latest stored point (or `backfillFrom`) through `now`, in one-day chunks, each in its own transaction. A point at or before `backfillThrough` runs in `backfill` mode; later points run in `live`. A crash mid-backfill therefore resumes still in backfill.
6. Select notifications and post them. A failed post is logged and counted in `detail`; the run still succeeds.
7. Prune, then finish the run as `succeeded`, or as `failed` with the first error's description (exit 1).

**Rebuild storage mapping** (implements §7.3):

| Discarded | Kept |
|---|---|
| responses, `eval_points`, episodes, rule events, `rule_state`, cursors, `failed_turns.evaluated_at` (reset to null) | `baseline_epochs` and their events, `shift_dismissals`, incidents, `status_components`, `statusPost` events, `failed_turns` and `connection_events` rows, `usage_limits` and `source_state` (overwritten by the next ingest), settings |

`CollectorEntry` runs with `TelltalePaths.live()` and the registry, and exits with `exitCode`. `--collect` and `--notification-check` skip Task 11's UI instance gate.

- [ ] **Step 1: Write the failing tests**

`RunLockTests`:
- `secondAcquireWhileHeldReturnsNil`.
- `releasedOnDeinit`.

`CollectorLogTests`:
- `rotatesAtMaxBytesKeepingConfiguredCount`: with a small `maxBytes`, no file beyond `keep` exists.

`RetentionTests`:
- `prunesPerRetentionTable`.
- `prunesAtMostOncePerDay`.

`CollectorRunTests` (fake sources and notifier; temporary paths):
- `skippedWhenLockHeld`.
- `firstRunBackfillsWithoutNotifying`.
- `liveRunNotifiesFreshFire`.
- `sourceProblemDoesNotStopOtherSources`.
- `statusFailureMarksUnavailableAndKeepsIncidents`.
- `rebuildFollowsRebuildTable`: seed the tables named in the Rebuild storage mapping and assert that mapping, with no notifications. Keep concrete seed rows in the test.
- `postFailureStillSucceeds`.
- `crashMidBackfillResumesInBackfillMode`: inject failure after a committed chunk; resume from the next unevaluated point and assert that the backfill notification policy survives. Keep chunk positions in the test.
- `runWritesStartAndFinishRecords`.

`CollectorIntegrationTests` (a real `CodexUsageSource` on a synthetic `codexHome` from `TelltaleTestSupport`, a fake status transport, a temporary database, a fake notifier):
- `endToEndSlowdownFiresOnceAndClears`: seed enough normal synthetic history to leave cold start, then a slowdown crossing the default trigger but below red, followed by recovery. Run with an injected clock on evaluation boundaries. Expect the fire and clear notices using `Copy`; keep rates, timestamps and percentage arithmetic in the test.
- `twentyDayGapCatchUpIsBoundedAndQuiet` (Review Focus: Long catch-up gap):
  - run live once;
  - add a sustained multi-day synthetic workload with episodes that end inside the gap and an episode still open at its end; the named test holds the gap length and workload size;
  - run once. It finishes in under 60 s (`ContinuousClock`, debug build), and posts only `Copy.slowerCatchUp` for the open episode.
- `neverTouchesRealHome`: review injected dependencies and apply the comparison contract of `codexFilesAreNotModified`.

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'RunLock|CollectorLog|Retention|CollectorRun|CollectorIntegration'`
Expected: compile failure.

- [ ] **Step 3: Implement.** Add a README section "How the collector runs" that points at this run order and lists the exit codes.

- [ ] **Step 4: Run the full suite**

Run: **Full suite**.
Expected: all pass.

- [ ] **Step 5: Commit** `Run Telltale's collector: ingest, evaluate and notify`

---

### Task 10: Collector management and health

**Files:**
- Create: `telltale/Sources/TelltaleCore/Launchd/{CommandRunner, LaunchAgentManager, CollectorHealth}.swift`, `telltale/Sources/Telltale/CollectorMonitor.swift`.
- Modify: `telltale/Sources/TelltaleCore/Rules/Copy.swift` (collector-health rows), `telltale/Sources/TelltaleCore/Settings.swift`.
- Test: `telltale/Tests/TelltaleCoreTests/{LaunchAgentManagerTests, CollectorHealthTests}.swift`, `telltale/Tests/TelltaleAppTests/CollectorMonitorTests.swift`.

**Interfaces:**
- Consumes: `TelltalePaths`, `TelltaleRelease`, `Settings.intervalError`, the runs and source state (Tasks 1, 3 and 9); `NotificationService`.
- Produces:
  - `CommandRunner` (`run(_ executable: String, _ arguments: [String]) throws -> CommandResult`) and `ProcessRunner`, which has a 10 s timeout.
  - `LaunchAgentManager(paths:, uid:, runner:, label: = TelltaleRelease.collectorLabel)` implements §9.3's actions table and plist keys through these methods:
    - `plist(executable:intervalMinutes:)`;
    - `turnOn(executable:intervalMinutes:)`;
    - `turnOff()`;
    - `changeInterval(executable:intervalMinutes:)`;
    - `kickstart()`;
    - `installedExecutable() -> URL?`;
    - `isLoaded() -> Bool`;
    - `needsRepair(currentExecutable:) -> Bool`, comparing standardized, symlink-resolved paths;
    - `repair(executable:intervalMinutes:)`.

    Additional lifecycle policy: atomically replace the plist, ignore only a not-loaded bootout result, and propagate bootstrap errors.

    `turnOn`, `changeInterval` and `repair` each validate before writing anything:
    - the executable must be the main executable of a `.app` bundle;
    - that bundle's identifier must equal `TelltaleRelease.bundleIdentifier`;
    - the interval must pass `Settings.intervalError`.
  - `LaunchAgentError`:
    - `.notInAppBundle`: `Copy.notInAppBundle`;
    - `.wrongBundle(String)`: `Copy.wrongBundle`;
    - `.invalidInterval(String)`;
    - `.launchctl(command:status:stderr:)`: `Copy.launchctlError`.
  - `LampState { unlit, green, red }`.
  - `CollectorHealth.evaluate(enabled:, installedExecutable:, currentExecutable:, loaded:, runs:, intervalMinutes:, sourceStates:, now:) -> CollectorHealthReport`, where the report is `{ installed, loaded, lastRun, onSchedule: LampState; problems: [String]; needsRepair: Bool; footer: String; notify: Bool }`:
    - the lamps and the "off by choice" behavior follow the §9.3 Collector lamps table and its notes;
    - `notify` follows §7.4's Collector health row;
    - skipped runs count as neither successes nor failures.
  - Implement the collector-health functions in the Copy table and extend `CopyTests` for them.
  - `CollectorMonitor` (app target):
    - use §9.3's UI health-check cadence; post a notification per health episode, plus the recovered notice when `notifyOnClear` is on;
    - it persists `SettingKey.collectorHealthNotice` (`HealthNoticeState { problem: String, notifiedAt: Date }?`, default nil), so a relaunch doesn't re-notify;
    - it respects `rules.collectorHealth`.

- [ ] **Step 1: Write the failing tests**

`LaunchAgentManagerTests` (fake runner; temporary paths; synthetic `.app` bundles created in a temporary directory with an Info.plist):
- `plistHasSpecKeys`.
- `turnOnOrderIsWriteBootoutBootstrap`.
- `turnOnIgnoresNotLoadedBootout`.
- `bootstrapFailureSurfacesStderr`.
- `turnOffBootsOutAndRemovesPlist`.
- `changeIntervalRewritesAndReloads`.
- `invalidIntervalThrowsBeforeAnyWrite`.
- `kickstartCommand`.
- `isLoadedFromPrintStatus`.
- `needsRepairWhenPlistPointsElsewhere`.
- `turnOnRefusesExecutableOutsideAppBundle` (Review Focus: Non-installed collector launch): no file is written and no command runs.
- `turnOnRefusesOtherBundleIdentifier` (Review Focus: Non-installed collector launch): use the acceptance bundle identifier defined in Task 11; no file is written and no command runs.

`CollectorHealthTests`:
- `allGreenWhenHealthy`.
- `offByChoiceIsUnlit`.
- `missingPlistWhileEnabledIsRed`.
- `notLoadedIsRedAndNotifies`.
- `lastRunFailedShowsReasonAndNextTry`.
- `onScheduleBoundary`: exercise timestamps on each side of §9.3's limit; keep concrete timestamps in the test.
- `twoFailedRunsInARowNotify`.
- `noSuccessForThreeIntervalsNotifies`.
- `skippedRunsDoNotCount`.
- `formatProblemLightsRed`.

`CollectorMonitorTests`:
- `postsOncePerEpisode`.
- `postsRecoveredWhenGone`.
- `relaunchDoesNotRepost`.
- `respectsRuleSettings`.

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'LaunchAgentManager|CollectorHealth|CollectorMonitor'`
Expected: compile failure.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests and the full suite**

Run: the Step 2 command, then **Full suite**.
Expected: all pass.

- [ ] **Step 5: Commit** `Manage Telltale's launchd collector and report its health`

---

### Task 11: Status item, glyph and panel

**Files:**
- Port from `brew_version/Sources/BrewVersion/` into `telltale/Sources/Telltale/`, using the same `.swift` filename: `StatusItemController`, `StatusPanel`, `ApplicationMenu`, `SystemEvents`, `AppDelegate`. Port the `StatusIcon` part of `NativeActions.swift` into `telltale/Sources/Telltale/StatusIcon.swift`. Extend `telltale/Sources/Telltale/UserNotifier.swift` with the source's `UserNotifier` class.
- Port `anker_charge_monitor/Sources/PrimeMonitor/AppInstanceGate.swift` into `telltale/Sources/Telltale/AppInstanceGate.swift`.
- Create: `telltale/Sources/Telltale/{PanelView, LiveStore, Theme, UserActions}.swift`, `telltale/Sources/TelltaleCore/Read/PanelSnapshot.swift`.
- Port tests into `telltale/Tests/TelltaleAppTests/` using this mapping (source paths are repository-relative):

  | Source | Destination | Selection |
  |---|---|---|
  | `brew_version/Tests/BrewVersionAppTests/StatusPanelTests.swift` | `StatusPanelTests.swift` | Whole file |
  | `brew_version/Tests/BrewVersionAppTests/NativeActionsTests.swift` | `StatusIconTests.swift` | Tests exercising `StatusIcon`, with their helpers |
  | `brew_version/Tests/BrewVersionAppTests/NativeActionsTests.swift` | `UserNotifierTests.swift` | Notification authorization, posting, concurrency and retry cases, with their helpers |
  | `brew_version/Tests/BrewVersionAppTests/SystemEventsTests.swift` | `SystemEventsTests.swift` | Whole file |
  | `anker_charge_monitor/Tests/PrimeMonitorAppTests/AppInstanceGateTests.swift` | `AppInstanceGateTests.swift` | Whole file |

- Create tests: `telltale/Tests/TelltaleAppTests/{PanelViewTests, LiveStoreTests, AppDelegateTests}.swift`, `telltale/Tests/TelltaleCoreTests/PanelSnapshotTests.swift`.
- Create: `telltale/Tests/Snapshots/{build.sh, Snapshots.swift}`, `telltale/Tests/Acceptance/{build.sh, AcceptanceApp.swift, SyntheticEnvironment.swift, AcceptanceServiceTests.swift}`.
- Create: `telltale/Tests/ReleaseChecks/check_harnesses.sh`.
- Modify: `telltale/Makefile` (`snapshots`, `acceptance`), `telltale/README.md`, the Validation Matrix.

**Interfaces:**
- Consumes: Tasks 7, 8 and 10; `Registry`.
- Produces:
  - `PanelSnapshot.load(store:, baseline:, health:, sources: [SourceSummary], now:, calendar:) throws -> PanelSnapshot`:
    - `SourceSummary` is `{ provider, name, statusName, signals: Set<Signal>, naming: any ModelNaming }`, built from `Registry`;
    - `PanelSnapshot` is `{ checkedAt: Date?, lamps: [Signal: LampColor?], alerts: [Alert], models: [ModelRow], shift: ShiftPrompt?, footer: String }`;
    - `Alert` is `{ color: LampColor, text: String }`;
    - `ModelRow` is `{ id, name, tps: Double?, usual: Double?, sparkline: [Double?], note: String? }`.
    - Follow §5 for signal admission and §9.1 for provider labels.
    - Model rows, sparkline and footer follow §9.1. `usual` comes from `mixUsual`, and `note` uses Copy's thin-data and learning rows.
  - `LiveStore` (`@MainActor @Observable`) exposes `snapshot` and implements §4's database-read/refresh contract. Include the `-wal` file in its filesystem watch **(plan call)**.
    - Hold no Store until a read-only open succeeds. Missing or uninitialized storage shows a waiting snapshot with no model rows or checked time and `Copy.waitingForFirstRun` as its footer; the app does not collect or initialize derived storage.
    - Watch the parent directory while database files are absent and retry on the poll as well as filesystem changes. After the collector initializes the database, open read-only and replace the waiting snapshot.
    - Other open/read errors remain visible using `Copy.databaseUnavailable`; retain any previously loaded snapshot as stale and retry through the same path **(plan call on first-run/recovery presentation)**.
  - `UserActions` (`@MainActor`), the narrow read-write path of §4:
    - `checkNow()`;
    - `accept(model:since:)`, `undo(epochID:)`, `keepAsAbnormal(_:)`;
    - `set(_:_:)`, `requestRebuild()`.
  - `StatusIcon.image(for: PanelSnapshot) -> NSImage?`:
    - follow the visual doc's menu-bar glyph contract and Brew Version's `StatusIcon` drawing approach;
    - size and stroke are the builder's call within the source icon's footprint **(plan call)**;
    - accessibility text follows §9.1, with `Copy.nothingToReport` for the quiet case **(plan call on quiet wording)**.
  - `AppDelegate(paths:, currentExecutable: URL, installedAppURL: URL, runner: any CommandRunner, …)`, injected for tests. The composition root supplies `/Applications/Telltale.app` as `installedAppURL`; tests supply a bundle under their temporary root:
    - at launch, when `collectorEnabled` is true and the plist is missing, it turns the collector on;
    - but only when `currentExecutable`, standardized and symlink-resolved, equals the main executable of `installedAppURL` **(plan call: Review Focus's Non-installed collector launch risk)**; `LaunchAgentManager` still validates the bundle;
    - it takes the instance gate on `paths.appLock` and quits a second UI instance.

**Port adaptations:**
- **`StatusContent`** hosts `PanelView` with `LiveStore`, in place of Brew Version's watch content.
- **Panel buttons.** Its Settings and Open dashboard buttons call a `DashboardOpening` protocol. Task 12 conforms the dashboard controller to it.
- **No custom-interval UI.**
- **`AppDelegate`** wires `LiveStore`, `CollectorMonitor`, `SystemEvents`, the gate and the status item, as described above.
- **`AppInstanceGate`** follows its Anker source, using `paths.appLock`.
- **`UserNotifier`** behaves as `brew_version/Sources/BrewVersion/UserNotifier.swift` does, replacing its `Notifier`/`Notice`/`PackageName` dependencies with Telltale's `PendingNotification`. Notification actions open Telltale's panel. Use Task 1's extended service and the notifier rows in the Copy table. The test mapping above identifies the source coverage to port.

**`PanelView` layout** follows the visual doc's panel wireframe and the mockup.

- [ ] **Step 1: Port the tests first**

- Follow the port-test mapping. Before adapting, record source test names at the port commit in a comment in each destination; beside each name record its destination test name. Check this mapping against source declarations and port declarations, preserving selected coverage while allowing Telltale additions. Do not compare raw `@Test` counts for subset ports.
- `StatusIconTests` adds:
  - `templateWhenNothingLit`;
  - `dotUsesMostSevereColor`;
  - `accessibilityNamesLitLamps`.

`PanelSnapshotTests` (seeded store):
- `quietSnapshotHasNoLamps`.
- `slowEpisodeLightsSpeedAmber`.
- `redOutranksAmberInAlertOrder`.
- `modelRowsOnlyForRecentModels`.
- `usualIsMixMatched`.
- `thinDataNote`.
- `learningNote`.
- `shiftPromptIncluded`.
- `collectorOffFooter`.
- `lampsLimitedToDeclaredSignals`.
- `alertsNameProviderWhenSeveral`.

`AppDelegateTests` (fake runner, synthetic bundles):
- `launchRestoresCollectorWhenEnabledAndMissing`: `installedAppURL` and `currentExecutable` name a matching synthetic bundle under the temporary root; `bootstrap` is called once.
- `launchDoesNotAutoEnableOutsideApplications` (Review Focus: Non-installed collector launch): a build-folder bundle with the real identifier runs no command.
- `collectorOffByChoiceIsNotTurnedOn`.
- `secondUIInstanceQuits`.

`LiveStoreTests`:
- `refreshesWhenDatabaseChanges`.
- `pollFallbackRefreshes`.
- `missingDatabaseWaitsThenLoadsAfterCollectorCreatesIt`.
- `uninitializedDatabaseIsRetried`.
- `databaseReadFailureIsVisibleAndRetryable`.

`PanelViewTests`:
- `rendersNothingToReportWhenQuiet`.
- `checkNowCallsKickstart`.

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'StatusPanel|StatusIcon|SystemEvents|AppInstanceGate|UserNotifier|PanelSnapshot|LiveStore|PanelView|AppDelegate'`
Expected: compile failure.

- [ ] **Step 3: Port and implement** under Global Constraints' Ports policy and the source-to-destination test mapping.

- [ ] **Step 4: Run the focused tests**

Run: the Step 2 command. The final **Full suite** run follows the harness edits.
Expected: all pass, with no ported test removed.

- [ ] **Step 5: Add snapshots and the acceptance harness**

- **`Tests/Snapshots/build.sh`.** Port `brew_version/Tests/Snapshots/build.sh`, adapted:
  - preserve the source builder's exclusion of production lifecycle owners: exclude `TelltaleMain.swift` and `AppDelegate.swift`, plus `CollectorEntry.swift`, `Registry.swift` and `NotificationCheck.swift`. Copy nested core sources while preserving their target layout; harness entry points supply synthetic construction and actions;
  - `Snapshots.swift` owns the maintained-view inventory. For this task, render the panel states on §13's snapshot list, using seeded synthetic stores and the source renderer's appearance loop.
- **`Tests/Acceptance/build.sh`.** Port `brew_version/Tests/Acceptance/build.sh`, adapted:
  - it builds a signed acceptance app with bundle identifier `com.example.telltale.acceptance`, so `LaunchAgentManager` refuses it;
  - seed its database with an alerting model, a shift prompt and the collector off;
  - `UserActions.checkNow` is a harness double.
  - use the snapshot builder's production-source exclusions and recursive library-copy policy; `AcceptanceApp.swift` supplies the app lifecycle;
  - omit Brew Version's `Homebrew-LICENSE.txt` copy; package Telltale's resources according to its release recipe;
  - replace the Homebrew-specific `SyntheticTransport.swift` dependency with Telltale's `SyntheticEnvironment.swift`. Replace the source's Homebrew service-test cases with `AcceptanceServiceTests.swift`, exercising seeded-store construction, injected command/action doubles and isolation from live paths/services. Keep the generated service-test target and its pre-build test run, adapted to the Telltale harness module names;
  - omit the source's `--settings-prototype` option and `SettingsPrototype.swift` branch; Telltale's Settings is exercised through the maintained acceptance app.
- **`check_harnesses.sh`.** Port the maintained-snapshot runtime block from Anker's `Tests/ReleaseChecks/check_bundle.sh`, adapting its source names. The snapshot builder prints the executable path needed by that block. Also build the synthetic acceptance target and assert its executable has the source package's supported runtime. Task 1's `test` recipe discovers this new release-check script, so the builders run in the full suite without calling `test` recursively. PNG inspection and real-click acceptance remain distinct README checks.
- **README "Native acceptance".** Port the checklist in `brew_version/README.md`'s "Settings and native acceptance gates" section. Record native results separately from automated ones.
- **Validation Matrix.** Add **Snapshots** and **Acceptance build**, described by their builders' contracts.

Run: **Snapshots** and **Acceptance build**.
Expected: each command succeeds. Inspect every printed PNG. The acceptance build prints its bundle path.

- [ ] **Step 6: Native acceptance (Kevin, or with his go-ahead).** Run the README checklist on the acceptance bundle, and record the date, macOS build and outcomes. Any failed press is a failure.

- [ ] **Step 7: Final full suite and commit** `Show Telltale's lamps in the menu bar with Brew Version's status item`

Run **Full suite**, then apply Global Constraints' Commits policy.

---

### Task 12: Dashboard window

**Files:**
- Port: `brew_version/Sources/BrewVersion/SettingsWindowController.swift` into `telltale/Sources/Telltale/DashboardWindowController.swift`.
- Create: `telltale/Sources/Telltale/{DashboardView, ModelView, CollectorView, Fonts}.swift`, `telltale/Sources/TelltaleCore/Read/{ModelDetail, Workload, EventFeed}.swift`, `telltale/Resources/Fonts/*`.
- Modify: `telltale/Makefile` (copy the fonts into the bundle's Resources), `telltale/Tests/Snapshots/Snapshots.swift`.
- Test: `telltale/Tests/TelltaleCoreTests/{ModelDetailTests, WorkloadTests, EventFeedTests}.swift`, `telltale/Tests/TelltaleAppTests/{DashboardWindowTests, ModelViewTests, CollectorViewTests, FontsTests}.swift`.

**Interfaces:**
- Consumes: Task 11's `LiveStore`, `UserActions`, `Theme` and `DashboardOpening`; Tasks 7, 8 and 10.
- Produces:
  - `ModelDetail.load(store:, baseline:, provider:, model:, range: ChartRange, now:, calendar:)`:
    - `ChartRange` is one case per §9.2 range;
    - `ModelDetail` is `{ lastHour: Readout, dots: [SpeedDot], incidents: [DateInterval], failures: [Date], learning, drift: Drift?, shift: ShiftPrompt?, bucketGaps: [InputBucket] }`;
    - `Readout` is `{ tps, usualTPS, medianSeconds, usualMedianSeconds }`;
    - `SpeedDot` is `{ hour, index, color: LampColor? }`, the hourly median of stored points, colored by the episode in effect then.
  - `Workload.load(store:, provider:, model:, now:, calendar:)`. It holds the §9.2 Workload measures, now against usual, plus a bucket histogram and `usageLimit: UsageLimitSnapshot?` (§6.4):
    - "now" uses §9.2's workload window, averaged over its active hours;
    - "usual" follows §9.2's workload-usual rule;
    - shares are ratios of sums.
  - `EventFeed.load(store:, limit:) -> [FeedEvent]`, where `FeedEvent` is `{ id, at, kind, title, body, link: URL?, undoableEpochID: Int64? }`. Implement §8's Undo contract. An already-undone event shows its undone state. For an older acceptance, confirm using `Copy.undoEarlierAcceptanceConfirmation` before Task 7's undo transaction.
  - `DashboardWindowController: DashboardOpening`:
    - `show(section:)`, where the section is `model(ProviderID, String)`, `collector` or `settings`;
    - follow `docs/lessons_learned.md`'s reused-window entry and §3's window contract;
    - inject `ActivationPolicyApplying` for the §3 activation-policy transitions.
  - `Fonts.register(from: URL) -> Bool`, registering for the process. On failure, the system font stands in and a log line is written **(plan call)**.
  - `Theme` applies §9.4's appearance contract.

**Views** follow §9.2, §9.3 and the visual doc's dashboard and collector wireframes and the mockup:
- **Model view: Accept as usual…** follows §8's picker contract. With no shift, default to today **(plan call)**.
- **Collector view:** show the tail of `collector.log` **(plan call)**; the log-file action follows §9.3.

- [ ] **Step 1: Get the fonts (needs Kevin's OK to download).**
  - Ask before downloading:
    - `BarlowSemiCondensed-Regular.ttf`, `BarlowSemiCondensed-Medium.ttf` and `OFL.txt`;
    - from `https://raw.githubusercontent.com/google/fonts/main/ofl/barlowsemicondensed/<file>`;
    - state each file's size.
  - Confirm that each URL resolves before asking.
  - Record the URLs and sha256 values in `Resources/Fonts/SOURCE.md`.

- [ ] **Step 2: Write the failing tests**

`ModelDetailTests`:
- `dotsAreHourlyMediansOfStoredPoints`.
- `dotColorsComeFromEpisodesAtTheTime`.
- `incidentBandsAndFailureMarkers`.
- `readoutUsualIsMixMatched`.
- `bucketGapsListed`.
- `rangeLimitsData`.

`WorkloadTests`:
- `nowIsLastThreeHoursActiveHoursOnly`.
- `usualIsMedianOfActiveHours`.
- `sharesComputedFromSums`.
- `effortMixSumsToOne`.
- `histogramSharesBothSides`.
- `usageLimitIncluded`.

`EventFeedTests`:
- `newestFirst`.
- `eachAcceptanceOffersUndoUntilUndone`.
- `olderAcceptanceUndoRequiresConfirmation`.
- `statusPostsCarryLinks`.

`DashboardWindowTests`:
- `showSetsRegularPolicyAndCloseRestoresAccessory`.
- `windowIsReusedAndMovesToActiveSpace`.
- `defaultSizeFromSpec`.

`ModelViewTests`:
- `acceptFlowCallsUserActionsWithChosenDate`.
- `acceptConfirmationUsesAcceptanceCopy`.
- `undoButtonCallsUndo`.

`CollectorViewTests`:
- `repairShownOnlyWhenNeeded`.
- `turnOnFailureShowsErrorText`.
- `offStateShowsUnlitLamps`.

`FontsTests`:
- `registersBundledFonts`: every font listed in `Resources/Fonts/SOURCE.md` resolves by PostScript name after registration.

- [ ] **Step 3: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'ModelDetail|Workload|EventFeed|DashboardWindow|ModelView|CollectorView|FontsTests'`
Expected: compile failure.

- [ ] **Step 4: Implement.**

- [ ] **Step 5: Run the focused tests**

Run: the Step 3 command. The final **Full suite** run follows the snapshot edits.
Expected: all pass.

- [ ] **Step 6: Extend the snapshots** with the dashboard model view and the collector problem view (§13). Run **Snapshots** and **Acceptance build**; inspect every PNG against the mockup. Record the renewed native checklist outcome separately.

- [ ] **Step 7: Final full suite and commit** `Add Telltale's dashboard with speed, workload and collector views`

Run **Full suite**, then apply Global Constraints' Commits policy.

---

### Task 13: Settings and login item

**Files:**
- Port: `brew_version/Sources/BrewVersion/LoginItem.swift` into `telltale/Sources/Telltale/LoginItem.swift`; port `anker_charge_monitor/Tests/PrimeMonitorAppTests/LoginItemTests.swift` into `telltale/Tests/TelltaleAppTests/LoginItemTests.swift`.
- Create: `telltale/Sources/Telltale/SettingsView.swift`.
- Modify: `telltale/Tests/Snapshots/Snapshots.swift`.
- Test: `telltale/Tests/TelltaleAppTests/{SettingsViewTests, LoginItemTests}.swift`.

**Interfaces:**
- Consumes: `UserActions` (Task 11); `LaunchAgentManager` (Task 10); `Store.components(source:)` (Task 6); `RuleSettings.validationErrors` and `Settings.intervalError` (Task 3).
- Produces: `SettingsView`, the dashboard's Settings section, following the §9.4 table. Additions:
  - **Rules.** Parameters display as percentages and minutes. An invalid edit shows its validation message inline and isn't saved.
  - **Collector.** Changes go through `LaunchAgentManager`, and a failure shows its error text.
  - **Watched components.** Saved names missing from the status page use `Copy.componentMissing`.
  - **Data.** Retention is shown from the §4 retention table, not editable **(plan call)**. Rebuild asks with `Copy.rebuildConfirmation(days:)`, then sets the request and kicks the job.
  - **General.** Apply §3's login-item behavior through the ported `LoginItem` and its injected service.

- [ ] **Step 1: Write the failing tests**

`SettingsViewTests`:
- `editingThresholdSavesRuleSettings`.
- `clearBandNotStricterShowsErrorAndDoesNotSave`.
- `resetToDefaultRestoresDefaults`.
- `intervalChangeRewritesLaunchAgent`: a synthetic Telltale bundle executable, with the fake runner seeing bootout and then bootstrap.
- `intervalChangeFailureShowsMessage`.
- `componentChecklistSavesNames`.
- `rebuildRequiresConfirmationThenKickstarts`.
- `appearanceChangeUpdatesTheme`.

`LoginItemTests`: every ported case, plus:
- `launchRegistersWhenOpenAtLoginOn`.
- `turningOffUnregisters`.

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path telltale --filter 'SettingsView|LoginItem'`
Expected: compile failure.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the focused tests**

Run: the Step 2 command. The final **Full suite** run follows the snapshot edits.
Expected: all pass.

- [ ] **Step 5: Extend the snapshots** with Settings showing an invalid Rules field. Run **Snapshots** and **Acceptance build**; inspect the views on §13's snapshot list in each supported appearance. Record the renewed native checklist outcome separately.

- [ ] **Step 6: Final full suite and commit** `Add Telltale settings for rules, collector and appearance`

Run **Full suite**, then apply Global Constraints' Commits policy.

---

### Task 14: Deployment tool and docs

**Files:**
- Create: `tools/deploy_telltale.mjs`, `tools/tests/deploy_telltale.test.mjs`, `tools/tests/telltale-deployment-fixture.mjs`.
- Modify: `tools/check_local_deployments.zsh` and `tools/tests/test_check_local_deployments.zsh`. Find every place they handle Anker Charge Monitor with `grep -n 'anker' <file>`, and add the Telltale counterpart, including the fixture setup and a `test_native_telltale_deployment` case.
- Modify: `docs/local_deployment_sync.md`:
  - a "Telltale app deployment" section modeled on "Anker Charge Monitor app deployment";
  - every step its "Adding a deployment" section requires.
- Modify: the Validation Matrix (Telltale's deployment line, and `deploy_telltale.test.mjs` in the "Static deployment/fleet audit tooling" `node --test` list), `telltale/README.md` (Deploy), and root `README.md` (the native-binaries sentence in "Development and deployment").

**Interfaces:**
- Consumes: `tools/deployment_files.mjs`, and `appTreeHash` from `tools/deploy_brew_version.mjs`, as `deploy_anker_charge_monitor.mjs` does.
- Produces: `deploy_telltale.mjs`, a port of `deploy_anker_charge_monitor.mjs`:
  - Telltale's project and app names, with no legacy name;
  - its required build inputs, the Task 1 files the Makefile and installer need;
  - its plist contract, with the §3 identifiers and Anker's minimum-OS and agent keys;
  - every CLI flag, with the same semantics.

  The tool doesn't touch launchd. The deployment doc links to §13's post-deployment check.

- [ ] **Step 1: Write the failing tests.** Port every `test(` case in `tools/tests/deploy_anker_charge_monitor.test.mjs`, and its fixture, to Telltale. Drop only the parts about Anker's legacy app name (`legacyName`), and note each dropped assertion in the test file.

- [ ] **Step 2: Run them to verify they fail**

Run: `node --test tools/tests/deploy_telltale.test.mjs`
Expected: fail (module not found).

- [ ] **Step 3: Implement** the tool, the fleet-audit registration, its test and the docs.

- [ ] **Step 4: Run every affected suite**

Run each of these and report each result:
- every command in the Validation Matrix's "Static deployment/fleet audit tooling" entry;
- every `telltale` Validation Matrix command.

Expected: all pass. Any failure is fixed or shown, never dismissed.

- [ ] **Step 5: Commit** `Deploy Telltale to /Applications with the native installer`

Real deployment needs Kevin's separate authorization after review and merge (AGENTS.md, Validation Matrix), and is outside this plan.

---

## Completion checks (part of Task 14's Step 4, for the final reviewer)

- Apply `AGENTS.md`'s Release Versions checks to the Task 1 release declarations and built bundle.
- Run `rg --hidden -n -i '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' telltale tools`, which includes non-ignored untracked files. Inspect matches against Global Constraints' synthetic-data policy. `rg` exit 1 means no matches; exit 2 is a scan failure.
- Run `rg --hidden -n '/Users/' telltale tools`. Inspect each match: distinguish guard-pattern syntax and conspicuously synthetic fixtures from actual private path literals; documentation paths use `/Users/example`. Resolve potential private literals under the repository's Public Repository rule before staging. Interpret exit codes as above. These searches are targeted checks; the complete staged-file and staged-diff inspection remains required.
- The spike results, native acceptance results and the Task 8 replay are recorded with dates. Unverified gates are listed as unverified.
