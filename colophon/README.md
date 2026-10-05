# Colophon

## Name

A colophon records who made a book, when, where and how. Colophon applies that
idea to Codex sessions: a local, read-only explorer of their activity and cost.
The [design spec](docs/colophon_design_spec.md) defines the complete application.
The compiler scans logs, preserves dated prices, and writes a self-contained
offline page. The page shell includes embedded Martian Mono, period controls,
URL history, search across full titles and requests, an archive toggle, and
collapsible diagnostics. Overview tiles and calendar, weekday/hour, workspace,
model, notable, and recent-session panels respect the active filters and the
viewer’s time zone. Click their values to drill into your matching sessions;
model-only descendant matches retain their parent and highlight the child.
The session list groups local days under newest and ranks other sorts by
the active period's time, agent time, tokens or cost. It includes orphaned
agents as flagged top-level sessions. Selecting a row opens the reader beside
the list at widths of 900 px or more; narrower pages use a back control.
The reader shows all-session usage with your/subagent splits, turn cards,
requests, tools, expandable agent details, outside-turn usage and a timeline.
Forked agents carry a timeline badge. Fork links show a known parent's title,
including parents outside the active filters, and retain its ID for navigation;
unavailable or conflicting titles fall back to the ID.
Unknown clocks stay unknown; recorded durations remain visible without
inventing active intervals. Font sources and regeneration are documented in
[font.md](docs/font.md).

Layouts are measured at 360, 390, 899, 901, 1024 and 1440 px, including long
synthetic names, dense agent timelines and expanded reader content. Truncated
labels expose their full text in tooltips. The calendar is the only horizontal
scroll region and starts at the most recent week. Keyboard Tab exposes a visible
focus ring; Enter and Space activate controls, whole session rows and reader
actions. Browser tests intercept Codex links and stub the clipboard; they do
not open the desktop application or execute copied commands. The thirty declared
text/background token pairs meet WCAG AA without further color changes.

Reader copy actions use the browser clipboard and fall back to a selected,
read-only field with a “press ⌘C” hint. “Continue in CLI” copies a command that
uses `codex resume <id>`; “Open in Codex” targets `codex://threads/<id>`.
Open-in-Codex and CLI support flags have browser-only
coverage; live, archived and subagent desktop behavior remains unverified
until Task 26's explicitly authorized pre-ship acceptance, including archived
session behavior. These flags do not establish desktop support.

Overview time totals clip to the selected period: your active time unions
overlapping own turns, while agent time sums each descendant’s own union.
Token and cost totals use the starts of the recorded 15-minute buckets and
include each descendant once. Unknown timestamps do not establish period
membership. The snapshot instant defines “now,” keeping an offline page stable.
The model tooltip lists recorded pricing references in matching sessions across
all dates; the payload does not map individual buckets to rate periods. Numeric
costs with missing references retain their estimate and show “rate period unknown.”
Token and cost LIVE markers count only running turns whose contribution to the
selected window is proved by conserved own usage. A timed bucket and a running
turn in the same session do not establish that relationship. Numeric cost and
unpriced-token contributions are proved separately; ambiguous usage has no marker.
This usage proof needs no inferred turn timestamp; time figures still require
their own known intervals. Numeric cost evidence must exceed the documented
currency representation tolerance as well as local arithmetic error.
Null-cost buckets may mix paid and unpriced units. A cost LIVE witness retains
all competing token capacity and may establish paid contribution alongside
wholly unpriced components only from conserved usage quantities, never from a
null cost or missing pricing reference alone.

## Install

