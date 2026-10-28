# Telltale

## Purpose

Telltale 0.1.0 is a native macOS menu bar app that watches Codex usage metadata
and OpenAI service status and tells you when something is off. The design is in
[`docs/telltale_design_spec.md`](docs/telltale_design_spec.md), the visual rules in
[`docs/telltale_visual_design.md`](docs/telltale_visual_design.md), and the build
sequence in [`docs/telltale_implementation_plan.md`](docs/telltale_implementation_plan.md).

Current state: the SwiftPM package, the vendored zstd decoder and the streaming `ZstdReader`
for Codex `.jsonl.zst` rollouts, the store, the Codex and OpenAI status sources, the usual-speed
baseline, the rule engine with its notification policy, the collector run
(`Telltale --collect`, see "How the collector runs"), the release identifiers and runtime paths,
and the notification check used for the spec's section 4 spike, the collector's launchd job and
its health, and the menu-bar status item and panel (see "Menu bar and panel"). The dashboard
window and Settings arrive in later tasks.

## Requirements

macOS 27 or newer, Xcode or Command Line Tools with Swift 6 and the macOS 27 SDK,
Git, Bash and ripgrep. There are no third-party Swift dependencies; zstd decompression is
vendored as the `CZstd` C target (see Third-party notices).

## Build and test

From `telltale/`:

```sh
make build
make test
make signing-preflight
make release
make snapshots
make acceptance
```

`make test` compiles with warnings as errors, runs every Swift test, then runs each
script in `Tests/ReleaseChecks/`:

- `check_test_isolation.sh` fails if a Swift test reaches the real home, `~/Library`
  or `~/.codex` (and `test_check_test_isolation.sh` proves the scanner catches each
  pattern). Tests inject every path.
- `test_notification_check.sh` runs `tools/notification_check.sh` against a fake app
  and a fake `launchctl` on a private `PATH`; the system `launchctl` is never invoked.
- `check_vendor.sh` recomputes the sha256 of every file listed in `Sources/CZstd/VERSION`
  and fails on a mismatch, on a `.c` or `.h` file that is not listed (the `include/czstd.h`
  shim excepted), or when `Package.swift` lacks a define that `VERSION` says was compiled.
- `check_bundle.sh` assembles and installs a bundle with synthetic signing commands
  to check release assembly, executable replacement and installer recovery. It is
  structural only and proves nothing about real certificate trust.
- `check_harnesses.sh` runs `make snapshots` and `make acceptance` and checks that the
  snapshot executable and the acceptance app carry the supported runtime (minos and SDK
  27.0), that six panel PNGs were written, that the acceptance service tests passed, and
  that the acceptance bundle is signed with identifier `com.example.telltale.acceptance`.
  It leaves both private homes in place for inspection.

`make release` creates `build/release/Telltale.app`.

