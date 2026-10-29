# Telltale Claude Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Telltale 0.2.0 watches Claude Code beside Codex, as
[telltale_claude_design.md](telltale_claude_design.md) specifies.

**Architecture:** Register these plugin targets in
`Sources/Telltale/Registry.swift`:
- `TelltaleClaude`, a `UsageSource` (design §5);
- `TelltaleStatuspage`, a generic `StatusSource` (design §6).

Follow design §§4 and 8 for core and app changes.

**Spec:** [telltale_claude_design.md](telltale_claude_design.md), cited as "design §n". It builds
on [telltale_design_spec.md](telltale_design_spec.md) ("spec §n") and
[telltale_visual_design.md](telltale_visual_design.md). Read the design in full before starting
any task. Where a task says "per design §n", that section is the requirement, and the task adds
only the interfaces, the tests and the decisions the design leaves to the builder.

## Global Constraints

**Repository rules**
- Follow the root `AGENTS.md` and design §9.

**Data handling**
- Follow design §§5.2 and 9 for permitted metadata and privacy.

**Git**
- Follow the root Git rules. Do not invent co-author attribution.

**Fixed values**
- Use the identifiers in design §§5 and 6.1, the replay policy in spec §7.3,
  `CollectorRun.lookbackDays`, and the copy and color rules in the visual design.

**Validation**
- The full test suite is `make -C telltale test`, run from the repository root. Follow the
  Telltale README and root validation matrix for release and owner-run native acceptance gates.
- Focused runs go from `telltale/`:
  ```bash
  mkdir -p .build/tmp && TMPDIR="$PWD/.build/tmp/" tools/check_no_temp_leaks.sh swift test -Xswiftc -warnings-as-errors --filter '<regex>'
  ```
  Follow `telltale/README.md` for Swift test isolation.
- Return to the repository root after each focused run before executing any root-relative command,
  including `make -C telltale` and the `rg` commands in this plan.
- Snapshots: `make -C telltale snapshots`. Acceptance: `make -C telltale acceptance`.
- Follow `Tests/Snapshots/build.sh` and `Tests/ReleaseChecks/check_test_isolation.sh` when
  building synthetic harness scenes and test fixtures.

## Review Focus

Use the tests in the evaluation progress, per-provider Rebuild, Claude usage source,
Statuspage source and source registration tasks to cover upgrade, interruption and availability.

---

### Task 1: Evaluation progress, backfill and failed-turn notices per evaluation unit (G1)

**Files:**
- Modify: `Sources/TelltaleCore/Store/Store+Rules.swift`, `Sources/TelltaleCore/Rules/RuleEngine.swift`,
  `Sources/TelltaleCore/Rules/NotificationPolicy.swift`, `Sources/TelltaleCore/Collector/CollectorRun.swift`
  (including the `RunReport` doc comment that describes the skipped evaluation),
  `Sources/TelltaleCore/Settings.swift` (the `backfillThrough` doc comment).
- Test: `Tests/TelltaleCoreTests/StoreTests.swift`, `RuleEngineTests.swift`, `CollectorRunTests.swift`,
  `NotificationPolicyTests.swift`.
- Modify: `README.md`, including “How the collector runs” and the exit-code table, to describe
  the resulting per-unit progress and ingest-failure behavior.

**Interfaces:**
- Produces, in `RuleEngine.swift`:
  ```swift
  /// What one evaluation pass covers. Each unit has its own progress, keyed by `key`.
  public enum EvaluationUnit: Sendable, Equatable {
      case provider(ProviderID)
      /// `available` false: points advance with no incident evaluated (today's `statusAvailable: false`).
      case statusSource(RuleStatusSource, available: Bool)
      public var key: String { get }   // the provider's raw value, or the status source id
  }
  public func evaluate(points: [Date], unit: EvaluationUnit, settings: RuleSettings, watchedComponents: [String]) throws -> [RuleOutcome]
  ```
  - Divide rules between units per design §4 G1.
  - Each pass loads only the `rule_state` rows and open episodes whose `provider` equals
    `unit.key`.
  - Replace the old `evaluate(points:providers:statusSources:settings:watchedComponents:statusAvailable:)`
    at every call site (`rg -n '\.evaluate\(' telltale/Sources telltale/Tests`).
- Produces, in `Store+Rules.swift`:
  ```swift
  public enum BackfillReason: String, Sendable, Codable { case new, rebuild }
  public struct ProviderBackfill: Sendable, Equatable, Codable {
      public var reason: BackfillReason
      public var startedAt: Date
      public var through: Date      // points after it are live
      public var finishedAt: Date?  // set when every eligible evaluation point through `through` has been processed
      /// True only for a `.new` provider backfill begun while another provider already had a last evaluated point (design §8.3).
      public var announce: Bool
  }
  public func lastEvaluatedPoint(unit key: String) throws -> Date?
  func setLastEvaluatedPoint(_ point: Date, unit key: String) throws
  public func backfill(unit key: String) throws -> ProviderBackfill?
  func setBackfill(_ backfill: ProviderBackfill, unit key: String) throws
  public func backfills() throws -> [String: ProviderBackfill]
  public func failureNotices(provider: ProviderID) throws -> FailureNotices
  public func setFailureNotices(_ notices: FailureNotices, provider: ProviderID) throws
  public func unevaluatedFailedTurns(provider: ProviderID, through: Date) throws -> [FailedTurnRecord]
  func adoptGlobalProgress(providers: [ProviderID], legacyStatusSourceIDs: [String]) throws -> Bool
  ```
  Storage goes in `rule_state` under `provider = unit key`. The scopes are:
  - `lastPoint`, under rule `engine`;
  - `backfill`, a new scope under rule `engine`;
  - `failedTurns`, under the notifications rule.
- Produces, in `NotificationPolicy.swift`: `failedTurnsThreadID(provider: ProviderID) -> String`,
  replacing the constant. The thread and notice ids include the provider.

**`adoptGlobalProgress` contract.**
- It runs only while the `engine`/`*`/`lastPoint` row exists.
- For each unit key that has a stored cursor (providers), and for each status source known to
  have existed in the legacy database, it
  copies:
  - the point;
  - the `*` failed-turn notices (providers only);
  - a backfill built from the `backfillThrough` setting: `reason .new`,
    `startedAt = through = backfillThrough`, `announce false`. `finishedAt` is `backfillThrough`
    when the adopted point is at or after it, else nil.
