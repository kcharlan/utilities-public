# Gorilla.BAS Reimagined

A browser-based artillery game inspired by the classic QBasic **Gorilla.BAS**. Two gorillas throw explosive bananas across a procedurally generated skyline, with fixed-step projectile physics, particle effects, optional simultaneous turns, and arcade progression. It is a reimagining rather than a direct port, and the complete application is contained in `index.html`.

## Quick Start

- Open `index.html` directly in a modern browser. You can also serve this directory with any static file server.
- The game has no runtime dependencies, build step, external assets, or network calls.

## Key Features

- **Three Game Modes:**
  - **Classic:** Standard 1v1 infinite play (Vs AI or Local PvP).
  - **Arcade:** Survival mode where Player 1 starts with 5 lives.
  - **Demo:** AI vs AI auto-play.
- **Constraint-Based Skyline Generation:** A single-pass planner builds gorilla platforms, central blockers, and filler buildings from explicit constraints instead of retrying random layouts.
- **Counterfire System:** Optional simultaneous turn mode where players lock in shots and fire a volley together.
- **Projectile Physics:** Fixed-step trajectories support gravity, wind, and high-arcing shots that can leave the visible canvas and return.
- **Procedural Audio & Graphics:** All visuals and sound effects are generated programmatically—no static assets.
- **Session Stats:** Tracks kills, first-shot aces, and kills by shot count until the page is reloaded or scores are reset.

## How to Play

- **Goal:** Hit the opposing gorilla with your banana.
- **Controls:**
  - Adjust **Angle** (0–180°) and **Velocity** (5–100).
  - Press the active player's **Throw** button or `Enter`.
  - **R** key or **New Round** restarts the round; **Reset Scores** clears scores and session stats and starts a new round.
  - **Stats** opens the session statistics; **Open Help** (in the settings sidebar) shows the rules.
  - `Escape` closes an open Help, Stats, or Arcade game-over dialog.
- **Strategy:** Account for **Wind** (indicated in the HUD) and **Gravity**.
- **Arcade Mode:** You have limited lives. Survive as long as you can against the AI.

## Demo Mode

- Append `?demo`, `?mode=demo`, `#demo`, or `#mode=demo` to the URL to launch directly into AI vs AI auto-play.
- Press `Escape` to return to the last manually selected mode, or choose a different game mode in the sidebar.

## Settings & Customization

- **Opponent:** Toggle between AI and Local 2-Player.
- **Difficulty:** Adjust AI precision (Easy, Medium, Hard).
- **Physics:** Tweak Gravity (Low, Normal, High) and Wind strength (Off, Low, High).
- **Environment:** Skyline Variance (Low, Normal, High) controls building height differences.
- **Counterfire:** Enable or disable simultaneous turns (unavailable in Demo mode).
- **Mute Sounds:** Toggle procedural audio on/off.

Settings and session statistics are held in memory and reset when the page reloads.

## Project Layout

- `index.html`: Complete application (game engine, UI, rendering, audio). Intentionally a single-file app.

## Developer Notes

- **Single-File Architecture:** The entire game engine, UI, and assets exist within `index.html`. This is intentional; do not split into modules.
- **Tech Stack:** Vanilla JavaScript (ES6+), HTML5 Canvas, CSS3.
- **State Management:** In-memory `state` and `settings` objects drive game logic; explicit DOM updates keep the controls and HUD in sync.
- **Physics and collisions:** `requestAnimationFrame` drives fixed-step Euler integration in logical world space. Projectiles can leave the viewport until a termination bound or flight timeout ends the shot. Building impacts remove the projectile without deforming terrain; a hit on a gorilla's rectangular hitbox records a kill and ends the round once the volley resolves. There is no splash damage.
- **AI:** The AI simulates angle/velocity pairs, then schedules a difficulty-dependent number of deliberately offset ranging shots before using its calculated shot.
- **Scope:** Multiplayer is local only. The responsive layout has no dedicated touch gestures. Arcade difficulty locks at the first firing.

## Level Generation Notes

The game uses a randomized, constraint-based pipeline:

- `createLevelSpec(...)` chooses gorilla zones, platform heights, and obstacle requirements using current gravity/wind context.
- `planBuildingZones(...)` creates ordered zones for left platform, center obstacle, right platform, and fillers.
- `constructBuildings(...)` materializes skyline geometry from those zones.
- `generateLevelConstraintBased(...)` returns a complete level payload in the same shape used by the round state.

`regenerateRound(...)` calls the constraint generator once. The previous retry, simple-mode fallback, and emergency-layout paths have been removed. Validation helpers such as `validateLevel(...)`, `findValidationShot(...)`, and `hasDirectLineOfSight(...)` remain available for manual verification and tuning, but round generation does not call them.

### Key Generation Controls (in `index.html`)

- `GORILLA_EDGE_MARGIN`, `GORILLA_ZONE_BAND`
  - Control left/right placement bands for gorilla platforms.
- `MIN_BUILDING_WIDTH`, `MAX_BUILDING_WIDTH`, `BUILDING_GAP_MIN`, `BUILDING_GAP_MAX`
  - Control skyline horizontal rhythm and filler density.
- `MIN_BUILDING_HEIGHT`, `MAX_BUILDING_HEIGHT`
  - Global hard bounds for building heights.
- `MID_OBSTACLE_EXTRA`, `MID_OBSTACLE_MIN`
  - Main center-obstacle baseline in normal generation.
- `SIMPLE_MID_OBSTACLE_EXTRA`, `SIMPLE_MID_OBSTACLE_MIN`, `SIMPLE_MID_OBSTACLE_MAX`
  - Alternative center-obstacle bounds used when `simpleMode` is enabled in generator calls.
- `GORILLA_NEIGHBOR_CAP`
  - Limits nearby filler heights around each gorilla platform to avoid boxed-in starts.

### Practical Tuning Workflow

- Change one constant group at a time.
- Play multiple rounds across all gravity/wind presets after each change.
- Watch for over-flat maps, over-sealed maps, or reduced skyline variety.
