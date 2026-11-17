# Turn, status, clock and pricing accuracy: implementation plan

Status: cross-checked and finalized for implementation. Owner decisions are
final.

## Scope and source anchors

Correct turn boundaries, turn and session clocks, statuses, duplicate fork
copies, OpenCode usage dating, Codex priority pricing and diagnostic noise
found in an aggregate review of the owner's rebuilt page. Preserve accounting
under **Usage parity** and compare external references under **Acceptance**.

Inspect existing behavior before changing it:

- Claude: `src/claude/parse.c` (`Parse`, `on_record`, `finish`, `on_raw`,
  `add_records`, `claude_known_type`), `src/claude/compose.c`
  (`claude_usage_line`, `Winner`, `wins`, `authored`), `src/claude/scan.c`
  (`claude_scan_aliases`), `src/claude/codec.c`, `src/corpus/subagents.c`
  (fork and subagent linking), `src/parse/reader.c` (callback order).
- Codex: `src/parse/turns.c::turns_build`, `src/parse/record.c`,
  `src/parse/classify.c` (known record list), `src/corpus/assemble.c`
  (session clocks and idle), `src/cache/cache.c` (`format`).
- Shared: `src/corpus/provider.c::corpus_session_idle`.
- OpenCode: `src/opencode/corpus.c` (`message_end`, `project_session`),
  `src/opencode/compose.c` (usage unit dating), `src/opencode/db.c` (message
  loading, table allow-list).
- Antigravity: `src/antigravity/corpus.c` (turn `end_kind`),
  `src/antigravity/db.c::read_rows`.
- Pricing: `src/price/pricing.c::price_usage_units`,
  `assets/pricing_rules.json` (`codex_fast`),
  `assets/curated_price_history.json`.
- Page: `assets/page.js` (request tags), `src/cli/run.c` (page size limit).
- References: CodexBar `origin/main` at `1f6da9bec`:
  `Sources/CodexBarCore/Vendored/CostUsage/CostUsagePricing.swift`
  (`codexAPIFastMultiplier`, `codexAPIFastAllowsLongContext`) and
  `Sources/CodexBarCore/Providers/OpenCode/OpenCodeLocalHistoryAdapter.swift`
  (message `time.created`).

Private transcript content and owner-specific values must not enter this
public repository. Implement and test with conspicuously synthetic inputs.
The owner requested the private parity check under **Acceptance**; it is
aggregate-only and runs in private temporary space.

## Decisions

### Claude turn starts

A user record that has a string `turnOrigin` and is not `isCompactSummary`
starts a turn, whatever its `isMeta` value or leading tag. Its request kind is
`notification` for `task_notification`, `peer` for `peer`, and otherwise follows
the tag classification in `src/claude/parse.c::on_record`.

A user record without `turnOrigin` keeps the existing classification, with one
addition: a non-`isMeta` record whose leading tag is `<task-notification>`
starts a `notification` turn when there is no current turn or the current turn
would finish `completed`, `interrupted` or `aborted`. Otherwise it stays in the
current turn.

In a subagent, a user record whose `origin.kind` is `coordinator` starts a turn
of kind `resume`.

Every new start finishes the previous turn through `src/claude/parse.c::finish`
and the steered rule in `on_record`. Include the start record in `on_record`'s
turn-clock condition.

### Request text and titles

For a turn started by `turnOrigin`, request text drops leading
`<system-reminder>` elements through their closing tags. When `add_records`
falls back to request text for a title, it uses the first `text` or `command`
request. Call `notification`, `peer` and `resume` the agent-started request
kinds; they cannot supply a title. If no eligible request exists, use the
filename fallback in `src/claude/parse.c::add_records`.

### Claude API failures

An assistant record with `isApiErrorMessage: true` marks the current turn as
failed; a later assistant record without that flag clears it. `finish` treats
the failed state like `Parse.api_error` under `finish`'s precedence. Preserve the regression
`claude_command_message_unknown_tag_and_last_assistant_end_reason`.

### Reply-less turns

A `command` turn with no assistant record finishes `completed` at its last
turn-clock record instead of `open`. Reply-less `text` turns keep current
behavior.

### Claude fork copies

Use the main transcript identity from `src/claude/parse.c::claude_parse`. It is a
fork when a record whose `sessionId` equals its own ID follows records whose
`sessionId` names another session; the first such own record is the
transition record. Transcripts without a transition retain `on_record`'s
alias behavior.

At the transition record, the parser discards everything it built from earlier
records: turns, requests, tools, answers, statuses, titles, `tool_turns`, and
session clocks. Usage rows and alias collection are kept. Records without a
`sessionId` after the transition count as the fork's own. The fork's
`meta.forked_from_id` is the last nonempty `sessionId` before the transition.
This is the recorded predecessor; do not infer an absent intermediate parent.
In `add_records`, also project it into `SessionModel.forked_from` so the payload
and page receive the link. Do not set `F_FORKED` for these main Claude forks.

