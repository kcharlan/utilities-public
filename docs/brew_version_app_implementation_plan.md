# Brew Version (Swift) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the command-line replacement and package-watching app specified in Decisions.

**Architecture:** Swift package `brew_version/`, with `BrewVersionCore` shared by `BrewVersionCLI` and `BrewVersion`. The executable `brew-version` delegates to the CLI library. Task headings name deliverables; each deliverable owns its file inventory and acceptance tests.

**Frameworks:** Observation, UserNotifications, ServiceManagement, Network and Swift Testing; deployment tests use Node `node:test` and zsh.

**Spec:** The Decisions and Global Constraints sections below. They record what the owner approved from a private design page reviewed in the planning session; that page is not part of this repository.

## Decisions

- **Interface:** menu bar app only: an `NSStatusItem` whose button opens an `NSPopover` (transient) with SwiftUI content. No Dock icon or main window. Settings opening is governed by Settings-opening gate under Menu bar app.
- **What gets watched:** only packages the user adds, by searching or with a Watch button. Nothing is watched by default, and only watched packages notify.
- **Other updates on this Mac:** a second section listing installed, unwatched packages that Homebrew lists as newer. At launch, recompute installed updates from a valid catalog cache; revalidate the catalog when absent or when 24 hours have elapsed since the last successful fetch. No notifications and no menu bar state. The section is collapsible and can be turned off in Settings (default on). Each row has a Watch button.
- **Installed versions:** decide when a watched row turns amber. They are read from Homebrew's folders and from app bundles; the app never runs `brew`.
- **Interval:** applies to watched packages. Default 30 minutes. The menu offers presets of 10, 15 and 30 minutes and 1, 2 and 6 hours. Custom accepts whole minutes from 10 to 1,440.
- **When a watched row turns amber, and when it notifies:** see `EvaluateTests.transitions` under Watch rules, interval and saved state.
- **Removing a watch:** Copy's stop-watching action in the row's context menu and its hover ⋯ menu, or Delete on a selected row. An inline undo line shows for 5 seconds. Removing deletes that package's saved state.
- **Command line:** replace `~/Library/Scripts/brew-version`. Behave as its argument parser and execution loop do, subject to Differences from the bash script. The app's interval floor does not apply to the command line.
- **Out of scope:** a global keyboard shortcut, a change-history window, a custom app icon, third-party taps, and running `brew upgrade` from the app.

## Global Constraints

- **Public repository:** follow `agents.md`, Public repository: no sensitive data. Fixtures must be conspicuously synthetic; `PackageNameTests` owns name examples.
- **Toolchain:** Xcode or the Command Line Tools providing Swift 6, plus Node.js for deployment. Use `swift-tools-version: 6.0`, Swift 6 language mode, platform `.macOS(.v14)`, and no dependencies in `Package.swift`. The generated project README is the maintained prerequisites reference after implementation.
- **Version:** the initial release is `1.0.0`. The single source is `CFBundleShortVersionString` in `brew_version/Resources/Info.plist`. `BrewVersionRelease.version` must equal it, which a test enforces. The deploy installer reads the expected version from the tracked plist. Everything else (tests, notices, docs) refers to the release version without writing the number.
- **App bundle:** `Brew Version.app`, executable `BrewVersion`, bundle identifier `local.utilities.brew-version`, `LSUIElement` true, `LSMinimumSystemVersion` `14.0`. Follow Release target for signing. Not sandboxed, because it reads Homebrew prefixes and application folders.
- **Package names:** behave as the package-validation branch of `~/Library/Scripts/brew-version` does; `PackageNameTests` owns the acceptance cases.
- **Homebrew URLs:**
  - one package: `https://formulae.brew.sh/api/{formula|cask}/{name}.json`
  - bulk lists: `https://formulae.brew.sh/api/formula.json` and `https://formulae.brew.sh/api/cask.json`
- **HTTP:**
  - HTTPS only, including redirects.
  - No URL cache: `urlCache = nil` and `.reloadIgnoringLocalCacheData`.
  - Timeouts for one package: request (idle) 10 s, resource (total) 30 s. Bulk lists: resource 120 s.
- **Lookup:** behave as `lookup_version()` in `~/Library/Scripts/brew-version` does. The app supplies a known kind when available. `HomebrewClientTests` and `ListingTests` own the decoding and error contract.
- **Homebrew prefixes:** candidates `/opt/homebrew`, `/usr/local`, in that order; for each package, the first prefix admitted by InstalledReader wins. Application directories: `/Applications`, `~/Applications`, in that order.
- **App state:** `~/Library/Application Support/Brew Version/state.json`, written atomically. Directory mode 0700, file mode 0600. Catalog cache: `~/Library/Caches/Brew Version/`.
- **Commit protocol:** work on local branch `brew-version-app` in the existing checkout. At each Commit step, follow `agents.md`, Git, including its authorization and sensitive-data inspection rules. Use the step's subject and a body explaining its deliverable; add the executing agent's own attribution trailer if applicable. This plan does not authorize committing, pushing, opening a PR, merging or deploying.
- **Copy** (exact, sentence case; tests and views use these strings):
  - Notification title: `NAME VERSION is on Homebrew`. Body when installed: `You have INSTALLED.` Body when not installed: `Was PREVIOUS.`
  - Popover title: `1 watched update` or `N watched updates` when any watched row is amber; otherwise `Watching 1 package` or `Watching N packages`. Empty list: `Search for a formula or cask to start watching it.`
  - Row status: `Installed`, `You have INSTALLED`, `Not installed`, `Updates itself` (cask version `latest`). Fallback note: `Version from Homebrew's records; the app may have updated itself.`
  - Row errors: `Couldn't reach Homebrew.`, `Homebrew returned HTTP STATUS.`, `Homebrew returned no usable version.`, `Not found in Homebrew.`
  - Section heads: `Watching`, with hint `Checked every INTERVAL, with alerts`; `Other updates on this Mac`, with hint `At launch and daily, no alerts`.
  - Row actions: `Copy upgrade command`, `Open homepage`, `Skip this version` (amber rows only), `Stop watching NAME`. Undo line: `Stopped watching NAME`, with button `Undo`.
  - Upgrade commands: `brew upgrade NAME` for a formula, `brew upgrade --cask NAME` for a cask.
  - Search: `Not a Homebrew formula or cask. Check the spelling.` and `Names use lowercase letters, numbers and @ + . _ -`
  - Footer: `Every INTERVAL` and `Next check H:MM AM`. Interval labels: whole hours read `1 hour` or `N hours`; everything else reads `N minutes`. Custom field error: format `Enter LOWER to UPPER minutes.` using Interval's bounds with grouped decimal formatting.
  - Settings header: `Brew Version VERSION`. Deploy notice when the app is running: `Quit and reopen Brew Version to use VERSION.`

## Differences from the bash script

The compatibility changes are defined by these named tests:
- `RunCLITests.helpAndVersion` for the release flag;
- `ArgumentsTests.table` for the watch-interval cap;
- `UsageTests.expectedHelp` for help edits;
- `RunCLITests.lookupWithoutDependencyTools` for removal of external dependency checks;
- `TransportTests.timeoutPolicy` for the transport timeout change.

## Validation commands

Use these command names in the task steps:
- **Swift suite:** `make -C brew_version test`; require passing tests without skips. For a failing-test step, inspect the failure and confirm it concerns the new test or missing implementation.
- **Release build:** `make -C brew_version release`; its output contract is defined under Menu bar app, Release target.
- **Installer suite:** `node --test tools/tests/deploy_brew_version.test.mjs`.
- **Fleet suite:** `zsh tools/tests/test_check_local_deployments.zsh`; expect `check_local_deployments tests: PASS`.
- **Affected-project gates:** use `agents.md`, Testing Scope and Validation Matrix. The final deployment task names its affected projects.

---

### Task 1: Core lookup

**Files:**
- Create: `brew_version/{.gitignore,Package.swift,Makefile}`, `brew_version/Resources/Info.plist`, `brew_version/Sources/BrewVersionCore/{Release,PackageName,Listing,HTTPTransport,HomebrewClient}.swift`
- Test: `brew_version/Tests/BrewVersionCoreTests/{PackageNameTests,ListingTests,HomebrewClientTests,TransportTests,ReleaseTests}.swift`

