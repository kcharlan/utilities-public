# AGENTS.md

## ⛔ PUBLIC REPOSITORY: NO SENSITIVE DATA

This is a public-facing repository. Never place sensitive data in code or commit it to this repository.

- Do not add secrets, credentials, API keys, tokens, personal information, financial or brokerage data, account identifiers, institutions, holdings, securities, balances, transaction data, health or location data, customer/production data, private exports, or realistic copies of such values.
- This prohibition applies to source, tests, fixtures, examples, documentation, comments, logs, screenshots, generated artifacts, and commit messages—not only runtime configuration.
- Use conspicuously synthetic fixtures and placeholders. They must be unmistakably fake and must not reproduce a real user's values.
- Keep operational configuration and mutable state in documented user-home runtime directories outside the repository. Track only synthetic `*.example.json` templates when a template is necessary.
- Before every commit, inspect the complete staged file list and staged diff specifically for sensitive data. If there is any uncertainty, stop and keep the file untracked until it has been sanitized.
- `.gitignore` is defense in depth, not permission to store sensitive files inside the repository tree.

## ⛔ MANDATORY: Test Accountability and Delivery Quality

> **THIS SECTION IS NON-NEGOTIABLE. IT OVERRIDES ALL OTHER CONSIDERATIONS INCLUDING VELOCITY, SCOPE, AND CONVENIENCE.**

**You MUST NEVER:**

1. **Ignore broken tests.** If a test fails, it is your problem. Investigate it, root-cause it, and fix it. There is no category of test failure you are permitted to disregard.

2. **Skip required tests.** For changes affecting executable behavior, build logic, or other areas meaningfully validated by automated tests, run the complete documented test suite for every affected independently maintained project — unit, integration, E2E, CLI, Playwright, and every other category that belongs to that project. Determine project boundaries from the project's README, runtime, dependencies, and test configuration, not directory depth alone. Changes to shared code, tooling, or configuration also require the suites of affected consumer projects, even when their files are unchanged. Do not run suites belonging only to unaffected projects. Changes intentionally outside automated coverage, such as documentation-only edits, comments, prose, or GitHub Actions schedule/metadata updates that the suites do not exercise, do not require tests. For mixed executable and non-executable changes, determine test scope from the executable or otherwise test-relevant portion.

3. **Hide broken tests.** You must report ALL test failures explicitly — every single one, by name, with output. Do not selectively report passing tests while omitting failures. Do not summarize a run as "passing" or "mostly passing" when any test has failed. Partial reporting is dishonest reporting.

4. **Dodge accountability.** You may NOT use phrases like "not related to my changes," "pre-existing failure," "unrelated to this work," or any variant to dismiss a failing test. If tests fail after your changes, you own them. Diagnose and fix them, or explicitly stop work and present the failures with full detail for the user to decide how to proceed. You do not get to decide which failures matter.

5. **Deliver broken or incomplete work.** Do not declare a task "done," "complete," or "ready" when any tests are failing. Do not move to the next task, commit, or create a PR with known failures. Quality is not negotiable and is never traded for speed. A broken deliverable is worse than no deliverable.

**If you find yourself wanting to skip, minimize, or explain away a test failure — STOP. That impulse is the exact problem this section exists to prevent.**

## Scope
This repository is a personal utilities monorepo of independently maintained projects with their own runtimes, dependencies, and workflows. Many projects occupy top-level folders; grouping directories such as `docker` and `web_games` contain separate nested projects.

## Core Rules
- Treat each independently maintained project as standalone, whether top-level or nested; account for shared dependencies when determining affected projects.
- Read that project's `README.md` before editing code.
- Keep changes scoped; do not refactor across unrelated projects unless explicitly asked.
- Many paths contain spaces (for example `Calculation tools`, `abacus usage`, `moneydance backup rotation`): always quote paths in shell commands.

## Documentation Discovery and Context
- **Follow documentation chains**: If a README references other docs (design docs, API specs, etc.), read those before making changes.
- **Check sibling directories**: Understand parent context and check for relevant documentation in sibling directories that might interact with your changes.
- **Document discovery**: Use `rg --files` to find files like `DESIGN.md`, `ARCHITECTURE.md`, `API.md`, or `docs/` folders.

## Robustness — Project-Specific Addition
The global CLAUDE.md defines base robustness and error handling rules. For interactive tools in this repo, gracefully handle errors and allow recovery when possible.

## Approach Before Effort

When a task is large, unfamiliar, or high-impact — or when an approach requires repeated tuning, workarounds, or accumulated rules to produce acceptable results — stop before investing further.

