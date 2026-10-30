# Development and validation

Release prerequisites and commands are in the [README](../README.md).
The full standalone suite uses macOS `sandbox-exec`, ripgrep, the project's
own Python 3.14 virtual environment, the pinned pytest and Playwright packages
in [requirements-dev.txt](../requirements-dev.txt), and cached Playwright Chromium.
Release builds do not require those Python tools.

Create `.venv` only if absent, using an absolute Homebrew interpreter:

```sh
/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv .venv
.venv/bin/python -m pip install --no-index -r requirements-dev.txt
# Alternatively, reuse uv's available package cache without downloading:
uv pip install --offline --python .venv/bin/python -r requirements-dev.txt
```

Try an available offline wheel source/cache first; `--no-index` does not
discover arbitrary cached wheels automatically. If packages are unavailable,
obtain approval before `.venv/bin/python -m pip install -r requirements-dev.txt`.
Browser downloads likewise require approval before
`.venv/bin/python -m playwright install chromium`. Existing Chromium in
`~/Library/Caches/ms-playwright` is reused. Never borrow another project's
venv or recreate an existing one. The approved setup for this clean project
uses the pinned packages in [requirements-dev.txt](../requirements-dev.txt).

```sh
make test
make sanitize
make tsan
make check-assets
make check-sort
```

`make test` runs the stable-sort guard, twelve asset digests, all retained
C units, synthetic CLI/integration cases and Chromium cases.
`make sanitize` runs those same categories under ASan/UBSan;
`make tsan` covers all retained C units, including concurrency assertions.
Category targets are `make test-unit`, `make test-cli` and `make test-browser`.
These are standalone checks, not historical parity coverage or performance
evidence. Help describes these shipped checks; historical native parity/performance
tools and their private workflow are not included here.

## Antigravity evidence and acceptance

