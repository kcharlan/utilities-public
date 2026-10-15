# Runtime behavior

The offline page defaults to all sources. Its All/Codex/Claude segmented
switch persists as `src=all|codex|claude` in the URL hash and retains the
other filters. Switching away from a selected reader's provider closes that
reader. Missing legacy provider fields mean Codex. Source filtering applies
to overview totals, session lists, descendants and direct subagent links.
The snapshot log count always includes both sources, regardless of the switch.

Codex uses green and Claude uses blue. In All, KPI share rules and workspace
bars split by provider; calendar cells use the provider with the greater
selected metric (ties use Codex). Model, recent and list rows carry provider
marks. Costs retain each provider's independent availability; a known subtotal
also names unavailable providers. Absent/disabled sources remain selectable
with a no-data label and explain the checked paths or `--no-claude` flag.
The All footer includes absent-source details, Claude unknown-record diagnostics
and the start of Claude token data when later than the calendar's start.

Claude history-only sessions are shown by default. The independent history-only
toggle persists as `h=1|0` in the hash, like the archive toggle `a`; both apply
to lists, descendants and direct reader links while preserving other filters.
`HISTORY ONLY` marks these rows in lists, recent sessions and readers. Each
usable history entry contributes one unknown-status turn and its prompt to
period filters and the hour-by-weekday grid. History adds no active time,
tokens or cost. Its first/last timestamps bound the session, and the first
entry's project supplies cwd. Empty or malformed-only history does not establish
source presence; usable history can be the sole source after directories vanish.

History identities match exact canonical Claude filename IDs first, then unique
primary transcript `sessionId` aliases. Aliases from live, retained, provisional
and collision-skipped records suppress duplicates. Ambiguous aliases emit no
history-only row and appear with candidate owners in
`claude_history_alias_conflicts`; Codex identity collisions keep Codex.
`meta.sources.claude.history_only` counts emitted history sessions and
`token_data_from_ms` reports the first actual Claude token datum, or null.

