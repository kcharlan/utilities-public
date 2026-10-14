# Lessons learned

These maintained lessons were extracted from historical Python Colophon at
`38d6998eb223f690fc9dc0bde0ba528fcf784449`. Git history retains the complete
original notes and retired test names; those tests are historical evidence,
not available native acceptance commands.

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
