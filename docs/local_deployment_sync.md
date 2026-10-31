# Local Deployment Synchronization

This repository is the canonical public source. Copies under `~/Library/Scripts` and top-level project directories under `~/` are deployment targets, not additional source repositories.

## Non-destructive rules

1. Validate repository source before deploying it.
2. Back up every destination file that will be replaced.
3. For direct copies and maintained source trees, copy only files tracked by Git. Never mirror a whole directory and never use `rsync --delete` against a live local project. Market Atlas is a narrow static-runtime exception: validated source and selected external local history supply exactly twelve copied runtime files. This does not authorize public data redistribution or copying its private inputs and recovery records into the repository.
4. Preserve ignored/local-only configuration, databases, exports, generated tables, logs, venvs, and runtime state.
5. After copying, compare the deployed artifact with its source and exercise documented offline diagnostics where available. App-only artifacts have no command diagnostic contract: never execute their GUI binary with `--help` or `--version` during an audit.
6. For Docker, capture which stacks are running before maintenance and restore the same running/stopped state afterward.

Run the read-only audit from the repository root:

```bash
zsh tools/check_local_deployments.zsh
```

The audit is read-only with respect to the repository, Git index, deployments,
configuration, and runtime state. It creates and removes one validated private
temporary directory for status-checked command output and bounded Model
Sentinel entry streams. It never prints protected configuration contents.

The audit contract is:

- One validated stage-0 Git-index snapshot defines current source for direct
  mappings, maintained top-level projects, the Time Machine Snapshot Monitor
  tree, Model Sentinel, and tracked repository `.gitignore` files. Staged
  additions are included; untracked files are excluded.
- Current direct and maintained-project files are compared byte-for-byte.
  Their complete numeric permission modes must also match, including setuid,
  setgid, and sticky bits as well as ordinary read/write/execute bits.
- An indexed source missing from the working tree, a staged deletion, an
  unmerged entry, a sparse-directory entry, a symlink, a submodule, or another
  unsupported indexed type fails as incomplete source state instead of being
  silently skipped.
- Model Sentinel must be a regular non-symlink file with its owner-execute bit
  set and must be executable by the audit process. The audit checks the exact
  executable preamble, bidirectional archive inventory, entry types,
  encryption state, advertised sizes, bounded streamed sizes, and contents.
  It lists before reading contents and never bulk-extracts the archive.
- Protected local configuration files must be regular non-symlink files at
  exactly `0600`. The n8n state check covers the top-level
  `~/.local/state/n8n-poc` directory at exactly `0700`; it does not recursively
  verify every descendant directory and file mode.

For maintained top-level projects, stale candidates come from pathname
deletions in the current `HEAD` first-parent history. Rename detection is
disabled deliberately, so the old pathname from a rename is treated as
deleted. Only current index membership suppresses a deleted pathname as a
re-add. A non-ignored untracked source object at the same pathname does not.

Repository ignore rules can classify a historical pathname as intentional
local-only state only when the winning positive rule comes from a tracked
stage-0 `.gitignore` inside this worktree. Untracked ignore files, global
excludes, `.git/info/exclude`, and winning `!` re-inclusion rules are not
authoritative. Shallow Git history fails stale-file coverage rather than
silently passing. History cannot detect source files deleted before the
retained public repository history began.

Stale detection reports aggregate counts and never deletes deployment files.
Removal remains a separately authorized operation performed with backups.

## Adding a deployment

Define the deployment form before building its installer or audit:

| Form | Deployment contract |
| --- | --- |
| Direct file copy | Explicit source-to-destination mappings; installed bytes and permission modes match the tracked files. |
| Maintained source tree | An explicit inventory of maintained files; updates preserve local-only configuration and runtime state. |
| Generated static artifact | A declared source/data inventory and build recipe; verify the built runtime inventory and installed bytes independently of source tests. |

Direct copies and maintained source trees retain the tracked-copy rules above.
Generated artifacts use their explicitly admitted inputs and runtime inventory;
Market Atlas follows the installer-only exception in rule 3. All forms preserve
local state.
Document the activation boundary, backups, rollback behavior, and what the
read-only audit verifies for the chosen form.

Reuse or build a small isolated fixture harness to prove the lifecycle early,
using conspicuously synthetic inputs and temporary source, destination, and
state directories. Invoke the actual deployment CLI to install a first release,
update it, exercise a controlled activation failure, roll back, and run the
read-only audit. Assert the expected active bytes and modes after each step,
that a failed activation preserves or restores the previous working release,
and that local-only state survives. Verify that the audit leaves source,
deployment, configuration, and runtime state unchanged. Establish this basic
path before expanding meaningful project-specific edge cases, such as an
interrupted update or invalid input; avoid building a general framework before
the working deployment path is proven.

Keep fast synthetic deployment tests separate from slower historical-data and
browser acceptance. Both remain required wherever applicable: synthetic
fixtures make failure paths repeatable, while full acceptance verifies the
actual application and artifact. Neither category replaces the other or
reduces the project's complete documented validation suite.

