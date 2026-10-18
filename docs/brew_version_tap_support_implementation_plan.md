# Brew Version: Tap Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Brew Version watch, search, list and look up packages from the third-party taps you have added. Their versions are read from each tap's GitHub repository, so new tap releases show up before `brew update` runs.

**Architecture:**
- **Names:** `PackageName` and `TapName` represent package identity.
- **Local index:** a scan of your tapped repositories lists every formula and cask, without network or `git`.
- **Remote reads:** `TapClient` composes `TapFileReader` and `TapVersionDetector`.
- **One resolver:** `PackageResolver` owns lookup routing and bare-name resolution.

**Tech Stack:** Swift 6, SwiftUI hosted in AppKit, Swift Testing, Foundation only (no packages).

**Spec:** The design the owner approved on 2026-10-18. Its decisions are summarized under Decisions; where this plan and that design differ, Decisions governs. Read `brew_version/README.md` first, then `docs/local_deployment_sync.md` ("Native Brew Version deployment"). The Command line task updates the CLI's golden help fixture; see the deployment guide's installer contract.

## Decisions

1. **Bare-name search.** Typing a short name finds tap packages:
   - **Suggestions** follow the Suggestions contract under Watches, search and Other updates in the controller.
   - **A bare search token** returns the official result plus every tapped package with exactly that short name, each as its own labeled row. A token shows the not-found row only when neither source has a match.
   - **Accepted names:** use the `PackageName` contract under Tap-qualified names, tap errors and rollback-safe persistence.
2. **Watch identity.** Follow the controller's `add` and `checkNow` contracts and the CLI watch-polling contract. Source collisions are covered by Review Focus.
3. **Where versions come from.** Follow the `TapClient` response mapping and Reading rules under Reading formula and cask files as text.
4. **Installed versions.** Follow Admission under Installed versions with tap provenance.
5. **Other updates.** Follow the controller's tap-listing and `refreshCatalog` contracts.
6. **Command line.**
   - **Bare names:** official formula, then official cask (or only the kind `--formula`/`--cask` asks for), then a unique tap match.
   - **Ambiguity:** several tap matches is an error that lists them.
7. **Remotes and freshness.** Follow the Remote scan rule and `TapClient` contract. Version freshness is subject to the remote host's HTTP caching.
8. **Rollback safety.** Follow the `AppState` persistence contract under Tap-qualified names, tap errors and rollback-safe persistence.

## Global Constraints

- **Release:** version 1.1.0 and bundle build 4.
- **Public repository:** never write the owner's real taps, installed tap packages or their versions into code, tests, docs or commit messages.
  - **Fixture names:** tap `synthetic-owner/synthetic-tap`, whose repository is `synthetic-owner/homebrew-synthetic-tap`; packages `synthetic-tool` (formula), `synthetic-app` (cask) and `synthetic-shared` (exists both officially and in the tap).
  - **Fixture versions:** plainly invented values such as `4.5.6`, `7.8`, `9.0.1`.
  - **Fixture URLs:** any host the version parsers need (for example `github.com`, `registry.npmjs.org`, `sourceforge.net`), with `synthetic-…` path names.
- **No new subprocesses or code execution:** the app and CLI never run `brew`, `git` or Ruby. Tap files and `.git/config` are read as text.
- **Network:** HTTPS through the existing `URLSessionTransport.standard()`. A tap file's URL is `https://raw.githubusercontent.com/<remote owner>/<remote repository>/HEAD/<path in repository>`. Use the `GitHubRepository` fields defined under Local tap index and percent-encode each path component.

  Concurrency follows the `LookupScheduler.run` contract under Tap client and package resolver.
- **Tap names:** normalize typed and directory-derived names as Homebrew's `Tap.fetch` and `Tap#name` do (`Library/Homebrew/tap.rb`, using `HOMEBREW_OFFICIAL_REPO_PREFIXES_REGEX` from `Library/Homebrew/tap_constants.rb`). `TapName.isOfficial` is true for results identified by `Tap.fetch` as `CoreTap` or `CoreCaskTap`. Each normalized segment matches `^[a-z0-9][a-z0-9_.-]*$`.
- **Version port:** port from the Homebrew commit installed when you start (`git -C "$(brew --repository)" rev-parse HEAD`), and record it in the source header comment under the existing BSD notice (`Resources/Homebrew-LICENSE.txt`), as `VersionOrder.swift` does. Sources:
  - `Library/Homebrew/version.rb` (`Version.detect`, `Version.parse` and its `VERSION_PARSERS`, `NUMERIC_WITH_DOTS`, `NUMERIC_WITH_OPTIONAL_DOTS`, `MINOR_OR_PATCH`, `CONTENT_SUFFIX` and `PRERELEASE_SUFFIX` constants);
  - `Library/Homebrew/version/parser.rb` (`UrlParser`, `StemParser.process_spec`);
  - `Library/Homebrew/extend/pathname.rb` (`Pathname#extname`, `#stem`);
  - `Library/Homebrew/global.rb` (`HOMEBREW_BOTTLES_EXTNAME_REGEX`).
