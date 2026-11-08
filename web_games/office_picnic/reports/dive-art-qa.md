# Effective dive and readable air — verification

The user's observed problem was real: shallow released pitch could remain level or rising in AC. Release now pitches to -0.55 radians; regressions verify descent and speed gain inside AC and recovery from a nose-up approach. High approaches at 170/200/230 m can dive underneath the washer, then level out. Holding still spends airspeed and can stall inside lift.

Physics was measured before revising geometry: released glide ratio 1.57003, full-speed pull-up 28.3184 m, stall 9 m/s. The shorter measured crossings preserve ten sparse over/under encounters and all five teaching-first air types. The park approach was retuned so the nominal final landing descends continuously into the bowl.

`npm test`: **47 passing, zero failures**, including physics, collisions, engagement, guidance, records, assets, HTTP server and CLI measurement/route proof. Exact final output: `tests-output.txt`. Both modes clear **6245 m /3.88 mi in 305.35 s /5:05.35**, zero impacts. All135 perturbed district trials,25 gap checks and 10 hazard encounters pass. Maximum design-envelope utilization 91.36%; no over-limit gap. Technical proof units remain metric.

The new transparent 1536×1024 illustration shows a hardhat-wearing worker with articulated limbs, squeegee, bucket and compact platform. Two code-drawn cables replace the giant mesh. A runtime draw-call regression checks body/art alignment at 1280×800,390×844 and 844×390. Empty space between suspension cables is physically empty.

Air labels now distinguish force from motion: AC/steam/roof heat push upward, wind pushes forward and upward, thermal power fades with height. The HUD separately reports rising/descending ft/s, height in feet and mph airspeed. Pitch-up instructions explicitly say it costs speed; released dive builds speed. A brief level-out prompt prevents endless descent beneath the washer.

Browser checks at 1280×800 and 390×844 passed both collision-enabled routes, nine rendered scenes, actual PNG decoding, browser/session records and Web Audio unlock/events/pause/resume/mute. Inspected washer desktop/portrait/landscape, steam burst versus lull, and reduced-scenery control. Native Space hold then release showed rising42 ft/s followed by descending31 ft/s in AC; pause froze the run. Logs contained no errors/warnings. Short host samples reported 0.30 ms drawing p95 and 8.30 ms median frame interval. Screenshots: `revised-washer-desktop.jpg`, `revised-washer-phone.jpg`.

Fresh independent review found hidden upward tailwind force and oversized phone art detached from cable/collision geometry. Both were fixed with regressions. Review diagnostics following HUD advice at 1/6/12/24 tick cadence finished without impacts; this is automated evidence, not independent novice testing.

The reviewer rechecked both fixes and ran the focused washer/guidance tests: 10 passed, zero failures, no remaining actionable findings in those fixes. The implementer's final full suite remains 47 passing, zero failures.

Physical mid-range-phone FPS, real touch/mobile audio and independent first-time-player completion remain unverified. Normal-UI play this revision was partial; full-course completion uses Node/browser bots. Earlier QA reports describe prior geometry/handling and are historical. Temporary preview server stops at teardown; use `npm start` before playing or refreshing localhost.
