# uv Bootstrap Migration — Remediation Plan

**Goal:** Fix every defect and cleanup item found in the post-migration review of branch `uv-bootstrap-migration`, in additional commits on the same branch. Nothing is deferred to later efforts except one explicitly out-of-scope item (below). The parent plan is `docs/uv_bootstrap_migration_implementation_plan.md`; this plan supersedes it where they conflict.

**Executor profile:** capable coding agent. Descriptions, not pre-written code. Code is the source of truth — verify every claim below against the file before editing. Review evidence dated 2026-07-10; findings marked **[reproduced]** were verified by actually running the failing scenario.

**Explicitly out of scope (do not touch):** `cognitive_switchyard/cognitive_switchyard/builtin_packs/*/scripts/verify` and their session-env venv bootstrap (`bootstrap_state.json` under `$env_dir`). That is app logic for workload target repos, and its possible uv migration is a separate future effort.

---

## Decisions (defaults for this remediation — flag if unworkable, don't relitigate)

1. **Test environments stay venv-based per project** (`.venv` + a tracked requirements file), since several suites import the launcher in-process and need app deps in the pytest interpreter. Fixtures that spawn the launcher keep using `sys.executable` **provided** the dev requirements file carries the launcher's runtime deps; do not switch fixtures to spawning via the uv shebang.
2. **Never auto-install at test time.** Any conftest logic that pip-installs into the running interpreter is removed, replaced by a clear failure message naming the exact setup command.
3. **Fleet `requires-python` floor is `>=3.12` everywhere** — align other declarations (e.g. pyproject files) up to it rather than lowering headers.
4. **Where a test was deleted that covered still-live behavior, it is restored** (recovered from `git show main:<path>` and adapted), not re-invented from scratch.
5. **Shared test helpers live in `tools/`** and may be imported by project test suites via a repo-root path insert. Tests only run in-repo, so this does not violate the standalone-launcher delivery doctrine (which governs launcher runtime code, not test code).
6. **One commit per phase** (or per task where a phase is large), imperative subjects.

---

## Phase A — Correctness and behavior regressions

**Task A1 — expense_dock `--help` must stop mutating state. [reproduced]**
In `expense_dock/expense_dock`, `main()` (~line 1987) calls `ensure_runtime_dirs()` and `ensure_runtime_config()` **before** `parse_args()`. Reorder so argument parsing happens first (argparse exits on `-h/--help` before any state is touched), matching the fleet convention (see routerview, fid_div_conv, van_div_conv). Check for anything between the old call sites that depended on the dirs existing pre-parse. Regression test required (Task B1 restores it).
Verify: `EXPENSE_DOCK_HOME=$(mktemp -d)/probe ./expense_dock/expense_dock --help` exits 0 and the probe path does not exist afterward.

**Task A2 — Fix launchmaster's broken test suite (60 errors). [reproduced]**
Root cause: `launchmaster/tests/conftest.py:80` (and a duplicate fixture in `tests/test_e2e.py:~80`) spawn `[sys.executable, launchmaster, ...]`, and `launchmaster/requirements-dev.txt` lists only pytest/playwright — the interpreter has no fastapi/uvicorn now that the bootstrap re-exec is gone.
- Add the launcher's runtime deps to `requirements-dev.txt` (read them from the launcher's PEP 723 header — after Task C3 trims it).
- Deduplicate the server fixture: one definition in `conftest.py`, remove the copy in `test_e2e.py` if it is genuinely identical (verify first).
- Update the stale docstring at `conftest.py:~36` ("Must be called AFTER bootstrap has run (i.e., from inside the venv)") to describe the actual post-uv contract: the pytest interpreter must provide the launcher's deps; provision via `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.
- Rebuild the local `launchmaster/.venv` from the updated file.
Verify: `launchmaster/.venv/bin/python -m pytest -q` passes in full — all 60+ tests, including `test_e2e.py`. Report exact counts.