- **Commits:** an imperative subject and a body saying what changed and why, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` or the executing agent's own attribution. Work on the local branch `brew-version-tap-support`. Commit at the end of each task; push, open PRs and deploy only when the owner asks.

**Copy** (exact). `TAP` is `user/repo`, `FULL` is `user/repo/name`, `NAME` is the short name.

| Where | Text |
| --- | --- |
| Row error, tap removed | `TAP is no longer tapped.` |
| Row error, non-GitHub remote | `Only taps hosted on GitHub can be checked.` |
| Row error, file not on GitHub (404) | `Not found in TAP.` |
| Row error, version can't be read | `Can't read this tap's version.` |
| Row error, network | `Couldn't reach GitHub.` |
| Row error, other status | `GitHub returned HTTP STATUS.` |
| CLI | `Error: TAP is not tapped.` |
| CLI | `Error: TAP is not hosted on GitHub.` |
| CLI | `Error: FULL not found in TAP.` |
| CLI | `Error: could not read a version for FULL.` |
| CLI | `Error: could not reach GitHub for FULL.` |
| CLI | `Error: GitHub returned HTTP STATUS for FULL.` |
| CLI, ambiguous | `Error: NAME matches several taps: FULL1, FULL2. Use the full name.` (full names sorted, joined with `, `) |
| Notification title, tap package | `NAME VERSION is in TAP` (official packages keep their current title) |
| Commands | `brew upgrade FULL` / `brew upgrade --cask FULL`, with `install` in place of `upgrade` when not installed |
| Help, first line | `Fetch current package versions from Homebrew's public API, or from GitHub for packages in your taps.` |
| Help, replacing `  Third-party taps are not supported.` | `  Packages from your taps work too, written as user/tap/name.` then `  Use a full tap name to select a particular source.` |
| Other updates status, `tapCheckFailures` failures | `Couldn't check 1 tap package.` / `Couldn't check N tap packages.` |
| Other updates status, `tapUncheckable` failures | `1 tap package can't be checked.` / `N tap packages can't be checked.` |

## Review Focus

- **Source collisions and add identity:** `bareNamePrefersOfficialThenUniqueTap`, `bareSearchShowsOfficialAndTapRows`, `bareAddSavesResolvedFullName`, `bareAddDoesNotDuplicateFullWatch`, `concurrentBareAndFullAddsCoalesce`, `failedBareAddDoesNotSave`.
- **Removed taps:** `untappedWatchShowsErrorWithoutNotice`, `untappedLeftoverIsNotOfficialInstall`.
- **Version scope:** `nestedBlocksDoNotLeakVersions`, `conditionalArchBranches`, `dynamicVersionsAreUnreadable`.

---

## File Structure

```
brew_version/Package.swift                                    add resources: [.copy("Fixtures")] to BrewVersionCoreTests
brew_version/Sources/BrewVersionCore/
  PackageName.swift          TapName, tap-qualified PackageName
  TapVersionDetector.swift   new: Homebrew URL version detection port
  TapFileReader.swift        new: reads a formula or cask file as text
  TapIndex.swift             new: local tapped repositories and GitHub remotes
  TapClient.swift            new: raw.githubusercontent.com download, ETag, TapFileReader
  PackageResolver.swift      new: official vs tap routing, bare names, search expansion
  HomebrewClient.swift       LookupError tap cases; refuses tap names
  Search.swift               LookupScheduler runs any lookup
  InstalledReader.swift      tap provenance
  WatchState.swift           tap notice title; split persistence of tap entries
  WatchController.swift      resolver, tap index, tap Other updates, suggestions
brew_version/Sources/BrewVersionCLI/{Usage,RunCLI}.swift, Sources/brew-version/main.swift
brew_version/Sources/BrewVersion/{WatchRowView,SearchSection,OtherUpdatesSection,AppDelegate}.swift
brew_version/Tests/BrewVersionCoreTests/{TapNameTests,TapVersionDetectorTests,TapFileReaderTests,TapIndexTests,TapClientTests,PackageResolverTests,TapInstalledTests,TapControllerTests}.swift
brew_version/Tests/BrewVersionCoreTests/Fixtures/{tap-url-versions.json,state-1.0.2.json}
brew_version/Tests/BrewVersionCLITests/{RunCLITests.swift,Fixtures/expected-help.txt}
brew_version/Tests/BrewVersionAppTests/NativeActionsTests.swift
brew_version/Tests/Snapshots/Snapshots.swift
brew_version/{README.md,Resources/Info.plist}, brew_version/Sources/BrewVersionCore/Release.swift
agents.md, docs/lessons_learned.md
```

---

### Task 1: Tap-qualified names, tap errors and rollback-safe persistence

**Files:**
- Modify: `brew_version/Sources/BrewVersionCore/PackageName.swift`, `HomebrewClient.swift` and `WatchState.swift`
- Create: `brew_version/Tests/BrewVersionCoreTests/Fixtures/state-1.0.2.json` and `brew_version/Tests/BrewVersionCoreTests/TapNameTests.swift`
- Modify: `brew_version/Package.swift` (resources for `BrewVersionCoreTests`)

**Interfaces:**
- Produces:
  - `public struct TapName: Hashable, Codable, Sendable, CustomStringConvertible { public init?(_ raw: String); public let user: String; public let repo: String; public var description: String; public var isOfficial: Bool }`. It follows the tap-name rules in Global Constraints.
  - `PackageName` accepts `name` and `user/repo/name`; apply the Tap names constraint to the tap segments and the existing `PackageName.init?` grammar to the short name. Reject official taps. It gains `public var tap: TapName?` and `public var shortName: String`, and `rawValue` stays the full string.
  - `LookupError` gains these cases:
    - `.notTapped(TapName)`
    - `.unsupportedTapRemote(TapName)`
    - `.notFoundInTap(PackageName)`
    - `.unreadableTapVersion(PackageName)`
    - `.tapUnreachable(PackageName)`
    - `.tapHTTP(status: Int, PackageName)`
    - `.ambiguous(String, [PackageName])`

    Each new case's `cliMessage` and `rowMessage` follow the Copy table.
  - `HomebrewClient.lookup` throws `.notFound` for a name with a tap, without making a request.
  - `AppState` encoding writes official entries to `watched` and `listingCache`, and tap entries to `tapWatched` and `tapListingCache`. Decoding preserves order within each watch group and merges official entries before tap entries. Rolling back to 1.0.2 loads the official entries; that release ignores the tap keys and drops them on its first save.

