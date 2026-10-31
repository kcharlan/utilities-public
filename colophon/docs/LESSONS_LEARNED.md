# Lessons learned

OpenCode 2.1 stopped repeating a message's id and type inside its JSON payload;
they live only in `session_message` columns. Requiring the embedded copies made
every real message malformed, and session rollups silently stood in for request
usage as unattributed totals dated at session start, so totals still looked
plausible. Take identity from the columns and validate embedded copies only when
present. A rise in `opencode_malformed_messages` to the full message count is the
signal of a format change; compare per-request models, not only token totals.

Index failed Antigravity execution IDs once per session before counting planner
calls, then route each step to its turn through an index. Merging split tool-call
metadata inside each planner call retains a fresh arena copy every time and can
turn small inputs into quadratic retained memory. Keep those merges in temporary
session scratch, copy index keys and destroy scratch/maps on every exit. Assert
both failed-tool behavior and an arena-capacity budget on split synthetic inputs;
wall-clock timing alone cannot reliably catch this retained-allocation defect.

Antigravity nested singular protobuf messages merge before scalar lookup;
choosing the last raw message loses earlier response text or timestamp seconds.
Keep raw optional SQL enum states separate from effective projection: an explicit
integer wins, otherwise only an explicit payload scalar can supply the fact.
Unknown completion clocks stay unknown when a later prompt closes a turn.
Open-turn quiet detection uses the latest completion as well as creation, and
provider aggregation must be rebuilt after every shared compose/destroy cycle,
including empty usage. Database disclosures need explicit independent state keys;
a shared fallback key couples otherwise separate provider panels.

Antigravity descriptor names collide across protobuf packages. Resolve each
fully qualified type through its owning FileDescriptorProto and typed fields:
the Jetski annotation archive field and Cortex retry layout differ from the
first unqualified descriptor match. Pin behavior through actual database/summary
decoding, retain independent filename/trajectory/cascade identity, and stage
acceptance until the conversation transaction commits. Text protobuf escape
decoding must reject a NUL after backslash before using C string lookup helpers.
Check summary indexes are regular files before asking SQLite to open them: a
FIFO with a database filename can block a read-only source scan. Enforce binary
collation for exact identity joins rather than inheriting source-table collation.
The same regular-file admission applies to all SQLite sidecars, including a
rollback journal: busy timeouts do not bound an OS FIFO open. Singular protobuf
submessages merge across occurrences; apply last-wins only to present scalar
fields within the merged message. Treat malformed optional SQL enums as distinct
raw states so they cannot erase independently valid indexed protobuf facts.

Native details toggle events are queued and may arrive after a footer rerender.
Snapshot connected panels' live open properties before replacement, ignore
detached toggle events, and restore open as a property rather than a false
boolean attribute. Keep collapse focus/scroll separate from ordinary restoration.

- Hidden follow-ups and subagent answers need the reader's existing refit
  path when revealed. Select the long-text state toggle explicitly once a
  separate top action exists; choosing the first button changes which control
  gets hidden. Test viewport and splitter thresholds with expansion retained.

- Collapse must restore both focus and position. After a rerender, resolve the
  surviving state control before focusing without scrolling, then return an
  offscreen section start explicitly. Browser regressions need tall expanded
  content, trailing space, and DOM activation of offscreen start controls so
  browser clamping and Playwright scrolling cannot mask missing return logic.
  `test_workspaces_collapse_from_top_and_bottom` fails with scrolling disabled
  while focus restoration remains enabled. Allow one CSS pixel for Chromium's
  rounding of fractional starts after `scrollIntoView`.

- Workspace identity must not depend on which provider recorded a session.
  Codex records the git remote while Claude and OpenCode record only cwd, so
  the same repository resolved to an `origin:` and a `git:` workspace with the
  same display name. Derive the missing remote from the repository's own
  config (following linked worktrees to the common directory), and search a
  deleted cwd from its nearest existing ancestor rather than dropping to cwd.

- OpenCode forks can copy a parent's payload message id and clocks. Keep the
  SQLite row identity and creation clock independently from payload display
  clocks. Token validation has signed-integer bounds; a finite recorded cost
  has a separate numeric contract and must survive invalid or missing tokens.
- SQLite text conversion can allocate after a successful row step. Check
  conversion errors immediately and propagate allocation failure before
  treating an empty result as absent text or a schema/migration rejection.
- Same-stem source copies need independent reader reconciliation: accounting
  winners do not identify the most complete transcript. Preserve prompt UUIDs,
  identified tools and answer clocks, then map file-local turn keys into a
  canonical reader without changing stored usage facts or resume precedence.
  Legacy aggregate facts cannot prove distinct tool identities; retain their
  counts conservatively and reparse live old caches for richer facts.
