# Colophon OpenCode Provider Implementation Plan

**Goal:** Add OpenCode sessions, turns, tools, subagents, archive state, tokens and recorded cost estimates to Colophon's offline page and CLI summary.

**Scope:** This document is the deliverable; code implementation is outside its review. Follow the repository's `agents.md` and project documentation.

Commands run from `colophon/` unless marked **repository root**. Read `README.md` and its documentation chain. Follow `docs/development.md` and `tests/README.md` for the project's venv, setup, wrappers and validation; do not invent dependency repair steps from an installed-package mismatch.

## Source anchors

The upstream pin is Homebrew OpenCode **2.0.32**. Inspect its bundled public code with `strings -n 6 "$(brew --prefix opencode)/bin/opencode" > <private-scratch>/opencode-strings.txt`, first confirming the installed formula version. If unavailable, obtain that version's public source before implementing the reader. Never substitute private databases for source inspection.

The following symbols/search strings locate authoritative upstream definitions. The contracts below specify proposed Colophon behavior. Upstream field definitions belong in the synthetic schema fixture and parser tests rather than a prose schema copy.

| Anchor | Source |
| --- | --- |
| `db-path` | Function containing `process.env.OPENCODE_DB??`; data-path initialization using `XDG_DATA_HOME` |
| `schema` | Migration SQL containing ``CREATE TABLE `session_v2` `` and ``CREATE TABLE `session_message` ``; migration `20261010180456_project_time_archived` |
| `migration` | `migration.v1-v2`, `Previous V2 database contains V1-only session history`, `opencode-next.db` |
| `messages` | Schema identifiers `Session.Message.Info`, `Session.Message.Assistant`, `Session.Message.Compaction.Completed`, `Session.Message.Compaction.Failed`, `Session.Message.Idle` |
| `tools` | `Session.Message.Assistant.Tool`, `Session.Message.ToolState.*`; subagent metadata producers using `sessionID` and legacy `sessionId` |
| `usage` | `SessionProjector.publishUsage`, projectors for step completion/failure and `session.usage.recorded`, and their helper updating session totals |
| `forks` | `SessionProjector.projectFork` |
| `revert` | Projector containing `Revert boundary message not found` |
| `stats` | Stats SQL containing `session.fork_session_id IS NULL OR message.time_created >= session.time_created` |
| `archive` | Session/project archive projectors; project sweep containing `time_archived:Date.now()` |
| `titles` | Placeholder constructors containing `New session - ` and `Child session - ` |
| `continue` | CLI `--session` option and its lookup/create handler |
| `credentials` | Migration definitions for `account`, `control_account`, `credential`; excluded from Colophon's reader |

Colophon integration anchors: `cli_run` in `src/cli/run.c`; `SessionModel` in `src/corpus/assemble.h`; `UsageUnit`/`compose_aggregate_session` in `src/price/compose.h`; `read_database`/`metadata_database_uri` in `src/meta/metadata.c`; provider branches in `src/out/session_payload.c`, `src/price/compose.c` and `assets/page.js`. Recheck symbols before editing; line numbers are not interfaces.

## Design decisions

### Recorded cost

Use valid OpenCode-recorded request costs. Add no repricing resolver and do not read its cached model catalog. Missing/invalid cost stays unpriced; explicit recorded zero is priced zero. Keep this provider independent of Codex ledger availability and Claude pricing. Identify these values as OpenCode catalog estimates, not invoices or Colophon rate-period lookups.

### Residual accounting

**Task: Usage** owns residual accounting and its date convention. A residual does not prove title, compaction or revert ownership or an event date.

### Schema boundary

Read v2 only. The fixture's required query columns govern compatibility; archive columns and `fork_session_id` are optional. Require completed `migration.v1-v2` when legacy `session` exists; missing/malformed phase is unsupported. Reject unfamiliar `migration.*` keys and session-generation tables. Allowed session table names: `session`, `session_v2`, `session_message`, `session_share`, `session_inbox`, `session_pending`. A migration id sorting after the `schema` pin produces an untested-schema warning when structural guards pass.