- [ ] **Step 1: Write the fixture and failing tests.** `state-1.0.2.json` is a literal saved state in the 1.0.2 format with one official watch. Write it by hand, following `AppState`'s current coding keys.
  - `acceptsShortAndFullNames`: `synthetic-owner/synthetic-tap/synthetic-tool` has `tap?.description == "synthetic-owner/synthetic-tap"` and `shortName == "synthetic-tool"`. `synthetic-owner/homebrew-synthetic-tap/synthetic-tool` and `Synthetic-Owner/synthetic-tap/synthetic-tool` both normalize to that same value.
  - `normalizesTapAliases`: cover the prefix and core-alias cases in `Tap.fetch` and the official classification required by the Tap names constraint, for typed and directory-derived names.
  - `rejectsMalformed`, each `nil`:
    - `a/b`
    - `a/b/c/d`
    - `/a/b`
    - `a/b/`
    - `homebrew/core/x`
    - `homebrew/homebrew-cask/x`
    - `a b/c/d`
  - `acceptsOtherHomebrewTaps`: `homebrew/synthetic-extra/x` is a tap name.
  - `loads102State`: decoding the fixture gives one official watch and no problem.
  - `tapEntriesSaveUnderSeparateKeys`: an `AppState` with an official watch and a tap watch encodes JSON whose `watched` and `listingCache` contain no name with `/`, and whose `tapWatched` holds the tap watch. Decoding returns both, official first.
  - `tapErrorsUseCopy`: each new case's `cliMessage` and `rowMessage` equal the Copy table.
  - `officialClientRefusesTapNames`: the lookup throws `.notFound`, and `StubTransport` records no request.
- [ ] **Step 2: Run** `swift test --package-path brew_version --filter TapNameTests`. Expected: build errors for `TapName` and the new cases.
- [ ] **Step 3: Implement.** Keep the split in `AppState`'s `init(from:)` and `encode(to:)`.
- [ ] **Step 4: Run** `make -C brew_version test`. Expected: all suites pass. Any change to an existing test must be explained in the commit body.
- [ ] **Step 5: Commit** "Accept tap-qualified package names".

---

### Task 2: Homebrew URL version detection port

**Files:**
- Create: `brew_version/Sources/BrewVersionCore/TapVersionDetector.swift`, `brew_version/Tests/BrewVersionCoreTests/Fixtures/tap-url-versions.json` and `brew_version/Tests/BrewVersionCoreTests/TapVersionDetectorTests.swift`

**Interfaces:**
- Produces: `public enum TapVersionDetector { public static func detect(url: String, tag: String? = nil) -> String? }`. It behaves as `Version.detect` does, and returns `nil` where that returns a null version.

- [ ] **Step 1: Generate the parity corpus.** From the repository root, create a temporary directory and retain its absolute path in `tap_corpus_dir`. Write `$tap_corpus_dir/urls.json` as an array of `[url, tag-or-null]` pairs, with at least one URL per `VERSION_PARSERS` entry plus the tap shapes listed below. Use fixture names and versions from Global Constraints. Then, still from the repository root, run:
  ```bash
  brew ruby -e 'require "json"; rows = JSON.parse(File.read(ARGV[0])).map { |u, t| v = t ? Version.detect(u, tag: t) : Version.detect(u); {url: u, tag: t, version: (v.null? ? nil : v.to_s)} }; puts JSON.pretty_generate({homebrewCommit: `git -C #{HOMEBREW_REPOSITORY} rev-parse HEAD`.strip, rows: rows})' "$tap_corpus_dir/urls.json" > brew_version/Tests/BrewVersionCoreTests/Fixtures/tap-url-versions.json
  ```
  Tap shapes to include:
  - a release download with the version in both the tag and the file name;
  - a release download with the version only in the tag;
  - `archive/refs/tags`;
  - an npm registry tarball;
  - an `_os_arch` binary;
  - a date stamp;
  - a SourceForge `/download` URL;
  - a percent-encoded and a `+`-containing file name;
  - a bottle file name;
  - a URL with no version;
  - git URLs with a `tag`.
- [ ] **Step 2: Write the failing test.** `matchesHomebrewCorpus` asserts `detect(url:tag:) == version` for every row, naming the failing URL.
- [ ] **Step 3: Run** `swift test --package-path brew_version --filter TapVersionDetectorTests`. Expected: build error, since `TapVersionDetector` doesn't exist yet.
- [ ] **Step 4: Port the detection.** Port it from the sources in Global Constraints, in `VERSION_PARSERS` order. Porting checks:
  - Follow `Version.parse`'s decoding through `URI.decode_www_form_component`.
  - Follow `StemParser.process_spec`, `Pathname#extname` and `#stem` for filename processing.
  - Ruby's `{,n}` quantifier is not valid in `NSRegularExpression`; write it as `{0,n}`.

  Compile each expression once.
- [ ] **Step 5: Run** `make -C brew_version test`. Expected: pass, including every corpus row.
- [ ] **Step 6: Commit** "Port Homebrew URL version detection". The body names the pinned commit.

---

### Task 3: Reading formula and cask files as text

**Files:**
- Create: `brew_version/Sources/BrewVersionCore/TapFileReader.swift` and `brew_version/Tests/BrewVersionCoreTests/TapFileReaderTests.swift`

**Interfaces:**
- Consumes: `TapVersionDetector.detect`, `Listing` and `PackageName`.
- Produces: `public enum TapFileReader { public static let hostIsArm64: Bool; public static func listing(from text: String, name: PackageName, kind: PackageKind, arm64: Bool = hostIsArm64) -> Listing? }`. It returns `nil` when no version can be read. `Listing.name` is the full name.