Existing references include the [read-only fleet audit](../tools/check_local_deployments.zsh)
and its [isolated fixture tests](../tools/tests/test_check_local_deployments.zsh),
plus Market Atlas's [synthetic artifact fixture](../Calculation%20tools/backtest/tests/helpers/static-fixture.cjs)
and [static deployment tests](../Calculation%20tools/backtest/tests/static-deploy.test.js).
These are project-specific implementations, not an established shared
deployment library. After implementations pass their required gates, identify
the common pieces from working code as a future extraction; do not
assume a common framework already exists.

## Market Atlas generated static deployment

The [project guide](../Calculation%20tools/backtest/README.md),
[data guide](../Calculation%20tools/backtest/data/README.md) and
[test guide](../Calculation%20tools/backtest/tests/README.md) describe local acquisition,
external history and complete validation. The runtime is twelve flat files:
HTML, eight app modules, the data JS/CSV pair and the source notice. Build and
browser operation work offline after setup. Real history, builds and backups
stay outside the public checkout.

From the child project, the owner prepares data and builds (agents never run
data acquisition; the data is not redistributable), then reviews the dry-run:

```sh
npm run setup:data   # owner only: may download workbooks
npm run build -- --offline
npm run deploy -- --dry-run --webroot "<WEBROOT>"
```

