# Authored-maneuvers revision — verification

## What changed

The user approved sparse authored maneuvers after playing the previous course. The revised course has five climb-over flocks and five dive-under washer frames, with breathing room between encounters. The first reference encounter arrives at 13.883 seconds. Receiving roofs in the latter half of Glass Mile now require rebuilding height after the dive; one launch pull-up followed by coasting no longer clears it.

Flight equations/handling are unchanged and were remeasured before layout. Lift strengths, widths and heights were rebalanced. AC is steady; vents range from a genuine descending lull to a rising burst; rooftop heat is wider and weaker; wind adds forward motion; fading thermal power decreases with height. Effects extend through the flight band and use the same strength/phase function as physics. Distinct arrows, steam, arches, ribbons and fading rings distinguish the types by shape as well as color. No headwinds or random hazard swarms were added.

Player displays use mph and miles, switching remaining distance to feet within a quarter mile. Technical proof data remain in meters/seconds. The v3 course has its own best-time table; older records remain stored under their older key.

## Automated evidence

`npm test` runs the whole dependency-free suite, including the CLI measurement/proof commands. Final suite: **38 passing, zero failures**. Exact output is in `tests-output.txt`.

`route-proof.json` records:

- Standard and Nonstop: **464.7667 seconds (7:44.76), 8,940m (5.56 miles), zero impacts** with actual collisions enabled and only hold/release bot input.
- **135** trials varying district-entry speed, height and input sampling cadence; all clear.
- **25** crossing-envelope trials, with design utilization from **55.6% to 92.0%**. Actual entry states, physical roof bounds, synthetic target clearance and real collision-inclusive roof clearance remain separate fields.
- **10** above/below encounter records; all passed. Nominal reference minimum hazard clearance: **8.711m / 28.6ft**. Minimum warning lead in that reference run: **13.867 seconds**. These are nominal-run measurements, not a claim that every possible player approach has that margin.
- Every encounter warning/arrival timestamp must be a finite number; absent warnings cannot pass by coercing null to zero.

Engagement regressions check that passive release fails in the opening, a single 2.1s or 3s launch hold cannot coast through Glass Mile, height-only cruising hits a hazard, and high targets of 185/230/300m cannot bypass the washer above. The washer suspension is visibly solid beyond reachable lift-plus-pull-up height. A separate scenario cruises at normal height, responds to the actual advertised warning after 0.4s, and clears below the washer. Feature tests exercise physical vent lull/burst, weaker rooftop heat, altitude falloff and tailwind motion.

Guidance regressions check early over/under advice, release instructions at low speed or sufficient height, rebuilding height between encounters, and a warning to climb rather than glide into a raised receiving roof.

## Browser observations

Used the in-app browser at **390×844** and **1440×900**. Normal game UI was played with native Space holds and releases driven by the visible instructions, without importing or modifying game state through the browser tools.

- Played the first climb on the phone layout, observed early release/low-speed guidance, and inspected the flock/perch in the actual flight band.
- An interval left coasting during the first observation sequence returned to the rooftop checkpoint. Subsequent guided UI play cleared the first climb/dive/recovery, reached Boiler Row, and exercised its vent/flock encounter. This was agent-guided play, not an independent novice trial or an uninterrupted full-course human run.
- Continued normal flight at desktop size and inspected the HUD, region boundaries, sprites and live air-state text. Pause between observations froze the run and resumed normally.
- Browser verification cleared the entire final course in both modes, decoded the generated sheets, exercised actual record functions/storage and Web Audio unlock/synthesis/pause/resume/mute, and rendered nine scenes including ending, steam burst/lull and washer approach. No warnings/errors were found in the inspected logs.
- Inspected the full-height steam burst against its visibly quiet lull, broad heat arches, wind ribbons, fading thermal rings, and the washer mesh/platform. The physical solid frame and rendered frame share their full bounds.
- Exercised the reduced-scenery-motion harness control. Decorative movement stops; essential air-strength state remains legible. This does not establish delivery of an actual OS reduced-motion preference change in the test environment.

Both short 90-frame host samples reported **0.50ms draw p95** and **8.30ms median frame interval**. These are browser/host renderer samples, not sustained physical-phone FPS measurements.

## Review and fixes

A fresh reviewer found three material issues: a high bypass over the finite washer frame, nullable warning timestamps accepted by the proof, and a discrete warning that did not allow enough descent preparation. All were reproduced with failing regressions, fixed, and followed by a green full suite. Warning consumers now share the hazard's preparation distance; the washer sits later in its gap to permit a delayed reaction from normal cruise. There are no deferred material review findings.

Further playtesting caught misleading permanent-climb guidance, a one-launch-hold coast through the opening, and an outside-lift hint that could direct a low plane into a raised roof. Those have regression coverage and were corrected. Visual cleanup separates flock silhouettes and avoids duplicate on-screen warning labels.

## Remaining limits

Physical mid-range-phone performance, real touch hardware/mobile audio output and independent first-time-player success remain unverified. The browser playthrough used visible guidance and partial normal-UI traversal; full-course completion of this revision was verified by Node/browser bots rather than a new uninterrupted unaided human run. The prior report's in-app focus-loss/OS preference test limitations still apply. These limits are not replaced by the synthetic proofs or renderer timings.

Run `npm start`, then use the printed URL to play. `/checks.html` exposes repeatable browser checks and feature previews. The local preview server is temporary; start it again before refreshing a local browser tab after teardown.
