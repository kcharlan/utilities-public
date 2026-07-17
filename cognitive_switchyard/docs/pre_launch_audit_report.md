# Pre-Launch Audit Report

**Date:** 2026-03-10
**Scope:** Full implementation review against design spec (`docs/cognitive_switchyard_design.md`)
**Method:** Architecture review of all modules, design spec compliance check, full test suite run
**Test Suite:** 159 tests, all passing (24.76s)

---

## Design Spec Compliance Summary

### Pipeline Phases (Section 3)

| Phase | Spec | Implemented | Notes |
|-------|------|-------------|-------|
| Intake | File watch, session lock | Yes | Polling-based (no inotify), correct lock behavior |
| Planning | Parallel planner agents | Yes | Configurable planner count, claim recovery |
| Resolution | agent/script/passthrough modes | Yes | All three modes |
| Execution | Constraint dispatch, parallel workers | Yes | DEPENDS_ON, ANTI_AFFINITY, EXEC_ORDER |
| Verification | Interval-triggered, pause dispatch | Yes | Configurable interval, FULL_TEST_AFTER flag |
| Auto-Fix | Multi-attempt with enriched context | Yes | Configurable max attempts |

### State Management (Section 5)

| Requirement | Status | Notes |
|-------------|--------|-------|
| SQLite for queryable metadata | Yes | All tables present |
| File-as-state directories | Yes | intake -> claimed -> staging -> review -> ready -> workers -> done/blocked |
| Filesystem as source of truth | Yes | `reconcile_filesystem_projection` rebuilds DB from dirs |
| Post-completion trimming | Yes | Retains summary.json, resolution.json, session.log, release notes |
| Constraint graph as JSON | Yes | `resolution.json` format matches spec |

### REST API (Section 6.6)

All 25 specified endpoints implemented, plus bonus `POST /api/sessions/{id}/preflight`. Path traversal validation on `reveal-file` correctly implemented.

### WebSocket Protocol (Section 6.5)

All 5 server push types (`state_update`, `log_line`, `task_status_change`, `progress_detail`, `alert`) and 2 client message types (`subscribe_logs`, `unsubscribe_logs`) implemented.

### Web UI (Section 6.3)

| View | Status | Notes |
|------|--------|-------|
| Main Monitor | Yes | Pipeline strip, worker cards, task feed, all animations |
| Task Detail | Yes | Two-column split, streaming log with search |
| DAG View | Yes | React Flow with custom nodes, missing group backgrounds |
| Setup View | Yes | Pack selector, preflight, intake list, planner count |
| History View | Yes | Session cards, purge controls, retention indicator |
| Settings View | Yes | Retention, defaults, gear icon access |

Design tokens, all 7 keyframe animations, Google Fonts, background noise texture, and stagger load animation all present and match spec.

### CLI & Bootstrap (Section 7.2)

| Feature | Status |
|---------|--------|
| Self-bootstrapping venv | Yes |
| Built-in pack sync | Yes |
| `--reset-pack` / `--reset-all-packs` | Yes (as subcommands) |
| Port auto-detection | Yes |
| `init-pack` scaffolding | Yes |
| `validate-pack` tooling | Yes |

### Crash Recovery (Section 10)

| Recovery Scenario | Status |
|-------------------|--------|
| Orphaned worker detection | Yes |
| Completed-but-not-collected | Yes |
| Revert incomplete work to ready | Yes |
| Clean isolation artifacts | Yes |
| Kill zombie subprocesses | Yes |
| Reconcile SQLite with filesystem | Yes |
| Planning phase (claimed -> intake) | Yes |
| Resolution phase (delete partial, re-stage) | Yes |
| Session state machine on restart | Yes |

---

## Findings

### CRITICAL — Active Data Loss Risk

#### 1. `isolate_end` script does not merge work on success

**File:** `cognitive_switchyard/builtin_packs/claude-code/scripts/isolate_end`

The script runs `git worktree remove --force` regardless of whether the task succeeded. It never merges the worktree branch back to the source branch. Successful task execution silently orphans all committed work. The branch object survives but is never merged anywhere and the commit SHA is not printed to stdout as required by the spec (Section 4.3).

**Impact:** Any real Claude Code session will lose all work product.

