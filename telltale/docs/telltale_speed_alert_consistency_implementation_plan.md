# Telltale Implementation Plan: Consistent Speed Alerts

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans when authorized to implement this plan. Checkboxes track execution, not approval.

**Goal:** Give each model a consistent speed display: prevent new overlapping speed episodes, read panel numbers from the alert evaluation, and use matching speed-alert wording in each direction.

**Authority:** **Decisions** defines the proposed behavior; **Copy** defines its text. The tasks below implement those definitions.

**Grounding:** `4e825fe`. Before execution, check the named symbols against the checkout, read repository-root `README.md`, `agents.md`, `docs/lessons_learned.md` and `telltale/README.md`, and record working-tree status. Requirements and build setup are in `Package.swift` and README **Requirements** and **Build and test**.

Paths are relative to `telltale/` unless marked repository-root. Run Git commands from the repository root and build/test commands from `telltale/`. This document authorizes no implementation or Git operations.

## Grounding sources

Use these symbols to inspect the behavior this plan changes:

- Overlapping episodes: `EvaluationPass.speed` in `Sources/TelltaleCore/Rules/RuleEngine.swift` and `RuleEngineTests.bothDirectionsAreSeparateEpisodes` in `Tests/TelltaleCoreTests/RuleEngineTests.swift`.
- Alert wording: `PanelSnapshot.load` and `Store.latestAlertEvent` in `Sources/TelltaleCore/Read/PanelSnapshot.swift`.
- Row and chart windows: `PanelSnapshot.row`, `ModelDetail.Readout.lastHour` in `Sources/TelltaleCore/Read/ModelDetail.swift`, and `SpeedIndex.at` in `Sources/TelltaleCore/Rules/SpeedIndex.swift`.
- Usual keys: `UsualKey` in `Sources/TelltaleCore/Baseline/Usual.swift`; check its declaration before changing assumptions about effort or service tier.
- Product docs to amend: `docs/telltale_design_spec.md` and `docs/telltale_visual_design.md`, as specified in each task's **Update docs** checkbox.

## Decisions (defaults; the owner may override before execution)

- **Reversal:** At each evaluation point, step the direction with an open episode first, then the other direction. Use `Direction.allCases` order when no direction is uniquely open. If the first remains open after its step and the other fires, end the first at that point with `EpisodeRow.EndReason.reversed`, regardless of severity. If the first clears at that point, retain its clear and give the other its ordinary fired wording. Previously stored overlapping episodes get no migration; exercise their eventual clear or idle end in `legacyOverlappingSpeedEpisodesSettle`.
- **Silent end:** A reversed end writes no event and posts no notice. The replacement episode's fired event and fresh notice use the `…Reversed` copy. Its catch-up notice uses the ordinary `…CatchUp` copy. Keep the reversed episode out of the Events list; its replacement's fired event records the change of direction.
- **Not a clear:** Preserve `ShiftDetector.prompt`'s dismissal behavior in `Sources/TelltaleCore/Baseline/ShiftDetector.swift`: a reversed end must not release a Keep-as-abnormal dismissal.
- **Delivered notifications:** Leave already delivered notifications unchanged on reversal. This is a scope choice; this plan does not add collector-side removal. For a later change to that choice, inspect `NotificationPosting` in `Sources/TelltaleCore/Collector/CollectorRun.swift`, `PanelModel.acknowledge` in `Sources/Telltale/PanelView.swift` and `UserNotifier.removeDelivered(threadIDs:)` in `Sources/Telltale/UserNotifier.swift`.
- **Copy scope:** Apply **Copy** to speed-rule alerts. Keep `Copy.shiftPrompt`'s text unchanged.
- **Panel row source:** Set the row's tok/s and usual from `medianTPS` and `mixUsual` of `PanelSnapshot.row`'s existing `current` selection. When `current` is absent or `medianTPS` is nil, set each number to nil. Preserve the note-selection code in that method. This default deliberately permits a dash while a model remains active in the panel, including a new model or a newly used usual key; do not substitute the dashboard's readout or invent a usual. **Panel row states** below defines the regression fixtures that make the cost of this default reviewable.
- **Dashboard readout:** Preserve `ModelDetail.Readout.lastHour`'s behavior and label; give `ModelDetail.readoutWindow` its own constant when removing `PanelSnapshot.rateWindow`.
- **Alert rows:** Word an open Slower or Faster episode with `Copy.slowerOpen` or `Copy.fasterOpen`, from `episode.worstValue` and `episode.onset`, when the worst value is below 1 for Slower or above 1 for Faster and `SpeedIndex.percent` returns a representable percentage. Otherwise behave as `PanelSnapshot.load`'s existing event-body fallback does. Preserve event and notification bodies.
- **Release:** Set version `0.3.1` and `CFBundleVersion` `6`.
- **Branch:** When implementation is authorized, start from `main` on `codex/telltale-speed-alerts` unless the owner specifies another name. Push, PR, merge and deployment require their own authorization. Deployment runs from merged `main`.

