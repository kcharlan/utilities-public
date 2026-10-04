# Colophon — Design Spec

Status: approved design; user review complete; revised after review round 1 and its sanity check; amended by the implementation plan on 2026-10-03 · Date: 2026-10-03

Colophon is a local, read-only explorer for OpenAI Codex session logs. One
command compiles the logs under `~/.codex` into a single self-contained,
offline HTML page and opens it. The page starts with an overview dashboard
(totals, heat maps, breakdowns); every element drills into a session list,
and the list opens a summary-level session reader.

**Why the name.** In a hand-made codex, the *colophon* is the closing note that
records who made the book, when, where and how. Colophon writes that note for
your Codex sessions: when they ran, where they worked, what they used and what
they cost.

## 1. Scope

**In scope (v1).**
- Every session in `~/.codex/sessions` and `~/.codex/archived_sessions`.
- An overview dashboard, a filtered session list and a session reader.
- Token and cost accounting.
- One dark theme, built on theme tokens so a light theme can follow (§8.6).

**Non-goals (v1).**
- Transcripts, commentary, reasoning, command output and file contents.
  Opening the real session covers that need (§8.4).
- A server, a background daemon, or any write to `~/.codex`.
- Logs from other agents.
- Editing or deleting sessions.
- A light theme. It is the planned next release after v1 acceptance.

## 2. Delivery and command line

**Form.** A single-file uv launcher, `colophon/colophon`, using the repository's
canonical header with `dependencies = []` (Python standard library only). It is
deployed by direct copy to `~/Library/Scripts/colophon`, or to any directory on
`PATH`.

**Run.** `colophon` + Enter performs these steps:
1. Scan logs, taking unchanged files from the cache.
2. Read Codex metadata.
3. Revalidate prices.
4. Compile.
5. Write the page atomically.
6. Open it in the default browser.
7. Print a one-line summary and exit.

**Flags.**

| Flag | Effect |
|---|---|
| `--no-open` | Write the page; do not open a browser. |
| `--rebuild` | Discard the parse cache, reparse every log, and save the results as the new cache. Prices, price history and settings are untouched. |
| `--offline` | Make no network request; use the cached catalog and the price history. |
| `--refresh-prices` | Force a full, unconditional price-catalog download. |
| `--output PATH` | Write the page to PATH instead of the default. |
| `--codex-home PATH` | Read Codex data from PATH (default `~/.codex`). |
| `--version` | Print the version and exit. |

`--rebuild` builds the new cache in a temporary directory next to the old one,
and swaps it in only after every log has been parsed. If the rebuild is
interrupted (signal, crash, full disk), the old cache stays intact and the run
reports that the rebuild did not complete. `--rebuild` may be combined with
`--refresh-prices`.

`--offline` together with `--refresh-prices` is a usage error (exit 2).
`--help` is argparse's standard help. Its epilog documents both environment
variables and the runtime files.

**Version.** A single `__version__` constant using semantic versioning,
starting at `0.1.0`. It is printed by `--version` and stored in the page `meta`.

**Environment variables.** Both are documented in the README and in `--help`,
and both are covered by tests. There are no undocumented settings.

| Variable | Default | Purpose |
|---|---|---|
| `COLOPHON_HOME` | `~/.colophon` | Runtime home, per the repo's `<TOOL>_HOME` launcher rule. |
| `COLOPHON_PRICING_URL` | `https://models.dev/api.json` | Price catalog URL, for a mirror or a local test catalog. |

**Runtime home.** `$COLOPHON_HOME`, created with mode 0700. Every file in it is
written with mode 0600.

| Path | Purpose |
|---|---|
| `colophon.html` | The generated page. |
| `cache/` | Per-log parse records, plus the cache format version. |
| `pricing-cache.json` | OpenAI subset of the catalog, its ETag and fetch time. |
| `price-history.json` | The user's editable price-history ledger (§5.6). Created empty on first run. Curated entries live in the launcher and are never copied here. |
| `priority-turns.json` | Sticky memory of detected priority turns (§5.5), retained after trace rows are pruned. |
| `workspaces.json` | Optional workspace aliases. |
| `workspaces.example.json` | Synthetic template written on first run. Never read as configuration. |
| `perf-baseline.json` | Local throughput baseline. Written only by the local acceptance script, never by `colophon` (§11). |
| `parity/` | Local parity reports (§12.4). |

A page written with `--output PATH` also gets mode 0600.

**Exit codes.**
- `0`: success, including runs that skipped files (reported in diagnostics),
  runs with zero sessions (the page shows an empty state), and runs where
  the browser could not be opened.
- `1`: fatal. The Codex home is missing or unreadable, or the page cannot be
  written.
- `2`: usage error.

## 3. Data sources

Colophon reads every source read-only. SQLite databases are opened with
`mode=ro`.

| Source | Use |
|---|---|
| All non-hidden files with a case-insensitive `.jsonl` extension under `sessions/` and `archived_sessions/` | Primary data, including date partitions, flat files and recursive legacy layouts. A log under `archived_sessions` is archived. |
| `state_*.sqlite` (newest readable schema): `threads` | Titles, cwd, git data, archived flag, agent nickname/role/path, `rollout_path`. |
| `state_*.sqlite`: `thread_spawn_edges` | Authoritative parent → child edges, when present (§5.3). |
| `logs_2.sqlite`: `logs` | Priority-turn detection, following the upstream cold scan (§5.5). The file is under `--codex-home`. |
| `session_index.jsonl`, `.codex-global-state.json` | Additional title sources, in the title priority of §5.1. |

Database threads with no log file are counted in diagnostics only.

Discovery follows `listCodexSessionFiles`, `listCodexSessionFilesFlat` and
`listCodexLegacySessionFilesRecursive` in `CostUsageScanner.swift`
@ `3bbf6bc48` (2151–2187, 3283–3330), over all history. Paths and filesystem
identities `(device, inode)` are de-duplicated so overlapping discovery paths
or hard links do not count the same file twice. No `rollout-` filename prefix
is required.

**Recognized record types.** Each type is either *used* or *known and
ignored*. Any other type is counted per type for format-drift diagnostics
(§9).

| Record | Treatment |
|---|---|
| `session_meta` | Used. **The first `session_meta` in a file owns the session identity.** A later one is ancestor metadata and marks a copied (inherited) prefix. Same rule as the research extractor and upstream CodexBar. |
| `turn_context` | Used: model, effort, turn id. |
| `event_msg` `task_started` / `task_complete` / `turn_aborted` | Used: turn lifecycle, duration, time to first token. |
| `event_msg` `thread_settings_applied` | Known; ends an inherited prefix (§5.3). Not a tier source. |
| `event_msg` `item_completed`: `UserMessage`, `AgentMessage` | Used: requests and final answers (§5.1). |
| `event_msg` `item_completed`: `CommandExecution`, `FileChange`, `McpToolCall`, `WebSearch`, `ImageView`, `Extension` | Used: tool summary (§5.4). |
| `event_msg` `item_completed`: `SubAgentActivity`, `CollabAgentToolCall` | Used: subagent linking (§5.3). |
| `event_msg` `item_completed`: `Reasoning`, `ContextCompaction`, `Plan` | Known and ignored. |
| `event_msg` `token_count` | Used: tokens, fallback path (§5.5). |
| `token_usage_record` | Used: tokens, primary path (§5.5). |
| `response_item` `message` | Used for requests and answers only in turns that have no `item_completed` message items. |
| `response_item` `function_call`, `custom_tool_call`, `local_shell_call`, `web_search_call` | Used for the tool summary only in turns without structured tool items (§5.4). |
| `response_item` `tool_search_call` | Known; classed as plumbing, not a tool call (§5.4). |
| `response_item` `*_output`, `reasoning`, `tool_search_output` | Known and ignored. |
| `response_item` `agent_message`, top-level `inter_agent_communication_metadata` | Known and **never stored**. These are inter-agent messages. Their header lines are plain text; in every task brief observed during research, the payload was encrypted. |
| Top-level `world_state`, `compacted` | Known and ignored. |
| Top-level `realtime_item` | Used for voice transcript segments only: user segments as requests, assistant segments as spoken replies (§5.1). |
| Legacy `event_msg` `user_message` / `agent_message` | Supported for older Codex versions; absent from current logs. |
| A line with no `type` that carries usage (one-shot `codex exec` output) | Used: tokens, via the ported bare-usage handling (§5.5). Absent from the research logs; a fixture covers it. |

## 4. Compile pipeline

```
fetch catalog (may run alongside the scan)
scan files → parse each file (cached) → load metadata → assemble sessions
→ link subagents → resolve workspaces → record catalog rates in the ledger
→ account tokens → price → render HTML (data embedded) → atomic write → open
```

**Parsing.**
- Each log is read once, as a stream.
- A parse produces a compact per-file record: session facts, turns, kept text,
  tool counts, usage events and diagnostics.
- A log without `session_meta` still contributes usage as a separate
  `file:<path>` accounting unit (§5.1). Files sharing a session id retain a
  union of distinct usage rows while display facts come from one copy.
- **The cached record holds only time-independent facts.** That covers turn
  starts and ends as logged, whether the final line was partial, the scan-start
  mtime, and the raw usage events.
- **Recomputed on every run, never cached.** Anything that depends on how long
  ago the log changed is derived at assembly time from the scan-start mtime
  and the current snapshot time:
  - running vs abandoned turns
  - "still being written" vs "truncated" final lines
  - LIVE flags
  - running-turn intervals

  An unchanged log is a cache hit, yet its open turn still moves from running
  to abandoned once the quiet threshold passes.
- **Cache key.** Each record is cached, keyed on:
  - path
  - size
  - mtime
  - a fingerprint (hash) of the last 4 KB of the bytes actually read
  - the parser/cache version

  Size and mtime are the values `stat` returned **at scan start**, before the
  read. Values taken after the read are never used. A file that grows during
  the scan therefore no longer matches its cache key on the next run, and is
  reparsed. The fingerprint catches a log rewritten in place with the same
  size and mtime.
- Malformed lines are handled by §4.1. They are never silently dropped.

**Cache maintenance.**
- **A changed file is reparsed from the beginning.** Codex can rewrite logs, so
  continuing from a saved byte offset is not used in v1.
- **Moved files.** A log moved from `sessions/` to `archived_sessions/`
  appears under a new path. It is parsed there, and the entry for the old
  path is pruned.
- **Vanished files.** Cache entries for files that no longer exist are
  pruned.

### 4.1 Live sessions and crash damage

Colophon runs while sessions are in progress. A page is a snapshot "as of" its
build time. A later run picks up the final state of any session that finished
in the meantime, because its log changed and is reparsed.

1. **Consistent read.** Each file's size is noted when the scan starts, and
   only that many bytes are read. Bytes appended during the scan are left for
   the next run.
2. **Partial final line.** A final line without a newline that does not parse
   is classified by how long the log has been quiet. The quiet threshold is
   2 hours. It is a fixed constant (`LIVE_QUIET_HOURS`), not a setting; the
   README describes the behavior.
   - Modified within the threshold: *still being written*. Skipped silently,
     with no diagnostic.
   - Older: *truncated, likely interrupted* (crash debris). Skipped and
     counted in its own diagnostic category, separate from format problems.
