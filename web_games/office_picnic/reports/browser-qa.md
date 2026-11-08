# Browser verification — 2026-11-08

Historical first-course report. The current authored-maneuvers revision is documented in `rebalance-qa.md`; its geometry, record version and reference time differ from this report.

## Observed results

Used the Codex in-app browser at desktop **1440×900**, phone portrait **390×844** (also its default narrow view), and phone landscape **844×390**. These are viewport tests on the host computer, not physical mobile devices.

- Inspected the generated title art, launch from the office window, plane/pigeon sprites, all five district scenes, rooftop machinery/lift marks, gold pull-up stripes, overhead platforms with cables/washer silhouettes, flock warnings, park/table/bowl, pause, and results.
- Played through the earlier 9.79 km development corridor through the normal game UI using keyboard input and visible gold-stripe cues. Observed crashes/restores in the final district and completed it at **7:36.23**, with distance and **“Thanks for coming.”** on the results card. Observed the best time survive returning to title and reloading.
- After that playthrough, fixed the continuous landing, corrected district feature coverage, and finalized the **9.65 km** route. Development best times were invalidated with the `office-picnic-v2` storage key. Do not compare the earlier manual time with the final course's records.
- The finalized collision-enabled route passed in both modes inside the browser harness at **7:28.05**. It uses the exact production physics, world, simulation, bot, renderer, record functions and Web Audio class. The latest Node proof covers the final stall correction as well.
- Used normal pointer holding on the playfield and observed speed decrease from 26 to 18 m/s. Used sustained keyboard hold to stall/crash in Nonstop and observed a fresh office throw with the timer reset.
- Exercised normal Pause/Keep flying and observed the clock freeze while paused. Exercised mute/unmute, reloaded, started a run and observed the muted preference persist.
- Browser checks verified actual alpha sprite decoding, session record fallback, local storage read/write, AudioContext unlock, synthesized event scheduling, suspend/resume and mute. No warnings/errors were captured in the inspected browser logs.
- Inspected the two-second landing replay after the fix; it uses the real landing state rather than substituting a render position.
- Exercised the reduced-scenery-motion harness control and inspected scenes. The actual game also reads and listens for the OS `prefers-reduced-motion` setting; the harness toggle does not prove an OS preference change was delivered by this browser environment.

## Performance samples

The harness measured 90 rendered frames, cycling all district/ending scenes. On this host browser, the finalized desktop sample reported **0.30 ms draw p95**, and the phone-size sample **0.20 ms draw p95**. Both reported a **8.30 ms median frame interval**. These are short host samples of renderer cost/RAF timing, not proof of sustained 60 fps on a mid-range phone. Device pixel ratio is capped at 2, skyline canvases are cached, and audio voices/catch-up steps are bounded.

## Fixes made from observed failures and review

- Phone portrait initially pushed the plane too low; a failing camera regression now protects independent vertical framing.
- Unbounded columns initially lifted the bot into platforms; columns have bounded heights.
- The original route could clear without holding; later receiving roofs now require pull-up energy management, guarded by a release-only regression.
- Broad thermal recovery width was insufficient before late pull-ups; recovered route states and perturbed trials now pass.
- Held stalls initially gained height inside lift, including with a nose-up entry; both are regression-tested and now lose height.
- Blocked storage initially discarded a session best on a slower replay; the current records are retained in memory.
- Proof margins initially described synthetic entry states alone; the report now separately records actual bot speed/pitch/height, solid roof bounds, actual receiver clearances, collision-enabled sampled trials, and measured actual-entry continuation range.
- Landing initially snapped to the bowl in one render frame; a two-second simulation state now descends continuously before results.
- The first feature selection omitted AC from later districts; every district now teaches its new feature first and includes every earlier type. A regression verifies coverage.

## Remaining verification limits

- No physical mid-range phone was available: sustained device FPS, real touch hardware behavior, thermal throttling and mobile audio output remain unverified.
- No independent first-time participant was available. A complete agent-controlled browser playthrough, generous teaching, collision proofs and perturbed trials support reachability, but do not establish first-time human success.
- The completed normal-UI manual playthrough preceded the final air-feature sequence and landing changes. The final route was fully cleared by Node and browser bots, rendered/inspected in browser, and checked by the full suite; a second complete unaided manual traversal of the final geometry was not performed.
- The in-app browser's separate tabs remained active during the attempted focus-loss test, so an actual hidden-tab/window-blur transition could not be established there. The event handlers clear input and pause, and paused-clock behavior was tested, but that specific OS/browser transition remains unobserved.
- Audio lifecycle/synthesis was exercised in the real browser; a human listening review of the entire musical progression was not performed.

## Reproduction

Run `npm start`, open the printed URL and use normal flight controls. Open `/checks.html` for repeatable route/audio/storage/render checks and scene/landing previews. Run `npm test` for the full Node suite, including the HTTP server, asset checks and CLI measurements/proofs. Exact final results are in `tests-output.txt`, `flight-limits.json` and `route-proof.json`.
