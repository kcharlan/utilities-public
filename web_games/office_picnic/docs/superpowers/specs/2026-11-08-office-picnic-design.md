# Office Picnic — design for approval

## Intent and chosen approach

A finished, one-input browser flight game: a calm trip across a dusk city that becomes tense near the park. A clean successful run lasts 4–8 minutes; repeat runs reward better energy management and faster times.

The user selected an authored flight corridor. A deterministic simulation supports five handcrafted districts, measured traversal limits, repeatable best times, and a bot that proves the route works. Seeded procedural routes were rejected because they complicate fair warnings and comparable times. More realistic aerodynamics were rejected because predictable, readable one-input handling matters more than simulation fidelity.

This is a new project in an empty directory. There is no existing README, code, test suite, or lessons file. PKM project resolution is unregistered and global searches found no applicable flight-game decisions. No commits, pushes, or PRs are authorized.

## Fixed narrative and screens

Working title: **Office Picnic**.

Opening narrative is exactly one line: “5:01 pm. From the 40th floor to the office picnic across town.”

The title screen shows the dusk key art, that line, two run modes, local best times, and the control instruction. Starting a run throws the plane from an open office window on the 40th floor. No additional story cards interrupt flight.

The ending visibly puts the plane in a bowl of potato salad on a picnic table in the park. The results card shows elapsed run time, route distance, mode, best time when applicable, and the exact line **“Thanks for coming.”** Replay is one button away.

## Controls, states, and fairness

Hold Space, the primary mouse button over the playfield, or one finger on the playfield to pitch up, gain height, and lose speed. Release to dive and regain speed. Pitch changes smoothly and has bounded angles. Releasing after a stall recovers through a visible nose-down descent; holding through it cannot generate height.

Pause and mute are separate accessible buttons, with Escape/P and M as conveniences. UI buttons never count as flight input. Losing focus, hiding the tab, pointer cancellation, and opening pause clear held input and pause the run. Resume requires an explicit action. The clock excludes paused time.

Standard mode has a checkpoint at each district boundary, placed on a safe rooftop. A wall, rooftop, or ground impact ends the current attempt and restores the most recent checkpoint in under one second. Early route geometry limits the amount a novice can lose before the first checkpoint. A restart preserves elapsed time plus a fixed, disclosed crash penalty, so crashing cannot improve a best time.

Nonstop mode has no checkpoints: an impact starts a fresh full run from the office tower and resets its timer. It has its own best-time record. Both modes are available from the start.

Pigeons and window-washer platforms are solid hazards with forgiving collision bounds; touching them causes the same crash/reset behavior as a wall. There is no damage meter. Every crash states its cause and a short useful correction. No randomized unavoidable encounters.

## Simulation and measurement before layout

Use plain JavaScript ES modules with no dependencies, build step, network requirement, or browser globals in the simulation. Node runs the same modules as the browser. State advances at a fixed 1/60-second step; rendering interpolates state. Catch-up work is bounded and tab suspension never advances the game offscreen.

State includes position, forward speed, pitch, stall/recovery state, district, elapsed simulation ticks, checkpoint, and deterministic hazard phases. World geometry and physics constants are shared by play, measurement, bot, and tests. Collision checks account for movement across a whole step.

Before authoring any district geometry, create and run a measurement script using the final candidate flight equations. Report physical units, steady released glide ratio, minimum sustainable speed/stall threshold, maximum height gained from a full-speed pull-up before stall, and forward distance during that maneuver. Also measure usable traversal envelopes across relevant entry speeds/heights and control patterns; one ideal glide number is insufficient to prove a route.

Record constants and measured results in a generated report. If tuning changes flight equations or constants, rerun measurements and regenerate layout/proof checks. Do not hand-write claims about limits.