- It then deletes the `*` rows and the `backfillThrough` setting, and returns true. Otherwise it
  returns false.
- Pass the legacy OpenAI status source ID for a 0.1.1 upgrade; newly registered status sources
  receive their own quiet backfill. Cover both cases in `adoptGlobalProgressMovesStarRows` and
  `newStatusSourceBackfillsQuietlyOnUpgrade`.
- Finish a backfill once its last eligible grid point at or before `through` has been processed;
  `through` itself need not be on the evaluation grid. Handle an empty eligible range as complete.

**Collector order: `prepareBackfill`.** Within one transaction:
1. adopt;
2. apply the global `rebuildRequestedAt` as the per-provider Rebuild task specifies;
3. give each status source with no progress a backfill
   (`reason .new, startedAt = through = now, announce false`).

**Collector order: after ingest.** Give each provider with no progress and no backfill a
backfill, but only if its ingest state this run is `.ready`. That backfill is
`ProviderBackfill(reason: .new, startedAt: now, through: now, finishedAt: nil, announce: <another provider has a last point>)`.
A provider with no prior progress or backfill that isn't ready gets neither a backfill nor an
evaluation. Cover a previously progressed provider becoming unavailable in
`progressedUnavailableProviderFollowsEvaluationPolicy`.

**Collector order: evaluation.**
- Evaluate each ready or already-progressed provider, then each status source.
- A provider whose ingest threw this run is skipped, and so is a status source whose provider
  ingests all threw.
- Liveness and failure notices are per unit and per provider.

- [ ] **Step 1: Write the failing tests.** Use synthetic providers and status sources.
  ```swift
  @Test func progressIsPerUnit()
  @Test func adoptGlobalProgressMovesStarRows()
  @Test func adoptMidBackfillLeavesItUnfinished()
  @Test func evaluationOnlyTouchesItsUnit()
  @Test func sharedStatusSourceEvaluatesIncidentsOnce()
  @Test func newProviderBackfillsQuietlyWhileOtherStaysLive()
  @Test func freshDatabaseBackfillsBothWithoutAnnouncing()
  @Test func upgradeFrom011KeepsCodexLive()
  @Test func providerReadyLaterBackfillsQuietly()
  @Test func interruptedBackfillResumesQuietly()
  @Test func offGridBackfillFinishes()
  @Test func ingestFailureSkipsOnlyThatProvider()
  @Test func failedTurnNoticesCoalescePerProvider()

  ```
  Then update these existing tests for per-unit state (design §4 G1):
  - every `CollectorRunTests` assertion on `.backfillThrough` becomes
    `backfill(unit: "codex")?.through` (`rg -n backfillThrough telltale/Tests`);
  - update `ingestFailureSkipsEvaluationAndRetriesNextRun` for its existing failing and healthy
    sources: the failing provider's progress remains unchanged and it retries, while Codex
    progresses and may notify;
  - adapt `reportedSourceProblemStillEvaluates` to cover an initially unavailable provider with
    no progress and the previously progressed case in `progressedUnavailableProviderFollowsEvaluationPolicy`;
  - the `RuleEngineTests` helper calls `evaluate(points:unit:…)`.
- [ ] **Step 2: Run them and see them fail.**
  Use the focused command with `--filter 'StoreTests|RuleEngineTests|CollectorRunTests|NotificationPolicyTests'`.
  Expect a compile failure: `EvaluationUnit` is undefined.
- [ ] **Step 3: Implement the store and engine interfaces.** `EvaluationPass` takes the unit. For
  `.statusSource`, its `series` holds the source's providers' responses from `preloadStart`, used
  only by `titleNamesRecentModel`.
- [ ] **Step 4: Implement the collector order above.** Log each backfill start with the unit's
  display name.
- [ ] **Step 5: Run the focused command, then the full suite.** Expect PASS.

### Task 2: Per-provider Rebuild

**Files:**
- Modify: `Sources/TelltaleCore/Collector/CollectorRun.swift` (`discardForRebuild`, `prepareBackfill`),
  `Sources/TelltaleCore/Settings.swift`, `Sources/TelltaleCore/Store/Store+Rules.swift` (event kinds),
  `Sources/TelltaleCore/Rules/Copy.swift`, `Sources/Telltale/UserActions.swift`.
- Test: `CollectorRunTests.swift`, `CopyTests.swift`, `SettingsTests.swift`,
  `Tests/TelltaleAppTests/PanelViewTests.swift` (`actionsNeverCreateTheDatabase`).

**Interfaces:**
- Consumes: the evaluation progress task's units and backfills.
- Produces:
  ```swift
  extension SettingKey where Value == [String: Date] {
      /// Provider id → when its Rebuild was requested (design §8.3).
      public static var providerRebuildRequests: SettingKey<[String: Date]>   // name "providerRebuildRequests", default [:]
  }
  extension EventKind { public static let providerAdded = "providerAdded"; public static let historyRebuilt = "historyRebuilt" }
  func discardForRebuild(provider: ProviderID) throws   // Store
  func requestRebuild(provider: ProviderID) throws      // UserActions; read-modify-write inside one Store.transaction
  public static func providerAdded(name: String, days: Int) -> String
  public static func historyRebuilt(name: String, days: Int) -> String
  public static func rebuildConfirmation(days: Int, providers: [String]) -> String   // replaces rebuildConfirmation(days:)
  ```
- Apply design §12 (Decided, Rebuild) and the existing `discardForRebuild()` contract.
- In `prepareBackfill`, per-provider requests are applied before the evaluation progress task's new-provider backfills.
  A rebuilt provider gets `reason .rebuild, announce false`. The request is removed from the
  dictionary in the same transaction.
- `providerAdded` and `historyRebuilt` are kept by every Rebuild, like `statusPost`.
- Write completion events per design §8.3.
- `providerRebuildLeavesOtherUnitsUntouched` compares unaffected units with an equivalent live
  control run without the rebuild, so their normal evaluation and notification updates are allowed.
- Preserve a completed, undismissed arrival independently of the mutable backfill record when a
  rebuild replaces that record. Introduce `pendingArrivals` in `Settings` here and store pending
  arrival provider IDs in it, writing the ID
  atomically when the announced backfill completes. Rebuild leaves that setting intact;
  `dismissArrival` removes the ID and records the dismissal atomically. Verify persistence across
  rebuild and reload with `undismissedArrivalSurvivesRebuild`.