- A selected symlink locator can survive its target. Resolve its existing link
  chain when the target is missing so stored provenance still matches, while
  retaining positive ENOENT/readable-ancestor proof and permission exclusions.
- Publish parser turns only after their required allocations and initialization
  succeed; a reader error must not finalize partially initialized state.

- History collision checks must index Codex public session IDs as well as map
  keys: a filename-fallback row can have a different internal key. Preserve
  primary aliases from collision-skipped transcripts and resolve exact canonical
  IDs before ambiguous aliases. Group history by exact ID and stable timestamp
  order so prompt activity has no invented duration or usage.

- Browser screenshots belong under each test's scratch root. Fixed session
  evidence paths escape wrapper cleanup and let repeat/concurrent runs overwrite
  reviewed artifacts; assert destination isolation before the screenshot writes.

- Source filtering must cover direct subagent reader hashes as well as the
  session list and descendant collection. Apply one provider predicate, treat
  legacy rows as Codex, and remove opposite-provider reader selections while
  retaining every other hash filter. Claude orphan rows still carry subagent
  identity and must obey subagent action-support restrictions.
- Keep known mixed-provider costs in the KPI value and unavailable-provider
  detail in compact text; a long availability sentence at value size distorts
  every card in the grid. Contain calendar scrolling in CSS before resize-time
  JavaScript fits cells, and keep sparse hour labels on one line at phone width.

- Claude subagent tool IDs belong to the actual parent agent transcript,
  rather than always the root session. Share graph validation and ordering
  with Codex while keeping record access and orphan diagnostics provider
  specific. Preserve independently valid sidecar fields even on orphan rows.

- Claude model normalization's pinned regular expressions use Foundation
  decimal digits, which differ from the older Codex candidate helper's broad
  numeric property. Use the system regex with composed-character boundaries;
  do not change Codex normalization to implement a Claude-only rule. ccusage
  fast-prefix matching tests its last occurrence only; an earlier valid
  occurrence must not override a later invalid suffix boundary.
- Capture prior nanocost facts on every complete raw Claude row before dedupe,
  including losing copies; pricing only authored winners loses the fallback
  needed if a later cache replay selects a different winner. Index OpenAI
  catalog rows once and give Claude independent lookup caches over borrowed
  immutable rows so provider expansion does not duplicate Codex diagnostics.

- Apply Swift's complete-grapheme matching to every decoded accounting marker,
  including IDs, model prefixes and original path roles. Restrict byte search
  to the pinned raw-line prefilters; a trailing combining mark can otherwise
  wrongly filter a response or change its winning owner.

- Claude advisor entries must survive a zero-token parent: the parent follows
  CodexBar's rejection while advisor construction follows ccusage's separate
  structural rules. Deduplicate constructed advisor IDs before aggregation.
  Keep serde's duplicate-known-field rejection scoped to advisor envelopes;
  primary Foundation row decoding retains its different last-value behavior.
- Foundation may decode long fractional JSON spellings as NSDecimalNumber;
  converting them through binary64 first changes intValue. Delegate fractional
  and oversized integer coercion to the same system implementation.
- Wide Claude rows and units need their type's explicit alignment. Extend the
  shared append primitive with an alignment argument rather than relying on
  macOS `max_align_t`; test every initial arena offset.
- Claude historical timestamps use Foundation's ISO8601 fallback. Its
  normalization and fractional truncation differ from a strict RFC3339 parser;
  the public CoreFoundation ISO8601 constructor matches the native formatter
  without changing Codex's approved historical-input omission.

- Track CLI config provenance per source root, including default/XDG roots;
  a process-wide custom root must never leak into Desktop/cswap/subagent rows.
  Resolve same-stem live origins independently of traversal order. Preserve
  provider-specific legacy counters when adding a second provider.
- A locator's missing store is an ordinary exclusion; its inaccessible store
  is incomplete traversal evidence. Hidden-directory filters can conceal
  unreadable `.claude/projects` descendants unless probes record failures.

- Provider presence must be resolved before runtime creation or cache opening.
  An absent source must not trigger cache recovery or rebuild cleanup: assert
  bytes, modes and recovery names under synthetic homes, rather than exit
  success alone. Gate provider-specific reader actions when adding rows.
- The shared JSON reader retains number spellings as raw values. Consume
  history milliseconds through `json_number`, preserving integer precision;
  yyjson numeric-type predicates alone silently reject valid history entries.
- Sandbox mutation probes need existing synthetic ancestor directories so
  nonexistent-path canonicalization cannot mask removal of a deny rule.
- On macOS `max_align_t` is not sufficient for `__int128`-bearing native
  structures. Arena allocations must pass each retained type's `_Alignof`,
  including tool vectors, session models and wide count-map values. Keep
  an alignment regression alongside sanitizer coverage.

