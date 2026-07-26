# Multibody Gravity Lab

A browser-based N-body gravity sandbox and screensaver. Bodies attract each other, merge on collision, and can show visual history (trails) plus forward predictions (leads).

The runtime is a single-file app (`index.html`): it has no build step, backend, external libraries, or required runtime assets. The other files in this directory are documentation, sample save files, and test tooling.

## What This Is (General Overview)

Multibody Gravity Lab simulates space-like motion:

- Each body has mass, position, velocity, and color.
- Every body pulls on every other body with gravity.
- When two bodies overlap, they merge into one larger body.
- The camera auto-frames the system by default so motion stays visible.

Two working modes:

- `Screensaver`: auto-generates bodies and runs continuously with auto-restart rules.
- `User setup`: you place/edit bodies and run your own scenario.

Use it for:

- visual exploration of orbital behavior,
- quick “what if” setups,
- passive screensaver-like motion.

## Quick Start

From repo root, `cd web_games/multibody_sim`:

```bash
open index.html
```

or serve locally:

```bash
npx http-server -p 4173 -c-1
# then open http://127.0.0.1:4173/index.html
```

## Project Layout

- `index.html`: complete application (UI, simulation, rendering, persistence). Intentionally a single-file app.
- `USER_GUIDE.md`: end-user guide for controls, modes, and save/load workflow.
- `multibody-test-1.json`: sample User setup mode save state for multibody testing.
- `multibody-test-2.json`: sample User setup mode save state for multibody testing.
- `multibody-test-3.json`: sample saved setup state for multibody testing.
- `tests/smoke.spec.js`: Playwright smoke tests.
- `playwright.config.js`: Playwright test configuration (launches `http-server` on `127.0.0.1:4173`).
- `package.json`: local tooling dependencies (`http-server`, Playwright libs).

## Core Behavior Summary

- Physics integrator: pairwise gravitational acceleration + leapfrog-style velocity half-step integration.
- Collision model:
  - regular bodies merge perfectly inelastically, conserving mass and momentum and using a mass-weighted color blend,
  - singularities use a deliberately stylized effective-mass model, compressed radius growth, and partial absorption of a regular body's displayed mass.
- UI layout:
  - collapsible sections for `User setup`, `Selected body`, and `Physics`,
  - floating stats overlay with live metrics and screensaver gate status.