- [ ] **Step 1: Write the failing tests.**
  ```swift
  @Test func providerRebuildLeavesOtherUnitsUntouched()
  @Test func globalRebuildRebuildsEveryUnit()
  @Test func rebuildDuringOtherBackfillKeepsBothCorrect()
  @Test func providerAddedWrittenOnce()
  @Test func rebuildAllNamesEveryProvider()
  @Test func providerAddedAndRebuiltCopy()

  ```
  Also:
  - extend `SettingsTests.settingKeyNamesAreStableAndDistinct` with `providerRebuildRequests`;
  - extend `PanelViewTests.actionsNeverCreateTheDatabase` to call `requestRebuild(provider:)`.
- [ ] **Step 2: Run them and see them fail.** Run the focused command with
  `--filter 'CollectorRunTests|CopyTests|SettingsTests|PanelViewTests'`. Expect a FAIL or compile error.
- [ ] **Step 3: Implement.** Follow design §4 G3 for collector logging. The `discardForRebuild`
  doc comment lists what the per-provider and the global discards remove and keep.
- [ ] **Step 4: Run the focused command, then the full suite.** Expect PASS.

### Task 3: Rules per source and signal, and copy that names its provider (G2, G3, G6)

**Files:**
- Modify: `Sources/TelltaleCore/Plugins.swift`, `Sources/TelltaleCore/Rules/RuleEngine.swift`,
  `Sources/TelltaleCore/Rules/NotificationPolicy.swift`, `Sources/TelltaleCore/Rules/Copy.swift`,
  `Sources/TelltaleCore/Launchd/CollectorHealth.swift`, `Sources/Telltale/CollectorMonitor.swift`
  (its `CollectorHealth.evaluate` call), `Sources/TelltaleCore/Collector/CollectorRun.swift`,
  `Sources/TelltaleCore/Read/PanelSnapshot.swift`, `Sources/TelltaleCodex/CodexUsageSource.swift`.
- Modify: `Sources/TelltaleCore/Baseline/BaselineEngine.swift` and
  `Sources/TelltaleCore/Store/Store+Rules.swift` at the baseline acceptance, undo and connection-gap
  event writers. Pass the provider display name to those writers from their existing callers;
  do not rely on `RuleEngine`'s provider information reaching them implicitly.
- Test: `RuleEngineTests.swift`, `NotificationPolicyTests.swift`, `CopyTests.swift`, `CollectorHealthTests.swift`,
  `EventFeedTests.swift`, `PanelSnapshotTests.swift`, `CollectorRunTests.swift`,
  `Tests/Acceptance/AcceptanceServiceTests.swift`.

**Interfaces:**
- Produces:
  ```swift
  // Add these as UsageSource protocol requirements; provide the defaults in its extension.
  extension UsageSource {
      public var failureNoun: String { "turn" }                      // Claude: "request" (design §8.1)
      public var supportedRules: Set<RuleID> { Set(RuleID.allCases) }
  }
  extension RuleID { public var signal: Signal? }   // moved from PanelSnapshot.signal(for:)
  public struct RuleProviderInfo: Sendable {
      public var name: String; public var failureNoun: String
      public var signals: Set<Signal>; public var rules: Set<RuleID>; public var naming: any ModelNaming
  }
  public init(store: Store, baseline: BaselineEngine, calendar: Calendar, providers: [ProviderID: RuleProviderInfo])  // RuleEngine
  // NotificationPolicy.select and withheldFailureNotices gain `provider: RuleProviderInfo?` (nil for a status-source unit)
  public static func formatProblem(source: String, since: Date, calendar: Calendar) -> String
  public static func failedTurns(source: String, noun: String, count: Int, reasons: [String]) -> String
  ```
- Apply design §4 G2 and G6 when gating rules and naming provider events.
- `PanelSnapshot` prefixes `source.name` only when the text doesn't already start with
  "<name>: ". That covers bodies that fall back to `rule.title` and 0.1.1 event bodies without a
  prefix.
- `Copy.failedTurnReason(code:)` gains the normalized codes in design §5.5. The Claude failure ingestion task emits them.

- [ ] **Step 1: Write the failing tests.**
  ```swift
  @Test func unsupportedRuleNeitherFiresNorNotifies()
  @Test func undeclaredSignalsRuleNeitherFiresNorNotifies()
  @Test func providerNamedBodies()
  @Test func formatProblemNamesTheSource()
  @Test func claudeFailureReasons()
  @Test func clearedAndCatchUpBodiesArePrefixed()
  @Test func connectionGapAndBaselineEventsArePrefixed()
  @Test func formatProblemUsesTheSourcesName()
  @Test func alertNamesItsProviderOnce()

  ```
  Then update the existing tests whose expected copy is now provider-prefixed (design §4 G6). Find
  them with `rg -n 'turns failed|disconnect or retry|Prompt sizes|changed its log format|is back to usual' telltale/Tests`.
  This includes `PanelSnapshotTests.alertsNameProviderWhenSeveral`, whose single-source case now
  expects the prefix in the body.
- [ ] **Step 2: Run them and see them fail.** Run the focused command with
  `--filter 'RuleEngineTests|NotificationPolicyTests|CopyTests|CollectorHealthTests|EventFeedTests|PanelSnapshotTests|CollectorRunTests'`.
  Expect a FAIL.
- [ ] **Step 3: Implement.** The collector builds one `RuleProviderInfo` per source. Codex keeps
  the protocol defaults.
- [ ] **Step 4: Run the focused command, then the full suite (it includes acceptance's
  service tests).** Expect PASS.

### Task 4: Incident model filter and per-source default watched components (G7)

**Files:**
- Create: `Sources/TelltaleCore/Read/StatusSourceSummary.swift`.
- Modify: `Sources/TelltaleCore/Plugins.swift`, `Sources/TelltaleCore/Rules/RuleEngine.swift`
  (`incidents(_:at:)`), `Sources/TelltaleCore/Settings.swift`, `Sources/TelltaleCore/Collector/CollectorRun.swift`,
  `Sources/TelltaleOpenAIStatus/OpenAIStatusSource.swift`, `Sources/Telltale/Registry.swift`,
  `Sources/Telltale/SettingsView.swift` (`SettingsModel` takes status summaries; `setWatched`),
  `Tests/Snapshots/Snapshots.swift` and `Tests/Acceptance/SyntheticEnvironment.swift` (synthetic
  status summaries).
