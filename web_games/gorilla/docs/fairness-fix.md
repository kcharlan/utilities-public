# Gorilla Fair Start Repair Plan

This document is an implementation plan only. It is intentionally split into isolated fixes so each one can be implemented and tested independently without destabilizing the page.

## Scope And Safety Rules

1. Only edit `/Users/example/source/utilities/web_games/gorilla/index.html`.
2. Implement exactly one fix at a time from this plan.
3. After each fix, run the smoke checks in this doc before moving to the next fix.
4. Do not combine refactors with behavior changes in the same fix.
5. Do not add recursive regeneration calls. Regeneration logic must remain bounded.

## Execution Tracking And Resume Protocol

### Status Legend

Use these prefixes on the tracker entries in this document:

1. `[ ]` means not started. No intended code from this fix should remain in the working tree.
2. `[~]` means in progress. The fix may be partially implemented or partially validated.
3. `✓` means implementation and validation complete. The fix passed acceptance criteria and per-fix smoke checks.

### How To Mark Status

1. Before touching code for a fix, change that fix line from `[ ]` to `[~]`.
2. Keep that fix as `[~]` while coding, refactoring, or debugging.
3. After code changes are done, run all per-fix smoke checks and the fix acceptance criteria.
4. Only if all checks pass, change the line from `[~]` to `✓`.
5. If checks fail, keep `[~]` while you rework, or set back to `[ ]` if you fully reverted the fix.
6. Never mark `✓` based on code review only. `✓` requires implementation plus successful validation.

### How To Interpret Status Safely

1. If all earlier fixes are `✓`, it is safe to start the next `[ ]` fix.
2. If any fix is `[~]`, treat the plan as paused on that fix. Do not start a later fix yet.
3. If a fix is `[ ]`, assume it has not been reliably applied even if some related code exists.
4. A `✓` fix is the baseline for future work. Later fixes should preserve that behavior.

### How To Resume Safely After A Pause

1. Open this file first and locate the first fix not marked `✓`.
2. If that fix is `[~]`, inspect the current code for partial edits in its listed edit targets.
3. Either finish and validate that same fix, or fully revert only that fix and reset it to `[ ]`.
4. Run per-fix smoke checks immediately after resuming work on `[~]` code.
5. Continue in order. Do not skip unresolved `[~]` fixes.
6. If you discover mixed changes from multiple fixes, split them before proceeding by reverting or separating commits so one fix can be validated at a time.

## Fix Status Tracker

Update these lines as you execute the plan:

1. `✓` Fix 1: Enforce A Strict “Validated Or Known-Good” Generation Contract
2. `✓` Fix 2: Make Validation Use The Same Gravity As The Upcoming Round
3. `✓` Fix 3: Validate Against The Actual Wind Envelope For The Active Wind Mode
4. `✓` Fix 4: Make Robustness Checks Wind-Aware
5. `✓` Fix 5: Align Validation Collision Priority With Runtime Collision Priority
6. `✓` Fix 6: Prevent “Simple Mode” From Reintroducing Major Blockers
7. `✓` Fix 7: Encode “Reasonable Shot” Requirements Explicitly
8. `✓` Fix 8: Unify Validation Flight Limits With Runtime Flight Limits

## Per-Fix Smoke Checks

Run these after each fix:

1. Load the page and confirm no console syntax/runtime errors on startup.
2. Click New Round or press `R` at least 10 times and confirm rounds regenerate normally.
3. Confirm gorillas remain on opposite sides and not side-by-side.
4. Fire at least one shot from each side and confirm turns advance.
5. Let AI play at least one round if opponent is AI.
6. Change gravity and wind settings, then regenerate, and confirm round still starts.

If any smoke check fails, revert only that fix and rework before proceeding.

## Fix 1: Enforce A Strict “Validated Or Known-Good” Generation Contract

### Objective
Prevent impossible starts from slipping through when generation retries fail.

### Current Risk
`attemptGorillaPlacement` currently returns an unvalidated map in its absolute fallback path.

### Edit Targets
`attemptGorillaPlacement`, `regenerateRound`, and nearby state setup in `/Users/example/source/utilities/web_games/gorilla/index.html`.