- Camera:
  - tracks body bounds in both modes,
  - can focus near interacting pairs in screensaver late phase,
  - supports floating `Camera Subject` targeting (`Auto`, `Full`, `Follow`),
  - `Follow` uses a compact id stepper (`◀`, id input, `▶`) and the same near-pair-style framing envelope,
  - `Follow` preserves lock through merges by inheriting the dominant source id (highest effective mass, then tie-breakers),
  - camera shortcuts (global override): `[` previous id, `]` next id, `\` back to `Auto`,
  - applies mode-specific maximum zoom caps (`screensaver` vs `user`),
  - applies a screensaver run-time minimum span floor to preserve scene context,
  - freezes during the 1-body end delay in screensaver.
- Restart lifecycle (screensaver):
  - restart after 2 seconds real-time when only one body remains,
  - otherwise restart only when all three gates are true: quiet timer elapsed, near-pair lock off, and zoom boundary exceeded.

---

## Developer Reference (Detailed)

### Architecture

Single-file, module-script app:

- `state`: mutable runtime model (mode, bodies, timers, camera gates, UI flags).
- `cfg`: simulation/rendering tuning constants.
- `ui`: DOM references.
- main loop:
  1. accumulate real frame delta,
  2. run physics substeps (`dt = 1/120`) scaled by `timeSpeed * timeMultiplier`,
  3. update safety/restart timers,
  4. update effects/leads/camera,
  5. render and update UI.

Important entry points:

- `physicsStep(dt)`: shared physics path for all modes.
- `updateCamera()`: auto-camera framing logic.
- `generateScreensaverBodies(n)`: spawn + velocity assignment + viability checks.
- `startSimulation()/pauseSimulation()/resetCurrentMode()`: run controls.

### Data Model

`Body` shape:

- `id: number`
- `pos: {x, y}`
- `vel: {x, y}`
- `mass: number`
- `radius: number` (regular: `radiusScale * sqrt(mass)`, singularity: compressed log-growth curve)
- `color: {r,g,b}`
- `isSingularity: boolean`
- `trail: Vec2[]`

Core unit conventions:

- Distances are world units (arbitrary).
- Velocity is world-units per simulation second.
- `timeSpeed` and `timeMultiplier` scale simulation time, not rendering time.

### Modes

`screensaver`:

- auto-camera by default, with `Full` and `Follow` subject overrides,
- auto-spawn and auto-restart,
- boundary tracking and restart gates enabled.

`user`:

- manual body placement/editing,
- optional auto-velocity assignment on start,
- reset restores the in-memory baseline captured by `Start` or `Load`,
- clear wipes setup,
- load/save JSON for setup persistence.

### Controls Implemented (Code-Level Summary)

Simulation controls:

- `Start/Pause`: toggle running state.
- `Reset`:
  - screensaver: regenerate random set,
  - user: restore baseline setup snapshot.
- `Clear` (user only): wipes current setup.
- `Auto velocities` (user only): assign computed starting velocities.
- `Load` (user only): JSON setup import.
- `Save` (screensaver + user): JSON setup export.
  - screensaver save exports the current screensaver cycle start (baseline) so it can be loaded into user mode.
  - user save exports the current scene while paused; while the simulation is running, it exports the baseline captured at the most recent `Start` or `Load`.
- screensaver mode controls:
  - `Screensaver bodies` default: `5`,
  - `Singularity chance (%)` (0-100),
  - `Max singularities` (at most N per generation, no guarantee of any; editable when chance > 0).
- physics/visual controls:
  - `Show object numbers` checkbox toggles on-canvas body id labels.
- camera subject controls:
  - `Camera Subject`: `Auto`, `Full`, or `Follow`,
  - `Follow ID` numeric input plus `◀` / `▶` step buttons to move across ids quickly.
- selected-body controls (user mode):
  - `Mass` slider,
  - `Velocity X` / `Velocity Y` numeric inputs,
  - `Velocity (drag x10)` live readout,
  - `Singularity` checkbox (editable while paused).

User setup pointer/keyboard (while paused):

- Left click empty canvas: create body.
- Left drag on body: move body.
- `Middle drag` on body: set velocity.
- `Right drag` on body: resize mass.
- Mouse wheel on body (paused user mode): adjust mass.
- `Delete`/`Backspace`: remove selected body (when focus is not in an input).

### Save/Load JSON Contract

Current payload (`version: 3`):

- `type`, `version`, `savedAt`
- `sourceMode` (`screensaver` or `user`) indicating where the save was created
- `bodies[]`
  - each body may include `isSingularity`
- `nextBodyId`
- `selectedBodyId`
- `settings`:
  - `timeSpeed`, `timeMultiplier`, `screensaverN`
  - `screensaverSingularityChance`, `screensaverSingularityMax`
  - `G`, `epsilon`
  - `trailsEnabled`, `trailLength`
  - `leadsEnabled`, `leadsLength`
  - `showBodyIds`
  - `autoAssignOnStart`, `autoVelFactor`, `autoCameraSetup`
  - `cameraSubjectMode`, `cameraSubjectBodyId`
- `userSetupBaseline`:
  - `bodies[]`, `nextBodyId`

Example User setup mode save states in this project:

- `multibody-test-1.json`
- `multibody-test-2.json`
- `multibody-test-3.json`

Load any of these files from `User setup` mode via the `Load` control to use them as sample multibody setup/testing scenarios.

Save behavior:

- tries `showSaveFilePicker()` first (filename dialog),
- falls back to download if unavailable.
- user mode save persists the current scene while paused. While running, it persists the most recent start/load baseline rather than transient in-run state.
- screensaver mode save persists the screensaver cycle start baseline (not transient in-run merged state).

Load behavior:

- validates/coerces body data,
- restores settings and baseline when present,
- uses baseline as the active loaded scene (or `bodies[]` when no baseline exists),
- camera snaps to loaded setup bounds.

The loader also accepts the included legacy version 2 samples and a bare body array; newly created saves use version 3.

### Restart Logic (Screensaver)

`screensaverRestartRequired()` returns true when any is met:

- `bodies.length <= 1` and `singleBodyRealElapsed >= 2s` (real-time delay).
- gate condition (all required together):
  - quiet time elapsed (`restartQuietTime`),
  - no near-pair exception active,
  - zoom boundary exceeded (`camera.zoom <= screensaverReferenceZoom / restartZoomOutFactor`).

Notes:

- Zoom gate is a hard restart requirement.
- During 1-body hold, camera updates are intentionally frozen to avoid zooming into the final body.

### Spawn and Initial Velocity Strategy

Screensaver body generation:

- random masses in `[50, 300]`,
- singularity masses in `[50, 150]` when selected by chance roll,
- singularity generation is chance-based and capped by `Max singularities`,
- random positions inside spawn radius with overlap rejection,
- diverse hue assignment.

Velocity assignment path:

- `n <= 4`: `assignLowBodyInteractionVelocities()` (adds inward and nearest-body bias to improve interaction likelihood).
- `n >= 5`: `assignOrbitishVelocities()` around COM.

Spawn quality gates:

- `validateScreensaverStart(20)`: rejects too-close/immediately problematic starts.
- `hasLowBodyInteractionPotential(80, 0.45)` for `n <= 4`: forward simulation check to reject likely “drift away” starts.

### Rendering Layers

Render order:

1. trails (dashed, fading),
2. bodies with glow,
3. body id labels (contrast-aware text for readability on regular/singularity bodies),
4. merge FX,
5. leads (future path + arrowhead),
6. velocity handles/arrows (paused user mode).

Special visual behaviors:

- velocity arrows originate at body edge (not center),
- lead paths are forward-biased and minimum-visible-length constrained,
- merge effects interpolate lobe/core blend over `mergeFxDuration`.

### Camera System Notes

Camera uses bounds fit against view rect that excludes the sidebar area:

- desktop: canvas area to the right of panel,
- mobile: canvas area below panel.

Key camera modifiers:

- `cameraPaddingFactor`: normal framing buffer.
- mode-aware zoom cap:
  - `cameraMaxZoomScreensaver`
  - `cameraMaxZoomUser`
- near-pair focus envelope:
  - `nearPairLockMultiplier`
  - `nearPairFocusEnvelopeFactor`
  - extra `pad = 1.15`
- user run min span:
  - `userRunMinCameraSpan` prevents collapsing too tight immediately after start.
- screensaver run min span floor:
  - uses `boundaryTrackedExtent * 2 * screensaverMinSpanFactor` to avoid over-zooming on tight interactions.

### Key Config Constants (Magic Numbers to Tune)

Physics/integration:

- `dt = 1/120`
- `maxSubsteps = 40`
- `maxSubstepsHard = 240`
- `collisionFactor = 1`
- `radiusScale = 1.7`

Camera and restart:

- `cameraLerp = 0.12`
- `cameraLerpFocus = 0.06`
- `cameraPaddingFactor = 1.3`
- `cameraMaxZoomScreensaver = 2.0`
- `cameraMaxZoomUser = 7`
- `screensaverMinSpanFactor = 0.65`
- `settleTime = 3`
- `boundaryMultiplier = 4`
- `restartZoomOutFactor = 3`
- `restartQuietTime = 480`
- `singleBodyRestartDelayRealSec = 2`
- `nearPairLockMultiplier = 10`
- `nearPairFocusEnvelopeFactor = 2`

Leads and trails:

- `leadRefreshInterval = 0.12`
- `leadPredictDt = 1/90`
- `leadLengthMultiplier = 30`
- `leadVelocityRef = 5`
- `leadVelocityScaleMax = 8`
- `leadMinVisibleRadiusFactor = 2.4`
- effective trails scale: `trailLength * 15` with large-N caps.

Merge FX and user velocity editing:

- `mergeFxDuration = 0.42`
- `mergeFxFollowRate = 12`
- `velocityArrowScale = 12`
- `velocityDragDivider = 10`

Hard bounds:

- `maxBodiesHard = 50`

### Important State Variables to Understand

- `timeSinceCollision`: drives quiet restart gate.
- `boundaryTrackedExtent` / `finalBoundary`: early-run extent tracking used during screensaver settling, camera reference capture, and screensaver minimum camera span floor.
- `referenceZoomCaptured` / `screensaverReferenceZoom`: zoom-gate reference capture.
- `singleBodyRealElapsed`: real-time delay counter before 1-body restart.
- `userRunMinCameraSpan`: protects user-run framing from over-zoom.
- `screensaverSetupBaseline`: save anchor for the current screensaver cycle start.
- `userSetupBaseline`: reset anchor in user mode.
- `leadDirty` / `leadRefreshClock`: lead recomputation scheduling.
- `velocityDrag`, `massDrag`, `moveDrag`, `pointerWorld`, `pointerScreen`: user interaction state.

### Safe Tuning Workflow

When changing behavior constants:

1. Change one constant family at a time (camera, restart, spawn, leads, etc.).
2. Test in both modes:
   - screensaver with 3, 5, 20 bodies,
   - user setup with manual and auto velocities.
3. Verify end-state behavior:
   - near-pair lock,
   - quiet timer,
   - single-body delay and camera freeze.

### Validation Commands

From repo root, `cd web_games/multibody_sim`:

Syntax check:

```bash
awk '/<script[^>]*>/{flag=1;next}/<\\/script>/{flag=0}flag' index.html > /tmp/multibody_sim_check.js
node --check /tmp/multibody_sim_check.js
```

Serve locally:

```bash
npx http-server -p 4173 -c-1
```

Run Playwright smoke tests (config launches local `http-server` on `127.0.0.1:4173`):

```bash
npm test
```

### Known Design Tradeoffs

- Single-file architecture is simple and portable but not modular.
- O(N²) gravity and collision checks scale poorly at high body counts.
- Physics is intentionally stylized for visual interest; it is not unit-calibrated astrophysics.
