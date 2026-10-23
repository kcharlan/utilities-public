# Colophon: Antigravity provider implementation plan

Target release: **0.5.0**. Project: `colophon/` in `utilities-public`.

## Goal and boundaries

Read local Antigravity conversations and add sessions, turns, prompts, final
answers, tools, workspaces, archive state, request usage and API-equivalent
catalog estimates to Colophon. References to existing code mean “behave as that
symbol does”, with the adaptations specified here.

This release deliberately excludes legacy blob decoding, Gemini
CLI chat logs, roots outside [Source access](#source-access), subscription-credit
display. Reader actions and subagent linking follow [Payload and page](#payload-and-page)
and [Corpus projection](#corpus-projection). These are scope choices, not claims
that other transcripts or archive interfaces cannot exist. Integration and
deployment follow the user's already supplied authorization.

## Pinned references

- **Colophon baseline:** commit `d128427eed5f7b3c67a4d8455d3cf2b64583e8b9`.
  Paths below are relative to `colophon/` unless explicitly repository-root
  paths. Consult `README.md`, `docs/runtime.md`, `docs/architecture.md`,
  `docs/development.md`, `docs/token_rules.md`, `docs/LESSONS_LEARNED.md` and
  `tests/README.md` at that commit for maintained contracts.
- **CodexBar:** commit `e5d6977ba547aa7046eed3865f8ee1cdd5d58731`,
  [Sources/CodexBarCore/Providers/Antigravity](https://github.com/steipete/CodexBar/tree/e5d6977ba547aa7046eed3865f8ee1cdd5d58731/Sources/CodexBarCore/Providers/Antigravity).
  Use `AntigravityLocalReader.swift::{pricingBaseModelID,routingVariantSuffixes,pricingModelAliases,explicitCatalogEntries}`
  for normalization and `AntigravityProtoReader.swift` for wire-reader comparison.
- **ccusage behavior oracle:** native `@ccusage/ccusage-darwin-arm64` v20.0.42,
  SHA-256 `b0529e16d914b42d5f7cfb1b30cd318f520b776f93798a3219741b8589a648b3`.
  Set `CCUSAGE_ORACLE` to the supplied absolute executable path before replacing
  `HOME`. Verify hash, `--version` and `antigravity session --help`, copy into private
  acceptance scratch and invoke that absolute copy. Never use the shell
  `ccusage` wrapper or resolve `latest`. Proposed source pointers are
  [v20.0.42 rust/adapters/antigravity](https://github.com/ccusage/ccusage/tree/v20.0.42/rust/adapters/antigravity):
  `parser.rs::{parse_sqlite_file,append_usage_event,merge_usage_event,model_name_from_id}`,
  `loader.rs::deduplicate_events`, `paths.rs::DEFAULT_ANTIGRAVITY_ROOTS`.
  Rust source has not been independently located/verified. Do not claim its
  algorithms were source-verified; use the concrete synthetic probes under
  [Usage](#usage), or verify the pinned source before adaptation.
- **Public protobuf descriptors:** installed
  `/Applications/Antigravity.app/Contents/Resources/bin/language_server`, SHA-256
  `060ebf79719024f1b3acb52a21c7a182cb6466b2ac4ac25e93391169b1c1bb46`.
  Resolve fully qualified names and follow typed references; never select the
  first unqualified match. Persist public schema-only fixture definitions with
  this binary hash, behaving
  as `tests/fixtures/opencode/` does for provenance. Do not copy schema tables
  into this plan or another fact sheet.

## Authoritative new shared contracts

These decisions define new Colophon behavior. A source reference alone cannot
choose admitted paths, precedence, projection, accounting ownership, UI additions
or composition initialization; tasks refer here rather than repeat them.
Descriptors supply wire facts; named synthetic tests hold fixture values and
oracle observations. Operational evidence remains outside the public checkout.

### Source access

Resolve Gemini root `R` from `--antigravity-home PATH`, else `~/.gemini`.
Behave as OpenCode's explicit-path resolver for tilde/relative paths.
`--no-antigravity` suppresses inspection even with an invalid override; behave
as `test_opencode_disabled_never_reads_invalid_override` specifies. Do not honor
Antigravity/ccusage environment overrides. Record nonempty
`ANTIGRAVITY_GEMINI_DIR`, `ANTIGRAVITY_APP_DATA_DIR`, `JETSKI_APP_DATA_DIR`
in `ignored_environment` by name only, explaining the explicit flag remedy.

Surface order is `R/antigravity` (`app`), `R/antigravity-cli` (`cli`),
`R/antigravity-ide` (`ide`); sort database paths within a surface. First
accepted conversation ID wins; count duplicates as
`antigravity_duplicate_sessions`. Summary indexes never locate conversation
files or create sessions without an accepted database.
Absent/disabled Antigravity alone must not initialize a runtime when the shared
no-readable-sources gate would otherwise exit.

The source-file admission list is:

- Per surface: `conversations/<uuid>.db`, `annotations/<uuid>.pbtxt`,
  `conversation_summaries.db`.
- Associated SQLite `-wal`, `-shm`, `-journal` sidecars of an admitted database,
  including the summary index. Use ordinary coordinated read-only SQLite,
  behaving as `src/opencode/db.c::opencode_db_open` and the coordination contract
  in `docs/runtime.md`; do not use immutable mode or promise unchanged SHM bytes.
- Enumerate `conversations/<uuid>.pb` names only: count distinct IDs lacking a
  `.db` in the admitted surfaces as `legacy_encrypted`; do not decode/create rows.

Do not read credential/settings files, other Gemini subtrees or symlink escapes.
Read each database in a read transaction, without a database-file-size cap.
The SQL authorizer admits the selected projection and required schema inspection.
Required conversation projection:
`trajectory_meta(trajectory_id,cascade_id,trajectory_type,source)`,
`trajectory_metadata_blob(id,data)`,
`steps(idx,step_type,status,metadata,step_payload,step_format)`,
`gen_metadata(idx,data)`.
This is the new reader's required SQL shape, not a source-table inventory.
Missing required tables/columns make that database unsupported with a reason;
extra tables do not. The summary projection is
`conversation_summaries(conversation_id,title,raw_summary)`; absent `raw_summary`
allows title-only fallback. Never query FTS tables. Stage before acceptance;
failed siblings must not erase successful databases.

### Decoding and archive precedence

Decode `trajectory_metadata_blob.data` as
`.exa.cortex_pb.CortexTrajectoryMetadata`, following its workspace references to
`.exa.cortex_pb.CortexWorkspaceMetadata`. Decode `steps.metadata` as
`.exa.cortex_pb.CortexStepMetadata`, `steps.step_payload` as
`.gemini_coder.Step`, and `gen_metadata.data` as
`.exa.cortex_pb.CortexStepGeneratorMetadata`. Follow their typed references into
`.exa.cortex_pb.ChatModelMetadata`, `.exa.cortex_pb.RetryInfo`,
`.exa.codeium_common_pb.ModelUsageStats`, `.exa.codeium_common_pb.ModelInfo`,
`.exa.codeium_common_pb.Model`, `.exa.codeium_common_pb.ChatToolCall`,
`.exa.cortex_pb.CortexStepUserInput`, `.exa.cortex_pb.CortexStepPlannerResponse`,
`.exa.codeium_common_pb.TextOrScopeItem`, `.exa.codeium_common_pb.Media`,
`.google.protobuf.Timestamp` and `.google.protobuf.Duration`. Enum references
are `.exa.cortex_pb.CortexStepType`, `.exa.cortex_pb.CortexStepStatus`,
`.exa.cortex_pb.CortexTrajectorySource`. Do not seek a fictitious `CortexStep`.

Archive/title annotations use `.exa.jetski_cortex_pb.ConversationAnnotations`.
Decode summary `raw_summary` through
`.exa.jetski_cortex_pb.CascadeTrajectorySummary.annotations` and pin that typed
reference with `test_antigravity_summary_archive_descriptor`.
Own-surface annotation wins over own-surface summary, never another surface's
index. Valid annotation with absent `archived` means false (proto3 default) and
still wins over summary true. Missing/unreadable/malformed annotation falls back
to summary, diagnosing read/parse errors. Valid sources that disagree increment
`antigravity_archive_disagreements`. With neither usable source, default false.
Set `archive_reason="session"` only for resolved true, otherwise empty.
Archive state never changes usage eligibility.

Write a bounded dependency-free C wire reader with distinct absent/found/
malformed results. Iterate repeated fields; handle packed/unpacked integers,
last-wins scalars, unknown varint/length-delimited/fixed32/fixed64 fields and
bounds-checked nested messages. Reject truncation, field zero, invalid wire
types, overlong/overflowing varints and unsafe lengths; bound recursion and
allocation. Malformed blobs diagnose context and lose only their staged record;
SQL/read failure loses the staged database. Preserve valid siblings.
Text-format annotations accept whitespace, C-escaped strings, optional title,
boolean archive and balanced unknown nested messages including quoted braces.
Malformed escapes/braces/truncation diagnose and fall back. Never copy system
prompts or planner thinking text into payloads; reasoning counters remain eligible.

### Corpus projection

Behave as `src/opencode/corpus.c::{project_session,link_sessions}` and shared
workspace/turn helpers, with these new mappings:

- Session start is trajectory creation, else first step creation; end is latest
  step completion, else latest creation. Zero-step databases remain sessions.
- A user-input step starts a turn; following steps belong until the next user
  input. Pre-prompt steps have no display turn; their usage stays outside turns.
  Turn start is user creation and end is latest member completion; absent
  completion stays unknown, never synthesized from the next prompt's timestamp.
- Prompt prefers `user_response`, else joined `items.text`; image count includes
  `images` and `media` with image MIME type. Last nonempty planner response
  supplies the answer, preferring `response`, then `modified_response`.
- Apply the [Turn-status reducer](#turn-status-reducer).
- Count planner `tool_calls` through `src/claude/parse.c::claude_tool_count`:
  `run_command` maps to `Bash`; `write_to_file`, `write_file`,
  `replace_file_content`, `multi_replace_file_content` map to `Edit`;
  `call_mcp_tool` maps to `mcp__<ServerName>__<ToolName>` from JSON arguments;
  other names pass through. Match execution metadata `tool_call.id` to determine
  failure from error status; malformed arguments diagnose without losing session.
- Title prefers annotation, own-surface summary, first meaningful request, ID.
  Annotation/summary titles use `title_source="antigravity_title"`; request
  titles use `first_request`. Percent-decode a `file://` workspace URI to cwd;
  invalid/other-scheme URIs diagnose. Use shared workspace resolution and retain
  git-root/branch metadata where available.
- Preserve trajectory source separately from surface. Link by trajectory parent,
  retain subagent-source rows lacking a parent, count orphan links as
  `antigravity_orphaned_subagents`; add no spawn links. Behave as OpenCode's
  `corpus_collisions` handling for cross-provider ID conflicts.

#### Turn-status reducer

Reduce member steps using this precedence: any `ERROR` yields aborted; otherwise
any `CANCELED`/`INTERRUPTED` yields interrupted; otherwise only the final turn
containing `PENDING`, `RUNNING`, `GENERATING`, `WAITING` or `QUEUED` uses open
`end_kind`; otherwise completed. The completed default includes `DONE`,
`CLEARED`, `INVALID`, `UNSPECIFIED`, unknown statuses, and earlier turns closed
by a following user input even if their steps retain active statuses. Status
reduction does not alter the timing rule in Corpus projection. For open turns,
behave as `turn_models`/`corpus_quiet`, passing latest step timestamp, else
session end, else snapshot as mtime. Cleared status does not suppress usage.
Pin this reducer in `test_antigravity_turn_status_reducer`, exercising each
descriptor status, default/unknown values, mixed precedence and final/earlier
turn positions, including missing-completion timing and quiet-threshold outcomes.

### Usage

Collect `ChatModelMetadata.usage`, its `retry_infos[].usage`,
`CortexStepMetadata.model_usage`, and its `retry_infos[].usage` through the
qualified descriptors. Skip token-empty records. Before implementing accounting,
write `test_antigravity_ccusage_usage_oracle` using the pinned executable and
synthetic databases. Independently probe:

- `response_id`, `provider_assigned_message_id`, `message_id`: each alone,
  conflicting candidates to establish priority, missing/empty IDs, equal-token
  distinct requests without IDs, copies across locations/retries/sessions,
  partial records and conflicting models.
- Output components independently absent, zero, unequal and contradictory;
  model enum/slug fallback, cleared steps and checkpoint-only usage.

Record exact observed expectations in named tests and the identity helper's
contract comment. This is a concrete required probe, not permission to guess
identity-less keys, priority or output reconciliation. If the executable cannot
expose a needed decision, verify pinned source or report that precise gap.
Do not label invented behavior upstream-compatible.

Colophon's additional accounting contract:

- Merge identity matches by component maximum, never sum. Global discovery
  order owns a merged record; count cross-session merges as
  `antigravity_cross_session_duplicates`. Do not merge separate identity-less
  requests merely because tokens match; exercise oracle-established identity-less
  behavior explicitly.
- `antigravity_requests_without_usage` counts generator rows lacking eligible
  usage. It cannot detect missing individual token/model/identity components or
  changed field meanings.
- `UsageUnit.source="antigravity"`; `input=fresh+cache_read+cache_write`,
  `cached=cache_read`, `cache_write=cache_write`; output is reconciled total
  output including reasoning. Preserve reasoning presence separately from zero.
  Reject negative/overflowing components or int64 sums as
  `antigravity_invalid_numbers`, retaining other events.
- Attribute by generator `response_model`, mapped usage enum,
  `.exa.codeium_common_pb.ModelInfo.chat_model_name` then `model_name` from the
  step's `model_info`, most recent attributed model in the conversation, then
  `antigravity/unattributed`. Unknown/generic enum labels cannot override a
  meaningful fallback. Confirm enum mappings through source or per-enum oracle
  probes; store them in one versioned table with expectations in the maintained
  model test. Exclude `display_name`, `vertex_model_id` and `model_url` from the
  step string fallback. Pin the descriptor-member choice in
  `test_antigravity_model_info_fallback` with independent fields, conflicting
  names, ignored fields and attribution-ladder interactions; use the pinned
  executable for synthetic behavioral comparison.
- Step events use their step; generator events match `execution_id`, else first
  `step_indices` entry. Time prefers that step's `completed_at`,
  `finished_generating_at`, `created_at`, then chat-start creation, then session
  start with `antigravity_unknown_clocks`. Merged events prefer step-derived
  clocks. Display turn follows [Corpus projection](#corpus-projection).
  Turn TTFT uses its first generator row's `time_to_first_token`.

Define the acceptance projection in the oracle regression: compare fresh input
as `u.input-u.cached-u.cache_write`, visible output as `u.output-reasoning`
(absent reasoning uses zero), cache components directly and total tokens as
`u.input+u.output`. Do not compare the providers' raw output columns directly.

### Pricing and composition lifecycle

New `src/antigravity/model.{c,h}` owns attribution/normalization. Set `model_raw`
to the recorded/attributed slug and `model` to normalized pricing ID. Behave as
pinned CodexBar's normalization symbols, additionally stripping `-medium`,
`-high`, `-trial`. Exclude its explicit Vertex entry and keep that unsupported
model unpriced; do not add a `google-vertex` routing lane. Preserve the pinned moving-default
alias and document its assumption. Unknown models remain unpriced.

Extract this API in `src/price/claude_cost.{c,h}`:

```c
Err catalog_price_usage_units(UsageUnit *units, size_t count,
    ModelsDevIndex *index, PricingReport *report,
    Str identity_prefix, bool key_by_model);
```

Behave as baseline `claude_price_usage_units`/`resolved`, with provider prefix
in memo keys/identities and lookup field selected by `key_by_model`. The Claude
wrapper passes `STR_LIT("claude:")`, false and retains existing outputs.
Antigravity passes `STR_LIT("antigravity:")`, true; unpriced identities follow
`resolved`'s format using this prefix. Behave as
`src/price/claude_model.c::claude_models_dev_lookup` for routing and the existing
pricer for request context tiers/provenance.

New `Err antigravity_compose(AntigravityStore *store, Corpus *corpus,
ModelsDevIndex *index, PricingReport *report);` runs after `opencode_compose`
and before `compose_refresh_costs` in `src/cli/run.c`. From the task that first
inserts sessions, call `compose_aggregate_session` for every Antigravity session
after `compose_usage` on every run, including empty usage. Insertion-time
allocation is insufficient: follow `compose_usage`/`compose_destroy` lifetime.
Usage implementation extends this composer, not a second initialization path.

### Payload and page

Add `PayloadInputs.antigravity`. Behave as `src/out/payload.c::opencode_source`
and `opencode_diagnostics` for source status/counts/reasons/diagnostics, using
`home` instead of `data_dir`, per-database `surface`, `legacy_encrypted` and
`ignored_environment`. Give Antigravity its own `costs` availability. Session
payload carries `antigravity_surface`; capabilities permit Copy session ID only.
Behave as OpenCode's capability-based action gates.

Extend `assets/page.js` provider registries/filtering and corresponding OpenCode
UI paths. Display name is `Antigravity`; reader surface tags are `APP`, `CLI`,
`IDE` using `.tag`. Cost provenance behaves as Claude catalog estimates.
Absence copy names checked paths and home flag; unreadable copy gives path/reason;
ignored-environment copy names the variable/remedy. Footer adds database details,
excluded legacy count and contextual diagnostic explanations. Keep exact copy
and fixture values in planned `test_antigravity_source_copy`, not prose examples.
Give database panels distinct explicit state keys in `renderFooter`/`footerPanel`.

Add production values in `assets/page.css`'s token section:

```css
--a: #ffa3c4;
--heat-a-1: #3d1f2c;
--heat-a-2: #6e3550;
--heat-a-3: #b5628a;
--heat-a-4: #ffa3c4;
--bar-a-from: #6e3550;
--bar-a-to: var(--a);
```

Extend selectors found by `rg -n 'opencode' assets/page.css` for this provider.
Verify `--a` contrast against `--bg` reaches 4.5:1. Preserve keyboard/focus and
source `aria-pressed` semantics; add no motion or product branding.

### Privacy and validation

Keep invented fixture rows, database/WAL files, generated pages and screenshots
in fresh private external scratch, behaving as `tests/README.md` specifies.
Use conspicuously synthetic values in named fixtures; never publish real source
content/identifiers or runtime copies. Add Gemini-root test sandbox read/write
denies and mutation probes, behaving as OpenCode sandbox tests. Canaries behave
as `test_opencode_credentials_never_enter_page_or_runtime`; unopened-file proof
uses the separate [Live acceptance](#live-acceptance) sandbox.

Each task must pass `make`, `make test`, `make sanitize`, `make tsan`,
`make check-assets`, `make check-sort` from `colophon/`, following its own
Python 3.14 venv/cached Chromium setup and root `AGENTS.md`. No skips; report
failure output. Shared deployment changes invoke affected root Validation Matrix
gates. This documentation-only plan repair needs no test execution.

### Release acceptance

After deployment, compare source and installed `--version`, generated
`payload.meta.version` and browser-rendered `[data-version]` with the target
release, allowing the command/browser's `colophon ` display prefix. Run the
installed executable offline/no-open against a fresh private synthetic
source/runtime and inspect its generated page using the payload and
rendered-version interfaces in
`tests/test_browser.py::test_opencode_source_hash_descendants_actions_and_version`.
Do not overwrite the owner's existing runtime page. Run the installer audit from
`docs/local_deployment_sync.md` against the installation. Handoff requires
version equality and successful audit; report the released version and results.
This new post-deployment gate cannot be supplied by source references alone:
the executable installation and its generated page are separate release outputs.

## Tasks

### Task 1 — Discover and read Antigravity databases

Deliver [Source access](#source-access) and
[Decoding and archive precedence](#decoding-and-archive-precedence), with source
summary/payload diagnostics but no corpus sessions. Add
`src/antigravity/{wire,db,scan}.{c,h}`. `AntigravityStore` follows
`src/opencode/db.h::OpencodeStore` ownership/staging, retaining raw sessions,
steps, generators, archive/title provenance, surface and diagnostics. Suggested
API: `Err antigravity_discover(const Args *args, AntigravityStore *store);`.
Preserve decoding-contract error distinctions in the wire API.

Add flags/Args fields to `src/cli/args.{c,h}`; append names and behave as its
unique-prefix parser. Discover/read beside `opencode_store_read` in
`src/cli/run.c`, extend the no-readable-sources gate and destroy on every exit.
Implement source serialization in `src/out/payload.{c,h}` and summary in
`src/cli/summary.c` under [Payload and page](#payload-and-page). Introduce
`PROVIDER_ANTIGRAVITY` in `src/corpus/assemble.h` and its
`src/corpus/provider.c::provider_id` branch now, before summary references it.
Audit `rg -n 'PROVIDER_' src` decisions and extend
`tests/unit/test_provider.c::provider_ids_cover_every_provider` in this task.

Tests and acceptance:

- `tests/unit/test_antigravity_wire.c`: varint boundaries, malformed lengths,
  recursion/allocation limits, wire rejection, nested/repeated/unknown fields,
  last-wins and absent distinctions under the decoding contract.
- `tests/unit/test_antigravity_db.c` and `tests/unit/antigravity_fixture.{c,h}`:
  behave as OpenCode fixture builders; cover schema/column rejection, extra
  tables, empty/zero-step DBs, summary title-only shape, archive defaults/
  precedence/disagreement/fallback, text escapes/whitespace/nesting/no newline,
  surface duplicates, malformed blobs and failed-sibling staging. Public schema
  constants cite qualified descriptor names and binary hash.
- Add `tests/test_antigravity.py` to Makefile `test-cli`, with stdlib protobuf
  encoder in `tests/helpers.py`. Cover absent/disabled/error-only/mixed sources,
  invalid options and unchanged existing ambiguity expectations, environment/help,
  legacy distinct IDs, large DB acceptance, unchanged database/WAL/annotation
  bytes/modes and allowed SQLite coordination. Add privacy-contract canary and
  sandbox regression/mutation tests.
- `test_antigravity_discovery_acceptance` runs offline/no-open with other
  providers disabled/empty, fresh scratch runtime/root; asserts fixture database
  counts in summary/source payload and runtime initialization behavior.

Update `README.md`, `docs/{runtime,architecture}.md`, `tests/README.md` for this
deliverable. Run the shared validation gate and commit this behavior change.

### Task 2 — Antigravity sessions in corpus and page

Deliver [Corpus projection](#corpus-projection) and interactive
[Payload and page](#payload-and-page). Add `SessionModel.antigravity_surface`
beside source-provenance fields. New `src/antigravity/corpus.{c,h}` exposes
`Err antigravity_corpus_add(AntigravityStore *store, int64_t snapshot,
Corpus *corpus);`, called after `opencode_corpus_add`, before
`corpus_resolve_workspaces`. Extend session serialization/summary counts.
Add the minimal empty `src/antigravity/compose.{c,h}` now under
[Pricing and composition lifecycle](#pricing-and-composition-lifecycle), making
generated-page refresh safe with inserted sessions. Update asset hashes using
`docs/development.md`.

Tests and acceptance:

- `tests/unit/test_antigravity_corpus.c`: the named reducer regression and
  projection-contract edges including pre-prompt/zero-step, tools/MCP/
  malformed arguments, title fallback, decoded/invalid cwd, orphan/parentless
  subagent-source and cross-provider collisions.
- Native integration exercises archived/unarchived rows in admitted surfaces,
  summary-only archive, default-false annotation overriding true summary, mixed/
  disabled providers and empty aggregation through refresh.
  `test_antigravity_corpus_acceptance` extends discovery acceptance with fixture
  session/turn counts and projection edges.
- `tests/test_browser.py` and `test_antigravity_source_copy`: filtering,
  KPIs/calendar/workspaces, archive inclusion, capabilities/tags, source remedy
  copy, independent footer state, 375px overflow, offline requests and
  `guard_browser_errors`. Inspect private Playwright overview/list/reader
  screenshots for layout, contrast and consistency.

Update `README.md`, `docs/{runtime,architecture}.md`, `tests/README.md` for the
deliverable. Run the shared validation gate and commit.

### Task 3 — Usage, pricing and release

Deliver [Usage](#usage) and complete
[Pricing and composition lifecycle](#pricing-and-composition-lifecycle).
Extend the existing composer; implement model handling and shared pricer
extraction. Record oracle-probe expectations before implementing compatible
algorithms; do not substitute speculative upstream facts.

Tests and acceptance:

- `tests/unit/test_antigravity_usage.c`: collection contract, oracle identity/
  output cases, maximum merge, cross-session ownership, retry/checkpoint/cleared
  inclusion, fresh-input conversion, reasoning presence, timestamp fallback/
  matching, pre-prompt outside-turn totals and invalid numbers retaining valid
  events. Model tests include the named ModelInfo fallback regression and cover
  every enum entry, attribution ladder, unattributed sentinel,
  aliases/suffixes/adaptations. Price tests preserve Claude outputs and separate
  provider identities for the same model.
- `test_antigravity_cached_pricing` seeds synthetic `pricing-cache.json` using
  existing cache fixtures before an offline build; no catalog socket. Put
  alias-to-catalog resolution, unknown-model unpriced identity and request
  context tiers in that named fixture. Browser tests assert provider-only/All
  tokens/cost and unpriced copy.

Update maintained version declarations/assertions/installer pins to the target
release. Inspect `rg -n '0\.4\.2'` at repository root, never blanket-substitute;
preserve historical release paragraphs/plans. Add the new release paragraph.
Include repository-root `tools/tests/deploy_colophon.test.mjs` where it asserts
the maintained release; use [Release acceptance](#release-acceptance) for version
verification.

Update `docs/token_rules.md` with accounting/oracle provenance, plus
`docs/runtime.md`, `README.md`, `tests/README.md`, `THIRD_PARTY.md` for actual
adaptations with pinned references/existing MIT licenses. Add the usage-copy
deduplication lesson to `docs/LESSONS_LEARNED.md`. Run the shared validation gate
and root “Static deployment/fleet audit tooling” commands required by installer
changes; include affected Market Atlas gates for shared tooling changes. Inspect
for sensitive data, commit, perform task review and whole-branch review, fix
findings and revalidate, then follow the authorized push, PR, squash merge,
deployment and cleanup workflow, enforcing [Release acceptance](#release-acceptance)
before handoff.

## Live acceptance

After usage/pricing/release completion, use a fresh private scratch runtime with
the real admitted root; seed cache from the private runtime for offline/no-open
builds. Keep copied databases and comparison output private. Invoke the absolute
copied/hash-verified oracle from [Pinned references](#pinned-references), with
`HOME` pointing at private copies of the same coherent snapshots, using
`antigravity session --json --offline`. Compare under the Usage oracle-comparison
contract; reconcile concurrent-source changes before treating mismatches as bugs.

Assert discovery/projection/legacy/zero-step counts against admitted files,
archive state against resolved annotations and cost availability against
unpriced notes. Confirm large databases remain included. Run an external
`sandbox-exec` profile denying reads under the real root except the
[Source access](#source-access) admission list, with its sidecars and normal
SQLite coordination permissions. Successful isolated execution supplies
unopened-credential evidence separately from canary non-disclosure. Remove only
scratch created by this acceptance run after completing checks.

## Risks and evidence limits

After upstream updates, reassess compatibility using [Usage](#usage),
[Pricing and composition lifecycle](#pricing-and-composition-lifecycle) and
[Pinned references](#pinned-references) for their diagnostic, alias and evidence
limits. CLI/IDE archive and subagent behavior require synthetic coverage; this
plan makes no empirical claim about untested UI operations. Live reads follow
[Source access](#source-access).