Each required crossing has metadata for takeoff/release location, receiving lift/safe area, entry speed band, required horizontal range and height, and the matching measured envelope. Report utilization and remaining margin for every crossing. Early crossings target 50–65% utilization; middle crossings 65–80%; the last district 85–95%. No crossing may exceed 100%, and sampled entry states need usable margin. These are design targets, not assumed measured results.

A deterministic feedback bot sees the real simulation and chooses only hold/release. It must navigate hazards, lift, and stalls without teleporting, disabling collisions, or rewriting player state. Prove each district from its documented checkpoint entry state and prove end-to-end runs in both modes. Also perturb entry height/speed and control timing to check that the nominal solution is not a single fragile input sequence.

## Five districts

Names and feature definitions are builder choices. The following is the proposed progression; exact geometry is deliberately deferred until measurements exist.

| District | New air feature | Teaching and mix |
| --- | --- | --- |
| Glass Mile | Steady AC updraft | Wide visible lift columns and generous clearances teach hold/release and speed. Introduce stationary window-washer platforms well away from the first maneuver. |
| Boiler Row | Pulsing vent | A vent visibly exhales before a lift pulse. Combine vent timing with steady AC; introduce pigeons with a perched flock and a visible flight path. |
| Sunward Roofs | Broad rooftop thermal | Warm roofs create weaker, wider lift, encouraging patient energy management. Mix steady and pulsing sources with separated hazards. |
| Crosswind Court | Horizontal wind lane | Visible ribbons show a consistent tailwind or headwind zone. Mix lift sources and clearly signed platform movement. No hidden gust randomness. |
| Park Approach | Fading thermal | A thermal weakens with height, with a visible upper boundary. Combine all prior features in tighter but measured crossings, then give a readable descent to the picnic table. |

Each district first presents its new feature in a safe setting, then mixes it with known ones. Target roughly 50–85 seconds per district, tuned from real simulated traversal times rather than idle padding. Efficient flight should improve time inside the 4–8-minute target for clean runs. Time spent recovering from mistakes may extend novice runs.

## Readability and presentation

Generate one dusk key-art image first: a small paper airplane leaving a high office window, warm illuminated windows, cool blue/violet shadows, and a distant park. Extract and record the actual working palette from that image. Backgrounds are drawn in Canvas code using those colors; key art supplies the title screen rather than becoming an oversized in-game background.

Generate separate transparent fixed-grid plane and pigeon sprite sheets. Specify uniform cells, centered pivots, gutters, exact frame counts, and no text. Inspect alignment and alpha, verify cell dimensions, and crop/normalize only if needed with an appropriate image workflow. Save production assets inside the project, with prompts and grid specifications documented. The code renderer owns the plane's pitch rotation; sprite states represent glide, strain/stall, and pigeon flap motion.

The memorable element is the tiny pale plane crossing a layered city. Quiet system typography keeps the game readable without font downloads. Canvas scenery uses a small number of cached parallax layers, warm window patterns, and district silhouettes; foreground collision surfaces are distinct from decorative buildings.

AC lift has cool rising marks; vents have a bright mouth and timed steam; rooftop heat has broad warm shimmer contours; wind lanes have horizontal ribbons; fading thermals have a visible height cap. Shape and motion identify features independently of color. Solid hazards have strong silhouettes. Platforms have visible cables and a predictable travel range. Pigeons have an advance flock cue. A hazard approaching from outside the visible area gets a directional warning before it can affect the plane.

Phone portrait and landscape both work without mandatory rotation. Preserve a minimum world-space lookahead on narrower screens by adapting camera scale and vertical framing; UI stays comfortably readable. Warning lead time is measured at maximum relative closing speed, with at least two seconds before a required response on the smallest supported viewport. If enough scenery cannot fit, warnings still show distance and direction.

```text
 Office Picnic      district / route progress      Pause  Sound
 ┌──────────────────────────────────────────────────────────┐
 │ distant skyline          lift marks        warning cue   │
 │            paper plane  →                                │
 │      warm windows       rooftop vents         park       │
 └──────────────────────────────────────────────────────────┘
 elapsed time       speed / stall cue        Hold to climb
```

