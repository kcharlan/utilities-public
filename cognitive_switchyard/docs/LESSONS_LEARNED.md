# Lessons Learned

## Recovery Inputs Must Not Stop Recovery

- What went wrong: Unreadable worker metadata raised during every resume, preventing the rest of the session from recovering.
- Pattern to follow instead: Quarantine unreadable recovery inputs with their bytes intact, record a warning, and follow the safe missing-input path.

## Cleanup Without a Session Thread

- What went wrong: Aborting a session with no live thread marked it aborted but left its worktree behind because cleanup was tied to the thread's exit.
- Pattern to follow instead: Run cleanup on the no-thread path too; when a thread is live, let it drain workers before removing their workspace.

## Planner Fallbacks Must Retain Inputs

- What went wrong: A matching plan file was treated as proof that a failed planner invocation had handled its input, although another invocation could have created it.
- Pattern to follow instead: Retain the original input whenever planner output cannot be parsed, including when existing plan names match its prefix.

## Process Groups and Inherited Pipes

- What went wrong: Terminating a wrapper left descendants running and holding its output pipes open, so joining readers could stall the orchestrator.
- Pattern to follow instead: Start subprocesses in their own process groups, terminate and escalate the group on timeout, and test cleanup with a synthetic signal-resistant descendant that inherits a pipe.

## DAG Geometry Must Follow Rendered Nodes

- What went wrong: The replacement DAG treated an 80-pixel layout estimate as the rendered height, so wrapped titles displaced handles and invalidated fit, edge and selection geometry.
- Pattern to follow instead: Measure rendered node dimensions and share them across every geometry consumer; test a wrapping title as well as live updates without resetting the user's viewport.

## Text Whitespace After Template Conversion

- What went wrong: Converting JSX to tagged templates kept the single spaces that JSX drops at line breaks. Option labels changed, and `white-space: pre` and `pre-wrap` elements (code blocks, release notes, log lines) showed indented first lines, while normal inline text shifted a few pixels.
- Pattern to follow instead: Derive template text from the JSX rule: text on one line keeps its spaces, a line break and the whitespace around it disappear, and `{" "}` is the explicit space. Assert exact text with raw `textContent` (`tools/testkit.py` `assert_exact_text`), because Playwright's `to_have_text` and `inner_text` normalize whitespace and hide this.

## Streaming Must Honor Injected Process Runners

- What went wrong: Enabling phase output callbacks bypassed the injected runner and launched the real agent CLI, while a test swallowed the resulting exception.
- Pattern to follow instead: Honor injected runners in both streaming and non-streaming paths, guard real subprocess boundaries in regressions, and assert successful results rather than swallowing errors.

## YAML Parsing In A Homebrew Python Environment

- What went wrong: Early validation ran against the shell's default Python, which hid the real dependency path and pushed the implementation toward environment-specific workarounds.
- Pattern that caused it: Assuming the shell's default Python and `pytest` entrypoint were the runtime of record.
- Pattern to follow instead: Run the product through the uv-managed `switchyard` launcher and development tests through the registered `tools/run_project_tests.py cognitive_switchyard` runner. Never depend on Homebrew or system Python package state.

## Plan Metadata With Numeric IDs

- What went wrong: YAML loaders can coerce `PLAN_ID: 001` into an integer, which silently strips leading zeroes and breaks task-file matching.
- Pattern that caused it: Using a default YAML loader for identifier-like metadata.
- Pattern to follow instead: Treat plan IDs as strings during parsing and preserve the source representation end-to-end.

## SQLite Access Across The API Thread And Orchestrator Thread

- What went wrong: The web server and background orchestrator share the same SQLite file, and default connection settings were too strict for that access pattern.
- Pattern that caused it: Using thread-local SQLite defaults in a multi-threaded design.
- Pattern to follow instead: Use WAL mode plus a thread-safe connection configuration, and keep the filesystem as the recoverable source of truth.

## Error Handling In Modules Without A Logger

- What went wrong: Adding a `_logger.exception()` call in `orchestrator.py` failed at runtime because the module had no logger defined — it had no logging usage before this change.
- Pattern that caused it: Following the `server.py` pattern (`_logger = __import__("logging").getLogger(__name__)`) without checking whether the target module already had one.
- Pattern to follow instead: Before referencing `_logger` in any module, grep the file for `_logger` or `logging` to confirm the logger is already defined; if not, add it at the module bottom (consistent with `server.py` style) before writing the call site.

## Placeholder UI Layers Age Poorly

