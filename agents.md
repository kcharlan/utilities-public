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
- Python/CLI/local web tools: `tax2`, `data_format_converter`, `transcription`, `mls-tracker`, `apple-health-extract`, `md-json`, `doc_linearizer`, `div_conv`, etc.
- Browser-first single-file apps: `web_games/gorilla`, `web_games/multibody_sim`, `web_games/rps_screen`, plus HTML calculators under `Calculation tools`.
- Docker stacks and services: `docker/actual-data`, `docker/excalidraw`, `docker/llm_collector`, `docker/mermaid`, `docker/webserver`.

## Validation Matrix
Use this matrix to identify project-specific validation commands after applying the testing scope above. Run the complete documented suite for every affected independently maintained project, including affected consumers of shared changes; a command listed here does not authorize omitting another test category belonging to that project. For affected projects not listed below, follow the project's README and local documentation and run every documented test category. Changes intentionally outside automated coverage do not require tests; for mixed changes, apply the scope rule above.

- Any uv-managed launcher (`jtree`, `editdb`, `tax2`, `routerview`, `storage_monitor`, etc.):
  - After editing a launcher's header or bootstrap region, run the fleet drift guard: `uv run --no-python-downloads --script tools/check_uv_headers.py`.
  - When an agent runs a uv launcher directly (e.g. `./tax2`), prefix it with `UV_PYTHON_DOWNLOADS=never` so uv never silently downloads a Python.
- `colophon`:
  - `.venv/bin/python -m pytest -q` from `colophon/` (unit, CLI, browser and scaling tests; no skips).
  - After launcher header edits: `uv run --no-python-downloads --script tools/check_uv_headers.py` from the repository root.
  - Local acceptance requires explicit approval for real data; outputs are private and never committed. Run `colophon/tests/perf/measure_throughput.py`, `colophon/tests/parity/compare_codexbar.py`, and after curated pricing changes `colophon/tests/parity/check_upstream_tables.py` with `colophon/.venv/bin/python` from the repository root; follow the project README for arguments and the guarded native oracle.
- `data_format_converter`:
  - `.venv/bin/python -m pytest`
  - Browser suite: `npm ci`, `npx playwright install chromium`, then `npm run test:browser`.
- `div_conv`:
  - `.venv/bin/python -m pytest tests -v`
- `web_games/multibody_sim`:
  - `npm test` (Playwright; config launches local `http-server` on `127.0.0.1:4173`)
- `Calculation tools/backtest` (independent nested Market Atlas project):
  - Follow `tests/README.md` for verified external data, locked Node/managed Chromium and a ready external compiler venv. Test drivers never prepare data or install dependencies. Agents never acquire market data: never run `npm run setup:data` or `npm run build` without `--offline` unless the owner explicitly asks. Where the owner has not prepared data, `npm test` and full compiler discovery cannot run; report that gate as unmet.
  - `npm test` (complete retained Node suite and all three original browser cases at flat file and isolated HTTP explicit-index targets).
  - `npm run test:synthetic` (complete invented subset and both original compiler modules; run root audit suites separately; this does not replace historical acceptance).
  - `PYTHONDONTWRITEBYTECODE=1 "$MARKET_ATLAS_TEST_PYTHON" -B -m unittest discover -s data -p 'test_*.py' -v` (full compiler suite including retained real-input reproduction; interpreter must be the prepared venv).
  - Installed browser acceptance requires separate live authorization and uses `http://127.0.0.1:7711/calculators/backtest/index.html`, checking response bytes as well as application behavior. Preserve the shared folder routing.
- Static deployment/fleet audit tooling:
  - `node --test tools/tests/check_static_deployments.test.mjs`
  - `zsh tools/tests/test_check_local_deployments.zsh`
  - Changes to the static audit or its child runner also require Market Atlas's complete suites above. The app synthetic command does not implicitly run root suites.