- Present 2-3 alternative approaches with tradeoffs before committing.
- Prefer the simplest approach that addresses the actual need.
- If an approach accumulates more than 2-3 corrective rules/workarounds and still produces inconsistent results, treat that as evidence the approach is wrong, not under-tuned.
- Do not optimize within an architecture you haven't validated. Validate the architecture first with a cheap probe, then optimize.

## Quality and Consistency
When changing existing code, maintain and extend existing frameworks:

- **Extend existing patterns**: If the project uses logging, testing, error handling, or input validation, extend those patterns to cover your changes.
- **Run validation**: After writing code, run the relevant commands from the Validation Matrix.
- **Match style**: Follow existing code style, naming conventions, and architectural patterns.
- **Complete implementations**: Avoid leaving TODOs without user approval.

### Regression Prevention
Before finalizing changes, verify you haven't:
- Removed or disabled existing logging or tests
- Bypassed existing validation or error handling
- Broken existing functionality in adjacent code

## Repo Shape (High-Level)
- Python/CLI/Streamlit tools: `tax2`, `data_format_converter`, `transcription`, `mls-tracker`, `apple-health-extract`, `md-autotax`, `md-json`, `doc_linearizer`, `div_conv`, etc.
- Browser-first single-file apps: `web_games/gorilla`, `web_games/multibody_sim`, `web_games/rps_screen`, plus HTML calculators under `Calculation tools`.
- Docker stacks and services: `docker/actual-data`, `docker/excalidraw`, `docker/llm_collector`, `docker/mermaid`, `docker/webserver`.

## Validation Matrix
Use this matrix to identify project-specific validation commands after applying the testing scope above. Run the complete documented suite for every affected independently maintained project, including affected consumers of shared changes; a command listed here does not authorize omitting another test category belonging to that project. For affected projects not listed below, follow the project's README and local documentation and run every documented test category. Changes intentionally outside automated coverage do not require tests; for mixed changes, apply the scope rule above.

- Any uv-managed launcher (`jtree`, `editdb`, `tax2`, `routerview`, `storage_monitor`, etc.):
  - After editing a launcher's header or bootstrap region, run the fleet drift guard: `uv run --script tools/check_uv_headers.py`.
- `data_format_converter`:
  - `python3 -m pytest`
- `div_conv`:
  - `pytest tests -v`
- `web_games/multibody_sim`:
  - `npm test` (Playwright; config launches local `http-server` on `127.0.0.1:4173`)
- `tax2`:
  - `python3 -m pytest` (currently minimal coverage)
  - If tax rules/table generation changed, also run `uv run --with-requirements requirements.txt cli.py generate-combined --year 2026` (or target year used by your change).
- Streamlit apps (`tax2`, `transcription`, `mls-tracker`, `md-autotax`):
  - smoke-run the app entrypoint after edits (`streamlit run ...` or project `run.sh`/`ui.sh`).
- Shell utilities (`pdf-split`, `media-dater`, `toggle_wifi`, etc.):
  - run `--help` and at least one safe/dry-run style command when available.

## Large/Vendored Directories
Avoid broad searches or edits in vendored/generated trees unless the task explicitly requires it:
- `tax2/.venv/`
- `data_format_converter/venv/`
- `docker/webserver/index/node_modules/`
- `docker/webserver/app_node/node_modules/`
- `**/__pycache__/`, `**/.pytest_cache/`

## Sensitive/Stateful Files
- Treat API keys and local state as sensitive. Do not expose secret values in diffs or logs.
- Pay special attention in `docker/llm_collector/` (`MY_API_KEY.txt`, compose/env config, extension config, state/snapshot files).
- Be careful editing runtime/state artifacts such as:
  - `transcription/session_backup.json`
  - `transcription/transcription_odometer.txt`
  - `docker/llm_collector/state.json`
  - `docker/llm_collector/snapshots/*`

## Project-Specific Notes
- `web_games/gorilla/index.html` and `web_games/multibody_sim/index.html` are intentionally single-file apps; preserve this architecture unless instructed otherwise.
- `web_games/multibody_sim/README.md` and `USER_GUIDE.md` are the maintained behavior references; keep them in sync when the single-file app changes.
- `docker/webserver/README.md` documents routing invariants; preserve static-first routing and `/files`/`/configure` behavior when touching proxy logic.

## Preferred Patterns for New Projects

