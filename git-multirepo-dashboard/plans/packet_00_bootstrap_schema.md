# Packet 00: Bootstrap & Schema

## Why This Packet Exists

Everything depends on the application being able to start, create its venv, initialize its database, and parse CLI arguments. This is the foundation that every subsequent packet builds on.

## Scope

- `bootstrap()` function: venv creation at `~/.git_dashboard_venv`, dependency installation, re-exec
- Preflight checks: Python version (hard), git (hard), optional tool detection (npm, pip-audit, go, cargo, cargo-audit, bundle, bundler-audit, composer, govulncheck, cargo-outdated)
- `TOOLS` runtime dict storing tool availability
- Preflight summary display with confirmation prompt (or `--yes` to skip)
- Hard-fail if no ecosystem tools found at all
- CLI argument parsing: `--port`, `--no-browser`, `--scan`, `--yes`/`-y`
- `DATA_DIR` and `DB_PATH` creation
- SQLite schema initialization (all 6 tables from spec section 2)
- FastAPI app creation with `GET /` serving a minimal placeholder HTML
- Uvicorn startup with `find_free_port()` pattern
- Browser auto-open via `webbrowser.open()` (skippable with `--no-browser`)
- `GET /api/status` endpoint returning tool availability and app version
- Cross-platform: Windows venv path (`Scripts/python.exe`), Windows re-exec (`subprocess.run` + `sys.exit` instead of `os.execv`)
- `README.md` for the project

## Non-Goals

- No git operations (packet 01)
- No repo registration (packet 02)
- No real UI beyond a placeholder page confirming the server is running
- No dependency scanning logic
- No SSE or scan orchestration

## Relevant Design Doc Sections

- Section 1: Project Structure (all of it)
- Section 2: SQLite Schema (all of it)
- Section 5.1: Technology (CDN URLs only — just include them in the placeholder HTML head)
- Section 11: Cross-Platform Requirements (all of it)

## Allowed Files

- `git-multirepo-dashboard/git_dashboard.py` (create)
- `git-multirepo-dashboard/README.md` (create)

## Tests to Write First

Since this is a single-file app, tests are inline verification scripts or manual checks. The implementer should create a `tests/` directory with a minimal test harness.

1. **Test: Preflight detects Python version**
   - Mock `sys.version_info` to `(3, 8)`. Expect `SystemExit` with code 1.
   - Verify error message mentions "Python 3.9+".

2. **Test: Preflight detects missing git**
   - Mock `shutil.which("git")` to return `None`. Expect `SystemExit` with code 1.

3. **Test: TOOLS dict populated correctly**
   - Mock `shutil.which` for various tools. Verify `TOOLS` dict has correct `None` vs path entries.

4. **Test: Hard-fail when no ecosystem tools found**
   - Mock all optional tools as missing. Expect `SystemExit`.

5. **Test: Schema creates all 6 tables**
   - Create an in-memory SQLite DB. Run schema init. Query `sqlite_master` for table names.
   - Expected tables: `repositories`, `daily_stats`, `branches`, `dependencies`, `working_state`, `scan_log`.

6. **Test: CLI args parse correctly**
   - `--port 9000` → args.port == 9000
   - `--no-browser` → args.no_browser == True
   - `--yes` → args.yes == True
   - `--scan /some/path` → args.scan == "/some/path"
   - Default port is 8300.

7. **Test: GET /api/status returns tool info**
   - Start the FastAPI app (TestClient). Hit `/api/status`. Verify response has `tools` dict and `version` field.

8. **Test: GET / returns HTML**
   - Start the FastAPI app (TestClient). Hit `/`. Verify response is HTML (status 200, content-type text/html).

## Implementation Notes

### Bootstrap Function

Follow the editdb pattern from this repo (see `editdb/editdb`). Key differences from editdb:

- Venv directory: `Path.home() / ".git_dashboard_venv"`
- Dependencies: `["fastapi", "uvicorn[standard]", "aiosqlite", "packaging"]`
- Must handle Windows: venv python at `Scripts/python.exe`, re-exec via `subprocess.run` + `sys.exit` (not `os.execv`)

