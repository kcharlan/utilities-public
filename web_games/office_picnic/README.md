# Office Picnic

A dependency-free browser game about a paper airplane's trip from the 40th floor to the office picnic. Static HTML/CSS/ES modules; no installation or build.

## Play locally

Requires Node 20+ for the local server and verification scripts.

```sh
npm start
```

Open http://127.0.0.1:4173. Any ordinary static HTTP host can serve the contents of `dist/`. Browser ES modules require HTTP serving rather than opening the HTML file directly. Hold Space, the primary mouse button, or a finger to climb; release to dive. Pause with Escape or P, and press R to restart from pause or the result screen (or at any time in Nonstop).

## Local webserver deployment

Canonical source lives at `web_games/office_picnic` in the utilities repository. The checked-in `dist/` directory is the maintained static runtime; there is no build step. From this directory:

```sh
npm test
git add dist
npm run deploy -- --dry-run
npm run deploy
npm run deploy -- --check
```

Play at [localhost:7711/games/office_picnic/index.html](http://localhost:7711/games/office_picnic/index.html). The existing webserver serves the files immediately; no container restart or dedicated Node server is needed. The server's `/games/` directory browser lists the game automatically; directory URLs open its file browser, so use the explicit `index.html` play link.

The installer copies only stage-zero tracked files beneath `dist/` and requires their working bytes and modes to match the Git index. It installs into `~/webroot/games/office_picnic/`, preserving other games and unrelated local files. Use `--webroot DIR` or `UTILITIES_WEBROOT_DIR` for another webroot. `--check` compares installed maintained files with indexed source, including permission modes; it does not classify unrelated files as drift. Source updates require rerunning deployment.

The complete prior managed runtime is backed up under `~/.utilities-deploy-backups/office-picnic/` before activation; successful forward deployments retain the newest two backups. These are persistent recovery records, not test scratch. Restore with `npm run deploy -- --rollback BACKUP` using the printed backup directory. Rollback works independently of unfinished or removed current source, also backs up the current files, preserves recovery history, and preserves unrelated local files. Files absent before installation are removed when restoring that backup. Failed activation restores prior maintained bytes. Test fixtures use private OS temporary directories and remove them.

Hold Space, the primary mouse button, or one finger on the playfield to pitch up and climb, spending airspeed. Release to pitch down, dive and build airspeed, including inside AC lift. Climb over rooftop flocks; dive below washer platforms, then hold briefly to level out and rebuild height. Rising air supplies upward push rather than free airspeed: holding can still stall below about 20 mph. The HUD separates air effects from actual rising/descending speed and shows height in feet.

The opening needs a climb, a dive and another height recovery. Casual Friday has ten encounters alternating flocks and washers across five districts. Rush Hour adds moving hazards, squeeze windows between washers and flocks, and headwinds in Crosswind Court. AC has steady chevrons; vents have full-height steam bursts and real lulls; rooftop heat has broad, weaker contours; tailwinds have horizontal ribbons; fading thermals weaken visibly with height. Display units are mph, miles, and feet within a quarter mile of the picnic. Physics/report data remain metric.

Optional time pickups sit near hazards and rooftops; each tag shows its time reward. The timer and best records use time after rewards and Standard impact penalties. The result breaks down flight time, impacts, and pickups. Choose Casual Friday, Rush Hour or Overtime on the title screen. Overtime adds more squeeze encounters, stronger headwinds and fewer prompts. Standard restores the last rooftop passed in 0.4 seconds; each impact adds 3 seconds in Casual, 5 seconds in Rush and 10 seconds in Overtime. Nonstop restarts from the office. Pause with the button, Escape or P; mute with the button or M. Press R to restart while paused or at the result screen, or at any time in Nonstop. Leaving the tab pauses. Best completed times are separate by tier and mode and saved on this browser; when storage is unavailable, records still survive replays during the current session.

## Verify

```sh
npm test
npm run measure
npm run prove
npm run playtest
```

The playtest runs seeded pilot studies, reference route and district proofs, and shortcut checks. Use `node scripts/playtest.mjs --tier casual --n 10` for a smaller diagnostic sample or add `--json` for machine-readable results. Diagnostic sample sizes cannot be combined with `--check`. Use `node scripts/playtest.mjs --tier casual --menu --n 100` to screen pickup placements in the current world.

Open the game with `?trace` to record inputs; after a finished flight, download its JSON trace from the result screen and run `node scripts/replay.mjs <trace.json>` to check it against the current tier and simulation version. Traces contain the full input history and crash locations; share them only when appropriate.

The full Node suite includes physics, collision/run state, timing/camera, records, assets and HTTP serving. The measurement command writes `reports/flight-limits.json`. The proof command writes `reports/route-proof.json` and fails on an uncleared route, collision, over-limit crossing, or failed perturbed trial.

At `/checks.html`, browser verification runs the same collision-enabled simulation in both modes for all three tiers, renders thirteen scenes (including vent burst/lull, moving washer, squeeze and headwind), checks actual sprite decoding, records and Web Audio, and samples drawing cost. This harness is separate from the play flow; it does not substitute for human playtesting.

## Architecture and limits

- `dist/game/physics.js` is browser-free, with a fixed 1/60-second step. `measure.js` measures it before `world.js` creates geometry. Physics and route proofs run unchanged in Node and browsers.
- `simulation.js` owns collision, rooftop checkpoints, 0.4-second respawn, warnings and the continuous final landing. `bot.js` outputs only hold/release. `main.js` owns input, UI, audio and scheduling.
- Canvas scenery is code-drawn from the generated key art's palette. Skyline layers are cached; device-pixel ratio is capped at 2. Portrait uses independent vertical framing to preserve horizontal warning distance. Reduced motion removes decorative parallax and animated air marks; essential flight/hazard motion remains.
- Clean Casual bot time is 5:05.35, Rush reference time is 5:19.08 and Overtime reference time is 5:37.35 over 3.88 miles. There are 25 crossings with synthetic design-envelope utilization from 55.3% to 91.4%. The report distinguishes synthetic envelope targets, actual bot entry states, actual receiving roof bounds, and real collision-enabled sampled clearance. It also records each actual above/below encounter, their clearance and warning timestamps, and input time by district. These are different measurements.
- Each tier proof includes 135 perturbed district-entry/control-cadence trials and 200 rooftop checkpoint trials at eight hazard-clock offsets. Harder-tier occupied gaps use district trials and actual-entry checks; release-only trials cover unoccupied gaps, including headwinds. Engagement regressions reject passive release, one launch pull-up followed by coasting, and high cruising past the opening washer. A reaction test checks responding to the advertised washer warning after a short delay. Reachability and required control are both tested.
- The tiered course uses `office-picnic-v5`. On first load it copies v4 best times into Casual and preserves the old key; the selected tier and mute preference are also saved.
- Runtime deployment is local, with no public game hosting, analytics or external runtime requests. The development server is optional once deployed.

See `docs/assets.md` for asset provenance and `reports/dive-art-qa.md` for historical dive-course QA. Earlier QA reports also describe historical courses. Physical mid-range-phone FPS and independent first-time-player success require testing on that hardware/with that participant; responsive browser emulation does not establish either.

Medals use net time after pickups and penalties. Each tier row shows its gold, silver and bronze targets and its saved Standard and Nonstop bests, graded against the current table. Both modes use the same thresholds. Regenerate tables with `node scripts/medals.mjs`; use `--tier casual --gold-quantile 0.45` to override a tier's quantile. `node scripts/playtest.mjs --tier overtime --headwinds` compares stale and regenerated thresholds on matched wind studies.