## Global constraints

- **Public repository:** Use conspicuously synthetic fixtures. Keep owner activity and private evidence outside the checkout.
- **Isolation:** Follow `Tests/ReleaseChecks/check_test_isolation.sh`.
- **Tests:** A filtered run is `mkdir -p .build/tmp && TMPDIR="$PWD/.build/tmp/" tools/check_no_temp_leaks.sh swift test -Xswiftc -warnings-as-errors --filter '<pattern>'`. Finish each task with the full `make test` gate, and report failure output. Use filtered runs to diagnose, not replace the full suite.
- **Build-input validation:** At each task's verification gate, also run the applicable commands under repository-root `agents.md` **Static deployment/fleet audit tooling** from the repository root; require PASS.
- **Expectations:** Name each changed or replaced test and its reason in the handoff and, if requested, commit body. Preserve tests' original purpose when adjusting fixtures.
- **Commit boundaries:** If the owner requests commits, commit each task's named files separately under **Branch**, including this plan with **Speed episodes**. Follow repository instructions for staging review and commit messages.
- **Shared calculation:** Speed-index deviation percentages use `SpeedIndex.percent(_:)`, including the lasting-shift percentage calculation. Baseline acceptance and drift retain their own calculations in `BaselineEngine`.
- **Lessons:** During implementation, add dated entries to repository-root `docs/lessons_learned.md`, naming the regression tests.

## Copy

Sentence case; format times through `Copy.clock`. The templates are specified here because they are the new product text, rather than a description of existing copy.

| `Copy` member | Text |
|---|---|
| `slowerFired(model:percent:since:calendar:)` | `{model} is {percent}% slower than usual for prompts this size. Since {clock(since)}.` |
| `slowerReversed(model:percent:since:calendar:)` | `{model} is {percent}% slower than usual for prompts this size, after running faster. Since {clock(since)}.` |
| `slowerCatchUp(model:percent:since:calendar:)` | `{model} has been {percent}% slower than usual for prompts this size since {clock(since)}.` |
| `slowerEscalated(model:percent:)` | `{model} is now {percent}% slower than usual for prompts this size.` |
| `fasterFired(model:percent:since:calendar:)` | `{model} is {percent}% faster than usual for prompts this size. Check that output isn't shallower. Since {clock(since)}.` |
| `fasterReversed(model:percent:since:calendar:)` | `{model} is {percent}% faster than usual for prompts this size, after running slower. Check that output isn't shallower. Since {clock(since)}.` |
| `fasterCatchUp(model:percent:since:calendar:)` | `{model} has been {percent}% faster than usual for prompts this size since {clock(since)}.` |
| `slowerOpen(model:percent:since:calendar:)` | `{model} has been up to {percent}% slower than usual for prompts this size since {clock(since)}.` |
| `fasterOpen(model:percent:since:calendar:)` | `{model} has been up to {percent}% faster than usual for prompts this size since {clock(since)}. Check that output isn't shallower.` |

