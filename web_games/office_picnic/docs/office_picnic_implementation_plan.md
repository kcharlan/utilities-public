# Office Picnic Implementation Plan

> Execute inline with superpowers:executing-plans. Use a fresh reviewer for the complete implementation. No Git operations or hosting publication.

**Goal:** Deliver the approved, measured, authored browser flight game.
**Architecture:** Browser-free fixed-step ES-module physics and world state; Canvas presentation and Web Audio consume events. Shared measurements, route geometry, bot, and tests prevent drift.
**Tech stack:** Static HTML/CSS/JavaScript; Node built-ins for tests, reports, and local serving.
**Spec:** docs/superpowers/specs/2026-11-08-office-picnic-design.md

## Global constraints

- No dependencies or build; one hold/release flight input; desktop and phone.
- Measure before district layout; all gaps within measured limits; 4–8-minute clean run.
- Five districts, checkpoints and nonstop mode; potato-salad ending and “Thanks for coming.”
- Generated key art first, palette from it, generated fixed-grid sprites; code backgrounds.
- Full Node suite and bot proofs, desktop/phone browser verification; no unobserved hardware/novice claims.

## Review focus

- Focus loss or pointer cancellation must release input and pause without clock advance.
- Crash must restore the correct mode's starting point within a second.
- Corrupt/unavailable storage must not prevent playing or corrupt best records.
- Small screens must preserve warning time, target size, and legible control guidance.
- Stall recovery and every crossing must work with actual collisions enabled.

## Task 1: Measured flight model

Files: dist/game/physics.js, scripts/measure.mjs, tests/physics.test.mjs, reports/flight-limits.json; asset generation and provenance in dist/assets and docs/assets.md.
Interfaces: createPlane({x,y,speed,pitch}), advancePlane(plane, held, air, dt), PHYSICS, measureFlight(). Coordinates use world meters, positive y upward. Immutable constants and fixed dt shared by Node/browser.

- [x] Generate and inspect key art, extract palette; generate and inspect plane/pigeon grids.
- [x] Write tests asserting hold trades speed for height, release gains speed, low speed stalls and release recovers, and identical inputs produce identical state. Run node --test tests/physics.test.mjs and observe missing implementation failure.
- [x] Implement physics and empirical measurement of glide ratio, pull-up climb/range and stall speed. Run measurements before writing world geometry.
- [x] Run physics tests and save measurement report. Expected all pass with finite limits.

## Task 2: Proven authored route and run state

Files: dist/game/world.js, dist/game/simulation.js, dist/game/bot.js, dist/game/records.js, scripts/prove.mjs, tests/simulation.test.mjs, tests/records.test.mjs, reports/route-proof.json.
Interfaces: buildWorld(limits), createRun(mode, world), stepRun(run, held), chooseInput(run), loadRecords(storage), saveResult(storage, mode, time). Run uses 60Hz ticks, emits discrete events, and exposes plane, district, elapsed, status, checkpoint, crash count.

- [x] Write and run failing tests for geometry margins, deterministic bot completion, stall handling, swept collisions, checkpoint/reset timing, nonstop reset, warning lead time and corrupt/blocked storage.
- [x] Author five districts from the measured envelopes. Implement real air features and hazards, checkpoint restore, timed respawn and clean finish.
- [x] Implement hold/release feedback bot, per-gap envelope utilization, end-to-end proof and perturbed entry trials. Run node scripts/prove.mjs; expected all districts/modes clear and every utilization <= 1.
- [x] Run full node --test suite; expected no failures and 240–480-second clean runs.

## Task 3: Playable presentation and browser validation

Files: dist/index.html, dist/style.css, dist/game/main.js, dist/game/render.js, dist/game/audio.js, scripts/serve.mjs, README.md, docs/lessons-learned.md, reports/browser-qa.md.
Consumes simulation/world/events and versioned records; browser code owns input, rendering, audio, storage and animation scheduling.

- [x] Write checks for served assets and UI state/timing helpers before implementation; observe failure. Timing/camera were tested first; HTTP/asset integration checks were added after those existing artifacts and passed directly.
- [x] Build title/game/pause/results, code city backgrounds using extracted palette, sprite rendering, all input routes and focus handling, reduced motion, adaptive camera and warnings, synthesized layered audio and event sounds.
- [x] Serve with node scripts/serve.mjs; inspect HTTP responses and play in browser at desktop/phone sizes. Exercise modes, ending, crashes, pause/mute, reload records, focus loss, reduced motion; fix and repeat. Exact observed checks and unavailable transitions are recorded in reports/browser-qa.md.
- [x] Obtain fresh reviewer findings, resolve material issues with regressions, and run node --test plus node scripts/prove.mjs in full. Record exact evidence and physical-device/independent-novice limits.
- [x] Document run/test commands, physics/proof results, assets and limitations. Hand off local runnable project without commits or publication.