3. **Fragment glued to a record.** A crash can leave a partial line, and a
   restarted Codex can append to it, so the fragment and the next record share
   one line. When a line fails to parse, the parser searches it for the start
   of a valid record (a `{"timestamp"` or `{"type"` object start) and parses
   from there. The fragment is dropped and counted as *recovered after
   truncation*. Only an unrecoverable line counts as *malformed*.
4. **Open turns.** A turn with a start and no end is classified as one of:
   - *Interrupted.* A later turn started in the same session. Its end is its
     last owned record before the later turn's start. That interval counts,
     and the turn is flagged.
   - *Running.* No later turn, and the log was modified within the quiet
     threshold. Its interval runs from the start to the snapshot time. It
     counts toward every time, token and cost total, flagged LIVE, and totals
     show "includes n running".
   - *Abandoned.* No later turn, and the log has been quiet longer than the
     threshold. Excluded from time totals and flagged abandoned. Its tokens
     and cost still count, because they were spent.
5. **Counter restart.** A cumulative token counter that restarts after a crash
   is handled by the ported interleaving rules (§5.5, fallback rule 3).
6. **Empty or header-only logs.** Skipped and counted. Not an error. A log
   with usage but no `session_meta` is counted instead (§5.1).
7. **Colophon's own interruption.** The page, the cache and the price-history
   ledger are always written via temp file + rename. An interrupted run leaves
   the previous versions intact.

Fixtures exist for each case (§12.1).

**Rules carried over from the research extractor.** The extractor is a
private research script, not part of this repository. Every rule taken from
it is restated in full in this spec:
- title priority (§5.1)
- timestamp provenance, collapsed timestamps, turn construction and duration
  (§5.2)
- inherited-prefix detection (§5.3)

The implementation must not depend on access to the extractor.

**Message deduplication** keeps the original semantics:
- **Duplicate:** same role and text, from a *different* record family, with
  compatible turn ids, within ±10 s.
- **Not a duplicate:** two identical messages from the *same* family. For
  example, the user sending the same text twice.
- **Survivor:** the copy from the higher-priority family is kept:
  `item_completed` item, then `event_msg` message, then `response_item`.
- **Complexity.** The original compares all pairs (quadratic). Colophon must
  be linear or n·log n. Index candidates by (role, text hash), then check the
  family, turn and ±10 s conditions only within each candidate list.

## 5. Domain rules

### 5.1 Sessions, titles and text

**Session types.**
- A session is identified by its first `session_meta` id. Multiple files
  sharing that id follow the copy rules below.
- "Your sessions" have no subagent parent. Subagents are nested under their
  parent.

**Logs without `session_meta`.** Their tokens count, as in CodexBar. Each
file is its own accounting unit, keyed `file:<path>` (`codexUsageRowKey`,
`CostUsageScanner+CacheHelpers.swift` @ `3bbf6bc48`, 497–512), never merged
with another file and never entered into the fork-parent index. For display
only, use the filename's trailing UUID, otherwise its stem. Flag the row
`no_session_meta`.

**Files sharing a session id.**
- Fallback rows are de-duplicated across copies with upstream
  `uniqueCodexRows` / `codexCrossFileRowKey`
  (`CostUsageScanner+CacheHelpers.swift`, 497–555), so the union of distinct
  rows counts. Primary records are de-duplicated by `(thread_id, response_id)`.
- Display facts (turns, requests, title and live state) come from the copy
  with the newest mtime, with ties broken by ascending path.
- Fork-parent lookup uses the newest-mtime copy, with the same tie-break.
  This is a user-approved difference from upstream's incremental file-index
  selection; the row union still follows upstream.
- `duplicate_session_ids` lists every **pre-pass** id found in more than
  one file. That is the id used by the fork-parent index. Its first eligible
  metadata record is subject to upstream's 256 KiB line limit, so it can
  differ from the true-first metadata id used for display. The diagnostic
  lists both when they differ.

**Display title.**
- **Your sessions:** the inherited title priority. Database name, then session
  index, desktop title, rollout title, database title (non-agent), first user
  request, then database first message. The title is cut to its first line at
  about 80 characters, and the full title is kept for expansion.
- **Subagents:** a humanized agent path plus the nickname, for example
  `review task · AgentName`.

**Requests.** Every user request in a turn is kept, including follow-ups sent
mid-turn, each with its time.

Each text part of a user message is classified in this order:
1. **Wrapped request.** The part begins with a context wrapper and contains a
   request heading: a line `## My request:` or `## My request for Codex:`.
   Only the text after the heading is kept; the context before it is dropped.
   Context wrappers:
   - `# Files mentioned by the user`
   - `# Files pasted by the user`
   - `# Browser comments`
   - `<in-app-browser-context`

   A wrapper part with no request heading is dropped as context.
