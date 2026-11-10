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

Hold Space, the primary mouse button, or one finger on the playfield to pitch up and climb, spending airspeed. Release to pitch down, dive and build airspeed, including inside AC lift. Climb over rooftop flocks; dive below washer platforms, then hold briefly to level out and rebuild height. Enter a tailwind band to gain a forward push, or fly outside it; the HUD indicates when a nearby lane is above or below. Rising air supplies upward push rather than free airspeed: holding can still stall below about 20 mph. The HUD separates air effects from actual rising/descending speed and shows height in feet.

The opening needs a climb, a dive and another height recovery. Each district begins with a clear crossing that introduces its air feature, followed by familiar hazards and a later climb that needs the new air. AC gives steady lift; vents pulse with real lulls; rooftop heat gives broad, weaker lift; wind columns provide lift and bounded ribbon lanes add optional tailwinds; thermals weaken with height. Rush Hour introduces moving hazards in District 2, additional familiar hazards in District 3, headwinds in District 4 and static squeezes in District 5. Overtime introduces moving hazards in District 2, a static squeeze in District 3, headwinds in District 4 and combines them in District 5. Display units are mph, miles, and feet within a quarter mile of the picnic. Physics/report data remain metric.

Optional time pickups sit near hazards and rooftops; each attached tag shows its time reward. Casual announces them 600 m ahead with a banner, placement hint, edge marker and route tick; Rush gives 450 m notice with a hint, marker and tick. Overtime gives a chime 300 m ahead. The timer and best records use time after rewards and Standard impact penalties. The result breaks down flight time, impacts, and pickups. Choose Casual Friday, Rush Hour or Overtime on the title screen. Overtime adds more squeeze encounters, stronger headwinds and fewer prompts. Standard restores the last rooftop passed in 0.4 seconds; each impact adds 3 seconds in Casual, 5 seconds in Rush and 10 seconds in Overtime. Nonstop restarts from the office. Pause with the button, Escape or P; mute with the button or M. Press R to restart while paused or at the result screen, or at any time in Nonstop. Leaving the tab pauses. Best completed times are separate by tier and mode and saved on this browser; when storage is unavailable, records still survive replays during the current session.

## Verify

```sh
npm test
npm run measure
npm run prove
npm run playtest
npm run ablation
npm run difficulty
```

The playtest runs seeded pilot studies, timing-window gates, reference route and district proofs, and shortcut checks. `npm run difficulty -- --tier overtime --json` prints machine-readable timing windows. Use `node scripts/playtest.mjs --tier casual --n 10` for a smaller diagnostic sample or add `--json` for machine-readable results. Diagnostic sample sizes cannot be combined with `--check`. Use `node scripts/playtest.mjs --tier casual --menu --n 100` to screen pickup placements in the current world.

Open the game with `?trace` to record inputs; after a finished flight, download its JSON trace from the result screen and run `node scripts/replay.mjs <trace.json>` to check it against the current tier and simulation version. Traces contain the full input history and crash locations; share them only when appropriate.

The full Node suite includes physics, collision/run state, timing/camera, records, assets and HTTP serving. The measurement command writes `reports/flight-limits.json`. The proof command writes `reports/route-proof.json` and fails on an uncleared route, collision, over-limit crossing, or failed perturbed trial.

At `/checks.html`, browser verification runs the same collision-enabled simulation in both modes for all three tiers, renders twenty-five scenes (including actual roof, flock and washer impacts, squeeze warning and pickup feedback, a district transition, vent burst/lull, moving washer, headwind and tailwind), checks actual sprite decoding, records and Web Audio, and samples drawing cost with live effects. This harness is separate from the play flow; it does not substitute for human playtesting.

## Architecture and limits

- `dist/game/physics.js` is browser-free, with a fixed 1/60-second step. `measure.js` measures it before `world.js` creates geometry. Physics and route proofs run unchanged in Node and browsers.
- `simulation.js` owns collision, rooftop checkpoints, 0.4-second respawn, warnings and the continuous final landing: release in the park to glide to the bowl, or hold overhead for a slower flutter down. A very late low capture also flutters when a shallow glide is no longer possible. The camera closes in on the picnic table as the plane lands in the salad, with a splash and reactions before results; reduced motion cuts to a still framing and splash. `bot.js` outputs only hold/release. `main.js` owns input, UI, audio and scheduling.
- Canvas scenery is code-drawn from the generated key art's palette. Skyline layers are cached; device-pixel ratio is capped at 2. Portrait uses independent vertical framing to preserve horizontal warning distance. Reduced motion removes decorative parallax, animated air marks, particles and camera bumps, replacing event effects with static cues; essential flight/hazard motion remains.
- `npm run difficulty` measures the first delayed reference input that causes an impact between checkpoints, using eight hazard-clock offsets in 50 ms steps. It reports the tightest window per district, capped at 1,500 ms:

  | Tier | District 1 | District 2 | District 3 | District 4 | District 5 |
  | --- | ---: | ---: | ---: | ---: | ---: |
  | Casual | 1500 ms | 1500 ms | 1500 ms | 1500 ms | 850 ms |
  | Rush | 1500 ms | 1500 ms | 750 ms | 800 ms | 550 ms |
  | Overtime | 1500 ms | 1350 ms | 500 ms | 550 ms | 350 ms |

  Every teaching crossing has at least 1,000 ms. The floor for any crossing is 400 ms in Casual, 300 ms in Rush and 200 ms in Overtime. Rush and Overtime also require District 5 to be within 50 ms of the tightest district and at most 60% of District 1's window. Casual's windows mostly sit at the cap, so its ramp is judged by pilot crash rates; all tiers require at least 1.5 times as many regular-pilot crashes in Districts 4–5 as in Districts 2–3. The highest regular crash rate must be in District 4 or 5, and District 5 must have at least as many crashes as District 1. In Casual, no crossing may exceed one novice crash per run. The no-input envelope utilization in route reports compares gap length with released-dive range; it is not a measure of difficulty. Controlled still-air range is reported separately by `npm run measure`.
- Casual has two qualifying choice lanes; Rush and Overtime each have one, in addition to the teaching lane.
- Each tier proof includes 135 perturbed district-entry/control-cadence trials and 240 rooftop checkpoint trials at eight hazard-clock offsets. Harder-tier occupied gaps use district trials and actual-entry checks; release-only trials cover unoccupied gaps, including headwinds. Engagement regressions reject passive release, one launch pull-up followed by coasting, and high cruising past the opening washer. A reaction test checks responding to the advertised washer warning after a short delay. Reachability and required control are both tested.
- The tiered course uses `office-picnic-v7`. On first load it carries the selected tier and mute preference from v6, leaves old records untouched, and starts fresh best times for the changed course.
- Runtime deployment is local, with no public game hosting, analytics or external runtime requests. The development server is optional once deployed.

See `docs/assets.md` for asset provenance and `reports/dive-art-qa.md` for historical dive-course QA. Earlier QA reports also describe historical courses. Physical mid-range-phone FPS and independent first-time-player success require testing on that hardware/with that participant; responsive browser emulation does not establish either.

Medals use net time after pickups and penalties. Each tier row shows its gold, silver and bronze targets and its saved Standard and Nonstop bests, graded against the current table. Both modes use the same thresholds. Regenerate tables with `node scripts/medals.mjs`; use `--tier casual --gold-quantile 0.45` to override a tier's quantile. `node scripts/playtest.mjs --tier overtime --headwinds` compares stale and regenerated thresholds on matched wind studies.