**Task A3 — Remove the pip-install shim from cognitive_switchyard's conftest.**
`cognitive_switchyard/tests/conftest.py:59-98`: `_sync_dev_dependencies()` runs at collection time and pip-installs missing packages into `sys.executable` — forbidden on this machine (Homebrew Python is EXTERNALLY-MANAGED) and a silent-mutation hazard in venvs. Replace with a check that, when imports are missing, fails collection with a message naming the setup command (venv + `pip install -r requirements.txt -r requirements-dev.txt`). Never install.
Also add a small test (new or in an existing suite file) asserting the switchyard PEP 723 header's dependency list is a subset of `requirements.txt` — this makes header-vs-requirements drift a red test instead of a silent gap. Parse the header with the same PEP 723 regex approach as `tools/check_uv_headers.py` (import it if practical — do not copy the regex).
Verify: full cognitive_switchyard suite passes in its `.venv`; running pytest from an interpreter missing fastapi produces the instructive error, not a pip install.

**Task A4 — Collapse the bootstrap-era argv round-trip in cognitive_switchyard.**
`cli.py:259-271` (`_initialize_runtime`, `_reconstruct_runtime_argv`) and `runtime_env.py:39-57` (`derive_runtime_settings` hand parser): the parse→serialize→re-parse loop survived its own justification. `_initialize_runtime` should call `default_runtime_settings` (runtime_env.py:24) directly with `args.runtime_root` / `args.builtin_packs_root`; delete the reconstructor and the hand parser. While there: `runtime_env.py:68` has a dead `or default_runtime_settings().builtin_packs_root` fallback, and `RuntimeSettings.runtime_paths` is typed `object` — fix both if they fall out naturally of the collapse.
**A4a — make `paths` report resolved settings.** `handle_paths` (cli.py:92) currently ignores its namespace and prints the constant `RUNTIME_HOME`, so `./switchyard --runtime-root <tmpdir> paths` accepts the flag and prints the wrong home — the exact "flag silently ignored" defect class this task's regression test exists to catch, and a diagnostics command that lies under override is actively harmful when debugging a sandboxed root. Change `handle_paths` to compute settings **purely** via `default_runtime_settings(runtime_root=..., builtin_packs_root=...)` (runtime_env.py:24 — pure path computation, verified no mkdir) and print the resolved runtime home (and builtin packs root). It must NOT call `_initialize_runtime`/`initialize_runtime_environment` — informational commands do not create state (fleet help-contract principle). Default invocation still prints the canonical `~/.cognitive_switchyard`, so the "canonical contract" semantics of the restored B4 test are preserved.
Note on syntax: `--runtime-root` is a root-parser option and must precede the subcommand — `./switchyard --runtime-root <tmpdir> paths`, never `paths --runtime-root`.
Regression tests: (a) in-process, `main(["--runtime-root", str(tmp), "paths"])` output reflects the override; (b) default `paths` prints the canonical home; (c) neither invocation creates the runtime home directory.
Verify: full suite passes; `./cognitive_switchyard/switchyard --runtime-root <tmpdir> paths` prints the override without creating it.

## Phase B — Restore deleted test coverage

**Task B1 — expense_dock: restore the two app-logic tests and the help contract.**
Recover from `git show main:expense_dock/tests/test_bootstrap.py` and `git show main:expense_dock/tests/conftest.py`:
- `test_append_expense_row_finds_headers_below_first_row` (Excel header detection / expense_id logic against `append_expense_row`, launcher ~line 652) — restore into a new `expense_dock/tests/test_app.py` (adapt imports to the current launcher via the shared loader from Task D1; the old conftest's loading approach may reference deleted bootstrap symbols — rewrite, don't port blindly).
- `test_runtime_config_is_seeded` — restore; it asserts default-config writing, which is still live behavior.
- Re-create the help contract test (`--help` with `EXPENSE_DOCK_HOME` override creates nothing) — this is the regression test for Task A1.