Legacy JSON and v1-only databases are unsupported, not extra providers. Preserve database-specific incompatibility reasons.

### Retention

Re-read databases each run, with no OpenCode parse cache or retained store. Deleted sessions disappear with their usage. Removed messages can contribute a residual only while their session row/totals remain. Discovery and duplicate precedence are defined in **Task: Integration**.

### Display and actions

Use payload id `opencode`, name `OpenCode`. Provider order is Codex, Claude, OpenCode, including calendar metric ties. Violet CSS tokens: `--o:#d7a6ff`, heat ramp `#2e2142`, `#533a7a`, `#8f68c6`, `#d7a6ff`, bar `#533a7a` to `var(--o)`.

Offer Copy session ID; omit Codex links and Copy log path. Keep OpenCode continuation capability disabled until **Continuation acceptance** succeeds. Preserve each row's absolute source database as `opencode_database`, so a later enabled command can target that database explicitly. Archived sessions, project-archived sessions and subagents remain ineligible. Desktop-specific discovery remains outside verified support.

## Shared constraints

- Follow `agents.md`'s public-repository and synthetic-data requirements. Generate runtime fixtures/evidence in wrapper scratch. The schema-only SQL fixture is a documented exception, containing no real rows.
- Use `src/meta/metadata.c::read_database` for database-opening behavior and `docs/runtime.md` for its coordination-side-file contract.
- Install an authorizer before queries. Allow SELECT, transaction and function actions; READ only on `project`, `session_v2`, `session_message`, `migration`, `kv`, `sqlite_master`/`sqlite_schema`; PRAGMA only for `table_info` on these tables. Deny other actions. Inspect legacy/generation presence through schema names rather than their contents. Query needed migration keys from `kv`, never arbitrary values.
- Stage each database's facts and diagnostics independently. Publish only after its read transaction finishes. SQLite failure makes that database unreadable and discards staged facts; keep its reason and other databases. Map SQLite out-of-memory to `ERR_NOMEM` and abort; propagate allocation failures. Cancellation follows `cli_run`'s interruption path rather than becoming a source warning.
- Validate SQLite/JSON scalar types before conversion. Token components must be exact nonnegative integers within signed 64-bit range. Missing optional components default to zero; invalid optional components invalidate the tuple. Costs are finite nonnegative numbers, excluding booleans. Invalid clocks remain absent. Diagnose malformed/numeric input rather than fabricate values. Accumulate tokens in aligned `__int128` storage with checked additions.
- Reuse existing stable sort, arena/vector, numeric and graph helpers. Destroy map nodes separately from arenas, including error paths.
- Preserve Codex/Claude row semantics and counters. Additive metadata/diagnostics/summary, help/version changes and new source controls are expected. Compare parsed provider payloads in regressions rather than demand identical whole-page bytes.
- Proposed release: **0.4.0**. Update active declarations in `src/cli/args.c`, `src/out/payload.c`, `tests/test_cli.py`, the current-version statement in `docs/runtime.md`, `../tools/deploy_colophon.mjs` and `../tools/tests/deploy_colophon.test.mjs`. Search for additional active declarations before release; preserve historical release notes.
- Apply **Release validation** after each executable deliverable and at final handoff. Keep asset digests synchronized through the asset workflow in project documentation.

## Task: Database reader

**Files:** create `src/opencode/db.{c,h}`, `tests/fixtures/opencode/{schema_v2.sql,README.md}`, `tests/unit/opencode_fixture.{c,h}`, `tests/unit/test_opencode_db.c`. Update fixture policy in `tests/README.md` and the module table in `docs/architecture.md`.

**Public interface:**

```c
Err opencode_store_add_database(OpencodeStore *store, Str path, bool primary);
Err opencode_db_open(const char *path, sqlite3 **out);
Err opencode_store_read(OpencodeStore *store, volatile sig_atomic_t *interrupted);
void opencode_store_destroy(OpencodeStore *store);
```

Define new owned types in `db.h`, using existing vector conventions:

- `OpencodeDatabase`: path, primary flag, status/reason, latest migration id, untested flag, accepted session/message counts. Status enum: `OC_DB_OK`, `OC_DB_ABSENT`, `OC_DB_UNREADABLE`, `OC_DB_UNSUPPORTED`, `OC_DB_SKIPPED`.
- `OpencodeTokens`: raw input, output, reasoning, cache-read and cache-write components.
- `OpencodeTool`: id, name, child-session id, failed flag and clocks.
- `OpencodeMessage`: kind, row id/type/seq, row creation clock, payload clocks, text/images, model/provider ids, finish/error/outcome/status, independent token/cost validity, tuple/cost, tools and later-populated turn/inherited fields.
- `OpencodeSession`: identity/provenance, parent/fork/project ids, directory/title/agent/model/version, archive flags, clocks, rollup tokens/cost with independent validity, messages and malformed/numeric diagnostics.
- `OpencodeStore`: arena, discovery state, database/session vectors, diagnostics and usage report from **Task: Usage**; explicitly own map nodes and teardown.

Retain row id and creation clock separately from payload JSON. Use row identity for turns and row clock for inheritance, including copied JSON with a parent's id. Display time uses valid payload clocks, falling back to row time.

Build minimal synthetic DDL from `schema`, preserving relevant types, nullability and constraints. Record required/optional query columns in its README. Select columns explicitly and synthesize null for absent optional columns. Left-join project metadata so a missing project cannot silently drop a session. Define query-column/compatibility lists once in code and reuse them.

Read sessions by id and messages by session id/seq. Parse `messages`' actual type strings; compare tool status to its serialized literal, not its schema identifier. Unknown message/content types get separate count maps and preserve the session. Malformed recognized rows are excluded from message projection and diagnosed. Unknown/malformed rows make residual provenance incomplete. Tokens and cost validate independently; invalid tokens cannot erase valid cost. Join assistant text content; derive user images from image MIME entries and child references from `tools`. Exclude credential content from facts and error messages.

Tests in `test_opencode_db.c`:

- `opencode_db_reads_v2_sessions_messages_and_archive`: message order/kinds, images, assistant/compaction accounting, current/legacy child metadata and serialized tool failures.
- `opencode_db_known_types_are_not_unknown`: pinned recognized union, unfamiliar messages/content and malformed input.
- `opencode_db_numeric_validation`: missing versus invalid components, types, fractions, oversized integers, negative/nonfinite cost, nullable model/title and malformed clocks.
- `opencode_db_authorizer_denies_credentials`: intended queries succeed; credential SELECT, ATTACH, writes and disallowed PRAGMAs fail; synthetic canaries never enter outputs.
- `opencode_db_schema_guards`: migration phases, v1-only, missing/optional columns, unfamiliar generation/table/key and untested migration; rejected databases publish no sessions.
- `opencode_db_deduplication_commits_only_successful_databases`: failed reads cannot reserve ids or leak partial counters against a valid sibling.
- `opencode_db_lock_and_snapshot`: timeout/unreadable, committed WAL visibility, non-database siblings, unchanged main/WAL bytes and the documented shared-memory allowance.
- `opencode_db_cancellation_and_cleanup`: cancellation between/within queries, repeated success/failure descriptor checks following `tests/unit/test_metadata.c`, and map cleanup.

- [ ] Add tests and observe the intended failure with `make test-unit`.
- [ ] Implement reader/fixtures and named documentation.
- [ ] Apply **Release validation**.

## Task: Provider seams

**Files:** create `src/corpus/provider.{c,h}`, `tests/unit/test_provider.c`; modify `src/corpus/assemble.h`, `src/claude/parse.c`, `src/out/session_payload.c`, `src/price/compose.c`, `src/cli/summary.c`, `docs/architecture.md`.

Add `PROVIDER_OPENCODE` and `SessionModel.archive_reason`, owned by the corpus arena and empty for existing providers. Add:

```c
Str provider_id(Provider provider);
Err corpus_turn_tools_adopt(Arena *arena, SessionModel *session,
                           TurnModel *turn, const CorpusTools *source);
void corpus_status_flags(SessionModel *session, Str status);
Err corpus_session_idle(Arena *arena, SessionModel *session);
```

Extract behavior from `claude_corpus_add`'s tool adoption, flags and idle calculation; make Claude call those helpers. Preserve alignment, map ownership and outputs.

Make `compose_usage` skip non-Codex sessions and `compose_refresh_costs` use ledger availability only for Codex. Serialize row/bucket provider strings through `provider_id`; preserve tier meanings. Generalize the Claude orphan/label serialization path to non-Codex subagents. Summary counter selection must be explicit per provider.

Tests: `provider_ids_cover_every_provider`, `compose_skips_opencode_and_prices_authored_units`, `payload_sessions_emits_opencode_provider`, `provider_helpers_preserve_claude`, `provider_archive_reason_is_additive`. Exercise unit aggregation/cost refresh with unavailable Codex ledger and bucket-provider serialization.

- [ ] Add tests; observe the intended failure with `make test-unit`.
- [ ] Implement extraction/seams and documentation.
- [ ] Apply **Release validation**, retaining legacy semantic assertions.

## Task: Corpus

**Files:** create `src/opencode/corpus.{c,h}`, `tests/unit/test_opencode_corpus.c`.

```c
Err opencode_corpus_add(OpencodeStore *store, int64_t snapshot, Corpus *corpus);
```

For accepted sessions, reject ids colliding with corpus keys or existing public `SessionModel.id` values, recording the collision. New sessions use the OpenCode enum, source session id for id/key/identity, kind `session`, empty log path and cwd only for a valid absolute directory. Preserve fork metadata as `forked_from`/`F_FORKED`; forks alone are not subagents. Keep source database provenance available for payload serialization as defined under **Display and actions**.

Mark inherited only when the session has a fork id and the row clock precedes session creation (`forks`/`stats`). Exclude inherited messages from prompts, turns, tools, usage and answers. Missing clocks cannot prove inheritance: keep the row and diagnose unavailable timing.

Each remaining user opens a turn keyed `opencode-turn-N`; row id becomes `TurnFact.turn_id`. Attach subsequent messages to that display turn; leading assistant/compaction usage stays outside turns. Construct request/timing facts as the Claude turn builder and `finish` do. Session end uses latest valid message time, falling back to session update time. Missing source clocks stay unknown, not epoch zero. Answer is last nonempty assistant text. Proposed end-state mapping:

| Last relevant message | end_kind |
| --- | --- |
| idle succeeded | completed |
| idle failed | aborted |
| idle interrupted, or assistant error type aborted | interrupted |
| assistant with another nonempty error type | aborted |
| completed assistant, nonempty finish other than tool-calls | completed |
| otherwise | open |

Pass facts through `turn_models` and adopt its displayed-turn timing/status policy, including open turns with known source clocks. Its modification-time input uses valid session update time, else session end, else snapshot with an unknown-clock diagnostic. Source fact clocks remain independent of the helper's displayed intervals. Adopt tools, status and idle through provider helpers.

Map names into `claude_tool_count`'s vocabulary: shell/bash to Bash; edit/patch/apply_patch to Edit; write to Write; multiedit to MultiEdit; webfetch to WebFetch; websearch to WebSearch. Other names follow its other/MCP classification. Choose a meaningful non-placeholder title (`titles`), else first request, else id; call `title_display`.

Set archived from session OR project. Archive reason precedence: `session` when the session flag is set; otherwise `project` when the project flag is set; otherwise empty. The project-only tag is `ARCHIVED (PROJECT)`.