- Test: `RuleEngineTests.swift`, `CollectorRunTests.swift`, `SettingsTests.swift`,
  `Tests/TelltaleAppTests/SettingsViewTests.swift`.

**Interfaces:**
- Produces:
  ```swift
  // Add these as protocol requirements, with these extension defaults, so existential calls dispatch to implementations.
  extension ModelNaming { public func incidentTitleIsModelSpecific(_ title: String) -> Bool { false } }
  extension StatusSource { public var defaultWatchedComponents: [String] { [] } }   // OpenAI: SettingKey.watchedComponents' current default list, moved here
  public struct StatusSourceSummary: Sendable, Equatable { public var id: String; public var displayName: String; public var defaultWatchedComponents: [String] }
  extension Settings { public static func defaultWatchedComponents(_ sources: [StatusSourceSummary]) -> [String] }  // union, registry order
  extension SettingKey where Value == [String]? { public static var watchedDefaultsApplied: SettingKey<[String]?> }  // nil reads as ["openai"]
  public func watchedComponents(sources: [StatusSourceSummary]) throws -> [String]   // Store: stored list, else the union default
  func applyWatchedDefaults(sources: [StatusSourceSummary]) throws                   // Store, in prepareBackfill
  static func statusSummaries() -> [StatusSourceSummary]                             // Registry
  ```
- Implement watched defaults and incident relevance per design §4 G7 and §6.3.

- [ ] **Step 1: Write the failing tests.** Use a synthetic `ModelNaming`.
  ```swift
  @Test func watchedComponentSkipsAnotherModelsIncident()
  @Test func watchedComponentFiresOnceTheNamedModelIsUsed()
  @Test func openIncidentEpisodeSurvivesUseRollingOff()
  @Test func modelFreeTitleStillFiresOnWatchedComponent()
  @Test func defaultNamingLeavesIncidentsUnchanged()
  @Test func storedWatchedListGainsClaudeCodeOnce()
  @Test func freshInstallUncheckIsKept()
  @Test func defaultWatchedIsTheUnionOfSources()

  ```
  Extend `settingKeyNamesAreStableAndDistinct` with `watchedDefaultsApplied`.
- [ ] **Step 2: Run them and see them fail.** Run the focused command with
  `--filter 'RuleEngineTests|CollectorRunTests|SettingsTests|SettingsViewTests'`. Expect a FAIL.
- [ ] **Step 3: Implement.** The collector and the app both read the watched list through
  `watchedComponents(sources:)`. No caller reads `SettingKey.watchedComponents.defaultValue` any
  more; check with `rg -n 'watchedComponents.defaultValue' telltale/Sources`.
- [ ] **Step 4: Run the focused command, then the full suite.** Expect PASS.

### Task 5: Compaction records and the Context compactions rule (G8)

**Files:**
- Modify: `Sources/TelltaleCore/Records.swift`, `Sources/TelltaleCore/Plugins.swift`,
  `Sources/TelltaleCore/Store/Schema.swift`, `Sources/TelltaleCore/Store/Store.swift`,
  `Sources/TelltaleCore/Store/Store+Ingest.swift`, `Sources/TelltaleCore/Settings.swift`,
  `Sources/TelltaleCore/Rules/RuleEngine.swift`, `Sources/TelltaleCore/Rules/NotificationPolicy.swift`,
  `Sources/TelltaleCore/Rules/Copy.swift`, `Sources/TelltaleCore/Read/EventFeed.swift` (`kind(_:)`),
  `Sources/TelltaleCore/Collector/CollectorRun.swift` (ingest; the per-provider discard of the per-provider Rebuild task),
  `Sources/TelltaleCore/Collector/Retention.swift`, `Sources/Telltale/ModelView.swift` (`kindLabel`),
  `Sources/Telltale/SettingsView.swift` (`SettingsRule` and `RuleParameter` cases; the schema-wait
  message), `Sources/Telltale/UserActions.swift`.
- Test: `RecordsTests.swift`, `StoreTests.swift`, `IngestStoreTests.swift`, `SettingsTests.swift`,
  `RuleEngineTests.swift`, `CopyTests.swift`, `RetentionTests.swift`, `CollectorRunTests.swift`,
  `EventFeedTests.swift`, `Tests/TelltaleAppTests/SettingsViewTests.swift`.

**Interfaces:**
- Produces:
  ```swift
  public enum CompactionTrigger: String, Sendable, Codable { case auto, manual }
  public struct CompactionRecord: Sendable, Equatable, Hashable, Codable {
      public var provider: ProviderID; public var lineID: String   // the line's uuid: copies across files share it
      public var sessionID: String; public var agentID: String?; public var at: Date
      public var trigger: CompactionTrigger; public var tokensBefore: Int; public var tokensAfter: Int?
      public var duration: TimeInterval?; public var precomputed: Bool
  }
  public var compactions: [CompactionRecord]   // IngestBatch; init parameter defaults to []
  public func upsert(compactions: [CompactionRecord]) throws -> Int
  public func compactions(provider: ProviderID, in range: ClosedRange<Date>) throws -> [CompactionRecord]  // [] when schemaVersion < 2
  public var schemaVersion: Int { get }   // Store
  case compactions   // RuleID; title "Context compactions"; signal .load
  public struct CompactionRule: Sendable, Equatable, Hashable, Codable { public var enabled: Bool; public var count: Int; public var windowMinutes: Int; public var notify: Bool; public var notifyOnClear: Bool }
  public var compactions: CompactionRule   // RuleSettings; defaults per design §7.3
  public static func compactionsFired(count: Int, windowMinutes: Int, blocked: TimeInterval?) -> String
  public static func compactionsCleared(windowMinutes: Int) -> String
  public static let settingsAfterUpgrade: String   // shown when an app write meets an older schema
  ```
- **Schema.** Follow design §7.3. Index `compactions` on `(provider, at)` and run each
  applicable migration exactly once.
- Follow ruling R27 and `Store.open` for migration. Map older-schema app-write errors to
  `Copy.settingsAfterUpgrade` in Settings and Data.
- **Decoding.** `RuleSettings.init(from:)` decodes `compactions` with `decodeIfPresent`,
  defaulting to `RuleSettings.defaults.compactions`. `validationErrors` rejects `count < 1` and
  `windowMinutes < 1`.
- Update the rules per source task's `UsageSource.supportedRules` default to exclude `.compactions`, preserving
  existing sources' behavior; the Claude usage source task's Claude source explicitly opts in.
