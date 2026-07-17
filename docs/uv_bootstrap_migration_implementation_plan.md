# uv Bootstrap Migration — Implementation Plan

**Goal:** Replace every hand-rolled self-bootstrapping venv launcher in this monorepo with `uv run` + PEP 723 inline script metadata, delete the ~2,000 lines of duplicated bootstrap code and its duplicated tests, update all documentation of the pattern, refresh deployed copies in `~/Library/Scripts`, and clean the now-obsolete venvs and bootstrap state off the machine.

**Executor profile:** A capable coding agent. This plan describes *what* to build and the constraints; it does not pre-write implementation code. Where something is tricky or load-bearing, the exact fragment or rule is given. Everything else you derive from the code.

**Source of truth is the code, not this plan.** Inventory tables below are orientation from a survey dated 2026-07-10. Before editing any file, read it and confirm the details (dependency lists, env var names, runtime-home paths). If the plan and code disagree, the code wins.

---

## Decisions already made (defaults — do not relitigate, but flag if one proves unworkable)

1. **No per-script lock files.** Dependencies stay unpinned in the PEP 723 header, matching today's behavior. Tools that already pin ranges (`router-log-analyzer`) keep their existing version specifiers in the header.
2. **No "uv missing" shim.** If uv is absent, the shebang fails with a shell error. The prerequisite is documented in READMEs instead. Do not add fallback bootstrap code.
3. **Stdlib-only tools (`fid_div_conv`, `van_div_conv`) get the uv header too**, with an empty `dependencies = []` list, for fleet uniformity and guaranteed interpreter selection.
4. **`model_sentinel` is untouched.** It is the zipapp-form reference, stdlib-only at runtime, and has no bootstrap layer.
5. **Runtime homes (`~/.toolname/`) survive.** Only the venv/bootstrap machinery is removed. Config, databases, logs, caches, and legacy-config import logic all stay. The `<TOOL>_HOME` env-var overrides keep working for the data home; only their venv-location branches are removed.
6. **`requires-python = ">=3.12"`** fleet-wide unless a specific tool's code demands otherwise. (All tools currently run under Homebrew Python 3.14.6, so this is safe.)
7. **Accepted behavior change:** `--help` currently has a fast path that avoids bootstrap. Under uv, the *very first* invocation of any command (including `--help`) resolves and caches the environment, which may hit the network. Subsequent runs are cached and fast. Do not build a workaround.
8. **Deployment stays copy-based.** `~/Library/Scripts` entries are plain copies today; refresh them as copies. (Symlinking is a future option, not part of this migration.)

---

## The canonical header (exact fragment — precision matters)

Every migrated launcher begins with:

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

Load-bearing details:

- Keep `--script` in the shebang. Validation on the installed uv (0.11.28) showed PEP 723 metadata is honored on extensionless files even without it, but the flag is the documented explicit form and guards against future argument-disambiguation changes. Do not omit it.
- The `# /// script` block must appear before any code, in exact PEP 723 comment format. The block body is TOML: extras like `uvicorn[standard]` must be quoted strings, and version specifiers go inline (e.g. `"PyMuPDF>=1.24,<2"`).
- The dependency list for each tool is **extracted from that tool's existing code** (`DEPENDENCIES` constant, `*_PACKAGES` constant, `requirements.txt`, or pip args) — never invented, never copied from this plan's table without verification.

## What gets removed vs. kept in each launcher

**Remove** (the bootstrap region, typically 75–215 lines): `BOOTSTRAP_VERSION` constant, `bootstrap_state.json` read/write/compare functions, venv path fields and creation (`venv.EnvBuilder` / `venv.create`), pip invocation and its flags, venv health checks, the `os.execv` re-exec and its in-venv guard, the `--help`/`--version` bootstrap fast path, wipe-and-rebuild logic, and any Windows-specific bootstrap branches. Also remove imports that become unused (`venv`, often `subprocess` — check each use site first; several tools use `subprocess` for app logic too).

**Keep**: runtime-home resolution and creation (`~/.toolname/`), default-config writing, legacy config import, `find_free_port`, all app logic, all progress/error messaging unrelated to venv setup.