These maintained lessons include knowledge from historical Python Colophon at
`38d6998eb223f690fc9dc0bde0ba528fcf784449` and later native work. Git history
retains the complete original notes and retired test names; those tests are
historical evidence, not available native acceptance commands.

- Codex compresses finished rollouts to `.jsonl.zst` and later deletes the
  plain originals. A discovery suffix filter can silently omit months of
  usage; agreement with CodexBar does not prove totals are complete. Compare
  discovered log counts against `*.jsonl*` on disk, accounting for siblings.
- Streaming zstd reports zero when a frame is complete and flushed. At the
  frozen input boundary, stop on that result even if the output buffer is
  full: another empty-input decode starts expecting a new frame and can
  falsely report a valid log as truncated. Keep a regression for exact
  output-buffer-sized expansion as well as partial output and damaged frames.
- EOF before the compressed snapshot's frozen size is unreadable even if the
  last decoded frame is complete. A file can shrink at a frame boundary after
  discovery; accepting its prefix silently undercounts and caches an incomplete
  snapshot. Check the read boundary independently of the decoder's frame state.
- Read-only SQLite uses normal coordination and bounded busy timeouts; it
  can create or update WAL shared-memory side files. Do not promise absolute
  source-write exclusion or substitute immutable mode without changing the contract.
- Codex's SQLite deletes `-wal` and `-shm` when its last connection closes.
  Homebrew SQLite recreates both for a read-only reader and reads normally;
  macOS's system SQLite cannot open that database read-only (code 14), which
  broke Telltale's Codex reads whenever Codex was closed. Keep linking Homebrew
  SQLite. `test_sqlite_closed_wal.c` closes fixtures with `PERSIST_WAL=0`
  because the system library otherwise keeps the WAL and hides the case.
- Unknown token components and clocks remain unknown. Reported durations do
  not prove intervals, and temporal proximity does not prove usage attribution.
  Keep conservation and ownership evidence distinct from display estimates.
- Apply every action restriction independently: archived rows cannot open
  desktop links, and subagents cannot copy CLI resume commands. Historical
  live-session read-only access did not prove writable continuation. Preserve
  tested support flags without generalizing version-specific observations.
- Keep acceptance fixtures conspicuously synthetic and temporary evidence
  outside the public checkout. Captured-corpus parity, real-data performance
  and installed acceptance need separate authorization; standalone suites do
  not replace them. Preserve no-external-request and browser-error guards.
- A repository update does not deploy an installed executable. Validate source,
  then separately authorize installation and check installed bytes, modes,
  version and receipt freshness. Report fleet drift without repairing unrelated
  deployments. Never edit a receipt to manufacture acceptance.
- Create development venvs only at new paths from an absolute stable Homebrew
  base interpreter, never another venv or a resolved versioned Cellar path.
  A relocated venv is preserved residue, not a reusable environment: scripts
  can retain old absolute entrypoint paths. Use each project's own venv.
- Runtime compatibility with prior Python releases does not make ledger
  read/check/replace a cross-process transaction. Run shared-home commands
  sequentially, avoid concurrent ledger edits, and never migrate private state
  automatically.
- When relocating source into a formerly retired project path, remove only the
  obsolete read deny; retain the location-independent `PROJECT_DIR` write deny
  and every real runtime, installed-command and historical-checkout protection.
  Prove source reads and scratch writes through the wrappers. Test the explicit
  source deny under canonical allowlisted scratch so the global write deny
  cannot mask its removal; policy evaluation avoids canary files in real homes.
  Preserve wrapper traps, scratch `TMPDIR`, browser cache and loopback-only
  networking. Apple Silicon ctypes calls to variadic `sandbox_check` must declare
  only its three fixed arguments, and evaluation errors must fail the test.
