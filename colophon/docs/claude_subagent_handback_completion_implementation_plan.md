# Claude subagent handback completion: implementation plan

Status: reviewed execution requirements. The user has separately requested
implementation and shipping through `$ship-plan`.

## Goal and source references

Recognize successful `SubagentHandback` results as Claude subagent turn
completion, capture the handback report, and invalidate stale live parse-cache
records. Do not read private transcripts to implement or validate this change.

Check current behavior at `src/claude/parse.c::on_record` and `finish`,
`src/corpus/turnstatus.c::turn_models`, and
`src/claude/store.c::claude_store_get`. Follow the cache lifecycle in
`docs/runtime.md#claude-parse-cache-and-retained-transcripts`, the codec rule in
`docs/development.md`, and the fixture policy in
`tests/fixtures/claude_codec/README.md`. These references replace a duplicated
description of existing behavior; the requirements below specify the change.

## Global constraints and decisions

- **Completion:** Only in a subagent record (`parent_session.p` set), a user
  `tool_result` matching an earlier assistant `SubagentHandback` call in the
  current turn sets `p->completed` when `is_error` is not JSON `true`.
  Consume the pending ID when a result arrives, including an error. Clear
  pending handback IDs on a new prompt. Delayed results and duplicate results
  must not complete a later turn or undo a later assistant stop decision.
- **Later events:** Continue applying `on_record`'s assistant stop-reason,
  prompt, interruption and error rules. Let `finish` assign the end clock as
  it does today. Do not change the unknown-record classification in this fix.
- **Answer:** A subagent's assistant handback call with a nonempty string
  `input.message` sets the current answer and its clock. Later text answers
  retain their existing replacement behavior. Missing, empty or nonstring
  handback messages leave the existing answer alone. Main sessions receive
  neither handback completion nor handback answer handling. This answer
  behavior is part of the requested release scope.
- **Cache:** Introduce `CLAUDE_PARSE_REVISION` with initial value `1`, persist
  it per `ClaudeRecord` in CLCD3, and reject live hits with an older revision.
  Preserve older decoders and immutable inputs. Retained records keep their
  stored facts; do not invent a repair when their transcripts are unavailable.
  Use a per-record revision rather than repurposing `reader_facts`, a global
  marker, or decode-time status repair. Reparse must follow the existing
  commit/retention rules referenced above.
- **Pricing:** Document the reparse effect by reference to
  `docs/token_rules.md#claude-pricing-and-public-seed-provenance` and
  `src/price/claude_cost.c`. A parser revision can recapture extraction-time
  snapshots; do not promise unchanged costs.
- **Rollback:** Document CLCD3 incompatibility with earlier decoders. Describe
  the operational consequence using `src/claude/store.c::inventory` and its
  unreadable-record handling: available transcripts can be reparsed, while
  undecodable records cannot supply retained facts. Do not delete those files.
- **Release:** Ship the tasks together as patch release `0.8.4`.
- **Validation:** Use conspicuously synthetic inputs in private OS temporary
  space. Preserve the project's sandbox, test framework, logging, source
  protection and runtime isolation. The immutable codec fixture is the
  documented exception to temporary fixture storage. Do not run the owner's
  page or acquire private/provider data.

## Task 1: Complete Claude subagent turns at handback

Implement **Completion**, **Later events**, and **Answer** in
`src/claude/parse.c`, with regression coverage and behavior documentation.

### Tests first

In `tests/unit/test_claude_parse.c`, add
`parse_subagent_text(const char *bytes, ClaudeRecord *out)` following
`claude_subagent_filename_uses_parent_identity`. Use an owned `mkdtemp`
directory under `$COLOPHON_HOME`, a fictional parent and child filename, and
remove every file and directory created by the helper. Every synthetic row
has an RFC 3339 clock.

Add named tests for:

- Handback calls with `tool_use` and null stop reasons followed by a matching
  successful result: completed, end at result, answer from call, answer clock
  at call.
- An error result, no result, and a foreign ID: open; a valid handback message
  is still captured as the answer.
- A trailing timestamped unknown record: completed, end at that record.
- A later `end_turn` text: completed, latest text answer.
- A later unresolved assistant tool call: open.
- A new prompt followed by `end_turn`: independent completed turns.
- A delayed result after a new prompt: new turn remains open.
- A duplicate result after a later unresolved assistant tool call: remains
  open because the first result consumed the ID.
- An error followed by a duplicate success for the same ID: remains open.
- Missing, empty and nonstring handback messages: preserve the prior answer.
- The successful-handback rows parsed through the main-session helper: open
  and no handback answer.

Give these tests stable descriptive names, using a
`claude_subagent_handback_` prefix. The named tests own their fictional IDs,
message text and clocks; fixture export and migration tests reuse that named
successful-handback scenario rather than maintaining separate prose values.
Assert handback tool counting remains intact in cases containing a call.
Assert end clocks for completed turns and answer clocks when present. Separate
answer assertions from completion assertions so a failure in one does not hide
coverage of the other.

In `tests/test_claude_store.py`, create a parent with
`NativeRun.claude_session` and its synthetic handback child beneath that
parent's subagent path. Set transcript clocks and mtime older than the quiet
threshold. Assert the emitted child turn is completed, duration is result
minus prompt, the handback answer is present, and the child has no abandoned
flag. Keep input strings distinct from the status string used by the stale-cache
migration test.

Run `make test-unit` and `make test-cli` before implementation. Record actual
failures for the new completion and answer behavior. Preservation cases such
as later `end_turn` may already pass; do not require them to fail.

### Implementation and docs

