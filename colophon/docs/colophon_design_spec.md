# Colophon — Design Spec

Status: approved design; user review complete; revised after review round 1 and its sanity check · Date: 2026-10-03

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
| `sessions/**/rollout-*.jsonl`, `archived_sessions/**/rollout-*.jsonl` | Primary data. A log under `archived_sessions` is archived. |
| `state_*.sqlite` (newest readable schema): `threads` | Titles, cwd, git data, archived flag, agent nickname/role/path, `rollout_path`. |
| `state_*.sqlite`: `thread_spawn_edges` | Authoritative parent → child edges, when present (§5.3). |
| `session_index.jsonl`, `.codex-global-state.json` | Additional title sources, in the title priority of §5.1. |

Database threads with no log file are counted in diagnostics only.

**Recognized record types.** Each type is either *used* or *known and
ignored*. Any other type is counted per type for format-drift diagnostics
(§9).

| Record | Treatment |
|---|---|
| `session_meta` | Used. **The first `session_meta` in a file owns the session identity.** A later one is ancestor metadata and marks a copied (inherited) prefix. Same rule as the research extractor and upstream CodexBar. |
| `turn_context` | Used: model, effort, turn id. |
| `event_msg` `task_started` / `task_complete` / `turn_aborted` | Used: turn lifecycle, duration, time to first token. |
| `event_msg` `thread_settings_applied` | Used: `service_tier` in force from that point (priority pricing, §5.6). Also ends an inherited prefix, as in the research extractor. |
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
| Top-level `realtime_item` | Used for the user's voice transcript segments only (§5.1). |
| Legacy `event_msg` `user_message` / `agent_message` | Supported for older Codex versions; absent from current logs. |

## 4. Compile pipeline

```
scan files → parse each file (cached) → load metadata → assemble sessions
→ link subagents → resolve workspaces → account tokens → price
→ render HTML (data embedded) → atomic write → open
```

**Parsing.**
- Each log is read once, as a stream.
- A parse produces a compact per-file record: session facts, turns, kept text,
  tool counts, usage events and diagnostics.
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
     threshold. Excluded from time totals and flagged incomplete. Its tokens
     and cost still count, because they were spent.
5. **Counter restart.** A cumulative token counter that restarts after a crash
   is handled by the counter-drop rule (§5.5).
6. **Empty or header-only logs.** Skipped and counted. Not an error.
7. **Colophon's own interruption.** The page, the cache and the price-history
   ledger are always written via temp file + rename. An interrupted run leaves
   the previous versions intact.

Fixtures exist for each case (§12.1).

**Rules carried over from the research extractor.** The extractor is a
private research script, not part of this repository. Its rules are restated
here and in §5, and are behaviors to carry over, not code to copy:
- title priority
- turn lifecycle
- inherited-prefix boundary for forks, including the
  synthetic-start-verified-by-completion case
- timestamp-provenance flags
- reported-duration fallback

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
- A session is one log file, identified by its first `session_meta` id.
- "Your sessions" have no subagent parent. Subagents are nested under their
  parent.

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

**Voice.** User transcript segments in `realtime_item` are kept as requests
marked "voice", grouped per contiguous run of segments. A run is attached to
the turn that contains it. A run that falls between turns, or before the
first turn, is attached to the next turn that starts; a run after the last
turn is attached to that last turn. In a session with no turns, runs appear
as session-level requests.

The wrapper, heading and prefix lists are single constants, and tests assert
each list in full. Fixtures cover every wrapper with and without a heading.

**Final answer.** The turn's last `final_answer`-phase agent message.

**Never stored.** Commentary, reasoning, command output, patch contents, MCP
arguments and results, inter-agent messages (including subagent task briefs),
and developer/system messages.

### 5.2 Turns and time

**Turns.**
- **Duration** comes from the start/end timestamps, otherwise from the
  reported duration.
- **Status** is completed, aborted, interrupted, running or abandoned. The last
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
- Inherited records are excluded from every metric.

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

Each usage unit is attributed to a session, turn, model (from the
`turn_context` in force), UTC instant, and service tier. The service tier is
the one in force at that instant, from the latest preceding
`thread_settings_applied`; the default tier applies before any.