Build defaults to `<DATA_HOME>/site`. Deploy consumes that existing build,
compares it against source and selected data, then moves the exact prior app
tree into a timestamped private container under
`~/.utilities-deploy-backups/backtest/` and copies twelve files to
`<WEBROOT>/calculators/backtest`. A brief unavailable route is acceptable.
A copy or verification error restores the saved tree using ordinary moves;
backups follow the [retention rule](#deployment-backup-retention). Recovery
commands are in the project guide. Existing attributes, including `com.apple.macl`, are not admission
failures and shared ancestor permissions are not changed.

`MARKET_ATLAS_DATA_HOME` defaults to `~/.cache/market-atlas`;
`UTILITIES_WEBROOT_DIR` defaults to `~/webroot`. Live deployment requires
explicit authorization. The source port is implemented; repository updates do
not update an installed copy. Deploy never runs setup/compiler/dependency
installation or reloads the webserver.

The canonical installed URL is
`http://127.0.0.1:7711/calculators/backtest/index.html`. The folder route may
remain a file browser. Installed acceptance checks all original browser scenarios
and compares served HTML/scripts/notice/CSV with source/selected pair bytes.

The [read-only helper](../tools/check_static_deployments.mjs) compares the ten
installed code and notice files with source from the fleet's validated Git
inventory. Market data is not redistributable and never enters the repository,
so the helper checks the installed `market-data.js`/`market-data.csv` pair only
for presence (regular, non-empty files) and never reads the external dataset.
A missing deployment, missing or empty data, extra or missing files and changed
code fail with a named reason. It does not acquire, build, repair or write
state; agents never run data acquisition (see the project guide). The
[isolated tests](../tools/tests/check_static_deployments.test.mjs) use invented
history. No release manifests, receipts, parser or metadata restoration
framework is required for this single-owner localhost deployment.

### Deployment backup retention

After a successful forward deployment and cleanup, the deployers keep the
newest two eligible backup directories per tool, by directory modification
time descending and name descending for ties. Failed, unchanged, dry-run and
rollback operations do not prune. Pruning failures warn without changing the
successful deployment result. Save any backup needed longer elsewhere.

## Calculator page direct-copy deployments

Two standalone pages under `Calculation tools/` are direct copies into
`<WEBROOT>/calculators/`, served by the existing Docker webserver:

| Source | Installer | Installed URL | Backup namespace |
| --- | --- | --- | --- |
| `ai-model-timeline.html` | `tools/deploy_ai_model_timeline.mjs` | `http://127.0.0.1:7711/calculators/ai-model-timeline.html` | `ai-model-timeline` |
| `drawdown.html` | `tools/deploy_drawdown.mjs` | `http://127.0.0.1:7711/calculators/drawdown.html` | `drawdown` |

Both entry scripts call the shared `tools/calculator_page_deployment.mjs`.
`UTILITIES_WEBROOT_DIR` defaults to `~/webroot`; no proxy or container restart
is needed. Repository updates do not update these installed copies; deploy
from merged `main`.

After validating the page with its project's full suite, stage its source so
that the index contains the reviewed bytes. From the repository root, for
example for drawdown:

```sh
node tools/deploy_drawdown.mjs --dry-run
node tools/deploy_drawdown.mjs
zsh tools/check_local_deployments.zsh
```

Both installers and the audit honor `UTILITIES_WEBROOT_DIR`. The installers also
accept `--webroot "<WEBROOT>"` and `--repo "<REPOSITORY>"`. Each requires a
regular stage-zero tracked HTML source with working bytes equal to the index.
It refuses symlinked destinations, user-created directory links and repository
webroots, while accepting macOS's standard `/var` and `/tmp` aliases.
Dry-run performs validation without creating directories or backups. When the
installed bytes and mode already match source, the installer reports that and
writes nothing.

Each installer changes only its one HTML file. When replacing it, the prior
file is saved at `~/.utilities-deploy-backups/<namespace>/copy-*/<page>.html`
in a new `0700` directory, with backup file mode `0600`. It verifies a temporary
candidate's bytes and complete permission mode before atomically renaming it
over the destination. Copy, validation or activation failure leaves the prior
installed file in place and removes the candidate. Backups follow the
[retention rule](#deployment-backup-retention).
To roll back, copy the chosen backup over the installed file and restore its
desired serving mode (normally `0644`); audit will flag that older copy until
source and deployment match again. Neighboring calculators and local state are
preserved. Drawdown backups made by hand before this installer existed use the
same `drawdown/copy-*` layout.

The fleet audit checks index membership, source and destination regular-file
types, installed bytes and complete permission modes. It does not update the
page or reload services. After live deployment, separately compare the HTTP
response bytes with the reviewed source and exercise the page in a browser.
Run the isolated installer lifecycle tests with:

```sh
node --test tools/tests/deploy_calculator_pages.test.mjs
```

## Native Colophon deployment

`~/Library/Scripts/colophon` is a generated macOS executable built from
the canonical [Colophon C17 project](../colophon/README.md) at `colophon/`.
The Python application is retired; Git history retains its source. The fleet
audit checks the generated executable and its receipt rather than comparing
a launcher to the installed command. Runtime defaults read Codex (`~/.codex`),
Claude Code (`~/.claude`), OpenCode (`~/.local/share/opencode`) and Antigravity
(`~/.gemini` app/CLI/IDE conversation databases) data and keep
state in `~/.colophon`; deployment does not read or migrate session data or
editable runtime state.

Validate with the native project's full suite and the root deployment suites,
then stage the reviewed native build inputs. From the repository root:

```sh
node tools/deploy_colophon.mjs --dry-run
node tools/deploy_colophon.mjs
node tools/deploy_colophon.mjs --audit
zsh tools/check_local_deployments.zsh
```

The installer requires regular stage-zero tracked build inputs whose working
bytes and modes match the index. It builds an explicitly selected release in
fresh temporary space using local sources/assets, Apple clang and installed
SQLite; no venv, dependency installation or existing build binary is copied.
The scripts destination defaults to `~/Library/Scripts`, with
`UTILITIES_SCRIPTS_DIR` or `--scripts-dir DIR` overrides. `--repo DIR` selects
another checkout. Destinations inside the repository or through user-created
directory links are refused. Dry-run validates without building or writing.

Before replacement, the previous command and optional native receipt are saved
under `~/.utilities-deploy-backups/colophon-native/copy-*/`, with directory mode
0700 and backup files 0600. Backup metadata records prior bytes and command mode.
The candidate is checked as a native executable, atomically installed at mode
0755, and exercised directly with `--version` and `--help`. If activation or
receipt publication fails, the old command and receipt are restored. Backups are
retained; no other commands or runtime state are changed.

The private mode-0600 `~/Library/Scripts/.colophon-native.json` receipt binds the
installed binary digest/mode to a fingerprint of all admitted tracked native
build inputs. The read-only audit uses the fleet's existing validated index
snapshot, checks current source and installed bytes/modes against that receipt,
and never rebuilds or executes the installed command. It verifies consistency,
not reproducibility across compiler/SDK upgrades or cryptographic authenticity.

The fingerprint includes repository-relative input paths. Moving source from
the former `colophon-native/` folder to `colophon/` intentionally makes a
pre-cutover receipt fail the current source audit, even when input bytes are
unchanged. After full source validation, a separately authorized redeployment
through `deploy_colophon.mjs` builds from the reviewed canonical inputs and
publishes a fresh receipt. A repository update alone does not deploy it.
Never edit the old receipt to suppress drift.

The schema-1 `.colophon-native.json` filename and
`~/.utilities-deploy-backups/colophon-native/` namespace are retained private
state compatibility exceptions, not alternate source locations. Existing
receipts and backups remain usable for rollback; no state is renamed,
migrated, deleted or automatically pruned.

Roll back with the exact backup directory printed by the installer:

```sh
node tools/deploy_colophon.mjs --rollback /path/to/colophon-native/copy-backup
```

Rollback validates the complete backup before replacement and backs up the
current command first. It restores the prior command mode and receipt, including
a previous Python launcher without a native receipt. The audit reports drift
until the native version matching current source is deployed again.

Installer lifecycle and fleet integration fixtures use invented data:

```sh
node --test tools/tests/deploy_storage_monitor.test.mjs tools/tests/deploy_colophon.test.mjs tools/tests/deploy_brew_version.test.mjs tools/tests/deploy_anker_charge_monitor.test.mjs tools/tests/deploy_telltale.test.mjs tools/tests/deploy_calculator_pages.test.mjs
zsh tools/tests/test_check_local_deployments.zsh
```

## Anker Charge Monitor app deployment

The app-only generated artifact installs at
`/Applications/Anker Charge Monitor.app`; there is no installed CLI command.
Use Node.js, macOS 27 and Swift 6 with the macOS 27 SDK. Validate the complete
[project suite](../anker_charge_monitor/README.md) and affected root/Market Atlas
suites, review and merge, then deploy from validated merged main:

```sh
node tools/deploy_anker_charge_monitor.mjs --dry-run
node tools/deploy_anker_charge_monitor.mjs
node tools/deploy_anker_charge_monitor.mjs --audit
zsh tools/check_local_deployments.zsh
node tools/deploy_anker_charge_monitor.mjs --rollback /private/path/to/copy-backup
```

`make -C anker_charge_monitor install` and `deploy` invoke that same root CLI.
Use `SIGN_IDENTITY='Exact Identity Name'` (or a complete 40-hex fingerprint) to
override the default **CodexBar Local** selection. A missing or ambiguous
identity fails before compilation or deployment mutation, with no ad-hoc
fallback. Activation checks use strict codesign verification with the literal
`=identifier "local.utilities.prime-monitor" and certificate leaf = H"FINGERPRINT"`
requirement, along with actual plist name/display name/version/build, executable,
bundle ID, agent/minimum-OS fields and the executable's macOS 27 minimum runtime.
Ownership checks permit an older installed version from that same identity.

`--repo DIR`, `--scripts-dir DIR`, `--apps-dir DIR`, `--rebuild` and audit-only
`--source-inventory FILE` follow the native installer conventions. Scripts/apps
overrides also honor `UTILITIES_SCRIPTS_DIR`/`UTILITIES_APPS_DIR`. The apps default
is always `/Applications`, with no home-directory fallback. Explicit test
destinations stay outside the checkout; symlink ancestors are rejected.

The admitted inventory is tracked Package.swift, Makefile and every regular
Sources, Resources, Tests and tools file under `anker_charge_monitor/`, plus
`tools/deploy_anker_charge_monitor.mjs`, `tools/deployment_files.mjs` and the
imported generic app hash owner `tools/deploy_brew_version.mjs`. It includes the
actual release/installer/signing scripts. Working bytes and modes must equal
the stage-zero index; missing, linked, sparse or unmerged inputs fail closed.
Only those captured bytes are copied to private scratch for `make release`, which
leaves nothing in either temp dir (see
[Native Brew Version deployment](#native-brew-version-deployment)). Source
identity is checked again after building. No runtime configuration,
vault, session cache or secret-pattern contents are build inputs.

`~/Library/Scripts/.anker-charge-monitor-native.json` is private mode 0600 and
has exactly `{schema: 1, sourceHash, version, appTreeHash, signingIdentity}`.
The generic app hash covers all sorted entry names/types, full permission bits
and content digests, including the bundle root and empty directories. Audit
compares that provenance, metadata and artifact identity without building,
signing, executing the app, querying credentials or writing source/deployment.
It prints exactly `OK: anker-charge-monitor native deployment`. Dry-run validates
the admitted inputs without writing or querying signing identities.

The project shell installer remains the one owner of app activation: it copies
into a private stage on the apps volume, validates, displaces the previous
whole bundle and renames the candidate. The root CLI adds private independent
backups and receipt publication/recovery. Backups under
`~/.utilities-deploy-backups/anker-charge-monitor/copy-*` retain the prior app
under its original name, receipt bytes/mode and checked metadata. Containers
are 0700, receipt/metadata files 0600, and app modes are retained. Saved app
hashes and receipt bytes are re-read before activation. Readers of the previous
executable remain valid; installers never quit or launch the app.

Activation, receipt publication, rollback and cleanup failures return nonzero
and restore the previous app/receipt, including an initially absent app.
Rollback validates the saved hashes before backing up and displacing the
current release. Both backup generations remain independent; later successful
forward deployments apply the [retention rule](#deployment-backup-retention).
Errors report the retained recovery location, and include restoration failures
if recovery cannot finish. A rollback to an older source intentionally causes
the current-source audit to report drift until that source is deployed again.

The same-directory legacy `Prime Monitor.app` migration retains ownership and
signature checks; having both names present fails as ambiguous. A copy under
`~/Applications` is a separate one-time operator retirement: privately back it
up and remove it only after the new canonical installation is verified. The
installer does not scan other users' applications. Internal product/executable,
bundle ID and `~/Library/Application Support/Prime Monitor/` state stay intact.
Quit/reopen when convenient to use the installed 0.1.1 release (build 2); restart
clears the process-memory credential/session cache and normal authorization
may be requested. Actual GUI behavior, 1Password/TCC approvals and native launch
at login registration for the `/Applications` copy require operator checks.
Synthetic tests establish none of those live outcomes. The separately authorized
`make -C anker_charge_monitor live-check` contacts the real vault and service;
its output belongs only in private storage.

## Telltale app deployment

The app-only generated artifact installs at `/Applications/Telltale.app`; there
is no installed CLI command. `tools/deploy_telltale.mjs` is a port of the Anker
Charge Monitor deployer above, with the same flags, receipt, backup and recovery
rules and no legacy app name. Use Node.js, macOS 27 and Swift 6 with the
macOS 27 SDK. Validate the complete [project suite](../telltale/README.md) and
the Static deployment/fleet audit tooling suites, review and merge, then deploy
from validated merged main:

```sh
node tools/deploy_telltale.mjs --dry-run
node tools/deploy_telltale.mjs
node tools/deploy_telltale.mjs --audit
zsh tools/check_local_deployments.zsh
node tools/deploy_telltale.mjs --rollback /private/path/to/copy-backup
```

`make -C telltale install` and `deploy` invoke that same root CLI. Use
`SIGN_IDENTITY='Exact Identity Name'` (or a complete 40-hex fingerprint) to
override the default **CodexBar Local** selection. A missing or ambiguous
identity fails before compilation or deployment mutation, with no ad-hoc
fallback. Activation checks use strict codesign verification with the literal
`=identifier "local.utilities.telltale" and certificate leaf = H"FINGERPRINT"`
requirement, along with the actual plist name/display name/version/build,
executable `Telltale`, bundle ID, `LSUIElement`/`LSMinimumSystemVersion` 27.0
fields and the executable's macOS 27 minimum runtime. Ownership checks permit an
older installed version from that same identity.

`--repo DIR`, `--scripts-dir DIR`, `--apps-dir DIR`, `--rebuild` and audit-only
`--source-inventory FILE` follow the native installer conventions, as do the
`UTILITIES_SCRIPTS_DIR`/`UTILITIES_APPS_DIR` overrides. The apps default is
always `/Applications`. Explicit test destinations stay outside the checkout;
symlink ancestors are rejected.

The admitted inventory is tracked Package.swift, Makefile and every regular
Sources, Resources, Tests and tools file under `telltale/`, plus
`tools/deploy_telltale.mjs`, `tools/deployment_files.mjs` and
`tools/deploy_brew_version.mjs` (the generic app hash). Package.swift, the
Makefile, `Resources/Info.plist`, the two Barlow Semi Condensed fonts and
`Resources/Fonts/OFL.txt` (the release recipe copies all three into
`Contents/Resources/Fonts`), `tools/install.sh`,
`tools/resolve_signing_identity.sh`, a Sources file and the three root tools are
required. README and `docs/` are not inputs, and neither are the Codex logs, the
database or the collector's job plist. Working bytes and modes must equal the
stage-zero index. Only those captured bytes are copied to private scratch for
`make release`, which leaves nothing in either temp dir (see
[Native Brew Version deployment](#native-brew-version-deployment)), and source
identity is checked again after building.

`~/Library/Scripts/.telltale-native.json` is private mode 0600 and has exactly
`{schema: 1, sourceHash, version, appTreeHash, signingIdentity}`. Audit compares
that provenance, metadata and artifact identity without building, signing,
executing the app, querying credentials or writing source or deployment state,
and prints exactly
`OK: telltale native deployment`. Dry-run validates the admitted inputs without
writing or querying signing identities.

`telltale/tools/install.sh` remains the one owner of app activation: it copies
into a private stage on the apps volume, validates, displaces the previous whole
bundle and renames the candidate. The root CLI adds private independent backups
under `~/.utilities-deploy-backups/telltale/copy-*` (0700 containers, 0600
receipt/metadata, app modes retained) and receipt publication and recovery.
Activation, receipt publication, rollback and cleanup failures return nonzero
and restore the previous app and receipt, including an initially absent app.
Readers of the previous executable remain valid; the deployer never quits or
launches the app.

The deployer never runs `launchctl` and never writes `~/Library/LaunchAgents`,
`~/Library/Application Support/Telltale` or `~/Library/Logs/Telltale`. The
installed app owns its collector job, `local.utilities.telltale.collector`: when
the copy in `/Applications` launches with the collector on and no job plist, it
writes the plist and loads the job (spec section 9.3). The job runs the
installed executable's path, so a replaced bundle keeps the same job; quit and
reopen Telltale when convenient to run the new release. Then do the
[post-deployment check](../telltale/docs/telltale_design_spec.md#13-build-test-and-release):
if the collector is on, the dashboard's Collector view must show Installed lit
green, and Repair must not be offered (if it is, press it to point the job at
the installed executable). The README's installed-release checks (launch at
login, collector and Settings) are separate, owner-run native gates; synthetic
tests establish none of those live outcomes.

## Native Brew Version deployment

Brew Version is a generated native release: the signed command installs at
`~/Library/Scripts/brew-version` and the signed bundle at
`~/Applications/Brew Version.app`. Node.js, macOS 27 and Swift 6 with the macOS 27
SDK from Xcode or Command Line Tools are required; see
[project requirements](../brew_version/README.md#requirements).
Deploy reviewed source from merged main after the native acceptance gates have
been completed and live deployment has been authorized:

```sh
node tools/deploy_brew_version.mjs --dry-run
node tools/deploy_brew_version.mjs
node tools/deploy_brew_version.mjs --audit
zsh tools/check_local_deployments.zsh
node tools/deploy_brew_version.mjs --rollback /path/to/brew-version/copy-backup
```

`--repo DIR`, `--scripts-dir DIR` and `--apps-dir DIR` select explicit
paths. Defaults honor `UTILITIES_SCRIPTS_DIR` and `UTILITIES_APPS_DIR`, then
use the paths above. Fleet audit passes no apps override and honors that same
apps environment/default. Destinations inside the repository or through
symlinked ancestors are refused. `--source-inventory FILE` is audit-only and
accepts the fleet's validated NUL-delimited index snapshot.

The maintained [installer](../tools/deploy_brew_version.mjs) defines
`buildInput` and `sourceInventory`: Package.swift, Makefile and all regular
tracked Resources, Sources and Tests files supply the release. Deploy refuses
unstaged input bytes and builds an isolated admitted snapshot with
`make -C <scratch>/brew_version release` (900-second limit). The
Swift toolchain check and `make release` get a `TMPDIR` inside that scratch, so
SwiftPM's lock files and `TemporaryDirectory.*` folders go with it. After the
build, passing or failing, `makeRelease` removes each new `TemporaryDirectory.*`
in the Darwin user temp dir (`getconf DARWIN_USER_TEMP_DIR`) that holds only an
empty `.keep-directory`, the marker each compile leaves there whatever `TMPDIR`
says, and names any other new one on stderr. The Anker and Telltale deployers
build through the same `makeRelease`. The expected
version comes from admitted Info.plist bytes; CLI help comes from the admitted
golden fixture. Built and installed command diagnostics check exact version
and help stdout, successful exit and empty stderr for `--version`, `--help`
and `-h`; bundle diagnostics check the release plist contract and
strict signature verification. The installer never launches the app.

The mode-0600 `<scripts>/.brew-version-native.json` receipt has exactly
`{schema: 1, sourceHash, version, commandHash, commandMode, appTreeHash}`.
The command mode is 0755. `appTreeHash` covers sorted relative paths, entry
types, full permission bits and content digests, including bundle root and
directories; links and special files are refused. Read-only audit compares
source and installed identity without executing or compiling either product;
it prints `OK: brew-version native deployment` on success. A current deploy
prints `already current; nothing changed`. Missing or drifted artifacts,
changed inputs or `--rebuild` rebuild both release products together.
Dry-run validates inputs and writes nothing.

The app is copied into a `.brew-version-stage-*` directory inside the apps
directory, checked, then renamed into place after saving the prior app. The old
live app moves into that same staging directory, so an apps directory on a
different volume from the backup home remains supported.
Backups under `~/.utilities-deploy-backups/brew-version/copy-*` retain the
previous command, receipt and app. Containers are 0700; saved command, receipt
and metadata are 0600 with original modes and digests recorded. The saved
app tree retains its original modes. Every copied payload is re-read and hashed
against its captured source identity, including the complete app tree and backup
metadata, before any live artifact changes. The installer prints `Recovery backup:`
before activation or rollback starts. These
private saved modes are an exception to the generic backup-file normalization
rule. Activation failure restores the prior command, app and receipt, including
an absent prior app. Rollback validates the backup before saving the displaced
release and restores prior bytes and modes. If activation and restoration both
fail, the error includes both failures and the retained backup path. Stop and
recover from that backup after resolving the reported filesystem problem; do
not discard it or repeatedly deploy over the unresolved state. Later successful
forward deployments apply the [retention rule](#deployment-backup-retention).

Cleanup attempts cover every owned staging and build directory even if another
cleanup fails. Reported errors retain the original activation/restoration
evidence, the recovery backup path and each failed cleanup path. If activation
completed and only cleanup failed, the selected release stays active; the
installer returns status 1 and explicitly reports completion with cleanup
failures. This applies to rollback too. Inspect the reported release and paths
before retrying; a cleanup failure does not mean the prior release was restored.

Deploy, audit and rollback preserve `~/Library/Application Support/Brew Version/`
and `~/Library/Caches/Brew Version/`. A running app is detected with
`pgrep -f "Brew Version.app/Contents/MacOS/BrewVersion"` (test override:
`BREW_VERSION_DEPLOY_TEST_ONLY_PGREP`, reserved for isolated lifecycle tests).
It is never terminated. After actual bundle replacement, deployment prints
`Quit and reopen Brew Version to use VERSION.` when running. Rollback of an app
prints the corresponding restored-release notice; an already-current deployment
prints no relaunch notice.

The lifecycle contract is exercised by
[installer tests](../tools/tests/deploy_brew_version.test.mjs), including
`assertActiveDeployment`'s independent bytes/type/full-mode snapshots,
activation failure at command/app/receipt boundaries and rollback. The
[fleet tests](../tools/tests/test_check_local_deployments.zsh)'s
`test_native_brew_version_deployment` owns source, app and receipt drift cases.

## Storage Monitor deployment

Storage Monitor installs a Python launcher and its native macOS walker as a
single deployment in `~/Library/Scripts`. The application never compiles the
walker at runtime. After validating and staging the reviewed launcher and native
build inputs, run from the repository root:

```sh
node tools/deploy_storage_monitor.mjs --dry-run
node tools/deploy_storage_monitor.mjs
node tools/deploy_storage_monitor.mjs --audit
zsh tools/check_local_deployments.zsh
```

The installer needs Node.js. Building requires macOS, `make`, and Apple clang
from the Xcode Command Line Tools (`xcode-select --install`). It builds from
regular stage-zero tracked inputs whose bytes and modes match the index, in
fresh temporary space. `--repo DIR` selects another checkout; the destination
defaults to `~/Library/Scripts`, with `UTILITIES_SCRIPTS_DIR` or
`--scripts-dir DIR` overrides. Destinations inside the repository or through
user-created directory links are refused. Dry-run reports required work without
building or writing.

The walker rebuilds when its receipt is missing or invalid, native inputs
change, the binary is missing or has drifted, or its version/protocol check
fails. Launcher-only changes update the launcher without rebuilding a current
walker. Use `--rebuild` to force a rebuild, including after a compiler or SDK
upgrade: the receipt does not track compiler versions.

The mode-0600 `.storage_monitor.json` receipt binds native source, launcher and
walker digests to installed modes, walker version and protocol. The read-only
fleet audit supplies its validated Git-index snapshot and checks source and
installed artifacts against this receipt without compiling or executing the
installed commands. It checks consistency rather than reproducibility across
toolchain changes or cryptographic authenticity.

Before replacement, the previous launcher, walker and receipt are saved under
`~/.utilities-deploy-backups/storage_monitor/copy-*/`, in a mode-0700 directory
with mode-0600 backup files and metadata recording original modes and digests.
Activation failure restores the previous files. Backups follow the
[retention rule](#deployment-backup-retention). Roll back
using the exact backup directory printed by the installer:

```sh
node tools/deploy_storage_monitor.mjs --rollback /path/to/storage_monitor/copy-backup
```

Rollback validates the backup and saves the current deployment before restoring
the prior bytes, modes and receipt. Runtime state under `~/.storage_monitor/`
is preserved. Migrating from the former direct-copy launcher needs an explicit
deployment to install the walker and publish its receipt; a repository update
alone leaves the fleet audit reporting deployment drift. Rollback can restore
that original direct copy without a walker or receipt, in which case the audit
continues reporting drift until the reviewed native deployment is installed.

Synthetic installer and fleet fixtures run with:

```sh
node --test tools/tests/deploy_storage_monitor.test.mjs tools/tests/deploy_colophon.test.mjs tools/tests/deploy_brew_version.test.mjs tools/tests/deploy_calculator_pages.test.mjs
zsh tools/tests/test_check_local_deployments.zsh
```

## `~/Library/Scripts`

These files are direct copies of tracked source and should remain byte-for-byte identical:

- `de-abacus.py` <- `abacus usage/de-abacus.py`
- `div_conv` <- `div_conv/div_conv`
- `dloc` <- `dloc/dloc`
- `docker-disk-compact.zsh` <- `docker/docker-disk-compact/docker-disk-compact.zsh`
- `editdb` <- `editdb/editdb`
- `etf_montecarlo` <- `etf_montecarlo/etf_montecarlo`
- `expense_dock` <- `expense_dock/expense_dock`
- `harscope` <- `harscope/harscope`
- `jtree` <- `jtree/jtree`
- `launchmaster` <- `launchmaster/launchmaster`
- `media-dater` <- `media-dater/media-dater`
- `moneydance_rotate_backups.sh` <- `moneydance backup rotation/moneydance_rotate_backups.sh`
- `router_log_analyze.py` <- `router-log-analyzer/router_log_analyze.py`
- `routerview` <- `routerview/routerview`
- `trim_last` <- `trim_last/trim_last`
- `usage-monthly-csv` <- `usage-monthly-csv/usage-monthly-csv`
- `worktree` <- `worktree-helper/worktree`

`model-sentinel` is intentionally different: it is a generated zipapp. Rebuild
it with `model_sentinel/install_standalone.sh`. The audit derives its exact
expected `__main__.py`, `model_sentinel/*.py`, and
`model_sentinel/browse/**` inventory from the same validated Git-index snapshot
used for other deployments, then validates and streams only those entries. It
also validates the generated `model_sentinel/_packaged_build.py` provenance
file, including its bounded size, exact structure, and source hash. The
installer builds through uv (`uv run --no-python-downloads --script
model_sentinel/build_standalone.py`), so it needs uv on `PATH` but no project
venv or particular `python3`; run it as is.

`time_machine_snapshot_monitor` is a maintained multi-file copy under
`~/Library/Scripts/time_machine_snapshot_monitor`. Deploy or update it from the
repository with:

```bash
./time_machine_snapshot_monitor/install.sh
```

The installer copies only the six documented project files, verifies staged
bytes before activation, backs up a changed prior source tree under
`~/.utilities-deploy-backups/`, refreshes the
`~/Library/Scripts/tm-snapshot-monitor` command symlink, and installs the
hourly user LaunchAgent. Successful updates apply the
[retention rule](#deployment-backup-retention). Mutable counters and bounded logs remain under
`~/Library/Application Support/TimeMachineSnapshotMonitor`, outside both source
trees. The read-only deployment audit compares the installed project tree
byte-for-byte and mode-for-mode and verifies the stable command link target.
Use the project README for setup, repair, and removal behavior.

## Top-level home project copies

The maintained runtime/source copies are:

- `~/apple-health-extract`
- `~/docker`
- `~/mem_snapshots`
- `~/mls-tracker`
- `~/tax2`
- `~/transcription`
- `~/vid-compiler`
- `~/video-scenes`

`~/docs` is an unrelated name collision. Do not synchronize the repository's `docs/` directory into it.
Transcription is a maintained source copy at `~/transcription`; run its
`transcription` launcher in place.

Copy tracked files without deleting local-only files. The following pattern is safe for one project after a rollback directory has been created:

```zsh
repo="$HOME/source/utilities-public"
project="tax2"
backup="$HOME/.utilities-deploy-backups/manual-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup"
chmod 700 "$backup"

git -C "$repo" ls-files -z -- "$project" | while IFS= read -r -d '' relative; do
  source_file="$repo/$relative"
  destination="$HOME/$relative"
  relative_destination="${destination#$HOME/}"
  if [[ -e "$destination" ]] && ! cmp -s "$source_file" "$destination"; then
    mkdir -p "$backup/${relative_destination:h}"
    cp -p "$destination" "$backup/$relative_destination"
  fi
  mkdir -p "${destination:h}"
  cp -p "$source_file" "$destination"
done
```

Do not treat local-only files as drift. Important examples include:

- Apple Health exports.
- Tax2 hand-edited `~/.tax2/config.yaml` and private built page `~/.tax2/tax2.html` (or the corresponding `TAX2_HOME` paths).
- Transcription's legacy counters in `~/transcription/session_backup.json` and
  `~/transcription/transcription_odometer.txt`; its current counters, lock and
  preserved unreadable files under `~/.transcription/` or `TRANSCRIPTION_HOME`,
  and any paths selected by `CUMULATIVE_JSON_PATH` or `LIFETIME_TXT_PATH`.
- Docker databases, exports, logs, extension configuration, API credentials, and Compose `.env` files.
- Project venvs, caches, and `.DS_Store` files.

Some project tests use the repository's shared `tools.testkit` helper. A top-level deployment remains runtime-standalone, but its copied test files need the canonical repository root on `PYTHONPATH`. For example, with a copied Tax2 launcher, tests and test requirements, use an isolated environment from the deployed launcher metadata. Start in private scratch so interpreter discovery cannot inherit a parent project environment:

```bash
repo="$HOME/source/utilities-public"
deployed="$HOME/tax2"
scratch=$(mktemp -d "${TMPDIR:-/tmp}/deployed-tests.XXXXXX")
(
  cd "$scratch" || exit 1
  clean_path=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
  interpreter=$(env -i HOME="$HOME" PATH="$clean_path" TMPDIR="$scratch" UV_PYTHON_DOWNLOADS=never \
    uv python find --no-python-downloads --no-cache --script "$deployed/tax2") || exit 1
  case "$interpreter" in /opt/homebrew/*) ;; *) echo "Unapproved interpreter: $interpreter" >&2; exit 1 ;; esac
  cd "$deployed" || exit 1
  probe=$(env -i HOME="$HOME" PATH="$clean_path" TMPDIR="$scratch" UV_PYTHON_DOWNLOADS=never PYTHONPATH="$repo" \
    uv run --no-project --isolated --no-python-downloads --python "$interpreter" \
    --with-requirements "$deployed/tax2" --with-requirements "$deployed/requirements-dev.txt" \
    python -c 'import sys; print(sys._base_executable); print(sys.version.split()[0])') || exit 1
  actual=${probe%%$'\n'*}
  [ "$actual" -ef "$interpreter" ] || { echo "Interpreter mismatch: $probe" >&2; exit 1; }
  printf 'Actual interpreter and version:\n%s\n' "$probe"
  env -i HOME="$HOME" PATH="$clean_path" TMPDIR="$scratch" UV_PYTHON_DOWNLOADS=never PYTHONPATH="$repo" \
    uv run --no-project --isolated --no-python-downloads --python "$interpreter" \
    --with-requirements "$deployed/tax2" --with-requirements "$deployed/requirements-dev.txt" \
    python -m pytest -q
)
status=$?
rm -r -- "$scratch"
test "$status" -eq 0
```

Use absolute canonical paths for both variables. `--no-cache` keeps discovery
from returning the launcher's cached virtual environment after a previous run.
The clean environment removes
inherited virtual environment and Python import settings; the only deliberate
import path is the canonical repository root. The shared runner itself does not
accept an inherited `PYTHONPATH`.

The same `PYTHONPATH` applies to copied tests in `~/mls-tracker` and
`~/transcription`. For Transcription, use its README's Self-test command from
the copied project directory with `--script transcription`.

## Docker-specific state

Private/runtime files must remain outside Git:

- Webserver: `~/docker/webserver/.env` (`0600`).
- LLM collector credentials: `~/.config/llm_collector/secret.env` (`0600`).
- LLM collector state: `~/.local/state/llm_collector/`.
- LLM Proxy generated provider configs, bookmarklet, and update script: `~/docker/llm_proxy/output/`. Only `output/README.md` is tracked; container-generated files are local runtime artifacts.
- n8n configuration: `~/docker/n8n-poc/.env` (`0600`).
- n8n state: `~/.local/state/n8n-poc/` (`0700` directories, `0600` files).
- Actual Budget data: `~/docker/actual-data/server-files/` and `user-files/`.

The n8n encryption key must remain stable for an existing database. Never replace it with the example value or rotate it casually; doing so can make stored credentials unreadable.

Before Docker maintenance:

```bash
docker compose ls --all
docker ps
```

Validate Compose configuration before starting. Rebuild/start only the projects intended to run, probe their health/UI, and return projects that were originally stopped to the stopped state. The local financial and utility web services should publish only on `127.0.0.1`.

`docker/propagate-updates.zsh deploy` applies these rules to `~/docker`: it copies only committed tracked files, backs up replaced files under `~/.utilities-deploy-backups/docker-<timestamp>/`, reruns `update.sh` only for stacks that were running, and verifies they are running again. Its `refresh` phase updates and audits the Docker lockfiles beforehand. See [docker/README.md](../docker/README.md#propagating-dependency-updates).

After a successful deploy that creates a backup, it keeps the two newest eligible
Docker backup directories by modification time, with descending name as the
tie-break. Failed, unchanged and dry runs leave backups untouched.

## Rollback

Deployment snapshots live under `~/.utilities-deploy-backups/`. They may contain old operational source or private local configuration and must never be copied into this public repository. Keep the directory at `0700` and backup files at `0600`.

Market Atlas moves the entire prior app into a new private backup container,
without normalizing the saved tree or promising exact metadata restoration.
Ordinary move-based recovery preserves the saved contents, including legacy
symlinks.