- `tax2`:
  - `.venv/bin/python -m pytest`
  - Run `UV_PYTHON_DOWNLOADS=never ./tax2 --help`. Create a fresh private acceptance home outside the checkout with `tax2_acceptance_home=$(mktemp -d "$HOME/.tax2-acceptance.XXXXXX")`, then build with `TAX2_HOME="$tax2_acceptance_home" UV_PYTHON_DOWNLOADS=never ./tax2 --no-browser`. Check runtime-home/config/page modes are `0700/0600/0600` (macOS: `stat -f '%Lp' "$tax2_acceptance_home" "$tax2_acceptance_home/config.yaml" "$tax2_acceptance_home/tax2.html"`). Use synthetic preferences only; do not inspect real user config or publish runtime output into Git.
  - Repeat the build after warming the same uv cache with `TAX2_HOME="$tax2_acceptance_home" UV_PYTHON_DOWNLOADS=never UV_OFFLINE=1 ./tax2 --no-browser`. Open its `file://` page in offline Chromium, exercise calculator inputs/state allocations, and verify all three real downloads: QIF, Markdown rate schedule and CSV lookup. Require no page/console errors or external requests. The complete pytest suite includes automated offline browser/download coverage; retain the actual uv smoke build as a separate acceptance check.
  - Run `TAX2_HOME="$tax2_acceptance_home" UV_PYTHON_DOWNLOADS=never ./tax2 --no-browser --output "$tax2_acceptance_home/explicit.html"`. Confirm `explicit.html` exists with mode `0600` (`test -f "$tax2_acceptance_home/explicit.html"` and `stat -f '%Lp' "$tax2_acceptance_home/explicit.html"` on macOS).
  - If rules or payload generation change, verify the bundled expectations and rule-validation/parity/export tests in the full suite; reference exports are outputs, not calculator inputs. After launcher-header edits, also run the fleet header guard above.
  - Finally remove only this run's fresh acceptance home with `rm -r -- "$tax2_acceptance_home"`, after all acceptance checks, while retaining the variable pointing to the directory this run created.
- `mls-tracker`:
  - `.venv/bin/python -m pytest -q`
  - Run `UV_PYTHON_DOWNLOADS=never ./mls_tracker --help`, then start `UV_PYTHON_DOWNLOADS=never ./mls_tracker --no-browser --port <free-port>`, request `/`, and terminate the FastAPI process cleanly.
- Streamlit apps (`transcription`):
  - Smoke-run each Streamlit entrypoint you edited, headless, then terminate it cleanly: `venv/bin/python -m streamlit run <entrypoint> --server.headless true` from the project directory. The entrypoints are `transcription`'s `app.py` and `transcribe.py`. `transcription`'s `run.sh`, `m4a-run.sh`, and `help.sh` are unsupported legacy wrappers; do not use them.
- Shell utilities (`pdf-split`, `media-dater`, `toggle_wifi`, etc.):
  - run `--help` and at least one safe/dry-run style command when available.

## Large/Vendored Directories
Avoid broad searches or edits in vendored/generated trees unless the task explicitly requires it:
- `tax2/.venv/`
- `data_format_converter/.venv/`
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
   #     "pyyaml",
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

### UI Shapes
These rules govern **new projects** unless the user chooses otherwise. Existing projects keep their current shape and front-end stack until the user deliberately ports them; do not change either as part of unrelated work. Existing React CDN apps keep the contracts in `tools/testkit.py` (`assert_react_19_import_map`, `assert_react_esm_graph`).