### Implementation Steps
1. Add a `lastKnownGoodLayout` state variable near `lastPlacement`.
2. Change `attemptGorillaPlacement` to return a structured result:
`{ ok: boolean, buildings, result, reason }`.
3. Ensure every success return path sets `ok: true` only after `validateLevel` passes.
4. Replace the current “absolute fallback uses last attempt anyway” path with `ok: false`.
5. In `regenerateRound`, handle `ok: false` by:
using `lastKnownGoodLayout` if available, otherwise using one deterministic emergency layout builder.
6. The deterministic emergency layout builder must be non-random and bounded. It must return the same fixed-safe skyline/placement each time and then be validated once.
7. On every successful validated generation, persist a deep copy into `lastKnownGoodLayout`.
8. Log a warning if fallback-to-lastKnownGood is used, but do not recurse and do not loop endlessly.

### Acceptance Criteria
1. No code path can start a round with a layout that failed validation.
2. Regeneration remains bounded and cannot enter an infinite loop.
3. Page startup and `R` key regeneration remain stable.

## Fix 2: Make Validation Use The Same Gravity As The Upcoming Round

### Objective
Eliminate stale-gravity validation mismatch.

### Current Risk
Validation runs before `state.gravity` is set for the new round.

### Edit Targets
`regenerateRound`, `attemptGorillaPlacement`, `validateLevel`, `checkDirection`, `simulateShot`, `checkRobustness`, `checkClearance`.

### Implementation Steps
1. At the top of `regenerateRound`, compute `const roundGravity = gravityLevels[settings.gravityLevel]`.
2. Pass `roundGravity` into `attemptGorillaPlacement`.
3. Thread `gravity` through `validateLevel` and subordinate check functions.
4. Update `simulateShot` and `checkClearance` signatures to accept a `gravity` parameter with default for compatibility.
5. Inside those functions, use the passed `gravity` instead of directly reading `state.gravity`.
6. Keep gameplay runtime physics unchanged by setting `state.gravity = roundGravity` as already done.
7. Verify no caller is left using old parameter order.

### Acceptance Criteria
1. Validation logic and round runtime use identical gravity for that round.
2. Toggling gravity and regenerating no longer validates under stale previous-round gravity.

## Fix 3: Validate Against The Actual Wind Envelope For The Active Wind Mode

### Objective
Ensure fair-start checks match the configured wind mode.

### Current Risk
Validation uses hardcoded `-15, 0, +15` regardless of active mode.

### Edit Targets
`validateLevel` and helpers that call `checkDirection`.

### Implementation Steps
1. Add a helper that returns validation wind samples from settings:
`off -> [0]`, `low -> [-15, 0, 15]`, `high -> [-30, -15, 0, 15, 30]`.
2. Deduplicate/sort sample values to avoid redundant checks.
3. In `validateLevel`, iterate sample winds for both firing directions.
4. Keep checks bounded and deterministic by iterating a fixed array only.
5. Preserve existing return contract (`true` only if all required checks pass).

### Acceptance Criteria
1. High-wind rounds are validated against high-wind extremes.
2. Wind-off mode no longer performs unnecessary windy validation.
3. No unbounded loops added.

## Fix 4: Make Robustness Checks Wind-Aware

### Objective
Ensure robustness checks evaluate the same wind context as the validated shot.

### Current Risk
`checkDirection` may validate a hit under override wind, then robustness is computed under zero wind.

### Edit Targets
`checkDirection`, `checkRobustness`, `checkClearance`.

### Implementation Steps
1. Add `wind` (and already-threaded `gravity`) parameters to `checkRobustness`.
2. In `checkDirection`, pass the same `overrideWind` used for the primary shot to robustness checks.
3. In `checkRobustness`, pass `wind` to each perturbed `simulateShot` call.
4. In `checkClearance`, apply `vx += wind * SIM_DT` instead of `vx += 0`.
5. Keep tolerance values unchanged for this fix to minimize blast radius.

### Acceptance Criteria
1. Robustness pass/fail reflects the same wind as the shot being validated.
2. No behavior regression in zero-wind mode.

## Fix 5: Align Validation Collision Priority With Runtime Collision Priority

### Objective
Remove simulation discrepancies between validation and actual gameplay.