2. **Injected content**, dropped. Parts that begin with:
   - `# AGENTS.md`, `<environment_context>`, `<INSTRUCTIONS>`,
     `<external_codex_apps_open_page>`, `<permissions instructions>`,
     `<recommended_plugins>`, `<skills_instructions>`,
     `<codex_apps_open_page_instructions>` (the research extractor's set)
   - `<realtime_delegation>`, `<skill>`, `<turn_aborted>` (added here)
3. **Answers to agent questions.** A `<send_user_message_question_reply>`
   part holds the user's answers to the agent's questions. It is kept as a
   request marked "answer", with the wrapper tag removed.
4. **Image parts** (`<image …>`, `</image>`) are dropped. A message that had
   images shows "+ n images".
5. **Everything else** is kept as the request.

**Voice.** `realtime_item` transcript segments alternate between user and
assistant.
- **Grouping.** Consecutive *user* segments, with no assistant segment between
  them, form one voice request. Each assistant segment run ends the current
  request.
- **Placement.** A request goes to the turn that contains its first segment.
  - A request before the first turn, or between turns, goes to the next turn
    that starts, under the label "before this turn". It is not shown as a
    follow-up.
  - A request after the last turn goes to that turn as a follow-up.
  - In a session with no turns, requests appear at session level.
- **Spoken replies.** Consecutive assistant segments form one spoken reply.
  - **Placement.** A reply is placed with the voice request immediately
    before it, so a question and its answer stay together. That includes
    replies spoken after a turn's `task_complete`.
    - With no preceding voice request, the reply goes to the most recent turn
      that started before it.
    - With no such turn either (a reply before the first turn, with no
      request), the reply is dropped, unless the session has no turns, in
      which case it appears at session level.
  - A turn with no `final_answer` uses as its answer the last reply placed
    with a request **inside** that turn, never a reply attached to a "before
    this turn" request. It is marked "voice reply". The last reply is chosen
    because earlier ones are often fillers.
  - A turn that has a `final_answer` shows only that.

The wrapper, heading and prefix lists are single constants, and tests assert
each list in full. Fixtures cover every wrapper with and without a heading.

**Final answer.** The turn's last `final_answer`-phase agent message. If there
is none, the voice reply above is used, if any. Otherwise the reader shows
"no final answer recorded".

**Never stored.** Commentary, reasoning, command output, patch contents, MCP
arguments and results, inter-agent messages (including subagent task briefs),
and developer/system messages.

### 5.2 Turns and time

**Event timestamps.** Each record's time is chosen in this order, and the
source is kept as its provenance:
1. Embedded clocks, which survive some log rewrites. Which ones are checked
   depends on the payload type:

   | Payload | Keys checked, in order |
   |---|---|
   | `task_started` | `started_at_ms`, then `started_at` |
   | `task_complete`, `turn_aborted` | `completed_at_ms`, then `completed_at` |
   | anything else | `completed_at_ms` |

   - `_ms` keys are epoch milliseconds; the others are epoch seconds.
   - The first valid key wins.
   - **Exception:** a seconds-precision key that is strictly less than 2 s from the
     wrapper `timestamp` yields the wrapper time, because the wrapper has
     sub-second precision. Its provenance is then `record_timestamp`.
2. Otherwise, the wrapper `timestamp`, with provenance `record_timestamp`.

**Collapsed timestamps.**
- A log is *collapsed* when it has more than one wrapper `timestamp` and all
  of them are identical. A rewritten log can stamp every record with one
  time.
- In a collapsed log, any time whose provenance is `record_timestamp` is
  unreliable:
  - message times with that provenance are flagged
  - the user-message span is not computed when any user message has an
    unreliable time
  - durations follow the rules below
- Open item: logs with only two distinct wrapper times (§15).

**Turn construction.**
- A `task_started` opens a turn, keyed by its `turn_id`. If there is no
  `turn_id`, the key is `turn-<n>`.
- Records between a start and its end belong to that turn when they carry no
  `turn_id` of their own.
- A `task_complete` closes the turn as *completed*, and a `turn_aborted` as
  *aborted*.
  - If the turn has no start but the end carries an embedded `started_at`,
    that becomes the start.
    Completion-only recovery requires the absence of a `task_started`
    record. A start record with no usable clock still opens the turn and keeps
    its record position; its logged start time stays unknown and it does not
    receive `start_from_completion`. Duration follows the rules below,
    including reported duration when present.
  - `duration_ms` and `time_to_first_token_ms` (when present and ≥ 0) are kept
    as the reported duration and time to first token.

**Turn duration.**
1. **Collapsed and unreliable: unknown.** If the log is collapsed, there is no
   reported duration, and both the start and the end have provenance
   `record_timestamp`, the duration is **unknown** and flagged.
2. **Reported duration.** If a reported duration exists and the turn has an
   end, use it when any of these hold:
   - there is no start
   - the log is collapsed
   - the end's provenance is `completed_at`

   Then start = end − reported, and the duration is the reported value.
3. **Start/end difference.** Otherwise, if start and end both exist and
   end ≥ start, the duration is end − start.
4. Otherwise the duration is unknown.

Turns with an unknown duration are excluded from active time and flagged.

**Status** is completed, aborted, interrupted, running or abandoned. The last
three are the open-turn cases of §4.1.
- **Active time** is the union of the intervals of completed, aborted,
  interrupted and running turns. Running turns end at the snapshot time.
  Abandoned turns are excluded and flagged.
- **Span** (first to last owned record) and idle gaps are reported separately.

**Time totals.**
- **"Your active time":** the union across your sessions only.
- **"Agent time":** the sum of subagent active time. It is shown separately and
  never added to your time.

**Time zones.**
- The page embeds UTC instants only.
- The browser converts them to the viewer's local time zone at view time,
  using `Intl`/`Date`. Day grouping, midnight splits of a turn across two
  local days, the hour × weekday grid and DST handling all happen there, from
  a single shared helper.
- `meta.generated_tz` is informational.

**Provenance flags.** Collapsed wrapper timestamps, reported-only durations,
and aborted, interrupted, running or abandoned turns each carry a flag. The UI marks every figure
they affect.

### 5.3 Subagents

**Child → parent session**, in priority order:
1. `thread_spawn_edges` (SQLite).
2. `session_meta.source.subagent.thread_spawn.parent_thread_id`.

**Forks.**
- `forked_from_id` on a subagent equals its parent and means "started with a
  copy of the parent's context". It is shown as a **forked** badge on the
  subagent, not as a separate edge.
- A `forked_from_id` on a session that has no subagent parent is shown as a
  "forked from <session>" link in the reader. None were observed; the case is
  supported anyway.
- Inherited records are excluded from every **non-token** metric. Tokens
  follow §5.5 and its ported fork rules.

**Inherited-prefix detection.** Restated from the research extractor.

*Setup.*
- `created_at` is the first `session_meta` payload `timestamp`, or that
  record's event time (§5.2) if the payload has none.
- A record whose event time is earlier than `created_at` is always inherited.

*Path A: the first `session_meta` has `forked_from_id`.* Scan the file's
`event_msg` `task_started` and `task_complete` records in order:
1. **Synthetic starts.** A `task_started` whose `turn_id` begins with
   `rollout-` is remembered as (record index, `started_at`) and skipped.
2. **Ownership.** Any other such record is **owned** when its `turn_id` is a
   UUIDv7 whose embedded creation time (the first 48 bits, in ms) is at least
   `created_at` − 1 s. Two adjustments, applied in this order:
   - It is **not** owned if its `started_at` (epoch seconds) is earlier than
     `created_at` − 1 s.
   - Then, a `task_started` whose `turn_id` is not a UUIDv7 **is** owned if
     its wrapper time is at least `created_at` + 1 s. This overrides the
     previous adjustment.
3. **Boundary.** At the first owned record:
   - If it is a `task_complete` whose `started_at` equals a remembered
     synthetic start's `started_at`, the boundary is the index of the **last**
     such matching synthetic start (*synthetic start verified by completion*).
     Both clocks must be finite JSON numbers (`int` or `float`, not `bool`)
     of epoch seconds, compared numerically. Missing, null, non-numeric,
     boolean and non-finite clocks never match, including each other.
   - Otherwise the boundary is this record's index (*own lifecycle*).
4. **Result.** Records strictly between index 0 and the boundary are
   inherited.
5. **No owned record found.** The session is flagged **history boundary
   unresolved**. It is listed with its title and links, but with no turn,
   time or request metrics. Its tokens and cost are shown only when the
   token accounting (§5.5, either path) attributes owned usage to it. Turn
   metrics are withheld because its own turns cannot be separated from the
   copy. It is counted in diagnostics.

*Path B: no `forked_from_id`.*
- A second `session_meta` with a different id starts an inherited run.
- The run ends at the first of:
  - a `thread_settings_applied`
  - a record whose payload `thread_id` equals the session id
  - an own `task_started`: its `started_at` is at least `created_at` − 1 s,
    or, if it has no `started_at`, its event time is at least
    `created_at` + 1 s
- The record that ends the run is itself **not** inherited.

**Child → parent turn(s).** A subagent has one *spawn turn* and zero or more
*interaction turns*, because a parent can send it follow-up tasks in later
turns. The spawn turn is the first of these that succeeds; the method used is
recorded on the link:
1. The parent's `SubAgentActivity` with `kind: "started"` whose agent thread
   id is the child, in the turn that contains it.
2. A spawn call in the parent whose output `task_name` equals the child's
   `agent_path`. A spawn call is a `function_call` with name `spawn_agent`
   in namespace `collaboration`. If the same task name was spawned more than
   once, the latest spawn before the child's start wins.
3. `token_usage_record.root_turn_id` in the child, **only when the child's
   depth is 1**. At depth ≥ 2 it names the root session's turn, not the
   direct parent's.
4. Time containment: the parent turn whose interval contains the child's
   start. Marked **inferred**.

Interaction turns are every other parent turn containing a `SubAgentActivity`
(`interacted`) for the child, or a follow-up/send-message call targeting it.
The reader lists the subagent under its spawn turn and shows "also used in
turn n" on interaction turns.

**Descendants and orphans.**
- "A session's subagents" means all of its descendants at every depth. A
  depth-2 subagent nests under its depth-1 parent.
- A subagent whose parent log no longer exists is listed as a top-level row
  flagged **orphaned subagent**, and counted in diagnostics.

### 5.4 Tool summary

Counts are per turn, rolled up per session and per subagent. The categories
are fixed.

**Precedence (prevents double counting).** Current logs record each call
twice: once as a structured `item_completed` item and once as the raw
`response_item` call (or inside a JS `exec` block).
- **For each turn:** if the turn has any structured tool item, count only
  structured items.
- **Otherwise:** count from the raw call forms.

Tests assert that a turn recorded in both forms is counted once.

| Category | Structured source | Raw / legacy source |
|---|---|---|
| Shell commands | `CommandExecution` | `function_call` `exec_command` / `shell` / `local_shell_call`; JS `tools.exec_command(` |
| File edits | `FileChange` (number of files changed) | `custom_tool_call` named `apply_patch`; JS `tools.apply_patch(` (one per call). A `custom_tool_call` named `exec` is a JS wrapper, never a file edit. |
| MCP tools, grouped by server | `McpToolCall` (server, tool) | `function_call` with namespace `mcp__<server>`; JS `tools.mcp__<server>__<tool>(` |
| Web searches | `WebSearch`; `Extension` with `kind: "web.search"` | `web_search_call`; `function_call` / JS `web.run` / `tools.web__run(` |
| Image views | `ImageView` | `view_image` / JS `tools.view_image(` |
| Other | any other `Extension` kind except `clock.sleep` (e.g. `image_gen.generation`) | any remaining non-orchestration call; names shown in the drill-down |

**Display.** Shell commands show a count and, when exit codes are recorded, a
failed count in amber. For example "N shell commands · k failed". Individual
programs (`ls`, `git` …) are deliberately not distinguished.

**Not tool calls.** Orchestration and plumbing:
- spawn / follow-up / send-message / interrupt / list / wait for agents (any
  namespace)
- `update_plan`, `request_user_input` (and `_async`), clock sleep in any form
  (including `Extension` `clock.sleep`), terminal `write_stdin`, JS-cell
  `wait`, `tool_search_call`

Subagents have their own section in the reader. Tests enumerate this list.

### 5.5 Tokens

Each usage unit, from either path below, carries a model, a UTC instant and a
service tier.

**Model in force.** As upstream tracks `currentModel`, the model in force is
set only by `turn_context` records (upstream `codexTurnContextModel`), read in
this order:
- `payload.model`
- `payload.model_name`
- `payload.info.model`
- `payload.info.model_name`

For each `turn_context` record:
- The first of those four fields whose value, after trimming whitespace, is
  not empty becomes the model in force. Blank fields are skipped.
- If at least one field is present but every present field is blank, the
  model in force is cleared.
- If all four fields are omitted (a non-string value counts as omitted), the
  model in force is unchanged.

The model in force is also reset to none at a subagent's owned suffix (see
"Forks" under the fallback path).

**Model per unit:**
- **`token_count` event:** the model in force. If there is none, the event's
  own model: the first non-blank, trimmed value of `info.model`,
  `info.model_name`, `payload.model`, then the top-level `model`. If there is
  none of those, `unknown`. This is upstream `handleTokenCount`.
- **`token_usage_record`:** the model in force, otherwise `unknown`.
  Colophon's own path; see "Primary path".
- **Bare usage line:** the order given under the fallback path.
- **`unknown`** is never priced (upstream `resolvedCodexPricing` returns
  nothing for it), and is shown as an unpriced model.

**Service tier: upstream trace detection plus sticky memory.** A usage unit
is priority exactly when its turn id is detected or stored as a priority
turn. This applies to both token paths, matching upstream's
`row.turnID.flatMap { priorityTurns[$0] }`. Other usage is standard.
`thread_settings_applied` only ends an inherited prefix; it supplies no tier.

**Detection (port).** On every invocation, cold-scan
`<codex-home>/logs_2.sqlite`, table `logs`, with no memo, cursor, anchors or
pruning. Open it read-only with
`sqlite3.connect("file:…?mode=ro", uri=True, timeout=0.25)`, matching upstream's
250 ms busy timeout. Port `resolveCodexPriorityTurns`' cold-scan semantics
from `CostUsageScanner+CodexPriority.swift` @ `3bbf6bc48`:

- `accumulateCodexPriorityTurns` and `storePendingCodexCompletedModels`
  (889–971), including the pending-completion FIFO cap of 4096 turn ids;
- `filteredResolvedCodexPriorityTurns` / `latestCodexCompletedModel`
  (440–459), selecting the highest-rowid retained completed model;
- `parseCodexPriorityTraceRow`, `parseCodexPrioritySubmissionRow`,
  `parseCodexCompletedTraceRow`, `value(named:in:)` and `quotedValue(named:in:)`
  (1020–1098);
- the non-indexed query from `codexPriorityAccumulationPlan` (973–1005):
  `rowid > 0`, `ts >= 0`, request/completion/submission body filters, ordered
  by rowid, over all history.

The detected model is the highest-rowid retained `response.completed`
model for that turn, otherwise the latest priority request model. Pending
completions before priority detection follow upstream's FIFO retention;
completions for an already-priority turn are retained for that turn. The
trace path follows `--codex-home`, a user-approved difference from upstream's
fixed `~/.codex` path.

**Sticky memory (Colophon addition).** Merge detected turns into
`$COLOPHON_HOME/priority-turns.json`, written atomically at mode 0600:

```text
{"schema": 1, "turns": {turn_id: {"thread_id": str or null,
  "model": str or null, "timestamp": str or null, "first_seen_ms": int}}}
```

Never remove stored turns. A database entry replaces the stored entry
except for `first_seen_ms`, which stays unchanged. Entries absent from the
database remain. Usage older than both the trace database and the first
Colophon run stays standard-priced; the README states this limitation.

**Priced model (port).** `codexPriorityPricingModel` and
`codexResolvedCostUSD` (`CostUsageScanner+PricingRows.swift`, 4–45, 87–95)
use the priority turn's **raw** model when `codexAPIFastMultiplier` knows
that model after normalization, otherwise the usage unit's own model. The
fixed upstream model set controls this override decision only; the actual
multiplier and cap come from price history (§5.6). Priority cost is
`max(priority cost, standard cost)` when a priority cost exists, otherwise
standard cost, both resolved for the priced model.

**Source selection, per turn.**
- If the turn has any `token_usage_record` belonging to this session, use
  those records.
- Otherwise use `token_count` deltas.

**Attribution (both paths).** Every usage unit goes to its session, its model
and tier, and its 15-minute bucket, always. It also goes to its turn, but only
when that turn is a displayed, owned turn under §5.3.
- A unit on a record §5.3 treats as inherited, or outside any displayed turn,
  still counts toward the session's totals.
- The reader shows that usage on a line "tokens outside displayed turns".
- **Invariant:** the turn cards plus that line equal the session's **own**
  total, which excludes its subagents. Subagent usage appears in the
  subagent rows. The session's overall total is its own total plus all
  descendants' totals (§5.9). Tests assert both equalities.

**Primary path: `token_usage_record`.** This is **Colophon's own design, not a
port**. Upstream never reads these records; it counts `token_count` for every
turn. Colophon prefers them because each is an exact per-response figure. The
difference is a recorded deviation (§15), and parity will show it.

