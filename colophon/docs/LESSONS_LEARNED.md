# Lessons learned

- OpenCode forks can copy a parent's payload message id and clocks. Keep the
  SQLite row identity and creation clock independently from payload display
  clocks. Token validation has signed-integer bounds; a finite recorded cost
  has a separate numeric contract and must survive invalid or missing tokens.
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
