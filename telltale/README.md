# Telltale

## Purpose

Telltale 0.1.0 is a native macOS menu bar app that watches Codex usage metadata
and OpenAI service status and tells you when something is off. The design is in
[`docs/telltale_design_spec.md`](docs/telltale_design_spec.md), the visual rules in
[`docs/telltale_visual_design.md`](docs/telltale_visual_design.md), and the build
sequence in [`docs/telltale_implementation_plan.md`](docs/telltale_implementation_plan.md).

Current state: the SwiftPM package scaffold (every target declared, most still
placeholders), the release identifiers and runtime paths, and the notification
check used for the spec's section 4 spike. The collector, rule engine and real UI
arrive in later tasks. Running the app with no arguments shows a placeholder
window that asks for notification permission and reports the answer.

## Requirements

macOS 27 or newer, Xcode or Command Line Tools with Swift 6 and the macOS 27 SDK,
Git, Bash and ripgrep. There are no third-party Swift dependencies; zstd will be
vendored as the `CZstd` C target.

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

Pending: the spike has not been run yet, so there are no results. Record each run
here (date, macOS build, result JSON and visual confirmation) once it has.