Add an `Omap handback_ids` beside `Parse.shell_ids`. Register nonempty IDs
only for subagent assistant handback calls. Check insertion errors with
`TRY(omap_put(...))`. Apply **Answer** using the existing arena-copy and
answer-clock mechanisms. In `tool_result` handling, read `tool_use_id` once,
keep the shell-failure behavior, and apply **Completion**. Destroy the map on
new prompts and on parser teardown, including reader-error exits. Keep the
existing tool-counting path.

Document the new user-visible rules beside the Claude subagent paragraph in
`docs/runtime.md`, referring to `corpus_quiet` for quiet handling. Add a short
lesson in `docs/LESSONS_LEARNED.md` about protocol completion/answers moving
into tool messages and requiring synthetic transcript coverage.

### Acceptance

Run every command in the root repository Validation Matrix's `colophon`
entry. Commit this task with its tests and docs, but release it only with
the cache migration and release task. Use full-suite results in the task report.

## Task 2: Reparse stale Claude cache records and release

Implement **Cache**, **Pricing**, **Rollback**, and **Release**.

### Capture the immutable CLCD2 input before changing the codec

Follow the fixture policy referenced above. Add a temporary unit test beside
the parser task's helper. Parse its named successful-handback transcript, reset
the turn to open with absent end/answer/answer clock, and set every file
identity field to conspicuously fictional values: `key.path` under
`/synthetic/`, `search_root`, `size`, `mtime_ns`, `device`, and `inode`.
Leave subagent config provenance empty. Encode using the unchanged CLCD2
encoder, and print exactly one `SYNTHETIC_V2_HEX:` line containing lowercase
hex. A source reference alone cannot create this old-format input, so this
temporary export step is required.

Capture `make test-unit` stdout/stderr to an owned external temporary file
and require that command to succeed before extracting the line. Require
exactly one matching, nonempty, even-length hexadecimal string; decode it
with `xxd -r -p` into temporary space. Check the header and successful decode,
inspect the decoded values for only synthetic provenance, and search bytes
for real-user and temporary-root paths. Only then copy the verified bytes to
`tests/fixtures/claude_codec/synthetic-v2.rec`. Do not use a pipeline that
masks the test command's failure or truncates the destination before success.
Remove the temporary test and scratch. Retain the fixture unchanged thereafter.

### Code and test-first migration coverage

- In `src/claude/parse.h`, add `CLAUDE_PARSE_REVISION` pointing at the
  authoritative development rule, and a persisted `uint64_t parse_revision`
  beside `reader_facts`. Initialize it in `claude_parse`.
- In `src/claude/codec.c`, append a `record_v3` unsigned revision field after
  `record_v2`; emit CLCD3. Accept only CLCD1, CLCD2 and CLCD3 headers, run v2
  decoding for v2/v3, then v3 decoding for v3. Preserve checksum and final
  position validation. Older records default to revision zero.
- In `src/claude/store.c::claude_store_get`, add the older-revision miss
  condition beside the existing `reader_facts` condition.

Write the following migration tests before implementing the behavior they
exercise. Record meaningful red results; a missing new declaration may need
to land with its test so the test compiles before behavioral implementation.

- `tests/unit/test_claude_codec.c`: extend the round-trip test to assert the
  CLCD3 header and current revision; decode the immutable v2 fixture from
  scratch and assert reader facts, revision zero, synthetic identity and open
  turn; assert revision zero for the existing immutable v1 fixture. Reject a
  CLCD3 body missing its revision and a CLCD2 body with an extra revision,
  recomputing checksums as existing malformed-traversal tests do.
- `tests/unit/test_claude_store.c`: follow
  `claude_store_legacy_live_records_reparse_without_losing_retained_facts`
  using revision zero with reader facts present. Assert cold reparse, commit
  with the current revision, and subsequent cache hit. Keep a separate old
  retained-record case proving stored status survives. Update the linear
  reference predicate in `claude_store_index_matches_linear_reconciliation`.
- Extend the parser task's CLI test: identify its child's installed CLCD3 record by
  exact synthetic ID in the decoded array. Change the unique completed
  `end_kind` to open, replace the encoded end clock with absent using
  `record_v1`'s `TurnFact` order, remove the trailing revision, recompute the
  checksum and write CLCD2. Build without `--rebuild` and without touching
  transcript bytes or mtime. Require one reparsed child, corrected completion
  and duration; on a further warm build require cache hits and zero parses.
  The immutable input proves actual old-codec compatibility; this mutation
  proves stale cache behavior against the real unchanged transcript.

### Version and documentation

Set the **Release** version in maintained declarations and assertions found by
`rg -n '0\.8\.3' colophon tools --glob '!*_implementation_plan.md'`, including
the installer activation check and its test. Preserve the README historical
note and add the release note there.

Update `docs/development.md` with the authoritative rule: parsing changes
that alter stored Claude facts bump `CLAUDE_PARSE_REVISION`; stored-layout
changes also add a codec version. Update `docs/runtime.md`'s Claude cache
section for the new codec, live reparse until the revised record is successfully
installed, and the **Pricing** and
**Rollback** decisions. Add a reference to that revision rule in the Claude
cache discussion in `docs/architecture.md` and in the parser task's lesson. Update
`tests/fixtures/claude_codec/README.md` and the immutable-fixture paragraph in
`tests/README.md` for the added immutable input.

### Acceptance and shipping

Run every command in the root Validation Matrix's `colophon` and `Static
deployment/fleet audit tooling` entries. Apply consumer-suite requirements
only when their triggering shared code changes. Confirm `./colophon --version`
matches **Release**, and the version search leaves only the historical note.
Report each test category and any failure output. No private-data acceptance
or predictions about the owner's aggregate status/token totals are required.

After the combined change is merged, deploy from main via
`docs/local_deployment_sync.md#native-colophon-deployment`. Follow its audit
and the synthetic installed-build/version checks in `docs/development.md`.
Keep the owner's existing runtime page untouched.