For a detected fork, usage rows with a nonempty persisted `session_id` that
differs from the fork's own ID are inherited and attach to no turn. Rows with
an empty `session_id` before the transition are inherited; those at or after
the transition are own rows. Persist the boundary or equivalent ownership facts
for cache and retained-record reuse. Clear attachment for every pre-transition
row and the transition record's own usage rows.
Account for callback sequencing in `src/parse/reader.c::consume_line` without
reusing discarded turn keys. In `wins`, a non-inherited
row beats an inherited row before the path-order comparison, so the original
session keeps its own responses.

A subagent transcript is a copy when it has usage rows, all its rows'
`session_id` name one session other than its directory's session, and that
session has a subagent transcript with the same file name. Copies produce no
subagent row, and their usage rows are excluded from deduplication candidates
so that the original's identical rows count. Fork detection and subagent-copy
suppression must remain correct on warm cache and retained records. Use persisted
usage-row and metadata fields; if the implementation needs a new stored field, add a
codec version as `docs/development.md` requires.

### Session clocks

Claude session `end_ms` is the latest turn-clock record of the session, falling
back to the existing `last_ms` when the session has no turns. Session start
follows **Claude fork copies** and is otherwise unchanged.

Codex `event_msg/thread_settings_applied` advances neither session `end_ms` nor
the current turn's `last_ms` in `turns_build`.

Idle time is clamped at zero. Move the Codex idle computation from
`src/corpus/assemble.c`, preserving its arithmetic, into
`corpus_session_idle` and call it from there, so that one function owns idle
for every provider.

### Codex interruptions

`event_msg/turn_aborted` with `payload.reason` equal to `interrupted` ends the
turn `interrupted`. Other or missing reasons keep `aborted`.

### OpenCode clocks and usage dating

When loading messages, `src/opencode/db.c` marks a `completed` clock as
unreliable when the identical millisecond value appears as `completed` on
messages in more than one session within the same database. `message_end`
ignores an unreliable `completed`; turn status still uses its presence. This
chosen heuristic assumes repeated cross-session stamps are bulk updates; it
can also discard legitimate simultaneous completions.

Date OpenCode usage units by `opencode_message_created`, following the pinned
CodexBar adapter. Preserve residual dating in `src/opencode/compose.c`.

### Antigravity statuses and identity diagnostic

A turn's `aborted` or `interrupted` status comes from the status of the last
step in the turn that has one; earlier error or cancel steps do not decide it.
`running` handling is unchanged.

`read_rows` reports the identity diagnostic only when `cascade_id` differs from
the filename conversation ID. `trajectory_id` is not compared.

### Codex pricing

Codex fast-tier multipliers and long-context allowance match CodexBar's
`codexAPIFastMultiplier` and `codexAPIFastAllowsLongContext` at the commit
named above, in `assets/pricing_rules.json` (`codex_fast.multipliers`,
`codex_fast.uncapped`) and as a `priority` object on every existing
`curated_price_history.json` row for those models, following the pricing
lesson in `docs/development.md`. Do not add multipliers CodexBar lacks.

In the timed path of `price_usage_units`, when the selected history entry has
no `priority` policy or no entry exists, take the priority multiplier and cap
from `codex_fast`, sharing the policy resolver with the untimed path. Preserve
an explicitly present history policy, including explicit null, under
`HistoryEntry.has_priority`.
Expose the effective fallback policy through the existing pricing provenance.

### Codex auto-review

`codex-auto-review` usage stays unpriced by owner decision.

### Diagnostics and page size

Add these record types to the known lists in `claude_known_type` and
`src/parse/classify.c` without adding ingestion behavior. These names came
from the owner's private page diagnostics; suppressing their warnings is a
chosen ingestion scope, not a claim about their upstream semantics:

- Claude: `attachment`, `atis-latch`, `api-request`, `api-request-shape`,
  `api-request-blob`, `agent-name`, `cost-state`, `tools-used`, `mode`,
  `file-history-delta`, `artifact-comment-monitor`,
  `artifact-autoreact-ledger`, `bridge-session`, `frame-link`,
  `permission-mode`, `session-owner`, `relocated`, `worktree-state`.
- Codex: `response_item/additional_tools`,
  `response_item/configuration_update`,
  `event_msg/item_completed/HookPrompt`,
  `event_msg/item_completed/FunctionCallOutput`.

`retained_context` stays unknown. OpenCode reports `session_part` as
unrecognized only when the table has rows.

Raise the page size limit in `src/cli/run.c` to 128 MiB, as a named constant
compared by a function that tests can call. Do not trim the payload.