- **Approved evidence (2026-10-03).** In the research period September 4
  through October 3, the per-response records exceed CodexBar's daily totals
  by 22.24M input tokens (0.65%) and 387K output tokens. Almost all is context
  compaction: Codex logs those calls as `token_usage_record` directly before
  `compacted`, without a corresponding `token_count`. Adding the 94 calls
  exactly explains 19 of 25 days; four more differ by one call across
  midnight. About 1.26M input tokens on September 4 and 6, under 0.04% of
  the period, remain unexplained. The user set that remainder aside; revisit
  it only if parity shows the gap growing.
- Each `(thread_id, response_id)` is counted once, including across copies.
- Only records whose `thread_id` equals the session's own id are counted. The
  real-data audit found no foreign records, so this guard is exercised by
  fixtures.

**Fallback path: `token_count`.** This is a behavioral port of upstream's
per-file Codex token accounting, not a new algorithm. It lives in
`CostUsageScanner.swift` and `CodexSubagentRolloutShape.swift` @ `3bbf6bc48`.
CodexBar is public, so the implementer ports from that source and cites it in
`token_rules.md`. **The upstream code is authoritative.** The rules below are
orientation only; where they disagree with upstream, upstream wins.

**Port targets:**
- `parseCodexFileCancellable` and its nested `handleTokenCount` /
  `commitDelta`: the per-event billed deltas.
- `CodexTotalsTracker`, and the helpers `codexShouldPreferTotalDelta`,
  `codexLooksLikeStaleRegression`, `codexTotalDelta`,
  `codexContainedTotalDelta`, `codexDivergentTotalDelta` and
  `codexPostLatchEventDelta`.