```python
VENV_DIR = Path.home() / ".git_dashboard_venv"
DATA_DIR = Path.home() / ".git_dashboard"
DB_PATH  = DATA_DIR / "dashboard.db"
DEFAULT_PORT = 8300
DEPENDENCIES = ["fastapi", "uvicorn[standard]", "aiosqlite", "packaging"]
```

### Preflight Checks

Run BEFORE venv creation. The required checks (Python version, git) must fail fast.

For optional tools, build a `TOOLS` dict:
```python
TOOLS = {}
for name, cmd in [("npm", "npm"), ("go", "go"), ("cargo", "cargo"), ("bundle", "bundle"), ("composer", "composer")]:
    TOOLS[name] = shutil.which(cmd)
```

Conditional tools (only check if parent is found):
- `pip_audit`: check after venv is active (it may be installed there)
- `govulncheck`: only if `TOOLS["go"]` is set
- `cargo_audit`: only if `TOOLS["cargo"]` is set
- `cargo_outdated`: only if `TOOLS["cargo"]` is set
- `bundler_audit`: only if `TOOLS["bundle"]` is set

### Preflight Display

Print the summary table to stderr. Format per spec section 1 "Startup Behavior":
```
Git Fleet - Preflight Check
============================

  git .............. OK (2.44.0)
  npm .............. NOT FOUND
    -> Node.js dependency checks will be disabled.
  ...
```

If any optional tools missing AND at least one ecosystem tool present: prompt `Continue anyway? [Y/n]`. Default Yes. `--yes` skips prompt.

If ALL ecosystem tools missing (none of npm, go, cargo, bundle, composer found AND pip-audit not found): hard fail.

### Schema

Use `aiosqlite` for async DB access. The schema init can be synchronous at startup (run via `asyncio.run()` or similar). Use the exact SQL from spec section 2, with `CREATE TABLE IF NOT EXISTS` for idempotency.

Enable WAL mode: `PRAGMA journal_mode=WAL;`

### CLI Args

Use `argparse`. The `--scan` flag registers and scans a directory on startup — but the actual scan logic is packet 02/03. In this packet, just parse and store the arg. The scan behavior will be wired later.

### FastAPI App

```python
app = FastAPI(title="Git Fleet")

@app.get("/", response_class=HTMLResponse)
async def get_ui():
    return HTML_TEMPLATE

@app.get("/api/status")
async def get_status():
    return {"tools": TOOLS, "version": "0.1.0"}
```

The `HTML_TEMPLATE` in this packet is just a minimal page confirming the server is running. The full UI comes in packets 04–05.

### Port Selection

Use the `find_free_port()` pattern from CLAUDE.md. Start from `args.port` (default 8300), try up to 20 ports.

### Signal Handling

Register `SIGINT` handler for graceful shutdown. On Windows, skip `SIGTERM` (unreliable).

## Acceptance Criteria

1. `python git_dashboard.py --help` prints usage and exits cleanly.
2. `python git_dashboard.py --yes --no-browser` starts the server on port 8300 (or next free port) and prints the URL to stdout.
3. `GET /` returns an HTML page with status 200.
4. `GET /api/status` returns JSON with `tools` dict and `version` field.
5. `~/.git_dashboard` directory is created with `dashboard.db` inside it.
6. `dashboard.db` contains all 6 tables with correct schemas.
7. WAL mode is enabled on the database.
8. If `git` is not in PATH, the script exits with code 1 and a clear error message.
9. If Python < 3.9, the script exits with code 1 and a clear error message.
10. All tests pass.

## Validation Focus Areas

- Cross-platform path handling: verify `Path.home()` usage, venv python path selection based on `sys.platform`.
- Schema correctness: every column, every constraint, every foreign key from spec section 2.
- Preflight prompt logic: verify the Y/n prompt behavior, `--yes` bypass, and hard-fail when no ecosystem tools found.
- Port scanning: verify `find_free_port` is used and fallback works.