Claude readers keep Copy session ID and never offer Codex links. Copy Continue
in CLI requires the lifecycle and subagent support flags, an absolute cwd and
established primary CLI config-root provenance. Deleted and history-only rows
cannot continue or copy a log path. Desktop/Cowork and cswap origins without
CLI provenance cannot continue. The copied command changes to cwd and sets
`CLAUDE_CONFIG_DIR` before `claude --resume`; every substituted value uses
POSIX shell quoting. Copying never runs the CLI. The command follows the
[Claude CLI reference](https://code.claude.com/docs/en/cli-reference) and
[settings reference](https://code.claude.com/docs/en/settings).

`--codex-home PATH` selects readable Codex data (default `~/.codex`).
Claude is enabled by default. `--claude-home PATH` overrides
`CLAUDE_CONFIG_DIR`; a nonempty value is one literal directory, resolved
relative to the process working directory, without tilde expansion.
An empty value selects the default `~/.claude` config root. Its
`history.jsonl` is inspected read-only for usable history entries.
`COLOPHON_HOME` selects the private runtime home (default `~/.colophon`);
tilde expansion is supported. `COLOPHON_PRICING_URL` defaults to
`https://models.dev/api.json`. Help and version exit without initializing
runtime state. Version is currently `colophon 0.2.0`.

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

Claude subagents are read from
`<projects>/<slug>/<session>/subagents/agent-<id>.jsonl`; their identity is
`<session>/agent-<id>`. An optional neighboring `agent-<id>.meta.json`
supplies `parentAgentId`, `toolUseId`, `spawnDepth`, `description` and
`agentType`, each validated independently. Other sidecars, including
`.prefix.json`, are ignored. Without a sidecar the parent is the session
and the spawn turn is unknown. Nested agents resolve tool IDs in their
actual parent agent's transcript. Missing parents and cycles become orphans;
Claude orphan diagnostics are separate from legacy Codex diagnostics/counts.
Orphans remain standalone session rows with their usable label, nickname,
depth and attempted parent identity; their spawn turn requires a resolved
parent transcript.

Desktop metadata is read from
`<desktop-dir>/claude-code-sessions/<account>/<org>/local_*.json` and matched
by `cliSessionId`. These JSON files and subagent sidecars are never edited.
Metadata provides title, archive state, cwd and creation/activity clocks;
usable transcript cwd/clocks take precedence over metadata fallbacks. Titles
prefer Desktop, then the latest custom-title record's candidate, latest
AI-title record's candidate and first prompt, through the shared display-title
formatting. An empty, invalid or missing candidate in the latest title record
clears the prior candidate, allowing fallback to the next title source.
Malformed Desktop metadata appears in `metadata_errors` with a `claude:` prefix. Desktop entries
without a transcript or retained record are counted separately. Disabled
Claude input does not read Desktop metadata.

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
opening, recovery and replacement, including with `--rebuild`. Eligible Claude
history entries render history-only sessions. Decodable retained records and eligible
provisional deletion candidates also establish presence (see below).

The home is created and reapplied with mode 0700; written files are mode
0600. Page and ordinary state replacements are atomic. Missing parent directories
of an explicit output are created with mode 0700. Direct hidden `.*.tmp` regular
files older than one hour are cleaned from the runtime home.

| Runtime path | Purpose |
| --- | --- |
| `colophon.html` | Generated offline page. |
| `cache-native/` | Native per-log parse cache; changed logs reparse from the beginning. |
| `cache-claude/` | Claude parse records, grouped by resolved search root. |
| `claude-retained/` | Claude facts retained after proved source deletion; no automatic age limit. |
| `price-history.json` | Editable user ledger, created with schema 1 and empty entries. |
| `pricing-cache.json` | Shared multi-provider catalog, URL, ETag and successful fetch timestamp. |
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

## Claude parse cache and retained transcripts

`cache-claude/<root-key>/<path-key>.rec` contains parsed Claude facts;
`claude-retained/<root-key>/` contains records whose source transcripts were
positively proved deleted. Keys are SHA-256 names from the resolved search-root
and original transcript paths. Files are private (0600), directories 0700.
The Claude CLCD2 codec is independent of the Codex native cache. It preserves
exact aliases, original paths, config/resume origin, prompts, turns, tools,
sidecar facts and every raw usage row, including extraction-time cost snapshots
for duplicate losers. Earlier codec versions keep their decoders and immutable
synthetic test inputs.

Same-stem copies share a reader assembled from their available turns. Prompt
UUIDs identify turns; conflicting UUIDs stay distinct. When UUIDs are unavailable,
the fallback matches exact prompt time, text, kind, image count and occurrence
within each copy. Identical partial prompts without UUIDs cannot always be
distinguished. The latest known turn clock/status and latest nonempty answer
are selected independently; equal-clock conflicts keep the first discovered
fact (a terminal status wins an equal-clock open status). Identified tool calls
are unioned by tool ID within each canonical turn, with failures preserved.
Anonymous tools use record identity or timestamp, name and block occurrence.
Accounting copy precedence and ascending live resume-config selection remain
independent of reader reconciliation.
An identical accounting response may supply a missing display turn from another
copy of the same canonical session; different session stems never donate turns.

CLCD1 retained records remain readable. Their aggregate tool counts use a
per-category maximum across copies because older facts cannot distinguish
mirrored calls from complementary calls; their answer ordering uses the turn's
last known clock. Live CLCD1 cache records reparse to obtain richer identities.
Runtime turn mappings never replace the original stored turn keys or usage rows.

Existing stores and history are inspected read-only before runtime creation.
Decodable retained records and eligible provisional deletion candidates establish
source presence. Retained records are read regardless of the selected roots;
`--no-claude` disables both reading and reconciliation. Installed cache records
are considered only for selected search roots, including on `--rebuild`.

Deletion requires a complete, uninterrupted scan plus a fresh ENOENT path check
and a readable/searchable surviving ancestor. Removed project directories,
Desktop session containers and cswap slots/roots retain their original search-root
provenance. Unreadable trees, other path errors and interrupted traversals never
prove deletion. Existing empty transcripts supersede stale facts with an empty
live record; they are not deletions. Unknown or corrupt installed cache data is
reparsed when its source is available. Corrupt/unreadable retained data remains
untouched and appears in `claude_retained_unreadable`.

Provisional and retained facts participate in the first disappearance-run page
and in response deduplication. Their owning sessions receive `transcript_deleted`.
Live parsed paths take precedence. Cached transcript hits still refresh live
sidecars independently; retained records preserve the last successfully observed
sidecar facts. History aliases survive retention and identity collisions.

Only successful page output permits commit. Before the first change for a root,
commit rechecks every provisional candidate. Changed evidence aborts all cache
updates and retention moves for that root, preserving its installed records;
the already-written page remains the scan snapshot. Eligible installed records
are atomically renamed into retained storage, then live records are atomically
installed. Rebuild reparses into the in-memory staging set rather than removing
an installed directory. Ineligible/unreadable installed records are not pruned.
Interrupted commits recover each record from its installed or retained location;
existing retained copies are never overwritten. Recovery siblings can accumulate,
and only one record per original path is replayed. A successfully installed live
record removes its decodable retained copies; undecodable files remain untouched.
Failed output and interruptions before commit leave all retention moves uncommitted.

Retention has no automatic age or size limit. It stores parsed facts, not original
transcript bytes, and is not a transcript backup. To forget retained data, stop
Colophon and manually remove the desired records (or the complete
`claude-retained/` directory) from the private runtime home. Also remove matching
`cache-claude/` records to prevent later deletion reconciliation from restoring
those facts. `--rebuild` does not forget retained data. Source transcripts and
sidecars are never edited.