- Implement the compaction rule and copy per design §7.3. Use
  `EpisodeMachine(firePoints: 1, clearPoints: 1, windowMinutes: 0, color: .amber)`,
  scope `*`, peak count as worst value and earliest counted record as onset.

- [ ] **Step 1: Write the failing tests.**
  ```swift
  @Test func version1DatabaseMigratesToVersion2()
  @Test func readOnlyVersion1ReadsNoCompactions()
  @Test func appWriteOnVersion1WaitsForCollector()
  @Test func compactionsDeduplicateByLineID()
  @Test func storedRulesWithoutCompactionsKeepTheirValues()
  @Test func compactionValidation()
  @Test func compactionsFireAtTwoAutomaticInTheWindow()
  @Test func compactionsNeedTheRuleAndTheSignal()
  @Test func compactionsCopy()
  @Test func compactionsPruneWithResponses()
  @Test func providerRebuildDiscardsItsCompactions()
  @Test func compactionEventsHaveAFeedKind()

  ```
  Then update these existing `StoreTests` for version 2 (design §7.3, G8):
  - `readWriteOpenCreatesWALDatabaseAtVersion1`, renamed `…AtCurrentVersion`, expects 2 and the
    compactions table;
  - `concurrentFirstOpensMigrateOnce` expects 2;
  - `openRefusesANewerSchema` and `existingReadWriteOpenNeverCreatesOrMigrates` use
    `Schema.currentVersion + 1` as "newer". The latter keeps version 0 throwing `notInitialized`,
    and gains version 1 throwing `unsupportedSchemaVersion(1)`.
- [ ] **Step 2: Run them and see them fail.** Run the focused command with
  `--filter 'StoreTests|IngestStoreTests|SettingsTests|SettingsViewTests|RuleEngineTests|CopyTests|RetentionTests|CollectorRunTests|EventFeedTests'`.
  Expect a FAIL.
- [ ] **Step 3: Implement.** Update exhaustive switches over `RuleID` for `.compactions` and
  check compiler diagnostics. The Rules section gets `count` and
  `windowMinutes` parameters.
- [ ] **Step 4: Run the focused command, then the full suite.** Expect PASS.

### Task 6: Status plumbing in core, and the Statuspage source (G5)

**Files:**
- Create: `Sources/TelltaleCore/Status/HTTPTransport.swift`. It takes `HTTPTransport`,
  `URLSessionTransport` and `StatusError` from `Sources/TelltaleOpenAIStatus/StatusClient.swift`,
  plus the 2xx check from `StatusClient.body(of:)` as
  `extension HTTPTransport { public func body(of url: URL) async throws -> Data }`.
- Create: `Sources/TelltaleCore/Status/RSSFeed.swift`: `RSSFeed.items(_ data: Data) throws -> [RSSItem]`,
  moved from `StatusDecoding.rss` and `RSSFallback.swift`.
- Modify: `Sources/TelltaleOpenAIStatus/*`, to call the moved code.
- Modify: `Package.swift`:
  - library and target `TelltaleStatuspage` (depends on `TelltaleCore`);
  - test target `TelltaleStatuspageTests` with `.copy("Fixtures")`;
  - add the target to the dependencies of `Telltale` and `TelltaleIntegrationTests`.
- Create: `Sources/TelltaleStatuspage/StatuspageSource.swift`, `StatuspageDecoding.swift`.
- Create: `Tests/TelltaleStatuspageTests/StatuspageSourceTests.swift`, and under `Fixtures/`:
  `summary_quiet.json`, `summary_incident.json`, `incident_detail.json`,
  `incident_no_affected.json`, `history.rss`, `error_page.html` and `README.md`. All are
  synthetic, shaped like design §6, with invented titles and ids.
- Test: `Tests/TelltaleOpenAIStatusTests/StatusDecodingTests.swift`.

**Interfaces:**
- Produces:
  ```swift
  public struct StatuspageSource: StatusSource {
      public init(id: String, displayName: String, baseURL: URL, transport: any HTTPTransport, defaultWatchedComponents: [String])
  }
  ```
- Requests and mapping follow design §6.1–§6.2.
- ISO 8601 parsing uses the Claude usage source task's `ISO8601Time.date(_:)`. If this task lands first, create that
  helper here instead, and the Claude usage source task consumes it.

- [ ] **Step 1: Move the plumbing.**
  - `StatusDecodingTests`' calls to `StatusDecoding.rss` become `RSSFeed.items`, a rename with no
    behaviour change.
  - Run the full suite. Expect PASS.
- [ ] **Step 2: Write the failing tests.** Use a fake transport that records requested URLs.
  ```swift
  @Test func quietSummaryHasComponentsAndNoIncidents()
  @Test func newIncidentFetchesItsDetailOnce()
  @Test func unchangedKnownIncidentSkipsDetail()
  @Test func resolvedIncidentMissingFromSummaryIsFetched()
  @Test func majorOutageNormalizesToFullOutage()
  @Test func updateWithoutAffectedComponentsFallsBack()
  @Test func summaryFailureFallsBackToRSS()
  @Test func htmlErrorPageMarksUnavailable()

  ```
- [ ] **Step 3: Run them and see them fail.** Run the focused command with
  `--filter StatuspageSourceTests`. Expect a compile failure.
- [ ] **Step 4: Implement.** Follow the structure of `OpenAIStatusSource.fetch(known:)`; reuse
  the moved core types.
- [ ] **Step 5: Run the focused command, then the full suite.** Expect PASS.

### Task 7: Claude usage source: files, responses, cursor and naming (G4)

**Files:**
- Modify: `Sources/TelltaleCore/Paths.swift` with the Claude roots per design §5.1 and
  `init(home:codexHome:claudeHome:)`.
- Modify: `Sources/TelltaleCore/Records.swift` (`ProviderID.claude`), `Sources/TelltaleCore/Plugins.swift`
  (add `UsageSource.dataFolder: URL` as a protocol requirement; Codex returns `codexHome`).
- Create: `Sources/TelltaleCore/Util/ISO8601Time.swift` (`date(_ text: String) -> Date?`, with and
  without fractions) and `Sources/TelltaleCore/Util/LineReader.swift` (`completeLines(of:from:_:) throws -> Int`).
  Both move existing code: `RolloutParser.date` and `RolloutParser.completeLines`, and
  `StatusDecoding.date`. Codex, the OpenAI source and Claude then share one copy of each.
  Preserve `RolloutParser.completeLines` error propagation so read failures do not advance the cursor.