Upstream detects priority from Codex's `logs_*.sqlite` trace database
instead. Colophon's source is a recorded deviation in `token_rules.md`, and
parity reports any difference.

**Source selection, per turn.**
- If the turn has any `token_usage_record` belonging to this session, use
  those records.
- Otherwise use `token_count` deltas.

**Primary path: `token_usage_record`.**
- Each `response_id` is counted once.
- Only records whose `thread_id` equals the session's own id are counted. The
  real-data audit found no foreign records, so this guard is exercised by
  fixtures.

**Fallback path: `token_count`.**
- Usage per event is the change in cumulative `total_token_usage`. A repeated
  snapshot counts zero. Summing `last_token_usage` overcounts because
  snapshots repeat.
- **Counter drop.** The cumulative total can decrease. The starting rule is:
  the pre-drop peak stays counted and the next segment starts a new baseline.
  The final rule is set by parity (§12.4).
- **Fork baseline.** Follows upstream `CodexSubagentRolloutShape`:
  - The first session meta owns leaf identity.
  - Embedded ancestor metadata proves a copied prefix.
  - A zero-component opening event carries inherited context.
  - The first owned event supplies the baseline.
  - Independently restarted counters still count their opening usage.

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

**Fetching.** The current-rate source is the catalog at
`COLOPHON_PRICING_URL` (models.dev by default). Prices are USD per 1M tokens.
- **Every run fetches the catalog before compiling, including the first.**
  - It sends a conditional GET (`If-None-Match`). A 304 keeps the cached copy;
    a 200 replaces it, keeping only the `openai` provider subset.
  - Timeouts: 3 s to connect and receive response headers, and 30 s for a
    body download.
  - `--refresh-prices` forces an unconditional GET with the same 30 s budget.
  - `--offline` skips the fetch.
- Catalog models without a `cost` object (for example image-only models) are
  ignored.
- There is no bundled snapshot of current prices.

**Two ledgers, one format.**
- **Curated history.** Maintained in the repository and embedded in the
  launcher as one clearly delimited JSON block, `CURATED_PRICE_HISTORY`, so
  the launcher stays a single file.
  - It is seeded with rates ported from upstream CodexBar
    (`CostUsagePricing.swift` @ `3bbf6bc48`, cited in `token_rules.md`): its
    bundled Codex rates and thresholds, plus `codexHistoricalPricing`.
  - **Seeding rule.** A historical rate valid until a cutoff becomes an entry
    with `effective_from: null`, which means "from the beginning". It is
    followed by an entry at the cutoff carrying the upstream bundled rate.
    A bundled rate with no historical predecessor becomes a single
    `effective_from: null` entry.
  - Only the curated ledger may use `null`.
- **User ledger.** `$COLOPHON_HOME/price-history.json` is created on first run
  with an empty `entries` list, and curated entries are never copied into
  it. Colophon only ever appends `catalog` entries, and only to this file. It
  never rewrites or deletes an entry. The user, or an agent, may edit the
  file freely, and edits apply on the next run.

**Format.** Human-readable JSON, prices per million tokens:

```json
{
  "schema": 1,
  "entries": [
    {
      "model": "gpt-example",
      "effective_from": "2026-08-21T00:00:00Z",
      "per_million": { "input": 4.0, "cached_input": 0.4, "cache_write": 5.0, "output": 20.0 },
      "long_context": { "threshold": 272000, "input": 8.0, "cached_input": 0.8, "cache_write": 10.0, "output": 30.0 },
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
| `model` | Required. Normalized model id. |
| `effective_from` | Required. An RFC 3339 UTC instant. Curated entries may instead use `null`, meaning "from the beginning". |
| `per_million` | Required, with all four keys. A model with no separate cached or cache-write rate repeats its `input` rate. |
| `long_context` | Optional. If present, `threshold` and all four rate keys are required. A request whose input exceeds `threshold` uses these rates. |
| `source` | Required. `curated` (launcher only), `catalog` (appended by Colophon) or `manual` (written by a person or an agent). |
| `recorded_at` | Required on `catalog` entries; optional otherwise. |
| `approximate_date`, `note` | Optional. |

**Resolution, per request.**
1. **Normalize** the model name, ported from upstream `normalizeCodexModel`.
2. **Merge** the curated and user ledgers. Entries never replace one another
   during the merge; all of them are kept.
3. **Pick** the applicable entry: the one with the latest `effective_from` at
   or before the request's timestamp. `null` sorts before every instant.
   - When entries share a model and `effective_from`, the order of precedence
     is `manual`, then `catalog`, then `curated`.
   - A user entry can therefore correct a curated entry, but only by being
     `manual` or `catalog`. A user-ledger entry marked `curated` is a
     validation error.
4. **If no entry is at or before the timestamp** (usage older than a model's
   first dated entry), use that model's **earliest** entry. Never use current
   rates for older usage. Record the diagnostic "priced at earliest known
   rate".
5. **Unpriced.** A model is unpriced at an instant only when it has no history
   entry at all and no catalog rate is available from a fetch or the cache.
   This is the single definition of "unpriced", used everywhere (§9).
6. **Long context.** Use the long-context rates when the request's input
   exceeds the entry's threshold. The threshold comes from:
   - `long_context.threshold` on the entry.
   - When an entry is first recorded from the catalog: the catalog's
     `cost.tiers[].tier.size`, or 200,000 if the catalog has only
     `context_over_200k`.
   - Curated Codex entries carry upstream's bundled 272,000.

   **Deviation.** Upstream uses 200,000 for every non-bundled model that has
   `context_over_200k`, even where the catalog's own tier size is 272,000.
   For such models (for example the gpt-6 family), Colophon follows the
   catalog's explicit tier size. This is recorded in `token_rules.md`, and
   parity is expected to report it.
7. **Priority tier.** When the tier in force (§5.5) is `priority`, apply the
   upstream `codexPriorityCostUSD` multiplier rules.

**Recording catalog rates.** Runs only after a successful fetch, and only when
the user ledger is valid. For each model in the catalog:
- **No history entry at all** (first sight). Append a `catalog` entry with
  `effective_from` set to the fetch time and `approximate_date: true`. Because
  of step 4, usage before this entry is priced at this rate.
- **Rates differ** from the model's latest entry in the merged history.
  Append a `catalog` entry with `effective_from` set to the fetch time and
  `approximate_date: true`.
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
- it is not valid JSON, or the schema is unknown
- an entry is missing a required field
- a rate is negative
- `effective_from` is unparseable, or is `null` in the user ledger
- `source` is unknown, or is `curated` in the user ledger
- two entries share model, `effective_from` and `source` but have different
  rates

A failed ledger stops cost computation for that run, and also stops
recording. Tokens are still shown. The error names the file, the entry index
and the problem. Exact duplicate entries are not an error: they collapse, and
a warning is reported. Colophon never repairs or guesses.

**Promotion to the repo** (maintainer procedure, in the README):
1. List the user-ledger `catalog` entries newer than the curated history.
2. Review them.
3. Add them to `CURATED_PRICE_HISTORY` as `curated` entries.
4. Commit with the usual validation.

`manual` entries are personal corrections and are promoted only
deliberately. An agent can perform this mechanically.

**Formula.** Applied per request or event. Token counts are lowercase; rates
come from the chosen entry, and are its `long_context` rates when `long` is
true.

```
tok_in        = request input tokens (total prompt size)
tok_cached    = min(cached_input_tokens, tok_in)
tok_cachew    = min(cache_write_input_tokens, tok_in − tok_cached)
tok_uncached  = tok_in − tok_cached − tok_cachew
long          = entry.long_context present and tok_in > entry.long_context.threshold
rate          = long ? entry.long_context : entry.per_million
cost_usd      = ( tok_uncached × rate.input
                + tok_cached   × rate.cached_input
                + tok_cachew   × rate.cache_write
                + output_tokens × rate.output ) / 1e6
