# Claude turn boundaries and clocks: implementation plan

Status: finalized for implementation under the owner's ship-plan request.

## Scope and source anchors

Correct Claude turn clocks and queued-prompt boundaries, recognize subagent
text endings, and stop superseded open turns from appearing live. Release the
tasks together after their acceptance checks pass.

Inspect existing behavior in `src/claude/parse.c::on_record` and `finish`,
`src/corpus/turnstatus.c::turn_models`, `src/claude/reconcile.c::merge_record`,
and the Claude sections of `docs/runtime.md`. The supplied prior review reports
private transcript observations motivating this work; private evidence and
transcript content must not enter this public repository. Implement and test
with invented inputs. No private replay is required for acceptance.

## Decisions

### Turn clock

Only the following records update a turn's `last_ms`: its prompt, assistant
records, non-`isMeta` user records containing a `tool_result` block or the
`[Request interrupted by user` marker, and `system` records with subtype
`api_error`. Use the parser's existing prompt and interruption classification.
Preserve session clocks and reader counts as `on_record` and the reader do.
Preserve API-error state behavior, including the regression
`claude_command_message_unknown_tag_and_last_assistant_end_reason`.

### Queued prompt (steered)

Track `assistant_seen`, `dequeued`, and `stop_marked` in `Parse`, resetting them
on each new prompt. Any assistant record sets `assistant_seen` and clears
`dequeued` and `stop_marked`. A `queue-operation` with `operation: dequeue`
sets `dequeued`; a `system` `stop_hook_summary` sets `stop_marked`.

Before finishing the previous turn on a new prompt, mark it `steered` if it
would otherwise finish `open`, `assistant_seen` and `dequeued` are true, and
`stop_marked` is false. Its end uses **Turn clock**. `finish` retains existing
interrupted, aborted and completed precedence over steered.

This is a heuristic: a queued resumption after a crash may also qualify.
Do not claim that the signal distinguishes those cases.

### Steered display and accounting

Store `steered` as `end_kind`. Count its duration in active time and average
turn time, without adding a session flag or counting it as aborted. Render its
turn header without warning styling. Add an `N steered` link to the turns KPI,
with a neutral variant of `.status-link`; it filters sessions containing that
status through the persisted `st` hash parameter.

### Superseded open turns

In `turn_models`, classify open turns after its existing stable `ordering`
sort. Only the final ordered turn can be running, and only in a non-quiet log.
Every earlier open turn is abandoned with no end, duration or live flag,
including when the final turn is terminal. Preserve quiet-log behavior.
This is a shared display rule for callers of `turn_models`.

### Subagent text endings

For subagent records (`parent_session.p`), an assistant message whose
`stop_reason` key is present and JSON null, with at least one text block and
no tool-use block in that message, sets `p->completed`. Preserve the existing
effects of later records. Main-session behavior stays unchanged.

### Output tokens

Preserve `src/claude/compose.c` and the contract in
`docs/token_rules.md#claude-accounting`. Do not infer replacement usage from
visible content. This work makes no upstream fix-version, parity, or
parent-result recoverability claim.

### Cache and rollback

Bump `CLAUDE_PARSE_REVISION` to its next value under the stored-facts rule in
`docs/development.md`. Change `claude_store_get` to miss on any revision
mismatch. Retained records preserve stored facts. Keep the existing codec
layout; see `src/claude/codec.c::record_v3` for the serialized revision and
`record_v1` for the string-valued turn representation.

For reparse pricing effects, refer to
`docs/token_rules.md#claude-pricing-and-public-seed-provenance`. For rollback
to 0.8.4, require a run with `--rebuild` to discard this release's live parse
facts. Preserve the earlier-decoder limitations in the CLCD3 rollback section
of `docs/runtime.md`. Future rollback into this release follows the mismatch
rule above.

### Release

Use version 0.9.0 for the new visible status and KPI action. This is the chosen
version, independent of historical feature-version conventions.

## Out of scope

Do not add requests from `queued_command` attachments. Preserve the request
representation in `src/claude/parse.c::add_records` and
`src/claude/reconcile.c::merge_record`. A prompt lacking the steered signal
follows existing parser status handling and **Superseded open turns**.
Do not change Codex duration policies. Usage policy is under **Output tokens**.

## Task 1: Claude clocks, steered turns and subagent text endings

Implement **Turn clock**, **Queued prompt (steered)**, **Steered display and
accounting**, and **Subagent text endings**.

### Tests first

In `tests/helpers.py`, add a shared synthetic-session builder consumed by
`tests/test_claude_store.py` and `tests/test_browser.py`. Include completed
and steered turns, idle bookkeeping after a completion, and a terminal final
turn. Fixture values live in the helper; assert behavior by the decisions
above rather than duplicating fixture construction.

In `tests/unit/test_claude_parse.c`, use `parse_text` and
`parse_subagent_text` with RFC 3339 clocks to add these named regressions:

- `claude_turn_clock_ignores_bookkeeping_records`: exercise queue operations,
  pr-link, isMeta user, attachment, stop-hook summary and unknown records.
  Assert **Turn clock** while preserving the session's later clock.
