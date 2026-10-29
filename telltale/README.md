# Telltale

## Purpose

Telltale 0.3.0 is a native macOS menu bar app that watches Codex and Claude Code usage metadata
and OpenAI and Claude service status and tells you when something is off. The design is in
[`docs/telltale_design_spec.md`](docs/telltale_design_spec.md), the visual rules in
[`docs/telltale_visual_design.md`](docs/telltale_visual_design.md), and the build
sequence in [`docs/telltale_implementation_plan.md`](docs/telltale_implementation_plan.md).

Current state: the SwiftPM package, the vendored zstd decoder and the streaming `ZstdReader`
for Codex `.jsonl.zst` rollouts, the store, the Codex and Claude Code usage sources and their status sources, the usual-speed
baseline, the rule engine with its notification policy, the collector run
(`Telltale --collect`, see "How the collector runs"), the release identifiers and runtime paths,
and the notification check used for the spec's section 4 spike, the collector's launchd job and
its health, the menu-bar status item and panel (see "Menu bar and panel"), the dashboard
window with its model, collector and Settings views (see "Dashboard"), and the deployment to
`/Applications` (see "Deploy").

## Requirements

macOS 27 or newer, Xcode or Command Line Tools with Swift 6 and the macOS 27 SDK,
Git, Bash and ripgrep. There are no third-party Swift dependencies; zstd decompression is
vendored as the `CZstd` C target, and the readout font is bundled in `Resources/Fonts` (see
Third-party notices).

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
script in `Tests/ReleaseChecks/`. Nothing is left in `$TMPDIR` or the Darwin user temp dir
(`getconf DARWIN_USER_TEMP_DIR`):

- `make build`, `make release` and `make test` run with `TMPDIR` in the project's ignored
  `.build/tmp/`, inside `tools/check_no_temp_leaks.sh`. The checker nests a private run directory
  there and removes it afterwards, so the Swift toolchain's own leftovers (honored
  `TemporaryDirectory.*` folders and package lock files) go with it.
- It fails the run if it left a Telltale entry inside that directory, in the given `TMPDIR` or in
  the Darwin user temp dir. A Telltale entry is a name starting `telltale-` or `telltale_`, or
  containing `_telltale-` or `_telltale_`, such as a SwiftPM lock file named after a Telltale
  package path. The lock files of the package being built are the toolchain's own.
- Each compile also puts one `TemporaryDirectory.*` in the Darwin user temp dir whatever `TMPDIR`
  says. The checker lists those before the run, then removes only new ones whose sole content is
  an empty `.keep-directory` (that file, then `rmdir`), and reports the count. Anything from
  before the run, or with other content, is left alone. `make snapshots` and `make acceptance`,
  whose homes stay in `TMPDIR` on purpose, get only this sweep (`--sweep-only`).
- Every test and script cleans up its own scratch, and scripts that build packages point
  `TMPDIR` into that scratch. The deploy tool gives `make release` a `TMPDIR` inside its own build
  scratch, which it removes, and then sweeps the build's new marker-only `TemporaryDirectory.*`
  from the Darwin user temp dir.

- `check_test_isolation.sh` fails if a Swift test reaches the real home, `~/Library`,
  `~/.codex`, the real login item (`SMAppService`, or `LoginItem()` with its default service) or
  the app's real preferences (`UserDefaults.standard`); `test_check_test_isolation.sh` proves the
  scanner catches each pattern. Tests inject every path and these services.
- `test_check_no_temp_leaks.sh` proves the leak check names a leaked directory or lock file
  (in either temp dir), ignores entries from before the run, other tools' entries and the built
  package's own locks, passes a failing command's status through, sweeps only new marker-only
  `TemporaryDirectory.*`, and that `make build` and `make test` run SwiftPM under `.build/tmp/`.
  It uses a fake Darwin user temp dir and a fake `swift`.
- `test_notification_check.sh` runs `tools/notification_check.sh` against a fake app
  and a fake `launchctl` on a private `PATH`; the system `launchctl` is never invoked.
- `check_vendor.sh` recomputes the sha256 of every file listed in `Sources/CZstd/VERSION`
  and fails on a mismatch, on a `.c` or `.h` file that is not listed (the `include/czstd.h`
  shim excepted), or when `Package.swift` lacks a define that `VERSION` says was compiled.