- Create: `Sources/TelltaleClaude/ClaudeUsageSource.swift`, `TranscriptDiscovery.swift`,
  `TranscriptParser.swift`, `ClaudeCursor.swift`, `ClaudeModelNames.swift`.
- Modify: `Package.swift`:
  - library and target `TelltaleClaude` (depends on `TelltaleCore`);
  - test target `TelltaleClaudeTests` with `Fixtures`;
  - add `TelltaleClaude` to the dependencies of `Telltale` and `TelltaleIntegrationTests`.
- Create: `Tests/TelltaleTestSupport/TranscriptBuilder.swift` (design §9 ids and placeholder),
  `Tests/TelltaleClaudeTests/{ClaudeUsageSourceTests,TranscriptParserTests,ClaudeModelNamesTests}.swift`,
  `Tests/TelltaleClaudeTests/Fixtures/README.md`.
- Test: `Tests/TelltaleCoreTests/ReleaseTests.swift` (the paths tests live there), and
  `Tests/TelltaleCodexTests/RolloutParserTests.swift` (unchanged; it must still pass after the
  move).

**Interfaces:**
- Produces:
  ```swift
  public struct ClaudeUsageSource: UsageSource {
      public init(roots: [URL])   // Registry passes [paths.claudeHome] + [paths.claudeConfigRoot] when it exists
      // identity and rules per design §5; dataFolder roots[0]
  }
  public struct ClaudeModelNames: ModelNaming   // displayName, incidentTitle, incidentTitleIsModelSpecific per design §7.1
  struct ClaudeCursor: Codable { var files: [String: FileCursor] }   // key "<root index>/<path relative to that root's projects/>"
  ```
- Parsing follows design §5.1–§5.4 and §5.8; `FileCursor` also stores the root index.

- [ ] **Step 1: Move the shared helpers.** Run the full suite. Expect PASS, with the
  Codex and OpenAI suites unchanged.
- [ ] **Step 2: Write the failing tests.** Every fixture comes from `TranscriptBuilder` in a
  `ScratchDirectory`.
  ```swift
  @Test func displayNames()
  @Test func titleVersionBoundary()
  @Test func allModelsPhrasesMatchAnyModel()
  @Test func modelSpecificTitles()
  @Test func multiLineMessageTakesLargestOutputAndFinalUsage()
  @Test func startIsLatestUserLineBetweenResponses()
  @Test func startFallsBackToPreviousEnd()
  @Test func firstResponseWithoutStartIsDropped()
  @Test func fastModeKeysAsFastTier()
  @Test func missingEffortIsNil()
  @Test func serverToolUseIsExcludedAndCounted()
  @Test func contentNeverReachesRecords()
  @Test func largeAttachmentLineIsNotDecoded()
  @Test func partialTrailingLineWaits()
  @Test func incompleteMessageResumesNextRun()
  @Test func replacedFileRereads()
  @Test func subagentFilesHaveTheirOwnSession()
  @Test func copiesAcrossFilesShareResponseIDs()
  @Test func twoRootsDontCollide()
  @Test func oldFileWithoutCursorIsSkippedOnBackfill()
  @Test func missingProjectsIsNotSetUp()
  @Test func claudeConfigDirOverrides()

  ```
- [ ] **Step 3: Run them and see them fail.** Run the focused command with
  `--filter 'TelltaleClaudeTests|ReleaseTests'`. Expect a compile failure.
- [ ] **Step 4: Implement.** Read with `LineReader.completeLines` from the cursor offset;
  follow design §§5.2 and 5.8 for decoding and cursor state.
- [ ] **Step 5: Run the focused command, then the full suite.** Expect PASS.

### Task 8: Claude failures, retries, usage limit, compactions and format drift

**Files:**
- Modify: `Sources/TelltaleClaude/TranscriptParser.swift`, `ClaudeUsageSource.swift`, `ClaudeCursor.swift`.
- Test: `Tests/TelltaleClaudeTests/TranscriptParserTests.swift`, `ClaudeUsageSourceTests.swift`.

**Interfaces:**
- Consumes:
  - the compaction records and rule task's `CompactionRecord`, keyed by the line `uuid`;
  - the rules per source task's normalized failure codes.
- Produces: `IngestBatch` contents per design §5.5 (failures and retries), §5.6 (usage limit),
  §5.7 (format drift and `sourceVersion`) and §5.9 (compactions).
- A Claude `FailedTurnRecord` has `startedAt` = the error line's time and `completedAt` = the same
  time **(plan call: the line records one instant)**.

- [ ] **Step 1: Write the failing tests.**
  ```swift
  @Test func retryLinesBecomeRetryEvents()
  @Test func exhaustedRetriesEndInOneFailedRequest()
  @Test func eachProviderSideErrorClassMapsToItsCode()
  @Test func syntheticErrorCopiesDedupeByUUID()
  @Test func clientErrorsAreCountedNotRecorded()
  @Test func rateLimitBecomesFullUsageSnapshot()
  @Test func compactBoundaryBecomesCompaction()
  @Test func compactBoundaryWithoutTriggerIsSkipped()
  @Test func usageMissingIsFormatProblem()
  @Test func noParsableTimestampIsFormatProblem()
  @Test func recentFilesOutsideLayoutAreFormatProblem()
  @Test func newestVersionIsSourceVersion()

  ```
- [ ] **Step 2: Run them and see them fail.** Run the focused command with
  `--filter TelltaleClaudeTests`. Expect a FAIL.
- [ ] **Step 3: Implement.** Decode in the same pass as responses, following design §5.5.
- [ ] **Step 4: Run the focused command, then the full suite.** Expect PASS.

### Task 9: Register Claude, and run the providers together

**Files:**
- Modify: `Sources/Telltale/Registry.swift`. Add the sources per design §5 and §6.1, using
  `defaultWatchedComponents` from design §6.3. Give `SourceSummary` `dataFolder` and
  `failureNoun`.
- Modify: `Sources/TelltaleCore/Read/PanelSnapshot.swift`. The new `SourceSummary` fields get
  defaults consistent with the usage-source protocol, so existing initializers compile.
- Modify: `Tests/ReleaseChecks/check_test_isolation.sh` and `test_check_test_isolation.sh`. Add
  the patterns `~/\.claude` and `\.config/claude`, and regression cases for them.