**Fix:** Add squash-merge of the worktree branch to the source branch on `done` status before removing the worktree. Print the merge commit SHA to stdout.

### SIGNIFICANT — Production Reliability

#### 2. No SQLite WAL mode

**File:** `cognitive_switchyard/state.py`

`_connect` opens a new `sqlite3.connect()` per operation without enabling WAL mode or setting a timeout. The orchestrator thread and FastAPI handler threads write concurrently, which produces `SQLITE_BUSY` errors under the default rollback journal mode. No `timeout` parameter means busy-waiting defaults to 5 seconds, causing API latency spikes.

**Fix:** Add `PRAGMA journal_mode = WAL` and `sqlite3.connect(path, timeout=10)` in `_connect` or `initialize_state_store`.

#### 3. TOCTOU race in `create_session`

**File:** `cognitive_switchyard/state.py`

Checks session existence in one connection scope, then inserts in a separate connection. A concurrent request could create a duplicate, producing an unhandled `IntegrityError` (500) instead of the intended `KeyError` (409).

**Fix:** Do check-and-insert in a single connection/transaction, or catch `IntegrityError` and map to `KeyError`.

#### 4. Claude Code pack prompts are stubs

**Files:** `cognitive_switchyard/builtin_packs/claude-code/prompts/*.md`

All 5 prompts total 41 lines of generic placeholders. The reference material in `reference/work/` contains 654 lines of production-tested prompts with specific output format contracts, phase structures, progress marker formats, metadata header contracts, and anti-pattern guardrails. Without real prompts, agent behavior will be unconstrained and inconsistent.

**Fix:** Distill the reference prompts (`PLANNER.md`, `WORKER.md`, `RESOLVER.md`, `SYSTEM.md`) into pack-generic versions that preserve output format contracts and phase structures.

#### 5. No `test-echo` pack

The design spec (Section 8, Phase 1) requires a `test-echo` pack for integration testing without Claude CLI dependencies. Only `claude-code` exists in `builtin_packs/`.

**Fix:** Create a minimal `test-echo` pack with shell executor, no LLM, no isolation. Execute script echoes output, writes status sidecar, and exits.

### MODERATE — Correctness Concerns

#### 6. `_task_id_from_path` uses fragile heuristic

**File:** `cognitive_switchyard/worker_manager.py`

After extracting the filename via `.removesuffix(".plan.md")`, additionally does `split("_", 1)[0]`, truncating task IDs containing underscores.

#### 7. Thread-safety gap in `_refresh_worker`

**File:** `cognitive_switchyard/worker_manager.py`

Reads `worker.last_output_at` and `worker.finalized` without holding `worker.lock`. Safe on CPython due to GIL but would break under free-threaded Python (3.13t+).

#### 8. `reconcile_filesystem_projection` ignores missing-from-filesystem tasks

**File:** `cognitive_switchyard/state.py`

If a task exists in the DB as "active" but its plan file is gone from the filesystem, reconciliation silently skips it rather than marking it blocked.

#### 9. Session timeout uses wall-clock

**File:** `cognitive_switchyard/orchestrator.py`

`_elapsed_since_timestamp` uses `datetime.now(UTC)` while worker timeouts use `time.monotonic`. System clock jumps (NTP, suspend/resume) could cause incorrect session timeout behavior.

#### 10. `execute` script discards Claude output

**File:** `cognitive_switchyard/builtin_packs/claude-code/scripts/execute`

Pipes Claude output to `/dev/null` and writes hardcoded `TESTS_RAN: targeted`, `TEST_RESULT: pass` regardless of actual results.

#### 11. Double `find_free_port` call

**Files:** `cognitive_switchyard/cli.py`, `cognitive_switchyard/server.py`

Port is resolved in `cli.py`, then resolved again in `serve_backend`. Between the two calls the first port could be taken.

#### 12. No WebSocket reconnection logic

**File:** `cognitive_switchyard/html_template.py`

Connection drops (laptop sleep, network blip) leave the UI permanently stale with only a warning banner. No automatic reconnection with backoff.

### MINOR — Polish Items

#### 13. `POST /api/sessions` and `PUT /api/settings` accept raw dicts

No Pydantic validation; malformed input produces 500s instead of 422s.

#### 14. DAG view uses grid layout

Node positions are `index % 4 * 220` regardless of dependency structure. No topological/hierarchical layout.