Verify model-name rewriting with `DisplayNames.speedText` in `Sources/TelltaleCore/Read/DisplayNames.swift` and the disambiguation tests specified under **Alert rows and release**.

## Speed episodes

**Files and implementation:**

- `Sources/TelltaleCore/Rules/EpisodeMachine.swift`: add engine-only `Transition.reversed` (the machine never returns it), and `public mutating func end() -> Bool`. Reuse `reset()`; return whether the machine was open.
- `Sources/TelltaleCore/Store/Store+Rules.swift`: add `EpisodeRow.EndReason.reversed = "reversed"`, documented by **Silent end** and **Not a clear**. Update the comment on `EventKind.ruleFired` to include this end reason.
- `Sources/TelltaleCore/Rules/SpeedIndex.swift`: add `public static func percent(_ index: Double) -> Int?`, moving the deviation expression from `EvaluationPass.speedContext`. Use `Int(exactly:)` after rounding; return nil for a non-finite input, overflowed calculation or unrepresentable integer. This checked result supports **Alert rows**' legacy fallback without an integer-conversion trap.
- `Sources/TelltaleCore/Baseline/ShiftDetector.swift`: route the median worst speed index for the same-direction run through `SpeedIndex.percent`, preserving median-before-rounding semantics and the existing no-result fallback. Keep dismissal behavior as specified in **Not a clear**.
- `Sources/TelltaleCore/Rules/RuleEngine.swift`:
  - Implement **Reversal** in `EvaluationPass.speed`, retaining the returned transitions from `step` to detect an actual fire. Determine the replacement copy from the opposite machine's state after its step, not merely from its state at the start of the point.
  - Give `speedContext` an `after reversed: Direction?` argument; apply **Silent end** when choosing its fired and catch-up messages. Consume the optional percentage with `index.flatMap(SpeedIndex.percent) ?? 0`.
  - Extract `step`'s episode-ending code for reuse by the reversal. For shared ending behavior, behave as `step`'s `.cleared, .idleEnded` branch and state-finalization code do. A reversal also calls `machine.end()` and records its outcome with `kind: nil` and empty failures.
  - Handle `.reversed` in each switch over `Transition`; message closures return `("", nil)` for it. `step`'s machine-transition switch must explicitly reject this engine-only case, rather than accidentally treating it as a clear.
  - Update the `RuleEngine` and `record` comments for **Silent end**.
- `Sources/TelltaleCore/Rules/NotificationPolicy.swift`: in `select`, handle `.reversed` as `.idleEnded`; in `catchUps`, count it as ended. Update the type comment for **Silent end**.
- `Sources/TelltaleCore/Read/EventFeed.swift`: update `FeedEvent.Kind.ended`, `EventFeed` and `Store.silentEpisodeEnds` comments for **Silent end**; retain the query's existing end-reason filter.
- `Sources/TelltaleCore/Rules/Copy.swift`: implement the speed members of **Copy**.

**Tests:** `Tests/TelltaleCoreTests/{RuleEngine,EpisodeMachine,SpeedIndex,NotificationPolicy,ShiftDetector,EventFeed,Copy}Tests.swift` (brace notation denotes the corresponding files). Also inspect each match from `rg -n 'Copy\.(slower|faster)|slower than usual|faster than usual' Tests` for changed expectations.

- [x] **Write the failing tests.** Use `RuleHarness`'s `seedUsual`, `run` and `evaluate` in `RuleEngineTests`:

| Test | Required assertion |
|---|---|
| `reversalEndsTheOppositeEpisode` | Replace `bothDirectionsAreSeparateEpisodes` on its fixture. Assert **Reversal** and **Silent end**, the ended and replacement episode IDs, and no remaining opposite open episode at subsequent evaluated points. |
| `fasterIsReversedBySlower` | Mirror that fixture, checking the invariant after each evaluated point. |
| `redSlowerEpisodeIsReversed` | Exercise **Reversal** after Slower reaches red. |
| `clearAtTheOppositeFireIsAClear` | Exercise the simultaneous-clear branch of **Reversal** in each direction. |
| `clearBeforeTheOppositeFireIsAClear` | Exercise a clear before the replacement fires. |
| `legacyOverlappingSpeedEpisodesSettle` | Seed rule state and episode rows with overlapping directions as the grounding implementation can persist; evaluate through their clear or idle end and check consistent stored state. |

