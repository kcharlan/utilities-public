# Runtime behavior

## Antigravity source discovery

`--antigravity-home PATH` selects a Gemini root, defaulting to `~/.gemini`,
with explicit-path tilde expansion and lexical relative-path resolution.
`--no-antigravity` returns before expansion or inspection. Nonempty
`ANTIGRAVITY_GEMINI_DIR`, `ANTIGRAVITY_APP_DATA_DIR` and `JETSKI_APP_DATA_DIR`
are ignored and reported by name only; use the explicit flag instead.

Surface precedence is `antigravity` (app), `antigravity-cli` (cli), then
`antigravity-ide` (ide), with database filenames sorted within each surface.
Only `conversations/<uuid>.db`, same-surface `annotations/<uuid>.pbtxt`,
`conversation_summaries.db`, and their ordinary SQLite coordination sidecars
are admitted. Symlink escapes are excluded. Legacy `<uuid>.pb` names are
enumerated without reading contents: distinct IDs lacking a database across
all surfaces count as `legacy_encrypted`. Summary indexes never locate or
create conversation sessions. Credentials/settings and other Gemini subtrees
are outside the admission list.

Exact filename UUID strings own conversation identity, without case folding or
case-insensitive aliases; annotation paths retain that spelling and summary
joins use the same exact string. Case-only copies can remain distinct.
Trajectory and cascade IDs remain
independent raw facts and mismatches are diagnosed. The first successful
database for an ID wins. A schema-valid database with empty required tables
is an accepted empty raw session, as is a zero-step database with metadata.
Missing required tables/columns are unsupported; extra tables are ignored.
Each database uses one coordinated read-only transaction and no database-size
cap. Database/WAL/annotation bytes and modes remain unchanged; SQLite may
create or update shared-memory coordination files, as for OpenCode. A failed
snapshot never consumes its ID or removes successful siblings.
Every existing SQLite sidecar must be a regular file before SQLite opens either
a conversation or summary database; FIFOs, directories and symlinks are rejected
with a source diagnostic so they cannot block later readable siblings.

The bounded wire decoder validates the pinned public schema projection,
retains unknown fields and raw blobs only in memory, and distinguishes absent,
found and malformed fields. Malformed blobs lose their staged record, with
contextual diagnostics; SQL/read failures lose the staged database. Archive
annotations accept text protobuf whitespace, escaped strings and balanced
unknown nested messages. A valid annotation wins over its own surface's summary,
including absent `archived` meaning false. Unusable annotations diagnose and
fall back to summary; valid disagreement is counted. With neither source,
archive defaults false. Resolved true records use archive reason `session`.
Repeated occurrences of the singular summary annotations message merge: the
last explicitly present archived scalar wins across them. Empty or title-only
occurrences preserve an earlier archived scalar.
Titles independently use a nonempty valid annotation title, then the own-surface
summary title. Explicit empty annotation titles preserve their raw presence but
allow that fallback; corpus projection then supplies the first meaningful request
or canonical filename ID.

SQL enum/index columns accept INTEGER values losslessly. Optional enums retain
three distinct states: integer, NULL/absent and malformed. A malformed enum is
diagnosed while independently valid identities and indexed protobuf facts remain
available. Steps/generators need an INTEGER index for row identity; malformed or
missing required indexes reject that unidentifiable row. Trajectory metadata
blob IDs can remain explicitly absent. These rules do not coerce textual enum
names or floating-point numbers into integer facts.

Antigravity sessions, including zero-step databases, enter the shared corpus.
Session creation uses trajectory creation or first step creation; session end
uses latest completion or latest creation. Explicit user-input steps start turns;
pre-prompt steps have no display turn. A turn's end is its latest member completion,
remaining unknown when no completion exists, even when the next prompt closes it.
Errors take precedence over cancellation/interruption. Active statuses keep only
the final turn open; earlier active turns are completed. Open turns use the shared
two-hour quiet rule with the latest step creation/completion timestamp. Cleared,
invalid, unspecified and unknown statuses default to completed.

