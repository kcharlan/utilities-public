# Lessons learned

- Claude advisor entries must survive a zero-token parent: the parent follows
  CodexBar's rejection while advisor construction follows ccusage's separate
  structural rules. Deduplicate constructed advisor IDs before aggregation.
  Keep serde's duplicate-known-field rejection scoped to advisor envelopes;
  primary Foundation row decoding retains its different last-value behavior.
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
