# Standalone Build Provenance and Freshness Design

Status: approved architecture; implementation pending written-spec review.

## Problem

Model Sentinel's scheduled LaunchAgent intentionally runs the standalone
zipapp at `~/Library/Scripts/model-sentinel`. The standalone is a copy of the
package at install time, so updating the repository does not update the
scheduled executable. The August 8 pricing-order fix was correct in the
repository, but the August 15 report was produced by a July 26 zipapp that
still sorted card rows by price impact.

The runtime currently exposes only the static package version `0.1.0`. It does
not identify the source revision, packaged contents, build time, executable
path, or whether the installed artifact matches the current checkout. This
made the stale deployment silent.

## Goals

1. Preserve a standalone runtime with no checkout or network dependency.
2. Give every packaged artifact an immutable identity derived from its exact
   Python contents, plus useful Git and build-time context.
3. Make that identity visible through `--version`, `healthcheck`, and every
   scan log before provider work begins.
4. Provide a read-only installer check that detects whether the configured
   standalone target matches the current checkout.
5. Keep installation atomic and refuse to replace a working target with an
   artifact that cannot execute its own version command.
6. Rebuild the installed standalone after implementation and verify that it
   contains both the provenance feature and the pricing-order fix.

## Non-goals

- No automatic update, network lookup, or dependency on a repository checkout
  at scheduled-run time.
- No comparison against remote branches or release services.
- No change to report ordering, provider fetching, snapshot storage, or
  baseline behavior.
- No dynamic version bump. The existing package version remains the product
  version; build provenance identifies a particular artifact.

## Chosen Approach

Keep the existing zipapp and make its build/deploy boundary explicit and
verifiable. This is preferred over pointing launchd at the checkout because
standalone independence is a requirement. It is also preferred over a
self-updater because Model Sentinel has no release channel, a self-updater
would add network and trust policy, and a failed update could disrupt the
scheduled monitor.

Two alternatives were rejected:

- **Run from the checkout:** eliminates copy drift, but makes the scheduled
  job depend on the repository path and working tree.
- **Self-update before each scan:** could discover new code automatically, but
  creates a networked mutation path and requires release verification,
  rollback, and failure policy well beyond this bug.

## Build Metadata

Add a small `model_sentinel/build_info.py` module containing source-checkout
defaults. Runtime helpers in that module expose a stable display string and
the current entrypoint path. The standalone installer replaces only the
staged copy of the metadata constants before creating the zipapp; it never
modifies the checkout.

Packaged metadata:

- `BUILD_KIND`: `standalone` for a zipapp and `source` in the checkout.
- `BUILD_REVISION`: the current 12-character Git revision when available,
  with a visible modified marker when tracked or untracked files under this
  project differ from that revision; otherwise `unknown`.
- `BUILD_SOURCE_HASH`: a SHA-256 digest over the staged Python files that will
  enter the artifact, excluding generated `build_info.py` to avoid a recursive
  hash. Paths are relative and sorted, making repeated builds of identical
  source produce the same content identity.
- `BUILD_TIME_UTC`: the UTC packaging timestamp. It is diagnostic metadata,
  not part of freshness equality.

The complete digest is stored in the artifact. Human output may show a short
prefix while the installer freshness comparison uses the complete value.
No username, repository path, environment value, credential, or runtime-home
state is embedded.

## CLI and Runtime Visibility

Add a top-level `--version` option that exits before configuration loading or
runtime-directory creation. It prints the product version, build kind, Git
revision, source hash, and build time. The default-`scan` argument normalizer
must leave `--version` at the top level rather than rewriting it as a scan
option.

`healthcheck` gains an informational `runtime_build` check containing the same
identity and the resolved command entrypoint. This check is always `ok`; it
reports what is running rather than claiming that a newer build does or does
not exist.

At the beginning of `run_scan`, after logging is configured but before
credential validation or provider access, log one structured human-readable
line containing the build identity and resolved entrypoint. Failures early in
a scheduled scan will therefore still identify the executing artifact.