In the corresponding test files add:

- `EpisodeMachineTests.endResetsAndReportsWhetherItWasOpen`: check an open machine, a closed machine with a partial streak, and repeated calls; no old streak survives `end()`.
- `SpeedIndexTests.percentIsTheRoundedDistanceFromUsual`: pin rounding and distance in each direction, including usual itself. Reuse the existing `speedContext` test expectations as grounding. Add `percentRejectsUnrepresentableValues` for non-finite inputs and finite values whose percentage cannot be converted to `Int`.
- `ShiftDetectorTests.typicalPercentRoundsAfterTakingTheMedian`: a same-direction run whose fractional deviations distinguish median-before-rounding from rounding each episode first; check the helper refactor preserves the existing result.
- `NotificationPolicyTests.reversedOutcomePostsNothing`: fresh reversed outcome with clear notices enabled.
- `NotificationPolicyTests.reversalInsideACatchUpPassPostsNoStaleNotice`: an episode fires and is reversed inside a stale gap; the replacement remains open. Assert **Silent end**'s catch-up behavior and exercise a fresh reversal separately.
- `ShiftDetectorTests.reversalDoesNotLiftAShiftDismissal`: extend the dismissal fixture from `keepAsAbnormalSuppressesUntilClearAndNewRun` with a reversed end and a later qualifying run. Check **Not a clear** and that an actual clear still releases the dismissal for a subsequent new run.
- `EventFeedTests.reversedEpisodeEndIsNotListed`: inspect the feed after reversal and retain its idle/rule-disabled end coverage.
- `CopyTests`: add a `CopyCase` for each member in **Copy**.

- [x] **Confirm failure.** Run the filtered command with `RuleEngineTests|EpisodeMachineTests|SpeedIndexTests|NotificationPolicyTests|ShiftDetectorTests|EventFeedTests|CopyTests`. Initially expect build failures for the added symbols. After the symbols compile, demonstrate the behavior tests fail against the old logic before completing the fix.
- [x] **Implement** the Files list, then verify under **Tests** and **Build-input validation**. Record changed expectations and command results.
- [x] **Update docs.** Amend spec §7.2 for **Reversal**, **Silent end**, **Delivered notifications** and **Not a clear**; §7.3's catch-up quote to match **Copy**; §8's lasting-shift bullet for **Not a clear**. Apply **Lessons**, **Expectations** and **Commit boundaries**.

## Panel numbers

**Files and implementation:**

- `Sources/TelltaleCore/Read/PanelSnapshot.swift`: implement **Panel row source** in `row(store:baseline:source:model:now:)`, remove its `ModelDetail.Readout.lastHour` call and `rateWindow`, and update the model-row type comment above `ArrivalNote`.
- `Sources/TelltaleCore/Read/ModelDetail.swift`: set `readoutWindow` to an independent `3_600` constant; update the `ModelDetail` and `Readout.lastHour` comments for **Dashboard readout**.
- `Tests/Acceptance/SyntheticEnvironment.swift`: preserve the Claude new-model fixtures in `twoProviders`, `arrival` and `claudeDashboard`; do not add numeric evaluation points to retain their old readout. Use the current seeded Codex evaluation points as the row-number source. If exercising a stored Claude point, derive it through `RuleEngine` from the scene's actual history. Validate these scenes in the acceptance service tests and snapshots.

**Panel row states:** Write these tests in `Tests/TelltaleCoreTests/PanelSnapshotTests.swift`. The note assertions are included here because preserving the note code alone does not demonstrate the visible cost of **Panel row source**.