**Definition of a migrated launcher:** starts with the canonical header, contains no occurrence of `BOOTSTRAP_VERSION`, `bootstrap_state`, `os.execv`, or venv creation, and `uv run --script ./<tool> --help` exits 0 without creating any `venv` directory or `bootstrap_state.json`.

---

## Inventory (orientation only — verify against code)

| Tool | Launcher file | Deps declared today via | Venv path(s) today | Has `tests/test_bootstrap*.py` |
|---|---|---|---|---|
| editdb | `editdb/editdb` | `DEPENDENCIES` list | `~/.editdb/venv` (+ orphan `~/.editdb_venv`) | yes |
| jtree | `jtree/jtree` | `DEPENDENCIES` list | `~/.jtree/venv` (+ orphan `~/.jtree_venv`) | yes |
| harscope | `harscope/harscope` | `DEPENDENCIES` list | `~/.harscope/venv` (+ orphan `~/.harscope_venv`) | yes |
| mls-tracker | `mls-tracker/mls_tracker` | `DEPENDENCIES` list | `~/.mls_tracker/venv` (+ orphan `~/.mls_tracker_venv`) | yes |
| docpipe | `docpipe/docpipe` | `DOCPIPE_PACKAGES` list | `~/.docpipe/venv` (+ orphan `~/.docpipe_venv`) | yes |
| storage_monitor | `storage_monitor/storage_monitor` | `DEPENDENCIES` list | `~/.storage_monitor/venv` | yes |
| tax2 | `tax2/tax2` | `requirements.txt` + sha256 marker | `~/.tax2/venv` | yes |
| routerview | `routerview/routerview` | `DEPENDENCIES` list | `~/.routerview_venv` (sibling) | yes |
| expense_dock | `expense_dock/expense_dock` | `DEPENDENCIES` list | `~/.expense_dock_venv` (sibling) | yes |
| git-multirepo-dashboard | `git-multirepo-dashboard/git_dashboard.py` | `DEPENDENCIES` list | `~/.git_dashboard_venv` (sibling) | yes (`test_bootstrap_state.py`) |
| launchmaster | `launchmaster/launchmaster` | `DEPENDENCIES` list | `~/.launchmaster_venv` (sibling) | yes |
| router-log-analyzer | `router-log-analyzer/router_log_analyze.py` | pinned list + `PIP_*` env vars | `~/.router-log-analyzer/venv` | no |
| fid_div_conv | `fid_div_conv/fid_div_conv` | none (stdlib) | `~/.fid_div_conv/venv` | yes |
| van_div_conv | `van_div_conv/van_div_conv` | none (stdlib) | `~/.van_div_conv/venv` | no |
| benchmark-llm | `benchmark-llm/bench` | `pip install -e` editable | `~/.benchmark_llm/venv` | no |
| cognitive_switchyard | `cognitive_switchyard/cognitive_switchyard/bootstrap.py` | `requirements.txt` | `~/.cognitive_switchyard/.../bootstrap_venv` (+ orphans `~/.cognitive_switchyard_venv`, `~/.switchyard_venv`) | yes (`test_bootstrap_smoke.py`) |
| model_sentinel | — (zipapp) | build-time only | none | n/a — **do not touch** |

---

## Phase 0 — Prerequisites and baseline

**Task 0.1 — Verify uv.** uv is already installed (`uv 0.11.28`, Homebrew, at `/opt/homebrew/bin/uv`; cache at `~/.cache/uv`). Confirm `uv --version` still reports ≥0.11.28. If it were ever missing, install via `brew install uv` — never via pip.

The following uv behaviors were validated on this machine (2026-07-10) and can be relied on without re-verification:
- The canonical shebang works on extensionless executable files; args pass through to the script's argparse untouched.
- Script environments live under `~/.cache/uv/environments-v2/<name>-<hash>`, keyed per script **path**, and are re-synced to the PEP 723 header on every run — adding/removing a dependency in the header auto-installs/removes it with no version bump or manual invalidation.
- No venv directory or state file is created next to the script or under `~/`.
- Extras (`coverage[toml]`-style) and pinned specifiers (`packaging>=23,<26`) in the header install correctly.
- `dependencies = []` (stdlib-only) works.
- `requires-python` is enforced with a clear error when unsatisfiable.
- Concurrent first-runs of the same script are safe (three simultaneous invocations: one install, all succeeded).
- `uv lock --script`, `uv run --project`, and `uv run --with-editable` all exist on this version (fallback options referenced in Tasks 4.3/4.4).