Build an OpenCode-only parent map. A nonempty source parent id sets `is_subagent`/`has_link` and kind `subagent`; set `agent_label` from the chosen title and `meta.agent_nickname` from the source agent. Resolve candidate parent ids, then call `corpus_graph_break_cycles` before constructing children/depths. Finalize as `src/claude/parse.c::link_records` does: append linked children to parent `children`, derive depths on the acyclic graph and call `corpus_children_order`. Missing/cycle-broken parents retain subagent identity, become orphan and are diagnosed. Assign spawn_turn/link_method `tool_use` and turn `spawned` only for unique parent-turn evidence; diagnose conflicting references instead of choosing arbitrarily.

Tests: `opencode_corpus_turns_and_status`, `opencode_corpus_open_turn_known_clocks`, `opencode_corpus_tool_mapping`, `opencode_corpus_archive_precedence`, `opencode_corpus_parent_children_depth_and_spawn`, `opencode_corpus_missing_and_cyclic_parents`, `opencode_corpus_public_id_collisions`, `opencode_corpus_placeholder_titles`, `opencode_corpus_fork_row_identity_and_inheritance`, `opencode_corpus_leading_usage`, `opencode_corpus_unknown_clocks_and_relative_cwd`. Timing and cycle expectations follow the shared helpers. Assert parent/child payload traversal and labels, out-of-order parents and ambiguous spawn evidence.

- [ ] Add in-memory store tests; observe the intended failure with `make test-unit`.
- [ ] Implement projection.
- [ ] Apply **Release validation**.

## Task: Usage

**Files:** create `src/opencode/compose.{c,h}`, `tests/unit/test_opencode_usage.c`; modify shared cost aggregation in `src/price/compose.c`. Add enduring OpenCode policy to `docs/token_rules.md` with implementation/test anchors, not a dependency on this temporary plan.

```c
Err opencode_compose(OpencodeStore *store, Corpus *corpus);
```

Store-owned `OpencodeUsageReport` tracks request/missing-usage/inherited/residual counters, missing usage by provider, residuals by session and shortfalls. Diagnostic shapes are owned by **Task: Integration**.

Take non-inherited assistants and completed/failed compactions belonging to inserted sessions; count them as requests. Count missing/invalid token tuples separately, including explicit all-zero tokens with missing/zero cost. Keep valid positive cost without usable tokens as a diagnosed cost-only unit. Do not infer its tokens/model from session totals. Explicit zero-token/zero-cost rows need no unit; positive-token/zero-cost rows remain priced. Inherited rows increment only their diagnostic.

Author units with this proposed mapping, leaving priority/fast/rate-period fields unset:

| UsageUnit field | Value |
| --- | --- |
| input | raw input + cache read + cache write |
| cached / cache_write / cache_write_1h | raw cache read / raw cache write / zero |
| output / reasoning | raw output + reasoning / present raw reasoning |
| model_raw, model | provider/model when available, otherwise `opencode/unattributed` |
| source | opencode |
| at_ms, timestamp_ms | completion clock, otherwise creation clock |
| display_turn | display-turn key or empty |
| has_cost, cost_usd | independent validated recorded cost |

Residual algorithm:

- Sum emitted units in message-seq order in raw component space, with checked wide integers and checked double cost addition. Cost-only units participate in cost sums. Invalid rollup tokens disable token residuals; invalid rollup cost disables cost residuals, with diagnostics. Apply **Cost aggregate failure** before residual arithmetic.
- Subtract sums from rollups. Absolute cost differences within `1e-9` count as zero. Diagnose negative differences and keep message units; never subtract usage. Clamp residual components to positive differences.
- For remaining positive differences, append a residual unit using the mapping table, unattributed model and empty turn. Date it at session start as a display convention; missing start stays untimed.
- A positive cost residual has known cost. A token-only residual has known zero cost only when rollup cost is valid, its difference is within tolerance, eligible message costs were valid, and no malformed/unknown row or cost-only unit left token attribution incomplete. Otherwise its cost is unknown. Existence of a residual cannot establish `has_cost`.
- Diagnostics preserve raw components, nullable cost, display date and `date_basis=session_start`, following the residual dating rule. Call `compose_aggregate_session` even without units. Final cost refresh follows integration.

### Cost aggregate failure