**Task B2 — editdb and storage_monitor: minimum viable suites.**
Both projects now collect zero tests (pytest exit 5). Create a small `tests/test_smoke.py` for each with at least: `--help` exits 0 via subprocess and creates no runtime state under an overridden `*_HOME`; the launcher module loads via the shared loader and exposes its FastAPI `app`; and one cheap behavior check per tool chosen from what the module makes easy to test in-process (e.g. editdb: a trivial request against the app with a temp SQLite db; storage_monitor: a pure helper function). Do not build big suites — the goal is that pytest collects real tests and the launchers' import-time health is covered.

**Task B3 — routerview: restore the help-contract test.**
The deleted `test_help_does_not_create_runtime_state` asserted still-live behavior (verified intact today — coverage only is missing). Add it to the existing `routerview/tests/test_startup.py` (or a new small file), using `ROUTERVIEW_HOME` override + subprocess `--help`.

**Task B4 — cognitive_switchyard: restore launcher-level tests.**
From `git show main:cognitive_switchyard/tests/test_bootstrap_smoke.py`, restore the non-bootstrap tests into a new `tests/test_launcher.py`, adapted to run the **current** `./switchyard` script as a subprocess: `--help` exits 0; the `paths` subcommand reports the canonical home by default and the resolved override when `--runtime-root` precedes it (per Task A4a — root options come before the subcommand); and a failed `start` propagates a nonzero exit code through `raise SystemExit(main())` (the exit-code propagation test is the important one — the launcher wiring currently has zero coverage). Skip the tests that asserted venv/bootstrap mechanics.

## Phase C — Dependency hygiene (PEP 723 headers)

**Task C1 — tax2: remove `httpx2` and `typer` from the launcher header.**
`tax2/tax2:13-14`. `httpx2` is an unrelated PyPI package from a pre-existing requirements.txt typo; nothing in tax2 imports httpx at all — also remove `httpx2` from `tax2/requirements.txt`. `typer` is used only by `cli.py` (which runs via `--with-requirements requirements.txt`) — remove from the header, **keep** in requirements.txt. Also check the launcher's `UploadFile, File` imports at line 33: pyflakes reports them unused — if nothing in the launcher uses any form/file/multipart feature, drop those imports AND `python-multipart` from the header; if something does, leave multipart and remove only the dead import names.

**Task C2 — Declare pydantic where it is directly imported.**
Add `pydantic` to the headers of exactly these four (each has a top-level `from pydantic import BaseModel`): `jtree/jtree:27`, `editdb/editdb:48`, `harscope/harscope:35`, `git-multirepo-dashboard/git_dashboard.py:134`. tax2 already declares it; the other launchers don't import pydantic (verified) — touch nothing else.

**Task C3 — Remove unused header dependencies.**
- `mls-tracker/mls_tracker:7` and `launchmaster/launchmaster:7`: remove `python-multipart` (no UploadFile/File/Form/multipart usage in either — verified).
- `cognitive_switchyard/switchyard:7`: remove `websockets` (the server pins `ws="wsproto"` at server.py:1426; nothing imports websockets — verified). **Keep `wsproto`** — it is load-bearing because the header uses plain `uvicorn`, not `uvicorn[standard]`. Also remove the `websockets` line from `cognitive_switchyard/requirements.txt` and the dependency list in `docs/cognitive_switchyard_design.md` (~line 1172).

**Task C4 — benchmark-llm: delete the stray lock and align python floors.**
Delete `benchmark-llm/uv.lock` (committed in f6970ad; no documented workflow consumes it — the launcher resolves from its header and the README test flow is venv+pip). Raise `pyproject.toml` `requires-python` from `>=3.10` to `>=3.12` (Decision 3). Add a small test in `benchmark-llm/tests/` asserting the `bench` header's dependency list matches `pyproject.toml`'s `[project] dependencies` and the two `requires-python` values agree — the executable cross-check that prevents the next drift. Also add a one-line note to the README test section that `uv run --extra dev pytest` is an equivalent quick path (verified working).

## Phase D — Code cleanup