- Modify: `Tests/TelltaleTestSupport/TestPaths.swift`, `Tests/Acceptance/SyntheticEnvironment.swift`
  (a synthetic Claude home).
- Modify: `README.md`, "How the collector runs", per design §11.
- Test: `Tests/TelltaleAppTests/RegistryTests.swift`, `Tests/TelltaleIntegrationTests/CollectorIntegrationTests.swift`.

**Interfaces:**
- Consumes: everything above.
- Produces: the registry order Codex then Claude. Sidebar groups and Providers rows follow it.

- [ ] **Step 1: Write the failing tests.**
  ```swift
  @Test func usageSourcesReadTheInjectedClaudeHome()
  @Test func configRootIsUsedOnlyWhenItExists()
  @Test func statusIDsDifferFromProviderIDs()
  @Test func statusSummariesCarryDefaults()
  @Test func codexAndClaudeTogether()
  @Test func statusFetchDoesntResetClaudeFormatSince()
  @Test func claudeHomeAloneWorks()
  @Test func claudeAbsentLeavesCodexUntouched()
  @Test func oneStatusSourceDownLeavesTheOtherEvaluated()

  ```
  Also add an isolation regression: a fixture Swift test mentioning either new pattern fails the
  check.
- [ ] **Step 2: Run them and see them fail.** Run the focused command with
  `--filter 'RegistryTests|CollectorIntegrationTests'`, then run
  `Tests/ReleaseChecks/test_check_test_isolation.sh`. Expect a FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Expect PASS.

### Task 10: Naming carryover in the panel, sidebar, dashboard and Events

