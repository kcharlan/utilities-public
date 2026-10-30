# AGENTS.md

## Public repository: no sensitive data

This is a public-facing repository, so anything committed here is published. Never place sensitive data in code or commit it to this repository.

- Do not add secrets, credentials, API keys, tokens, personal information, financial or brokerage data, account identifiers, institutions, holdings, securities, balances, transaction data, health or location data, customer/production data, private exports, or realistic copies of such values.
- This prohibition applies to source, tests, fixtures, examples, documentation, comments, logs, screenshots, generated artifacts, and commit messages—not only runtime configuration.
- Use conspicuously synthetic fixtures and placeholders. They must be unmistakably fake and must not reproduce a real user's values.
- Keep operational configuration and mutable state in documented user-home runtime directories outside the repository. Track only synthetic `*.example.json` templates when a template is necessary.
- Before every commit, inspect the complete staged file list and staged diff specifically for sensitive data. If there is any uncertainty, stop and keep the file untracked until it has been sanitized.
- `.gitignore` is defense in depth, not permission to store sensitive files inside the repository tree.

## Scope
This repository is a personal utilities monorepo of independently maintained projects with their own runtimes, dependencies, and workflows. Many projects occupy top-level folders; grouping directories such as `docker` and `web_games` contain separate nested projects.

## Core Rules
- Treat each independently maintained project as standalone, whether top-level or nested; account for shared dependencies when determining affected projects.
- Keep changes scoped; do not refactor across unrelated projects unless explicitly asked.
- Many paths contain spaces (for example `Calculation tools`, `abacus usage`, `moneydance backup rotation`): always quote paths in shell commands.
- Follow documentation chains: if a README references other docs (design docs, API specs, `docs/` folders), read them before making changes, and check sibling directories whose docs or code interact with your change. `rg --files` finds files like `DESIGN.md`, `ARCHITECTURE.md` and `API.md`.

## Quality and Consistency
When changing existing code, maintain and extend its existing frameworks:
- If the project uses logging, testing, error handling, or input validation, extend those patterns to cover your changes. Follow its code style, naming conventions, and architecture.
- Interactive tools handle errors gracefully and let the user recover when possible.
- After writing code, run the relevant commands from the Validation Matrix.
- Don't leave TODOs without user approval.
- Put test, acceptance and evidence directories in private OS temporary space, not `$HOME`. If a tool requires a home-directory location, record why in that project's docs. Remove everything your run created before reporting done, and only what your run created. If evidence must outlive the run, say where it is in your report.
- Run `zsh tools/check_home_residue.zsh` on demand to report old, temporary-looking direct children of `$HOME` by name and age. This heuristic does not classify or remove them and is not mandatory validation.
- Before finalizing, check you haven't removed or disabled existing logging or tests, bypassed existing validation or error handling, or broken existing functionality in adjacent code.

## Release Versions
- Every release of a versioned project must include a version bump in the same change as the released code. Publishing or deploying changed code with the previous release's version is not allowed.
- Follow the project's versioning scheme and keep maintained version declarations synchronized. Ask Kevin how to increment the version if the appropriate increment is unclear; the bump is still required before release.
- Before handoff, verify the source version, deployed version, and runtime or browser-displayed version agree wherever those interfaces expose a version. Include the released version in the completion report.
- Browser extension releases must bump `manifest.json`'s `version`; verify the deployed manifest and the browser's extension version after loading or reloading it.

## Testing Scope
This applies the global test rule (full suite, every category) to a monorepo:
- For changes affecting executable behavior, build logic, or other areas the tests exercise, run the complete documented suite for every affected independently maintained project. Determine project boundaries from the project's README, runtime, dependencies, and test configuration, not directory depth alone.
- Changes to shared code, tooling, or configuration also require the suites of affected consumer projects, even when their files are unchanged. Don't run suites that belong only to unaffected projects.
- Documentation-only edits, comments, prose, and GitHub Actions schedule or metadata updates the suites don't exercise need no tests. For mixed changes, the executable or otherwise test-relevant part sets the scope.
- Don't commit or open a PR with known test failures.

