# Brew Version

Brew Version reads current formula and cask versions from Homebrew's public API.
The Swift `brew-version` command supports one-time lookups and watching until a
version changes. The shared core also supports the planned native menu bar app,
which will watch chosen packages and notify about their updates without running
`brew` or upgrading packages.

This native macOS app is a deliberate exception to the UI Shapes defaults in
the repository's `agents.md`.

## Requirements

- macOS 14 or newer.
- Xcode or the Command Line Tools providing Swift 6.
- Node.js for deployment tooling.
- Network access to Homebrew's HTTPS public API for lookups.

The Swift package has no external dependencies. The CLI needs neither `curl`
nor `jq`. The app bundle is named `Brew Version.app`, uses the
`local.utilities.brew-version` bundle identifier and `BrewVersion` executable,
and is a menu bar app without a Dock icon. The app is not sandboxed because it
reads Homebrew installation folders and application bundles. App packaging and
deployment are separate deliverables.

## Build and test

From the repository root:

```sh
make -C brew_version build
make -C brew_version test
```

The test target runs the complete Swift Testing suite, including transport,
lookup, CLI parsing, output, timestamps, and watch behavior. Tests use synthetic
responses; a live lookup is a separate acceptance check.

To run the debug command from the repository root, resolve SwiftPM's binary
directory (its layout varies by toolchain):

```sh
brew_version_bin="$(swift build --package-path brew_version --show-bin-path)"
"$brew_version_bin/brew-version" --help
```

## Command usage

```text
brew-version [OPTIONS] PACKAGE...
```

- `--formula` or `--cask` forces all names to that kind. Otherwise each name
  tries formula first, then cask.
- `--watch [SECONDS]` or `--watch=SECONDS` checks immediately, then repeats
  every 300 seconds by default, until any version changes.
- `--version` prints the release version. `-h` and `--help` print full help.
- Names use lowercase letters, digits and `@ + . _ -`, beginning with a letter
  or digit. Third-party taps are not supported.

One name prints only its version; several names print `name: version`.
Watch output includes local date, time, time zone, name and version on every
check. A changed version includes its initial version and exits successfully.
Output is line buffered so watch lines appear promptly through a pipe.
Lookups run in argument order and stop at the first error, preserving earlier
output. Press Ctrl-C to stop watching.

Exit codes are 0 for success (including detecting a change), 1 for a lookup
error, and 2 for invalid arguments. Watch intervals are positive whole seconds
through `4294967295`; leading zeroes are accepted. The app's minimum interval
does not apply to the CLI.

### Compatibility with the bash command

The CLI preserves the existing argument ordering and watch loop. Deliberate
changes are covered by the named regression tests:

- `RunCLITests.helpAndVersion`: adds the release version flag.
- `ArgumentsTests.table`: caps watch seconds at the representable UInt32 limit.
- `UsageTests.expectedHelp`: adds version help, removes the external dependency
  requirement and calls exit code 1 a lookup error.
- `RunCLITests.lookupWithoutDependencyTools`: removes `curl` and `jq` checks.
- `TransportTests.timeoutPolicy`: uses a 10-second idle request timeout and
  30-second total resource timeout for individual lookups.

The release version comes from the tracked Info.plist through
`BrewVersionRelease.version`; a core test verifies that they agree.