**Reading rules:**
- **Statements:** read complete Ruby statements, joining continuation lines that end with `,`, `\` or an open parenthesis, so a multi-line `url "…", tag: "…", revision: "…"` is one statement. Skip comment lines and trailing comments outside strings.
- **Blocks:** track block nesting for `do … end`, `def`/`class`/`module … end`, and statement-leading `if`/`unless`/`case … end`, including `elsif`/`else`. A trailing `if`/`unless` modifier opens no block.
- **Where statements count:** at formula class-body level or the outer `cask "…" do` body, or inside these blocks nested in that package body:
  - `stable do`;
  - `on_macos do`;
  - `on_arm do` when `arm64`, or `on_intel do` otherwise;
  - the matching architecture branch of `if Hardware::CPU.arm?` or `if Hardware::CPU.intel?`, with `else` read as the other branch.

  Ignore every other block, including `resource`, `head`, `bottle`, `livecheck`, `patch`, `test`, `service`, `caveats` and `def`.
- **First wins:** take the first counting `version`, `url`, `revision`, `desc`, `homepage` and `auto_updates`. Collect every `app`.
- **String literals:**
  - Single-quoted and double-quoted strings without `#{` are literals.
  - In a `url`, a plain `#{version}` is replaced by the explicit version when there is one.
  - Any other interpolation, a non-literal argument, or a version built from method calls makes that statement unreadable.
- **Formula version:** use a readable explicit `version`. If an explicit version statement exists but is unreadable, return `nil` for the listing, even with a version-bearing URL; never treat unreadable as absent. Only when the statement is absent, call `TapVersionDetector.detect(url:tag:)` on the main `url`, passing its `tag:` keyword argument. The `revision N` statement sets `revision`; a `revision:` keyword inside a `url` statement does not.
- **Cask version:** `version "x"`, or `version :latest` (which is `latest`). `auto_updates true` sets `autoUpdates`. `app "X.app"` adds `X.app`, and `app "X.app", target: "Y.app"` adds the last path component of the target.

- [ ] **Step 1: Write the failing tests:**
  - `explicitFormulaVersionAndRevision`: `version "4.5.6"` plus `revision 2` gives version `4.5.6`, revision 2.
  - `versionFromURL`: `url "https://github.com/synthetic-owner/synthetic-tool/releases/download/v9.0.1/synthetic-tool-9.0.1.tgz"` gives `9.0.1`.
  - `interpolatedURLUsesExplicitVersion`: `version "7.8"` plus `url ".../v#{version}/synthetic-tool-#{version}.zip"` gives `7.8`.
  - `nestedBlocksDoNotLeakVersions`: a `resource` block with a different-version URL placed before the main `url`, plus `head`, `bottle do` and `livecheck do` blocks, still gives the main URL's version.
  - `conditionalArchBranches`: exercise every architecture predicate listed in Reading rules with each `arm64` value, distinct versions in the selected and unselected branches, and with and without `else`. Require the selected version or `nil` when no branch applies. Regress a trailing `url "…" if OS.mac?` modifier's block depth.
  - `stableAndArchBlocks`: a version inside `stable do` is read; distinct `on_arm` and `on_intel` URLs choose by `arm64`.
  - `multiLineGitURL`: a `url "https://github.com/synthetic-owner/synthetic-tool.git",` line followed by continuation lines `tag: "v4.5.6",` and `revision: "0123abcd"` gives version `4.5.6` and revision 0.
  - `dynamicVersionsAreUnreadable`: each of these gives `nil`:
    - `version "#{x}"`
    - `version ENV["V"]`
    - `version "1.#{y}"`
    - a `url` with `#{something_else}` and no explicit version
    - a file with no `url` or `version`
  - `dynamicExplicitVersionNeverFallsBack`: pair each unreadable explicit-version form with a readable version-bearing URL; require `nil` rather than the URL's version.
  - `caskFields`: `version "4.5.6"`, `auto_updates true`, a `desc`, a homepage on `example.invalid`, and `app "Synthetic.app", target: "Renamed.app"` produce matching fields, with `appNames == ["Renamed.app"]`.
  - `completePackageWrappers`: pass complete synthetic formula and cask files, including their outer declaration and nested ignored blocks, through `listing(from:name:kind:arm64:)`; require the package's fields and reject fields outside its package body.
  - `caskLatest`: `version :latest` gives `latest`.
  - `commentsIgnored`: a commented-out `version` line and a trailing comment don't count.
- [ ] **Step 2: Run** `swift test --package-path brew_version --filter TapFileReaderTests`. Expected: build errors.
- [ ] **Step 3: Implement** following the reading rules. `hostIsArm64` uses `#if arch(arm64)`.
- [ ] **Step 4: Run** `make -C brew_version test`. Expected: pass.
- [ ] **Step 5: Commit** "Read tap formula and cask versions as text".

---

### Task 4: Local tap index

**Files:**
- Create: `brew_version/Sources/BrewVersionCore/TapIndex.swift` and `brew_version/Tests/BrewVersionCoreTests/TapIndexTests.swift`

**Interfaces:**
- Consumes: `TapName`, `PackageName` and `HomebrewPrefix`.
- Produces:
  - `public struct GitHubRepository: Hashable, Sendable { public let owner: String; public let repo: String }`. Extract these fields from the origin normalized by the Remote scan rule; keep the repository segment intact rather than applying tap-name normalization.
  - `public struct TapEntry: Hashable, Sendable { public let name: PackageName; public let kind: PackageKind; public let path: String; public let repository: GitHubRepository? }`. `path` is relative to the tap's repository root.
  - `public struct TapIndex: Sendable`, with:
    - `public static func scan(prefixes: [HomebrewPrefix]) -> TapIndex`
    - `public static let empty: TapIndex`
    - `public var taps: Set<TapName>`
    - `public func entries(shortName: String, kinds: KindPreference) -> [TapEntry]`
    - `public func entry(_ name: PackageName, kind: PackageKind?) -> TapEntry?`. A `nil` kind prefers the formula.
    - `public func suggestions(prefix: String) -> [TapEntry]`
    - `public func repository(for tap: TapName) -> GitHubRepository?`