Check finiteness after cost addition/subtraction, including residual arithmetic, before passing OpenCode units into shared aggregation. If an accepted session's message costs cannot be summed, retain its token units, set their costs unavailable and suppress cost residuals for that session; preserve recorded facts in the store and emit `opencode_invalid_numbers` with aggregate context. Never replace an overflow with zero or serialize a nonfinite value.

Shared aggregation/cost-refresh must also guard session, turn and bucket cost sums and mark only the affected summary unavailable. Provider-summary and page cost aggregates must guard cross-session/mixed-provider sums and show unavailable with a contextual diagnostic rather than Infinity. Do not discard independently valid provider/session costs. This requires targeted guards in `src/price/compose.c`, `src/cli/summary.c` and the page cost aggregation path, covered by the regression below; preserve existing valid-input behavior.

Rollup equality is an acceptance check for valid synthetic sessions without shortfalls, not a claim for malformed/unknown/incomplete/conflicting data. Keep such differences visible.

Tests: `opencode_usage_component_mapping`, `opencode_usage_compaction`, `opencode_usage_missing_and_explicit_zero_cost`, `opencode_usage_cost_without_tokens`, `opencode_usage_missing_usage_by_provider`, `opencode_usage_residual_components_and_date`, `opencode_usage_residual_unknown_cost`, `opencode_usage_residual_known_zero_cost`, `opencode_usage_rounding_and_shortfalls`, `opencode_usage_invalid_rollups_and_overflow`, `opencode_usage_finite_cost_aggregate_overflow`, `opencode_usage_fork_inheritance`, `opencode_usage_codex_ledger_independence`. Keep invented numeric inputs/outputs in tests; cover token-only, cost-only, mixed-sign differences and removed-message/deleted-session rebuilds. The unit cost-overflow regression exercises shared composition/refresh; its CLI and browser counterparts belong to their integration deliverables and enforce **Cost aggregate failure** through payload generation and mixed-provider rendering.

- [ ] Add tests; observe the intended failure with `make test-unit`.
- [ ] Implement composition/accounting docs.
- [ ] Apply **Release validation**.

## Task: Integration

**Files:** create `src/opencode/scan.{c,h}`, `tests/test_opencode.py`. Modify `src/cli/{args.h,args.c,run.c,summary.c}`, `src/out/{payload.h,payload.c,session_payload.c}`, test helpers/wrappers/sandbox/Makefile, active version declarations in **Shared constraints**, and project README/runtime/development/architecture/tests docs.

Add `Args.opencode_db`, `Args.no_opencode`, `PayloadInputs.opencode`, `Err opencode_discover(const Args *, OpencodeStore *)`. Add flags `--opencode-db PATH` and `--no-opencode` with explicit dispatch; derive parser bounds from the option array and keep order stable. Help documents flags/environment inputs. Pin ambiguity candidate sets, including existing `--no` and new `--no-op`/`--o`, and test missing/explicit values.

**Discovery contract:**

- Disabled returns before source inspection.
- Explicit DB flag uses `file_expand_path` and selects only that file. Relative flag resolves against cwd; reject `:memory:` as a file override with an argument error.
- Otherwise choose nonempty `XDG_DATA_HOME` plus `opencode`, or the default under HOME (`db-path`). Resolve relative environment paths against cwd. `OPENCODE_DB` chooses primary, relative to data directory when needed; an empty value is an invalid candidate with a reason. `:memory:` suppresses primary.
- Add regular sibling `opencode-*.db` files sorted by path; include default `opencode.db` when distinct from an overridden file primary, excluding it when the override is `:memory:`. Deduplicate normalized paths. Prefer primary sessions, then ascending paths. `opencode-next.db` is skipped even when explicit; `migration` owns its import. Do not broaden the glob to unrelated filenames.
- Missing candidates stay absent; existing inaccessible candidates/discovery failures become unreadable with reasons. Presence for runtime gating means a non-skipped existing candidate or discovery error needing a report. An absent empty directory alone is insufficient. Unsupported/unreadable-only input may build a diagnostic page.