`make snapshots` (`Tests/Snapshots/build.sh`) compiles the maintained app sources, without
the production lifecycle (`TelltaleMain`, `AppDelegate`), the collector entry, the source
registry or the notification check, into a separate synthetic renderer in a new 0700
directory under the OS temporary directory. It seeds a database per scene from
`Tests/Acceptance/SyntheticEnvironment.swift`, reads it through the real `LiveStore`, and
renders the panel offscreen at 340 pt in light and dark appearances: quiet, alerting and the
lasting-shift prompt (spec section 13's panel states). It checks each layout's width,
whole-point height and painted pixels, prints every PNG path, the executable and the
directory. Look at every PNG; the checks don't judge the design.

`make acceptance` (`Tests/Acceptance/build.sh`) builds the same sources with
`AcceptanceApp.swift` as the app lifecycle. It first runs the generated
`AcceptanceServiceTests` target, then assembles `Telltale Synthetic Acceptance.app` (ad-hoc
signed, identifier `com.example.telltale.acceptance`, which `LaunchAgentManager` refuses) in
a new 0700 temporary home recorded in its Info.plist as `SyntheticAcceptanceHome`. On first
launch the app seeds that home with an alerting model, a lasting-shift prompt and the
collector off. `launchctl` goes through a recording double, and Check now records a
synthetic run instead of kickstarting launchd. The builder prints the bundle path; it never
launches it.

## Signing

Release builds require an existing usable code-signing identity, selected with
`SIGN_IDENTITY` (default **CodexBar Local**) and never ad-hoc, as in Anker Charge
Monitor. See the "Signing and installation" section of the
[Anker Charge Monitor README](../anker_charge_monitor/README.md). The resolver and
installer in `tools/` are ports of that project's scripts.

## How the collector runs

`Telltale --collect` is one collector run; launchd runs it every N minutes (spec section 9.3).
`CollectorRun` in `Sources/TelltaleCore/Collector/CollectorRun.swift` documents the normative run
order: take the `collector.lock` overlap guard, close any run a killed process left `running` (as
`failed`, detail `interrupted`), record the run's start, apply a pending Rebuild or a
cold start, ingest each usage source from the 30-day lookback, fetch each status source, evaluate
every missed 5-minute point one day per transaction (points up to `backfillThrough` are backfill and
never notify), post the live notifications, prune per the retention table and record the run's end.
The plugins it runs are listed in `Sources/Telltale/Registry.swift`.

It writes only under `~/Library/Application Support/Telltale` (database and lock) and
`~/Library/Logs/Telltale/collector.log` (rotated at 5 MB, 3 archives kept), and reads `~/.codex`
(or `CODEX_HOME`) read-only. Its only network requests go to the OpenAI status page.

| Exit code | Meaning |
|---|---|
| 0 | The run succeeded, or found another run holding the lock and recorded itself as `skipped: previous run still active`. Failed notification posts are logged and counted in the run record's detail but don't fail the run. |
| 1 | The run failed. The run record holds the first error (when the database could be opened, including a lock failure other than "held") and the log has every step. If any usage source's ingest throws, the run skips evaluation and notification entirely and fails, so the next run evaluates those points with their data; a source that reports a format problem or a missing setup still lets the run evaluate. |
| 2 | Usage error: an argument Telltale doesn't recognize. The system's own launch arguments (a lone `-psn_…`, or `-NS…`/`-Apple…` flag and value pairs) still open the app. The usage goes to stderr and nothing runs, so a mistyped launchd argument never opens the UI. |

A stored rule setting that fails validation doesn't stop a run: it evaluates with the default
rules, and the log and run detail name the invalid fields (or say the stored rules couldn't be read).

Retention: responses and evaluation points are kept 180 days, run records 30 days; everything else,
including failed turns and connection events, is kept.

## Collector management and health

`LaunchAgentManager` (`Sources/TelltaleCore/Launchd/`) installs the job as
`~/Library/LaunchAgents/local.utilities.telltale.collector.plist` (spec section 9.3): it runs
`[Telltale.app's executable, --collect]` every interval (1-60 minutes, default 5), at load, as a
Background process, with stdout and stderr appended to the collector log. Turn on, Change interval
and Repair replace the plist atomically, then `launchctl bootout` (a not-loaded result is fine) and
`launchctl bootstrap gui/$UID`; Turn off boots the job out, then removes the plist. They refuse,
before writing anything, an executable that isn't the main executable of an app bundle whose
identifier is `local.utilities.telltale`, so a `swift build` product or the acceptance build never
becomes the collector. The plist records the validated, symlink-resolved executable. Every
`launchctl` call has a 10-second timeout.

`CollectorHealth` judges the collector from its run records (skipped runs count for nothing), the
plist, `launchctl print` (Loaded only) and the sources' format problems. The app's
`CollectorMonitor` checks every minute and posts one Collector health notification per episode: the
job should be on but isn't loaded, the two newest finished runs failed, no run succeeded for more
than 3 intervals (measured from turn-on, the plist's last write, until a run is on record), or a
format problem. An episode starts only when two checks in a row see it, so the minute after wake, before launchd's catch-up run, doesn't notify. The open episode is stored in the
`collectorHealthNotice` setting, so a relaunch doesn't repeat it; "Telltale's collector is running
again." follows when the rule's clear notice is on; turning the collector or the rule off ends an
episode silently.

## Menu bar and panel

The status item and its panel are ported from Brew Version's (see its README's "Settings and
native acceptance gates"): AppKit owns the delegate, the status item and an owned borderless
panel; SwiftUI supplies the content. On macOS 27 a press on the closed item starts the
expanded-interface session, whose begin shows the panel; a press while it is open is caught by
a global mouse monitor and closes it. Escape and clicks elsewhere hide it. While the item is
hidden or not yet placed, the panel opens at the top right of the menu-bar screen.

The glyph is a lamp lens: a template image while nothing is lit, and the lens with a 7 pt dot
in the most severe lamp color when a lamp lights. Its accessibility label names the lit lamps.
The panel (340 pt) shows Checked HH:MM with Check now, the lamp strip, the alert list or
"Nothing to report.", a row per model active in the last 3 hours (tok/s, usual, sparkline),
the lasting-shift prompt with Accept as usual… and Keep as abnormal, and the collector footer.
Settings and Open dashboard stay disabled until the dashboard window exists.

The app reads the database read-only (`LiveStore`): it polls every 30 seconds and watches the
database, its `-wal` file and, while they don't exist yet, the nearest existing parent
directory. Before the collector's first run it shows the waiting footer; it never creates the
database. Its few writes (Accept, Undo, Keep as abnormal) open the database only if it exists.

Only the installed copy (`/Applications/Telltale.app`, compared by its resolved main
executable) turns the collector on when the setting says it should be on, requests
notification permission and posts Collector health notifications. A copy run from elsewhere,
such as `build/release/Telltale.app`, shows the same health read-only and changes nothing.
Only one app instance runs at a time.

## Native acceptance

Automated tests, offscreen snapshots and signatures establish no native input result. Run
these checks by hand on `make acceptance`'s bundle (and the installed release where noted)
and record each one separately, with the date and macOS build. One missed press fails the
check. The Settings, Open dashboard and launch-at-login checks join this list with the
dashboard tasks.

- Lens glyph, amber dot and accessibility label. Press the status item repeatedly, slowly
  and quickly; every press must open or close the panel exactly once, with the whole panel,
  header and footer included, on-screen. Reopen the app from Finder, or click a notification,
  then press the icon once: the panel must close. Click outside the panel, then press the
  icon once: it must open. Run these with the menu bar manager running; while it hides the
  item, Finder reopening places the panel at the top right.
- Escape closes the panel; the panel also appears over a full-screen app and on the current
  desktop Space.
- Check now: the checked time moves (the acceptance double records a synthetic run).
- **Add red alert** lights Errors red and turns the glyph's dot red; VoiceOver reads the lit
  lamps from the status item and the lamp strip.
- Accept as usual… with its date, then Undo; Keep as abnormal hides the prompt.
- **Test notification** shows a visible notification, and clicking it opens the panel.
  **Test posting failure** shows the warning with Retry, and Retry clears it.
- **Light** and **Dark**: both appearances are legible, and the lit lamps keep their colors.
- In the installed release only: the collector turns on at first launch, and no launchd job
  exists for the acceptance bundle (`launchctl print gui/$UID/local.utilities.telltale.collector`
  names the installed executable).

### Results

Native results are recorded separately from automated ones.

| Check | Result |
| --- | --- |
| All of the above | Not yet run |

## Notification spike

Spec section 4 builds on one executable posting notifications as Telltale when
launchd starts `Telltale --collect`, with or without the UI running. The spike
confirms that before anything depends on it:

```sh
tools/notification_check.sh build/release/Telltale.app ui-not-running
tools/notification_check.sh build/release/Telltale.app ui-running
```

Grant notification permission first: the installed app asks at launch; a copy elsewhere never
asks (see "Menu bar and panel"), but the check itself asks when permission is undetermined. The script loads a
one-shot launchd job named `local.utilities.telltale.notification-check` into
`gui/$UID` from a private temporary directory (never `~/Library/LaunchAgents`),
waits up to 20 s for the result JSON, prints it and boots the job out. The run
passes when `posted` and `delivered` are true, `bundle` is
`local.utilities.telltale` and a banner from **Telltale** appears. Delivery is
confirmed by finding the request posted in that run among the delivered
notifications, matched by its request identifier.

## Spike results

Passed on 2026-10-27, macOS 27.0.1 (26A434). The bundle was a signed copy of the
`make release` build of the Task 1 scaffold. Notification permission was granted from the
placeholder app first.

| Mode | Time | Result JSON | Visual |
|---|---|---|---|
| `ui-running` | 17:33:15 EDT | `{"authorization":"authorized","bundle":"local.utilities.telltale","delivered":true,"error":null,"posted":true}` | Kevin saw the banner from Telltale |
| `ui-not-running` | 17:33:50 EDT | same as above | Kevin saw the banner from Telltale |

The first run was started with `ui-not-running`, but the placeholder's window had been
closed without quitting, so its process was still running. That run is recorded as
`ui-running`. The second run had no Telltale process before or after it. Notifications from
a launchd-started `Telltale` therefore carry Telltale's identity in both states, and the
one-executable design (spec §4) stands.

## Rule replay against real data

On 2026-10-27, the rule engine at commit 4ef61b2 was replayed against Kevin's real Codex
history, read-only from a scratch package outside the repository. Nothing from that data is
committed. Responses were ingested from 2026-09-13, and evaluation points ran from
2026-09-13 through Oct 27 with the default rules. The incident rule was not stepped (no
network).

| Spec §12 anomaly | No user actions | Accepting each lasting-shift prompt |
|---|---|---|
| Oct 13 slower | missed | caught, 07:50, worst 0.72× |
| Oct 16–17 faster | caught | caught, worst 1.68× |
| Oct 22 evening slower | missed | caught, 22:05, red, worst 0.59× |
| Oct 26 morning slower (4 capacity failures) | missed (failures caught) | caught, 10:25, red, worst 0.58× |
| Oct 27 slower from about 08:30 | missed | caught, onset 08:15, fired 08:40 |

- **With acceptances:** the run fired 7 slowdown notifications over Oct 20–27, the same as
  §12, plus 13 other speed episodes (6 slower, 7 faster). These weren't checked against
  status posts.
- **Without acceptances:** the model sped up from about Oct 8–14. §8 keeps the earlier usual
  until Kevin accepts, so later slowdowns read as normal, and about 20 "faster" episodes fire
  instead.
- **Thin data:** about half of the daytime 5-minute windows were too thin to judge (fewer
  than 10 qualifying responses), mostly on low-volume days.

Kevin reviewed these results and kept the defaults unchanged. The lasting-shift prompt and
Accept are how usual follows a lasting change.

## Third-party notices

Telltale vendors the decompression half of [zstd](https://github.com/facebook/zstd) v1.5.7
under `Sources/CZstd/`, copied byte for byte from `colophon/vendor/zstd/` (the same upstream
release Colophon uses). zstd is dual-licensed BSD-3-Clause or GPLv2; Telltale uses it under
the BSD-3-Clause terms. The license text is `Sources/CZstd/LICENSE`, and
`Sources/CZstd/VERSION` records the source URL, the sha256 of the upstream archive and of every
file, the excluded upstream files, and the compile-time defines that `Package.swift` applies
(`XXH_NAMESPACE=ZSTD_`, `ZSTD_DISABLE_ASM=1`, `ZSTD_LEGACY_SUPPORT=0`). `Tests/ReleaseChecks/check_vendor.sh`
keeps the tree and that record in agreement. Only `Sources/CZstd/include/czstd.h`, a shim that
includes the two public zstd headers, is Telltale's own. These notices do not assign a new
license to Telltale.