An explicit SQL type/status integer wins. If SQL is absent or invalid, a present
payload type/status scalar supplies that fact; absent payload scalars never become
an invented proto3 default. Conflicting explicit SQL/payload enums diagnose, and
the SQL fact wins. User-input submessage presence alone does not create a turn.
Nested singular messages merge before their scalar and repeated fields are read.
Prompts prefer user_response, otherwise joined text items; images include image
media. Answers use the last nonempty planner response, with modified-response
fallback. Planner thinking and generator/system prompts never enter the page.

Planner tools map shell/edit names to the shared counters. MCP calls use their
ServerName/ToolName JSON arguments, and execution tool IDs determine failed
counts. Malformed arguments diagnose while retaining the session and other tools.
Workspace file URIs are percent-decoded; invalid schemes/escapes diagnose.
Recorded git root and branch are retained and participate in shared workspace
resolution. Parent links stay within Antigravity, without invented spawn links;
source-marked subagents lacking a parent remain visible as orphans.

The page offers an Antigravity source filter, APP/CLI/IDE tags and Copy session
ID only. Source status, legacy exclusions, ignored environment remedies and each
database's surface/status/reason appear in the footer. Each database disclosure
retains its own open state. Usage includes generator and step records plus all
retries, including cleared/checkpoint steps. Trajectory metadata keys may be
opaque TEXT, INTEGER or NULL; TEXT remains source provenance, while numeric
step/generator indexes retain their strict integer contract. Valid metadata
supplies creation, workspace and provider-local parent facts regardless of key
type. Identity copies merge globally by
component maximum; the first discovered session/turn owns the merged unit.
Unmatched/pre-prompt usage remains outside displayed turns. Every composition
rebuilds session/turn/bucket summaries, including empty sessions.

The reader emits source counts/status/reasons, ignored environment names and
diagnostics alongside corpus sessions and capability-gated UI actions. Model
attribution uses response slug, meaningful usage enum, step chat_model_name then
model_name, most recent attributed conversation model, or an unattributed marker.
Pricing uses independently available bundled/catalog estimates with Antigravity
identities, normalized effort/routing suffixes and unknown-model unpriced notes.
The moving gemini-pro-default alias assumes gemini-3.1-pro-preview; Vertex-only
models remain unsupported/unpriced. Raw system
prompts and planner thinking never enter page/runtime output. No Antigravity
cache is written. Absent/disabled input alone does not initialize the runtime;
a reportable database error can initialize a diagnostic-only page.

The offline page opens on month to date (MTD). The period buttons are MTD, QTD
(quarter to date), YTD (year to date), rolling 7D/30D/90D, ALL and Custom; the
choice persists as `p` in the URL hash. "Now" is the snapshot time shown as
"data as of", not the time the page is viewed. The period dial beside the
buttons names the dates on screen and steps MTD by month, QTD by quarter and
YTD by year; `o=-N` in the hash records N steps back. A past month, quarter or
year covers the whole period and its KPI deltas compare it with the whole
previous one. The current period compares with the same elapsed span of the
previous one. Choosing a period button always returns to its current period,
so pressing MTD after stepping back returns to this month. Custom shows two date inputs in the dial,
pre-filled with the range that was on screen. Its arrows shift the range by its
own length. Rolling periods and ALL have no steps. The back arrow stops once the
window starts at or before the earliest session. The forward arrow stops at the
current period, or for Custom once the range reaches the snapshot day. `[` and
`]` step back and forward unless focus is in a text field.

The page defaults to all sources. Its All/Codex/Claude/OpenCode/Antigravity segmented
switch persists as `src=all|codex|claude|opencode|antigravity` in the URL hash and retains the
other filters. Switching away from a selected reader's provider closes that
reader. Missing legacy provider fields mean Codex. Source filtering applies
to overview totals, session lists, descendants and direct subagent links.
The snapshot log count always includes Codex and Claude logs, regardless of the
switch; accepted OpenCode and Antigravity database counts are shown separately. The footer
displays the embedded payload's release version (`colophon 0.5.0`).