```

- `output_tokens` is used as reported: it already includes reasoning tokens,
  which are not added again.
- "Request input" comes from the usage record, or from the event's
  `last_token_usage` on the fallback path. It is never a cumulative total.
- **Deviation.** Upstream passes zero cache-write tokens for Codex rows.
  Colophon uses the logged `cache_write_input_tokens`. These are zero in all
  current logs, so the results are identical today. The deviation is recorded
  in `token_rules.md`.

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
| `diagnostics` | Skipped files, malformed-line counts, truncated and recovered lines, unknown record types, database threads without logs, orphaned subagents, inferred links, unpriced models, usage priced at earliest known rate, ledger warnings, page size. |

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
- problem turns (amber): the count of aborted + interrupted + abandoned turns,
  with the breakdown beneath

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
| Problem turns | The list filtered to sessions with aborted, interrupted or abandoned turns (same set as the tile's count) |

**Panels:**
- **Calendar heat map:** 53 weeks × 7 days, or fewer for short periods. Metric
  toggle: sessions / active time / tokens / cost.
  - Cell size scales down to a minimum of 9 px.
  - If the weeks still do not fit, the grid sits in a horizontal scroll region
    (`data-scroll-region`), scrolled to the most recent week by default.
  - This is the only permitted scroll region (§8.5).
- **Hour × weekday heat map:** counts turn starts, in local time.
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
- **IT USED:** tool-summary chips (§5.4), with failures in amber.
- **SUBAGENTS · n:** subagents spawned in this turn. Each row shows agent-path
  label · nickname · start · active time · tokens, plus a forked badge where
  it applies, as in the approved mockup (e.g. "code review · AgentName"). Expanding
  a row shows a miniature card: timing, tools, tokens and final answer. Turns
  that only interacted with a subagent show "also used: <agent-path label>".
- **FINAL ANSWER:** an excerpt, with "expand".

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
| Database thread without a log file | Counted in diagnostics. |
| Catalog unreachable or timed out | Use the cached catalog and the price history; diagnostic recorded. |
| Model with no history entry and no catalog rate | "Unpriced" for that model; tokens still shown (§5.6 step 5, the only definition). |
| Usage before a model's first dated entry | Priced at that model's earliest entry; diagnostic recorded. |
| Invalid `price-history.json` | Costs are not computed and nothing is recorded for the run; tokens still shown. Stderr names the file, entry index and problem (§5.6). |
| Ledger changed by another writer during the run | Appending is skipped for this run, with a warning. |
| Orphaned subagent (parent log missing) | Listed as a top-level row with a flag; counted. |
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
- **Public repository.** It holds only conspicuously synthetic fixtures and
  examples. Parity and real-data acceptance output stays under
  `$COLOPHON_HOME` and is never committed.

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

Every category below runs in the project's documented suite.

### 12.1 Fixtures

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
  - Priority tier, including a session that switches between default and
    priority.
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
  - Aborted turns, and the interrupted, running and abandoned open-turn cases
    either side of the 2-hour threshold.
  - A turn crossing local midnight, and DST transitions.
- **Live and crash damage (§4.1):**
  - A log growing between two runs, and bytes appended during a scan.
  - Partial final lines, recent and old.
  - A fragment glued to a following record.
  - A counter restart.
  - Empty and header-only logs.
  - A same-size, same-mtime rewrite, caught by the tail fingerprint.
  - A log moved into `archived_sessions`, and a deleted log.
  - A file that grows during the scan (scan-start cache key).
- **Text and requests:**
  - Injected request prefixes.
  - Every context wrapper, with and without a request heading.
  - Answer parts and image parts.
  - Multiple requests per turn.
  - Voice transcript runs inside, between, before and after turns.
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
- `colophon/requirements-dev.txt` (pytest, playwright, fonttools).
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

**Deliberate deviations from upstream CodexBar** (each recorded in `token_rules.md`;
parity is expected to show them):
- The long-context threshold for non-bundled models follows the catalog's
  tier size, not a fixed 200,000 (§5.6).
- The priority tier comes from `thread_settings_applied`, not the trace
  database (§5.5).
- Logged cache-write tokens are used; they are zero in current logs (§5.6).
- Prices are dated history, so a price change never reprices past usage
  (§5.6).

**Resolved during implementation.**
1. Counter-drop rule and fork baselines on the fallback path: set by parity.
2. Whether sessions missing from CodexBar's report are a CodexBar rule or a
   gap. Colophon counts them unless a recorded rule says otherwise.
3. Open in Codex / `codex resume` behavior (§8.4).
4. Measure and record cold throughput and real page size.
5. Light theme: the next release after v1 acceptance.