**Interfaces:**
- Produces:
  - `public enum BrewVersionRelease { public static let version: String }`
  - `public struct PackageName: Hashable, Codable, Sendable, CustomStringConvertible { public let rawValue: String; public init?(_ raw: String) }`
  - `public enum PackageKind: String, Codable, Sendable { case formula, cask }`
  - `public enum KindPreference: Sendable, Equatable { case auto, formula, cask; public init(_ kind: PackageKind); public var candidates: [PackageKind]; public var label: String }`. Behave as the source script's `kinds` assignment does.
  - `public struct Listing: Codable, Equatable, Sendable { name: PackageName; kind: PackageKind; version: String; revision: Int; autoUpdates: Bool; summary: String?; homepage: URL?; appNames: [String] }`, with:
    - `public static func decode(_ data: Data, kind: PackageKind, name: PackageName) throws -> Listing`
    - `public static func decodeItem(_ object: [String: Any], kind: PackageKind) -> Listing?`. Bulk lists use `name` (formula) or `token` (cask) from the object.
  - `public struct HTTPResponse: Sendable { status: Int; body: Data; etag: String? }`
  - `public protocol HTTPTransport: Sendable { func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse }`
  - `public final class URLSessionTransport: HTTPTransport { public init(requestTimeout: TimeInterval, resourceTimeout: TimeInterval, protocolClasses: [AnyClass]? = nil); public static func standard() -> URLSessionTransport; public var configuration: URLSessionConfiguration { get } }`. `standard()` uses the one-package timeouts from Global Constraints.
  - `public enum LookupError: Error, Equatable, Sendable { case unreachable(PackageName), http(status: Int, PackageName), invalidVersion(PackageKind, PackageName), notFound(PackageName, KindPreference); public var cliMessage: String; public var rowMessage: String }`
  - `public struct CachedListing: Codable, Equatable, Sendable { etag: String; listing: Listing }`
  - `public actor ListingCache { public init(entries: [URL: CachedListing] = [:]); public func entry(for url: URL) -> CachedListing?; public func store(_ entry: CachedListing, for url: URL); public func snapshot() -> [URL: CachedListing] }`
  - `public struct HomebrewClient: Sendable { public init(transport: HTTPTransport, cache: ListingCache? = nil); public func lookup(_ name: PackageName, kinds: KindPreference) async throws -> Listing }`. It throws only `LookupError`.
  - `Package.swift` with the `BrewVersionCore` library and the `BrewVersionCoreTests` test target only. Each later task adds its own targets.
  - `Makefile` targets `build` (`swift build`), `test` (`swift test`) and `clean` (removes `.build` and `build`). Release packaging is added under Menu bar app.

- [ ] **Step 1: Write the failing tests**

Create the package manifest, Makefile and test-target scaffolding before invoking the Swift suite. Ignore `.build/`, `.swiftpm/` and `build/` in the project `.gitignore`.

`PackageNameTests`:
- accepts `synthetic-formula`, `python@3.13`, `a`, `g++` and `x.y_z-1`;
- rejects `""`, `Synthetic`, `-x`, `@x`, `a b`, `a/b` and `.x`.
- `decodingValidatesName`: decode the accepted and rejected cases through `JSONDecoder`, including a name nested inside a cached Listing; invalid values throw `DecodingError.dataCorrupted`.

`ReleaseTests.infoPlistMatchesRelease`: read `Resources/Info.plist` (find the path from `#filePath`). Assert that its version equals `BrewVersionRelease.version`, and that the bundle identifier, executable name and `LSUIElement` match Global Constraints.

`ListingTests`:
- `formulaFields`: `{"name":"synthetic-formula","versions":{"stable":"1.2.3"},"revision":2,"desc":"Synthetic","homepage":"https://example.invalid/"}` decodes all fields.
- `caskAppNames`: `"artifacts":[{"app":["Synthetic.app"]},{"app":["Source.app",{"target":"Renamed.app"}]},{"zap":[]}]` gives `appNames == ["Synthetic.app", "Renamed.app"]`.
- `caskSiblingTarget`: `{"app":["Source.app",{"target":"Argument.app"}],"target":"/synthetic-apps/Override.app"}` gives `appNames == ["Override.app"]`. A valid sibling target takes precedence; otherwise use the app argument's target, then its source, taking the selected path's last component. Follow the serialization shape of `Cask::Artifact::Relocated#initialize`, `AbstractArtifact#to_args` and `Cask#artifacts_list` in the pinned Homebrew checkout named under VersionOrder.
- `malformedArtifactsDoNotFail`: an `artifacts` value of `"oops"` gives `appNames == []`.
- `missingOptionals`: missing `revision` decodes as `0`; null `auto_updates` decodes as `false`.

`HomebrewClientTests` use a `StubTransport` that maps a URL to a response or an error and records each request:
- `formulaFound`: a formula 200 gives the formula, and only the formula URL is requested.
- `fallsBackToCask`: formula 404, then cask 200, gives the cask.
- `caskOnlySkipsFormula`: `kinds: .cask` requests only the cask URL.
- `notFoundBoth`: `cliMessage == "Error: synthetic-missing not found in Homebrew (formula cask)."`.
- `httpErrorStops`: formula 404, then cask 503. `cliMessage == "Error: Homebrew returned HTTP 503 for synthetic-cask."`, and `rowMessage` is the HTTP row error from Copy.
- `unreachable`: the transport throws. `cliMessage == "Error: could not reach Homebrew for synthetic-formula."`.
- `refusedRedirectIsUnreachable`: a response status from 300 to 399 other than 304 maps to `.unreachable`.
- `invalidVersion`: each body `{"versions":{"stable":""}}`, `{"versions":{"stable":null}}`, `{"versions":{"stable":3}}` and `not json` gives `cliMessage == "Error: no valid formula version returned for synthetic-formula."`.
- `etagRoundTrip`: a 200 with an ETag is cached; the next request sends that value as `ifNoneMatch`, gets a 304, and returns the cached listing.
- `notModifiedWithoutCacheIsError`: a 304 with no cache entry gives `.http(status: 304, …)`.
- Error results assert `rowMessage` against Copy. Successful results assert Listing fields.