Codex uses green, Claude blue, OpenCode violet and Antigravity pink. In All, KPI share rules and workspace
bars split by provider; calendar cells use the provider with the greater
selected metric (ties follow Codex, Claude, OpenCode, Antigravity order). Model, recent and list rows carry provider
marks. Costs retain each provider's independent availability; a known subtotal
also names unavailable providers. Absent/disabled sources remain selectable
with a no-data label and explain the checked paths or disabling flag.
The All footer includes absent-source details, Claude unknown-record diagnostics
and the start of Claude token data when later than the calendar's start.
The Claude boundary note appears only in Claude and All views.

A session's workspace is, in order: a matching `workspaces.json` alias; its
repository's normalized remote origin; its git root path; or its working
folder ("(no repo)"). Codex records the remote; for Claude and OpenCode, which
do not, Colophon reads `remote "origin"`'s first url from the repository's git
config (a linked worktree's `.git` file leads to the shared config). A working
folder that no longer exists is searched from its nearest existing ancestor,
so deleted worktrees join their repository and keep the path as subfolder.
Workspace bars put the full name above the bar and wrap long paths. Beside an
open reader, the session list can be resized by dragging or with the arrow
keys on its divider (Shift for larger steps; double-click resets). The width
is kept in this browser's `colophon.sessionListWidth` storage.

Workspaces has independent time/tokens and top 6/all scope controls when the
filtered list exceeds six rows. The end action expands the preview or returns
to the top six. Both collapse paths restore focus to the selected scope button
and bring an offscreen section start back into view. Changing metrics preserves
scope; lists of six or fewer omit both scope and end controls.

Reader disclosure controls use `show more` and `show less` for requests and
answers, including subagent answers. Expanded text taller than the viewport
also has `show less` above it; resizing the window or session-list divider
refits that action without changing expansion. Short unclipped text has no
toggle. Additional requests start behind `+ N follow-ups sent while it worked`;
when open, `hide N follow-ups` appears at both ends. Collapsing text or
follow-ups restores focus to its surviving toggle and returns an offscreen
block start to view, while an in-view start keeps its scroll position.

Footer diagnostic and database panels retain independent open states across
source and metric changes. Each native summary has a matching `hide` action
at the panel's end. Closing from either end restores focus to its summary and
returns an offscreen panel start to view; ordinary rerenders do not move focus
into the footer.

OpenCode's unsupported/unreadable views name database reasons. An expandable database
footer preserves successful, failed and skipped-preview entries even when a
sibling database succeeded. Structured diagnostics retain their contextual
fields, count-map sums and residual-session counts.

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
runtime state. Version is currently `colophon 0.5.0`.

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
| `--opencode-db PATH` | Select only this OpenCode database; expand tilde and resolve relative paths against cwd. Reject `:memory:`. |
| `--no-opencode` | Disable OpenCode discovery and reads before inspecting source paths. |
| `--antigravity-home PATH` | Select the Gemini root; expand tilde and resolve relative paths against cwd. |
| `--no-antigravity` | Disable Antigravity discovery and reads before inspecting source paths. |

OpenCode discovery defaults to `~/.local/share/opencode`; nonempty
`XDG_DATA_HOME` replaces `~/.local/share` (relative values resolve against cwd,
without tilde expansion). `OPENCODE_DB` selects the primary database relative
to that data directory, or as an absolute path. Empty `OPENCODE_DB` is a
reported invalid candidate; `:memory:` suppresses both the primary and default
`opencode.db`. Without a file flag, regular `opencode-*.db` siblings are added
in ascending normalized path order, plus a distinct default `opencode.db`
when primary is overridden. Normalized paths deduplicate, primary sessions
win duplicate IDs, and successful siblings remain usable after a source failure.
`opencode-next.db` is skipped even when explicitly selected: OpenCode migration
owns that preview database. Desktop-specific discovery is not verified.

Only structurally compatible v2 databases are read; legacy JSON, v1-only
schemas and incomplete/unfamiliar migrations are unsupported. A newer known-shape
migration produces an untested-schema warning. Database status and reasons
remain in `meta.sources.opencode.databases`; aggregate status prefers any
successful database, then unsupported, then unreadable, then absent. Disabled
is independent. Unsupported or unreadable candidates can alone generate a
diagnostic page. Empty directories, absent candidates and skipped previews
alone do not establish source presence. OpenCode contributes no parse cache
and does not cause an absent Codex cache to be opened during rebuild.

OpenCode cost availability describes the recorded-estimate engine. It remains
available independently of Codex history and Claude rates; missing request costs
remain unpriced and explicit zero stays priced zero. No OpenCode model catalog,
credential tables or unrelated key/value settings are read. Costs are OpenCode
catalog estimates, not invoices. Source session/project archive precedence is
reported as `archive_reason=session|project`; absolute source provenance is
`opencode_database`. Rows expose `capabilities` permitting only Copy session ID.
Continuation stays disabled: disposable CLI/database acceptance is unmet.
No empirical evidence currently establishes originating-database routing,
existing-service behavior or a verified CLI launch mode for `OPENCODE_DB`.
Copy session ID remains available for live, archived and subagent rows; OpenCode
offers no Codex links or Copy log path. Project-only archives show `ARCHIVED (PROJECT)`;
session archives show `ARCHIVED`, including when both archive flags are set.
Reader, turn, outside-turn and model tooltips identify OpenCode's recorded catalog
estimates without inventing rate-period warnings. Mixed-provider models retain
the other providers' real rate provenance, unknown-period and unpriced warnings.

OpenCode source counters describe deduplicated accepted database facts and
inserted display/accounting rows: excluded cross-provider collisions do not
count as sessions or requests; subagents include orphan children. Requests cover
accounting-eligible assistant/finished-compaction messages. Inherited-message
counts cover all copied rows regardless of kind; they contribute no requests,
tokens or costs. Diagnostic lists preserve session/database/reason context; unknown
types and missing usage are count maps. Residuals are keyed by session and keep
raw `input`, `output`, `reasoning`, `cache_read`, `cache_write`, nullable `cost`,
nullable millisecond `date` and `date_basis=session_start`. Shortfalls preserve
the same fields plus a reason. Residual dating is a display convention; it
does not prove event ownership or timing. Stderr summarizes list lengths,
count-map sums and residual-session counts and prints per-database reasons,
including skipped previews, even when aggregate status is ok. Finite request
costs that overflow a provider total make that CLI total unavailable with a
contextual diagnostic while preserving valid session costs. Page totals, daily
cells, model totals and reader/list cost sums also check finite addition. An
overflowing summary remains unavailable after later additions; the footer names
the affected provider, day, model or reader. Other valid summaries stay visible.

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
`--no-open`, `--no-claude`, `--no-opencode` and `--no-antigravity`; `--no-op` matches both
`--no-open` and `--no-opencode`. `--o` matches `--offline`, `--output` and
`--opencode-db`; `--claude` is ambiguous between the two Claude
path flags. `--c` is also ambiguous between Codex and Claude path flags.
Use the full flag names when scripting.

Presence is decided before creating the runtime home. A readable source
directory, a usable Claude history entry or a reportable OpenCode/Antigravity candidate
is sufficient. With no source,
exit 1 names the Codex home, Claude roots/history, OpenCode paths and Antigravity home checked, and
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

Metadata, priority trace and OpenCode SQLite databases are opened read-only with
normal SQLite coordination. Metadata and OpenCode use a 1,000 ms busy timeout; priority
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