Entrypoint reporting uses the resolved `sys.argv[0]`, which names the zipapp
for standalone execution and the launcher for checkout execution. It must not
report `sys.executable`, because that identifies Python rather than Model
Sentinel.

## Installer Interface and Safety

Retain the current install command:

```text
./install_standalone.sh [target-path]
```

Add a read-only mode:

```text
./install_standalone.sh --check [target-path]
```

Both modes stage the exact package inputs and compute the expected source
hash. `--check` invokes the target's configuration-free `--version` command
and returns:

- exit 0 with a clear `current` message when its complete source hash matches;
- exit 1 with an actionable `stale` message when the target is missing, cannot
  report build identity, or has a different source hash;
- exit 2 for invalid installer arguments.

Install mode builds to a temporary target in the destination directory, marks
it executable, and runs its `--version` command before the existing atomic
`mv`. A failed smoke check leaves any prior installation untouched. After the
move, the installer prints the installed identity and an explicit reminder to
run `--check` after repository updates.

The source hash contract must be emitted in a machine-readable fragment of
`--version` output, such as `source_sha256=<64 lowercase hex characters>`, so
the shell check performs exact matching without parsing presentation prose.

## Documentation and Operating Procedure

Update the README standalone section and launchd documentation to state:

1. the zipapp is a point-in-time copy;
2. rerun `install_standalone.sh` after repository updates;
3. use `install_standalone.sh --check` to verify freshness;
4. use the installed executable's `--version` and `healthcheck` when
   diagnosing scheduled behavior.

The deployment performed for this change will rebuild the existing
`~/Library/Scripts/model-sentinel` target atomically. Runtime configuration,
credentials, database contents, reports, and LaunchAgent scheduling are not
changed. Reloading launchd is unnecessary because the runner already resolves
that same target path on each invocation.

## Testing

Follow red-green TDD for each executable behavior:

- CLI tests pin configuration-free `--version` behavior and the required
  machine-readable fields.
- Build-info unit tests pin checkout defaults, formatting, path resolution,
  and full-versus-short hash handling.
- Healthcheck tests pin the informational runtime-build row in text and JSON
  without changing exit status.
- Scan tests pin that build identity is logged before the provider scan line,
  including a missing-credential path.
- A standalone installer integration test uses a temporary runtime home and
  target. It builds a real zipapp, invokes its `--version`, verifies `--check`
  succeeds, changes a conspicuously synthetic copied source input, and verifies
  `--check` reports stale without mutating the installed artifact.
- Existing pricing-order tests remain unchanged and must pass against the
  checkout. After installation, inspect the zipapp's `--version` and embedded
  reporting module, then run a configuration-free installed-artifact smoke
  test proving `Input`, cache, `Output` ordering from synthetic changes.

Per repository policy, run the complete pytest suite before deployment. After
deployment, rerun the installed artifact checks and `healthcheck`; do not run
another saved provider scan merely to validate packaging.

## Failure Handling and Security

- If Git metadata is unavailable, packaging continues with revision
  `unknown`; the content hash remains authoritative.
- If SHA-256 calculation, zipapp creation, or the temporary artifact's version
  command fails, installation aborts and preserves the existing target.
- `--check` never writes configuration, replaces the target, or contacts a
  provider.
- All tests and documentation use conspicuously synthetic paths, revisions,
  hashes, providers, and credentials.
- Staged and committed diffs receive the repository's mandatory sensitive-data
  review. Build metadata must never include absolute checkout paths or Git
  identity information.

## Acceptance Criteria

- The repository launcher and standalone zipapp both support `--version`
  without configuration or credentials.
- A packaged zipapp reports `build=standalone`, a full source SHA-256, Git
  revision context, and UTC build time.
- `healthcheck` and scan logs identify the running artifact and entrypoint.
- `install_standalone.sh --check` reliably distinguishes matching and stale
  targets and is read-only.
- A failed candidate-artifact smoke check cannot overwrite the existing
  standalone executable.
- The complete test suite passes.
- The rebuilt scheduled target contains the provider-defined pricing sorter,
  reports current build provenance, passes healthcheck, and does not require a
  LaunchAgent configuration change.