### Current Risk
Validation checks building collision before gorilla collision, runtime does the opposite.

### Edit Targets
`simulateShot` and collision logic sections.

### Implementation Steps
1. In `simulateShot`, reorder checks so target-hit evaluation runs before building-hit evaluation.
2. Keep hitbox/radius math exactly the same values as runtime collision code.
3. Verify this function still returns deterministic `{ hit, reason }` objects.
4. Confirm no callers depend on the previous check ordering side-effect.

### Acceptance Criteria
1. Validation and runtime agree on edge cases where banana intersects both target and building in one step.
2. Regeneration success/failure decisions become more consistent with actual play.

## Fix 6: Prevent “Simple Mode” From Reintroducing Major Blockers

### Objective
Keep fallback/simple generation actually simple and playable.

### Current Risk
`enforceMidObstacle` can undo simple-mode openness by re-raising a middle blocker.

### Edit Targets
`placeGorillas`, `enforceMidObstacle`, and call sites from generation.

### Implementation Steps
1. Add a flag to placement flow indicating whether the skyline is simple-mode.
2. In simple-mode paths, either skip `enforceMidObstacle` or cap its effect to a low safe increment.
3. If capped behavior is chosen, document explicit cap constants near other skyline constants.
4. Keep non-simple behavior unchanged in this fix.
5. Verify fallback generation remains visually varied but does not create near-sealed trajectories.

### Acceptance Criteria
1. Simple-mode fallback increases validation pass rate.
2. Simple-mode still renders correctly and keeps gorillas separated.

## Fix 7: Encode “Reasonable Shot” Requirements Explicitly

### Objective
Make fairness criteria enforce practical, non-extreme solutions.

### Current Risk
A technically valid but impractical shot can still satisfy validation.

### Edit Targets
Validation-side shot selection and `checkDirection`.

### Implementation Steps
1. Add a validation-specific shot constraint helper, for example:
`minAngle`, `maxAngle`, `maxVelocity`, and optional minimum clearance margin.
2. Do not change AI targeting behavior in this fix. Keep AI using existing `computeOptimalShot`.
3. In `checkDirection`, require the found validation shot to satisfy the reasonable-shot helper before accepting.
4. If no reasonable shot is found in the current solver pass, treat direction as invalid.
5. Keep thresholds configurable constants near existing physics constants for easy tuning.
6. Start with conservative thresholds and adjust only after smoke tests and quick play tests.

### Acceptance Criteria
1. Validated rounds have at least one non-extreme firing solution in both directions.
2. AI and user input pipelines remain functional.

## Fix 8: Unify Validation Flight Limits With Runtime Flight Limits

### Objective
Remove false negatives caused by differing simulation end conditions.

### Current Risk
Validation max simulation time/bounds do not match runtime miss/out rules.

### Edit Targets
`simulateShot`, runtime miss/out helpers, and constants region.

### Implementation Steps
1. Introduce shared projectile termination constants used by both validation and runtime.
2. Set validation max time to match runtime `maxFlightSeconds`.
3. Align world-out bounds thresholds used by validation with runtime miss thresholds.
4. Keep fixed timestep `SIM_DT` unchanged.
5. Verify that long-arc valid shots are not prematurely discarded in validation.

### Acceptance Criteria
1. Validation no longer fails shots solely due to a shorter internal time horizon.
2. No performance regression during normal regeneration.

## Recommended Implementation Order

1. Fix 1
2. Fix 2
3. Fix 3
4. Fix 4
5. Fix 5
6. Fix 6
7. Fix 7
8. Fix 8

This order maximizes stability by first preventing invalid-start leakage, then fixing physics-context mismatches, then tightening fairness quality.

## Post-Fix Verification Pass

After all fixes are complete, run this final manual pass:

1. Generate at least 50 rounds across each wind mode (`off`, `low`, `high`) and each gravity mode (`low`, `normal`, `high`).
2. For each configuration sample, play at least one round from each side.
3. Confirm no startup failures, no endless regeneration loops, and no obvious impossible starts.
4. Confirm AI vs AI demo mode still cycles rounds without hanging.
5. Confirm classic mode keyboard controls and counterfire mode still work.