- [Claude retention](runtime.md#claude-parse-cache-and-retained-transcripts)
  requires positive deletion evidence, not absence from a discovery list.
  Reconcile before presence/rendering, recheck every candidate before any root
  mutation, and retain installed bytes through failed output and rebuild.
  Interrupted live supersession can leave both installed and retained copies;
  prefer the installed candidate and replay the original path once without
  deleting the last decodable recovery copy. Refresh live sidecars on cache
  hits, while retained facts preserve their last-known sidecar state.
- A persistence checksum does not validate the decoded shape. Stop map traversal
  immediately after a bad key, and make wide-number helpers honor prior errors
  before touching their value pointer. Exercise malformed maps with recomputed
  checksums and truncated values. Test const encoders against read-only memory:
  comparing values alone misses writes that store the same value.

## OpenCode continuation restrictions

Apply lifecycle and agent restrictions independently even when payload capability
normally disables both; an archived agent must satisfy both support flags. Keep
shell arguments independently quoted, and test compiled orphan and child rows as
well as mutated support combinations. See `tests/test_browser.py`'s OpenCode action
and shell-roundtrip regressions and `tests/test_opencode.py`'s capability regression.
The synthetic command test does not establish upstream database routing; see the
disposable probe recorded in `docs/runtime.md`.

## Recorded-cost aggregate overflow

Finite request costs can still overflow a session, turn or bucket sum. Check
addition before publishing the result; keep the affected summary unavailable
through later additions, and keep independently valid units/summaries intact.
OpenCode additionally suppresses all authored session costs and cost residuals
when its message sum fails, while preserving recorded source facts and tokens.
Explicit valid zero-token/zero-cost requests count as missing usage but are
exact facts: they do not alone make a token residual's zero cost unknown.
See `tests/unit/test_opencode_usage.c` for synthetic overflow/isolation and
zero-tuple regressions.

Provider CLI totals need their own finite guard even when every session cost
is valid. Check compensated-sum intermediates and the corrected total; retain
valid per-session payload costs while marking only the overflowing provider
summary unavailable. Discovery and test isolation must also precede runtime
creation: default-enabled SQLite providers can otherwise inspect a real home
even during an offline smoke run. Strip environment overrides and set a fresh
synthetic HOME as well as COLOPHON_HOME.

Browser sums need independent finite checks across sessions and providers,
including daily/model and reader summaries. Preserve valid individual costs,
keep failed sums unavailable, and scale provider shares before summing their
weights so overflow cannot create invalid CSS widths. Recorded OpenCode costs
carry estimate provenance rather than a missing rate-period warning; mixed
tooltips must still retain genuine warnings from other providers.

Carry exact cross-task display strings into page regressions: project-only
OpenCode archives use `ARCHIVED (PROJECT)`, while session archives use
`ARCHIVED` even when the project is also archived. Assert native provenance
and all three displayed locations (recent, list and reader), rather than
locking a paraphrase into a new test.

Count inherited OpenCode messages before request-kind filtering. The diagnostic
describes every copied row, including prompts, control messages and running
compactions; request eligibility describes a narrower accounting population.
When integration exposes a counter mismatch, check the specified population
against both projection and composition before changing a regression expectation.

## OpenCode effective clocks and fragmented text

Keep payload creation and SQLite row creation as independent raw facts. Derive
one effective creation clock (valid payload first, otherwise row) for request
starts, message-end fallback and usage dating; valid payload completion still
wins for usage. Fork inheritance uses only row creation, even when a copied
payload clock suggests different ownership. Test the DB-to-corpus/usage boundary
and emitted buckets as well as the raw parser facts and numeric diagnostics.

Arena allocations live until the complete store is destroyed. Joining fragments
by allocating every cumulative prefix retains quadratic bytes. Validate and sum
fragment lengths with overflow checks, allocate the final text once and copy
each fragment once. Regress both exact output and arena capacity through the
real database reader; content equality alone cannot detect this retention bug.

## Antigravity usage copies

The same request can appear in generator usage, generator retries, step usage
and step retries, including later conversations. Deduplicate namespaced identity
aliases transitively before aggregation and merge component maxima; summing
locations overcounts requests. Equal token tuples without IDs are independent.
Retain first session/turn ownership even when a later step improves the clock.
Reuse projection's step-to-turn mapping and rebuild summaries after each shared
usage reset, including empty sessions. Synthetic native oracle expectations
establish output/identity behavior; public enum descriptors alone cannot supply
behavioral model slugs, and placeholder enum labels must not defeat fallbacks.
Reconcile visible output within each observation before merging component maxima:
different reasoning counts can reveal different visible totals. Raw maxima first
would silently discard that evidence; a native-oracle partial-record probe
caught this despite ordinary duplicate and single-event output tests passing.

Opaque SQLite metadata keys are not step indexes. Preserve trajectory metadata
TEXT keys independently of INTEGER/NULL compatibility, and validate their blobs
without routing them through the required numeric step/generator index gate.
Regress workspace, creation and a resolvable provider-local parent through the
real database-to-payload path; raw-row count tests alone miss projection loss.
When adapting pinned aliases, retain exact-alias lookup both before and after
one routing suffix is stripped. Individual effort and suffix tests miss their
composition; cached-price acceptance must exercise the composed spelling too.

Every consumed nested clock needs its qualified schema at admission, including
ChatStartMetadata.created_at. Structural validation of an opaque parent cannot
validate a nested Timestamp. Clock decoding must also reject malformed framing
and wrong wire types before applying protobuf's absent-scalar zero defaults.
Retain empty/default epoch timestamps and singular-message merges, and test
malformed generator isolation with an independent valid sibling through SQLite.
