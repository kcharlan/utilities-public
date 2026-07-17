# Gorilla.BAS Reimagined

A modern, web-based artillery game inspired by the classic QBasic **Gorilla.BAS**. While the core concept of two gorillas throwing explosive bananas across a skyline remains, this project is a complete reimagining rather than a direct port. It features a fluid physics engine, particle effects, simultaneous turn-taking, and arcade progression—all contained within a single HTML file.

## Quick Start
- Open `index.html` directly in a modern browser, or serve the folder (e.g., `python3 -m http.server`) and visit `http://localhost:8000`.
- **No runtime dependencies:** The game itself is self-contained with no build step, external assets, or network calls. `package.json` is only for Playwright development/testing tooling.

## Key Features
- **Three Game Modes:**
  - **Classic:** Standard 1v1 infinite play (Vs AI or Local PvP).
  - **Arcade:** Survival mode where Player 1 starts with 5 lives.
  - **Demo:** AI vs AI auto-play.
- **Constraint-Based Skyline Generation:** A single-pass planner builds gorilla platforms, central blockers, and filler buildings from explicit constraints instead of retrying random layouts.
- **Counterfire System:** Optional simultaneous turn mode where players lock in shots and fire a volley together.
- **Modern Physics:** High-fidelity trajectory simulation allowing for high-arcing off-screen shots, wind effects, and particle explosions.
- **Procedural Audio & Graphics:** All visuals and sound effects are generated programmatically—no static assets.

## How to Play
- **Goal:** Hit the opposing gorilla with your banana.
- **Controls:**
  - Adjust **Angle** (0–180°) and **Velocity** (5–100).
  - Press **Throw** (or `Enter`).
  - **R** key restarts the round.
- **Strategy:** Account for **Wind** (indicated in the HUD) and **Gravity**.
- **Arcade Mode:** You have limited lives. Survive as long as you can against the AI.

## Demo Mode
- Append `?demo` or `#demo` to the URL (e.g., `index.html?demo`) to launch directly into AI vs AI auto-play.
- Great for screensavers or watching the AI battle it out.
- Interrupt at any time by hitting the Escape key, or by changing the game mode in the sidebar between rounds.

## Settings & Customization
- **Opponent:** Toggle between AI and Local 2-Player.
- **Difficulty:** Adjust AI precision (Easy, Medium, Hard).
- **Physics:** Tweak Gravity (Low, Normal, High) and Wind strength (Off, Low, High).
- **Environment:** Skyline Variance (Low, Normal, High) controls building height differences.
- **Counterfire:** Enable/Disable simultaneous turns.
- **Mute Sounds:** Toggle procedural audio on/off.

## Project Layout
- `index.html`: Complete application (game engine, UI, rendering, audio). Intentionally a single-file app.
- `docs/`: Design and implementation notes (PRD, level generation refactor, fairness fix).
- `package.json`: Dev tooling dependency (`@playwright/test`).

## Developer Notes
- **Single-File Architecture:** The entire game engine, UI, and assets exist within `index.html`. This is intentional; do not split into modules.
- **Tech Stack:** Vanilla JavaScript (ES6+), HTML5 Canvas, CSS3.
- **State Management:** Centralized state for physics and game logic; reactive UI updates.

## Level Generation Notes
- The game now uses a deterministic constraint pipeline:
  - `createLevelSpec(...)` chooses gorilla zones, platform heights, and obstacle requirements using current gravity/wind context.
  - `planBuildingZones(...)` creates ordered zones for left platform, center obstacle, right platform, and fillers.
  - `constructBuildings(...)` materializes skyline geometry from those zones.
  - `generateLevelConstraintBased(...)` returns a complete level payload in the same shape used by the round state.
- `regenerateRound(...)` always uses the constraint generator directly. Legacy retry loops, simple-mode retries, and emergency/fallback layouts were removed.
- Validation helpers (`validateLevel`, `findValidationShot`, `hasDirectLineOfSight`) are still present for debugging/tuning and AI-related logic, but generation correctness is achieved by construction.

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