## Repo Shape (High-Level)
- Native macOS: `brew_version` (Swift CLI and menu bar app; deliberate exception to UI Shapes).
- Python/CLI/local web tools: `tax2`, `data_format_converter`, `transcription`, `mls-tracker`, `apple-health-extract`, `md-json`, `doc_linearizer`, `div_conv`, etc.
- Browser-first single-file apps: `web_games/gorilla`, `web_games/multibody_sim`, `web_games/rps_screen`, plus HTML calculators under `Calculation tools`.
- Docker stacks and services: `docker/actual-data`, `docker/excalidraw`, `docker/llm_collector`, `docker/mermaid`, `docker/webserver`.

## Validation Matrix
Project-specific validation commands, applied with the Testing Scope above. A command listed here does not authorize omitting another test category belonging to that project. For affected projects not listed below, run every test category the project's README and local documentation describe.

- Any uv-managed launcher (`jtree`, `editdb`, `tax2`, `routerview`, `storage_monitor`, etc.):
  - After editing a launcher's header or bootstrap region, run the fleet drift guard: `uv run --no-python-downloads --script tools/check_uv_headers.py`.
  - When an agent runs a uv launcher directly (e.g. `./tax2`), prefix it with `UV_PYTHON_DOWNLOADS=never` so uv never silently downloads a Python.
- Registered Python suites: from the repository root run `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py <key>` for each affected entry in `tools/project_tests.toml`; also run its non-Python categories and acceptance gates below. Install a missing browser explicitly with `--install-browsers` only when authorized.
- Shared uv header guard (`tools/check_uv_headers.py`):
  - `uv run --no-python-downloads --script tools/check_uv_headers.py` and `uv run --no-project --no-python-downloads --with pytest pytest tools/tests/test_check_uv_headers.py tools/tests/test_run_project_tests.py -q -p no:cacheprovider`.
  - Guard code changes also require the full `tax2`, `data_format_converter`, `benchmark-llm`, and `cognitive_switchyard` suites. Use the registered runner for Tax2, Data Format Converter, and Benchmark; for Cognitive create an absent project test environment with `/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv .venv`, install its documented test dependencies, and prepend its own `.venv/bin` to `PATH` for its suite.
- Migrated CLI tools (run launchers with `UV_PYTHON_DOWNLOADS=never`):
  - `"abacus usage/de-abacus.py" --help`, `anduril_steps/anduril_steps.py --help`, `worktree-helper/worktree --version` and `--list`; exercise `dloc/dloc` in a synthetic Git repository and `md-json/md_converter.py` against a synthetic input in temporary space.
  - For `Claude_plugin_converter/to_gemini_cli`, run `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py to_gemini_cli` and smoke the launcher against a synthetic category in a temporary workspace.
  - `doc_linearizer`: `bash tests/test_launcher.sh` from its project directory.
  - `reversible-skew`: `uv python find --no-python-downloads --script reversible-skew/rs.py` and the same for `reversible-skew/rs-big.py` (both must resolve Python 3.12), then the complete compatibility validation in its README.
  - `video-scenes`: `uv python find --no-python-downloads --script video-scenes/video-scenes`, then its README's synthetic Validation check in temporary space.
  - `apple-health-extract`: `bash tests/test_run_wrapper.sh` and `bash tests/test_extraction.sh` from its project directory; use only synthetic inputs.
