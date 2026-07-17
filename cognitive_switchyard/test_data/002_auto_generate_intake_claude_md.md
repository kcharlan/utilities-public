# Generate a CLAUDE.md in the intake directory at session creation

When a user creates a new session and clicks "Open Intake", they currently face a multi-step manual process to create intake tickets: open a terminal, navigate to the intake folder, launch `cc-opus`, find the pack's intake prompt file, and paste the path into the CLI. This is 5-6 manual steps across multiple apps.

The fix is to leverage Claude Code's built-in convention: it automatically loads a `CLAUDE.md` file from the current working directory. By generating a `CLAUDE.md` in the session's `intake/` directory at session creation time — populated with the pack's intake prompt — the user's workflow collapses to: open a terminal in the intake folder, run their Claude CLI, and start dictating work items. The prompt is already loaded.

## Context
- **Session materialization:** `cognitive_switchyard/config.py` — `SessionPaths.materialize()` (lines 89-94) creates the `intake/` directory and seeds `NEXT_SEQUENCE`
- **Pack intake prompt:** `cognitive_switchyard/builtin_packs/claude-code/prompts/intake.md` — the generalized intake prompt that tells the CLI how to create intake documents, including format, quality standards, and naming conventions
- **Pack loading:** `cognitive_switchyard/pack_loader.py` — `load_pack_manifest()` resolves prompt paths from `pack.yaml` relative to the pack root directory
- **Session creation endpoint:** `cognitive_switchyard/server.py` — `create_session()` (lines 522-572) calls `store.create_session()` which calls `materialize()`
- **State store:** `cognitive_switchyard/state.py` — `create_session()` (lines 92-103) invokes `session_paths.materialize()`
- **Pack manifest dataclass:** The pack manifest already carries a resolved `Path` for each phase prompt, including intake if defined in `pack.yaml`
- **Current behavior:** `materialize()` creates subdirectories and writes `NEXT_SEQUENCE` but does not write a `CLAUDE.md`

## Acceptance criteria
- When a new session is created, a `CLAUDE.md` file is written into the session's `intake/` directory
- The `CLAUDE.md` content is sourced from the session's pack `prompts/intake.md` file (not hardcoded)
- If the pack does not have a `prompts/intake.md`, no `CLAUDE.md` is generated (graceful no-op)
- The generated `CLAUDE.md` is functionally equivalent to the pack's intake prompt — a user running any Claude Code CLI variant in the intake directory gets the intake-creation instructions automatically
- The `CLAUDE.md` does not appear in the intake file list shown in the UI (it should be filtered out alongside `NEXT_SEQUENCE` in the `get_intake` endpoint)
- Existing sessions are not affected (no backfill required)

## Notes
- **Where to do the work:** The cleanest place is in `SessionPaths.materialize()` in `config.py`, alongside the existing `NEXT_SEQUENCE` seeding. However, `materialize()` currently has no knowledge of the pack. The pack name is available in `state.py:create_session()` and `server.py:create_session()`. The planner should decide whether to: (a) pass the pack's intake prompt path into `materialize()`, (b) write the file in `state.py:create_session()` after `materialize()`, or (c) write it in the server endpoint after session creation. Option (b) or (c) avoids changing the `materialize()` signature.
- **Filtering in the UI:** The `get_intake` endpoint in `server.py` (lines 713-742) already filters out `NEXT_SEQUENCE` by name. Add `CLAUDE.md` to the same filter so it doesn't show up as an intake ticket in the file list.
- **Content strategy:** Copy the raw content of the pack's `prompts/intake.md` file. Do not template or modify it — the prompt is already written to be self-contained. If the pack also has a `prompts/system.md`, consider whether to prepend it (matching the `_load_prompt_bundle` pattern in `agent_runtime.py` lines 128-136), but this may not be necessary since CLAUDE.md serves a different role than a system prompt for an automated agent.
- **The `docs/INTAKE_PROMPT.md` in the cognitive_switchyard repo** is a project-specific copy of the intake prompt. Once this feature ships, that file becomes redundant for users of the system — it was a workaround for the lack of auto-discovery.
- **Scope:** ~30 minutes. Touches 2-3 files (config.py or state.py, server.py for filtering).