HUD supplies time, district/progress, a readable speed/stall cue, and concise contextual guidance during first encounters. Avoid permanent tutorial paragraphs over the flight path.

Reduced motion removes decorative parallax, shimmer animation, camera easing, and shake. Essential plane/hazard motion remains so the game is playable. No strobe or screen flash. Focus indicators, sufficiently large touch targets, contrast, and text alternatives for controls/results are required.

## Audio

Synthesize music and effects with Web Audio after the first user gesture. Use a gentle looping harmonic foundation, then add one compatible layer per district; the last district adds rhythmic tension without a sudden volume jump. Sound does not carry exclusive gameplay information.

Discrete gameplay events have sounds: launch, lift entry, vent pulse, stall onset, recovery, hazard warning, impact, respawn, checkpoint, district entry, landing, and result/best-time confirmation. Pitch input gets a restrained transition cue rather than a repeated beep per frame. Pause/resume and menu actions have quiet feedback. Continuous wind can track speed softly. Rate-limit repeated events, cap voices, and ramp gains to avoid clicks. Mute covers both music and effects, persists locally, and works before audio initialization. Pause suspends gameplay audio and resumes cleanly.

## Persistence and packaging

Local storage holds versioned best completed time per mode, mute preference, and any first-run guidance preference. Failed or abandoned runs never set records. Handle unavailable/corrupt storage without preventing play. Show distance as deterministic route progress in world meters; results show the full completed route distance. No accounts, analytics, dependencies, or external services at runtime.

Deliver a static runnable directory with HTML/CSS/JS, local assets, Node verification scripts/tests, README with local-server and test commands, measurement/proof reports, and asset provenance. File serving is required for browser ES modules; no build is required. Do not commit, push, open a PR, or publish to hosting unless separately authorized under the user's standing Git rule. Local browser preview is part of delivery.

## Acceptance and validation

1. Run measurements before placing geometry. Produce a per-gap report with no over-limit crossing and an increasingly demanding final district.
2. Full dependency-free Node suite covers physics energy tradeoffs, stall/recovery, deterministic fixed steps, all collision types including swept impacts, reset/checkpoint/nonstop behavior, timing, route completion, bot control restrictions, hazard warning lead time, and records/settings behavior where separable from the DOM.
3. Bot clears every district and complete standard/nonstop runs with real hazards active. Report clean run duration, distance, minimum margins, and perturbation outcomes. A bot clear alone does not establish novice usability.
4. Browser play at desktop and phone sizes: complete an unaided manual route, observe every hazard/air feature and potato-salad ending, exercise crash/respawn, both modes, pause/resume, mute, records/reload, touch/keyboard/mouse, focus loss, and reduced motion. Fix observed problems and repeat affected checks plus the project's full suite after executable changes.
5. Check frame timing and draw cost at phone size with a mid-range-phone performance budget, bounded objects/voices, capped device-pixel ratio, and no unnecessary per-frame allocation. Desktop emulation is evidence of responsiveness, not proof of 60 fps on physical mid-range hardware; report any remaining hardware verification limit explicitly.
6. For novice usability, test from a fresh state without bot assistance or privileged route knowledge where possible. Use generous early margins, timely teaching, and checkpoints. If no independent first-time participant or physical phone is available, do not claim those observations occurred; report the limit with the completed manual and simulated evidence.

## Builder discretion and approval boundary

The builder owns exact physics constants, measured district geometry, music notes, hazard art details, palette hex values after key-art generation, and test implementation. Keep all choices readable and fair. Revisit the design only for a material conflict with the fixed brief.

This document is the design approval checkpoint. It does not authorize implementation until approved. No formal implementation plan has been requested by the user; after design approval, use the applicable implementation workflow without treating incidental planning as a new stopping point.