Answer in order and stop at the first match:
0. **Out of scope.** Delivered as a Docker stack, a library, a browser extension, or a background agent such as a `launchd` job? Follow that delivery model; these rules do not apply.
1. **No browser UI.** If terminal output, files, or text, CSV, or Markdown reports serve the user, build a command-line tool.
2. **Local server.** Once the page is open, does it need to:
   - change something outside the browser, aimed at an item the user finds in the page (save an edit back to its file, delete a file, stop a job)?
   - run Python libraries or native programs, or make network requests, on what the user enters or picks in the page?
   - apply security-sensitive logic (redaction, sanitizing, anything whose bug leaks a secret) to what the user enters or picks?
   - show outside state (files, processes, jobs) that changes while the user watches?
   - query detail too large to embed even after summarizing at build time?

   Yes to any → local server. These do not count: page-local state (browser storage, the URL, the clipboard), browser downloads and save dialogs for new files, links that open in a new browser tab, links and copied commands that hand off to another application (never for destructive changes), and general actions the user runs before opening the page (import, rescan, refresh), which become CLI subcommands.
3. **Built page (default).** Everything else. If the page needs only what the user types or picks with a file picker, make it a static page instead.

**Built page.** A launcher (normally the uv-managed launcher above) gathers data, writes one self-contained HTML file, and opens it from `file://`. `colophon` is the reference.
- Python gathers, validates, and precomputes, including every network request. Logic that depends on interaction in the page lives only in JavaScript; no logic lives in both. If a CLI path also needs that logic, drop the CLI path or use a local server.
- Security-sensitive logic runs only in Python: at build time, or behind a local server when the user applies it from the page (step 2).
- Embed data in the page (for example `<script type="application/json">`); never `fetch()` local files. Inline all scripts, styles, and fonts; the page makes no external requests.
- By default write the page to a fixed path in a 0700 runtime home (`~/.toolname/`), replaced atomically with mode 0600; an explicit user-chosen output path gets the same mode. Never write it into the repository or a shared folder such as Downloads by default. Never embed credentials or tokens. Show the build time in the page; refreshing means rerunning the command.
- Summarize unbounded data at build time so the page stays a manageable size.
- A built page may have CLI subcommands that maintain a store in the runtime home (import, scan, refresh); the page is a view of that store.
- Prefix browser-storage keys with the tool name; pages opened from `file://` may share a storage origin.

**Static page.** One HTML file with no launcher. It inlines everything, makes no external requests, and prefixes its storage keys. Inputs come from form fields or the File API; outputs leave as browser downloads. `web_games/gorilla` and `Calculation tools/money_sense_calculators.html` are examples.