- `check_bundle.sh` assembles and installs a bundle with synthetic signing commands
  to check release assembly (including the bundled fonts, byte for byte), executable
  replacement and installer recovery. It is
  structural only and proves nothing about real certificate trust.
- `check_harnesses.sh` runs `make snapshots` and `make acceptance` and checks that the
  snapshot executable and the acceptance app carry the supported runtime (minos and SDK
  27.0), that twelve panel PNGs and eighteen dashboard PNGs were written, that the acceptance service tests passed, and
  that the acceptance bundle is signed with identifier `com.example.telltale.acceptance`.
  Both build inside its own scratch (`TELLTALE_HARNESS_ROOT`) in the Darwin user temp dir,
  where the snapshot executable requires its home even though the suite points TMPDIR into
  `.build/tmp/`, and it removes the scratch on success and failure, so the suite keeps no PNGs; run `make snapshots` to look at them.

`make release` creates `build/release/Telltale.app`, with the two Barlow Semi Condensed
fonts and `OFL.txt` in `Contents/Resources/Fonts`.

`make snapshots` (`Tests/Snapshots/build.sh`) compiles the maintained app sources, without
the production lifecycle (`TelltaleMain`, `AppDelegate`), the collector entry, the source
registry or the notification check, into a separate synthetic renderer in a new 0700
directory under the OS temporary directory. It seeds a database per scene from
`Tests/Acceptance/SyntheticEnvironment.swift`, reads it through the real `LiveStore`, and
renders the panel offscreen at 340 pt in light and dark appearances: quiet, alerting, acknowledged and the
lasting-shift prompt (spec section 13's panel states), two providers with colliding Claude names, and the arrival note. It also renders the dashboard window at
its default width (1100 pt) in both appearances: the model view, as tall as its whole scroll
content (14 days of speed dots with a fast spell, a slow morning with failed turns under a
provider incident, workload and events), an idle Claude sidebar, a Claude model with fast mode, and the collector view's problem state at 760 pt
(the last run failed), and Settings as tall as its content, with an invalid Rules entry (the
slower rule's clear band equal to its trigger) and the watched-components checklist with names the
synthetic status page no longer lists. Four more Settings scenes show normal, not-set-up, format-problem and backfilling providers in both appearances. It registers the bundled fonts first and fails if they don't register.
It checks each panel layout's width, whole-point height and painted pixels, prints every PNG path, the executable and the
directory, followed by the `rm -r` command that removes it. Look at every PNG; the checks
don't judge the design. A manual run keeps its directory (SwiftPM's lock files included)
until you remove it.

`make acceptance` (`Tests/Acceptance/build.sh`) builds the same sources with
`AcceptanceApp.swift` as the app lifecycle. It first runs the generated
`AcceptanceServiceTests` target, then assembles `Telltale Synthetic Acceptance.app` (ad-hoc
signed, identifier `com.example.telltale.acceptance`, which `LaunchAgentManager` refuses) in
a new 0700 temporary home recorded in its Info.plist as `SyntheticAcceptanceHome`. On first
launch the app seeds that home with an alerting model, a lasting-shift prompt and the
collector off. Open dashboard and Settings open the dashboard window (its collector view is
read-only here, since only the installed copy may change launchd state), and Light and Dark
apply to it too. Its Settings store rules, watched components (from a synthetic status page) and
the appearance in the synthetic home; the interval, Rebuild and Open at login are unavailable,
and its login item is a double that never reaches `SMAppService`.
`launchctl` goes through a recording double, and Check now records a
synthetic run instead of kickstarting launchd. The builder prints the bundle path and the
`rm -r` command that removes its home; it never launches the app.

## Signing

Release builds require an existing usable code-signing identity, selected with
`SIGN_IDENTITY` (default **CodexBar Local**) and never ad-hoc, as in Anker Charge
Monitor. See the "Signing and installation" section of the
[Anker Charge Monitor README](../anker_charge_monitor/README.md). The resolver and
installer in `tools/` are ports of that project's scripts.

## Deploy

The release installs as `/Applications/Telltale.app` through the root deployment CLI,
`tools/deploy_telltale.mjs`, a port of Anker Charge Monitor's. Deploy only reviewed, merged
`main` after the full suite and the root deployment suites pass; a real deployment needs the
owner's authorization. From the repository root:

```sh
node tools/deploy_telltale.mjs --dry-run
node tools/deploy_telltale.mjs
node tools/deploy_telltale.mjs --audit
zsh tools/check_local_deployments.zsh
```

`make install` (or `make deploy`) from `telltale/` runs the same CLI. It copies the tracked,
staged build inputs (including the bundled fonts) to a private scratch directory, runs
`make release` there with the `SIGN_IDENTITY` identity, validates the bundle (identifiers,
version, macOS 27 minimum, signature), activates it with `tools/install.sh`, and writes the
provenance receipt `~/Library/Scripts/.telltale-native.json`. Each deployment keeps a
private backup under `~/.utilities-deploy-backups/telltale/`; `--rollback BACKUP` restores
one, and any failure restores the previous app. `--audit` checks the installed app against
current source without building or running anything.

An older release cannot decode a `readProblem` stored by this release. After
rollback, that row can block the affected provider's ingest, Collector health,
and the Settings provider list. Stop Telltale and its collector, then delete
only the affected source row (replace `example` with the affected source ID):

```sh
sqlite3 "$HOME/Library/Application Support/Telltale/telltale.sqlite" "DELETE FROM source_state WHERE source = 'example';"
```

The next collector run recreates the row. Other source rows and collected data
are preserved.

The deployer never runs `launchctl` and leaves the database, the log and the collector's
job plist alone. A running Telltale keeps running the old release: quit and reopen it. The
installed copy turns the collector on at launch when it should be on and its plist is
missing. After deploying, if the collector is on, open Collector in the dashboard: Installed
must be lit green and Repair must not be offered (spec section 13); if it is, press it. Then
run the installed-release checks under "Native acceptance". The full contract is in the
[deployment guide](../docs/local_deployment_sync.md#telltale-app-deployment).

## How the collector runs

`Telltale --collect` is one collector run; launchd runs it every N minutes (spec section 9.3).
`CollectorRun` in `Sources/TelltaleCore/Collector/CollectorRun.swift` documents the normative run
order: take the `collector.lock` overlap guard, close any run a killed process left `running` (as
`failed`, detail `interrupted`), record the run's start, apply a pending Rebuild or a
cold start, ingest each usage source from the 30-day lookback, fetch each status source, evaluate
each provider and status source independently at every missed 5-minute point, one day per
transaction, post live notifications, prune per the retention table and record the run's end.
Each unit keeps its own progress and backfill boundary; historical points never notify. A new
provider starts backfilling when its source is ready, while other providers continue live.
The plugins it runs are listed in `Sources/Telltale/Registry.swift`.
A changed Codex database that Codex has closed is read from a private APFS clone;
an unchanged closed file is skipped. See the closed-WAL policy in spec sections 6 and 11
(`docs/telltale_design_spec.md`).

It writes only under `~/Library/Application Support/Telltale` (database, locks and temporary `codex-snapshots`) and
`~/Library/Logs/Telltale/collector.log` (rotated at 5 MB, 3 archives kept), and reads `~/.codex`
(or `CODEX_HOME`), `~/.claude` (or `CLAUDE_CONFIG_DIR`) and, when present, `~/.config/claude` read-only. Its only network requests go to the OpenAI and Claude status pages.

| Exit code | Meaning |
|---|---|
| 0 | The run succeeded, or found another run holding the lock and recorded itself as `skipped: previous run still active`. Failed notification posts are logged and counted in the run record's detail but don't fail the run. |
| 1 | The run failed. The run record holds the first error (when the database could be opened, including a lock failure other than "held") and the log has every step. A throwing ingest skips that provider's evaluation and retries it next run; other providers continue, and a status source is skipped if all its providers' ingests threw. An unavailable provider with prior progress still evaluates; one without progress waits until ready. |
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
plist, `launchctl print` (Loaded only) and the sources' format and read problems. The app's
`CollectorMonitor` checks every minute and posts one Collector health notification per episode: the
job should be on but isn't loaded, the two newest finished runs failed, no run succeeded for more
than 3 intervals (measured from turn-on, the plist's last write, until a run is on record), or a
format or read problem that two consecutive collector runs report (the lamp and panel message show from the first
report; see the shared problem policy in the design spec, section 6.5). An episode starts only when two checks in a row see it, so the minute after wake, before launchd's catch-up run, doesn't notify. The open episode is stored in the
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

The glyph is a lamp lens: a template image while nothing is lit, a filled dot in the most severe
new alert's color, or a ring in the most severe lit color when all alerts are acknowledged. Its
accessibility label names the lit lamps and marks acknowledged lamps.
The panel (340 pt) shows Checked HH:MM with Check now, the lamp strip, the alert list or
"Nothing to report.", a row per model active in the last 3 hours (tok/s, usual, sparkline;
a model in a slower or faster episode shows its tok/s and sparkline in the lamp color),
the lasting-shift prompt with links to the provider's status-page incidents in its period,
Accept as usual… and Keep as abnormal, and the collector footer. The row uses the
current stored speed evaluation for tok/s and mix-matched usual. Numbers
are dashes when the point is stale or has no matched responses, including a new
model or an unfamiliar prompt mix. Thin matched data retains its numbers and
thin-data note; learning notes remain when appropriate, while a ready idle model
has no note. The dashboard's last-hour readout is independent.
Open dashboard and the gear (Settings) open the dashboard window (see "Dashboard").
Use Acknowledge on an alert, or Acknowledge all for the new alerts shown, to reset the attention
dot while leaving the lamp lit. Acknowledged rows show a hollow diamond and their acknowledgement
time; Mark as new restores their attention. A new episode, higher severity, or another counted
failure makes the relevant alert new again. Acknowledging also removes delivered notifications
for the selected alert threads.
After a newly added provider finishes its first backfill on an existing installation, a
standing arrival note names the ready models. If its stored models are all idle, the note says none responded in the sidebar window. Open the provider's first model or dismiss the
note; dismissal persists across relaunches and rebuilds. The footer shows the app version; its help gives the build number.

The app reads the database read-only (`LiveStore`): it polls every 30 seconds and watches the
database, its `-wal` file and, while they don't exist yet, the nearest existing parent
directory. Before the collector's first run it shows the waiting footer, or the collector's
problem with a red Collector lamp when health finds one (not loaded, say). The app never creates
the database (ruling R27): its writes (Accept, Undo, Keep as abnormal, settings and the stored
collector-health notice) use `Store.Mode.readWriteExisting`, which opens only a database the
collector already created and migrated. Until then the health notice is held in memory.

Only the installed copy (`/Applications/Telltale.app`, compared by its resolved main
executable) turns the collector on when the setting says it should be on, requests
notification permission and posts Collector health notifications. A copy run from elsewhere,
such as `build/release/Telltale.app`, shows the same health read-only and changes nothing.
Only one app instance runs at a time.

## Dashboard

The dashboard window (`DashboardWindowController`, ported from Brew Version's Settings window
controller) is one reused, resizable window, 1100 × 760 pt by default and at least 860 × 600.
Opening it switches the app to a regular app with a Dock icon, activates it and brings the
window to the current Space; closing it returns the app to a menu-bar-only accessory. Open
dashboard shows the last section shown, or the first model; Settings shows the Settings
section. It is dark by default and follows the stored appearance setting (spec section 9.4).

The sidebar lists each provider's models with a response in the last 14 days (a provider whose
source isn't set up shows "Not set up", dimmed; one whose models are all older shows "No
responses in the last 14 days"; names stay unique over every stored model, spec section
[9.2](docs/telltale_design_spec.md#92-dashboard-window)), then Collector and Settings. The sidebar foot shows the app version with the build number in help. A model’s view shows the lamp strip with
Collector, the alerts, Speed against usual (6h, 24h, 7d or 14d: last-hour tok/s and median
response time against usual, hourly speed-index dots colored by the episode in effect,
the dashed usual line, the provider's own status-page incidents as dashed amber bands, and
failed-turn markers, drawn with Swift Charts), the lasting-shift prompt with links to its
period's incidents, Accept as usual… with its date picker, drift, learning and missing-history notes,
Prompt sizes (the last 3 hours against usual; the 300k+ bar takes the Load lamp's color while
it is lit) beside Workload (median prompt, responses an
hour, active sessions, cached input, reasoning and subagent shares, effort mix and the usage
limit). Claude's workload also shows provider-wide automatic compactions, blocked time and the
median point of the last five; a rejected usage limit appears for five hours. Events are newest
first, with Undo on each live acceptance (undoing an older one
asks first, since later acceptances are undone too). While the window is closed, store changes
reread nothing; opening it reads everything again. Readout numbers use Barlow Semi
Condensed, registered for the process at launch; if it can't be registered, the system font
stands in and one line is logged.
The dashboard alert list offers the same Acknowledge, Acknowledge all and Mark as new controls
as the panel, scoped to its displayed rows.

The collector view shows the four collector lamps, any problem, the schedule, the last and
next run, the last success and the job label, Run now, Turn on or Turn off, Repair (only when
the job's plist doesn't match this app), Change interval (opens Settings), Show log file, and
the last lines of `collector.log`, failures in red. Turn on, Turn off and Repair change launchd
state, so only the installed copy offers them; any other copy says so and shows the rest
read-only. Turn off appears only once the collector's first run has created the database, since
the off choice is stored there; before then the view says it can be turned off after its first
run. A failed read of the database shows as its own line, apart from an action's failure.

Settings (spec section 9.4) has six parts:

- **Rules**: one row per rule with its switch, its parameters (fractions of usual as percentages,
  durations in minutes, prompt sizes in thousands of tokens), Notify, Notify when it clears and
  Reset to default. An entry is saved on Return or when focus leaves it, and only when the edited
  rules pass validation; otherwise it stays in its field, outlined in red, with the validation
  message beneath, and nothing is stored. When the stored rules can't be used, the defaults the
  collector falls back to are shown with a note.
  Context compactions fires at the configured count of automatic compactions in its time window
  (by default two in 60 minutes), and clears when that window contains none. Manual compactions
  do not count; precomputed compactions do.
- **Collector**: the interval (1-60 minutes) and the on/off switch. While the collector is on, a
  new interval rewrites the plist and reloads the job before it is stored; a launchctl failure or
  a refused executable shows in the same words as the collector view.
- **Providers**: each usage source's state, version, history and data folder, with a per-provider
  Rebuild action disabled while its history is being read or a request is pending.
- **Watched status components**: a checklist of each status page's components, followed by saved
  names the page no longer lists, marked "(not on the status page now)".
- **Data**: the retention table (not editable) and Rebuild all providers, which asks first, then
  stores the request and kicks the job so the collector applies it.
- **General**: Open at login and the dashboard appearance (Dark, Light or Match system), applied
  to the window at once.

Every change is stored through the same read-write-existing path as Accept, so until the
collector's first run creates the database Settings shows the defaults read-only and says so. The
app also waits for the collector to upgrade an older database before accepting writes. The
interval, the collector switch, Rebuild and Open at login change launchd or login-item state, so
only the installed copy offers them; another copy says so.

Open at login is on by default, applied once (ruling R32): the installed copy's first launch
registers the app as a login item (`SMAppService.mainApp`) unless the stored setting is already
off, and records that it did in the app's own preferences
(`local.utilities.telltale.openAtLoginDefaultApplied`), since the database may not exist yet.
After that, launch never registers; only the Settings switch does. Removing Telltale in System
Settings > Login Items therefore stands, and at the next launch the stored setting follows the
system (where the database exists). The switch stores the choice first and changes the login item
only once that worked; if the login-item change fails, the stored setting goes back to the
system's state. Login-item approval is reread whenever the dashboard window becomes key.

## Native acceptance

Automated tests, offscreen snapshots and signatures establish no native input result. Run
these checks by hand on `make acceptance`'s bundle (and the installed release where noted)
and record each one separately, with the date and macOS build. One missed press fails the
check.

- VoiceOver reads the version in the panel footer and dashboard sidebar; hovering each shows the build number.
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
- First acknowledge the existing alerts, then **Add red alert** and acknowledge it. Check the
  glyph, row and VoiceOver against the acknowledgement contracts in spec §9.1. **Add failed
  turn** fills the dot red again and shows the count beyond the acknowledgement. Exercise
  Acknowledge all and Mark as new; quit and reopen to check that acknowledgements persist.
- The lasting-shift prompt links to "Synthetic slow responses", which opens its synthetic
  status-page address in the browser.
- Accept as usual… with its date, then Undo; Keep as abnormal hides the prompt.
- **Test notification** shows a visible notification, and clicking it opens the panel.
  **Test posting failure** shows the warning with Retry, and Retry clears it.
- **Light** and **Dark**: both appearances are legible, and the lit lamps keep their colors.
- Open dashboard from the panel: the dashboard window opens on the current desktop Space with
  a Dock icon, on the first model (Example); pressing it again while the window is behind other
  windows brings the same window forward. Close it: the Dock icon goes away. Open it from
  another Space: it moves to that Space.
- The gear (Settings) in the panel opens the same window on its Settings section.
- Settings, in the acceptance bundle: edit the Slower than usual threshold and press Return, then
  Tab out of another field after editing it; both are saved (reopen Settings to check). Enter a
  clear band equal to the threshold: the field turns red with "The clear band must be stricter
  than the trigger", and leaving the field doesn't save it. Reset to default restores the row.
  Toggle a rule's switch, Notify and Notify when it clears. Check "Example Chat" and uncheck a
  "(not on the status page now)" name. Switch Dashboard appearance through Dark, Light and Match
  system (with the system in each appearance): the window follows at once, and after **Light** or
  **Dark** the next Settings choice wins. The interval, Collector on, Rebuild from Codex logs… and
  Open at login are unavailable, with "Only Telltale in Applications can change this." VoiceOver
  reads each rule parameter by its name (such as "Slower than usual clear band"). The switches
  show their on state in the accent color in both appearances (offscreen snapshots don't).
- In the dashboard, select Sample, Collector and Settings in the sidebar; switch Speed against
  usual through 6h, 24h, 7d and 14d; Accept as usual… with a date, then Undo from Events.
  **Light** and **Dark** apply to the dashboard, and the readouts use Barlow Semi Condensed.
- The collector view shows the four lamps, the run facts and the log lines; Turn on, Turn off
  and Repair stay unavailable in the acceptance bundle, with the note saying why, and Show log
  file reveals the log in Finder.
- In the installed release only: the collector turns on at first launch, and no launchd job
  exists for the acceptance bundle (`launchctl print gui/$UID/local.utilities.telltale.collector`
  names the installed executable).
- In the installed release only, acknowledge existing rule alerts, boot out the collector job,
  and acknowledge its problem. Check the footer and glyph against spec §9.1. Wait past a collector
  interval: the not-loaded problem stays acknowledged. Repair the job and verify the next check
  clears the acknowledgement. Changing next-try text is covered by `collectorAcknowledgementFollowsProblemKeys`.
- In the installed release only, launch at login: after the first launch, System Settings >
  General > Login Items lists Telltale (allowed, or asking for approval; if it asks, Settings shows
  "Approval required in System Settings" with Open Login Items Settings, and approving it there
  turns the description to "Enabled" when the dashboard window is next focused). Log out and in:
  Telltale's status item appears. Turn Open at login off in Settings: Telltale leaves Login Items,
  and a relaunch doesn't add it back. Turn it on again in Settings: Telltale is listed again. Then
  turn Telltale off in System Settings' Login Items instead and relaunch, twice: Telltale must not
  re-register itself, and Settings shows Open at login off.
- In the installed release only, Settings after the first run: change the interval to 2 minutes;
  the plist's `StartInterval` is 120 and `launchctl print` still finds the job. Rebuild from Codex
  logs… asks first; confirming logs "Rebuilding from Codex logs" in `collector.log` within a minute
  and keeps accepted baselines. Before the first run (a fresh install), Settings says "You can
  change settings after the collector's first run." and changes nothing.
- In the installed release only, closed Codex database: avoid a Colophon scan during the check,
  and leave Codex idle until neither the highest-numbered `~/.codex/thread_history_N.sqlite` nor the
  highest-numbered `~/.codex/logs_N.sqlite` has a `-wal` beside it. The next collector
  run must log no format problem, and no Collector health notification may follow. Record it
  apart from the sidebar check; it does not establish the cause of an earlier incident. Keep the
  evidence (log lines, times) outside the repository.
- In the installed release only, after Codex quits with recent activity: the next collector run
  logs no format problem, `~/Library/Application Support/Telltale/codex-snapshots` is empty,
  and neither closed Codex database has a `-wal` or `-shm` beside it. Record this separately
  from the 0.2.1 check above.
- In the installed release only, sidebar window: a model whose last response is more than 14 days
  old is absent from the dashboard sidebar (the Codex group shows "No responses in the last 14
  days" if every model is that old). Keep the evidence outside the repository.

### Results

Native results are recorded separately from automated ones.

Run by Kevin on 2026-10-28, macOS 27.0.1 (26A434), on `make acceptance`'s bundle.

| Check | Result |
| --- | --- |
| Menu bar, panel, notifications, Light and Dark (acceptance bundle) | Passed |
| Dashboard, Settings and Open dashboard checks (acceptance bundle) | Passed after one fix: Match system rendered Light under a Dark system and ignored system changes, because the harness's Light/Dark buttons pinned `NSApp.appearance`. Fixed in a604a1f; Match system then passed before and after pressing those buttons |
| Settings (acceptance bundle) | Passed |
| Installed 0.1.0, first launch: status item, notification prompt, collector on with the installed executable, Collector view Installed green with no Repair, Login Items listing | Passed (2026-10-28). The "before the first run" Settings message wasn't observed: the first run finished in about 45 s, before Settings was opened |
| Installed 0.1.0, Rebuild from Codex logs… | Failed: confirming stored no request and started no run, because closing the alert cleared the confirmation flag before the Rebuild task checked it. Fixed in 0.1.1, along with the same pattern in the Undo confirmation |
| Installed 0.1.0, dashboard sidebar | Failed: `gpt-6.1-sol`, `gpt-6-sol` and `gpt-5.6-sol` were all named "Sol". From 0.1.1, names keep the version ("6.1 Sol") |
| Installed 0.1.1: interval to 2 minutes, Rebuild, log out and in, Open at login off and on, removal in Login Items | Not yet run |
| 0.2.0 acceptance bundle and installed release, including arrival note and Claude readouts | Not yet run |
| Installed 0.2.1, closed Codex database: no format problem logged and no Collector health notification | Not yet run |
| Installed release, closed Codex snapshot read and cleanup | Not yet run |
| 0.3.0 acceptance bundle acknowledgement and failed-turn re-arm | Not yet run |
| Installed 0.3.0 Collector acknowledgement and repair | Not yet run |
| Installed 0.2.1, sidebar window: a model unused for 14 days is absent from the sidebar | Not yet run |
| Market Atlas complete suites (`Calculation tools/backtest`) | UNMET: not run. Required because this branch changed `tools/check_local_deployments.zsh`, the static audit's child runner. Its data, compiler venv and `node_modules` aren't prepared, and no Market Atlas code changed; Kevin approved proceeding without them on 2026-10-28 |

The panel keeps following the system when Dashboard appearance is Light or Dark; Kevin
confirmed that is the intended behavior (spec section 9.4).

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

The rule engine can be replayed against private usage history in a private scratch home.
Keep the source data and results outside the repository; publish only a non-sensitive
qualitative assessment.

A read-only replay with both usage sources completed in an isolated home without status
network requests or notifications. Recorded Claude failures used the supported provider-side
categories, and compaction episodes met the automatic-compaction trigger. This check does not
establish whether every historical anomaly was detected or whether the defaults suit future use.

## Third-party notices

Telltale vendors the decompression half of [zstd](https://github.com/facebook/zstd) v1.5.7
under `Sources/CZstd/`, copied byte for byte from `colophon/vendor/zstd/` (the same upstream
release Colophon uses). zstd is dual-licensed BSD-3-Clause or GPLv2; Telltale uses it under
the BSD-3-Clause terms. The license text is `Sources/CZstd/LICENSE`, and
`Sources/CZstd/VERSION` records the source URL, the sha256 of the upstream archive and of every
file, the excluded upstream files, and the compile-time defines that `Package.swift` applies
(`XXH_NAMESPACE=ZSTD_`, `ZSTD_DISABLE_ASM=1`, `ZSTD_LEGACY_SUPPORT=0`). `Tests/ReleaseChecks/check_vendor.sh`
keeps the tree and that record in agreement. Only `Sources/CZstd/include/czstd.h`, a shim that
includes the two public zstd headers, is Telltale's own. The dashboard's readout font, [Barlow Semi Condensed](https://github.com/jpt/barlow) Regular and Medium
(Copyright 2017 The Barlow Project Authors), is bundled under `Resources/Fonts/` and in the app's
`Contents/Resources/Fonts`, copied byte for byte from the Google Fonts repository. It is licensed
under the SIL Open Font License 1.1, whose text is `Resources/Fonts/OFL.txt` and ships beside the
fonts in the app. `Resources/Fonts/SOURCE.md` records each file's source URL and sha256.

These notices do not assign a new
license to Telltale.