### uv-Managed Launcher (Python/CLI projects)
When creating or updating a Python tool that a user runs directly, use the **uv-managed launcher pattern** used across the fleet (`jtree`, `div_conv`, `storage_monitor`, `cognitive_switchyard`, and others). The script works with zero manual setup — no separate install step, no colocated config requirement, and no README prerequisite beyond installing [uv](https://docs.astral.sh/uv/) (`brew install uv`) and running the command.

**Machine prerequisite:** uv. **New Python tools MUST NOT hand-roll venv bootstrap.**

How it works:
1. The script begins with the canonical uv shebang and a PEP 723 inline-metadata block:

   ```python
   #!/usr/bin/env -S uv run --script
   # /// script
   # requires-python = ">=3.12"
   # dependencies = [
   #     "fastapi",
   #     "uvicorn[standard]",
   # ]
   # ///
   ```

2. uv resolves the interpreter and dependencies from the header, caching the environment on first run (which may hit the network once); subsequent runs are fast. Stdlib-only tools use `dependencies = []`.
3. The script still resolves a stable runtime home under `~/.toolname/` (honoring a `<TOOL>_HOME` env override) for **mutable state only** — config, logs, databases, caches, lock files. No venv lives there.
4. On first run the launcher writes an empty or synthetic config template into the runtime home. Never embed usable private defaults. If a legacy config may contain sensitive data, do not import it automatically; document a manual local migration instead.

**Do NOT** create a private venv, write a `bootstrap_state.json` marker, define a `BOOTSTRAP_VERSION`, invoke pip, or `os.execv()`-re-exec. uv owns the environment. The fleet drift guard `tools/check_uv_headers.py` discovers tracked and non-ignored untracked launchers, checks imports at every scope, and compares PEP 723 dependencies with tracked project manifests in both directions. Run it after adding or editing a launcher, register the launcher's path, and add/update its dependency-manifest policy.

Key design rules:
- Prefer a user-home runtime directory like `~/.toolname/` over scattered fixed paths, for mutable state.
- Keep dependencies unpinned in the header unless a tool needs a specific range (e.g. `router-log-analyzer` pins `PyMuPDF>=1.24,<2`).
- Keep a tracked dev/test requirements file (or pyproject test extra) that reproduces the interpreter used by the full project suite; never rely on an untracked local venv's package history.
- Single entry point — no separate `setup.sh`.
- Under uv, the first invocation of any command (including `--help`) may resolve/cache the environment; that is expected and not worth a workaround.

When a tool has no third-party dependencies, still use the uv header with `dependencies = []` for guaranteed interpreter selection and fleet uniformity, and keep runtime files under `~/.toolname/`.

When this does **not** apply:
- Single-file HTML/JS apps (no Python, no dependencies to manage).
- Projects that already use Docker as their delivery mechanism.
- Libraries or packages meant for `pip install` distribution.

### UI: Embedded React SPA (instead of Streamlit)
When a project needs a local web UI, prefer the **embedded single-file React SPA** pattern from `editdb` over Streamlit for responsiveness, layout control, and fewer dependencies.

Stack (all loaded via CDN — no `npm install`, no `node_modules`): React 18, ReactDOM 18, Babel Standalone, Tailwind CSS, Lucide Icons (all UMD/CDN from unpkg).

Architecture:
- Python backend (FastAPI + uvicorn) serves a single HTML template via `GET /`. All React/JSX, CSS, and Tailwind config are embedded in that HTML string.
- Frontend communicates with backend via `fetch()` to `/api/*` JSON endpoints.
- State via React `useState`/`useEffect` hooks. Dark mode via Tailwind `darkMode: 'class'` with localStorage. `ErrorBoundary` wraps the app.

When this does **not** apply: quick prototypes where Streamlit's speed-to-first-render matters more, or when the user explicitly requests Streamlit.

### Port Selection (local server tools)
Never hardcode a single port. Always scan for a free port starting from the preferred default.

Pattern (Python, using only stdlib `socket`):
```python
def find_free_port(start_port, max_attempts=20):
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start_port}–{start_port + max_attempts - 1}")
```

Rules:
- Call `find_free_port(args.port)` in `main()` before starting the server or browser thread.
- If the resolved port differs from the requested one, log a warning (e.g. `"Port 8100 is in use; using port 8101 instead."`).
- Pass the resolved port to both the server (`uvicorn.run`) and the browser-open thread so they stay in sync.
- The default port in `argparse` is just a preference, not a requirement.

## Execution Guidance for Agents
- Prefer `rg`/`rg --files` for discovery.
- Prefer minimal, targeted diffs over broad formatting sweeps.
- Update documentation when behavior, interfaces, or run commands change.
- If a change affects multiple projects, including through shared dependencies, validate each affected project independently with the commands above.
- Pytest environment note (Homebrew macOS): `pytest` may be installed as a shell entrypoint even when `python3 -m pytest` fails in a specific interpreter. For test execution, prefer `pytest` first; if needed, also try `python3 -m pytest` as a secondary option.