`TransportTests` use a `URLProtocol` subclass passed in `protocolClasses`:
- `refusesHTTPRedirect`: a 301 to `http://example.invalid/x` comes back as status 301; it is not followed.
- `rejectsNonHTTPSURL`: `get(URL(string: "http://example.invalid")!, …)` throws.
- `sendsIfNoneMatch`: the request carries the header.
- `noURLCache`: configuration obeys HTTP in Global Constraints.
- `timeoutPolicy`: initializer values reach their matching URLSession configuration properties; `standard()` uses HTTP in Global Constraints. This deliberately replaces the source script's curl `--connect-timeout` with URLSession's idle timeout; follow [Apple's request timeout semantics](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/timeoutintervalforrequest) and [resource timeout semantics](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/timeoutintervalforresource). Assert the configured policy independently of cache settings. A reference is needed here because connection and idle timeouts are not interchangeable.

- [ ] **Step 2: Run tests to verify they fail**

Run Swift suite.
Expected: build errors for the missing types.

- [ ] **Step 3: Implement**

Decode with `JSONSerialization` into `[String: Any]` so the lenient `artifacts` rule stays simple. `URLSessionTransport` is its own session delegate; implement the redirect behavior asserted by `TransportTests.refusesHTTPRedirect`. `PackageName.init(from:)` must pass decoded values through its validating initializer.

- [ ] **Step 4: Run tests to verify they pass**

Run Swift suite. Check `git status --short brew_version` against the project `.gitignore` before handoff.

- [ ] **Step 5: Commit**

Subject `Add Brew Version core lookup`. Follow Commit protocol.

---

### Task 2: Swift `brew-version` command line

**Files:**
- Create: `brew_version/Sources/BrewVersionCLI/{Usage,Arguments,Timestamp,RunCLI}.swift`, `brew_version/Sources/brew-version/main.swift`, `brew_version/README.md`
- Modify: `brew_version/Package.swift`, adding the `BrewVersionCLI` library, the `brew-version` executable and the `BrewVersionCLITests` test target
- Test: `brew_version/Tests/BrewVersionCLITests/{ArgumentsTests,TimestampTests,RunCLITests,UsageTests}.swift`
- Fixture: `brew_version/Tests/BrewVersionCLITests/Fixtures/expected-help.txt`

**Interfaces:**
- Produces:
  - `public let usageText: String`
  - `public enum CLICommand: Equatable { case help, version, run(CLIOptions) }`
  - `public struct CLIOptions: Equatable { public var kinds: KindPreference; public var watchInterval: UInt32?; public var packages: [PackageName] }`
  - `public func parseArguments(_ arguments: [String]) -> CLICommand?`. `nil` means invalid arguments.
  - `public func strftimeTimestamp(_ date: Date) -> String`. Use `localtime_r` and `strftime`; behave as the source script's `date` call does.
  - `public struct CLIEnvironment { public var transport: HTTPTransport; public var writeOut: (String) -> Void; public var writeErr: (String) -> Void; public var now: () -> Date; public var timestamp: (Date) -> String; public var sleep: (UInt32) async -> Void; public init(transport:writeOut:writeErr:now:timestamp:sleep:) }`
  - `public func runCLI(_ arguments: [String], environment: CLIEnvironment) async -> Int32`

- [ ] **Step 1: Write the failing tests**

`ArgumentsTests.table`: behave as the source script's argument loop does, with the representable `UInt32` cap asserted below.

| Arguments | Result |
|---|---|
| `[]` | `nil` |
| `["synthetic-formula"]` | `.run(kinds: .auto, watchInterval: nil, packages: [synthetic-formula])` |
| `["--formula", "--cask", "x"]` | `nil` |
| `["--cask", "--cask", "x"]` | `.run(kinds: .cask, …)` |
| `["--watch", "x"]` | interval 300, packages `[x]` |
| `["--watch", "60", "x"]`, `["--watch=60", "x"]` | interval 60 |
| `["--watch", "0300", "x"]` | interval 300 |
| `["--watch", "-5", "x"]`, `["--watch", "0", "x"]`, `["--watch=", "x"]` | `nil` |
| `["--watch", "5x", "y"]`, `["--watch", "1.5", "x"]` | `nil`: the argument is taken as the interval and fails validation |
| `["--watch", "4294967296", "x"]` | `nil` (see Differences) |
| `["-x"]`, `["Synthetic"]` | `nil` |
| `["x", "--help"]`, `["-h"]` | `.help` |
| `["--bogus", "--help"]` | `nil` |
| `["--version"]` | `.version` |

`TimestampTests.matchesDate`: for a fixed epoch, `strftimeTimestamp` equals the output of `/bin/date -r EPOCH '+%Y-%m-%d %H:%M:%S %Z'`, run with `Process` in the same environment.

`RunCLITests`, with `StubTransport`, recorded output, and `timestamp` stubbed to return `T`:
- `singlePackagePrintsVersionOnly`: stdout `"1.2.3\n"`, exit 0.
- `multiplePackagesPrefixNames`: stdout `"synthetic-formula: 1.2.3\nsynthetic-cask: 4.5,6\n"`.
- `errorAfterFirstPackage`: stdout keeps the first line; stderr is that package's `cliMessage` and a newline; exit 1.
- `invalidArgumentsPrintUsageToStderr`: stderr is `usageText` and a newline, stdout is empty, exit 2.
- `helpAndVersion`: `--help` prints `usageText` to stdout and exits 0. `--version` prints `"brew-version \(BrewVersionRelease.version)\n"` and exits 0.
- `watchStopsOnChange`: responses `1.0.0`, then `1.0.1`. Stdout is `"T synthetic-formula: 1.0.0\n"`, then `"T synthetic-formula: 1.0.1 (changed from 1.0.0)\n"`. `sleep` is called once with 60. Exit 0.
- `watchStopsOnLookupError`: a 503 in the second round exits 1.
- `lookupWithoutDependencyTools`: in an isolated test process with a PATH containing neither curl nor jq, call `runCLI` with a successful synthetic StubTransport response. Assert success output and exit 0. Launch the already-built test executable by absolute path; change no process-global environment in concurrent tests.

`UsageTests.expectedHelp`: preserve a checked-in golden help fixture copied from the source script before deployment. Its expected edits are:
- add `  --version          Show the brew-version version.` before the help option;
- remove the curl/jq requirement from PACKAGE LOOKUP;
- change exit-code 1's description to `Lookup error`.

Assert the complete `usageText` against that independently maintained fixture, and assert the new option and exit description and absence of the old dependency text. Do not derive expected text from `usageText`.

- [ ] **Step 2: Run tests to verify they fail**

Run Swift suite.
Expected: the CLI tests fail to build.

- [ ] **Step 3: Implement**

Implement the help contract owned by `UsageTests.expectedHelp`; keep the production string independent of the golden fixture.

`main.swift` builds `CLIEnvironment` with `URLSessionTransport.standard()`, `strftimeTimestamp` and line-buffered stdout (`setvbuf(stdout, nil, _IOLBF, 0)`), so that `--watch | tee` shows each line as it happens. It passes no `ListingCache`.

`README.md` covers:
- what the command and the app do;
- requirements from Toolchain and App bundle in Global Constraints;
- build/test instructions pointing to the Makefile targets;
- command usage, with compatibility changes derived from the tests named in Differences from the bash script;
- a statement that this native app is a deliberate exception to `agents.md`, UI Shapes.

The app and deployment deliverables extend this README in their own documentation steps.

- [ ] **Step 4: Run tests and smoke the binary**

Run Swift suite.

**CLI smoke checks:** after `swift build --package-path brew_version`, run the debug command by absolute path with `--help`, an invalid argument from `ArgumentsTests.table`, and a public package selected for live lookup. Check stdout, stderr and status against the corresponding `RunCLITests` assertions. The live lookup must return a nonempty version without a CLI error. These are build/deployment acceptance checks, separate from stubbed tests.

- [ ] **Step 5: Commit**

Subject `Add Swift brew-version command`. Follow Commit protocol.

---

### Task 3: Installed versions and version order

**Files:**
- Create: `brew_version/Sources/BrewVersionCore/{VersionOrder,InstalledReader,UpdateStatus}.swift`
- Test: `brew_version/Tests/BrewVersionCoreTests/{VersionOrderTests,InstalledReaderTests,UpdateStatusTests}.swift`

**Interfaces:**
- Produces:
  - `public enum VersionOrder { public static func compare(_ a: String, _ b: String) -> ComparisonResult }`
  - `public struct HomebrewPrefix: Sendable { public let root: URL; public static func detectAll(candidates: [URL]) -> [HomebrewPrefix] }`. It returns every candidate that has a `Cellar` or `Caskroom` directory, in candidate order.
  - `public enum InstalledSource: String, Codable, Sendable { case cellar, caskroom, appBundle, caskroomFallback }`
  - `public struct InstalledVersion: Equatable, Codable, Sendable { public var version: String; public var source: InstalledSource }`
  - `public struct InstalledReader: Sendable { public init(prefixes: [HomebrewPrefix], applicationDirectories: [URL]); public func installed(_ name: PackageName, kind: PackageKind, listing: Listing?) -> InstalledVersion?; public func installedPackages() -> [(name: PackageName, kind: PackageKind)] }`
  - `public enum UpdateStatus: Equatable, Codable, Sendable { case upToDate, ahead, updateAvailable(installed: String), notInstalled, unversioned }`
  - `public func updateStatus(listing: Listing, installed: InstalledVersion?) -> UpdateStatus`

- [ ] **Step 1: Write the failing tests**

`VersionOrderTests.cases`, each as (`a`, `b`, expected result):

| a | b | Expected |
|---|---|---|
| `1.25.0_2` | `1.25.0` | descending |
| `23.1.3_1` | `23.1.3_2` | ascending |
| `1.0.1` | `1.0` | descending |
| `1.0.0` | `1.0` | same |
| `1.0rc1` | `1.0` | ascending |
| `1.0beta` | `1.0` | ascending |
| `1.0a1` | `1.0` | ascending |
| `1.0p1` | `1.0` | descending |
| `1.10` | `1.9` | descending |
| `0.0.45` | `0.1.0` | ascending |
| `4.5,6` | `4.5,7` | ascending |
| `001.2` | `1.2` | same |
| `99999999999999999999` | `9` | descending (no integer overflow) |
| `1.0p1` | `1.0.0` | descending |
| `1.0b` | `1.0.0` | descending |
| `1.0.0` | `1.0p1` | same |
| `1.0.0` | `1.0b` | same |
| `1.0preview` | `1.0` | ascending |
| `1.0Z` | `1.0a` | ascending |
| `1.0alpha` | `1.0a0` | same |
| `1.0alpha10` | `1.0a20` | ascending |
| `1.0alpha1` | `1.0beta1` | ascending |
| `1.0rc1` | `1.0pre1` | descending |
| `HEAD` | `9999` | descending |
| `HEAD-synthetic-one` | `HEAD-synthetic-two` | same |

`VersionOrderTests.homebrewParity`: expand coverage across token classes and zero-token positions. Record an independently generated expected result for each ordered pair under test, using the pinned upstream commit below. Development may use `HOMEBREW_NO_AUTO_UPDATE=1 brew ruby` to generate/verify synthetic pair results; the shipped app and routine tests must not require brew.

`InstalledReaderTests` build synthetic prefixes in a temporary directory:
- `provenance`: formula receipts with `source.tap == "homebrew/core"` and cask receipts with `source.tap == "homebrew/cask"` are admitted. Legacy casks without a receipt are explicitly admitted (the owner's correction overrides the previous unknown-provenance rule). Formula receipts remain required. An existing unreadable, malformed, unknown-tap, wrong-kind or third-party receipt excludes the installation even when its short name matches a public listing; dangling receipt symlinks are not the absence exception. Assert nil from `installed` and absence from `installedPackages` for excluded installs; a matching app bundle must not bypass admission. Reject version-folder symlinks. Other reader fixtures create admitted receipts through the same fixture helper.
- `formulaFromOptLink`: `Cellar/synthetic-formula/` holds `1.0.0_1/` and `0.9.0/`, and `opt/synthetic-formula -> ../Cellar/synthetic-formula/1.0.0_1`. Result: `1.0.0_1`, source `.cellar`.
- `formulaWithoutOptLinkUsesHighest`: with no `opt` link, the highest Cellar folder wins.
- `aliasNameIsNotInstalled`: `opt/synthetic-alias -> ../Cellar/synthetic-formula/1.0.0` with no `Cellar/synthetic-alias`. `installed(synthetic-alias, .formula, …)` is `nil`, and `installedPackages()` leaves it out. An `opt` link only counts when it resolves inside `Cellar/NAME`.
- `caskIgnoresMetadataAndLatestLink`: `Caskroom/synthetic-cask/` holds `.metadata/`, `2.0.0/` and `latest -> 2.0.0`. Result: `2.0.0`, source `.caskroom`.
- `selfUpdatingCaskReadsAppBundle`: listing `autoUpdates: true`, app `Synthetic.app` with `CFBundleShortVersionString` `2.3.0`. Result: `2.3.0`, source `.appBundle`.
- `appBundleReadIsFresh`: read, rewrite the plist with `2.4.0`, read again with the same reader. The second read gives `2.4.0`.
- `missingAppFallsBackToCaskroom`: the same setup without the app gives the Caskroom version, source `.caskroomFallback`.
- `firstPrefixWins` and `secondPrefixFound`: exercise candidate order from Global Constraints.
- `installedPackagesSkipsHiddenAndInvalid`.

`UpdateStatusTests`:
- equal versions give `.upToDate`, and an installed version newer than the listing gives `.ahead`;
- installed `1.0.0_1` against listing `1.0.0` with revision 2 gives `.updateAvailable(installed: "1.0.0_1")`;
- `appBundleComparesBeforeComma`: listing `3.3.1,4940` with app version `3.3.1` (source `.appBundle`) gives `.upToDate`;
- `nil` gives `.notInstalled`;
- a cask listing version of `latest` gives `.unversioned`.

- [ ] **Step 2: Run tests to verify they fail**

Run Swift suite.
Expected: the new types are missing.

- [ ] **Step 3: Implement**

`VersionOrder.compare` must behave as `Version#<=>`, `Version#tokens`, `SCAN_PATTERN`, `Token.create`, the token subclass comparators and `Version#head?` do in [Homebrew version.rb at commit 19fe946b9a257cb41ebb5cef5c592ba7923d1f3b](https://github.com/Homebrew/brew/blob/19fe946b9a257cb41ebb5cef5c592ba7923d1f3b/Library/Homebrew/version.rb). Port those symbols as the semantic source; do not substitute a simplified token algorithm. Preserve arbitrary-precision numeric comparison without Swift integer overflow. `VersionOrderTests` owns the concrete parity examples.

`installedForm` renders formula release identity as `version`, plus `_REVISION`
when `revision > 0`; it is display text, not a comparison operand. Comparison:
- formula: split the installed keg at its last underscore only when the suffix is nonempty ASCII digits; otherwise use the whole version and revision zero. Compare the upstream versions with `VersionOrder`, then numeric revisions only on a version tie (Homebrew `PkgVersion` semantics). Reuse `FormulaVersion` for update status and highest-keg selection without a valid opt link. Keep numeric comparison arbitrary precision and deterministic filename order on ties;
- cask whose installed source is `.appBundle`: `version` up to its first comma;
- any other cask: `version`.

Use `Data(contentsOf:)` and `PropertyListSerialization` to satisfy `InstalledReaderTests.appBundleReadIsFresh`.

Share provenance admission between `installed` and `installedPackages`, applying `InstalledReaderTests.provenance` to the selected keg/cask before app-bundle fallback. Locate/read receipt metadata using the pinned Homebrew `Tab.for_keg` (`Library/Homebrew/tab/tab.rb`), `Cask::Tab.for_cask` (`Library/Homebrew/cask/tab.rb`), `Cask::Metadata#metadata_main_container_path` and `AbstractTab.create` (`Library/Homebrew/tab.rb`) as source references. If a linked keg is excluded, do not substitute an older keg from that rack; continue to the next prefix candidate.

- [ ] **Step 4: Run tests to verify they pass**

Run Swift suite.

- [ ] **Step 5: Commit**

Subject `Read installed Homebrew versions without running brew`. Follow Commit protocol.

---

### Task 4: Watch rules, interval and saved state

**Files:**
- Create: `brew_version/Sources/BrewVersionCore/{CheckInterval,WatchState,WatchController}.swift`
- Test: `brew_version/Tests/BrewVersionCoreTests/{CheckIntervalTests,EvaluateTests,WatchStoreTests,WatchControllerTests}.swift`

**Interfaces:**
- Produces:
  - `public struct CheckInterval: Codable, Hashable, Sendable { public let minutes: Int; public init?(minutes: Int); public static let presets: [CheckInterval]; public static let standard: CheckInterval; public var label: String }`
  - `public enum CheckSchedule { public static func nextDue(lastCheck: Date?, interval: CheckInterval) -> Date?; public static func isDue(lastCheck: Date?, interval: CheckInterval, now: Date) -> Bool }`. A `nil` `lastCheck` is always due.
  - `public struct ReleaseID: Codable, Equatable, Sendable { kind: PackageKind; version: String; revision: Int; public init(_ listing: Listing); public var displayVersion: String }`. Formula identity uses the listing's revision; cask identity normalizes revision to zero. `displayVersion` reuses the formula branch of `installedForm` for formulas, and the full listing version for casks.
  - `public struct WatchEntry: Codable, Equatable, Sendable { name: PackageName; kind: PackageKind?; lastListing: Listing?; installed: InstalledVersion?; lastSeenRelease: ReleaseID?; notifiedRelease: ReleaseID?; skippedRelease: ReleaseID?; unseenRelease: Bool; lastError: String?; public var isAmber: Bool }`
  - `public struct Notice: Equatable, Sendable { public var name: PackageName; public var title: String; public var body: String }`
  - `public func evaluate(_ entry: WatchEntry, listing: Listing, installed: InstalledVersion?) -> (WatchEntry, Notice?)`
  - `public struct AppState: Codable, Equatable, Sendable { schema: Int; watched: [WatchEntry]; interval: CheckInterval; showOtherUpdates: Bool; otherUpdatesCollapsed: Bool; lastCheck: Date?; lastCatalogFetch: Date?; listingCache: [URL: CachedListing]; public static let currentSchema = 1; public static let initial: AppState }`
  - `public struct StoreLoad: Sendable { state: AppState; problem: String?; canSave: Bool }`
  - `public struct WatchStore: Sendable { public init(fileURL: URL); public func load() -> StoreLoad; public func save(_ state: AppState) throws }`
  - `public protocol Notifier: Sendable { func post(_ notice: Notice) async }`
  - `@MainActor @Observable public final class WatchController`, with:
    - `public init(transport: HTTPTransport, installed: InstalledReader?, store: WatchStore, notifier: Notifier, now: @escaping () -> Date = Date.init)`. Apply `StoreLoad` before building `ListingCache(entries: state.listingCache)` and `HomebrewClient`.
    - `public private(set) var state: AppState`
    - `public private(set) var persistenceError: String?`
    - `public private(set) var canSave: Bool`
    - `public func retryLoad()`
    - `public private(set) var isChecking: Bool`
    - `public var amberCount: Int { get }`
    - `public func add(_ name: PackageName, kind: PackageKind?) async`
    - `public func remove(_ name: PackageName) -> (entry: WatchEntry, index: Int)?`
    - `public func restore(_ entry: WatchEntry, at index: Int)`
    - `public func skip(_ name: PackageName)`
    - `public func popoverClosed()`
    - `public func setInterval(_ interval: CheckInterval)`
    - `public func checkNow() async`
    - `public func checkIfDue() async`

- [ ] **Step 1: Write the failing tests**

`CheckIntervalTests`:
- valid minutes run from the Interval range's lower bound to its upper bound, inclusive; one minute below and one minute above are `nil`;
- `presets` and `standard` match Decisions;
- labels follow the Copy rule; assert `10 minutes`, `1 hour`, `2 hours`, `45 minutes`, `90 minutes` and `24 hours`;
- `isDue` is true for `nil`, false one minute before the standard interval has passed, and true once it has.
- `decodingValidatesMinutes`: JSONDecoder admission enforces the same range, rejecting out-of-range and noninteger stored values.

`EvaluateTests.transitions` owns the watch rules below. `V = ReleaseID(listing)` and `P` is a distinct previously seen identity. Apply rows in order. Notice text comes from Copy, with VERSION/PREVIOUS rendered through `displayVersion`.

| Entry before | Installed | Result |
|---|---|---|
| `lastSeenRelease == nil` (just added) | any | set `lastSeenRelease = V`, `notifiedRelease = V`, `unseenRelease = false`; no notice; amber exactly when an installed update is available |
| `skippedRelease == V` | any | no notice; clear `unseenRelease`; not amber |
| update available, `notifiedRelease != V` | `I` | notice with the installed body; `notifiedRelease = V`; amber |
| update available, `notifiedRelease == V` | `I` | no notice; amber |
| up to date, ahead or unversioned | any | no notice; not amber |
| not installed, `lastSeenRelease == P`, `notifiedRelease != V` | nil | set `unseenRelease = true`, `notifiedRelease = V`; notice with the not-installed body; amber |
| not installed, `lastSeenRelease == P`, `notifiedRelease == V` | nil | no notice; preserve `unseenRelease`; amber follows that flag |
| not installed, `lastSeenRelease == V` | nil | no notice; not amber |

On a successful evaluation, update `lastListing`, `installed` and `kind`, and clear `lastError`. Clear `unseenRelease` for an installed or unversioned result. `popoverClosed()` acknowledges the current listing identity for not-installed entries and clears their unseen flag; opening does not acknowledge. `skip` records the current identity.

`EvaluateTests.notInstalledPollsUntilAcknowledged`: exercise baseline, new release, repeated polls, a persisted-state restart, popover close and another poll; assert transitions from the table. `EvaluateTests.formulaRevisionIdentity`: with an older synthetic installed keg, evaluate successive revisions of an unchanged upstream version, then repeat and skip; assert the table using ReleaseID equality.

These transitions add text because no existing implementation defines the acknowledgement/notification distinction or formula revision identity.

`WatchStoreTests`:
- `missingFile`: returns `.initial`, no problem and `canSave == true`.
- `roundTrip`: saves and loads state with `ReleaseID` values.
- `privateModes`: after saving, modes obey App state in Global Constraints, including when the parent already exists.
- `corruptStateIsSetAside`: test Persistence boundary admission with malformed JSON, unsupported schema, invalid nested PackageName and invalid CheckInterval.
- `unreadableStateIsSetAside`: exercise that boundary with an injected read failure.
- `existingBadFileSurvives`: exercise quarantine-name collision handling.
- `quarantineFailureBlocksWrites`: inject a move failure and verify StoreLoad and source/quarantine snapshots against the boundary contract.
- `saveFailureKeepsPreviousBytes`: inject write/rename failure and assert the prior state file survives.
- `decodedStateRejectsDuplicates`: reject duplicate watched names and malformed release identities as invalid state.

`WatchControllerTests` use the stub transport, a synthetic prefix, a recording notifier, a controllable `now` and a temporary store:
- `addBaselinesWithoutNotice`.
- `addingWatchedNameIsNoOp`: one entry and one request.
- `checkNotifiesOncePerVersion`.
- `checkUsesKnownKind`: a watched cask requests only its cask URL.
- `removedFromHomebrewShowsError`: after watching, a 404 for the known kind gives `lastError` set to the not-found row error, keeps `lastListing`, and sends no notice.
- `popoverClosedClearsUnseen`: exercise acknowledgement through the controller according to `EvaluateTests.transitions`.
- `removeAndRestore`: the entry returns at the same index with its state.
- `skipClearsAmber`.
- `overdueAfterSleepRunsOneCheck`: with `lastCheck` 5 hours ago and the standard interval, one `checkIfDue()` makes exactly one request per watched package.
- `concurrentCheckIsIgnored`: a second `checkNow()` during a check starts nothing.
- `cacheSurvivesRestart`: after a check, a new controller built on the same store sends `If-None-Match` on its first check.
- `stateSavedAfterEachMutation`: after each of `add`, `skip`, `remove`, `restore` and `setInterval`, a reload shows the change.
- `failedMutationDoesNotPublish`: exercise the Persistence boundary through controller mutations with failed and successful saves.
- `blockedLoadDoesNotCheckOrMutate`: drive controller checks, mutations and retryLoad while quarantine fails, then allow recovery; assert the boundary contract.
- `savePrecedesNotice`: inspect persisted state from the recording notifier and exercise an injected save failure.

- [ ] **Step 2: Run tests to verify they fail**

Run Swift suite.
Expected: the new types are missing.

- [ ] **Step 3: Implement**

`checkNow()` works as follows:
- It looks up watched packages with at most 4 requests in flight, using `KindPreference(entry.kind)` when the kind is known.
- It evaluates into a candidate state, sets `lastCheck = now()`, copies `cache.snapshot()` into that candidate, then uses the persistence boundary below before posting notices.
- A lookup error sets `lastError` to the error's `rowMessage` and changes nothing else.

**Persistence boundary.** Initial and saved state use `AppState.currentSchema`; `WatchStore.load` requires that value and validates nested domain values and watched-name uniqueness. On read/decode failure, move the existing source to `state.json.bad`; if that name is occupied, use a unique `state.json.bad-UUID` destination without replacing prior evidence. Return the initial state with a recovery warning only after the move succeeds. If it fails, return the initial view with saving disabled and the failure visible; never replace the unread source. `retryLoad` retries admission, refreshes the listing cache from the admitted state and clears the block only on success.

`save` obeys App state in Global Constraints, writes a same-directory temporary file and renames it into place. Clean up temporary output on failure. Controller mutations save a candidate before publishing it. On save failure, keep the prior committed state and set `persistenceError`; a later successful operation clears it. A blocked load prevents checks/mutations; a failed ordinary save does not prevent retrying an operation. Notices are posted after commit.

Implement `CheckInterval.init(from:)` through its validating initializer; implement ReleaseID decoding with nonempty version, nonnegative formula revision and normalized cask revision. The read/move/write failure tests need an injectable file-I/O seam. This specification is necessary because the store has no existing failure policy to reference.

- [ ] **Step 4: Run tests to verify they pass**

Run Swift suite.

- [ ] **Step 5: Commit**

Subject `Add watch rules, check interval and saved state`. Follow Commit protocol.

---

### Task 5: Catalog and other updates

**Files:**
- Create: `brew_version/Sources/BrewVersionCore/Catalog.swift`
- Modify: `brew_version/Sources/BrewVersionCore/WatchController.swift`
- Test: `brew_version/Tests/BrewVersionCoreTests/{CatalogTests,OtherUpdatesTests}.swift`, plus additions to `WatchControllerTests`

**Interfaces:**
- Produces:
  - `public struct Catalog: Sendable`, with:
    - `public func listing(for name: PackageName, kind: PackageKind) -> Listing?`
    - `public func suggestions(prefix: String, limit: Int = 8) -> [(name: PackageName, kind: PackageKind)]`
  - `public struct CatalogClient: Sendable`, with:
    - `public init(transport: HTTPTransport, cacheDirectory: URL)`
    - `public static func makeTransport() -> URLSessionTransport`, which applies the bulk-list timeout
    - `public func cached() throws -> Catalog?`: read and validate the existing list files without network access; nil means no usable cache.
    - `public func load() async throws -> CatalogFetch`. Send conditional GETs with persisted ETags. A 304 uses validated cached bytes; 304 without a valid cache retries unconditionally. A failed or invalid download preserves the previous cache and may return it as stale.
  - `public struct CatalogFetch: Sendable { catalog: Catalog; revalidated: Bool }`. Set `revalidated` only if each required list was successfully downloaded or revalidated during this call.
  - `public struct OtherUpdate: Equatable, Sendable { public var listing: Listing; public var installed: InstalledVersion }`
  - `public func otherUpdates(catalog: Catalog, installed: InstalledReader, watched: Set<PackageName>) -> [OtherUpdate]`. It returns only `.updateAvailable` entries, sorted by name.
  - Changes to `WatchController`:
    - `init` gains a trailing `catalogClient: CatalogClient? = nil`; `nil` disables Other updates and suggestions;
    - `public private(set) var catalog: Catalog?`
    - `public private(set) var others: [OtherUpdate]`
    - `public func refreshCatalogIfDue() async`, whose cadence follows Other updates in Decisions; `lastCatalogFetch` records successful revalidation, not a stale fallback
    - `public func hydrateCatalog()` reads `cached()` and computes `others` independently of whether a network refresh is due
    - `public func scheduledTick() async` coordinates the due checks for watched packages and the catalog; guards concurrent catalog refreshes separately from `isChecking`
    - `public func setShowOtherUpdates(_ on: Bool)`
    - `public func setOtherUpdatesCollapsed(_ collapsed: Bool)`

- [ ] **Step 1: Write the failing tests**

`CatalogTests`:
- a synthetic formula list and cask list decode; items without a usable version are skipped, not fatal;
- a 304 reads the cached file; a 500 with a cache keeps it; a 500 without a cache throws;
- `suggestions` returns at most `limit` and matches only at the start of a name;
- `makeTransportTimeout`: `CatalogClient.makeTransport().configuration.timeoutIntervalForResource` equals the bulk-list timeout.
- `cachedDoesNotRequest`: a fresh client reads a valid persisted cache without a transport call; corrupt cache returns nil.
- `revalidationOutcome`: successful responses mark CatalogFetch revalidated; cached fallback after failure does not.

`OtherUpdatesTests`:
- an out-of-date formula and an out-of-date cask appear;
- up-to-date, ahead, unversioned, watched and not-in-catalog packages do not;
- a `.caskroomFallback` cask appears and keeps its source.
- `tapNameCollision`: use real InstalledReader over synthetic installs from `InstalledReaderTests.provenance`, with a catalog listing sharing the excluded install's short name. Parameterize by kind and require no OtherUpdate for that install.

`WatchControllerTests` additions:
- `catalogRefreshUsesSuccessfulFetchCadence`: assert Other updates in Decisions with absent, fresh and overdue cache states
- `hiddenOtherUpdatesSkipsDownload`
- `watchingAnOtherUpdateMovesIt`
- `stopWatchingReturnsItToOthers`
- `restartHydratesBeforeDue`: a new controller with a persisted recent fetch time hydrates its cache, shows suggestions and computes Other updates without network requests.
- `scheduledTickRefreshesDaily`: drive scheduledTick with a fake clock across the catalog due boundary; verify requests, separate watch cadence and overlapping-tick suppression.
- `failedRefreshDoesNotAdvanceFetchTime`: stale fallback retains the last successful timestamp. Bound retry attempts to at most once per watch interval using an in-memory last-attempt time; network reconnection may request an immediate retry.
- `reenablingOtherUpdatesHydratesThenChecksDue`: enabling the setting immediately restores cached content and schedules revalidation when due.
- `catalogPersistenceFailureKeepsCommittedState`: persist a new fetch timestamp through Persistence boundary; surface save failure rather than silently claiming it was committed.

- [ ] **Step 2: Run tests to verify they fail**

Run Swift suite.
Expected: the new types are missing.

- [ ] **Step 3: Implement**

Decode lists off the main actor with `JSONSerialization` into `[[String: Any]]` and map items through `Listing.decodeItem`. `hydrateCatalog` runs when Other updates is enabled; disabling that setting skips catalog I/O. `scheduledTick` invokes `checkIfDue` and `refreshCatalogIfDue` independently so a slow catalog request does not postpone a watched check. Use the existing Persistence boundary for setting/timestamp changes. Recompute Other updates when watches change. The cache-loading and retry tests own startup and failure behavior.

- [ ] **Step 4: Run tests to verify they pass**

Run Swift suite.

- [ ] **Step 5: Commit**

Subject `List other out-of-date installs from Homebrew's catalog`. Follow Commit protocol.

---

### Task 6: Menu bar app

**Files:**
- Create:
  - `brew_version/Sources/BrewVersionCore/Search.swift`
  - `brew_version/Sources/BrewVersion/{BrewVersionApp,AppDelegate,StatusItemController,PopoverView,WatchRowView,SearchSection,OtherUpdatesSection,IntervalMenu,SettingsView,UserNotifier,SystemEvents,LoginItem}.swift`; add `SettingsWindowController.swift` if required by Settings-opening gate
- Modify:
  - `brew_version/Sources/BrewVersionCore/WatchController.swift` (search state)
  - `brew_version/Package.swift` (adds the `BrewVersion` executable target)
  - `brew_version/Makefile` (adds `release`)
  - `brew_version/README.md` (app section)
- Test: `brew_version/Tests/BrewVersionCoreTests/SearchTests.swift`, `brew_version/Tests/BrewVersionAppTests/SystemEventsTests.swift`; add the app test target to Package.swift
- Acceptance harness: `brew_version/Tests/Acceptance/`, containing a separate bundled entry point that reuses the app's UI/notifier sources with injected synthetic services; exclude the production entry point when building it

**Interfaces:**
- Produces:
  - `public enum SearchToken: Equatable { case valid(PackageName), invalid(String) }`
  - `public func tokenize(_ text: String) -> [SearchToken]`. It splits on whitespace, drops duplicates and keeps order.
  - `public enum LookupResult: Equatable { case found(Listing, installed: InstalledVersion?, watched: Bool), notFound(PackageName), failed(PackageName, String), invalid(String) }`
  - On `WatchController`: `public private(set) var results: [LookupResult]`, `public func search(_ text: String) async` and `public func clearSearch()`.

- [ ] **Step 1: Write the failing tests**

`SearchTests`:
- `tokenize("a  b a Bad")` gives `[.valid(a), .valid(b), .invalid("Bad")]`.
- `searchDeduplicatesAndRejectsInvalid`: `search("synthetic-formula Bad synthetic-formula")` makes one request and gives `[.found(…), .invalid("Bad")]`.
- Exhausted candidate-kind 404 responses give `.notFound`.
- A watched name gives `found(…, watched: true)`.
- `search` uses the same in-flight limit as `checkNow()`.

`SystemEventsTests.scheduling`: inject timer, wake and network event sources and a recording scheduledTick callback. Drive the actual adapter through periodic, wake, offline and reconnect events; require a tick when appropriate, suppress ticks while offline, and reconnect without replaying missed intervals. Controller scheduling is exercised by `WatchControllerTests.scheduledTickRefreshesDaily`.

- [ ] **Step 2: Run tests to verify they fail**

Run Swift suite.
Expected: the search types are missing.

- [ ] **Step 3: Implement search, then the app**

**Structure.**
- `BrewVersionApp` is the `@main` SwiftUI `App`. It uses `@NSApplicationDelegateAdaptor(AppDelegate.self)`, and its only scene is `Settings { SettingsView }`.
- `AppDelegate` builds the `WatchController` with these parts:
  - `URLSessionTransport.standard()`;
  - `InstalledReader` over `HomebrewPrefix.detectAll` (`nil` when no prefix exists);
  - the state path from Global Constraints;
  - `UserNotifier`;
  - a `CatalogClient` built with `makeTransport()`.
- `StatusItemController` implements Interface in Decisions, with an `NSHostingController(rootView: PopoverView)` as popover content.
  - The button image is the template SF Symbol `mug`, or `mug.fill` while `amberCount > 0`. It is kept current with a re-armed `withObservationTracking`.
  - Its `NSPopoverDelegate.popoverDidClose` calls `popoverClosed()`.
  - Expose `showPopover()` for `UserNotifier`.

**Settings-opening gate.** Before completing the app, build a minimal bundled prototype with the Structure above and an isolated synthetic controller. Click the footer SettingsLink and require Settings to open, activate, close and reopen while the status item remains usable. Test the supported minimum macOS and the current development macOS; an unavailable minimum-system check remains an explicit release gate. [Apple's SettingsLink contract](https://developer.apple.com/documentation/swiftui/settingslink) establishes the intended scene action, but does not prove this separately hosted environment. If the exact arrangement fails, retain an AppKit `NSWindowController` named `settings`, hosting SettingsView, with a footer Button calling `settings.showWindow(nil)`, `settings.window?.makeKeyAndOrderFront(nil)` and `NSApp.activate(ignoringOtherApps: true)`. In that fallback, use an AppKit application entry point and remove the SwiftUI Settings scene. Record the chosen path and evidence in the project README. A source reference cannot establish this arrangement's runtime environment; the prototype supplies that evidence.

**Popover, top to bottom.**
- The title, the `Checked …` time and a refresh button that calls `checkNow()`.
- The search field. While it has text, look-up results replace the lists:
  - Return watches the selected result;
  - ⌘C copies the selected result's version;
  - `catalog` suggestions appear when a single partial token is typed.
- The Watching section: amber rows first, then by name; use Copy for empty state.
- `OtherUpdatesSection` follows the matching Decisions entry.
- The footer: `IntervalMenu`, the next-check time, and the action selected by Settings-opening gate.
- If `persistenceError` is present, show its diagnostic and a Retry action; use `retryLoad` for a blocked load, otherwise explain that the failed action can be retried. Disable state-changing controls and refresh while `canSave` is false.

**Watched rows.**
- Each row shows the name, kind, version, and either its status or `lastError`.
- Amber rows show the copy-upgrade and skip actions as buttons.
- Implement removal and undo as specified by Removing a watch in Decisions, with Undo calling `restore`.
- Context and hover menus use Copy for their actions.

**Other updates rows.** Name, kind, version, installed status and the applicable fallback note from Copy. The action follows Other updates in Decisions; the header toggles collapse through `setOtherUpdatesCollapsed`.

**`IntervalMenu`.** Use CheckInterval for choices, validation and labels, with a checkmark on the current choice. `Custom…` opens a sheet with a minutes field and Copy's error message.

**Settings window.**
- the version header;
- the interval;
- `Show other updates on this Mac`;
- `Open at login`, through `SMAppService.mainApp` `register()`/`unregister()`, showing the current status and any error text.

**`UserNotifier`** requests authorization the first time a package is added and posts each `Notice`. As the `UNUserNotificationCenterDelegate`, it calls `showPopover()` when a notification is clicked.

**`SystemEvents`.** Wire a one-minute timer, `NSWorkspace.didWakeNotification`, and an `NWPathMonitor` transition to `.satisfied` to `scheduledTick()`. The adapter's offline behavior is owned by `SystemEventsTests.scheduling`.

**At launch:** hydrate the catalog, then start a scheduled tick. Respect a blocked store load. With no Homebrew prefix, watched rows still show listed versions with the `Not installed` status, and Other updates is hidden.

**Release target.**
- Build products with `swift build -c release --product brew-version` and `swift build -c release --product BrewVersion`.
- Assemble `build/release/Brew Version.app/Contents/{MacOS/BrewVersion,Info.plist}` and copy `build/release/brew-version`.
- Run `codesign --force --sign - --timestamp=none` on each, then `codesign --verify --strict` on each.

**README app section.** What each part of the popover does, where state is kept, how to stop watching, and that removing the app leaves its Application Support and Caches folders to delete by hand.

- [ ] **Step 4: Run tests and the release build**

Run Swift suite.

Run Release build. Then run `plutil -extract CFBundleShortVersionString raw "brew_version/build/release/Brew Version.app/Contents/Info.plist"` and compare with the authority checked by `ReleaseTests.infoPlistMatchesRelease`.

- [ ] **Step 5: Manual acceptance on this Mac**

Open the app with `open "brew_version/build/release/Brew Version.app"`, then check each item and report it:
- the mug appears;
- searching a public formula shows its version, and Return watches it;
- notification permission is requested once;
- `NotificationAcceptance.newReleaseOpensPopover`: use an isolated acceptance harness with synthetic state and a controllable HTTPTransport. Add a package to establish its baseline, advance its listing identity, and check again. Click the resulting delivered system notification and verify `UserNotifier` opens the popover. The harness uses a separately identified, signed bundle and private temporary home outside the checkout; it must not read the owner's package inventory or reuse real app state. Restore notification permission/state through normal OS controls where needed; add no production simulation environment variable;
- Other updates lists packages, and Watch moves one into Watching;
- exercise `CheckIntervalTests`' invalid custom cases through the UI, and verify a valid interval changes the next-check display;
- exercise Removing a watch in Decisions through its UI entry points;
- click the footer Settings action and repeat Settings-opening gate against the assembled release; exercise the window's toggles and login status;
- inspect light and dark appearances.

Afterward, turn Open at login off and quit the app, because this copy lives in the build folder.

- [ ] **Step 6: Commit**

Subject `Add the Brew Version menu bar app`. Follow Commit protocol.

---

### Task 7: Deployment and fleet audit

**Files:**
- Create: `tools/deploy_brew_version.mjs`, `tools/tests/deploy_brew_version.test.mjs`, `tools/tests/brew-version-deployment-fixture.mjs`
- Modify: `tools/check_local_deployments.zsh`, `tools/tests/test_check_local_deployments.zsh`, `docs/local_deployment_sync.md`, `README.md`, `agents.md`, `brew_version/README.md`

**Interfaces:**
- Produces:
  - `node tools/deploy_brew_version.mjs [--dry-run | --audit | --rollback BACKUP] [--rebuild] [--repo DIR] [--scripts-dir DIR] [--apps-dir DIR] [--source-inventory FILE]`.
    - Scripts directory: `UTILITIES_SCRIPTS_DIR`, otherwise `~/Library/Scripts`.
    - Apps directory: `UTILITIES_APPS_DIR`, otherwise `~/Applications`. The fleet audit passes no `--apps-dir`, so it audits whatever that environment variable or the default names.
  - `export const buildInput = name => …`. It is true for `brew_version/Package.swift`, `brew_version/Makefile`, and anything under `brew_version/Resources/`, `brew_version/Sources/` or `brew_version/Tests/`; false for other project paths.
  - `export function sourceInventory(repo, snapshot, requireStaged = false)` and `export function appTreeHash(bundleDirectory)`.
  - Receipt `<scripts>/.brew-version-native.json`, mode 0600: `{schema: 1, sourceHash, version, commandHash, commandMode, appTreeHash}`.
  - Audit success line: `OK: brew-version native deployment`.

- [ ] **Step 1: Write the failing installer tests**

Use the fixture factory in `tools/tests/deploy_colophon.test.mjs` as the lifecycle harness reference. Adapt its invented build inputs to produce the Release target's artifact layout using a tiny C command and minimal app bundle, with the version read according to Global Constraints. The synthetic build signs its outputs and requires no Swift compilation. These artifact differences need specification because the reference fixture produces a standalone native command.

`assertActiveDeployment` is a fixture helper: independently snapshot expected bytes, entry types and full numeric modes for the active command, receipt and app tree. Include bundle-root and directory modes; do not rely solely on the installer's hash function. Use it after each lifecycle transition named below, following `docs/local_deployment_sync.md`, Adding a deployment.

Tests:
- `buildInputs`: the predicate above.
- `firstDeployReplacesExistingScript`: back up a synthetic existing bash command. The installed command is 0755; use `assertActiveDeployment` for the receipt contract and release app tree. Audit prints the success line from Interfaces and leaves fixture state unchanged.
- `updateOverPreviousRelease`: change a synthetic source, commit and deploy again. Use `assertActiveDeployment` for the new release, and verify the prior release's bytes and original-mode metadata in the new backup.
- `currentDeployChangesNothing`: a second deploy with no changes prints `already current; nothing changed` and writes nothing. `--rebuild` forces a build.
- `appStateSurvives`: synthetic files under the fixture's `Library/Application Support/Brew Version` and `Library/Caches/Brew Version` are byte-identical after deploy, rollback and audit.
- `auditDetectsDrift`: each of these makes `--audit` fail:
  - changed command bytes;
  - a changed command mode;
  - any changed file in the app bundle;
  - a changed receipt;
  - a changed tracked source.
- `dryRunWritesNothing`: snapshots of scripts and apps are unchanged.
- `activationFailureRestores`: make the installed command fail its version diagnostic; use `assertActiveDeployment` against the entire prior deployment. Cover failures after app activation and receipt publication as well as command activation.
- `rollbackRestoresPrevious`: use `assertActiveDeployment` to verify restored bytes and modes, and verify the replaced release was backed up before rollback.
- `refusesDestinationsInsideRepo`: parameterize over destination options; refuse symlinked ancestors too.
- `refusesUnstagedChanges`.
- `runningAppGetsRelaunchNotice`: stub the Running app process check; deployment succeeds and prints Copy's relaunch notice, without terminating the process.
- `bundleWithSymlinkIsRefused`.
- `backupModes`: assert the backup policy referenced under Backups, including saved app-tree modes.
- `auditDetectsAppModeDrift`: mutate a bundle file mode, a nested directory mode and the bundle-root mode independently; each audit fails.

- [ ] **Step 2: Run them to verify they fail**

Run Installer suite.
Expected: importing `../deploy_brew_version.mjs` fails.

- [ ] **Step 3: Implement `tools/deploy_brew_version.mjs`**

Behave as `tools/deploy_colophon.mjs`'s `sourceInventory`, `backup`, `readBackup`, `restore` and `main` do, using exports from `tools/deployment_files.mjs`. For conditional rebuilding, behave as `tools/deploy_storage_monitor.mjs:main` does. Apply the Brew Version differences below.

**Brew Version installer differences.**
- **Version:** follow Version in Global Constraints, extracting from the inventory bytes rather than an unvalidated working file.
- **Build:** `make -C <scratch>/brew_version release`, with a 900-second timeout.
- **Artifact rebuilding:** extend the referenced conditional-rebuild decision to a missing or drifted command or app bundle. A rebuild refreshes the Release target's artifact set together.
- **Toolchain check before building:** `xcrun --find swift`, `xcrun swift --version` and `make --version`; validate against Toolchain in Global Constraints. On failure, point to the maintained project README requirements.
- **Diagnostics:**
  - built and installed command: assert `RunCLITests.helpAndVersion` through the compiled executable;
  - app: assert `ReleaseTests.infoPlistMatchesRelease`'s version contract and Release target's signature verification;
  - the installer never launches the app.
- **App tree hash:** walk the bundle in sorted path order, including a root entry with relative path `.`. For each entry, feed `relative-path \0 type \0 mode-octal \0 sha256(bytes) \0` into one SHA-256; use full numeric permission modes, and empty content for directories. Refuse symlinks and anything other than directories and regular files.
- **App install:** copy the built bundle to a `.brew-version-stage-*` directory inside the apps directory and verify its tree hash. Move the existing bundle into the backup, then rename the staged bundle into place.
- **Backups:** use `~/.utilities-deploy-backups/brew-version/copy-*`. For the container, command, receipt and metadata, behave as Colophon's `backup`/`readBackup` do. Preserve the saved app's modes, record its tree hash in backup metadata and validate it before restore. Restoring an absent prior app removes the newly activated bundle. Keep a prior-release backup after successful activation.
- **Running app:** check with `pgrep -f "Brew Version.app/Contents/MacOS/BrewVersion"`; the command can be overridden by `BREW_VERSION_DEPLOY_PGREP` for tests. When the app is running, print the relaunch notice. Never quit the app.

- [ ] **Step 4: Run the installer tests**

Run Installer suite.
Expected: all pass.

- [ ] **Step 5: Register with the fleet audit (failing test first)**

1. **Fixture writer.** Behave as `tools/tests/native-deployment-fixture.mjs` does, adding an invented app bundle and using `sourceInventory`/`appTreeHash` from the new installer.
2. **Fixture setup:** extend `tools/tests/test_check_local_deployments.zsh:new_fixture` with the new installer and writer. Before its baseline commit, create synthetic project inputs matching `buildInput` and the audit registration's required inputs. Invoke the writer alongside the existing native fixture writers.
3. **New audit test.** Port `test_native_colophon_deployment` to `test_native_brew_version_deployment`, substituting the new artifact paths and labels. Add app-bundle byte and mode drift cases. Keep source-case selection tied to that function rather than a copied prose list.
4. **Required installers.** Add the new installer and its label to `test_native_required_installers`.
5. **Confirm the failure.** Run Fleet suite and inspect the new failure.

Then edit `tools/check_local_deployments.zsh`:
- add `brew_version` and `tools/deploy_brew_version.mjs` to `audited_scopes`;
- in `audit_native_deployment`, derive the expected stdout byte count from `printf '%s\n' "$success"` under a byte-counting locale instead of a label-specific constant;
- add an `audit_native_deployment` call for scope `brew_version` with:
  - installer `tools/deploy_brew_version.mjs`;
  - inventory file `brew-version-source-inventory` and output prefix `brew`;
  - label `brew-version native`;
  - drift message `brew-version native deployment unverified (source, command, app or receipt drift)`;
  - required inputs `brew_version/Package.swift`, `brew_version/Makefile`, `brew_version/Resources/Info.plist`, `tools/deploy_brew_version.mjs` and `tools/deployment_files.mjs`.

Run Fleet suite.

- [ ] **Step 6: Documentation**

- **`docs/local_deployment_sync.md`:** add "Native Brew Version deployment" after the Colophon section. Document this deliverable's Interfaces, installer differences and lifecycle contract by reference to the maintained installer/test symbols. Include runnable deploy, dry-run, audit, rollback and fleet-audit commands for operators. This operational command documentation is needed after the implementation plan is retired.
- **`README.md`:** add a `brew_version` utilities entry linking to its maintained README. Add it to the native-binaries sentence in Development and deployment.
- **`agents.md`:** add a Brew Version Validation Matrix entry pointing to the maintained Makefile suite/release targets and CLI smoke checks under Swift command line; require installer/fleet validation for deployment changes. Extend Static deployment/fleet audit tooling's installer command with the new test file, and register the native project in Repo Shape as an exception to UI Shapes.
- **`brew_version/README.md`:** add a deployment section that points to `docs/local_deployment_sync.md`.

- [ ] **Step 7: Run every affected suite**

Run these gates and report the results:
- Swift suite and Release build
- the installer and fleet-audit commands in `agents.md` under "Static deployment/fleet audit tooling", including `tools/tests/deploy_brew_version.test.mjs`
- the Market Atlas suites in `agents.md` under `Calculation tools/backtest`. They are required because `check_local_deployments.zsh` runs the static audit as a child process. Follow that entry's data rules: if the owner hasn't prepared the data, report the gate as unmet rather than preparing data.

Expected: every suite that can run passes, and any unmet Market Atlas data gate is stated as such.

- [ ] **Step 8: Commit**

Subject `Deploy Brew Version and add it to the fleet audit`. Follow Commit protocol.

---

## After the branch

When separately authorized under Commit protocol, push/open a PR, then deploy from merged `main` using `docs/local_deployment_sync.md`, Native Brew Version deployment.

Afterward:
- open `~/Applications/Brew Version.app`;
- confirm that `brew-version --version` and the Settings header show the release version;
- turn on Open at login if you want it.