**Scan rules:**
- **Where taps live:** read `Library/Taps` under each prefix's Homebrew repository: the prefix itself when `<prefix>/Library/Taps` exists, and `<prefix>/Homebrew/Library/Taps` otherwise.
- **Files:** discovery behaves as `Tap#formula_dir`, `#formula_files`, `#formula_files_by_name`, `#cask_dir`, `#cask_files` and `#cask_files_by_name` do in `tap.rb`.
- **Remote:** read `[remote "origin"] url` from `.git/config` and normalize as `Tap.normalize_remote` does in `tap.rb`. Extract `GitHubRepository` only from a normalized `https://github.com/<owner>/<repository>` URL; otherwise `repository == nil`.
- **Skipped:** hidden directories, directories without `.git`, taps whose `TapName.isOfficial` is true, and files whose basenames fail the existing `PackageName.init?` short-name grammar.

- [ ] **Step 1: Write the failing tests** with a synthetic prefix in a temporary directory:
  - `scansLayouts`: `Taps/synthetic-owner/homebrew-synthetic-tap`, with `Formula/synthetic-tool.rb`, `Formula/s/synthetic-nested.rb`, `Casks/synthetic-app.rb` and `Casks/s/synthetic-shared.rb`, gives four entries with the right kinds, full names and paths.
  - `formulaDirectoryPrecedence`: verify discovery against `Tap#formula_dir` and `#formula_files`, including their directory-precedence and root/sharded-scope cases.
  - `duplicateShardKeepsLongerPath`: exercise formula and cask duplicates against their respective name-to-file mappings in the Files scan rule.
  - `intelRepositoryLayout`: taps under `<prefix>/Homebrew/Library/Taps` are found.
  - `remoteParsing`: exercise `https://`, `git@github.com:`, `ssh://git@github.com/` and `git://github.com/` synthetic remotes, suffix variants and mixed case against the Remote scan rule; also cover a non-GitHub host and a missing `origin`.
  - `packageBasenamesKeepExistingGrammar`: cover the punctuation accepted by `PackageName.init?` in formula and cask filenames, separately from tap-segment validation.
  - `skipsOfficialAndInvalid`.
  - `queries`:
    - `entries(shortName: "synthetic-shared", kinds: .auto)` returns the tap cask.
    - `suggestions(prefix: "synthetic-t")` includes `synthetic-tool`.
    - `entry(fullName, kind: nil)` prefers the formula.
  - `rescanSeesNewTaps`.
- [ ] **Step 2: Run** `swift test --package-path brew_version --filter TapIndexTests`. Expected: build errors.
- [ ] **Step 3: Implement.** Sort entries by full name, then kind.
- [ ] **Step 4: Run** `make -C brew_version test`. Expected: pass.
- [ ] **Step 5: Commit** "Index tapped repositories from the local Taps folder".

---

### Task 5: Tap client and package resolver

**Files:**
- Create: `brew_version/Sources/BrewVersionCore/TapClient.swift`, `PackageResolver.swift`, `brew_version/Tests/BrewVersionCoreTests/TapClientTests.swift` and `PackageResolverTests.swift`
- Modify: `brew_version/Sources/BrewVersionCore/Search.swift` and `WatchController.swift` (scheduler call sites only)

**Interfaces:**
- Consumes: `TapIndex`, `TapEntry`, `TapFileReader`, `HomebrewClient`, `ListingCache` and `LookupError`.
- Produces:
  - `public struct TapClient: Sendable { public init(transport: any HTTPTransport, cache: ListingCache? = nil); public func lookup(_ entry: TapEntry) async throws -> Listing }`. It requests the URL from Global Constraints with `If-None-Match`, and maps responses as follows:
    - 200 reads the file through `TapFileReader`; `nil` throws `.unreadableTapVersion`.
    - 304 with a cached entry returns that listing; 304 without one throws `.tapHTTP(status: 304, …)`.
    - 404 throws `.notFoundInTap`.
    - Other 3xx and transport failures throw `.tapUnreachable`.
    - Any other status throws `.tapHTTP`.
    - An entry with no `repository` throws `.unsupportedTapRemote`.
  - `public struct PackageResolver: Sendable`, with:
    - `public init(client: HomebrewClient, tapClient: TapClient, taps: TapIndex)`
    - `public func lookup(_ name: PackageName, kinds: KindPreference) async throws -> Listing`. It looks up exactly that identity: official names through `client`; tap names require the tap in `taps.taps` (otherwise `.notTapped`) and an entry of an allowed kind (otherwise `.notFoundInTap`).
    - `public func resolveBare(_ name: PackageName, kinds: KindPreference) async throws -> Listing`. It applies the Command line decision. Fall back to tap matches only after the allowed official kinds return `.notFound`; propagate other official errors. Group the allowed tap entries by `PackageName` before deciding ambiguity. For a unique identity, choose its entry in `KindPreference.candidates` order. For multiple identities, throw `.ambiguous` with distinct full names; with none, rethrow the official `.notFound`.
    - `public func tapMatches(_ name: PackageName, kinds: KindPreference) -> [TapEntry]`
    - **Initial lookups:** use `resolveBare` for a bare input and `lookup` for a full input.
  - `LookupScheduler.run<T: Sendable>(_ work: @Sendable () async throws -> T) async throws -> T` replaces its client-specific method. Wrap the controller's lookups in `add`, `search`, `checkNow` and tap Other updates with the same scheduler instance, so they share its permit pool. The call sites modified in this task retain their existing lookup behavior until the controller task.