**Task D1 — One shared launcher-loading test helper.**
Five differently-shaped copies of the "import an extensionless launcher via SourceFileLoader" mechanism exist: `tax2/tests/loader.py` (new in this branch, with dead `monkeypatch`/`runtime_home` params), `jtree/tests/conftest.py`, `harscope/tests/conftest.py`, `launchmaster/tests/conftest.py`, and per-file `load_module()` helpers in `docpipe/tests/test_docpipe.py` and `routerview/tests/test_startup.py`. Create `tools/testkit.py` with a single `load_launcher(path, module_name=None)` that covers the union of needs (unique module names to avoid sys.modules collisions, `__name__` override so `if __name__ == "__main__"` doesn't fire, extensionless handling via SourceFileLoader). Convert all six call sites to import it (repo-root `sys.path` insert relative to each conftest via `Path(__file__).resolve().parents[2]`). Delete `tax2/tests/loader.py`. Tasks B1/B2 use this helper too.
Verify: all converted suites still pass.

**Task D2 — Remove orphaned imports across the fleet (pyflakes-driven).**
Run `uv run --with pyflakes python -m pyflakes <all 16 launcher paths>` and fix everything it reports in launcher files, including: `editdb/editdb:383` function-local `import json` shadowing the (dead) module-level one; harscope's unused `global` statements at ~5329; tax2's unused `datetime/json/sys/Path/UploadFile/File/JSONResponse` (coordinate with C1); and the unused `sys`/`json`/`Path`/`fastapi.Request`/typing imports pyflakes lists in jtree, editdb, harscope, mls_tracker, routerview, expense_dock, storage_monitor, launchmaster. Do not "fix" pyflakes findings inside app logic beyond import/global removal — anything behavioral gets reported instead.
Verify: pyflakes clean (or an explicit list of intentionally-kept items with reasons); every launcher still runs `--help`.

**Task D3 — Normalize bootstrap-era import layout and comments.**
`editdb/editdb`, `routerview/routerview`, and `launchmaster/launchmaster` retain the two-stage import layout (minimal stdlib block, then a second "safe after bootstrap" block) whose ordering constraint died with the bootstrap. Consolidate each to a single top import block and delete stale section comments (`# === THIRD-PARTY AND STDLIB IMPORTS ===` in launchmaster ~line 25, the editdb split at ~37-48, routerview's second block at ~74). Check expense_dock and storage_monitor for lighter cases of the same. Also update module docstrings/top comments in any launcher still describing venv bootstrap behavior.
Verify: `--help` and each project's suite still pass; `tools/check_uv_headers.py` still passes.

**Task D4 — docpipe: retire the constant-true package sentinels, keep external-tool degradation.**
The PEP 723 header now guarantees all eight Python packages, so `HAS_DOCX/HAS_PPTX/HAS_OPENPYXL/HAS_PANDAS/HAS_BS4/HAS_READABILITY/HAS_MARKDOWNIFY` (docpipe:36-42) and their try/except import blocks guard an impossible condition — convert those to plain imports and remove the flags and their branch sites. **Keep** `HAS_PDFTOTEXT/HAS_PDFTOPPM/HAS_PDFINFO/HAS_PANDOC` and their detection — external binaries are genuinely optional. Fix the `init_optional_imports` docstring ("after bootstrap"). Note: the original migration plan said to preserve this layer; that instruction predates the insight that the header makes the package half unreachable — this task supersedes it.
Verify: docpipe suite passes; a conversion smoke-run on a sample file works; behavior with pandoc/poppler absent still degrades (read the code paths to confirm, and say so).

## Phase E — Tooling and docs

**Task E1 — Drift guard: discover unregistered launchers.**
`tools/check_uv_headers.py` is registry-only; a 17th launcher added without registration is silently unchecked. Add a discovery pass: scan the repo (respecting the existing vendored-dir exclusions plus `.venv`/`venv`/`node_modules`/`__pycache__`) for files whose first line is `CANONICAL_SHEBANG`; any hit not in `LAUNCHERS` (and not the guard itself) is a failure telling the author to register it. Keep it fast — read only the first line of candidate files (limit to files without an extension plus `*.py`, or use `rg`-equivalent walking in stdlib).
Optional stretch (do it if clean to implement, skip with a note if not): for registered launchers, AST-parse top-level imports and flag third-party modules absent from the header, using a small import-name→distribution alias map (e.g. `bs4→beautifulsoup4`, `docx→python-docx`, `yaml→PyYAML`, `fitz→PyMuPDF`) and treating stdlib via `sys.stdlib_module_names`. This is the check that would have caught the pydantic gap.
Verify: guard passes on the fleet; temporarily creating an unregistered file with the shebang makes it fail; revert the probe file.

**Task E2 — git-multirepo-dashboard: make the documented test path work. [reproduced]**
README (~lines 111-127) omits `uvicorn` from the venv recipe; the tracked `tests/requirements-test.txt` is worse (pytest+httpx only). Make `tests/requirements-test.txt` the complete single source (pytest, httpx, fastapi, `uvicorn[standard]`, aiosqlite, packaging; document playwright/pytest-playwright as the E2E add-on) and change the README to `pip install -r tests/requirements-test.txt` instead of an inline package list.
Verify: from a fresh venv built exactly per the updated README, unit suite passes (482 expected) — and E2E if playwright is set up (65 expected).

**Task E3 — Stale-doc sweep for bootstrap-era instructions.**
- `tax2/docs/multi_state_implementation_plan.md` (~line 89) instructs bumping `BOOTSTRAP_VERSION`; `tax2/docs/multi_state_design.md` (~131-134) describes `~/.tax2/venv` and `bootstrap_state.json`. If the multi-state work is still pending (living plan), update those passages to the uv-header reality; if it shipped, add a superseded note instead.
- `launchmaster/tests/conftest.py` docstring — covered by A2.
- Re-run the straggler grep from the parent plan (`rg -il "bootstrap_state|BOOTSTRAP_VERSION|self-bootstrap|private venv"` over docs) and fix remaining **living** docs; archived plans get a superseded line only. The cognitive_switchyard builtin-pack references are exempt (out of scope).

## Phase F — Redeploy and exit verification

**Task F1 — Refresh deployed copies.** Phases C/D edit launcher files, so every deployed copy in `~/Library/Scripts` (editdb, expense_dock, fid_div_conv, harscope, jtree, launchmaster, router_log_analyze.py, routerview, storage_monitor, van_div_conv) must be re-copied and re-verified with `--help` — same procedure and expectations as the parent plan's Phase 8 (first run per copy may print `Installed N packages`; that's the per-path env rebuild).

**Task F2 — Full exit verification (mandatory, report all results by name):**
1. `uv run --script tools/check_uv_headers.py` passes, including the new discovery pass.
2. Every project suite passes via its documented command — including launchmaster (was 60 errors), expense_dock/editdb/storage_monitor (were zero tests), benchmark-llm (`uv run --extra dev pytest`), git-dashboard unit + E2E per updated README, cognitive_switchyard full suite. Report exact pass counts per project; no failure may be waved off.
3. Pyflakes clean across the 16 launchers (or documented exceptions).
4. Help-no-state probes pass for expense_dock, routerview, and the Task B2 pair.
5. All 16 launchers run `--help` via shebang; deployed copies verified (F1).
6. `git status` clean, new files tracked (`tools/testkit.py`, new test files), `uv.lock` deletion committed.

## Known-good baseline for comparison (review of 2026-07-10)

jtree 168 / harscope 163 / mls-tracker 74 / tax2 25 / routerview 18 / cognitive_switchyard 484 / docpipe 4 / fid_div_conv 5 / van_div_conv 3 / router-log-analyzer 33 / benchmark-llm 54 / git-dashboard 482+65 — all passing. launchmaster 60 errors; editdb, storage_monitor, expense_dock zero tests. Remediation must end with every project ≥ its baseline and the broken/empty ones green with real coverage.
