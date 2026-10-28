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
and the notification check used for the spec's section 4 spike. Installing the collector's
launchd job and the real UI arrive in later tasks. Running the app with no arguments shows a
placeholder window that asks for notification permission and reports the answer.

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

`make release` creates `build/release/Telltale.app`.

## Signing

Release builds require an existing usable code-signing identity, selected with
`SIGN_IDENTITY` (default **CodexBar Local**) and never ad-hoc, as in Anker Charge
Monitor. See the "Signing and installation" section of the
[Anker Charge Monitor README](../anker_charge_monitor/README.md). The resolver and
installer in `tools/` are ports of that project's scripts.

## How the collector runs

`Telltale --collect` is one collector run; launchd runs it every N minutes (spec section 9.3).
`CollectorRun` in `Sources/TelltaleCore/Collector/CollectorRun.swift` documents the normative run
order: take the `collector.lock` overlap guard, record the run's start, apply a pending Rebuild or a
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
| 1 | The run failed. The run record holds the first error (when the database could be opened) and the log has every step. |
| 2 | Usage error: an argument Telltale doesn't recognize. The usage goes to stderr and nothing runs, so a mistyped launchd argument never opens the UI. |

A stored rule setting that fails validation doesn't stop a run: it evaluates with the default
rules, and the log and run detail name the invalid fields.

## Notification spike

Spec section 4 builds on one executable posting notifications as Telltale when
launchd starts `Telltale --collect`, with or without the UI running. The spike
confirms that before anything depends on it:

```sh
tools/notification_check.sh build/release/Telltale.app ui-not-running
tools/notification_check.sh build/release/Telltale.app ui-running
```

Open the app once first to grant notification permission. The script loads a
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