- What went wrong: A minimal shell can make tests pass while leaving major design-doc behavior effectively unimplemented.
- Pattern that caused it: Treating the API scaffold as equivalent to the full operator console.
- Pattern to follow instead: Close placeholder gaps in the same implementation pass, or explicitly track them as incomplete before declaring a phase finished.

## Filesystem-Then-DB Ordering Creates Unrecoverable Divergence

- What went wrong: Several code paths wrote to the filesystem (file move, log write) before committing to the DB. A crash between the two left the filesystem and DB in divergent states that recovery could not detect or repair.
- Pattern that caused it: Treating the filesystem as the primary record and the DB as the secondary, with no protection for the gap between them.
- Pattern to follow instead: Commit DB state first, then perform the filesystem change. Reconcile before projecting again from a DB path: recovery now reconciles first so it can repair a DB that is ahead of the filesystem. Defer blocking missing plans until orphan cleanup has run, preserving the persisted distinction between active orphans and deliberately blocked work across another crash. The reconciler cannot repair a DB that is behind.

## Lock Discipline Must Cover All Mutable State Fields on Shared Objects

- What went wrong: Timeout-related fields on `_ActiveWorker` were read and written by both the orchestrator thread and reader threads without holding `worker.lock`, while other fields on the same struct were already lock-protected.
- Pattern that caused it: Adding new mutable fields to a shared dataclass without auditing which of the existing lock-acquire sites needed to cover the new fields.
- Pattern to follow instead: When adding fields to a dataclass shared across threads, explicitly decide and document the lock that protects each field. Apply the same discipline to all methods that access those fields — not just the ones that already acquire a lock.

## Frozen Dataclasses Cannot Be Monkeypatched at Instance Level

- What went wrong: Tests tried to use `unittest.mock.patch.object(instance, "method", ...)` on a `@dataclass(frozen=True)` instance, which raises `FrozenInstanceError`.
- Pattern that caused it: Applying the standard `patch.object` pattern without checking whether the target is a frozen dataclass.
- Pattern to follow instead: For frozen dataclasses, patch on the class (`patch.object(type(instance), "method", ...)`) rather than the instance.

## UI And API Contracts Drift Without Browser Assertions

- What went wrong: Three UI paths silently disagreed with the backend. Setup collected timeout overrides but never sent them (and read them back under keys the API never returns), History's Purge All confirmation counted only completed/aborted sessions while the endpoint also deleted idle ones, and the DAG endpoint returned `resolution.json` without the titles and statuses the view rendered, so every node read "Task" / "ready".
- Pattern that caused it: API tests built request payloads by hand and asserted response shapes, while browser tests checked that views rendered, not what the UI sent or what each element showed. Neither side owned the contract between them.
- Pattern to follow instead: For each form or view, add a browser test that drives the real control and asserts the request payload or the rendered values (`page.expect_response`, element text and colors), and keep confirmation counts and endpoint filters on one shared definition of the affected set.

## UI Form Defaults Can Silently Override Pack Defaults

- What went wrong: The Setup form prefilled verification interval 4, auto-fix enabled and 2 attempts, and always sent them, so a pack's own `verification.interval` and `auto_fix` settings never applied to UI-created sessions (the built-in `test-echo` pack's `auto_fix.enabled: false` was ignored).
- Pattern that caused it: Hard-coding the backend's fallback values in the frontend draft instead of leaving override fields unset.
- Pattern to follow instead: Start override fields blank, show the selected pack's value as the hint, and send a field only when the operator sets it, so the backend's pack-default merge stays the single source of defaults.

## Worktree Cleanup Requires Server-Owned Authority

- What went wrong: A session's client-provided environment could identify a directory for cleanup, and a worktree collision could remove a directory Git did not own.
- Pattern that caused it: Treating a path string as proof of worktree ownership and force-deleting isolation branches regardless of merge state.
- Pattern to follow instead: Record cleanup paths on the server, verify that Git lists the target as a secondary worktree before removal, and retain unmerged isolation branches for recovery.

## Squash Conflicts Need Explicit Recovery

- Git squash conflicts do not necessarily create `MERGE_HEAD`. Refuse dirty target trees, restore only the clean target on failure, and preserve the task branch and workspace for resolution; remove a registered worktree before deleting its branch.

## Reap Workers When a Test Stops Polling Early

- What went wrong: A warning assertion returned while its synthetic worker was still running; the manager's timeout only advances when polled.
- Pattern to follow instead: Terminate, poll to completion, and collect in a `finally` block, and verify cleanup when polling raises.