Install [uv](https://docs.astral.sh/uv/) (`brew install uv` on macOS), then run
`./colophon` from this directory. The launcher requires Python 3.12 or newer;
uv selects the interpreter. It has no third-party runtime dependencies.
The single executable can also be copied into a directory on your `PATH`.

For development on Homebrew macOS, create a project virtual environment only
if `.venv` does not already exist; never overwrite an existing environment.
The absolute Homebrew interpreter is used only to create this new environment;
use its explicit venv binaries thereafter:

```sh
/opt/homebrew/bin/python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```

## Usage

```sh
./colophon --help
./colophon --version
./colophon --offline --no-open --codex-home /synthetic/codex-home
```

The synthetic example path must exist. The default source is `~/.codex`.
Missing or unreadable Codex homes exit 1; invalid flags exit 2.
Help and version commands do not create runtime files.

| Exit code | Meaning |
|---|---|
| 0 | Success, including empty or partly skipped inputs and failure to open the browser after writing the page. |
| 1 | Fatal error: missing/unreadable source, page write failure, interruption or unexpected failure. |
| 2 | Usage error, including conflicting flags. |

The fixed quiet threshold is two hours. An unfinished turn with recent activity
is running; after that threshold it is abandoned. Warm scans reclassify open
turns against the new snapshot time. A recent partial final line is silently
ignored; an old one produces a diagnostic. A live **subagent** caught mid-write
withholds fallback `token_count` usage until its final line completes, matching
CodexBar's end-of-file gate. Primary per-response records and bare usage still
count, subject to each turn's accounting-path selection. Until fallback replay
runs, primary usage follows the file's own `C`/`XC` model observations in order,
without the owned-suffix model reset, so known models remain priced.

Cold scans show parsed/total MB and a whole-second ETA on terminal stderr.
Redirected stderr receives final summaries only; warm cache hits have no parsing
progress. MB follows the page summary's 1,048,576-byte unit.

## Performance validation

The full suite includes a fixed cold scaling test: 100 and 200 own sessions,
each with forty turns and one forty-turn subagent. Each turn carries a request,
tool and token count; alternating turns also carry primary usage records, so
both retained accounting paths are exercised. Fixture generation is outside
the timed CLI subprocess. Three fresh runtime homes per size establish medians;
the smaller median must stay at least two seconds and doubling must take no
more than 2.5 times as long.

Local throughput acceptance is separate from pytest. After authorizing real
log access, run from this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/perf/measure_throughput.py --codex-home /synthetic/codex-home
```

Replace the synthetic path with the approved source. Without `--codex-home`,
the tool reads `~/.codex`. `COLOPHON_HOME` selects the baseline directory,
defaulting to `~/.colophon`. It compiles offline with `--rebuild --no-open` in
a fresh temporary runtime home, reports page size and diagnostics, then removes
the temporary page/cache. MB/s uses the scan's actual parsed bytes divided by
the complete cold compiler duration. The first nonempty measurement writes a
private, atomic `perf-baseline.json` with `mb_per_s`, `measured_at`, `logs` and
`bytes`. Later runs preserve that baseline and exit 1 with `REGRESSION` when
throughput falls below baseline divided by 1.5. Empty measurements or damaged
baselines exit 1 without replacing the baseline. Review and deliberately remove
an old baseline before recording a new one. Colophon itself never reads it.

## Flags

| Flag | Contract |
|---|---|
| `--no-open` | Suppress opening the compiled page in a browser. |
| `--rebuild` | Reparse logs into a fresh cache, replacing the cache on success. |
| `--offline` | Use cached catalog and price history without a catalog request. |
| `--refresh-prices` | Force an unconditional catalog download. Conflicts with `--offline`. |
| `--output PATH` | Write the compiled page to an explicit path. |
| `--codex-home PATH` | Read Codex data from this directory; default `~/.codex`. |
| `--version` | Print the version and exit. |
| `--help` | Show flags, environment variables and runtime files. |

`--offline --refresh-prices` is rejected. The page is written before the parse
cache is committed, so a failed page write preserves the previous cache.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `COLOPHON_HOME` | `~/.colophon` | Private mutable runtime directory; `~` is expanded. |
| `COLOPHON_PRICING_URL` | `https://models.dev/api.json` | Price-catalog endpoint, including a local test catalog or mirror. |

## Runtime files

Colophon creates the runtime home with mode 0700 and reapplies that mode on
each run. Every file it writes has mode 0600 and is replaced atomically.
First-run files are created only when absent; existing files are preserved.
Each initialization removes direct hidden `.*.tmp` regular files older than
one hour, retaining recent files that may belong to a concurrent run.

| Path | Purpose |
|---|---|
| `price-history.json` | User ledger; initially `{"schema": 1, "entries": []}`. |
| `workspaces.example.json` | Synthetic alias example, never read as configuration. |
| `workspaces.json` | Optional workspace aliases. |
| `priority-turns.json` | Persistent detected priority-turn metadata and first-seen times. |
| `pricing-cache.json` | OpenAI price-catalog cache. |
| `cache/` | Per-log parse records; changed logs are reparsed from the beginning. |
| `colophon.html` | Compiled offline page. |
| `perf-baseline.json`, `parity/` | Local acceptance outputs only. |

The catalog fetcher stores only the OpenAI provider in `pricing-cache.json`,
with its URL, ETag and successful fetch time. Matching URLs use conditional
requests; refresh requests omit the ETag. A 304 preserves the fetch time.
Connection and headers share a three-second budget; the body has thirty
seconds. Failures use a valid cached catalog with diagnostics. A cache from
another URL remains a fallback with a warning, without sending its ETag.
Offline fetching opens no socket. Catalog fetching overlaps the log scan;
failure or a bounded wait uses the available cached catalog with diagnostics.

Priority detection (A1) cold-scans the `logs` table in
`<codex-home>/logs_2.sqlite` for upstream priority-request trace evidence and
retains detected turn ids in sticky memory. Later detections replace stored
metadata while retaining `first_seen_ms`; absent turns remain remembered after
trace pruning. Usage older than both the trace database and the first Colophon run
remains standard-priced because no priority evidence survives for those turns.

## Privacy

Colophon never modifies Codex data or non-SQLite files under the Codex home.
SQLite databases use `file:<path>?mode=ro` with the plan-specified timeout;
SQLite's own read coordination may create or update `-shm` and `-wal` side files.
That coordination is the one exception to the read-only source policy, approved
on 2026-10-04. Live reads retain normal SQLite locking and change detection;
they do not use immutable mode or exclusive locking. Metadata reads wait up
to one second; an unreadable or locked database falls back to older database
schemas or log, index and desktop titles, with diagnostics.
Priority trace reads use a 250 ms timeout; a missing trace database is silent,
and a locked or unreadable trace database keeps stored priority-turn evidence
with diagnostics. Detected entries replace stored metadata while preserving
their first-seen time. Valid remembered turns survive trace pruning.
Runtime state belongs outside this public repository.
The compiler's only network traffic is the price-catalog GET; it
sends no session data. `--offline` suppresses that request. uv may provision
an interpreter on its first invocation. The generated page contains private
requests and final answers, so keep it private, including explicit outputs.
Public tests and examples use conspicuously synthetic values; private
acceptance output must never be committed.

## Price history

The curated ledger in the launcher supplies starting rates. The user ledger
`price-history.json` stores dated catalog observations and manual corrections;
curated entries are never copied into it. Rates are USD per million tokens.
Each entry names an exact normalized model id, or a priority override pricing
key. A newer catalog observation keeps earlier usage on its earlier rates.
Catalog changes are dated when downloaded, so detection can lag the real change.
Usage between the real change and its detection keeps the previously known
rates. Correct that interval with a `manual` entry at the true UTC change time.

To correct a historical rate or introduce a priority multiplier, find the
applicable period in the user ledger or the launcher's curated history. Copy
its `per_million` and, if present, `long_context` into a new `manual` entry
with the true UTC date, then add the priority object. This invented model
gains a multiplier without changing its standard rates; its original period
has no long-context block, so the example omits it:

```json
{
  "model": "gpt-synthetic-example",
  "effective_from": "2030-01-07T00:00:00Z",
  "per_million": {"input": 2, "cached_input": 0.5, "cache_write": 3, "output": 7},
  "priority": {"multiplier": 2, "max_input_tokens": null},
  "source": "manual",
  "note": "Synthetic example; replace with reviewed public rates"
}
```

Add the entry to the ledger's existing `entries` list under `schema: 1`.
All four rates are required. Optional `long_context` and `priority` must be
objects when supplied; omit absent objects. Only the curated ledger permits
a null effective date. Unknown JSON metadata is preserved, but nonfinite
numbers are invalid everywhere. Same-key duplicates compare JSON values:
booleans differ from numbers, while integer and decimal numbers can be equal;
only `note` and `recorded_at` are excluded. A manual correction remains effective
until the catalog's rates change; a model priced only manually gets a catalog entry
when the catalog first lists it. Invalid ledgers disable recording and costs
in the compiler while retaining token counts. An editor save during a run
skips recording with a warning rather than overwriting the edit.

Usage with no timestamp retains a null bucket and uses current resolved rates
and the source's current priority policy in a transient period, without picking
a dated ledger entry. Diagnostics report its input plus output token volume as
"priced at current rates: usage has no timestamp". Costs are always an
API-equivalent estimate (not billed).

Maintainers can refresh the seed with a reviewed public models.dev snapshot:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/tools/seed_price_history.py --snapshot /tmp/public-models-dev-snapshot.json --snapshot-date YYYY-MM-DD
```

The tool reads only the explicit snapshot and launcher, prints deterministic
indented JSON, and never fetches data. Paste its output between the launcher's
`CURATED_PRICE_HISTORY` markers and record the date, SHA-256 and command in
`docs/token_rules.md`. Keep the snapshot outside the repository. Historical
cutoffs and priority multipliers remain pinned to the cited CodexBar source.
To promote later observed rates, list user-ledger catalog entries newer than
the curated history, review their public rates, and add selected entries to
the curated block with source `curated`; then validate and commit. Promote
manual corrections only deliberately, after reviewing them for privacy.
Run the table check and full suite below before committing the curated update.

## Validation and upstream parity

From `colophon/`, run the complete unit, CLI, browser and scaling suite; no
skips are permitted. Browser dependencies are installed by the development
commands above. These tests use synthetic homes, never real Codex data:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/parity/check_upstream_tables.py --codexbar <pinned-CodexBar-checkout>
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/parity/check_upstream_drift.py --codexbar <CodexBar-checkout> --to 3bbf6bc48
```

The table checker verifies the bundled and curated source values at the pin.
The drift checker reads the function map in [token_rules.md](docs/token_rules.md).
From the repository root, run all fleet checks:

```sh
uv run --no-python-downloads --script tools/check_uv_headers.py
PYTHONDONTWRITEBYTECODE=1 colophon/.venv/bin/python -m pytest tools/tests/test_check_uv_headers.py -q
zsh tools/tests/test_check_local_deployments.zsh
node --test tools/tests/check_static_deployments.test.mjs
```

Local parity acceptance requires explicit authorization for its source and
runtime homes, and separate approval for real data. The three pinned CLI
commands (`codexbar cost --provider codex --format json --period all`, with no
group option, `--group-by session`, or `--group-by project`) provide day/project
cross-checks; none supplies session IDs. Session truth comes from a dedicated
Swift test target calling pinned **CodexBarCore** through
`CostUsageFetcher.loadCachedCodexTokenSnapshotForScopedHome`, with project/session
tracking enabled and Pi disabled, using the caught-up isolated cache, copied trace and
shared catalog/window/time zone. Colophon reads the authorized source home
immediately after CLI catch-up; source fingerprints must remain unchanged.
It never reconstructs session truth in Python.

Prepare an external detached clone at
`3bbf6bc48c20d8e507b30ed93dbdce19ed928bb6`, install the tracked harness as
documented in [the native oracle README](tests/parity/native_oracle/README.md),
and build with exactly:

```sh
swift build --build-tests --disable-keychain --force-resolved-versions -j 8
```

Keep upstream `Sources/` untouched. The clone, source and fake home must avoid
symlinked paths (the native README explains `/private/var/tmp` preparation).
Read the default pinned CLI's adjacent `PROVENANCE.md` in
`~/Downloads/colophon-prebuilt/codexbar-cli-3bbf6bc48/` before execution.
Record provenance from the repository root, using private paths:

```sh
PYTHONDONTWRITEBYTECODE=1 colophon/.venv/bin/python colophon/tests/parity/compare_codexbar.py \
  --native-clone <external-clone> --native-bundle <test-bundle> \
  --native-provenance <private-provenance.json> --record-native-provenance
```

The provenance records the prescribed build command. The runner checks the
exact pin, harness and bundle hashes and upstream source state, including
staged, tracked and untracked source changes; it does not prove the build
invocation from that recorded command.
After human authorization, run acceptance from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 colophon/.venv/bin/python colophon/tests/parity/compare_codexbar.py \
  --approved --codex-home <authorized-source-home> --colophon-home <authorized-runtime-home> \
  --native-clone <external-clone> --native-bundle <test-bundle> \
  --native-provenance <private-provenance.json> --output-dir <new-private-output-directory>
```

Real-data runs additionally require `--real-data-approved`; these flags record
approval and do not obtain it. The guarded runner requires the CodexBar app
quit and Sandbox self-test success, sets isolated `HOME` and `CFFIXED_USER_HOME`,
denies network and real-home writes/cache reads, and compares before/after real
CodexBar cache/preferences fingerprints. Only the dedicated exporter is run;
unfiltered upstream tests are prohibited. It copies ledger, catalog, sticky
memory and a consistent read-only SQLite trace backup into private isolation.
Public catalog fetching occurs outside the guard; `--offline-catalog` uses the
selected cached public snapshot, never the synthetic fixture catalog.

Default limits are 30 CLI and 10 native runs, each configurable only to at
least three. Three consecutive stable CLI runs establish catch-up before
immediate offline Colophon compilation and native export with fixed inputs.
Native stability also requires three consecutive matches. Size
`--max-runs` for the corpus: the pinned refresh budget is
512 MiB per refresh, so allow catch-up plus three stable matches. Defaults
alone do not establish completeness; scan metadata and history coverage must
also be complete. Any structural tie at a session ID's maximum file mtime makes
the oracle incomplete,
including files outside the selected window: even `500/500/500` cannot resolve
it. Any material disagreement remains a failure even after a matching suffix
(`500/600/500/500/500`). Tied IDs are reported, never silently selected.

Native day/project fields and nested model/source metrics must agree with CLI
cross-checks (relative tolerance `1e-10`, absolute `1e-12`). Token parity is
exact; cost parity permits `1e-9 × abs(reference) + 1e-9` USD. Missing session
IDs, required nulls and ambiguous/tied observations remain explicit oracle
gaps. Primary/fallback, date, sticky priority, trace and approved fork differences
need evidence for classification as approved differences; unexplained token or
cost differences fail. The cold fallback check uses upstream rates and the
copied trace without sticky memory, across day/project/session units.
Custom CLI differences are class (d), never explained as approved deviations.
Reports, raw native/CLI output, pages, logs and fingerprints stay in the explicit
private output directory (default `$COLOPHON_HOME/parity/<UTCstamp>/`), never in
this repository. Real-data and desktop-link verification remain Task 26 work.

## Attribution

Token and pricing rules are adapted from [CodexBar](https://github.com/steipete/CodexBar)
at `3bbf6bc48` (MIT, © 2026 Peter Steinberger). Catalog rates come from
[models.dev](https://models.dev/) (MIT). Embedded Martian Mono uses the
[SIL Open Font License 1.1](OFL.txt); see [font.md](docs/font.md).