| Test | Fixture and assertions |
|---|---|
| `rowMatchesTheSpeedReadingNotTheLastHour` | Fast then slow stretches; evaluate to the load point. Require non-nil point values, row values equal to that point, a matching terminal sparkline value, and a non-nil differing `ModelDetail.Readout.lastHour.tps`. |
| `rowKeepsNumbersWithThinButUsualMatchedResponses` | Below `SpeedIndex.minimumSamples` but at least one throughput-bearing response with a usual; load at the latest point. Require numeric row values and `Copy.thinData`. |
| `rowShowsADashWhenRecentResponsesHaveNoUsual` | A model past cold start uses an effort/tier or input bucket without a usual. After evaluation require a fresh `.thin` point with nil median, nil row numbers and `Copy.thinData`. |
| `rowShowsADashAfterTheResponseWindowEmpties` | Continue collecting after the last qualifying response leaves `SpeedIndex`'s window, before `RuleEngine.idleMinutes`. Require a newly written `.thin` point with nil median, nil row numbers and `Copy.thinData`. |
| `newModelShowsADashAndLearningNote` | A new model with throughput-bearing responses and no usable usual history. Require a fresh `.cold` point, nil row numbers and the learning note produced by `Copy.learning`. |
| `idleReadyModelShowsADashWithoutNote` | Fully ready baseline; continue evaluation past `RuleEngine.idleMinutes`, then past the final stored point's freshness limit, while the model remains within `PanelSnapshot.activeWindow`. Assert no new speed point was written after idleness, `current` is absent, row numbers nil and note nil. |
| `stalePointKeepsTheBaselineLearningNote` | A still-learning baseline; stop evaluation until `current` expires, keeping the model active. Require nil row numbers and the corresponding `Copy.learning` note. |
| `stalePointWithReadyBaselineHasNoNote` | The same collector-gap fixture with a ready baseline; nil row numbers and note nil. |

In `Tests/TelltaleCoreTests/ModelDetailTests.swift`, replace `panelRowShowsTheDashboardReadout` with the distinct-window test above; retain dashboard readout tests. Rework `PanelSnapshotTests.usualIsMixMatched` to place its response mix inside the latest point's speed window and evaluate through it, preserving its mix-matching assertions.

In `Tests/Acceptance/AcceptanceServiceTests.swift`, add `panelScenesUseStoredSpeedReadings`: load the affected scenes and compare Codex row values with their stored points; require Claude row numbers nil and a learning note. Also inspect each row-expectation match from `rg -n '\.tps|\.usual|models\.' Tests`; change expected values when the readout contract changes, and add evaluation only where the fixture's purpose requires a judged window.

- [x] **Confirm failure.** Run the filtered command with `PanelSnapshotTests|ModelDetailTests`. Demonstrate failures caused by the old last-hour row source; existing note behavior may already pass.
- [x] **Implement** the Files list, then verify under **Tests** and **Build-input validation**, including the acceptance service assertions.
- [x] **Update docs.** Amend spec §8's usual-number bullet for **Panel row source** and **Dashboard readout**, retaining mix matching; §9.1's panel-row line; the visual doc's **Panel** row annotation; README **Menu bar and panel**. Document the dash behavior using **Panel row states**. Apply **Lessons**, **Expectations** and **Commit boundaries**.

## Alert rows and release

**Files and implementation:**

