# Local Deployment Synchronization

This repository is the canonical public source. Copies under `~/Library/Scripts` and top-level project directories under `~/` are deployment targets, not additional source repositories.

## Non-destructive rules

1. Validate repository source before deploying it.
2. Back up every destination file that will be replaced.
3. For direct copies and maintained source trees, copy only files tracked by Git. Never mirror a whole directory and never use `rsync --delete` against a live local project. Market Atlas is a narrow static-runtime exception: validated source and selected external local history supply exactly twelve copied runtime files. This does not authorize public data redistribution or copying its private inputs and recovery records into the repository.
4. Preserve ignored/local-only configuration, databases, exports, generated tables, logs, venvs, and runtime state.
5. After copying, compare the deployed artifact with its source and exercise the deployed command directly.
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

From the child project, prepare data/build and review the dry-run:

```sh
npm run setup:data
npm run build -- --offline
npm run deploy -- --dry-run --webroot "<WEBROOT>"
```

Build defaults to `<DATA_HOME>/site`. Deploy consumes that existing build,
compares it against source and selected data, then moves the exact prior app
tree into a timestamped private container under
`~/.utilities-deploy-backups/backtest/` and copies twelve files to
`<WEBROOT>/calculators/backtest`. A brief unavailable route is acceptable.
A copy or verification error restores the saved tree using ordinary moves;
backups are never automatically pruned. Recovery commands are in the project
guide. Existing attributes, including `com.apple.macl`, are not admission
failures and shared ancestor permissions are not changed.

`MARKET_ATLAS_DATA_HOME` defaults to `~/.cache/market-atlas`;
`UTILITIES_WEBROOT_DIR` defaults to `~/webroot`. Live deployment requires
its existing authorization. This port's live cutover follows upstream merge
and the branch completion workflow. Deploy never runs setup/compiler/dependency
installation or reloads the webserver.

The canonical installed URL is
`http://127.0.0.1:7711/calculators/backtest/index.html`. The folder route may
remain a file browser. Installed acceptance checks all original browser scenarios
and compares served HTML/scripts/notice/CSV with source/selected pair bytes.

The [read-only helper](../tools/check_static_deployments.mjs) compares the twelve
installed files with source from the fleet's validated Git inventory and the
selected external dataset. Extra files, missing inputs and changed bytes fail
as drift. It does not acquire, build, repair or write state. The
[isolated tests](../tools/tests/check_static_deployments.test.mjs) use invented
history. No release manifests, receipts, parser or metadata restoration
framework is required for this single-owner localhost deployment.

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
- `storage_monitor` <- `storage_monitor/storage_monitor`
- `trim_last` <- `trim_last/trim_last`
- `usage-monthly-csv` <- `usage-monthly-csv/usage-monthly-csv`
- `worktree` <- `worktree-helper/worktree`

`model-sentinel` is intentionally different: it is a generated zipapp. Rebuild
it with `model_sentinel/install_standalone.sh`. The audit derives its exact
expected `__main__.py`, `model_sentinel/*.py`, and
`model_sentinel/browse/**` inventory from the same validated Git-index snapshot
used for other deployments, then validates and streams only those entries. It
also validates the generated `model_sentinel/_packaged_build.py` provenance
file, including its bounded size, exact structure, and source hash. Run the
installer with a venv-provided `python3` on Homebrew-managed macOS.

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
hourly user LaunchAgent. Mutable counters and bounded logs remain under
`~/Library/Application Support/TimeMachineSnapshotMonitor`, outside both source
trees. The read-only deployment audit compares the installed project tree
byte-for-byte and mode-for-mode and verifies the stable command link target.
Use the project README for setup, repair, and removal behavior.

`fid_div_conv` and `van_div_conv` are retained local legacy launchers. They were intentionally excluded from the public repository because `div_conv` supersedes them and the old source historically mixed operational mappings with code. Do not copy them back into public source. Remove them only after deciding the legacy rollback path is no longer needed.

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

- Apple Health exports and its project venv.
- Tax2 generated CSV/Parquet tables and `~/.tax2/config.json`.
- Transcription counters and session backups.
- Docker databases, exports, logs, extension configuration, API credentials, and Compose `.env` files.
- Project venvs, caches, and `.DS_Store` files.

Some project tests use the repository's shared `tools.testkit` helper. A top-level deployment remains runtime-standalone, but its copied test files need the canonical repository root on `PYTHONPATH`:

```bash
cd "$HOME/tax2"
PYTHONPATH="$HOME/source/utilities-public" \
  uv run --with-requirements requirements-dev.txt python -m pytest -q
```

The same pattern applies to `~/mls-tracker`.

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

## Rollback

Deployment snapshots live under `~/.utilities-deploy-backups/`. They may contain old operational source or private local configuration and must never be copied into this public repository. Keep the directory at `0700` and backup files at `0600`.

Market Atlas moves the entire prior app into a new private backup container,
without normalizing the saved tree or promising exact metadata restoration.
Ordinary move-based recovery preserves the saved contents, including legacy
symlinks. Restoring a legacy tree also restores its old exposure profile.