- [ ] **Step 1: Write the failing tests:**
  - `TapClientTests.requestsRemoteRepositoryPath`: for an entry whose repository is `synthetic-owner/homebrew-synthetic-tap` and whose path is `Formula/synthetic-tool.rb`, the request URL is exactly `https://raw.githubusercontent.com/synthetic-owner/homebrew-synthetic-tap/HEAD/Formula/synthetic-tool.rb`.
  - `TapClientTests.etagRoundTrip`: a 200 with an ETag is cached, and the next call sends `If-None-Match` and accepts a 304.
  - `TapClientTests.errorMapping`: every response row in the mapping above gives its error.
  - `PackageResolverTests.bareNamePrefersOfficialThenUniqueTap`:
    - `synthetic-shared` exists officially (formula 200) and in the tap; `resolveBare` returns the official listing.
    - `synthetic-tool` is official 404/404 and unique in the tap, so it returns the tap listing with its full name.
  - `PackageResolverTests.ambiguousAcrossTaps`: two taps share a short name, so it throws `.ambiguous` with both full names sorted.
  - `PackageResolverTests.fullNameRequiresTappedTap`.
  - `PackageResolverTests.kindPreferenceFiltersTaps`.
  - `PackageResolverTests.sameTapKindsAreNotAmbiguous`: a formula and cask with the same full name resolve according to `KindPreference.candidates`; adding a distinct matching tap identity produces the ambiguity required by `resolveBare`, without repeated names.
  - `PackageResolverTests.lookupNeverFallsBack`: `lookup(PackageName("synthetic-tool"))` with official 404/404 throws `.notFound` even though the tap has `synthetic-tool`.
  - `PackageResolverTests.schedulerBoundsTapLookups`: following the existing scheduler test's held-transport pattern, more concurrent tap lookups than the scheduler's limit never exceed that limit in flight.
- [ ] **Step 2: Run** `swift test --package-path brew_version --filter 'TapClientTests|PackageResolverTests'`. Expected: build errors.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `make -C brew_version test`. Expected: pass.
- [ ] **Step 5: Commit** "Look up tap packages from GitHub and resolve bare names".

---

### Task 6: Installed versions with tap provenance

**Files:**
- Modify: `brew_version/Sources/BrewVersionCore/InstalledReader.swift`
- Create: `brew_version/Tests/BrewVersionCoreTests/TapInstalledTests.swift`

**Interfaces:**
- Consumes: `TapName` and `PackageName.tap` / `shortName`.
- Produces:
  - `InstalledReader.init` gains `tappedTaps: @escaping @Sendable () -> Set<TapName> = { [] }`.
  - **Admission:** retain `admittedVersion`'s official and legacy-cask admission paths. Extend receipt admission to normalized `source.tap` values in `tappedTaps()`; exclude removed taps. Keep the existing filesystem and receipt-validation guards.
  - **Snapshot keys:** official installs are keyed by short name, tap installs by full name.
  - **Point lookups:** `installed(_:kind:listing:)` reads the rack named `name.shortName`. For an official name (`name.tap == nil`), retain `admittedVersion`'s kind-specific official receipt check and legacy-cask behavior. For a tap name, require an admitted receipt whose normalized tap equals `name.tap`; a missing receipt cannot establish tap provenance. Share this provenance classification with snapshot-key derivation.

- [ ] **Step 1: Write the failing tests**, using `InstallationFixture`:
  - `tapInstallKeyedByFullName`
  - `untappedLeftoverIsNotOfficialInstall`: a rack named `synthetic-shared` whose receipt names a tap that isn't tapped is returned neither for the official name nor in the snapshot.
  - `officialWatchIgnoresTapInstall`
  - `pointLookupProvenance`: exercise official formula/cask receipts, cross-kind official receipts, legacy casks, matching and mismatched tap receipts, and removed taps; require point lookups and snapshot keys to agree.
  - `tapCaskAppBundle`: a self-updating tap cask reads its app version, as official casks do.
- [ ] **Step 2: Run** `swift test --package-path brew_version --filter TapInstalledTests`. Expected: build errors, then failures.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `make -C brew_version test`. Expected: pass, with the existing `InstalledReaderTests` unedited.
- [ ] **Step 5: Commit** "Read installed tap packages by their tap".

---

### Task 7: Command line

**Files:**
- Modify: `brew_version/Sources/BrewVersionCLI/RunCLI.swift`, `Usage.swift`, `brew_version/Sources/brew-version/main.swift` and `brew_version/Tests/BrewVersionCLITests/Fixtures/expected-help.txt`
- Test: `brew_version/Tests/BrewVersionCLITests/RunCLITests.swift`

**Interfaces:**
- Consumes: `PackageResolver`, `TapIndex.scan` and `TapClient`.
- Produces: `CLIEnvironment` gains `taps: TapIndex`, defaulting to `.empty` in its public init. `main.swift` passes a scan of the same prefix candidates `AppDelegate` uses. Apply the resolver's Initial lookups contract. In watch mode, retain the resolved `listing.name` per argument and use `lookup` for later polls. Use that full identity in watch output so the selected source is visible.

- [ ] **Step 1: Write the failing tests:**
  - `fullTapNamePrintsVersion`
  - `bareNameFallsBackToTap`
  - `ambiguousBareNameExplains`: stderr is the Copy line, exit 1.
  - `untappedFullName`: stderr is the Copy line, exit 1.
  - `watchWorksForTapNames`
  - `bareWatchKeepsResolvedIdentity`: after the initial bare-name resolution, change official/tap availability between polls and assert later requests still target the resolved identity and watch output identifies it; loss of that source is an error rather than a new resolution.
  - `UsageTests.expectedHelp` against the updated fixture.