### Usage parity

No change in this plan may alter Claude or Codex token totals, or Claude cost,
for any day and model. Codex cost changes only through **Codex pricing**.
OpenCode totals change only in day placement through **OpenCode clocks and
usage dating**.

### Cache and release

Bump `CLAUDE_PARSE_REVISION` once and the native Codex cache `format` in
`src/cache/cache.c` once, following `docs/development.md`, in the final task.
Release as 0.10.0.

## Out of scope

Codex duration policies, Claude output-token under-logging, the existing small
Claude output-token difference from ccusage, display of partly unpriced
session costs, request rows from `queued_command` attachments, Codex threads
whose rollouts no longer exist, and **Codex auto-review**.

## Task 1: Claude turn starts, failures and reply-less commands

Implement **Claude turn starts**, **Request text and titles**, **Claude API
failures** and **Reply-less turns** in `src/claude/parse.c`.

Tests first, in `tests/unit/test_claude_parse.c` with `parse_text`,
`parse_subagent_text` and RFC 3339 clocks:

- `claude_turn_origin_starts_turns`: one case per `turnOrigin` kind, including
  an `isMeta` peer record and a `<system-reminder>`-led SDK prompt; assert
  request kinds, stripped request text, and that tool calls after each start
  belong to it.
- `claude_turn_origin_compact_summary_continues`: a compact summary carrying
  `turnOrigin` does not start a turn.
- `claude_task_notification_tag_after_completion`,
  `claude_task_notification_tag_first_record` and
  `claude_task_notification_tag_mid_turn`.
- `claude_subagent_coordinator_resume_starts_turn`, plus a main-session case
  where `origin.kind` `coordinator` does not start a turn.
- `claude_api_error_message_aborts_turn` and
  `claude_api_error_message_then_reply_completes`.
- `claude_command_without_reply_completes` and
  `claude_text_without_reply_stays_open`.
- `claude_wakeup_turn_clock_excludes_wait`: the wait before a wakeup belongs to
  no turn.
- `claude_title_skips_agent_requests`: cover **Request text and titles** with
  an agent-started request followed by an eligible request, and a session
  containing only agent-started requests.

Existing regressions must pass; any edit to one states why in the change.

In `tests/test_claude_store.py`, extend the shared synthetic builder in
`tests/helpers.py` with a peer wakeup and an SDK prompt led by a system
reminder; assert emitted turn statuses, request kinds and durations, and that
session usage totals equal the sum of turn and outside usage.

In `assets/page.js`, tag every agent-started request kind using the `command`
tag rendering pattern; cover the tags in `tests/test_browser.py`.

Document these rules beside the Claude turn rules in `docs/runtime.md`.

## Task 2: Claude fork copies and session clocks

Implement **Claude fork copies** and the Claude part of **Session clocks**.

Tests first:

- `tests/unit/test_claude_parse.c`: `claude_fork_transition_discards_inherited`
  (turns, tools, clocks, statuses and title come only from own records,
  including an inherited region with records lacking `sessionId`;
  `forked_from_id` follows **Claude fork copies**), `claude_fork_of_fork_parent`,
  `claude_foreign_only_transcript_is_not_fork`, and
  `claude_session_end_uses_turn_clock` (trailing queue and link records do not
  extend `end_ms`).
- `tests/unit/test_claude_usage.c`: a fork and its source sharing response IDs
  produce each response's usage exactly once, credited to the source, whatever
  their path order. Assert source ownership for pre-transition rows lacking
  IDs, own-row ownership for blank `session_id` rows after the transition,
  and no turn attachment for transition-record usage. Assert warm-cache and
  retained-record behavior.
- `tests/test_claude_store.py`: a synthetic source session with a subagent and
  a fork containing a byte-identical copy of that subagent; assert one
  subagent row, the fork's `forked_from`, no `forked` flag on the fork,
  unchanged total usage and no duplicated turns. Add a case where the source
  subagent is missing, so the copy is kept.

Document the fork and session-clock rules in `docs/runtime.md`, beside the
history-alias rules.

## Task 3: Codex interruptions, session clocks and idle

Implement **Codex interruptions**, the Codex part of **Session clocks**, and
the shared idle clamp.

Tests first: a Codex fixture in `tests/test_cli.py` with `turn_aborted`
reasons `interrupted`, another value and none; a `thread_settings_applied`
record after the last turn, and one inside an open turn; and a subagent whose
turns extend past its session span. Add a unit regression in
`tests/unit/test_provider.c` for the clamp. Assert statuses, session `end_ms`,
turn `last_ms` and non-negative `idle_ms`.

Document the interruption, end-clock and idle rules in `docs/runtime.md`.

## Task 4: OpenCode clocks and usage dating