**Task 0.2 — Entry test baseline (mandatory).** This is a batch refactor, so run the **full test suite of every project listed in the inventory** before changing anything. Use `pytest` from each project directory (per repo CLAUDE.md, prefer the `pytest` entrypoint; fall back to `python3 -m pytest` inside the project's venv where one exists, e.g. `tax2/.venv`). Record every pre-existing failure by name with output in a scratch note so post-migration failures can be attributed honestly. If a project's tests cannot run at all, record that too.

**Task 0.3 — Snapshot the machine state.** Record the current output of `ls -d ~/.*/venv ~/.*_venv` and `ls -l ~/Library/Scripts` into the same scratch note. This is the checklist for Phases 8–9. Known state as of 2026-07-10: sibling venvs exist for editdb, harscope, jtree, mls_tracker, docpipe, cognitive_switchyard (×2 orphans: `.cognitive_switchyard_venv`, `.switchyard_venv`), routerview, expense_dock, git_dashboard, launchmaster; in-home venvs exist for editdb, fid_div_conv, harscope, jtree, mls_tracker, storage_monitor, tax2, van_div_conv, router-log-analyzer, benchmark_llm.

---

## Phase 1 — Pilot migration: `jtree`

Migrate one simple, test-covered, FastAPI-based tool first to validate the recipe end to end before batching.

**Task 1.1 — Migrate `jtree/jtree`** using the per-tool recipe:

1. Read the launcher fully. Identify the bootstrap region and the keep-list (see "What gets removed vs. kept").
2. Extract the dependency list from the code.
3. Add the canonical header; delete the bootstrap region and unused imports.
4. Preserve `JTREE_HOME`-style data-home override if present; delete only venv-related branches.
5. Delete `jtree/tests/test_bootstrap.py`. Grep the remaining tests for references to deleted functions/constants and fix or remove those references.
6. Update `jtree/README.md`: remove self-bootstrap description; add a short "Requirements: [uv](https://docs.astral.sh/uv/) (`brew install uv`). Run: `./jtree`" section; note that the first run downloads dependencies.
7. Verify (all four, report actual output):
   - `uv run --script ./jtree --help` exits 0 and creates no `venv` dir or `bootstrap_state.json` anywhere under `~`.
   - Full project test suite passes.
   - Smoke-run the app: launch it, confirm the server comes up and the UI/health endpoint responds, then stop it.
   - `rg -n "BOOTSTRAP_VERSION|bootstrap_state|os\.execv|EnvBuilder|venv\.create" jtree/` returns nothing.
8. Commit (imperative subject, e.g. `Migrate jtree to uv-managed PEP 723 bootstrap`).

**Task 1.2 — Checkpoint.** If anything in the recipe didn't fit reality (header placement, shebang behavior on extensionless files, test fallout pattern), adjust the recipe notes before proceeding. If the pilot surfaces a fundamental problem with the uv approach itself, **stop and report rather than improvising a hybrid**.

---

## Phase 2 — Batch: classic single-file tools

Apply the Task 1.1 recipe, one commit per tool, to:

**Task 2.1 — `editdb`** • **Task 2.2 — `harscope`** • **Task 2.3 — `mls-tracker`** • **Task 2.4 — `storage_monitor`**

Straightforward recipe applications.

**Task 2.5 — `docpipe`.** Extra constraints: preserve the `init_optional_imports` graceful-degradation logic (missing optional tools like Pandoc/Poppler must still degrade, not crash) and put all `DOCPIPE_PACKAGES` entries in the header. The current bootstrap runs `pip install --upgrade pip` first — that concept has no uv equivalent and is simply dropped.

**Task 2.6 — `tax2`.** Extra work: dependencies live in a `requirements.txt`, and the state marker adds a `requirements_sha256` field with supporting hash code — remove that machinery entirely (uv's cache keying replaces it). Fold the requirements into the header, preserving any version specifiers. Before deleting `requirements.txt`, grep the project (and its docs/CI, if any) for references to it; if the repo-local dev venv setup (`tax2/.venv`) or docs depend on it, keep the file and note in the README that the launcher no longer reads it — the header is authoritative. Exit checks additionally include the validation-matrix command `python3 cli.py generate-combined --year 2026` **only if** your changes touched anything the CLI shares; otherwise the standard suite + smoke-run applies. `tax2/tests/test_bootstrap.py` asserts the sha256 field — it gets deleted with the rest.

---

## Phase 3 — Batch: sibling-venv tools

Same recipe; these differ only in that the venv defaulted to `~/.tool_venv` beside the home, with an in-home venv when the `*_HOME` override was set. Both branches are venv logic — remove both; keep the data-home override.

**Task 3.1 — `routerview`.** Note `routerview/docs/DESIGN.md` and `README.md` both describe the venv/bootstrap model — update them.

**Task 3.2 — `expense_dock`.**

**Task 3.3 — `git-multirepo-dashboard` (`git_dashboard.py`).** Extra: this is the only launcher with Windows bootstrap support (`Scripts/python.exe`, `subprocess.run` re-exec fallback) — delete it; uv is cross-platform natively. It also has a `UTILITIES_TESTING` env flag wired into bootstrap: read how `tests/test_bootstrap_state.py` and any other tests use it before deleting; if non-bootstrap tests rely on the flag for other behavior (e.g., suppressing browser open), keep that part.

---

## Phase 4 — Oddballs (each needs judgment)

**Task 4.1 — `launchmaster`.** Functionally the standard recipe, but this copy was hand-ported to `os.path`/string style and re-execs `sys.argv[0]` instead of `__file__`. Nothing special survives — same removal rules.

**Task 4.2 — `router-log-analyzer` (`router_log_analyze.py`).** Keep its pinned specifiers (e.g. `PyMuPDF>=1.24,<2`) in the header. Remove the belt-and-suspenders `PIP_*` env var exports along with the pip code. It exempts both `--help` and `--version` from bootstrap today — both exemptions disappear (Decision 7). It has **no** bootstrap tests but does have `test_router_log_analyze.py` — run it in full.

**Task 4.3 — `benchmark-llm` (`bench`).** Trickiest one. Today `bench` creates a venv and does `pip install -e <project>` (editable self-install), then re-execs `python -m benchmark_llm`. PEP 723 cannot express an editable self-install. Approach: read the project's packaging metadata (`pyproject.toml`/`setup.py`) to find its *third-party* dependencies; put those in the header; have the script import the adjacent `benchmark_llm` package directly (the script's own directory is on `sys.path`, so a launcher sitting next to the package can import it — verify the actual layout and adjust, e.g. via a `sys.path` insert relative to `__file__` resolved through symlinks). This tool requires the repo checkout anyway (editable install), so repo-relative imports do not weaken its delivery model. If the package layout makes this genuinely awkward, `uv run --project` or `uv run --with-editable` (both confirmed present in uv 0.11.28) are fallbacks — but try the plain header first.

**Task 4.4 — `cognitive_switchyard`.** The only modular bootstrap: `cognitive_switchyard/cognitive_switchyard/bootstrap.py` (~240 lines, dependency-injected, with a `command_needs_bootstrap` allowlist and pip-notice retry logic). Work:
- Find the actual entry point (top-level launcher script and/or `__main__.py`) and how it calls bootstrap.
- Give the launcher the canonical header with deps from `requirements.txt`; same `requirements.txt` retention rule as tax2 (grep for other consumers first).
- Delete `bootstrap.py` and `tests/test_bootstrap_smoke.py`. Then grep the whole package and test suite (`test_cli.py`, `test_config.py`, others) for imports from `bootstrap` and for the `command_needs_bootstrap` concept; remove or rewrite affected call sites. The subcommand allowlist existed only to skip bootstrap for cheap commands — with uv it has no purpose.
- This project has real internal structure; expect the most test fallout of any task. Run its full suite and fix everything before committing.

---

## Phase 5 — Stdlib-only tools

**Task 5.1 — `fid_div_conv`** and **Task 5.2 — `van_div_conv`.** Apply the recipe with `dependencies = []`. These currently build a venv that installs nothing — all of it goes. Keep the legacy-config import and runtime-home logic. `fid_div_conv` has both `tests/test_bootstrap.py` (delete) and `tests/test_fid_div_conv.py` (must pass in full). `van_div_conv` has only app tests.

---

## Phase 6 — Fleet drift guard

**Task 6.1 — Write `tools/check_uv_headers.py`** (new top-level `tools/` directory), a stdlib-only script that:
- Holds the registry of all migrated launcher paths (the 16 files above).
- For each: asserts the first line is exactly the canonical shebang; parses the PEP 723 block and validates the TOML body with `tomllib` (must contain `requires-python` and a `dependencies` list); asserts none of the forbidden patterns appear anywhere in the file (`BOOTSTRAP_VERSION`, `bootstrap_state`, `os.execv`, `venv.EnvBuilder`, `venv.create`, `ensure_private_venv`).
- Exits non-zero with a per-file report on any violation; prints a one-line OK summary otherwise.
- Runs under `uv run --script` itself (empty dependencies) — eat the dog food.

This replaces the 12 deleted `test_bootstrap.py` copies as the fleet's regression guard: if anyone pastes old bootstrap code back into a launcher, this fails.

**Task 6.2 — Run it** and fix anything it flags across the fleet.

---

## Phase 7 — Documentation

**Task 7.1 — Repo root `README.md`.**
- Rewrite the "Single-File Python Launcher" implementation rules: the bootstrap-venv/`bootstrap_state.json`/`os.execv` rules are replaced by "uv shebang + PEP 723 header; runtime home under `~/.toolname/` for mutable state only."
- Rewrite the "Intentional Code Duplication" section: bootstrap duplication no longer exists and must not be reintroduced; the remaining intentional duplication (`find_free_port`, HTML calculator CSS) stays documented.
- Update the zipapp form's dependency rules where they reference the private-venv bootstrap.
- Add uv as a stated machine prerequisite for the Python launcher form.

**Task 7.2 — `agents.md` (repo root; `CLAUDE.md` may be a symlink to it — check before editing so you don't edit the same file twice or break the link).** Replace the "Self-Bootstrapping (Python/CLI projects)" preferred-pattern section with the uv pattern: canonical header, runtime-home rules (unchanged), the drift-guard script, and an explicit instruction that new Python tools must NOT hand-roll venv bootstrap. Update the Validation Matrix if any listed command changes, and add `tools/check_uv_headers.py` to it as a fleet-level check.

**Task 7.3 — Per-project docs sweep.** Per-project READMEs were updated in each task; now grep the repo for stragglers: `rg -il "bootstrap_state|BOOTSTRAP_VERSION|self-bootstrap|private venv" --glob '!**/node_modules/**' --glob '!**/.venv/**' --glob '!**/venv/**'` and fix remaining descriptions in docs (e.g. `routerview/docs/`, `cognitive_switchyard/docs/`, project `docs/implementation_plan.md` files may be left as historical records — update only living docs, not archived plans; when in doubt, add a one-line "superseded by uv migration, see docs/uv_bootstrap_migration_implementation_plan.md" note instead of rewriting history).

---

## Phase 8 — Refresh deployed copies (BEFORE machine cleanup)

All `~/Library/Scripts` entries are **plain copies**, not symlinks. If they are not refreshed, the old copies will keep running old bootstrap code and recreate the venvs Phase 9 deletes. Order matters: Phase 8 strictly before Phase 9.

**Task 8.1 — Refresh.** For each migrated tool that exists in `~/Library/Scripts` (as of 2026-07-10: `editdb`, `expense_dock`, `fid_div_conv`, `harscope`, `jtree`, `launchmaster`, `router_log_analyze.py`, `routerview`, `storage_monitor`, `van_div_conv`), copy the migrated launcher over the deployed copy, preserving the executable bit. Leave `model-sentinel` and all non-migrated entries (`dloc`, `worktree`, shell scripts, etc.) alone.

**Task 8.2 — Verify each deployed copy** by running `~/Library/Scripts/<name> --help` directly (this exercises the shebang path, not just `uv run`). Every one must exit 0. Expected: because uv keys script environments by path, each deployed copy builds its own cached env on first run, separate from the repo copy's — an `Installed N packages` line on that first run is normal, and it completes in milliseconds from uv's shared wheel cache.

---

## Phase 9 — Machine cleanup

Only after Phases 1–8 are complete and verified.

**Task 9.1 — Delete obsolete venvs.** Using the Phase 0.3 snapshot, delete:
- All sibling venv dirs: `~/.editdb_venv`, `~/.harscope_venv`, `~/.jtree_venv`, `~/.mls_tracker_venv`, `~/.docpipe_venv`, `~/.routerview_venv`, `~/.expense_dock_venv`, `~/.git_dashboard_venv`, `~/.launchmaster_venv`, `~/.cognitive_switchyard_venv`, `~/.switchyard_venv`.
- All in-home venv dirs: `~/.editdb/venv`, `~/.fid_div_conv/venv`, `~/.harscope/venv`, `~/.jtree/venv`, `~/.mls_tracker/venv`, `~/.storage_monitor/venv`, `~/.tax2/venv`, `~/.van_div_conv/venv`, `~/.router-log-analyzer/venv`, `~/.benchmark_llm/venv`, and any `bootstrap_venv` under `~/.cognitive_switchyard/` (find it: `find ~/.cognitive_switchyard -maxdepth 3 -type d -name 'bootstrap_venv'`).
- Re-run `ls -d ~/.*/venv ~/.*_venv` first to catch any dirs created since the snapshot; anything matching those patterns for a migrated tool goes.

**Delete only `venv`/`*_venv` directories. Do not delete runtime homes or anything else inside them** — they hold live config, SQLite databases, logs, and state.

**Task 9.2 — Delete bootstrap markers:**

```sh
find ~ -maxdepth 2 -name 'bootstrap_state.json' -path "$HOME/.*"
```

Review the list (every hit should be directly inside a `~/.toolname/` runtime home), then delete them.

**Task 9.3 — Confirm nothing regenerates.** Run each deployed tool from `~/Library/Scripts` once more (`--help` is enough), plus one repo-run of a non-deployed tool (e.g. `mls-tracker`), then re-run the Task 9.1/9.2 listing commands and confirm zero venvs or markers reappeared.

**Task 9.4 — Note the dev-venv exclusions.** Repo-local dev venvs are NOT part of this cleanup and must survive: `tax2/.venv`, `data_format_converter/venv`, and any other in-repo venv used for tests.

---

## Phase 10 — Exit verification (mandatory before declaring done)

1. **Full test suites of every touched project**, run again from scratch. Report every failure by name with output; compare against the Phase 0.2 baseline. Per repo rules, no failure may be dismissed as unrelated — fix or stop and present.
2. `tools/check_uv_headers.py` passes across the fleet.
3. Repo-wide grep is clean: `rg -n "BOOTSTRAP_VERSION|bootstrap_state|os\.execv" --glob '!**/node_modules/**' --glob '!**/.venv/**' --glob '!**/venv/**' --glob '!docs/**' --glob '!**/docs/**' --glob '!**/plans/**' --glob '!**/audits/**'` — hits only in historical docs are acceptable; hits in code are not. (`os.execv` may legitimately remain in non-bootstrap code — e.g. cognitive_switchyard runner logic or worktree-helper; verify each remaining hit is app logic, not bootstrap.)
4. Every smoke-run performed in Phases 1–5 was actually performed (web tools served a page/health endpoint; CLI tools ran a real command, e.g. `fid_div_conv`/`van_div_conv` `--help` plus a dry-run-style invocation if available).
5. `git status` / `git ls-files` confirm all new files (`tools/check_uv_headers.py`, doc updates) are tracked and no launcher was accidentally excluded by `.gitignore`.
6. Deployed copies in `~/Library/Scripts` verified (Phase 8.2 / 9.3).
7. Machine state clean (Phase 9 listings empty for migrated tools).

## Commit discipline

One commit per task (per tool), imperative subject. Suggested final commits: the drift guard, the docs sweep. Phases 8–9 touch only the machine, not the repo — no commits, but report their results explicitly.

## Known post-migration follow-ups (report, don't do)

- The main agent's session memory references `~/.routerview_venv`; it will update its own memory after this migration lands.
- Symlinking `~/Library/Scripts` entries instead of copying is a possible future improvement.
- `find_free_port` duplication across web tools remains intentional and out of scope.