- `claude_turn_clock_follows_conversation_records`: independently exercise
  tool results, interruption markers and API errors against **Turn clock**.
- `claude_queued_prompt_steers_open_turn`: exercise **Queued prompt (steered)**
  with a tool result before dequeue and assert tool-count preservation.
- Separate negative regressions for a completed prior turn, no dequeue,
  an assistant clearing dequeue, a command without an assistant, a Stop hook,
  an interrupted turn, and an API error immediately before the next prompt.
  Assert that existing terminal precedence and the guards above hold.
- `claude_subagent_null_text_ending_completes`: assert **Subagent text
  endings**. Add separate negative cases for a later tool call, absent stop
  reason, thinking-only content, main-session parsing, and text plus tool use
  in the same assistant content array.
- Update `claude_subagent_handback_unknown_last_clock` to assert **Turn clock**.

Preserve the existing regression named under **Turn clock**.

In `tests/test_claude_store.py`, use the shared builder with a quiet mtime.
Assert parser statuses, idle-gap exclusion from turn time, idle time excluding
the steered span, and absence of failure/interruption/abandonment flags. Add a
subagent null-text ending case without an abandoned flag.

In `tests/test_browser.py`, generate a page from the shared builder and assert
**Steered display and accounting** using the existing data-kpi conventions.
Verify computed neutral styling, header class, filtering with a distractor
session, and persistence through URL reload. Exercise active and average turn
time as well as the aborted KPI.

Run `make test-unit`, `make test-cli`, and `make test-browser` before
implementation, recording the expected new regression failures.

### Implementation and docs

- `src/claude/parse.c`: implement the parser decisions in `Parse`, `finish`
  and `on_record`, preserving existing record/session-clock processing and
  error handling.
- `assets/page.js`: update the `st` allow-list, `turnIntervals`, `ownActive`,
  `kpis`, `renderKpis` and turn-header rendering for the display decision.
  `assets/page.css`: add the neutral link variant.
- `docs/runtime.md`: document these Claude rules beside the handback rules;
  revise the later-events/end-clock sentence to reference the clock rule.
  Document the new KPI action beside the KPI share rules.
- `docs/token_rules.md`, Claude accounting: document **Output tokens** without
  adding unverified upstream/version claims.
- `docs/LESSONS_LEARNED.md`: record that conversation clocks must be separate
  from transcript bookkeeping and delivery heuristics need negative cases.

### Acceptance

Run the complete root Validation Matrix `colophon` entry; report every
category and failure output. Release scope is defined under **Scope and source
anchors**.

## Task 2: Superseded open turns, cache revision and release

Implement **Superseded open turns**, **Cache and rollback**, and **Release**.

### Tests first

- `tests/unit/test_corpus.c`,
  `turn_models_superseded_open_turn_is_not_running`: assert the shared status
  decision with non-quiet open turns, out-of-input-order clocks, quiet logs,
  equal clocks preserving stable order, and a terminal final turn. Include
  missing-clock ordering and verify `active_interval_union` excludes abandoned
  spans. These cases distinguish final ordered turn from final open turn.
- In `claude_codec_v3_revision_and_immutable_v2`
  (`tests/unit/test_claude_codec.c`) and
  `claude_store_stale_revision_reparses_then_hits`
  (`tests/unit/test_claude_store.c`), replace only assertions for newly parsed
  current records with `CLAUDE_PARSE_REVISION`. Preserve immutable legacy
  revision-zero assertions and deliberately stale inputs.
- In `tests/test_claude_store.py`, update the trailing revision assertion in
  `test_claude_handback_stale_v2_live_cache_reparses` to the new revision.
- `tests/unit/test_claude_store.c`: add a live newer-revision miss/reparse/
  commit test. Update the reference predicate in
  `claude_store_index_matches_linear_reconciliation` for revision inequality.

Record expected regression failures before production changes.

### Implementation, version and docs

- Update `src/corpus/turnstatus.c::turn_models`, `src/claude/parse.h` and
  `src/claude/store.c` according to the decisions.
- Locate maintained release declarations/assertions with
  `rg -n '0\.8\.4' colophon tools --glob '!*_implementation_plan.md'`.
  Synchronize them to **Release**, including installer activation and its
  test. Preserve historical README notes and add this release's note.
- `docs/runtime.md`: add the shared status decision in a separate
  provider-independent paragraph; document the cache/rollback decision in
  the Claude cache section. `docs/development.md`: document mismatch misses.

### Acceptance and deployment

Run the complete root Validation Matrix `colophon` and `Static
deployment/fleet audit tooling` entries. Do not treat optional live checks as
required or acquire market data. Follow existing prepared-data constraints
for any affected suite. Report each category with counts and failure output.
Verify source `--version` against **Release** and inspect remaining old-version
matches to distinguish historical references from maintained declarations.

After merging, deploy via `docs/local_deployment_sync.md#native-colophon-deployment`
and perform the installed synthetic offline/version verification in
`docs/development.md`, including rendered footer verification and installer
audit. The owner's ship-plan request authorizes this deployment; no real
session data or owner-page run is necessary.