- [ ] **Step 2: Run** `swift test --package-path brew_version --filter 'RunCLITests|UsageTests'`. Expected: failures.
- [ ] **Step 3: Implement.** Apply the help rows of the Copy table to `Usage.swift` and `expected-help.txt`.
- [ ] **Step 4: Run** `make -C brew_version test`, then `node --test tools/tests/deploy_brew_version.test.mjs` (see the Spec's deployment-guide reference). Expected: pass.
- [ ] **Step 5: Commit** "Let brew-version look up tap packages".

---

### Task 8: Watches, search and Other updates in the controller

**Files:**
- Modify: `brew_version/Sources/BrewVersionCore/WatchController.swift` and `WatchState.swift`
- Create: `brew_version/Tests/BrewVersionCoreTests/TapControllerTests.swift`

**Interfaces:**
- Consumes: `TapIndex`, `TapClient`, `PackageResolver` and the provenance-aware `InstalledReader`.
- Produces:
  - **Tap index:** `WatchController.init` gains `taps: @escaping @Sendable () -> TapIndex = { .empty }`. `public private(set) var tapIndex: TapIndex` is set from that closure in `init`, before any check can run. It is rescanned at the start of `refreshCatalog` and `refreshNow`.
  - **Resolver:** a computed `resolver` builds `PackageResolver` from the current `client`, a `TapClient` on the same `cache`, and `tapIndex`. Replacing the cache in `remove` and `retryLoad` therefore rebuilds the tap client too.
  - **Tap listings for Other updates:** retain `private var tapListings: [PackageKind: [PackageName: Listing]]` between refreshes. Maintain a combined `Catalog` from `(catalog?.listings ?? [])` and the retained tap listings, including when no official catalog exists. Rebuild its identity only when a source changes; use that identity throughout `refreshInstalled`'s capture, derivation and publication checks, replacing its official-only catalog dependency.
  - **Failure counts:** `public private(set) var tapCheckFailures: Int` and `public private(set) var tapUncheckable: Int` count installed tap packages whose last refresh failed with `.tapUnreachable`/`.tapHTTP`, or with `.unreadableTapVersion`/`.unsupportedTapRemote`/`.notFoundInTap`.
  - **Installed names:** `public private(set) var installedNames: [PackageKind: Set<PackageName>]` holds the latest snapshot's keys by kind and is refreshed by `refreshInstalled`.
  - **Suggestions:** `public struct Suggestion: Equatable, Sendable { public let name: PackageName; public let kind: PackageKind; public let installed: Bool }` and `public func suggestions(prefix: String, limit: Int = 8) -> [Suggestion]`.
    - It collects every official prefix match (pass an unlimited limit to `Catalog.suggestions`) and every `tapIndex.suggestions` match.
    - For queries containing `/`, it matches full-name prefixes.
    - Order: installed (membership in `installedNames` for that entry's kind) first, then an exact short-name match, then official before tap, then by full name; then it cuts to `limit`.
  - **Notices:** `evaluate` uses the tap title from the Copy table when `entry.name.tap != nil`.

**Behavior:**
- **`add`** applies the resolver's Initial lookups contract.
  - Keep request coalescing while resolving. On success, use `listing.name` for the `WatchEntry`, installed-version lookup and generation key. Before awaiting installed data, atomically check that resolved identity against saved watches and pending adds from other calls, then reserve it through the save. Recheck `canSave` and saved-watch membership against that identity after the final await. Release request and identity reservations on every exit.
  - A failed bare resolution saves no watch, listing cache or generation entry. Show the lookup error in a `.failed` search result for that name if the initiating search generation is still current; a later add can retry. A reference to existing failure behavior would preserve an unresolved identity, so this failure rule replaces that path for bare adds. Full-name lookup failures retain the current error-watch behavior because the identity is explicit.
- **`checkNow`** uses `resolver.lookup` on the saved name only, following that method's error distinctions. `.tapUnreachable` counts like `.unreachable` for the reconnect retry and for keeping `lastCheck`.
- **`search`** implements the Bare-name search decision using `resolver.tapMatches` for tap expansion.
- **`refreshCatalog`** retains its due, network, persistence and retry-floor gates. Once admitted, attempt the optional official catalog refresh and the installed-tap refresh independently. The tap branch obtains an installed snapshot even without an official catalog, uses the resolver through the shared scheduler, and updates `tapListings` and its failure counts. An official exception or absent `catalogClient` must not skip this branch. A source failure retains its previous listings and records its error without changing the other source's result; tap success must not clear an official error or advance the official-success timestamp. Refresh installed updates after source publication using the combined catalog contract.

- [ ] **Step 1: Write the failing tests:**
  - `bareSearchShowsOfficialAndTapRows`: `search("synthetic-shared")` gives the official row, then the tap row.
  - `bareSearchNotFoundOnlyWhenNoSource`: an official miss with a tap match shows no not-found row.
  - `bareAddSavesResolvedFullName`: verify the `add` contract's saved identity, installed-version association and subsequent check target.
  - `bareAddDoesNotDuplicateFullWatch`: start with a saved full-name watch, add its bare name, and require unchanged watch state and a clean `WatchStore.load()`.
  - `concurrentBareAndFullAddsCoalesce`: hold resolution and installed reads to complete bare/full requests in each order; require one saved identity, preserved watch metadata, released reservations and a clean reload.
  - `failedBareAddDoesNotSave`: cover offline/transport errors, official HTTP errors, not-found, ambiguity and tap lookup errors; require unchanged saved bytes and watch/cache/generation state, a visible error for the current search, no stale error after a new search, and successful retry after recovery.
  - `checkNeverSwitchesSource`: a saved official watch whose official lookup fails never uses the tap.
  - `addAndCheckTapWatch`: a newer tap version against an older installed tap keg posts the tap title and turns the row amber.
  - `untappedWatchShowsErrorWithoutNotice`: after the `taps` closure stops returning the tap, `refreshNow()` sets the not-tapped error, keeps `lastListing`, and posts nothing.
  - `missingFileInPresentTapUsesNotFoundInTap`: remove a watched entry while retaining its tap in the index; require the resolver's missing-entry error, retained last listing and no notice.
  - `indexReadyBeforeFirstCheck`: with no `catalogClient`, a tap watch's first `checkNow()` succeeds.
  - `tapOtherUpdatesSurviveLaterChecks`: an installed, out-of-date tap formula appears in `others` after `refreshCatalogIfDue()` and is still there after `checkNow()`.
  - `tapOtherUpdatesWithoutOfficialCatalog`: with no official cache, fail the official fetch while GitHub succeeds; require the tap update, preserved official error and unchanged official-success timestamp. Also cover absent `catalogClient`, successful official recovery and the existing retry floor.
  - `tapKindsStaySeparate`: retain formula and cask listings sharing a full name through refresh/check overlap; require kind-specific Other updates and installed suggestion flags, with no cross-kind overwrite.
  - `tapFailureCounts`: an unreachable tap package increments `tapCheckFailures`; an unreadable one increments `tapUncheckable`; the official results are unchanged.
  - `suggestionsRankInstalledTapFirst`: with more official prefix matches than the limit and an installed tap package, the installed tap entry comes first.
  - `sameShortNameWatchesStaySeparate`.
- [ ] **Step 2: Run** `swift test --package-path brew_version --filter TapControllerTests`. Expected: build errors, then failures.
- [ ] **Step 3: Implement** the behavior above.
- [ ] **Step 4: Run** `make -C brew_version test`. Expected: pass; explain any edit to an existing test in the commit body.
- [ ] **Step 5: Commit** "Watch, search and list tap packages".

---

### Task 9: Interface, snapshots, docs and release

**Files:**
- Modify: `brew_version/Sources/BrewVersion/WatchRowView.swift` (`PackageRow`), `SearchSection.swift`, `OtherUpdatesSection.swift` (`CatalogStatusLine`) and `AppDelegate.swift`
- Modify: `brew_version/Tests/BrewVersionAppTests/NativeActionsTests.swift` and `brew_version/Tests/Snapshots/Snapshots.swift`
- Modify: `brew_version/README.md`, `brew_version/Resources/Info.plist`, `brew_version/Sources/BrewVersionCore/Release.swift`, `agents.md` and `docs/lessons_learned.md`

**Interfaces:**
- Consumes: `WatchController.suggestions`, `tapCheckFailures`, `tapUncheckable` and `PackageName.tap` / `shortName`.

**Interface rules:**
- **Rows:** `PackageRow` titles a tap package with its short name, followed by its tap in 11-point secondary text. The help tooltip and accessibility label use the full name. The row's commands follow the Copy table.
- **Suggestions:** suggestion rows come from `controller.suggestions(prefix:)` and show the tap (nothing for official packages) and "Installed" when installed.
- **Other updates status:** `CatalogStatusLine` appends the Copy rows for `tapCheckFailures` and `tapUncheckable` when their counts are non-zero.
- **App setup:** `AppDelegate` passes `taps:` and `tappedTaps:` closures over the same prefix list it already detects.

- [ ] **Step 1: Write the failing tests:** `tapRowTitleAndCommand` and `tapStatusCopy` in `NativeActionsTests`.
- [ ] **Step 2: Run** `swift test --package-path brew_version --filter NativeActionsTests`. Expected: failures. **Step 3: Implement.**
- [ ] **Step 4: Add snapshot states.** In `Snapshots.swift`, add a watching state with official, amber tap and untapped-error rows, and a tap-suggestion state. Update the state list and count there (`Snapshots.swift`, near its "Validated" output), in `brew_version/README.md`'s Build and test section and in `agents.md`'s Validation Matrix entry.
- [ ] **Step 5: Docs and release.**
  - **README:** add a "Taps" section covering every Decision, including Rollback safety. Update the overview, Requirements network bullet, Command usage name grammar and lookup policy, Compatibility with the bash command, and the installed-receipt rules in Catalog and Other updates. Replace the Command usage prohibition on third-party taps with a reference to Taps.
  - **Lessons learned:** add an entry on porting Homebrew's URL version detection with a generated parity corpus.
  - **Version:** set the release version in `Info.plist` and `Release.swift`.
- [ ] **Step 6: Run every validation and report each result:**
  - `make -C brew_version test`, `release`, `acceptance` and `snapshots`, inspecting every maintained PNG;
  - `brew_version/build/release/brew-version --help` and `--version`, the latter reporting the release version;
  - `node --test tools/tests/deploy_brew_version.test.mjs` and `zsh tools/tests/test_check_local_deployments.zsh`.
  - Complete and record the README's Settings and native acceptance gates separately from the automated targets, including tap rows, suggestions, commands and status copy. Owner-dependent or unavailable checks remain unmet release gates; do not report them as passed from offscreen rendering or the harness build.
- [ ] **Step 7: Commit** "Show tap packages in Brew Version and prepare the release".

---

## After the branch

Stop and report under the Commits constraint.

After an owner-approved deploy from `main`, check that these agree with the release version:
- the source;
- the deploy receipt;
- `~/Library/Scripts/brew-version --version`;
- the installed and running app (`Info.plist`, and the Settings footer).

Also confirm that Open at login points at the installed app, and report the release version.
