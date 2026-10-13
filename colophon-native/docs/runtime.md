# Runtime behavior

`--codex-home PATH` selects readable Codex data (default `~/.codex`).
`COLOPHON_HOME` selects the private runtime home (default `~/.colophon`);
tilde expansion is supported. `COLOPHON_PRICING_URL` defaults to
`https://models.dev/api.json`. Help and version exit without initializing
runtime state. Version is currently `colophon 0.1.0`.

| Flag | Behavior |
| --- | --- |
| `--no-open` | Write the page without opening a browser. |
| `--offline` | Use cached catalog/history without a catalog request. |
| `--refresh-prices` | Force an unconditional catalog download; conflicts with offline. |
| `--rebuild` | Reparse every log into a fresh native cache, installed on success. |
| `--output PATH` | Write the page at this explicit path instead of the runtime default. |

The home is created and reapplied with mode 0700; written files are mode
0600. Page and ordinary state replacements are atomic. Parent directories
of an explicit output must already exist. Direct hidden `.*.tmp` regular
files older than one hour are cleaned from the runtime home.

| Runtime path | Purpose |
| --- | --- |
| `colophon.html` | Generated offline page. |
| `cache-native/` | Native per-log parse cache; changed logs reparse from the beginning. |
| `price-history.json` | Editable user ledger, created with schema 1 and empty entries. |
| `pricing-cache.json` | OpenAI catalog, URL, ETag and successful fetch timestamp. |
| `priority-turns.json` | Sticky detected priority-turn metadata and first-seen times. |
| `workspaces.json` | Optional workspace aliases. |
| `workspaces.example.json` | Synthetic template, never read as configuration. |
| `native-events.jsonl`, `native-events.jsonl.1` | Best-effort native event log and rotated predecessor. |

Python and native share the ledger, catalog, priority memory, aliases and
default page when using the same home. Their parse caches are separate.
Select a different native home for independent state; the application does
not migrate existing private state. Shared-home use should be sequential.
Ledger recording checks for edits before replacement, but a concurrent edit
after the check can still be overwritten. There is no ledger lock spanning
the read/check/replace operation.

Codex JSONL inputs are read, not edited. Metadata and priority trace SQLite
databases are opened read-only with normal SQLite coordination. Metadata
uses a 1,000 ms busy timeout; priority tracing uses 250 ms. This is not
immutable mode: SQLite may create or update
coordination side files such as WAL shared-memory files when permitted.
An absolute no-source-writes guarantee would misdescribe this behavior.
Missing trace data is silent; SQLite errors retain sticky priority evidence
with diagnostics. Detected turns remain remembered after trace pruning.

Catalog fetching overlaps scanning. Matching URLs normally use conditional
requests; refresh omits the ETag and 304 preserves the fetch timestamp.
Failures fall back to a valid cache with diagnostics. A cache from another
URL can remain a warned fallback, without sending its ETag. Offline runs
open no catalog socket. A page write failure preserves the prior parse cache;
the page is written before cache commit, so a later failure can leave the
new page present. Browser-opening failure reports a fallback path and can
still succeed.

| Exit | Meaning |
| --- | --- |
| 0 | Success, including empty/partly skipped inputs and browser-opening fallback. |
| 1 | Fatal source, output or other runtime failure, or interruption. |
| 2 | Invalid arguments, including offline/refresh conflict. |

The page contains private session requests, titles, paths, identifiers,
tool/activity details, usage and cost estimates. Offline does not mean safe
to publish. Keep pages, runtime state and execution evidence out of this
public repository. The page embeds its data, scripts, styles and fonts and
makes no external requests. Reader actions can copy commands or open native
Codex links when the recorded support flags permit them; these are user
actions, not background page requests.

Current limits include quadratic worst-case combining-mark ordering,
best-effort event recording, and synchronous joined catalog cleanup that can
extend total wall time after a failure/cancellation. libcurl's certificate
trust behavior can differ from Python's HTTPS stack. A consumed cached ETag
containing NUL is retained as a JSON label but omitted from the HTTP request,
which can change refresh/fetch-timestamp outcomes. Performance is
workload-dependent and three original targets were missed; no new speed or
memory acceptance is claimed.