Call discovery/read after `claude_scan_aliases`, before runtime creation; extend the source gate with OpenCode presence. An all-absent/disabled run preserves no-runtime behavior and names checked paths. Add corpus sessions after `claude_metadata_apply`, before workspaces; compose after `claude_price_units`, before `compose_refresh_costs`. Destroy store after corpus teardown and on failures.

**Payload contract:**

`meta.sources.opencode`: status, data_dir, databases, sessions, subagents, archived, requests, requests_without_usage, residual_sessions, cached, costs. Database entries expose `OpencodeDatabase` fields. Counters describe accepted/deduplicated/inserted facts; excluded collisions do not count as displayed sessions. Cached is zero; engine cost availability is true/null reason, while missing unit costs remain unpriced. Status: disabled; otherwise ok if a database succeeded; otherwise unsupported if structural rejection occurred; otherwise unreadable for attempted/discovery failures; otherwise absent. Skipped candidates do not establish presence.

Expose archive reason per **Task: Corpus** and row provenance/capability fields per **Display and actions**. Authoritative diagnostics:

| Keys | Shape |
| --- | --- |
| opencode_schema_errors, opencode_unreadable_databases | path/reason object lists |
| opencode_untested_schema | path/latest_migration object list |
| opencode_session_id_collisions, opencode_duplicate_sessions, opencode_orphaned_subagents, opencode_spawn_conflicts, opencode_rollup_shortfalls, opencode_invalid_numbers | contextual session/database/reason lists |
| opencode_unknown_message_types, opencode_unknown_content_types, opencode_requests_without_usage | count maps; absent provider uses `opencode/unattributed` |
| opencode_rollup_residuals | session map with **Task: Usage** residual fields |
| opencode_malformed_messages, opencode_inherited_messages, opencode_cost_without_tokens | counts |

Feed these shapes to stderr and page footer: list lengths, sums of count-map values and residual session counts. Unless disabled, print provider summary with accepted provider counters/database counts and cost formatting as `provider_summary` does. Append non-ok status/reasons. Partial-source errors and skipped preview details remain visible even with aggregate ok; include skipped entries in a database-details footer. Sanitize line breaks in CLI reasons through the existing error-output convention.

**Isolation:** add real-home read/write denies and independently mutated probes, following the Claude-protection loop in `tests/run-pytest.sh`, for `.local/share/opencode`, `.local/state/opencode`, `.config/opencode`, `.cache/opencode`, `Library/Application Support/ai.opencode.desktop`. The test wrappers unset `OPENCODE_DB`/`XDG_DATA_HOME`; `NativeRun.env` removes them before intentional overrides. Keep canaries synthetic. Register the new pytest module in Makefile `test-cli`. DB helpers use this project's venv sqlite3/shared fixture under each test's scratch HOME.

CLI/integration tests must cover source-only/mixed builds; disabled/no-source/unsupported/unreadable and partial failures; diagnostics through stderr/payload; archive precedence; discovery precedence/path order/duplicates/preview; credential exclusion from page/runtime; rollback/WAL preservation; locked source with a working provider; runtime modes; and unopened Codex cache preservation during normal/rebuild runs. Implement the CLI **Cost aggregate failure** guard/regression here. Name cases by behavior. `test_sandbox_opencode_paths_denied` needs assertion/mutation pairing as the existing sandbox probe does.

- [ ] Add tests; observe relevant failure with `make test-cli PYTEST_ARGS='-k "opencode or help_and_version or invalid_options"'`.
- [ ] Implement integration/version/docs.
- [ ] Apply **Release validation**. Do not change shared audit/runner merely to update a version expectation.

## Task: Page

**Files:** `assets/{page.js,page.css,MANIFEST}`, `tests/test_browser.py`, `README.md`, `docs/runtime.md`.

Define `PROVIDERS`/`PROVIDER_NAMES` from **Display and actions**. Derive controls, source normalization, availability fallbacks, snapshots, KPI/workspace shares, model tags and calendar dominance from these definitions. Apply provider filtering to direct reader hashes and descendants. Restrict Claude boundary notes to Claude/all views. Use payload fields for archive display and action eligibility.