#### 15. DAG view missing anti-affinity group backgrounds

Renders dashed edges but not the colored rectangular group regions from the spec.

#### 16. `handleSocketMessage` declared `async` but never awaits

Creates unnecessary Promise wrapping on every WebSocket message.

#### 17. Tailwind CSS loaded but unused

~60KB dead weight — no utility classes used in JSX.

#### 18. Setup View missing timeout fields

`task_idle`, `task_max`, `session_max` are in state but not exposed in the Advanced panel.

#### 19. `config.py` uses hand-rolled YAML parser

Splits on `:` instead of using `yaml.safe_load` (already a dependency).

#### 20. Template filename mismatch

`templates/status.txt` vs spec's `templates/status.md`.

#### 21. `verify` script is a no-op

Always exits 0 without running any verification.

#### 22. `execute` script skips phase 2/5

Progress markers jump from phase 1 to phase 3.

---

## Fix Priority

**Pass 1 (before launch testing) — COMPLETED 2026-03-10:**
- #1: `isolate_end` merge on success — FIXED. Added squash-merge of worktree branch to source branch on `done` status before removal. Prints merge commit SHA.
- #2: SQLite WAL mode — FIXED. Added `PRAGMA journal_mode = WAL` and `timeout=10` to both `_connect` and `initialize_state_store`.
- #3: TOCTOU race in `create_session` — FIXED. Replaced check-then-insert with single INSERT catching `IntegrityError`.
- #4: Flesh out pack prompts — FIXED. Distilled reference prompts (SYSTEM.md 200→88 lines, PLANNER.md 210→120 lines, WORKER.md 141→108 lines, RESOLVER.md 104→86 lines, fixer.md 8→62 lines). Total: 41 lines → 464 lines with output format contracts, phase structures, metadata headers, and anti-pattern guardrails.
- #5: Create `test-echo` built-in pack — FIXED. Minimal pack with shell executor, passthrough resolution, no isolation, no LLM. 3-phase execute script (reading/executing/finalizing) with progress markers and status sidecar.
- #10: `execute` script output handling — FIXED (along with #22). Claude output captured to file instead of /dev/null. Status sidecar values derived from actual output. All 5 progress phases emitted. Blocked reason includes Claude output tail.

**Pass 2 (moderate + minor) — COMPLETED 2026-03-10:**
- #6: `_task_id_from_path` — FIXED. Removed spurious `split("_", 1)[0]` truncation.
- #7: Thread-safety in `_refresh_worker` — FIXED. Added `worker.lock` acquisition.
- #8: `reconcile_filesystem_projection` — FIXED. Missing-from-filesystem tasks now marked blocked.
- #9: Session timeout clock — FIXED. Switched to `time.monotonic()`.
- #11: Double `find_free_port` — FIXED. Port resolved once in `serve_backend`.
- #12: WebSocket reconnection — FIXED. Exponential backoff (1s→30s max) with status banner.
- #13: Raw dict endpoints — FIXED. Added Pydantic `CreateSessionRequest` and `UpdateSettingsRequest` models.
- #14: DAG grid layout — FIXED. Replaced with topological depth-based column layout.
- #15: DAG anti-affinity groups — FIXED. Added tinted rectangular group backgrounds with labels.
- #16: Async `handleSocketMessage` — FIXED. Removed unnecessary `async`.
- #17: Tailwind CSS dead weight — FIXED. Removed unused CDN script tag.
- #18: Setup View timeout fields — FIXED. Added task_idle, task_max, session_max to Advanced panel.
- #19: Hand-rolled YAML parser — FIXED. Replaced with `yaml.safe_load`.
- #20: Template filename — FIXED. Renamed `status.txt` → `status.md`.
- #21: `verify` script no-op — FIXED. Now attempts pytest, npm test, or no-op with message.

**Pack review (bonus fixes) — COMPLETED 2026-03-10:**
- `isolate_end` SHA extraction — FIXED. Replaced fragile sed parsing with `git rev-parse --short HEAD`.
- `isolate_end` dangling branches — FIXED. Branch cleanup now runs for both `done` and `blocked` status.
- `test-echo` template consistency — FIXED. Renamed `status.txt` → `status.md`.

**All 22 findings resolved. Full test suite: 159 passed.**