The [public schema fixture](../tests/fixtures/antigravity/README.md) records
the producing language-server hashes and qualified descriptor provenance.
[Token rules](token_rules.md#antigravity-accounting-and-oracle-provenance-050)
record synthetic native ccusage 20.0.42 probes, binary hash and accounting
adaptations. The proposed [ccusage v20.0.42 Rust source](https://github.com/ccusage/ccusage/tree/v20.0.42/rust/adapters/antigravity)
was not independently located or verified; those probes are behavioral
evidence, not source verification. Pricing normalization adapts the pinned
[CodexBar Antigravity reader](https://github.com/steipete/CodexBar/tree/e5d6977ba547aa7046eed3865f8ee1cdd5d58731/Sources/CodexBarCore/Providers/Antigravity).
Synthetic canary tests establish non-disclosure in their fixtures, not that a
real execution never opens credentials. CLI/IDE archive and subagent tests do
not establish behavior of untested upstream UI operations.

Real-source parity and credential-access acceptance require separate
authorization; completion is unknown. If authorized, compare the reader and
oracle on coherent private snapshots using the token-rule projection, reconcile
concurrent-source changes before interpreting mismatches, and check discovery,
archive, zero-step, large-database and unpriced results. A separate sandbox
denying reads outside the admitted files and SQLite coordination sidecars is
needed for unopened-credential evidence. Keep copies and evidence private and
remove only the scratch created for that run. Historical session authorization
and oracle paths are not standing permission or executable instructions.

After an authorized deployment, follow the [deployment guide](../../docs/local_deployment_sync.md#native-colophon-deployment)
and audit the installation. Run the installed executable offline and without
opening a browser against fresh private synthetic source and runtime homes;
inspect the generated page without replacing the owner's runtime page. Compare
source and installed `--version`, `payload.meta.version`, and the rendered
`[data-version]` footer, allowing the `colophon ` display prefix. All four
must agree with the release version and the installer audit must succeed.

## Test isolation and maintenance

The [tests README](../tests/README.md) describes fixtures and browser guards.
Wrappers create invented homes/logs under `/tmp`, select the tested release
through `COLOPHON_BIN`, disable Python bytecode/pytest caches, and deny real
runtime/project writes and reads/writes of protected historical checkouts.
The active source, executable, assets and development dependencies remain
readable. Compilation precedes sandboxed runtime validation.
Keep all temporary data, reports and execution evidence outside the public
checkout; do not introduce real session data even into ignored directories.

Sandbox lesson: inherited macOS `TMPDIR` commonly points under `/var/folders`.
C `tmpfile()` followed that location and failed when the strict profile
allowed only `/tmp` scratch writes. Both wrappers now explicitly select
their fresh scratch directory as `TMPDIR`. Preserve this setting and the
sandbox boundary instead of widening writes to system temporary directories.

The pytest wrapper also evaluates the source-write policy under a canonical
scratch `PROJECT_DIR` and verifies that removing its explicit deny makes the
regression fail. Separate sandbox invocations avoid macOS's nested-sandbox
restriction. Policy evaluation leaves real homes and source untouched; all
mutation profiles and captured output live in trapped scratch directories.

Both wrappers unset `OPENCODE_DB` and `XDG_DATA_HOME` as well as
`CLAUDE_CONFIG_DIR`; per-case helpers remove them before intentional overrides.
The profile denies real OpenCode data, state, config, cache and Desktop roots.
Each of the five explicit read/write denies is independently mutation-tested
under an existing synthetic ancestor in canonical scratch. Keep `HOME` and
runtime isolated for every direct smoke run, including offline/rebuild runs.

Optional Unicode maintenance uses
`.venv/bin/python -B tools/gen_unicode.py src/gen` only as a deliberate
maintainer action, with `PYTHONDONTWRITEBYTECODE=1` and Unicode 16.0.0.
Python 3.14's `unicodedata` must report that exact version; the generator
rejects other versions. Normal builds consume committed tables. This
generator must not regenerate the separate Unicode 17 pricing Numeric,
Extend/SpacingMark/ZWJ and Prepend ranges.

Asset refresh, font subsetting and public pricing updates are deliberate
maintainer actions requiring provenance review and the full suite; they are
not build steps or part of a private-state migration. No font generator or
historical pricing updater is shipped here. Preserve [notices](../THIRD_PARTY.md)
and the asset manifest when deliberately updating embedded inputs.

Changes to serialized Codex `LogRecord` or `TokenStream` content require a
native cache format bump in `src/cache/cache.c`; compose-only accounting rows
are rebuilt and are not cached. Keep Claude codec versions independent and
preserve their old decoders and immutable synthetic inputs.

Pricing lesson: an incorrectly seeded long-context threshold must be corrected
in every existing curated-history row, not only in the resolver or a new dated
row; dated lookup otherwise keeps earlier usage incorrectly priced. Validate
raw tier keys/types and rate underflow in both catalog tier locations before
sanitization, and decode the complete array even after finding a matching tier.

Ledger lesson: snapshots and request-ledger records have different numeric
contracts. Validate required request fields and covering totals before response
deduplication; a malformed record must not consume a later valid response id.
Keep the raw per-file request-session ownership separately from thread identity,
and share nonempty turn-alias selection across ledger and token-stream parsing.

Request pairing must consume events chronologically: a whole-file exact pass
can reserve a request away from its earlier near mirror and double-count usage.
Keep exact indexes restricted to observed counterparts, file-local replay
separate from session-wide counting, and two-pass mirror aliases independent of
copy order. Guard regressions must cover record aliases, paired-snapshot aliases
and observation keys without last usage independently.
An already-owned repeated snapshot must preserve a different response's pending
mirror; otherwise it consumes that request's pairing slot and leaves its real
snapshot counted again. Keep response ownership canonical and share its key
builder with cross-copy aliases.

Priority lesson: a final per-turn priority flag loses the state at earlier rows
when the same turn resumes under different settings. Keep file-local start
history indexed by turn and line, and pass it to both compose passes. Settings
changes take effect at the next start; turnless starts and rows share the empty
id. Preserve trace/sticky evidence independently from the thread setting.
