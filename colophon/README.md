# Colophon

## Name

A colophon records who made a book, when, where and how. Colophon applies that
idea to Codex sessions: a local, read-only explorer of their activity and cost.
The [design spec](docs/colophon_design_spec.md) defines the complete application.
The current scaffold validates the Codex home and initializes private runtime
files; log compilation and the offline page are added by subsequent tasks.

## Install

Install [uv](https://docs.astral.sh/uv/) (`brew install uv` on macOS), then run
`./colophon` from this directory. The launcher requires Python 3.12 or newer;
uv selects the interpreter. It has no third-party runtime dependencies.
The single executable can also be copied into a directory on your `PATH`.

For development, use a project virtual environment:

```sh
python3 -m venv .venv
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

Compilation flags are parsed now; their pipeline behavior arrives with the
compiler. `--offline --refresh-prices` is already rejected.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `COLOPHON_HOME` | `~/.colophon` | Private mutable runtime directory; `~` is expanded. |
| `COLOPHON_PRICING_URL` | `https://models.dev/api.json` | Price-catalog endpoint, including a local test catalog or mirror. |

## Runtime files

Colophon creates the runtime home with mode 0700 and reapplies that mode on
each run. Every file it writes has mode 0600 and is replaced atomically.
First-run files are created only when absent; existing files are preserved.

| Path | Purpose |
|---|---|
| `price-history.json` | User ledger; initially `{"schema": 1, "entries": []}`. |
| `workspaces.example.json` | Synthetic alias example, never read as configuration. |
| `workspaces.json` | Optional workspace aliases. |
| `priority-turns.json` | Persistent priority-turn memory, introduced with usage composition. |
| `pricing-cache.json` | OpenAI price-catalog cache, introduced with catalog fetching. |
| `cache/` | Parse records, introduced with log scanning. |
| `colophon.html` | Compiled offline page, introduced with the compiler. |
| `perf-baseline.json`, `parity/` | Local acceptance outputs only. |

Priority detection follows upstream's trace database and retains detected
turn ids. Usage older than both the trace database and the first Colophon run
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
The completed compiler's only network traffic is the price-catalog GET; it
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

To correct a historical rate or introduce a priority multiplier, copy the
applicable entry's `per_million` and, if present, `long_context` into a new
`manual` entry with the true UTC date. For example, this invented model gains
a multiplier from a date without changing its standard rates:

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
a null effective date. A manual correction remains effective until the
catalog's rates change; a model priced only manually gets a catalog entry
when the catalog first lists it. Invalid ledgers disable recording and costs
in the compiler while retaining token counts. An editor save during a run
skips recording with a warning rather than overwriting the edit.

Maintainers can refresh the seed with a reviewed public models.dev snapshot:

```sh
.venv/bin/python tests/tools/seed_price_history.py --snapshot /tmp/public-models-dev-snapshot.json --snapshot-date YYYY-MM-DD
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
