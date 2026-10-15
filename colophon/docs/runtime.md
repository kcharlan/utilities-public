# Runtime behavior

`--codex-home PATH` selects readable Codex data (default `~/.codex`).
Claude is enabled by default. `--claude-home PATH` overrides
`CLAUDE_CONFIG_DIR`; a nonempty value is one literal directory, resolved
relative to the process working directory, without tilde expansion.
An empty value selects the default `~/.claude` config root. Its
`history.jsonl` is inspected read-only for usable history entries.
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
| `--claude-home PATH` | Select the Claude config root using the environment semantics above. |
| `--claude-desktop-dir PATH` | Replace `~/Library/Application Support/Claude` for discovery. |
| `--no-claude` | Disable Claude inputs and reconciliation. |

Default Claude search roots are `~/.config/claude/projects`,
`~/.claude/projects`, the Desktop `local-agent-mode-sessions` and
`claude-code-sessions` containers, and `~/.claude-swap-backup/sessions`.
A nonempty config override suppresses the XDG and Desktop roots while
keeping the override's `projects` and cswap. Desktop discovery finds
`.claude/projects` through four directory levels, skipping hidden,
package and build/output directories. Cswap selects positive numbered
`NUMBER-NAME/projects` slots. Search-root and slot symlinks are resolved
and deduplicated; nested symlink directories are not traversed.
Claude transcripts are read-only. Filename stems define session identities;
same-stem copies share a session. Codex wins an identity collision, reported
in `claude_session_id_collisions`. Unhandled Claude record types have their
own `claude_unknown_record_types` diagnostic. Claude reader rows offer no
Codex continuation or desktop links.

Primary CLI records preserve the resolved config origin for default `.claude`,
XDG `.config/claude`, environment and explicit config roots. Same-stem live
copies select the config origin in ascending resolved-path order. Desktop,
cswap and subagent records have no resume-config provenance. Missing,
non-directory and excluded symlink locator stores are ordinary exclusions;
permission and other traversal errors produce `skipped_files` and mark the
selected search-root scan incomplete.

Legacy `meta.counts` remains Codex-only. Claude log/parse counters are additive
under `meta.sources.claude`, independently of the legacy counts.

Long flags accept unique prefixes. `--no` is now ambiguous between
`--no-open` and `--no-claude`; `--claude` is ambiguous between the two Claude
path flags. `--c` is also ambiguous between Codex and Claude path flags.
Use the full flag names when scripting.

Presence is decided before creating the runtime home. A readable source
directory or a usable Claude history entry is sufficient. With neither,
exit 1 names the Codex home, Claude roots and history path checked, and
creates no runtime home. An absent Codex home skips all native parse-cache
opening, recovery and replacement, including with `--rebuild`. Claude
history is only inspected for presence in this release; history-only
session rendering and Claude parse caching/retention are separate work.

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

Prior Python releases used the same ledger, catalog, priority memory, aliases
and default page. Native retains compatibility and a separate parse cache.
Select a different native home for independent state; the application does
not migrate existing private state. Commands sharing a home must run sequentially.
Ledger recording checks for edits before replacement, but a concurrent edit
after the check can still be overwritten. There is no ledger lock spanning
the read/check/replace operation.

Codex `.jsonl` and `.jsonl.zst` inputs are read, not edited. Compressed logs
are stream-decoded in memory, never decompressed to disk. When a directory
contains both `NAME.jsonl` and `NAME.jsonl.zst`, only the plain copy counts,
because it may still be growing. Corrupt, truncated or still-being-written
compressed frames appear in `skipped_files` with reason `unreadable`, while
the remaining logs are counted; a later run retries them. A zero-byte
compressed file is an empty log.

Metadata and priority trace SQLite databases are opened read-only with
normal SQLite coordination. Metadata uses a 1,000 ms busy timeout; priority
tracing uses 250 ms. This is not
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

Decoding a single-segment compressed log can allocate a window as large as
the expanded log. The decoder accepts windows above its default 128 MiB
limit so larger finished rollouts remain included.

Current limits include quadratic worst-case combining-mark ordering,
best-effort event recording, and synchronous joined catalog cleanup that can
extend total wall time after a failure/cancellation. libcurl's certificate
trust behavior can differ from Python's HTTPS stack. A consumed cached ETag
containing NUL is retained as a JSON label but omitted from the HTTP request,
which can change refresh/fetch-timestamp outcomes. Performance is
workload-dependent and three original targets were missed; no new speed or
memory acceptance is claimed.