Implement **OpenCode clocks and usage dating**.

Tests first, in `tests/unit/test_opencode_db.c`,
`tests/unit/test_opencode_corpus.c` and `tests/unit/test_opencode_usage.c`
with the existing synthetic fixture builder: messages in several sessions
sharing one `completed` value days after their creation, including a session's
final message; assert turn and session ends ignore it, statuses are unchanged,
and usage units are dated at `created`. Add a case where one session's
messages share a `completed` value (kept) and a case with distinct values
(unchanged).

Document **OpenCode clocks and usage dating** in `docs/token_rules.md` beside the OpenCode usage
rules and the clock rule in `docs/runtime.md`.

## Task 5: Antigravity statuses and identity diagnostic

Implement **Antigravity statuses and identity diagnostic**.

Tests first, with `tests/unit/antigravity_fixture.c`: a turn with an errored
step followed by a successful final step (`completed`), a turn whose final
step errored (`aborted`), and a cancel-then-success turn (`completed`) in
`tests/unit/test_antigravity_corpus.c`; a database whose `trajectory_id`
differs and `cascade_id` matches (no diagnostic), and one whose `cascade_id`
differs (diagnostic) in `tests/unit/test_antigravity_db.c`.

Document the status rule in `docs/runtime.md`.

## Task 6: Codex pricing

Implement **Codex pricing**.

Tests first, in `tests/unit/test_price.c`: timed and untimed priority units
for each model added from CodexBar's lists, including a model with no curated
history row, a catalog-sourced `gpt-6.1-terra` history entry without a `priority`
field, explicit-null history policy, and a unit above the long-context threshold;
assert costs, effective policy provenance and that
`priority_without_multiplier` is empty for cases with an effective multiplier.
Cover stored-policy precedence under **Codex pricing** separately.

Document the CodexBar parity source and the timed fallback in
`docs/token_rules.md` beside the existing Codex priority rows.

## Task 7: Diagnostics, page size, cache and release

Implement **Diagnostics and page size** and **Cache and release**.

Tests first: unit cases that each newly known type no longer appears in
unknown-type diagnostics; an empty and a non-empty `session_part` table in
`tests/unit/test_opencode_db.c`; and the page-size comparison function just
below, at and above the limit. Update revision assertions as
`docs/claude_turn_boundaries_implementation_plan.md` describes for
`claude_codec_v3_revision_and_immutable_v2`,
`claude_store_stale_revision_reparses_then_hits` and
`test_claude_handback_stale_v2_live_cache_reparses`.

Set the version in every maintained declaration found by
`rg -n '0\.9\.0' colophon tools --glob '!*_implementation_plan.md'`, keeping
historical notes, and add the README release note.
Update `docs/development.md` and `docs/LESSONS_LEARNED.md` with the source-field
precedence in **Claude turn starts** and **Claude fork copies**, and the
assumption and limitation of **OpenCode clocks and usage dating**.

### Acceptance

Run the complete root Validation Matrix `colophon` and `Static
deployment/fleet audit tooling` entries and report every category.

Follow the private-data constraints under **Scope and source anchors**:

1. In a private temporary directory, make two copies of the owner's Colophon
   runtime home, so both builds keep its price history, pricing cache,
   priority memory and retained Claude facts (`docs/runtime.md`, runtime
   files).
2. Use documented source overrides with coherent private snapshots when
   supported. Otherwise fingerprint the admitted source files and relevant
   SQLite sidecars before and after every reader below; invalidate and rerun
   an affected comparison if inputs changed. Do not enumerate unrelated
   credential/settings trees or query SQLite contents for this check. Distinguish
   retained/deleted Colophon inputs from the live population ccusage can read.
3. Build a page with the installed binary, after confirming its `--version`
   is the previous release, and one with the new build. Each run sets
   `COLOPHON_HOME` to its own copy and passes `--rebuild --offline --no-open`.
4. Extract per-day, per-provider, per-model token and cost totals from each
   payload's buckets for every local date present in either payload.
5. Run `ccusage daily --json --offline --by-agent --timezone <local zone>`
   and take its per-agent model breakdowns for the same dates.
6. Check **Usage parity** between the two builds. Compare the total Codex cost
   per affected model per day with ccusage, preserving the source's
   standard/priority mix. The owner selected **Usage parity** as the governing
   rule when unchanged Colophon counting differs from ccusage: report the
   aggregate oracle gap and ship without changing token ownership or dating
   merely to force the cost comparison within one cent.
   OpenCode per-day tokens must match ccusage's OpenCode breakdown;
   report any remaining day-level difference with its cause, such as
   compaction or rollup residual units, instead of adjusting either side.

Read OpenCode session contents only through Colophon and ccusage. Remove the
temporary directory afterwards.