**Files:**
- Create: `Sources/TelltaleCore/Read/DisplayNames.swift`.
- Modify: `Sources/TelltaleCore/Read/PanelSnapshot.swift` (provider groups, and rows hidden while
  a provider's backfill is unfinished), `Sources/Telltale/PanelView.swift`,
  `Sources/Telltale/DashboardView.swift`, `Sources/Telltale/ModelView.swift`,
  `Sources/TelltaleCore/Rules/Copy.swift` (the usual explanation), `Sources/TelltaleCore/Read/EventFeed.swift`.
  Follow design §§8.1 and 8.3.
- Modify: `Tests/Snapshots/Snapshots.swift` for the naming scenes in design §10. Raise the PNG count in its `pngs.count`
  guard, in `Tests/ReleaseChecks/check_harnesses.sh`'s panel and dashboard counts, and in
  `README.md`'s snapshot description by the scenes added.
- Test: `Tests/TelltaleCoreTests/DisplayNamesTests.swift` (new), `PanelSnapshotTests.swift`,
  `EventFeedTests.swift`, `Tests/TelltaleAppTests/PanelViewTests.swift`, `ModelViewTests.swift`.

**Interfaces:**
- Produces:
  ```swift
  public enum DisplayNames {
      /// Names for ids shown together; colliding names gain the part of the id that differs (design §8.1).
      public static func disambiguated(_ ids: [String], naming: any ModelNaming) -> [String: String]
  }
  ```
- Update model-name call sites in `PanelSnapshot`, `EventFeed`, the sidebar and `RuleEngine`
  messages. Find them with
  `rg -n 'displayName\(model:' telltale/Sources/TelltaleCore/Read telltale/Sources/Telltale telltale/Sources/TelltaleCore/Rules`.

- [ ] **Step 1: Write the failing tests.**
  ```swift
  @Test func collidingNamesGainTheDifference()
  @Test func distinctNamesAreUnchanged()
  @Test func twoProvidersGroupWithProviderLines()
  @Test func backfillingProviderHasNoRows()
  @Test func longNameFitsWithoutTruncation()
  @Test func claudeMissingEffortReadsNotRecorded()
  @Test func failureLegendUsesProviderNoun()
  @Test func collidingModelsAreDisambiguatedInEvents()
  ```
- [ ] **Step 2: Run them and see them fail.** Run the focused command with
  `--filter 'DisplayNamesTests|PanelSnapshotTests|PanelViewTests|ModelViewTests|EventFeedTests'`.
  Expect a FAIL.
- [ ] **Step 3: Implement.** Follow design §8.1.
- [ ] **Step 4: Run the full suite, then the snapshot command.** Expect PASS.
  Inspect every printed PNG: names unclipped, provider lines present, the dimmed state readable in
  light and dark themes.

### Task 11: Settings: Providers section, per-provider Rebuild, Rules and checklist

**Files:**
- Create: `Sources/TelltaleCore/Read/ProviderSummary.swift`.
- Modify: `Sources/Telltale/SettingsView.swift` (Providers section and confirmation per design §8.3), `Sources/TelltaleCore/Rules/Copy.swift`.
- Modify: `Tests/Snapshots/Snapshots.swift` for the Providers scenes in design §10; raise the counts as the naming carryover task does.
- Modify: `README.md`, the Settings description.
- Test: `Tests/TelltaleCoreTests/ProviderSummaryTests.swift` (new), `CopyTests.swift`,
  `Tests/TelltaleAppTests/SettingsViewTests.swift`.

**Interfaces:**
- Consumes: the per-provider Rebuild task's `requestRebuild(provider:)` and `rebuildConfirmation(days:providers:)`.
- Produces:
  ```swift
  public struct ProviderSummary: Sendable, Equatable {
      public enum State: Sendable, Equatable { case normal, notSetUp(String), formatProblem(since: Date), backfilling(started: Date), rebuildRequested(at: Date) }
      public var provider: ProviderID; public var name: String; public var state: State
      public var sourceVersion: String?; public var lastIngestAt: Date?; public var oldestResponse: Date?
      public var lastBackfillFinished: Date?; public var dataFolder: URL?
      public static func load(store: Store, sources: [SourceSummary]) throws -> [ProviderSummary]
  }
  ```
  State precedence, first match wins: rebuild requested, backfilling, format problem, not set up,
  normal.
- Copy and layout follow design §8.3 and option B of the options mockup. The tests below hold the
  exact strings.
- **Confirmation.** Follow `confirmUndo` (commit 0e9461f) for carrying the presented provider
  into the action, and use the `canRebuild` gate.

- [ ] **Step 1: Write the failing tests.** Use a fixed calendar and a synthetic configuration folder.
  ```swift
  @Test func stateLines()
  @Test func factLines()
  @Test func providerRebuildConfirmation()
  @Test func statePrecedence()
  @Test func providerRebuildStoresOnlyThatProvider()
  @Test func providerTravelsWithTheAlert()
  @Test func rebuildDisabledWhileBackfilling()
  @Test func rebuildAllUsesGlobalRequest()
  @Test func compactionsRuleRowEditsAndValidates()
  ```
- [ ] **Step 2: Run them and see them fail.** Run the focused command with
  `--filter 'ProviderSummaryTests|CopyTests|SettingsViewTests'`. Expect a FAIL.
- [ ] **Step 3: Implement.** `SettingsModel` loads `ProviderSummary` alongside the rules. The
  section uses the existing Settings tokens and row styles; no new colours.
- [ ] **Step 4: Run the full suite, then the snapshot command.** Expect PASS.
  Inspect the Providers PNGs in light and dark themes.

### Task 12: Arrival note, Claude Workload readouts, and release

**Files:**
- Modify: `Sources/TelltaleCore/Read/PanelSnapshot.swift` (`arrivals`), `Sources/Telltale/PanelView.swift`,
  `Sources/Telltale/UserActions.swift` (`dismissArrival`), `Sources/TelltaleCore/Settings.swift`
  (`dismissedArrivals`), `Sources/TelltaleCore/Read/Workload.swift`, `Sources/Telltale/ModelView.swift`,
  `Sources/TelltaleCore/Rules/Copy.swift` (the arrival text is built here, using its private
  `list` helper).
- Carry each source's `supportedRules` through `SourceSummary` and the registry into
  `DashboardView` and `Workload.load`; update synthetic summaries and all callers. Verify that a
  source without the compactions rule yields a nil readout with `unsupportedCompactionsAreHidden`.
- Modify: `Tests/Snapshots/Snapshots.swift` for the arrival scene in design §10; raise the counts as the naming carryover task does.
- Release changes:
  - `Sources/TelltaleCore/Release.swift` (`version`);
  - `Resources/Info.plist` (`CFBundleShortVersionString`, and `CFBundleVersion` + 1);
  - `README.md` (version line, Native acceptance rows for the release, "Rule replay against real
    data");
  - the Telltale entry of the root `CLAUDE.md`/`AGENTS.md` Validation Matrix (the snapshot count
    and scenes).
- Test: `PanelSnapshotTests.swift`, `WorkloadTests.swift`, `SettingsTests.swift`,
  `Tests/TelltaleAppTests/PanelViewTests.swift`, `StatusPanelTests.swift`, `ModelViewTests.swift`,
  `Tests/TelltaleCoreTests/ReleaseTests.swift`.

**Interfaces:**
- Produces:
  ```swift
  public struct ArrivalNote: Sendable, Equatable { public var provider: ProviderID; public var text: String; public var firstModel: String? }
  public var arrivals: [ArrivalNote]   // PanelSnapshot: completed, undismissed arrivals, including across rebuilds
  extension SettingKey where Value == [String] { public static var dismissedArrivals: SettingKey<[String]> }  // default []
  extension SettingKey where Value == [String] { public static var pendingArrivals: SettingKey<[String]> }  // default []
  func dismissArrival(provider: ProviderID) throws   // UserActions; follow the arrival persistence contract in the per-provider Rebuild task
  public static func arrival(name: String, days: Int, readyModels: [String]) -> String
  // Workload gains:
  public struct CompactionReadout: Sendable, Equatable { public var lastThreeHours: Int; public var blocked: TimeInterval; public var latestPoint: Int? }
  public var compactions: CompactionReadout?   // nil for a provider that declares no compaction rule
  public struct LimitReached: Sendable, Equatable { public var at: Date; public var resetsAt: Date? }
  public var limitReached: LimitReached?        // design §5.6: only within 5 h of a 100% snapshot
  ```
- Note behaviour, buttons and ready models follow design §8.3.
- Replace Claude's `usageLimit` readout and compute `latestPoint` per design §§5.6 and 7.3.

- [ ] **Step 1: Write the failing tests.**
  ```swift
  @Test func arrivalShowsAfterAnnouncedBackfillFinishes()
  @Test func arrivalHiddenOnFreshInstall()
  @Test func dismissedArrivalStaysHiddenAfterReload()
  @Test func undismissedArrivalSurvivesRebuild()
  @Test func arrivalText()
  @Test func openProviderSelectsItsFirstModel()
  @Test func compactionReadouts()
  @Test func unsupportedCompactionsAreHidden()
  @Test func limitReachedOnlyForFiveHours()

  ```
  Also:
  - update `ReleaseTests.infoPlistMatchesRelease` for the release version;
  - extend `settingKeyNamesAreStableAndDistinct` with `pendingArrivals` and `dismissedArrivals`;
  - extend `actionsNeverCreateTheDatabase` with `dismissArrival`.
- [ ] **Step 2: Run them and see them fail.** Run the focused command with
  `--filter 'PanelSnapshotTests|WorkloadTests|SettingsTests|PanelViewTests|StatusPanelTests|ModelViewTests|ReleaseTests|CopyTests'`.
  Expect a FAIL.
- [ ] **Step 3: Implement, then bump every version declaration.** Check that the old version
  string remains only in history text (README results rows and the design docs):
  `rg -n '0\.1\.1' telltale --glob '!*.md'` must print nothing.
- [ ] **Step 4: Run the real-data replay.** It is manual, read-only and never committed.
  - Use the README's "Rule replay against real data" approach: the real engine, over Kevin's real
    `~/.claude` and `~/.codex`, in a private temporary home outside the repository.
  - Evaluate replay results against design §§3.4 and 7.3 and follow design §10.
  - Keep replay results outside the public repository, and remove the temporary home after review.
    Record only a synthetic or non-sensitive validation summary in the README, consistent with the
    repository's public-data rule.
- [ ] **Step 5: Run automated release validation.** Follow the Telltale README for the separate owner-run native acceptance gate.
  - the full suite, `make -C telltale release`, the snapshot command (inspect
    every PNG) and the acceptance command: all PASS.
  - The root `CLAUDE.md` Validation Matrix "Static deployment/fleet audit tooling" commands,
    including `tools/tests/deploy_telltale.test.mjs`. They are required because
    `tools/deploy_telltale.mjs`'s build inputs changed (the Telltale entry says so). All PASS.
  - `/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" telltale/build/release/Telltale.app/Contents/Info.plist`
    prints the new version.