**Local server.** The exception. Python (FastAPI + uvicorn, or the standard library for read-only tools) serves the page and `/api/*` JSON endpoints.
- Bind to `127.0.0.1` only and select the port as described in Port Selection below.
- Block other websites from driving the API: reject any request whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>` (as `model_sentinel/model_sentinel/browse/server.py` `_valid_host` does; Starlette's `TrustedHostMiddleware` ignores the port, so FastAPI needs custom middleware); never change state on GET or HEAD; reject other methods unless `Origin` is present and equals the server's own origin; never send CORS headers.
- Use the same vendored front-end stack as built pages, so the UI also works offline; fetch data from `/api/*` instead of embedding it.

**Front-end stack (all three shapes).**
- Default to Preact with hooks and htm; plain JavaScript is acceptable for small pages. `colophon` predates this default and uses plain JavaScript; follow it for shape, not stack. No JSX, no CDN, and no npm, bundler, or transpile step.
- Vendor exact-version UMD or IIFE builds. Built and static pages inline them; a server may serve them from packaged files. Record each file's version, exact source URL, and SHA-256, and keep its license file, as `model_sentinel/model_sentinel/browse/assets/vendor/VERSIONS.md` does; include the required license notices in the page.
- Plain CSS with custom-property color tokens; do not use Tailwind, which needs a runtime compiler or a build step. Use framework-free chart libraries (for example uPlot) or SVG; do not use React-only libraries.
- Browser tests use Playwright Chromium, open built and static pages from `file://`, and assert that every page, including server pages, makes no external requests. Use `tools/testkit.py`'s `guard_browser_errors` to fail on `pageerror`/`console.error`, and its launcher helpers (`load_launcher`, `run_launcher`, `assert_launcher_help`) for launcher tests.
- Do not use Streamlit for new projects unless the user explicitly asks for it.

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
- Pass the resolved port to both the server (`uvicorn.run` or the standard-library server) and the browser-open thread so they stay in sync.
- The default port in `argparse` is just a preference, not a requirement.

## Execution Guidance for Agents
- Prefer `rg`/`rg --files` for discovery.
- Prefer minimal, targeted diffs over broad formatting sweeps.
- Update documentation when behavior, interfaces, or run commands change.
- If a change affects multiple projects, including through shared dependencies, validate each affected project independently with the commands above.
- Python as an agent (Homebrew macOS). Agents on this setup run Python only inside a virtual environment. Project READMEs are written for developers on any platform and often assume an activated venv (`source venv/bin/activate`, then `python …`, `pip …`, `pytest …`). Do not run their Python setup and test commands literally; translate them:
  - Use the project's existing venv: the directory the README names (`.venv` or `venv`) for the section you are following. If the README names none, use `.venv`. Call its interpreter by path instead of activating, e.g. `<dir>/bin/python -m pytest`, `<dir>/bin/python -m pip install -r <file>`, `<dir>/bin/python script.py`. Never run a bare `pytest`, `streamlit`, `pip`, `python`, or `python3`: outside an activated venv they run on Homebrew's tools or Python, which lack the project's dependencies.
  - If the venv does not exist yet, create it under that directory name from a Homebrew interpreter by absolute path: `/opt/homebrew/bin/python3 -m venv <dir>`. If the project pins a Python version anywhere (`--python X.Y`, `pythonX.Y -m venv` in a setup script, or "Python X.Y" in the README), use `/opt/homebrew/opt/python@X.Y/bin/pythonX.Y -m venv <dir>` instead. Any README `uv venv …`, with or without `--python`, becomes `uv venv --seed --no-python-downloads --python <that Homebrew interpreter path> <dir>`. If that Homebrew Python version is not installed, stop and ask; installing a Python needs approval. Then install the documented dev/test requirements into it (`<dir>/bin/python -m pip install -r <file>` or `uv pip install --python <dir>/bin/python -r <file>`, both allowed) and any other documented setup step, such as `<dir>/bin/python -m playwright install chromium`.
  - Do not run a project script that creates or recreates a venv with a bare interpreter. Examples include the `setup.sh` scripts in `transcription`, `reversible-skew`, `video-scenes`, `md-json`, and `apple-health-extract`, `docker/llm_collector/migrate.sh`, and scripts under `benchmark-llm/examples`. Check any setup script before running it. Reproduce its steps as above, keeping any version it pins, and ask before recreating a venv that already exists. Where a tool accepts an interpreter option (e.g. `Calculation tools/backtest`'s `--python`), pass an absolute Homebrew interpreter.
  - Add `--no-python-downloads` right after the subcommand in `uv run`, `uv tool run`, and `uv tree --frozen` commands, and right after `uvx` (e.g. `uvx --no-python-downloads pip-audit`). For a uv launcher run directly, see the uv-managed launcher entry in the Validation Matrix.
  - Needs approval even when a README lists it:
    - any `uv run` without `--script`, `--with`, or `--with-requirements` (e.g. `uv run --python 3.12 python -m unittest …` and `uv run …/migrate_skills.py` in `Claude_plugin_converter/to_gemini_cli`);
    - `uv run --with`/`--with-requirements` inside a uv project (`benchmark-llm`, `docker/llm_proxy`) without `--no-project` (e.g. `uv run --extra dev pytest` in `benchmark-llm` is approval-only too). Elsewhere, `--with` may only name packages the project's docs or requirements name; packages a task needs ad hoc go in the project venv instead;
    - commands that change a project's lockfile or sync its environment: `uv pip compile`, `uv sync`, `uv lock`, `uv add`, `uv remove`, and `uv tree` without `--frozen`.