- **Fork handling:** `inheritedTotals(for:atOrBefore:)` (which uses
  `CodexSnapshotAccumulator` to compute a parent's totals at the fork point),
  `raiseInheritedBaselineIfContinuedCounter`, `configureForkAccountingIfReady`,
  and the related local state in `parseCodexFileCancellable`
  (`remainingInheritedTotals`, `adjustedLastDelta`,
  `hasUnresolvedForkBaseline`, `suppressUnownedCopiedPrefix`), plus the
  subagent owned-suffix reset (`subagent_history_start_ordinal`).
- **Fork baseline:** `CodexSubagentRolloutShape`.
- **Bare usage lines:** `handleBareUsage` and `codexBareUsage`. These are
  one-shot `codex exec` usage lines that have no `type`, ported so they are
  counted, not reported as unknown records. As upstream, they bypass the
  `token_count` state machine. They follow the per-turn source selection like
  fallback usage, so they are discarded for a turn that has `token_usage_record`
  usage. A bare line outside any turn has no selection to apply and always
  counts.
  - **Its model**, as upstream `handleBareUsage`:
    1. the line's own model, checked in this order: line `model`, line
       `model_name`, `data.model`, `data.model_name`. Values are trimmed and
       blank values skipped.
    2. otherwise the model in force (defined above)
    3. only if neither exists, `unknown`, which is unpriced
- **Note:** `CodexSnapshotAccumulator.apply` is **not** the per-event billing
  logic. It only builds a parent's snapshot totals.

The port is complete when the parity script (§12.4) agrees with CodexBar, or
every difference is recorded.

**Upstream rules, for orientation.** In the non-fork case, for each
`token_count` event:
1. **Repeat.** A cumulative total identical to one already seen counts zero.
2. **Stale regression.** A total that fell back by roughly one recent increment
   is stale and counts zero.
3. **Interleaving.** A total with any component below the running watermark
   latches *interleaved* mode. From then on, deltas are contained against the
   watermark and the counted totals. This handles counter drops and restarts
   after a crash.
4. **Normal case.** The counted delta is the event's `last_token_usage`. The
   total-derived delta replaces it when all of these hold:
   - a baseline exists (the tracker watermark, otherwise the raw totals
     baseline)
   - the current total is ≥ the baseline in every component
   - the total delta is ≤ `last` in every component
   - no divergence has been seen
5. **Total only.** An event with a total but no `last` counts the total delta,
   which is contained once latched, or computed by `codexDivergentTotalDelta`
   once divergence has been seen.

**First event and divergence.**
- No previous totals exist at the first event, so its counted delta is its
  `last_token_usage`. The raw baseline becomes its `total`.
- If that first `total` differs from its `last`, counted and raw totals
  diverge immediately. Divergence is then set for the rest of the file, which
  disables rule 4's total-delta preference.
- Some real logs start this way, so the port must reproduce it exactly.

**Forks.** A file with `forked_from_id` uses upstream's totals-only fork
accounting:
- Subtract the parent's inherited totals at the fork point.
- Trim `last` by the remaining inherited totals.
- Raise the baseline when a continued counter proves it.
- Suppress rows while the fork baseline is unresolved, and suppress any
  unowned copied prefix.
- Reset at the subagent's owned suffix.

**Parent-log dependency.** It follows upstream `configureForkAccountingIfReady`:
- **Independent counters, or a local owned-suffix boundary:** the fork is
  accounted without the parent, and its usage counts even if the parent log
  is missing.
- **Otherwise:** the fork needs its parent's parse record. The dependency is
  recursive when the parent is itself a fork. The parent's prefix up to the
  fork point never changes, so the dependency is stable.
  Colophon resolves parents on demand regardless of file order. This is the
  approved fork-of-fork difference (§15): upstream's production scan order
  can leave the `b10` chain unresolved, whereas Colophon resolves it.
- **Parent log missing, or the fork timestamp missing or unparseable:** the
  fork baseline is unresolved, as upstream returns it. The fork's
  fallback-path usage is suppressed with the diagnostic "fork baseline
  unavailable".

**Inputs and scope.**
- **All events go in.** The ported state machine receives **every**
  `token_count` record in the file, in order, including records in the
  inherited prefix, exactly as upstream does. Upstream's fork rules, not the
  §5.3 inherited-record exclusion, decide owned token usage on this path.
  §5.3's exclusion still governs every non-token metric.
- **Selection is per turn.** The state machine always runs over the whole
  file, which keeps its baselines correct. The per-turn source selection
  above then decides which counted deltas are used:
  - **Turns with a `token_usage_record`:** their counted deltas from
    `token_count` are discarded.
  - **Turns without one:** their counted deltas are used. For example, an
    aborted turn that has only a `token_count` in a file whose other turns
    have records.
- **Components:** input, cached input, output and reasoning output. Upstream
  does not track cache-write on this path, so it is taken as zero.

**Pricing uses the counted deltas.** The counted delta components are the
token counts passed to the §5.6 formula, and the long-context test uses the
counted input delta.

**Provenance.** `colophon/docs/token_rules.md` lists every CodexBar-derived
token and pricing rule with:
- the upstream file
- the function
- the upstream commit (`steipete/CodexBar` `origin/main`, currently
  `3bbf6bc48`; never a custom-build commit)
- the decision: ported, adapted, or rejected with a reason

### 5.6 Pricing and price history

Every cost is computed from a **price history**: a dated record of rates per
model. A request is priced at the rate in effect at its own timestamp. Once a
model has history, a later price change never reprices earlier usage.

**Normative source.** Rate *resolution* (how a catalog entry becomes rates),
model normalization, the cost formula and the priority multiplier are ports
of upstream CodexBar, `CostUsagePricing.swift` @ `3bbf6bc48`:
- `resolvedCodexPricing`
- `normalizeCodexModel`
- the catalog lookup chain: `codexModelsDevLookup`,
  `codexModelsDevPricingTargets`, and in `ModelsDevPricing.swift`
  `ModelsDevProvider.pricing(modelID:)`, `ModelsDevModelIDNormalizer` and
  `ModelsDevModel.pricing` (which decides `isPriceable` and the 200,000
  `context_over_200k` threshold)
- `codexCostUSD`
- `codexPriorityCostUSD` / `codexAPIFastMultiplier`

The upstream code is authoritative. Where this section summarizes it, the
summary is orientation only; if the two disagree, upstream wins and the
difference is fixed in this spec. What this section *does* define
normatively is Colophon's own design: the dated ledgers, recording,
validation and the recorded deviations.

**Fetching.** The current-rate source is the catalog at
`COLOPHON_PRICING_URL` (models.dev by default). Prices are USD per 1M tokens.
- **Every run fetches the catalog before recording and pricing, including the
  first.** The fetch may overlap the log scan (§4).
  - It sends a conditional GET (`If-None-Match`). A 304 keeps the cached copy;
    a 200 replaces it, keeping only the `openai` provider subset.
  - Timeouts: 3 s to connect and receive response headers, and 30 s for a
    body download.
  - `--refresh-prices` forces an unconditional GET with the same 30 s budget.
  - `--offline` skips the fetch.
- A catalog model is usable only if the ported `ModelsDevModel.pricing` finds
  it priceable. That means it has a `cost` with both input and output;
  image-only models, for example, are not priceable.
- There is no bundled snapshot of current prices.

**The resolver.** `resolve(id, catalog)` takes a normalized model id for
ordinary usage; `resolve_rates(raw_model)` retains raw lookup only for the
priority override described below. It is
the port of upstream `resolvedCodexPricing`, **excluding its historical-rate
branch**, because history lives in the ledgers.
- **Catalog lookup.** It finds the catalog entry through the ported lookup
  chain. That chain tries the id, then the candidates produced by
  `ModelsDevModelIDNormalizer`, which strip date and version suffixes such as
  `-YYYY-MM-DD`. The first priceable match wins.
- **Bundled values.** It uses `CURATED_BUNDLED` (below) wherever upstream
  uses its bundled `codex` table.
- **Normalization.** The `normalizeCodexModel` port also reads
  `CURATED_BUNDLED` keys, as upstream does: an id that is a bundled key is
  kept as is, and a dated suffix is stripped only when the base is bundled.
- **Output.** The resolver returns **fully effective numeric rates**. It
  applies upstream `codexCostUSD`'s own fallbacks before storing, so no rate
  field is ever empty:
  - a missing cached rate becomes the input rate
  - long-context fields fall back as `codexCostUSD` does

  Pricing therefore never needs fallback logic, and two entries can be
  compared field by field.
  - **Fill order.** Long-context fields are derived from the **raw, unfilled**
    fields, in `codexCostUSD` order:
    - long input: `longInput = inputAbove ?? input`
    - long output: `outputAbove ?? output`
    - long cached: `cacheReadAbove ?? cacheRead ?? longInput`
    - long cache write: `cacheWriteAbove ?? cacheWrite ?? longInput`

    The standard fields are filled only afterwards: `cached = cacheRead ??
    input`, and `cache write = cacheWrite ?? input`. Filling them first would
    change long-context results. Upstream `codexCostUSD` is authoritative for
    any case this list misses.
- **Threshold.** The bundled threshold when the bundled table has one;
  otherwise the catalog's (200,000 from `context_over_200k`); otherwise no
  `long_context`. This follows upstream exactly.
- **Note in `token_rules.md`.** models.dev's own `tiers` data gives 272,000
  for models where upstream uses 200,000. Colophon keeps upstream's behavior
  for parity and records this as an upstream simplification to revisit.
- **Ordinary usage is keyed by normalized id, as upstream.** Each logged
  model is priced as `resolve(normalizeCodexModel(raw), …)`. Upstream stores
  normalized row models (`CostUsageScanner.swift`, 4288, 4637), so ordinary
  alias, bundled-only alias and folded dated-id pricing all match upstream.
  Raw-id lookup applies only to priority overrides below. Thresholds,
  bundled fills and historical rates use the normalized id.
  - **Unfolded spellings.** A dated or versioned spelling that
    `normalizeCodexModel` does not fold (for example
    `gpt-6-sol-2026-09-01`, whose base is not bundled) is its **own key**
    with its own history.
    - The lookup chain still prices it from the base's catalog entry, as
      upstream does.
    - Its history starts with a `catalog` entry recorded at the first fetch
      after it appears. Earlier usage is priced at that entry's rate. Upstream
      also prices such a spelling at the current catalog rate, so the cost
      matches upstream as of the time it is recorded. After a later repricing,
      upstream reprices past usage and Colophon does not (the dated-history
      deviation in §15). The diagnostic for this case reads "price history for <id>
      begins <date>", as information, not a warning.
    - If the catalog later lists the spelling itself at different rates,
      that is recorded as an ordinary rate change. Past usage keeps its
      rates.
  - **Provider-qualified ids.** Ids such as `provider/model` for a provider
    other than OpenAI are unpriced, because only the `openai` subset is
    kept. That is also recorded.

**Curated data (in the launcher, maintained in the repo).** Two clearly
delimited JSON blocks keep the launcher a single file:
- **`CURATED_BUNDLED`** is a port of upstream's bundled `codex` table. It has
  **its own schema**, not the ledger format: an object keyed by model id
  whose values use upstream's field names and **per-token** units
  (`inputCostPerToken`, `outputCostPerToken`, `cacheReadInputCostPerToken`,
  `cacheWriteInputCostPerToken`, `thresholdTokens` and the `…AboveThreshold`
  fields). Fields upstream leaves `nil` are omitted. It has no
  `effective_from` or `source`.
  - It is read by the resolver and by the `normalizeCodexModel` port.
  - The maintainer script `tests/parity/check_upstream_tables.py` checks every
    value against upstream's table at the cited commit. It is separate from
    the suite; suite tests never read an external repository or binary.
- **`CURATED_PRICE_HISTORY`** holds dated entries in the ledger format below,
  seeded by the maintainer from a dated models.dev snapshot. `token_rules.md`
  records the snapshot date and method.
  - **Model with an upstream historical rate** (`codexHistoricalPricing`):
    an entry with `effective_from: null` ("from the beginning") carrying the
    historical rate, then an entry at the cutoff carrying
    `resolve(id, snapshot)`.
  - **Every other seeded id:** one `null` entry carrying `resolve(id,
    snapshot)`. The seeded ids are the union of:
    - every `CURATED_BUNDLED` key
    - the normalized id of every **priceable** `openai` model in the snapshot,
      resolved against the snapshot and `CURATED_BUNDLED` only

    This covers models upstream prices only from the catalog, such as
    gpt-6-sol and gpt-6.1-sol. Upstream prices those at the catalog rate for
    all dates; a `null` entry does the same.
  - **Priority:** seed entries carry `priority` from upstream
    `codexAPIFastMultiplier`:
    - ×2 for gpt-5.4, gpt-5.4-mini, gpt-5.6-sol, gpt-5.6-terra and
      gpt-5.6-luna, capped at 272,000 input tokens
    - ×2 for gpt-6-astra, with no cap
    - ×2.5 for gpt-5.5, capped at 272,000
  - **Effect.** The seed is the resolver's own output for the snapshot, so a
    first fetch of an unchanged catalog records nothing. Only models that
    are new or repriced since the snapshot get `catalog` entries.

**User ledger.** `$COLOPHON_HOME/price-history.json` is created on first run
with an empty `entries` list, and curated entries are never copied into it.
Colophon only ever appends `catalog` entries, and only to this file. It never
rewrites or deletes an entry. The user, or an agent, may edit the file
freely, and edits apply on the next run.

**Ledger format** (both ledgers). Human-readable JSON, prices per million
tokens, every rate a plain number:

```json
{
  "schema": 1,
  "entries": [
    {
      "model": "gpt-example",
      "effective_from": "2026-08-21T00:00:00Z",
      "per_million": { "input": 4.0, "cached_input": 0.4, "cache_write": 5.0, "output": 20.0 },
      "long_context": { "threshold": 272000, "input": 8.0, "cached_input": 0.8, "cache_write": 10.0, "output": 30.0 },
      "priority": { "multiplier": 2.0, "max_input_tokens": 272000 },
      "source": "catalog",
      "recorded_at": "2026-08-23T14:02:11Z",
      "approximate_date": true,
      "note": "free text"
    }
  ]
}
```

| Field | Rule |
|---|---|
| `model` | Required string; a normalized model id, except the priority-override key `catalog:<matched_catalog_id>\|<normalized_id>` below. |
| `effective_from` | Required. An RFC 3339 UTC instant. `null` ("from the beginning") is allowed **only** in `CURATED_PRICE_HISTORY`. |
| `per_million` | Required object. All four keys are required, each a number ≥ 0. |
| `long_context` | Optional object. If present, `threshold` is required (a positive integer), and all four rate keys are required, each a number ≥ 0. A request whose input exceeds `threshold` uses these rates. |
| `priority` | Optional object. `multiplier` is a number > 0. `max_input_tokens` is a positive integer, or `null` for no cap. |
| `source` | Required. `curated` (launcher only), `catalog` (appended by Colophon) or `manual` (written by a person or an agent). |
| `recorded_at` | Required on `catalog` entries; optional otherwise. |
| `approximate_date`, `note` | Optional. |

A hand-written `manual` entry must also give every rate as a number. A manual
entry covers only its own rate period. To add a priority multiplier from date
D, for example for gpt-6.1-sol, which upstream does not know, write a
`manual` entry at D that repeats that period's rates and adds `priority`. The
README shows how to copy the rates.

**Resolution, per request.**
1. **Normalize** the model name (ported `normalizeCodexModel`).
2. **Merge** `CURATED_PRICE_HISTORY` and the user ledger. All entries are kept.
3. **Pick** the entry with the latest `effective_from` at or before the
   request's timestamp. `null` sorts before every instant.
   - For the same model and `effective_from`, `manual` beats `catalog`, which
     beats `curated`.
   - A user entry can therefore correct a curated entry, but only as `manual`
     or `catalog`. A user-ledger entry marked `curated` is a validation error.
4. **Usage older than a model's first dated entry** uses that model's
   **earliest** entry, never current rates. It records the informational
   diagnostic "price history for <id> begins <date>". The same diagnostic
   covers unfolded spellings (above).
5. **No ledger entry at all.**
   - If a catalog rate is available (fetched or cached) but was not recorded,
     because recording was skipped this run (see "Writing the ledger"), price
     with a *transient* entry, `resolve(id, catalog)`, effective from the
     beginning. Record the diagnostic "priced from unrecorded catalog rate".
   - Otherwise the model is **unpriced**. This is the single definition of
     "unpriced", used everywhere (§9).
6. **Long context.** Use the entry's `long_context` rates when the request's
   input exceeds its `threshold`.
7. **Priority turn.** Applies when the unit's turn id is detected or stored
   as priority (§5.5), following upstream `codexPriorityCostUSD` and
   `codexResolvedCostUSD`. Resolve rates for the priced model, including the
   raw-model override below; the bucket still uses the normalized usage model.
   - The *standard cost* is the non-priority cost from the formula, with
     long-context rates when they apply.
   - **Multiplier.** Read `priority` from the history entry selected for the
     normalized **priced** model at the request time, independently of the
     rates key. Within `max_input_tokens` (`null` means no cap), priority cost
     = `multiplier` × standard cost, and final cost is
     `max(priority cost, standard cost)`.
   - **Over the cap.** If the input exceeds the cap, use the standard cost.
   - **No `priority` field in that multiplier entry.** Use the standard cost
     and record the diagnostic
     "priority usage on a model with no known multiplier; priced at
     standard", with the token volume. That tells the user which models need
     a `manual` entry.

**Priority-override rate selection.** This follows upstream
`resolvedCodexPricing(model: m)` (`CostUsagePricing.swift`, 562–620). Let
`m` be the raw trace model chosen by the override rule, `n` its normalized
id, and `t` the usage timestamp:

1. If `n` has an upstream historical cutoff and `t` precedes it, pick `n`'s
   history. Historical rates take precedence over the catalog.
2. Otherwise run the ported catalog lookup chain for both `m` and `n`.
   Let their first priceable matched catalog model ids be `c_m` and `c_n`.
   If `c_m` exists and differs from `c_n`, use history key
   `catalog:<c_m>|<n>`. Resolve that key's rates through `resolve_rates(m)`:
   raw catalog lookup, with the bundled entry and threshold of `n`, exactly
   as upstream merges them.
   - With no entries for this key, use a transient `resolve_rates(m)` entry.
   - With entries but `t` before their first one, use `n`'s history instead.
     Before the alias catalog entry existed, both lookups matched `n`;
     adding an alias entry later must not reprice earlier override usage.
3. When the matches are equal, absent, or step 2 selects the earlier-history
   fallback, pick `n`'s history with the ordinary rules and bundled fallback.

The override key is the only non-normalized ledger key. The multiplier and
cap always come from `history.pick(n_priced, t).priority`, where `n_priced`
is the normalized priced model, independently of that key.

**Recording catalog rates.** Recording runs whenever a catalog is available
and the user ledger is valid: from a 200, a 304, the cache, or `--offline`.
It happens **before** pricing (§4). Let *T* be the catalog's **fetch time**,
which is when that copy was downloaded, not the current run time.

Recording receives `key → source_model` pairs. For ordinary keys,
`source_model = key`; for an active priority override key,
`source_model = m`. Run the priceable-catalog filter and resolver on the
source model while recording the result under the key. The set below
includes these override pairs in addition to ordinary ids.

The **recording set** is the union of:
- the normalized id of every **priceable** model in the catalog (the same rule
  as the seed)
- the normalized ids of every model seen in this run's logs
- every id that has an entry in **either** ledger

Only ids whose lookup chain finds a **priceable catalog entry** are recorded.
A bundled-only id absent from the catalog is never recorded: its curated seed
entry already prices it, and a `source: catalog` label would be misleading.
For each such id:
- **Skip** if any entry for this model already has `effective_from` = *T*.
  This makes recording idempotent: re-reading the same cached catalog never
  appends.
- **Compute** `resolve_rates(source_model)` for each recording key. Its
  `priority` is copied from the
  entry the pick rule selects at *T*, of any source, if there is one,
  because the catalog has no priority data.
- **Compare** with the latest **non-`manual`** entry (`catalog` or `curated`)
  at or before *T*. Compare the standard rates, and the `long_context`
  threshold and rates. `priority` is not compared.
  - No such entry exists (first sight, or a model with only `manual`
    entries): **append**.
  - Any compared field differs: **append**.
  - Otherwise: nothing.
- **Appended entries** have `source: catalog`, `effective_from` *T*,
  `recorded_at` set to now, and `approximate_date: true`.
- **Manual entries are never compared against.** A `manual` correction stays
  in force until the catalog itself changes price; the catalog's new price
  then supersedes it from *T* onward. A model the user priced manually before
  the catalog listed it gets a `catalog` entry at *T* once it appears. The
  README states both behaviors.
- **Never** backdate to the catalog's per-model `last_updated`. It is not a
  price-change date: in research it lagged real repricings by weeks.

**Detection lag.** Colophon only sees a change when it fetches. Usage between
a real change and its detection is priced at the earlier rate. A `manual`
entry with the true date corrects this, and the README explains how.
Correcting history changes the figures on pages generated afterwards; that is
the intended effect.

**Writing the ledger.**
1. Re-read `price-history.json` immediately before appending.
2. If its mtime changed since the start of the run (for example, an editor
   saved it), skip appending for this run and warn.
3. Otherwise write a temp file and rename it into place.

**Validation.** The user ledger fails validation when:
- it is not valid JSON, or the `schema` is unknown
- any field violates the table above (missing, wrong type, out of range)
- `effective_from` is unparseable, or is `null`
- `source` is unknown, or is `curated`
- two entries share model, `effective_from` and `source` but differ in any
  field other than `note` and `recorded_at`

A failed ledger stops cost computation for that run, and also stops
recording. Tokens are still shown. The error names the file, the entry index
and the problem. Exact duplicates are not an error: they collapse, and a
warning is reported. Colophon never repairs or guesses.

A test validates `CURATED_PRICE_HISTORY` with the same rules, with two
exceptions: `source: curated` is required, and a `null` `effective_from` is
allowed. `CURATED_BUNDLED` is validated against its own schema, above.

**Promotion to the repo** (maintainer procedure, in the README):
1. List the user-ledger `catalog` entries newer than the curated history.
2. Review them.
3. Add them to `CURATED_PRICE_HISTORY` as `curated` entries.
4. Commit with the usual validation.

`manual` entries are personal corrections and are promoted only
deliberately. An agent can perform this mechanically.

**Formula.** The port of `codexCostUSD`, applied per request or event with the
chosen entry's rates (its `long_context` rates when `long`):

```
tok_in        = max(0, request input tokens) (total prompt size)
tok_cached    = min(max(0, cached_input_tokens), tok_in)
tok_cachew    = 0 (upstream Codex rows bill no cache writes)
tok_uncached  = tok_in − tok_cached − tok_cachew
long          = entry.long_context present and tok_in > entry.long_context.threshold
rate          = long ? entry.long_context : entry.per_million
input_rate    = rate.input / 1_000_000
cached_rate   = rate.cached_input / 1_000_000
cachew_rate   = rate.cache_write / 1_000_000
output_rate   = rate.output / 1_000_000
cost_usd      = (tok_uncached × input_rate)
                + (tok_cached × cached_rate)
                + (tok_cachew × cachew_rate)
                + (max(0, output_tokens) × output_rate)
```

- `output_tokens` is used as reported: it already includes reasoning tokens,
  which are not added again.
- Token counts come from the usage record on the primary path, and from the
  counted deltas of the ported accounting on the fallback path (§5.5). They
  are never a raw cumulative total.
- Cache-write billing is zero, matching upstream. The logged count remains
  in the payload's `cache_write` field for display only.
- Rates are never rounded. Catalog per-million values are stored as given.
  A bundled per-token value `x` becomes per million through
  `float(Decimal(repr(x)).scaleb(6))`. Dividing each rate before multiplying,
  and adding terms in the order shown, matches `codexCostUSD`'s operations.
  A bundled double can differ by one ulp after that round trip; parity may
  also sum in a different order. The accepted daily cost tolerance is
  `|Δcost| ≤ 1e-9 × cost + 1e-9` USD (representation only).

**Labels.** Costs are labelled "API-equivalent estimate (not billed)"
everywhere. The reader and the models panel show which rate period, and which
ledger source, priced a cost.

### 5.7 Workspaces

- **Workspace key.** The first of these that applies:
  1. The normalized git origin URL. Normalization: scheme and host lowercased,
     userinfo and credentials stripped, `.git` removed, SSH form equated with
     HTTPS.
  2. The git top-level folder of the cwd, if it still exists.
  3. The cwd folder.
- **Aliases.** `workspaces.json` maps origin URLs and path prefixes to a
  display name. Typical uses: merging a private and a public remote of the
  same project, or a deployed copy that lives outside the repo.
- **Subfolder.** The cwd's path below the workspace root is kept as a
  secondary chip (`tools-public › some_project`) and can be used as a filter.
- Codex desktop "project" assignments are ignored in v1.

### 5.8 Archived sessions

- Included by default, tagged ARCHIVED.
- One "archived: shown/hidden" filter affects every panel.

### 5.9 Roll-up rules (your sessions vs subagents)

- **Tokens and cost.** A session's figures include its subagents' usage,
  shown as "total (yours + subagents)" with the split visible in the reader.
  KPIs and the model, workspace and calendar totals count every usage unit
  exactly once.
- **Time.** "Your active time" and "agent time" stay separate, as in §5.2.
- **Drill-downs land on your sessions.** A filter matches a session if the
  session *or any of its subagents* matches. For example, the model
  `gpt-x-mini` matches a session whose only use of it was a subagent. The
  matching subagents are highlighted in the reader.
- **Counts.** "Sessions" means your sessions. Subagent counts are shown
  separately.

## 6. Embedded data contract

The page embeds one JSON document in
`<script type="application/json" id="colophon-data">`:

| Key | Contents |
|---|---|
| `meta` | Version, build instant (UTC), `generated_tz`, counts, catalog fetch time and status. |
| `sessions` | Your sessions: turns, kept text, tool summaries, usage, cost, flags, subagent ids. Usage is aggregated into **UTC 15-minute buckets** per model and tier. Every real time-zone offset is a whole multiple of 15 minutes, so local-day and local-hour grouping is exact in every zone. |
| `subagents` | Keyed by id: the same shape, plus the parent link, spawn and interaction turns, and the link method. |
| `workspaces` | Name, keys, aliases. |
| `models` | Rate periods used per model, each with its ledger source (curated, catalog or manual), or "unpriced". |
| `diagnostics` | Skipped files, malformed-line counts, truncated and recovered lines, unknown record types, database threads without logs, logs without metadata, `duplicate_session_ids`, orphaned subagents, inferred links, unpriced models, models whose price history begins after their first use, priority usage without a known multiplier, rates from an unrecorded catalog, unresolved fork boundaries, ledger warnings, page size. |

- All times are UTC.
- Aggregates and filters are computed in the browser from `sessions` and
  `subagents`, so every panel respects the active filters and the viewer's
  time zone.
- Text is inserted as text, never as HTML.
- The implementation plan fixes the field names, and a schema test locks
  them.

## 7. Visual direction

Style **"instrument panel"**:
- near-black background with a faint grid
- phosphor green for data and highlights
- amber for section labels and warnings
- Martian Mono throughout, with a light weight for figures

The approved mockups cover the overview and the session list + reader, and
the layout rules in §8.5 came from their review.
The mockups remain private because they contain real session titles. Only
their design tokens and layout values, restated in the implementation plan,
may enter public source; the mockup files themselves must not.

## 8. Screens and behavior

### 8.1 Global

**Top bar:**
- Product mark and breadcrumb.
- "Data as of", log count and price-catalog time.
- Search across titles and requests.
- Period chips: 7D, 30D, 90D, MTD, ALL, CUSTOM (date range).
- The archived toggle.

Filters show as removable chips. Filter state lives in the URL hash, so back
and reload preserve it.

**Empty state.** Zero sessions shows a message naming the Codex home that was
read.

### 8.2 Overview (home)

**KPI row:**
- sessions
- your active time
- agent time
- turns (with average turn time)
- tokens (with cached-input share)
- estimated cost
- aborted turns (amber), as in the approved mockup. The line beneath shows
  "n interrupted · n abandoned". These two statuses replaced the mockup's
  "incomplete" when live-session handling was added (§4.1).

**Turn scope.** The turns, average turn time and aborted-turns tiles, and the
hour × weekday heat map, count **your sessions' turns only**. Subagent
activity appears in the agent-time and subagent figures, never in turn
counts. Tokens and cost include subagents, per §5.9.

When any total includes running turns, that tile shows a LIVE marker with
"includes n running" (§4.1).

**Period-over-period change.** Each tile shows its change against the
previous period of equal length, for 7D, 30D, 90D and MTD (MTD compares with
the same days of the previous month). It is hidden for ALL and CUSTOM.

**Clickable tiles.**

| Tile | Opens |
|---|---|
| Sessions | The list |
| Your active time | The list sorted longest-first |
| Agent time | The list sorted by subagent time |
| Turns | The list |
| Tokens | The list sorted by tokens |
| Estimated cost | The list sorted by cost |
| Aborted turns | The list filtered to sessions with aborted turns. The "interrupted" and "abandoned" figures beneath are separate links, each filtering to its own status. |

**Panels:**
- **Calendar heat map:** 53 weeks × 7 days, or fewer for short periods. Metric
  toggle: sessions / active time / tokens / cost.
  - Cell size scales down to a minimum of 9 px.
  - If the weeks still do not fit, the grid sits in a horizontal scroll region
    (`data-scroll-region`), scrolled to the most recent week by default.
  - This is the only permitted scroll region (§8.5).
- **Hour × weekday heat map:** counts your sessions' turn starts, in local
  time.
- **Workspaces:** bars, with a time / tokens toggle; top N, then "+ N more".
- **Models:** tokens and cost.
- **Notable:** busiest day, longest active day, biggest subagent fan-out,
  longest streak.
- **Recent sessions:** short list, plus "view all".

**Drill-down.** Every cell, bar, notable item and row is clickable. It opens
the session list with the matching filter (day, hour-of-week, workspace,
model, session) applied per §5.9.

### 8.3 Session list

**Grouping.** Your sessions only, grouped by local day under amber day
headers.

**Row contents:**
- start time
- title, with the ARCHIVED tag when it applies
- workspace and subfolder chip
- active time
- subagent count
- flags: LIVE, aborted, interrupted, abandoned, uncertain timing

**Sort:** newest, longest, subagent time, tokens, cost.

**Search** matches the full title and request text.

**Selection.** Clicking a row opens the reader in the right-hand pane.

### 8.4 Session reader

**Header:**
- full title on expand
- workspace › subfolder, branch, time range, originator
- short id
- a forked link, when the session is forked from another

**Buttons:**
- **Open in Codex:** the `codex://threads/<id>` link.
- **Copy "Continue in CLI":** copies `codex resume <id>`. The label states that
  this continues the session; it is not a viewer.
- **Copy session ID.**
- **Copy log path.**

Clipboard actions use `navigator.clipboard` when it is available. Otherwise
they fall back to selecting the text in a read-only field with a "press ⌘C"
hint.

**Stats strip:** active time, span, turns, subagents (with agent time), tokens
and cost (with a yours / subagents split).

**Mini timeline:**
- Turns are solid blocks; idle time is a hairline.
- Subagents run in a sub-lane, each labelled with its humanized agent path
  (e.g. `code review`). Codex's `agent_role` field is empty in current logs,
  so it is never the label.
- Inferred links are drawn dashed.
- Forked subagents carry a badge.

**Turn card.** One per turn.
- **Header:** time range, duration, time to first token, tokens, cost,
  status.
- **YOU ASKED · n:** the first two requests are shown. "+ n follow-ups sent
  while it worked" expands the rest. Long text is clamped behind "more".
  Voice requests are marked.
  - Requests labelled "before this turn" (§5.1) appear first, in their own
    group, and do not count toward the "first two" or the follow-ups.
  - A voice-reply answer is marked "voice reply" under FINAL ANSWER.
- **IT USED:** tool-summary chips (§5.4), with failures in amber.
- **SUBAGENTS · n:** subagents spawned in this turn. Each row shows agent-path
  label · nickname · start · active time · tokens, plus a forked badge where
  it applies, as in the approved mockup (e.g. "code review · AgentName"). Expanding
  a row shows a miniature card: timing, tools, tokens and final answer. Turns
  that only interacted with a subagent show "also used: <agent-path label>".
- **FINAL ANSWER:** an excerpt, with "expand".

Below the last turn card, a line "tokens outside displayed turns" appears
whenever §5.5 attributed usage to the session but to no displayed turn, so the
cards plus that line equal the session's own total (§5.5).

**Pre-ship verification.** Confirm that "Open in Codex" opens a live session,
an archived session and a subagent session, and that it does not un-archive
anything. Also confirm what `codex resume` does to an archived session.

- Failing cases hide the button for that case.
- The README states the verified behavior.

### 8.5 Layout rules

- Grid and flex children set `min-width: 0`.
- Titles truncate with an ellipsis and show the full text in a tooltip.
- The list's metrics column has a fixed width.
- The stats strip and button rows wrap.
- Timeline labels never overlap. A colliding label moves to a second row or
  into a tooltip.
- Below 900 px, the list/reader split becomes a single pane with a back
  control.
- **Invariant:** no text overflows its container, and no text overlaps another
  column, at any width ≥ 360 px. Tests enforce this (§12.3).
- The only exception is an element marked `data-scroll-region` (the
  calendar). Its content may exceed its box, and it must scroll internally.
  The page itself never scrolls horizontally.

### 8.6 Theming (light-ready)

- `<html data-theme="dark">` is the default.
- Every color, border, shadow and heat-map ramp step is a CSS custom property
  in a single `:root[data-theme="dark"]` token block.
- JavaScript reads ramp colors from computed custom properties and never
  holds color literals.
- A lint test fails on any color literal outside the token block.
- Adding the light theme later means adding a `[data-theme="light"]` block, a
  toggle and `prefers-color-scheme` handling.

### 8.7 Page constraints

- **Self-contained.** No external requests. Fonts, CSS and JS are inline.
- **Martian Mono** (SIL OFL 1.1) is embedded as a subset WOFF2. Its license
  ships as `colophon/OFL.txt` and is reproduced in a comment next to the
  embedded font. System monospace is the fallback.
  - `colophon/docs/font.md` records the provenance and the regeneration
    recipe: the upstream release and version, the weights, the Unicode
    subset range, and the subsetting command. Subsetting uses fontTools in
    the dev requirements, never at runtime.
- **Plain JavaScript.** No framework and no build step; the script is
  embedded in the launcher as a template.
- **Accessibility basics:**
  - controls are focusable and keyboard-operable
  - focus is visible
  - text contrast meets WCAG AA against the dark background

## 9. Errors and diagnostics

| Condition | Behavior |
|---|---|
| Codex home missing or unreadable | Message naming the path; exit 1. |
| Malformed JSONL line | Skipped; counted per file. |
| Unreadable or empty log file | Skipped; named in diagnostics. |
| Unrecognized record type (§3) | Counted per type. The footer says "Codex's log format may have changed". |
| Metadata SQLite locked or unreadable | Fall back to titles from the logs; diagnostic recorded. |
| Priority trace database unavailable | Retain sticky priority memory; units without detected or stored priority evidence use standard pricing. |
| Database thread without a log file | Counted in diagnostics. |
| Log with usage but no `session_meta` | Count tokens in its own `file:<path>` unit; display filename-derived identity with `no_session_meta` (§5.1). |
| Files sharing a session id | Count the union of distinct rows; display newest-mtime copy; `duplicate_session_ids` lists pre-pass ids and differing display ids (§5.1). |
| Catalog unreachable or timed out | Use the cached catalog and the price history; diagnostic recorded. |
| Model with no history entry and no catalog rate | "Unpriced" for that model; tokens still shown (§5.6 step 5, the only definition). |
| Usage before a model's first dated entry | Priced at that model's earliest entry; diagnostic recorded. |
| Invalid `price-history.json` | Costs are not computed and nothing is recorded for the run; tokens still shown. Stderr names the file, entry index and problem (§5.6). |
| Ledger changed by another writer during the run | Appending is skipped for this run, with a warning. |
| Orphaned subagent (parent log missing) | Listed as a top-level row with a flag; counted. |
| Priority usage on a model with no known multiplier | Priced at standard; diagnostic names the model and token volume (§5.6 step 7). |
| Model priced from an unrecorded catalog rate | Transient entry used; diagnostic (§5.6 step 5). |
| Fork history boundary unresolved | Session listed without turn, time or request metrics (tokens per §5.5); flagged and counted (§5.3). |
| Truncated final line or glued fragment | Per §4.1: skipped or recovered, counted in its own category. |
| Invalid `workspaces.json` | Stderr names the file, line and problem. The file is ignored, the run continues, and diagnostics record it. |
| Cache version mismatch or corruption | Discard the entry (or the whole cache) and reparse. |
| Zero sessions | Empty-state page; exit 0. |
| Browser cannot be opened | Print the page path; exit 0. |
| Concurrent runs | Every write goes to a temp file in the same directory, then is renamed into place. |

The page footer shows the diagnostics panel whenever a count is non-zero, and
stderr prints a one-line summary.

## 10. Privacy and security

- Colophon is read-only on `~/.codex`.
- **Network.** Colophon's only traffic is the price-catalog GET, and no
  session data is ever sent. Separately, uv may contact the network on its
  very first run to provision a Python interpreter. That is uv's normal
  behavior, and needs no packages since dependencies are empty.
- **File modes.** The runtime directory is 0700, and every written file is
  0600, including `--output` pages. The page contains plaintext copies of
  your requests and final answers.
- **What is stored.** Only the text described in §5.1.
- **Origin URLs** are stripped of credentials before they are stored.
- **Public repository.** It holds conspicuously synthetic fixtures and
  examples, plus seven specifically approved, allowlist-scrubbed fixture
  families (§12.1). No raw real data is committed. Parity and real-data
  acceptance output stays under `$COLOPHON_HOME` and is never committed.

## 11. Performance

The targets scale with the data rather than fixing a number of seconds.

- **Linear scaling (hard test).** On synthetic corpora of size S and 2S,
  `time(2S) ≤ 2.5 × time(S)`. Each measurement is a cold run: `--rebuild`
  against a fresh temporary `COLOPHON_HOME`. No hidden cache-off switch
  exists.
- **Cold throughput.** The local acceptance script (`tests/perf/`, committed
  code) measures MB of log parsed per second on real data and writes
  `$COLOPHON_HOME/perf-baseline.json`. A later acceptance run more than 1.5×
  slower than the baseline is reported as a regression. `colophon` itself
  never reads or writes the baseline.
- **Warm run.** The cost is fixed overhead, plus the changed logs, plus a
  render that is linear in the session count.
- **Progress.** A cold run prints progress to stderr by bytes, with an ETA.
- **Page size.** Reported in the run summary. Over 20 MB is a diagnostic,
  not a failure.

## 12. Testing

Unit, integration and browser categories run in the project's documented
suite. Local acceptance and maintainer scripts are separate commands;
neither the suite nor its fixtures require an external checkout or binary.

### 12.1 Fixtures

All test data is Colophon's own. The suite never reads another repository's
code, tests or fixtures and never runs CodexBar. Upstream sanitized fixtures
are not imported. Maintainer scripts may use a local CodexBar checkout and
CLI outside the suite.

Seven scrubbed real fork/subagent families in `tests/fixtures/scrubbed/`
were approved on 2026-10-03. They use an allowlist scrub, generated ids,
synthetic paths, names and text, whole-day time shifts and doubled tokens.
Their stored reference outputs were checked against the private originals
using the same mapping. They are immutable Colophon fixtures; never change
or regenerate their inputs or expected values to make a test pass. No raw
real data is committed.

A generator in `tests/` builds synthetic Codex homes. They cover:
- **Log formats and records:**
  - Both log formats: structured items, and raw/legacy calls including JS
    `exec` wrappers.
  - Turns recorded in both forms.
  - Every recognized record type in §3, plus an unknown one.
- **Subagents and forks:**
  - Depth-2 subagents.
  - All four turn-link methods.
  - A subagent used in several parent turns, and a repeated `task_name`.
  - Forked subagents with an inherited prefix and two `session_meta` records.
  - A forked top-level session.
- **Tokens and pricing:**
  - Repeated token snapshots, a counter drop, and `token_usage_record` turns.
  - A turn that has only `token_count` inside a `token_usage_record` file.
  - A foreign-thread usage record.
  - Priority tier from a synthetic `logs_2.sqlite`, including standard and
    priority turns in the same session, completed-model highest-rowid choice,
    pending-completion FIFO retention, and sticky memory after pruning.
  - Priority on a model with a multiplier (under and over its input cap), on
    gpt-6-astra (no cap), and on a model with no multiplier (diagnostic);
    a `manual` entry adding a multiplier; `priority` carried forward.
  - Lookup chain: a dated or versioned log model id priced through
    `ModelsDevModelIDNormalizer` candidates; a catalog model without input
    or output (not priceable); a provider-qualified id (unpriced).
  - The resolver port: catalog models with and without `cache_read`,
    `cache_write` and a long-context block; bundled models with and without a
    bundled threshold; a bundled model missing from the catalog. Expected
    values are derived by hand from upstream `resolvedCodexPricing` and
    `codexCostUSD`.
  - A model with only `manual` entries that then appears in the catalog.
  - A bare usage line with no `type`.
  - Recording scope: a priceable catalog model added after the snapshot and
    not yet used is recorded at first fetch; a seeded but unused model is
    recorded when repriced.
  - The seed union: a catalog-only model (not in `CURATED_BUNDLED`) priced
    from its `null` seed entry.
  - Ordinary aliases, bundled-only aliases and folded dated spellings with
    their own catalog entries: normalized row pricing matches upstream.
    Raw lookup is exercised only for priority overrides, including a later
    alias catalog entry that must not reprice earlier usage (§5.6).
  - Unfolded spellings:
    - A dated log id whose base is not bundled: its own key; priced through
      the lookup chain from the base's catalog entry; a `catalog` entry under
      the dated id at its first fetch; the "price history begins" diagnostic;
      and the same cost upstream gives it.
    - A compact-date (`-YYYYMMDD`), `-vN:N` or `@` spelling of a bundled base:
      not folded, so no bundled threshold or historical rate applies, exactly
      as upstream.
    - The catalog later listing a dated spelling itself at different rates:
      recorded as a rate change, with past usage unchanged.
  - Bare usage lines: the model from the line itself, from `data`, from the
    model in force, and the `unknown` model; a bare line outside any turn.
  - Model in force: a blank field followed by a non-blank one (the non-blank
    one wins); all present fields blank (cleared); all four omitted
    (unchanged); reset at a subagent's owned suffix.
  - The attribution invariants (§5.5): turn cards + "outside displayed
    turns" = own total; own + descendants = overall total.
  - A forked log whose counted deltas fall on inherited records ("tokens
    outside displayed turns").
  - Recording from a 304, from the cache and under `--offline`, and
    idempotence; a transient entry when recording is skipped.
  - Fallback-path counted deltas matching upstream behavior: first event,
    repeated totals, stale regressions, interleaving latch, gaps larger than
    `last_token_usage`, and total-only events.
  - Historical-cutoff dates, and the curated `null` seed entries.
  - Long-context requests, including the 200k–272k band.
  - Catalog `tiers` and `context_over_200k` shapes, a catalog model without
    `cost`, and an unknown model.
  - Price history:
    - curated + user ledgers, and manual or catalog correcting a curated
      entry on the same date
    - usage before the first dated entry (earliest-entry rule)
    - first sight of a model, and a detected rate change
    - a ledger edited during the run
    - exact and conflicting duplicates
    - every invalid-ledger case of §5.6
- **Time and turns:**
  - Collapsed timestamps.
  - Every embedded-clock key, and the within-2 s wrapper preference.
  - Each turn-duration rule of §5.2, including reported duration with a
    `completed_at` end, and unknown duration in a collapsed log.
  - Inherited-prefix path A (own lifecycle, a verified synthetic `rollout-*`
    start, and unresolved) and path B (each of its three end conditions).
  - Aborted turns, and the interrupted, running and abandoned open-turn cases
    either side of the 2-hour threshold.
  - A turn crossing local midnight, and DST transitions.
- **Live and crash damage (§4.1):**
  - A log growing between two runs, and bytes appended during a scan.
  - Partial final lines, recent and old.
  - A fragment glued to a following record.
  - A counter restart.
  - Empty and header-only logs.
  - Logs with usage but no `session_meta`, counted as separate file units.
  - Files sharing session ids: fallback-row union, primary-record
    de-duplication, newest-mtime display and parent selection, path tie-break,
    and pre-pass ids that differ from true-first display ids.
  - Fork-of-fork resolution independent of scan order (approved `b10` case).
  - A same-size, same-mtime rewrite, caught by the tail fingerprint.
  - A log moved into `archived_sessions`, and a deleted log.
  - A file that grows during the scan (scan-start cache key).
  - An unchanged log first parsed within 2 hours, then re-run after 2 hours:
    its open turn flips from running to abandoned and its partial final line
    from "still being written" to "truncated", despite the cache hit.
- **Text and requests:**
  - Injected request prefixes.
  - Every context wrapper, with and without a request heading.
  - Answer parts and image parts.
  - Multiple requests per turn.
  - Voice: alternating user and assistant segments, requests before and
    between turns ("before this turn"), after the last turn, a turn with no
    `final_answer` using the voice reply, and a session with no turns.
  - Identical repeated user messages.
- **Tools:** `Extension` `clock.sleep` (not counted), `image_gen.generation`
  (Other), `custom_tool_call` `exec` vs `apply_patch`, and `tool_search_call`.
- **Subagents:** an orphaned subagent.
- **Workspaces and other cases:**
  - Archived sessions.
  - Malformed lines.
  - Database threads without logs.
  - Origin URLs with credentials.
  - Alias files.
  - Zero sessions.

### 12.2 Unit and integration tests (pytest)

**Unit tests:**
- every rule in §5
- dedup semantics
- cache invalidation
- price-history resolution, merge, change recording, validation and formula
- open-turn classification and the live/crash rules of §4.1
- the orchestration and prefix lists

**CLI integration.** Run `--no-open --offline --codex-home <fixture>` against
a temp `COLOPHON_HOME`. Check:
- the embedded JSON values and the schema
- every row of §9 (exit codes and messages)
- 0600/0700 file modes, including `--output`
- atomic writes
- no network use under `--offline`
- `--offline --refresh-prices` is rejected
- first-run creation of `price-history.json` and `workspaces.example.json`
- `--rebuild`: the cache is replaced only on success, and an interrupted
  rebuild leaves the old cache intact
- a second run after a fixture log grows picks up the new totals
- user ledger entries survive every run unchanged

**Price refresh.** Against a local HTTP catalog via `COLOPHON_PRICING_URL`:
200, ETag/304, header timeout, body timeout, and `--refresh-prices`.

### 12.3 Browser tests (Playwright Chromium, repo standard)

- The page opens from `file://` with no `pageerror` or `console.error`, and
  makes no network requests.
- KPIs equal values computed independently from the embedded data.
- Each KPI tile, heat-map cell, bar and notable item produces the expected
  list.
- The reader shows turn cards, follow-up expansion, subagent expansion, the
  forked badge and inferred styling.
- The archived toggle, URL-hash state, the empty state and the clipboard
  fallback all work.
- The time-zone helper is checked under at least two emulated time zones.
- **Overflow:** at 360, 390, 899, 901, 1024 and 1440 px, no element's content
  overflows its box, no text overlaps another column, and the page has no
  horizontal scroll. Elements marked `data-scroll-region` are exempt from the
  box check only, and must scroll internally.
- **Theme lint:** no color literals outside the token block.

### 12.4 Local-only acceptance (documented; outputs never committed)

- **Parity script** (`tests/parity/`, committed code, no data):
  - Compares per-day, per-project and per-session tokens and cost against
    `codexbar cost` on the maintainer's real logs.
  - Writes reports under `$COLOPHON_HOME/parity/`.
  - Every mismatch is resolved in `token_rules.md`: the rule is ported,
    adapted, or the deviation is recorded.
  - The report states the CodexBar version, which may be a custom build.
- **Real-data smoke run:** record timing, throughput baseline, page size and
  diagnostics.
- **§8.4 link verification.**

### 12.5 Fleet suites

Run the uv-header guard tests, the deployment-audit fixture test and the
static deployment test, as `agents.md` requires.

## 13. Repository integration and deployment

**Project files:**
- `colophon/colophon`: the launcher.
- `colophon/README.md`: name, install, usage, flags, environment variables,
  runtime files, price-history format and editing, the price-history
  promotion procedure, privacy, attribution, parity procedure, verified link
  behavior.
- `colophon/OFL.txt`.
- `colophon/docs/`: this spec, the implementation plan, `token_rules.md`,
  `font.md`.
- `colophon/tests/`.
- `colophon/requirements-dev.txt` (pytest, playwright, fonttools, brotli).
- `colophon/pytest.ini`.

**Fleet registration:**
- the `tools/check_uv_headers.py` launcher registry and dependency-manifest
  policy
- the `tools/check_local_deployments.zsh` mapping
  `~/Library/Scripts/colophon <- colophon/colophon`, and its fixture test
- the direct-copy list in `docs/local_deployment_sync.md`
- the root README project list
- an `agents.md` validation-matrix entry

**Deploy.** Per `docs/local_deployment_sync.md`:
1. Validate.
2. Back up the existing copy.
3. Copy.
4. Byte-compare, and run `colophon --version` from the installed copy.
5. Run the read-only audit.

Repository commits do not deploy.

## 14. Attribution

The README carries an attribution section:
- **CodexBar** (MIT, © 2026 Peter Steinberger). Token-accounting rules, the
  cost formula, model normalization, the seed of the curated price history (historical rates and thresholds) and the
  priority-tier multiplier are ported or adapted from it. The upstream files
  and commit are cited in `token_rules.md` so future maintainers can re-check
  them when upstream changes.
- **models.dev** (MIT). The price catalog.
- **Martian Mono** (SIL OFL 1.1). The embedded typeface; the license is in
  `OFL.txt`.

Ported functions carry a header comment naming their upstream source.

## 15. Decisions and open items

**Decided by the user (2026-10-03).**
- Port CodexBar's historical rates and Codex thresholds. They seed the curated
  price history (§5.6).
- No bundled current-price snapshot. Every run, including the first, fetches
  the catalog; "unpriced" appears only in the cases listed in §5.6.
- Keep price history going forward: a curated ledger in the repo plus a
  user-editable JSON ledger per machine (§5.6, option B).
- Live sessions are snapshots. Running turns count toward totals with a LIVE
  marker. The quiet threshold for abandoned turns is 2 hours (§4.1).
- `--rebuild` replaces the cache atomically (§2).

**Approved differences from upstream CodexBar (complete list, 2026-10-03).**
Each is recorded in `token_rules.md`; other token and cost calculations
follow upstream at `3bbf6bc48`.

1. Exact per-response `token_usage_record` usage is preferred where present;
   other turns use the ported `token_count` accounting. The context-compaction
   evidence and the explicitly set-aside remainder are recorded in §5.5.
2. Prices are dated history, so a price change never reprices past usage.
   The priority multiplier and cap live in that history, seeded from
   upstream `codexAPIFastMultiplier` (§5.6).
3. Priority tier comes from upstream's trace database, plus sticky memory of
   detected priority turns. This Colophon addition preserves detected turns
   after trace pruning (§5.5), serving the role of upstream's persistent
   cached row pricing mode/model.
4. The trace database follows `--codex-home`; upstream uses `~/.codex`
   regardless of `CODEX_HOME`.
5. Only the `openai` catalog subset is kept. `openai/` is stripped as
   upstream normalization does; any other provider-qualified model is
   unpriced with a diagnostic. Colophon reads no CodexBar cache, settings
   or data.
6. Duplicate-id fork parents use the newest-mtime copy, with ascending-path
   ties, rather than upstream's incremental file-index selection (§5.1).
   The union of distinct token rows across copies still follows upstream.
7. Fork-of-fork chains resolve regardless of file order. Upstream's
   newest-first production scan retries a pending parent only one level
   deep, leaving the `b10` reference chain unresolved when the grandchild
   file is newest. Colophon resolves parents on demand; this was approved
   with "resolve them anyway". The comparison was verified by reordering
   only mtimes; porting upstream's scan-order machinery was declined.

**Factual correction C1.** Ordinary raw-alias, bundled-only alias and folded
dated-id pricing are not deviations. Upstream normalizes usage rows before
pricing; only its priority override carries a raw model into the resolver
(`CostUsageScanner.swift`, 4288, 4637;
`CostUsageScanner+PricingRows.swift`, 15–19, 87–95). Colophon follows that
structure. Cache-write tokens are billed as zero. Rate conversion changes
only representation, within the explicit §5.6 cost tolerance.

**Deliberate deviation from the research extractor:** a fork whose history
boundary cannot be resolved is listed without turn, time or request metrics,
with tokens only where token accounting attributes owned usage. The extractor
dropped such sessions entirely (§5.3).

**Resolved during implementation.**
1. Fallback-path port (snapshot accounting and fork baselines): verified by
   parity; any remaining difference is recorded in `token_rules.md`.
2. Whether sessions missing from CodexBar's report are a CodexBar rule or a
   gap. Colophon counts them unless a recorded rule says otherwise.
3. Open in Codex / `codex resume` behavior (§8.4).
4. Measure and record cold throughput and real page size.
5. Light theme: the next release after v1 acceptance.
6. Logs with only two distinct wrapper timestamps exist in the research
   sample. Measure them during acceptance, and decide whether the collapsed
   rule (§5.2) should cover them. Record the decision here.