- `benchmark-llm`: `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py benchmark_llm` from the repository root.
- `cognitive_switchyard`: install `requirements.txt` and `requirements-dev.txt` in its project `.venv`, then `.venv/bin/python -m pytest tests/ -v` from its directory, including browser E2E.
- `brew_version` (Swift command line, from repository root; see its README):
  - `make -C brew_version test` (complete Swift Testing suite, isolated release build integration tests and the shared temp-leak checker's self-test; no skips). It runs under `tools/check_no_temp_leaks.sh`, which gives the suite a private `$TMPDIR` inside the project's ignored `.build/tmp/` that it then removes, fails if the run leaves any Brew Version entry in `$TMPDIR` or the Darwin user temp dir, and removes only the run's new marker-only `TemporaryDirectory.*` there.
  - `make -C brew_version release` (signed CLI/app release and signature verification).
  - `make -C brew_version acceptance` (synthetic service test and signed harness build in a fresh private OS temporary directory; no GUI launch or real state/inventory). It and `snapshots` run their builder under `tools/check_no_temp_leaks.sh --sweep-only`: the printed home is the only entry they may leave.
  - `make -C brew_version snapshots` (twenty maintained-view PNGs in private OS temporary space, light/dark pixel and layout checks; inspect every state visually).
  - `brew_version/build/release/brew-version --help` and `brew_version/build/release/brew-version --version` (offline CLI smoke checks).
  - Native GUI and current minimum macOS 27 runtime acceptance remain separate release gates described in the project README; do not install an older OS on the owner's development machine for acceptance.
  - Deployment changes require all Static deployment/fleet audit tooling commands below, including the Brew Version installer suite and affected Market Atlas suites. Real deployment needs separate authorization.
- `anker_charge_monitor` (native app; see its README):
  - `make -C anker_charge_monitor test` (all Swift tests, scanner regressions, release/install checks, the maintained snapshot/runtime gate and the shared temp-leak checker's self-test), under `tools/check_no_temp_leaks.sh` as for Brew Version. `make -C anker_charge_monitor snapshots` runs its builder under `--sweep-only`; the printed home is the only entry it may leave.
  - Deployment changes require all Static deployment/fleet audit tooling commands below, including the app installer lifecycle suite and complete Market Atlas suites when the fleet child runner changes. Real vault/cloud, GUI and launch-at-login acceptance remain separately authorized live checks.
- `telltale` (native app; see its README):
  - Full suite: `make -C telltale test` (all Swift tests, then every script in `telltale/Tests/ReleaseChecks/`: test-isolation scanner and its regressions, notification-check runner, vendored zstd digests, release/install structure checks, the temp-leak checker's self-test, and the snapshot and acceptance builders below inside a removed scratch). `build`, `release` and the whole test run are wrapped in `telltale/tools/check_no_temp_leaks.sh`, which runs them under a private `$TMPDIR` inside the project's ignored `.build/tmp/` that it then removes, fails if the run leaves any Telltale entry in `$TMPDIR` or the Darwin user temp dir, and removes only the run's new marker-only `TemporaryDirectory.*` there (the snapshot and acceptance builders get only that sweep).
  - Release: `make -C telltale release` (signed `build/release/Telltale.app` with the stable-identity resolver and strict verification; never ad-hoc).
  - Snapshots: `make -C telltale snapshots` (synthetic renderer of the maintained app sources in a fresh private OS temporary directory; thirty-two PNGs: quiet, alerting, faster alerting, acknowledged, lasting-shift, two-provider and arrival panels; model, idle sidebar, collector and Settings views including provider states, each in light and dark, with layout and pixel checks). Inspect every printed PNG. A manual run keeps its directory and prints the `rm -r` command that removes it.
  - Acceptance build: `make -C telltale acceptance` (runs the generated synthetic service tests, then builds the ad-hoc signed `Telltale Synthetic Acceptance.app`, identifier `com.example.telltale.acceptance`, over a fresh private temporary home; prints the bundle path and never launches it). A manual run keeps its home and prints the `rm -r` command that removes it. The README's Native acceptance checklist is a separate, owner-run gate.
  - Deployment: changes to `tools/deploy_telltale.mjs` or its build inputs require all Static deployment/fleet audit tooling commands below, including the app installer lifecycle suite `tools/tests/deploy_telltale.test.mjs`, and the complete Market Atlas suites when the fleet child runner changes. Real deployment (`node tools/deploy_telltale.mjs`, `make -C telltale install`) and the README's installed-release checks need separate authorization.
- `colophon` (from `colophon/`; see its README and `docs/development.md`):
  - `make` (release build; `SQLITE_PREFIX` selects an existing Homebrew SQLite prefix).
  - `make test` (all retained C units, standalone synthetic CLI/integration, Chromium browser cases, stable-sort and asset guards).
  - `make sanitize` (same categories with ASan/UBSan), `make tsan` (retained C units with TSan).
  - `make check-assets` and `make check-sort` (local guards); individual categories: `make test-unit`, `make test-cli`, `make test-browser`.
  - Use this project's own Python 3.14 `.venv` and cached Chromium. Dependency/browser downloads require approval. Test fixtures and evidence stay outside the public checkout; wrappers sandbox real runtime/source access. Original native parity/performance tools and their `private/` workflow are not included.
- `data_format_converter`:
  - `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py data_format_converter` from the repository root.
  - Browser suite: `npm ci`, `npx playwright install chromium`, then `npm run test:browser`.
- `div_conv`:
  - `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py div_conv` from the repository root.
- `docpipe`, `etf_montecarlo`, `hysa-excel`, `router-log-analyzer`, and `vid-compiler`:
  - Run their registered suites from the repository root using `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py <key>`; keys are `docpipe`, `etf_montecarlo`, `hysa_excel`, `router_log_analyzer`, and `vid_compiler` respectively. Preserve the README's synthetic render checks when changing video processing.
- `docker/llm_collector` (from `docker/llm_collector/`):
  - Setup: `.venv/bin/python -m pip install -r requirements-dev.txt`, then `.venv/bin/python -m playwright install chromium`.
  - `.venv/bin/python -m pytest collector snapshots extension` (collector, snapshot and Chromium popup tests; no skips).
  - `zsh tests/test_local_config.zsh` and `node --test extension/test_*.js`.
  - Validate migration changes with `bash -n migrate.sh`; agents never run it, even with `--dry-run`.
- `web_games/multibody_sim`:
  - `npm test` (Playwright; config launches local `http-server` on `127.0.0.1:4173`)
- `Calculation tools/backtest` (independent nested Market Atlas project):
  - Follow `tests/README.md` for verified external data, locked Node/managed Chromium and a ready external compiler venv. Test drivers never prepare data or install dependencies. Agents never acquire market data: never run `npm run setup:data` or `npm run build` without `--offline` unless the owner explicitly asks. Where the owner has not prepared data, `npm test` and full compiler discovery cannot run; report that gate as unmet.
  - `npm test` (complete retained Node suite and all three original browser cases at flat file and isolated HTTP explicit-index targets).
  - `npm run test:synthetic` (complete invented subset and both original compiler modules; run root audit suites separately; this does not replace historical acceptance).
  - `PYTHONDONTWRITEBYTECODE=1 "$MARKET_ATLAS_TEST_PYTHON" -B -m unittest discover -s data -p 'test_*.py' -v` (full compiler suite including retained real-input reproduction; interpreter must be the prepared venv).
  - Installed browser acceptance requires separate live authorization and uses `http://127.0.0.1:7711/calculators/backtest/index.html`, checking response bytes as well as application behavior. Preserve the shared folder routing.
- Shared temp-leak checker (`tools/check_no_temp_leaks.sh`, used by the Brew Version and Anker Makefiles; Telltale keeps its own copy):
  - `tools/tests/test_check_no_temp_leaks.sh` (checker cases with a fake TMPDIR and Darwin temp dir, and both Makefiles' `test` and harness targets with a fake `swift`).
  - Changes to the checker also require the complete `brew_version` and `anker_charge_monitor` suites above.
- Static deployment/fleet audit tooling:
  - `zsh tools/tests/test_check_home_residue.zsh` (synthetic home residue audit cases).
  - `node --test tools/tests/deploy_storage_monitor.test.mjs tools/tests/deploy_colophon.test.mjs tools/tests/deploy_brew_version.test.mjs tools/tests/deploy_anker_charge_monitor.test.mjs tools/tests/deploy_telltale.test.mjs tools/tests/deploy_calculator_pages.test.mjs` (native and calculator-page installer lifecycles and shared filesystem helpers).
  - `node --test tools/tests/check_static_deployments.test.mjs`
  - `zsh tools/tests/test_check_local_deployments.zsh`
  - Changes to the static audit or its child runner also require Market Atlas's complete suites above. The app synthetic command does not implicitly run root suites.
- Docker update propagation (`docker/propagate-updates.zsh`):
  - `zsh docker/tests/test_propagate_updates.zsh` (stubbed refresh/deploy suite; no Docker, network or real deployment access).
  - `docker/propagate-updates.zsh refresh --dry-run` and `deploy --dry-run` are read-only. A real `refresh` changes lockfiles and a real `deploy` rebuilds running stacks; agents need approval for each.
- `storage_monitor` (from `storage_monitor/`):
  - `.venv/bin/python -m pytest -q` (complete unit, native protocol, integration, and browser suite; builds the walker into a temporary directory; no skips).
  - `make -C native sanitize tsan`, then `STORAGE_MONITOR_WALKER="$PWD/native/build/sanitize/storage_monitor_walk" .venv/bin/python -m pytest -q` and `STORAGE_MONITOR_WALKER="$PWD/native/build/tsan/storage_monitor_walk" .venv/bin/python -m pytest -q` (complete suite against ASan/UBSan and TSan walkers).
  - After launcher header edits, run the fleet header guard above.
  - Deployment changes also require `node --test tools/tests/deploy_storage_monitor.test.mjs` and `zsh tools/tests/test_check_local_deployments.zsh` from the repository root; shared deployment helper changes require all native installer suites above.
  - Real-disk performance and parity runs require owner approval; keep their runtime homes, outputs, and diagnostics private, outside the repository, and never commit them.
- `tax2`:
  - `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py tax2` from the repository root.
  - Run `UV_PYTHON_DOWNLOADS=never ./tax2 --help`. Create a fresh private acceptance home outside the checkout with `tax2_acceptance_home=$(mktemp -d "${TMPDIR:-/tmp}/tax2-acceptance.XXXXXX")`, then build with `TAX2_HOME="$tax2_acceptance_home" UV_PYTHON_DOWNLOADS=never ./tax2 --no-browser`. Check runtime-home/config/page modes are `0700/0600/0600` (macOS: `stat -f '%Lp' "$tax2_acceptance_home" "$tax2_acceptance_home/config.yaml" "$tax2_acceptance_home/tax2.html"`). Use synthetic preferences only; do not inspect real user config or publish runtime output into Git.
  - Repeat the build after warming the same uv cache with `TAX2_HOME="$tax2_acceptance_home" UV_PYTHON_DOWNLOADS=never UV_OFFLINE=1 ./tax2 --no-browser`. Open its `file://` page in offline Chromium, exercise calculator inputs/state allocations, and verify all three real downloads: QIF, Markdown rate schedule and CSV lookup. Require no page/console errors or external requests. The complete pytest suite includes automated offline browser/download coverage; retain the actual uv smoke build as a separate acceptance check.
  - Run `TAX2_HOME="$tax2_acceptance_home" UV_PYTHON_DOWNLOADS=never ./tax2 --no-browser --output "$tax2_acceptance_home/explicit.html"`. Confirm `explicit.html` exists with mode `0600` (`test -f "$tax2_acceptance_home/explicit.html"` and `stat -f '%Lp' "$tax2_acceptance_home/explicit.html"` on macOS).
  - If rules or payload generation change, verify the bundled expectations and rule-validation/parity/export tests in the full suite; reference exports are outputs, not calculator inputs. After launcher-header edits, also run the fleet header guard above.
  - Finally remove only this run's fresh acceptance home with `rm -r -- "$tax2_acceptance_home"`, after all acceptance checks, while retaining the variable pointing to the directory this run created.
- `mls-tracker`:
  - `.venv/bin/python -m pytest -q`
  - Run `UV_PYTHON_DOWNLOADS=never ./mls_tracker --help`, then start `UV_PYTHON_DOWNLOADS=never ./mls_tracker --no-browser --port <free-port>`, request `/`, and terminate the FastAPI process cleanly.
- Streamlit app (`transcription`):
  - Run `uv run --no-python-downloads --with pytest --with pip --with httpx --script transcription/transcription self-test` from the repository root. The owner-selected test environment is the Self-test overlay. It exercises both launcher modes and clean server shutdown with synthetic state. Launch with `UV_PYTHON_DOWNLOADS=never transcription/transcription [app|divider]`.
- Shell utilities (`pdf-split`, `media-dater`, `toggle_wifi`, etc.):
  - run `--help` and at least one safe/dry-run style command when available.

## Large/Vendored Directories
Avoid broad searches or edits in vendored/generated trees unless the task explicitly requires it: `tax2/.venv/`, `data_format_converter/.venv/`, `docker/webserver/index/node_modules/`, `docker/webserver/app_node/node_modules/`, `**/__pycache__/`, `**/.pytest_cache/`.

## Sensitive/Stateful Files
- Treat API keys and local state as sensitive. Do not expose secret values in diffs or logs.
- Pay special attention in `docker/llm_collector/` (`MY_API_KEY.txt`, compose/env config, extension config, state/snapshot files).
- Be careful editing runtime/state artifacts such as `~/.transcription/` (or its overrides), legacy `transcription/session_backup.json`, `transcription/transcription_odometer.txt`, `docker/llm_collector/state.json`, and `docker/llm_collector/snapshots/*`.

## Project-Specific Notes
- `web_games/gorilla/index.html` and `web_games/multibody_sim/index.html` are intentionally single-file apps; preserve this architecture unless instructed otherwise.
- `web_games/multibody_sim/README.md` and `USER_GUIDE.md` are the maintained behavior references; keep them in sync when the single-file app changes.
- `docker/webserver/README.md` documents routing invariants; preserve static-first routing and `/files`/`/configure` behavior when touching proxy logic.

## Preferred Patterns for New Projects

### uv-Managed Launcher (Python/CLI projects)
When creating or updating a Python tool that a user runs directly, use the **uv-managed launcher pattern** used across the fleet (`jtree`, `div_conv`, `storage_monitor`, `cognitive_switchyard`, and others). The script works with zero manual setup — no separate install step, no colocated config requirement, and no README prerequisite beyond installing [uv](https://docs.astral.sh/uv/) (`brew install uv`) and running the command.

**Machine prerequisite:** uv. New Python tools don't hand-roll venv bootstrap.

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

2. uv resolves the interpreter and dependencies from the header, caching the environment on first run (which may hit the network once); subsequent runs are fast. Stdlib-only tools still use the header, with `dependencies = []`, for guaranteed interpreter selection and fleet uniformity.
3. The script still resolves a stable runtime home under `~/.toolname/` (honoring a `<TOOL>_HOME` env override) for **mutable state only** — config, logs, databases, caches, lock files. No venv lives there.
4. On first run the launcher writes an empty or synthetic config template into the runtime home. Never embed usable private defaults. If a legacy config may contain sensitive data, do not import it automatically; document a manual local migration instead.

Don't create a private venv, write a `bootstrap_state.json` marker, define a `BOOTSTRAP_VERSION`, invoke pip, or `os.execv()`-re-exec. uv owns the environment. The fleet drift guard `tools/check_uv_headers.py` discovers tracked and non-ignored untracked launchers, checks imports at every scope, and compares PEP 723 dependencies with tracked project manifests in both directions. Run it after adding or editing a launcher, register the launcher's path, and add/update its dependency-manifest policy.

The guard also flags regular `.py` files with no shebang and a column-zero `if __name__ == "__main__":` guard (single quotes also match), except test paths and entries in `NON_UV_ENTRYPOINT_ALLOWLIST`. Test paths have a `test` or `tests` directory, a `conftest.py` name, or a name starting with `test_`. Unreadable or undecodable files are skipped; scripts without a main guard are not detected by this signal.

Key design rules:
- Prefer a user-home runtime directory like `~/.toolname/` over scattered fixed paths, for mutable state.
- Keep dependencies unpinned in the header unless a tool needs a specific range (e.g. `router-log-analyzer` pins `PyMuPDF>=1.24,<2`).
- Keep tracked test requirements (or a pyproject test extra) for the full suite. Registered projects use test-only requirements alongside launcher metadata through the shared runner; nonregistered projects document their test interpreter and dependencies. Never rely on an untracked local venv's package history.
- Single entry point — no separate `setup.sh`.
- Under uv, the first invocation of any command (including `--help`) may resolve/cache the environment; that is expected and not worth a workaround.

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

**Built page.** A launcher (normally the uv-managed launcher above) gathers data, writes one self-contained HTML file, and opens it from `file://`. Colophon is the built-page shape reference implemented in C: see [page output](colophon/src/out/page.c), [atomic I/O](colophon/src/util/atomic.c), and [runtime behavior](colophon/docs/runtime.md). For Python helper examples, use Tax2's own `tax2/taxkit/config.py` and `tax2/taxkit/page.py`.
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
- Default to Preact with hooks and htm; plain JavaScript is acceptable for small pages. Colophon (`colophon/`) predates this default and uses plain JavaScript; follow it for shape, not stack. No JSX, no CDN, and no npm, bundler, or transpile step.
- Vendor exact-version UMD or IIFE builds. Built and static pages inline them; a server may serve them from packaged files. Record each file's version, exact source URL, and SHA-256, and keep its license file, as `model_sentinel/model_sentinel/browse/assets/vendor/VERSIONS.md` does; include the required license notices in the page.
- Plain CSS with custom-property color tokens; do not use Tailwind, which needs a runtime compiler or a build step. Use framework-free chart libraries (for example uPlot) or SVG; do not use React-only libraries.
- Browser tests use Playwright Chromium, open built and static pages from `file://`, and assert that every page, including server pages, makes no external requests. Use `tools/testkit.py`'s `guard_browser_errors` to fail on `pageerror`/`console.error`, and its launcher helpers (`load_launcher`, `run_launcher`, `assert_launcher_help`) for launcher tests.
- Do not use Streamlit for new projects unless the user explicitly asks for it.

### Port Selection (local server tools)
Never hardcode a single port. Scan for a free port starting from the preferred default, using a copy of `find_free_port()` from `jtree/jtree` (stdlib `socket` only; tries 20 ports on `127.0.0.1`, then raises `RuntimeError`).
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
  - Exception for projects registered in `tools/project_tests.toml`: run their documented Python suites with `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py <key>` from the repository. Read `~/.claude/shared/python-env.md` for the complete runner, synthetic fixture and deployed-test rules and all retained safeguards. For ad hoc Python in registered projects use the utility venv; this restriction is instructional, not enforced by the heuristic hook or audit. Nonregistered projects retain the venv workflow below. Preserve all non-Python test categories.
  - Use the project's existing venv: the directory the README names (`.venv` or `venv`) for the section you are following. If the README names none, use `.venv`. Call its interpreter by path instead of activating, e.g. `<dir>/bin/python -m pytest`, `<dir>/bin/python -m pip install -r <file>`, `<dir>/bin/python script.py`. Never run a bare `pytest`, `streamlit`, `pip`, `python`, or `python3`: outside an activated venv they run on Homebrew's tools or Python, which lack the project's dependencies.
  - If the venv does not exist yet, create it under that directory name from a Homebrew interpreter by absolute path: `/opt/homebrew/bin/python3 -m venv <dir>`. If the project pins a Python version anywhere (`--python X.Y`, `pythonX.Y -m venv` in a setup script, or "Python X.Y" in the README), use `/opt/homebrew/opt/python@X.Y/bin/pythonX.Y -m venv <dir>` instead. Any README `uv venv …`, with or without `--python`, becomes `uv venv --seed --no-python-downloads --python <that Homebrew interpreter path> <dir>`. If that Homebrew Python version is not installed, stop and ask; installing a Python needs approval. Then install the documented dev/test requirements into it (`<dir>/bin/python -m pip install -r <file>` or `uv pip install --python <dir>/bin/python -r <file>`, both allowed) and any other documented setup step, such as `<dir>/bin/python -m playwright install chromium`.
  - Do not run a project script that creates or recreates a venv with a bare interpreter. The scripts under `benchmark-llm/examples` use `BENCH_BASE_PYTHON`, which only a bench run sets, so never run them directly. Check any setup script before running it. Reproduce its steps as above, keeping any version it pins, and ask before recreating a venv that already exists. Where a tool accepts an interpreter option (e.g. `Calculation tools/backtest`'s `--python`), pass an absolute Homebrew interpreter.
  - Add `--no-python-downloads` right after the subcommand in `uv run`, `uv tool run`, and `uv tree --frozen` commands, and right after `uvx` (e.g. `uvx --no-python-downloads pip-audit`). For a uv launcher run directly, see the uv-managed launcher entry in the Validation Matrix.
  - Needs approval even when a README lists it:
    - any `uv run` without `--script`, `--with`, or `--with-requirements` (e.g. `uv run --python 3.12 python -m unittest …`);
    - `uv run --with`/`--with-requirements` inside a uv project (`benchmark-llm`, `docker/llm_proxy`) without `--no-project`. Elsewhere, `--with` may only name packages the project's docs or requirements name; packages a task needs ad hoc go in the project venv instead;
    - commands that change a project's lockfile or sync its environment: `uv pip compile`, `uv sync`, `uv lock`, `uv add`, `uv remove`, and `uv tree` without `--frozen`.