- `Sources/TelltaleCore/Read/PanelSnapshot.swift`: implement **Alert rows** in `load`'s episode loop before the existing provider-prefix and `DisplayNames.speedText` passes. Use `source.naming.displayName(model: episode.scope)` and `SpeedIndex.percent(episode.worstValue)`. Update the alerts type comment and `Store.latestAlertEvent`'s comment for **Alert rows**.
- `Tests/Acceptance/SyntheticEnvironment.swift` and `Tests/Snapshots/Snapshots.swift`: add a `fasterAlerting` scene with an open Faster episode and a usable worst value, rendered in each appearance, and assert its text, blue lamp and row color. Preserve existing scene assertions. Extend the scene switches in `Tests/Acceptance/AcceptanceServiceTests.swift` and the renderer, and add acceptance service assertions for this scene's alert wording. Update the renderer's image-inventory checks/reports and `Tests/ReleaseChecks/check_harnesses.sh`'s expected panel image total for the expanded `Snapshots.states` inventory. Update the maintained inventories in README **Build and test** and repository-root `agents.md` **Validation Matrix**. The new scene is needed to inspect the longer Faster template; existing scenes remain in the renderer.
- Apply **Release** to `Sources/TelltaleCore/Release.swift`'s `TelltaleRelease.version`, `Resources/Info.plist`'s version/build fields, README **Purpose**, `Tests/TelltaleCoreTests/ReleaseTests.swift`'s `infoPlistMatchesRelease`, and the visual doc's panel footer. From the repository root, inspect `git grep -n '0\.3\.0' -- telltale` for other maintained declarations; preserve historical results and earlier plans.
- Inspect alert-text expectations in `Tests/TelltaleCoreTests/PanelSnapshotTests.swift`, `Tests/Acceptance/AcceptanceServiceTests.swift`, and `Tests/TelltaleAppTests/LiveStoreTests.swift` and `SystemEventsTests.swift`. Search `rg -n 'alerts.*text|alertText|slower than usual|faster than usual' Tests` for additional matches. Update contract-dependent text; use unusable worst-value fixtures only when the test's purpose is the fallback path (for example `alertNamesItsProviderOnce`).

Consumes the helpers and copy from **Speed episodes**.

- [ ] **Write the failing tests** in `PanelSnapshotTests`:

| Test | Required assertion |
|---|---|
| `speedAlertStatesItsWorstSinceOnset` | Use the real engine to fire Slower and worsen it without escalating. Require **Alert rows**, amber severity and unchanged fired-event wording. Mirror the worst-value rendering for Faster. |
| `reversedSpeedAlertIsNew` | Acknowledge a speed alert, then reverse it through the engine in each direction. Require the replacement alert's acknowledgement to be nil and its text/color to follow **Alert rows**. |
| `speedAlertWithoutAUsableWorstKeepsItsEventWording` | Exercise **Alert rows**' fallback boundary, wrong-direction and finite unrepresentable-percentage values for each speed rule. Check non-finite rejection in `SpeedIndexTests`; do not weaken storage validation to persist NaN. |

Keep `openLegacyAlertsDisambiguateModels` on its fallback path; add a worst-value-rendered alert with a colliding display name and require correct disambiguation. Preserve fallback and provider-prefix coverage.

- [ ] **Confirm failure.** Run the filtered command with `PanelSnapshotTests` and demonstrate event-body versus worst-value wording failures before implementing **Alert rows**.
- [ ] **Implement** the Files list, including **Release**.
- [ ] **Run release gates.** Apply the Telltale entries in repository-root `agents.md` **Validation Matrix**:
  - Complete **Tests** and **Build-input validation**.
  - `make release`: require a signed bundle satisfying **Release**.
  - `make snapshots`: inspect the rendered states for wrapping of **Copy**'s open-alert templates, **Panel numbers**' scene assertions and `fasterAlerting`. Follow `Tests/Snapshots/build.sh` for output and cleanup.
  - `make acceptance`: require PASS. Follow `Tests/Acceptance/build.sh` for output and cleanup.
- [ ] **Update docs.** Amend spec §9.1, visual doc **Panel** and **Copy rules**, `docs/mockups/telltale_mockups.html` panel alerts, and README **Menu bar and panel** for **Alert rows**. Add the native check below under README **Native acceptance** and mark it **Not yet run** under **Results**. Apply **Lessons**, **Expectations** and **Commit boundaries**.

## Native check after authorized deployment

Add this to README and run it only after **Branch**'s merge/deployment requirements are satisfied:

- Exercise a reversal and check **Reversal** and **Alert rows** in the panel.
- While loading at a fresh evaluation point, compare the row with its terminal sparkline value.
- Check the panel footer, dashboard sidebar and installed `Info.plist` against **Release**, including build-number help text.

Follow README **Native acceptance** for evidence and result recording.