`sourceAbsence` must distinguish disabled (name flag), absent (checked paths/data dir), unsupported and unreadable (database reasons). Render partial/preview details via **Payload contract**, including a database-details footer rather than losing skipped sources.

Handle diagnostic object/count-map shapes structurally in `diagnosticCount`, `diagnosticItems` and `diagnosticText`. Explain schema/unknown-format warnings, missing usage, cost-only units and residuals. Residual wording follows **Residual accounting**. Never stringify nested objects as `[object Object]`.

Update `usageRateTooltip` and `rateTooltip`: OpenCode recorded-estimate provenance must not produce invented rate-period warnings. Mixed-provider/model tooltips retain genuine Codex/Claude warnings and missing-cost indicators. Cover reader/turn/outside-turn and overview models. Add violet provider/source CSS through **Display and actions** and update MANIFEST.

Use `source_page`, `open_native`, `guard_browser_errors` as existing browser cases do; require no external requests. Add cases for source/hash/filter preservation, direct subagent filtering, KPI/workspace shares including zero totals, calendar ties, selected color, archive toggle/tags, source states/partial failures, structured footer/preview, tooltips with mixed models, native DB-to-page integration and narrow viewport layout. Implement the page **Cost aggregate failure** guard/regression here. Before enabling continuation, add copied-command shell round-trip tests with quotes/metacharacters, unusable/control-character cwd rejection, source database targeting and independent lifecycle/subagent restrictions.

- [ ] Add tests; observe intended failure with `make test-browser PYTEST_ARGS='-k "opencode or provider_shares"'`.
- [ ] Implement page/CSS, digest updates and docs.
- [ ] Complete **Release validation**.

## Continuation acceptance

This gate verifies the action described in **Display and actions**, beyond synthetic rendering/quoting tests. Follow `docs/LESSONS_LEARNED.md`'s action-acceptance requirements.

Use disposable synthetic OpenCode sessions/databases outside the repository, with source fingerprints before/after, a known cwd and database target, and the pinned CLI. Confirm that copying never runs a command. Deliberately execute only against disposable targets; prove the existing id resumes in the originating database without creating another session. Check overridden and sibling database sources, existing-service behavior and the exact CLI launch mode needed to honor `OPENCODE_DB`. Private sessions are not acceptance fixtures.

The candidate copied command is `cd <quoted-cwd> && OPENCODE_DB=<quoted-absolute-db> opencode --session <quoted-id>`, using `shellArgument` for substituted values. An existing service ignoring the target or a required unverified launch mode fails this gate. Record verified lifecycle, routing and CLI version in runtime docs before enabling the capability under **Display and actions**; report an unmet gate at handoff.

## Release validation

After an executable deliverable, run the full affected-project suite from `agents.md`'s Testing Scope and Validation Matrix. At final handoff, also complete the build, sanitizer, local-guard and offline CLI checks in `README.md`/`docs/development.md`. Deployment version-check edits require the root Static deployment/fleet audit tooling suites from `agents.md`. These references own the commands; targeted task checks do not replace them. Require successful categories and no sanitizer reports; report failures with output.

Compare active source declarations, synthetic payload and browser-displayed version with **Shared constraints**. Inspect the diff for scope, changed legacy assertions and sensitive data. Completion of this document does not mean implementation tests ran.

Real-data comparison and installation are separate authorized gates. If requested, keep evidence outside the repository. Compare per-session/component totals using a coordinated read-only snapshot. Use `stats` to align database/provider/date/fork/message-kind scope. Explain residuals, shortfalls, inherited exclusions and unsupported/malformed inputs. A separate stats process may see another snapshot; do not demand a fixed delta or unconditional equality. Do not start its service against private data without authorization.

When deployment is requested, follow `../docs/local_deployment_sync.md`'s native Colophon workflow; verify installed bytes, modes, receipt and version. Recheck browser version after opening the new page. Repository edits alone do not establish installed acceptance.
