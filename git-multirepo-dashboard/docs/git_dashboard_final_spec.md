# Git Multi-Repo Dashboard: Final Implementation Spec

> For implementation by a coding agent. Every decision is made; no ambiguity remains.

---

## 1. Project Structure

Single Python file with embedded HTML/JS SPA. No build step. Must run on **Windows, macOS, and Linux**.

```
git-multirepo-dashboard/
  git_dashboard.py       # Entry point (run as: python git_dashboard.py)
  README.md
```

Note: The file is named `git_dashboard.py` (with `.py` extension) for Windows compatibility. On Unix systems it may optionally also have a shebang `#!/usr/bin/env python3` but **must not** rely on it — always document invocation as `python git_dashboard.py` or `python3 git_dashboard.py`.

### Bootstrap Constants

```python
VENV_DIR = Path.home() / ".git_dashboard_venv"
DATA_DIR = Path.home() / ".git_dashboard"
DB_PATH  = DATA_DIR / "dashboard.db"
DEFAULT_PORT = 8300
DEPENDENCIES = ["fastapi", "uvicorn[standard]", "aiosqlite", "packaging"]
# pip-audit is NOT a hard dependency; detect at runtime
```

### Startup Preflight Checks

Run these checks **before** venv creation or any other work. Exit immediately with a clear, actionable error message if a required check fails.

| Check | Required? | How | On failure |
|---|---|---|---|
| **Python version** | Required | `sys.version_info >= (3, 9)` | `"Error: Python 3.9+ required. Found {sys.version}. Install from python.org."` |
| **git** | Required | `shutil.which("git")` then `git --version` | `"Error: git not found in PATH. Install from https://git-scm.com/"` |
| **npm** | Optional | `shutil.which("npm")` | Log: `"Warning: npm not found. Node.js dependency checks will be disabled."` |
| **pip-audit** | Optional | `shutil.which("pip-audit")` (checked after venv is active) | Log: `"Warning: pip-audit not found. Python vulnerability scanning will be disabled. Install with: pip install pip-audit"` |
| **go** | Optional | `shutil.which("go")` | Log: `"Warning: go not found. Go dependency checks will be disabled."` |
| **cargo** | Optional | `shutil.which("cargo")` | Log: `"Warning: cargo not found. Rust dependency checks will be disabled."` |
| **cargo-audit** | Optional | `shutil.which("cargo-audit")` (only if cargo found) | Log: `"Warning: cargo-audit not found. Rust vulnerability scanning will be disabled. Install with: cargo install cargo-audit"` |
| **bundle** | Optional | `shutil.which("bundle")` | Log: `"Warning: bundler not found. Ruby dependency checks will be disabled."` |
| **bundler-audit** | Optional | `shutil.which("bundler-audit")` (only if bundle found) | Log: `"Warning: bundler-audit not found. Ruby vulnerability scanning will be disabled. Install with: gem install bundler-audit"` |
| **composer** | Optional | `shutil.which("composer")` | Log: `"Warning: composer not found. PHP dependency checks will be disabled."` |
| **govulncheck** | Optional | `shutil.which("govulncheck")` (only if go found) | Log: `"Warning: govulncheck not found. Go vulnerability scanning will be disabled. Install with: go install golang.org/x/vuln/cmd/govulncheck@latest"` |
| **cargo-outdated** | Optional | `shutil.which("cargo-outdated")` (only if cargo found) | Log: `"Warning: cargo-outdated not found. Rust outdated checks will be disabled. Install with: cargo install cargo-outdated"` |

Store the results of optional tool checks in a runtime dict (e.g., `TOOLS = {"npm": "/usr/bin/npm", "pip_audit": None, "go": "/usr/local/bin/go", ...}`) so scan code can quickly check availability without re-running `shutil.which()`.

#### Startup Behavior

**Hard failures** (required tools missing): Print the error message to stderr and `sys.exit(1)` immediately. No prompt, no workaround.

**Soft failures** (optional tools missing): If **any** optional tools are missing, do **not** silently continue. Instead, print a summary to the terminal and **prompt for confirmation** before launching the server:

```
Git Fleet - Preflight Check
============================

  git .............. OK (2.44.0)

  npm .............. NOT FOUND
    -> Node.js dependency checks will be disabled.
    -> Affects: outdated + vulnerability scanning for Node repos.

  pip-audit ........ NOT FOUND
    -> Python vulnerability scanning will be disabled.
    -> Outdated checks still work via PyPI API.
    -> Install with: pip install pip-audit

  go ............... OK (1.22.1)
  govulncheck ...... NOT FOUND
    -> Go vulnerability scanning will be disabled.
    -> Outdated checks still work via 'go list'.
    -> Install with: go install golang.org/x/vuln/cmd/govulncheck@latest

  cargo ............ NOT FOUND
    -> All Rust dependency checks will be disabled.

  bundle ........... NOT FOUND
    -> All Ruby dependency checks will be disabled.

  composer ......... OK (2.7.1)

Some dependency tools are missing. Results may be incomplete.
Continue anyway? [Y/n]
```

- If **all** ecosystem tools are missing (none of `npm`, `go`, `cargo`, `bundle`, `composer` found, AND `pip-audit` not found): **hard fail**. The dependency scanning features — a core part of the dashboard — would be completely non-functional. Print the summary, then: `"Error: No dependency tools found. The dashboard requires at least one ecosystem tool to be useful. Install one or more of the tools listed above and try again."` Exit with code 1. The `--yes` flag does **not** override this.
- If **some** ecosystem tools are missing (at least one primary tool is available): prompt for confirmation. Default is Yes (pressing Enter continues).
- If `--yes` or `-y` CLI flag is passed, skip the prompt and continue automatically. This is for scripted/automated launches.
- If the user types `n` or `N`, exit with code 0 and a message: `"Exiting. Install the missing tools and try again."`
- If **all** optional tools are found, skip the prompt entirely and launch normally (just print the OK summary briefly).

Also expose the tool status via `GET /api/status` so the frontend can show a **persistent but dismissible banner** at the top of the content area: "Some dependency tools are not installed. Dependency results may be incomplete. [Show details]". The details expandable shows the same list as the terminal output. This ensures users who didn't launch from a terminal (e.g., via `--scan` from a shortcut) are also informed.

### Bootstrap Sequence

(Same pattern as routerview/editdb):
1. Run preflight checks (above). Fail fast on required checks.
2. Check for venv at `VENV_DIR`. If missing, create it using `venv` module (`python -m venv`), install deps, re-exec. On Windows, the venv Python executable is at `VENV_DIR / "Scripts" / "python.exe"`; on Unix it is `VENV_DIR / "bin" / "python"`. Use `sys.platform` to select the correct path.
3. If venv exists but deps missing, install and re-exec.
4. Re-run optional preflight checks for tools that depend on the venv (e.g., `pip-audit`).
5. Create `DATA_DIR` if missing.
6. Initialize SQLite schema if tables don't exist.
7. Start uvicorn on `DEFAULT_PORT` (or `--port` arg).
8. Open browser to `http://localhost:{port}` using `webbrowser.open()` (cross-platform).

CLI args:
- `--port N` (default 8300)
- `--no-browser` (skip auto-open)
- `--scan /path/to/dir` (register + scan a directory on startup, then launch)
- `--yes` / `-y` (skip the missing-tools confirmation prompt; for scripted/automated launches)

---

## 2. SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS repositories (
  id TEXT PRIMARY KEY,             -- sha256(absolute_path)[:16]
  name TEXT NOT NULL,              -- directory basename
  path TEXT NOT NULL UNIQUE,
  default_branch TEXT DEFAULT 'main',
  runtime TEXT,                    -- python | node | shell | html | docker | mixed | unknown
  added_at TEXT NOT NULL,          -- ISO 8601
  last_quick_scan_at TEXT,
  last_full_scan_at TEXT
);

CREATE TABLE IF NOT EXISTS daily_stats (
  repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  date TEXT NOT NULL,              -- YYYY-MM-DD
  commits INTEGER DEFAULT 0,
  insertions INTEGER DEFAULT 0,
  deletions INTEGER DEFAULT 0,
  files_changed INTEGER DEFAULT 0,
  PRIMARY KEY (repo_id, date)
);

CREATE TABLE IF NOT EXISTS branches (
  repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  last_commit_date TEXT,
  is_default BOOLEAN DEFAULT FALSE,
  is_stale BOOLEAN DEFAULT FALSE,  -- last_commit_date older than 30 days from now
  PRIMARY KEY (repo_id, name)
);

CREATE TABLE IF NOT EXISTS dependencies (
  repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  manager TEXT NOT NULL,           -- pip | npm | gomod | cargo | bundler | composer
  name TEXT NOT NULL,
  current_version TEXT,
  wanted_version TEXT,             -- highest satisfying declared range (npm concept; same as current for pip)
  latest_version TEXT,
  severity TEXT DEFAULT 'ok',      -- ok | outdated | major | vulnerable
  advisory_id TEXT,                -- CVE or advisory ID if vulnerable
  checked_at TEXT,
  PRIMARY KEY (repo_id, manager, name)
);

CREATE TABLE IF NOT EXISTS working_state (
  repo_id TEXT PRIMARY KEY REFERENCES repositories(id) ON DELETE CASCADE,
  has_uncommitted BOOLEAN DEFAULT FALSE,
  modified_count INTEGER DEFAULT 0,
  untracked_count INTEGER DEFAULT 0,
  staged_count INTEGER DEFAULT 0,
  current_branch TEXT,
  last_commit_hash TEXT,
  last_commit_message TEXT,
  last_commit_date TEXT,           -- ISO 8601
  checked_at TEXT
);

CREATE TABLE IF NOT EXISTS scan_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_type TEXT NOT NULL,         -- quick | full | deps
  started_at TEXT NOT NULL,
  finished_at TEXT,
  repos_scanned INTEGER DEFAULT 0,
  status TEXT DEFAULT 'running'    -- running | completed | failed
);
```

---

## 3. Git Data Collection

All git operations use `asyncio.create_subprocess_exec` with `git -C {repo_path}`.

**Cross-platform subprocess notes:**
- Use `asyncio.create_subprocess_exec("git", "-C", str(repo_path), ...)` — never use shell=True, never join paths into a shell string. `str(repo_path)` ensures `Path` objects are stringified with the correct OS separator.
- On Windows, `asyncio.create_subprocess_exec` requires a `ProactorEventLoop` (the default on Python 3.8+ Windows). No special setup needed.
- Locate the `git` executable using `shutil.which("git")` at startup. If not found, fail fast with a clear error message. On Windows, `git.exe` is typically in `C:\Program Files\Git\cmd\` but `shutil.which` handles PATH lookup.
- Locate `npm` and `pip-audit` the same way using `shutil.which()`.
- Decode subprocess output with `errors='replace'` for non-UTF8 commit messages.

### 3.1 Quick Scan (per repo, <100ms each)

Run on every page load. Total for 40 repos: <2 seconds.

```
git -C {path} rev-parse --is-inside-work-tree
  -> confirms valid repo

git -C {path} status --porcelain=v1
  -> parse: lines starting with 'M'/'A'/'D'/' M' etc for modified_count
  -> '??' lines for untracked_count
  -> lines with index changes for staged_count
  -> has_uncommitted = any non-empty output

git -C {path} log -1 --format='%H%x00%aI%x00%s'
  -> split on \x00: hash, ISO date, subject
  -> populates last_commit_hash, last_commit_date, last_commit_message

git -C {path} rev-parse --abbrev-ref HEAD
  -> current_branch
```

### 3.2 Full History Scan (per repo)

Runs on demand. For incremental, add `--after={last_full_scan_at}`.

```
git -C {path} log --all --format='%H%x00%aI%x00%an%x00%s' --shortstat --after={since}
```

Parse this output in chunks. Each commit produces:
- A format line: `hash\x00date\x00author\x00subject`
- Optionally followed by a blank line + shortstat line: ` N files changed, N insertions(+), N deletions(-)`

Aggregate into `daily_stats` by date (YYYY-MM-DD). For each date, sum commits, insertions, deletions, files_changed.

### 3.3 Branch Scan (per repo)

```
git -C {path} branch --format='%(refname:short)%x00%(committerdate:iso-strict)'
```

Parse each line. Mark `is_stale = True` if `committerdate` is more than 30 days ago. Identify default branch via:

```
git -C {path} symbolic-ref --short HEAD
```

### 3.4 Dependency Detection

**File detection priority** (check in order, first match determines `runtime`):

| Priority | File(s) | Runtime | Dependency parsing |
|---|---|---|---|
| 1 | `pyproject.toml` | `python` | Parse `[project].dependencies` or `[tool.poetry.dependencies]` |
| 2 | `requirements.txt` | `python` | Parse `pkg==version` lines (ignore comments, `-r` includes, `-e` editable) |
| 3 | `setup.py` or `setup.cfg` | `python` | Detect runtime only; dep parsing from requirements.txt or pyproject.toml |
| 4 | `package.json` | `node` | Parse `dependencies` and `devDependencies` |
| 5 | `go.mod` | `go` | Parse `require` block: each line is `module/path vX.Y.Z` |
| 6 | `Cargo.toml` | `rust` | Parse `[dependencies]` section: `name = "version"` or `name = { version = "..." }` |
| 7 | `Gemfile` | `ruby` | Parse `gem 'name', '~> version'` lines (basic regex; ignore complex constraints) |
| 8 | `composer.json` | `php` | Parse `require` and `require-dev` objects |
| 9 | `Dockerfile` or `docker-compose.yml` | `docker` | No dep parsing |
| 10 | Majority of files are `.sh`/`.zsh`/`.bat`/`.ps1` | `shell` | No dep parsing |
| 11 | `index.html` exists at root | `html` | No dep parsing |
| 12 | Otherwise | `unknown` | No dep parsing |

If multiple ecosystem files coexist (e.g., both `pyproject.toml` and `package.json`) -> `runtime = "mixed"`. In the mixed case, **all** detected ecosystems get dependency parsing and health checks.

**Cross-platform note for file detection:** Use `pathlib.Path` for all file existence checks. Path comparisons must be case-insensitive on Windows (`Dockerfile` vs `dockerfile`). Use `path.name.lower()` when matching filenames.

### 3.5 Dependency Health Check

**This is the key distinction.** Two separate questions per ecosystem: "Is anything **outdated**?" and "Is anything **vulnerable**?"

#### Per-Ecosystem Tooling

| Ecosystem | Outdated check | Vulnerability check |
|---|---|---|
| **Python** | PyPI JSON API (see below) | `pip-audit --requirement requirements.txt --format json` |
| **Node** | `npm outdated --json` (cwd=repo) | `npm audit --json` (cwd=repo) |
| **Go** | `go list -m -u -json all` (cwd=repo) | `govulncheck -json ./...` (cwd=repo) |
| **Rust** | `cargo outdated --format json` (cwd=repo) | `cargo audit --json` (cwd=repo) |
| **Ruby** | `bundle outdated --parseable` (cwd=repo) | `bundle audit check --format json` (cwd=repo) |
| **PHP** | `composer outdated --format=json` (cwd=repo) | `composer audit --format=json` (cwd=repo) |

**Required tools per ecosystem** (all optional — skip gracefully if not found):

| Ecosystem | Required tool | Extra tools (optional) |
|---|---|---|
| Python | none (PyPI API for outdated) | `pip-audit` for vuln scan |
| Node | `npm` | none |
| Go | `go` | `govulncheck` for vuln scan (`go install golang.org/x/vuln/cmd/govulncheck@latest`) |
| Rust | `cargo` | `cargo-outdated` (`cargo install cargo-outdated`), `cargo-audit` (`cargo install cargo-audit`) |
| Ruby | `bundle` (bundler) | `bundler-audit` (`gem install bundler-audit`) |
| PHP | `composer` | none (audit is built-in since Composer 2.4) |

**Severity classification for each dependency (all ecosystems):**

```
if has_known_vulnerability:
    severity = "vulnerable"      # red
elif major_version_behind:
    severity = "major"           # orange  (e.g., current=2.x, latest=3.x)
elif any_version_behind:
    severity = "outdated"        # yellow  (e.g., current=2.1, latest=2.3)
else:
    severity = "ok"              # green
```

#### Python Details

**pip-audit** output shape (JSON):
```json
{
  "dependencies": [
    { "name": "pkg", "version": "1.0", "vulns": [{"id": "CVE-...", "fix_versions": ["1.1"]}] }
  ]
}
```

**For Python outdated check**, since we can't assume the project's venv is active, use a lightweight approach:
1. Parse `requirements.txt` or `pyproject.toml` for pinned versions.
2. For each package, check PyPI JSON API: `https://pypi.org/pypi/{package}/json` -> `.info.version` gives latest.
3. Compare versions using `packaging.version.parse()` (in DEPENDENCIES).

This avoids needing the project's venv active. It won't catch transitive deps but covers declared ones.

#### Node Details

**npm audit** output shape (JSON):
```json
{
  "vulnerabilities": {
    "pkg": { "severity": "high", "via": [...], "fixAvailable": true }
  }
}
```

**npm outdated** output shape (JSON):
```json
{
  "pkg": { "current": "1.0.0", "wanted": "1.0.5", "latest": "2.0.0", "dependent": "myapp" }
}
```

#### Go Details

**`go list -m -u -json all`** output (one JSON object per line, NDJSON):
```json
{
  "Path": "github.com/gin-gonic/gin",
  "Version": "v1.9.1",
  "Update": { "Path": "github.com/gin-gonic/gin", "Version": "v1.10.0" }
}
```
If `Update` field is present, the module is outdated. Compare major versions to distinguish `major` vs `outdated`.

**`govulncheck -json ./...`** output:
```json
{
  "Vulns": [
    { "OSV": { "id": "GO-2024-...", "aliases": ["CVE-..."] }, "Modules": [...] }
  ]
}
```
If `govulncheck` is not installed, skip vuln scanning for Go. The outdated check (`go list`) only requires `go` itself.

#### Rust Details

**`cargo outdated --format json`** output:
```json
{
  "dependencies": [
    { "name": "serde", "project": "1.0.190", "latest": "1.0.210", "kind": "Normal" }
  ]
}
```

**`cargo audit --json`** output:
```json
{
  "vulnerabilities": {
    "list": [
      { "advisory": { "id": "RUSTSEC-2024-...", "title": "..." }, "package": { "name": "...", "version": "..." } }
    ]
  }
}
```
Both `cargo-outdated` and `cargo-audit` are separate installs. If neither is available, parse `Cargo.toml` for declared deps but mark all as "ok" (no version comparison possible without the tools).

#### Ruby / PHP Details

These ecosystems follow the same pattern. Parse their output formats:

- **Ruby `bundle outdated --parseable`**: One line per gem: `gem-name (newest X.Y.Z, installed A.B.C, requested ~> A.B)`. Parse with regex.
- **Ruby `bundler-audit`**: If installed, run `bundle audit check --format json`. Falls back to no vuln data.
- **PHP `composer outdated --format=json`**: Returns `{"installed": [{"name": "...", "version": "...", "latest": "...", "latest-status": "up-to-date|semver-safe-update|update-possible"}]}`.
- **PHP `composer audit --format=json`**: Built-in since Composer 2.4. Returns advisory data.

#### Cross-Platform Notes for Dependency Tools

- `pip-audit`: Invoked via the dashboard's own venv pip-audit if installed. Use `shutil.which("pip-audit")` to detect.
- `npm` / `npx`: On Windows, `npm.cmd` is the actual executable. Use `shutil.which("npm")` which returns the correct platform-specific path.
- `go`: Cross-platform. `shutil.which("go")` works on all platforms.
- `cargo`: Cross-platform. `shutil.which("cargo")` works on all platforms.
- `bundle` / `composer`: Same `shutil.which()` pattern.
- When invoking any tool that needs to run in the repo directory, set `cwd=repo_path` in the subprocess call rather than trying to use a `-C` flag (most tools don't support it).

#### Fallback Behavior (All Ecosystems)

The principle is the same for every ecosystem: **degrade gracefully, never block**.

- If the primary tool for an ecosystem is missing (e.g., `npm`, `go`, `cargo`, `bundle`, `composer`): skip all checks for that ecosystem. Log a warning at startup. Show "tool not available" in the UI for affected repos.
- If only the vulnerability tool is missing (e.g., `pip-audit`, `govulncheck`, `cargo-audit`, `bundler-audit`): skip vuln checks only. Outdated checks still run if possible.
- If `npm audit` fails (no lockfile): skip vulnerability scan, still try `npm outdated`.
- Network errors (PyPI API, any registry calls): cache last successful result, show "last checked N minutes ago".
- If a tool produces unexpected output (version change, different JSON schema): catch the parse error, log it, skip that check, show "check failed" in the UI. Do not crash.

---

## 4. API Endpoints and Response Shapes

### GET /api/fleet

Quick scan all repos, return fleet overview.

```json
{
  "repos": [
    {
      "id": "a1b2c3d4e5f6g7h8",
      "name": "routerview",
      "path": "/Users/example/utilities/routerview",
      "runtime": "python",
      "default_branch": "main",
      "current_branch": "main",
      "last_commit_date": "2026-03-09T14:23:00-06:00",
      "last_commit_message": "fix: handle empty response from API",
      "has_uncommitted": true,
      "modified_count": 2,
      "untracked_count": 1,
      "staged_count": 0,
      "branch_count": 3,
      "stale_branch_count": 1,
      "dep_summary": { "total": 12, "outdated": 3, "vulnerable": 1 },
      "sparkline": [0,0,2,0,1,3,0,0,0,5,1,0,0]
    }
  ],
  "kpis": {
    "total_repos": 42,
    "repos_with_changes": 5,
    "commits_this_week": 23,
    "commits_this_month": 87,
    "net_lines_this_week": 1450,
    "stale_branches": 12,
    "vulnerable_deps": 3,
    "outdated_deps": 18
  },
  "scanned_at": "2026-03-10T08:00:00-06:00"
}
```

`sparkline` is an array of 13 integers: commit counts per week for the last 13 weeks (one quarter). Index 0 = oldest week. This is enough for a tiny sparkline on each card.

**Path representation:** The `path` field always uses the OS-native separator as returned by Python's `Path.resolve()`. The frontend displays it as-is (backslashes on Windows, forward slashes on Unix).

### POST /api/fleet/scan

Trigger a full scan. Returns immediately with a scan ID. Progress via SSE.

Request body:
```json
{ "type": "full" }
```
or
```json
{ "type": "deps" }
```

Response:
```json
{ "scan_id": 42 }
```

### GET /api/fleet/scan/{scan_id}/progress

SSE stream. Each event:

```
data: {"repo": "routerview", "step": "history", "progress": 12, "total": 42, "status": "scanning"}
data: {"repo": "routerview", "step": "history", "progress": 13, "total": 42, "status": "scanning"}
...
data: {"progress": 42, "total": 42, "status": "completed"}
```

`step` values: `history`, `branches`, `deps`

### GET /api/repos/{id}

Full detail for one repo. Combines working_state + latest daily_stats + branches + deps.

```json
{
  "id": "a1b2c3d4e5f6g7h8",
  "name": "routerview",
  "path": "/Users/example/utilities/routerview",
  "runtime": "python",
  "default_branch": "main",
  "working_state": { /* same fields as in fleet */ },
  "last_full_scan_at": "2026-03-10T07:55:00-06:00"
}
```

### GET /api/repos/{id}/history?days=90

```json
{
  "repo_id": "a1b2c3d4e5f6g7h8",
  "days": 90,
  "data": [
    { "date": "2026-03-09", "commits": 3, "insertions": 120, "deletions": 45, "files_changed": 8 },
    { "date": "2026-03-08", "commits": 1, "insertions": 10, "deletions": 2, "files_changed": 1 }
  ]
}
```

Only dates with activity are included. Frontend fills gaps with zeros.

### GET /api/repos/{id}/commits?page=1&per_page=25

```json
{
  "commits": [
    {
      "hash": "abc123",
      "date": "2026-03-09T14:23:00-06:00",
      "author": "Synthetic Author",
      "message": "fix: handle empty response from API",
      "insertions": 45,
      "deletions": 12,
      "files_changed": 3
    }
  ],
  "page": 1,
  "per_page": 25,
  "total": 312
}
```

Sourced from `git log` at query time (not cached in SQLite; daily_stats only stores aggregates). Use `--skip` and `--max-count` for pagination.

### GET /api/repos/{id}/branches

```json
{
  "branches": [
    { "name": "main", "last_commit_date": "2026-03-09", "is_default": true, "is_stale": false },
    { "name": "feature/auth", "last_commit_date": "2025-12-01", "is_default": false, "is_stale": true }
  ]
}
```

### GET /api/repos/{id}/deps

```json
{
  "manager": "pip",
  "packages": [
    {
      "name": "fastapi",
      "current_version": "0.109.0",
      "wanted_version": "0.109.0",
      "latest_version": "0.115.0",
      "severity": "major",
      "advisory_id": null
    },
    {
      "name": "requests",
      "current_version": "2.31.0",
      "wanted_version": "2.31.0",
      "latest_version": "2.32.3",
      "severity": "vulnerable",
      "advisory_id": "CVE-2024-35195"
    }
  ],
  "checked_at": "2026-03-10T07:55:00-06:00"
}
```

### GET /api/analytics/heatmap?days=365

```json
{
  "data": [
    { "date": "2026-03-09", "count": 8 },
    { "date": "2026-03-08", "count": 3 }
  ],
  "max_count": 15
}
```

Aggregated commits across all repos per day.

### GET /api/analytics/allocation?days=90

```json
{
  "series": [
    { "repo_id": "a1b2c3", "name": "routerview", "data": [
      { "date": "2026-03-09", "commits": 3 },
      { "date": "2026-03-08", "commits": 1 }
    ]},
    { "repo_id": "d4e5f6", "name": "editdb", "data": [
      { "date": "2026-03-09", "commits": 1 }
    ]}
  ]
}
```

Only repos with activity in the period are included.

### GET /api/analytics/dep-overlap

```json
{
  "packages": [
    {
      "name": "fastapi",
      "manager": "pip",
      "repos": [
        { "repo_id": "a1b2c3", "name": "routerview", "version": "0.109.0" },
        { "repo_id": "d4e5f6", "name": "editdb", "version": "0.115.0" }
      ],
      "version_spread": "0.109.0 - 0.115.0",
      "count": 2
    }
  ]
}
```

Sorted by `count` descending. Only packages appearing in 2+ repos.

### POST /api/repos

Register a directory. Recursively find git repos.

Request:
```json
{ "path": "/Users/example/utilities" }
```

Response:
```json
{
  "registered": 42,
  "repos": [ { "id": "...", "name": "...", "path": "..." } ]
}
```

**Cross-platform note:** The `path` field accepts both forward and backslashes. The backend normalizes using `Path(path).resolve()` which produces the OS-native format. On Windows, paths like `C:\Users\example\projects` and `C:/Users/example/projects` both work.

### DELETE /api/repos/{id}

Unregister. Deletes from all tables (CASCADE). Returns 204.

---

## 5. UI Specification

### 5.1 Technology

Embedded in `HTML_TEMPLATE` string. No build step.

- React 18 via CDN (`react`, `react-dom`, `babel-standalone` for JSX)
- Recharts via CDN (for all charts)
- JetBrains Mono + Geist Sans via Google Fonts CDN
- No CSS framework. Inline styles + CSS custom properties.

CDN URLs (pin versions):
```html
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"></script>
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.9/babel.min.js"></script>
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/recharts/2.12.7/Recharts.min.js"></script>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Geist:wght@400;500;600&display=swap" rel="stylesheet">
```

**Font loading note:** If Google Fonts are unreachable (offline/air-gapped), fallback gracefully. The `--font-display` and CSS `font-family` stacks include system fallbacks so the UI remains functional without the custom fonts — it just won't look as polished.

### 5.2 Design System

CSS custom properties on `:root`:

```css
:root {
  /* Base */
  --bg-primary: #0f1117;
  --bg-secondary: #1a1d27;
  --bg-card: #1e2130;
  --bg-card-hover: #252838;
  --bg-input: #12141c;

  /* Borders */
  --border-default: #2a2d3a;
  --border-hover: #3a3d4a;

  /* Text */
  --text-primary: #e4e6ef;
  --text-secondary: #8b8fa3;
  --text-muted: #5a5e72;

  /* Accent */
  --accent-blue: #4c8dff;
  --accent-blue-dim: rgba(76,141,255,0.15);

  /* Status */
  --status-green: #34d399;
  --status-yellow: #fbbf24;
  --status-orange: #f97316;
  --status-red: #ef4444;
  --status-green-bg: rgba(52,211,153,0.12);
  --status-yellow-bg: rgba(251,191,36,0.12);
  --status-orange-bg: rgba(249,115,22,0.12);
  --status-red-bg: rgba(239,68,68,0.12);

  /* Freshness (card backgrounds + left border accents) */
  --fresh-this-week: var(--bg-card);          /* normal */
  --fresh-this-month: #1a1c28;               /* slightly dimmer */
  --fresh-older: #16171f;                     /* noticeably dimmer */
  --fresh-stale: #131420;                     /* very dim */

  /* Freshness left-border accents (secondary visual signal) */
  --fresh-border-this-week: var(--accent-blue);
  --fresh-border-this-month: transparent;     /* no border */
  --fresh-border-older: transparent;           /* no border */
  --fresh-border-stale: var(--status-orange);

  /* Runtime colors (for badges/icons) */
  --runtime-python: #3776ab;
  --runtime-node: #339933;
  --runtime-go: #00add8;
  --runtime-rust: #dea584;
  --runtime-ruby: #cc342d;
  --runtime-php: #777bb4;
  --runtime-shell: #4eaa25;
  --runtime-docker: #2496ed;
  --runtime-html: #e34c26;

  /* Typography */
  --font-heading: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace;
  --font-body: 'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace;

  /* Sizing */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;

  /* Transitions */
  --transition-fast: 100ms ease-out;
  --transition-normal: 150ms ease-out;
  --transition-slow: 200ms ease-out;
}
```

**Typography usage rules:**
- `--font-heading` (JetBrains Mono): App title, project names, KPI numbers, tab labels, section headers. Weight 500-700.
- `--font-body` (Geist Sans): Labels, descriptions, body text, button text, commit messages. Weight 400-600.
- `--font-mono` (JetBrains Mono): File paths, branch names, version numbers, commit hashes, code-like data. Weight 400.

### 5.3 Layout

```
+-----------------------------------------------------------------------+
| HEADER BAR (56px height)                                               |
| [logo/title]                      [Scan Dir] [Full Scan] [settings]   |
+-----------------------------------------------------------------------+
| NAV TABS (44px height)                                                 |
| [Fleet Overview]  [Analytics]  [Dependencies]                          |
+-----------------------------------------------------------------------+
| CONTENT AREA (fills remaining viewport, scrollable)                    |
|                                                                        |
|   (varies by active tab - see sections below)                          |
|                                                                        |
+-----------------------------------------------------------------------+
```

**Header bar**: Fixed top. Background `var(--bg-secondary)`. Border-bottom `1px solid var(--border-default)`. Title "Git Fleet" in 18px `var(--font-heading)` weight 700 `var(--text-primary)`. Right side: action buttons.

**Header button styling:**
- "Scan Dir" button: **secondary** style — `background: transparent`, `border: 1px solid var(--border-default)`, `color: var(--text-secondary)`, `font: 13px var(--font-body) weight 500`. Hover: `border-color: var(--border-hover)`, `color: var(--text-primary)`.
- "Full Scan" button: **primary** style — `background: var(--accent-blue)`, `border: none`, `color: #fff`, `font: 13px var(--font-body) weight 600`. Hover: `filter: brightness(1.1)`.
- Settings: icon-only button (gear SVG, 18px), same style as secondary but no border, just icon. `color: var(--text-muted)`. Hover: `color: var(--text-primary)`.
- All buttons: `padding: 8px 16px`, `border-radius: var(--radius-sm)`, `cursor: pointer`, `transition: all var(--transition-fast)`.

**Nav tabs**: Below header. Text-only, underline style (no pill/box, no icons). Font: 14px `var(--font-heading)` weight 500. Active tab has `var(--accent-blue)` underline (3px) and text color. Inactive tabs `var(--text-secondary)`. Hover on inactive: `var(--text-primary)`. Tab transition: underline slides to active tab (CSS `transition: left var(--transition-normal), width var(--transition-normal)` on a pseudo-element).

**Content area**: `padding: 24px`. `max-width: 1400px; margin: 0 auto`.

### 5.4 Fleet Overview Tab

#### KPI Row

Horizontal row of 6 stat cards at the top.

```
+----------+  +----------+  +----------+  +----------+  +----------+  +----------+
| 42       |  | 5 !!     |  | 23 / 87  |  | +1,450   |  | 12       |  | 3 / 18   |
| Repos    |  | Dirty    |  | Commits  |  | Net LOC  |  | Stale Br |  | Vuln/Out |
+----------+  +----------+  +----------+  +----------+  +----------+  +----------+
```

Each KPI card:
- Background: `var(--bg-card)`
- Border: `1px solid var(--border-default)`
- Border-radius: `var(--radius-md)`
- Padding: `16px 20px`
- Number: 28px `var(--font-heading)` weight 700 `var(--text-primary)`
- Label: 12px `var(--font-body)` weight 500 `var(--text-secondary)` uppercase tracking 0.5px
- Row layout: `display: flex; gap: 16px; flex-wrap: wrap`. Cards use `flex: 1 1 140px` so they fill available space evenly but wrap gracefully on narrower desktops (1024px viewport with 48px padding = ~976px, 6 cards wrap to two rows of 3).
- Conditional coloring:
  - "Dirty" count: number in `var(--status-yellow)` if > 0
  - "Vuln" count: number in `var(--status-red)` if > 0
  - "Stale Br": number in `var(--status-orange)` if > 0
  - Others: `var(--text-primary)`

#### Project Grid

Below KPI row, `margin-top: 24px`.

Grid layout: `display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px`.

**Sort control** above grid: dropdown with options:
- "Last active" (default) -- sort by `last_commit_date` desc
- "Name A-Z"
- "Most changes" -- sort by `modified_count + untracked_count` desc
- "Most stale branches"

Sort dropdown: `var(--bg-input)` background, `var(--border-default)` border, `var(--font-body)` 13px. Custom styled (not native `<select>`) for visual consistency.

**Filter control** next to sort: text input for filtering by name (case-insensitive substring match). Placeholder "Filter projects...". Style: `var(--bg-input)` background, `var(--border-default)` border, `var(--font-body)` 13px, `var(--text-primary)` text. On focus: `border-color: var(--accent-blue)`.

**Grid re-sort animation:** When sort order changes, cards animate to their new positions using CSS `transition: transform var(--transition-slow)` (apply via React key-based reordering with `transform` offsets, or use `layout` animation if feasible). If too complex, a simple crossfade (opacity 0 -> 1, 100ms) on the grid container is acceptable.

#### Project Card (Compact 3-Row)

Each card is 100% width of its grid cell. Compact layout optimized for scanability.

```
+-----------------------------------------------------------+
| [Py]  routerview                          3 days ago      |
| fix: handle empty response from API                       |
| [!!2 mod] [+1 new]  main  3br  12 deps                   |
+-----------------------------------------------------------+
```

On hover, a sparkline reveals from the bottom of the card (slides up, 150ms ease-out).

Detailed specs:

**Row 1: Header**
- Runtime badge: 24px square, rounded 4px, background is `var(--runtime-{type})` at 20% opacity, text is full color, font 11px `var(--font-heading)` weight 700 uppercase. Labels: "PY" (python), "JS" (node), "GO" (go), "RS" (rust), "RB" (ruby), "PHP" (php), "SH" (shell), "DK" (docker), "HTML" (html), "MIX" (mixed), "??" (unknown).
- Project name: 16px `var(--font-heading)` weight 600 `var(--text-primary)`, truncate with ellipsis. On hover, show **tooltip** with full filesystem path (12px `var(--font-mono)` weight 400, `var(--bg-secondary)` background, `var(--border-default)` border, `var(--radius-sm)` corners, padding `6px 10px`, max-width 500px, positioned above the name). Path displays as-is from the OS (backslashes on Windows, forward slashes on Unix).
- Time ago: 13px `var(--font-body)` `var(--text-secondary)`, right-aligned. Show relative time: "2h ago", "3d ago", "2mo ago". Use the `last_commit_date`.

**Row 2: Last commit message**
- 13px `var(--font-body)` `var(--text-secondary)`. Single line, truncate with ellipsis. Margin-left aligned with project name (past the runtime badge).

**Row 3: Status bar**
- All items on one line, `display: flex; align-items: center; gap: 8px; flex-wrap: wrap`.
- Left cluster: working tree status pills.
  - If clean: single green pill "Clean" with `var(--status-green)` text on `var(--status-green-bg)`.
  - If dirty: show pills for each category:
    - "2 mod" -- yellow pill (yellow text on yellow-bg)
    - "1 new" -- orange pill (orange text on orange-bg)
    - "1 staged" -- blue pill (accent-blue text on accent-blue-dim)
  - Pill style: 11px `var(--font-body)` weight 500, padding `2px 8px`, border-radius 4px.
- Separator: `var(--text-muted)` dot or `flex: 1` spacer pushing right cluster.
- Right cluster (13px `var(--font-mono)` weight 400):
  - Current branch name in `var(--text-secondary)`.
  - Branch count: "3br" in `var(--text-muted)`. If stale > 0, show in `var(--status-orange)`.
  - Dep badge (compact):
    - All ok: "12 deps" in `var(--text-muted)`
    - Some outdated: "3 out" in `var(--status-yellow)`
    - Any vulnerable: "1 vuln" in `var(--status-red)` (shown first if both vuln and outdated)
    - No deps: omit entirely

**Hover sparkline overlay:**
- On card hover, a sparkline bar reveals at the bottom of the card.
- Container: `position: absolute; bottom: 0; left: 0; right: 0; height: 32px; overflow: hidden`.
- Slides up from `translateY(100%)` to `translateY(0)` over `150ms ease-out`.
- Background: `linear-gradient(transparent, var(--bg-card) 30%)` to blend into the card.
- Sparkline: Recharts `<AreaChart>` filling the container width, 28px tall. Fill `var(--accent-blue-dim)`, stroke `var(--accent-blue)`, no axes, no tooltip. Data = 13-week commit counts.
- On mouse leave: slides back down over `100ms ease-in`.

**Card styling:**
- `position: relative; overflow: hidden` (for sparkline overlay).
- Background: varies by freshness. Determined by `last_commit_date`:
  - Within 7 days: `--fresh-this-week`
  - Within 30 days: `--fresh-this-month`
  - Within 90 days: `--fresh-older`
  - Older: `--fresh-stale`
- Left border accent (secondary freshness signal, more noticeable than background dimming alone):
  - Within 7 days: `border-left: 3px solid var(--fresh-border-this-week)` (blue)
  - Within 30 days: no left border
  - Within 90 days: no left border
  - Older: `border-left: 3px solid var(--fresh-border-stale)` (orange)
- Border: `1px solid var(--border-default)` (top, right, bottom). Left border as above or `1px solid var(--border-default)` when no freshness border.
- Border-radius: `var(--radius-md)`
- Padding: `14px 16px`
- On hover: background lightens to `var(--bg-card-hover)`, border to `var(--border-hover)`, `cursor: pointer`, sparkline reveals.
- Transition: `background var(--transition-fast), border-color var(--transition-fast)`.
- Click: navigates to project detail view.

### 5.5 Project Detail View

Reached by clicking a card. Back button at top-left returns to fleet.

**View transition:** When navigating from fleet to detail (and back), apply a fade + slight slide:
- Enter: `opacity: 0, translateY(8px)` -> `opacity: 1, translateY(0)` over `var(--transition-normal)`.
- Exit: instant (no exit animation — keeps navigation feeling snappy).

**Header area:**
```
[< Back]   routerview                    [Scan Now]
           /Users/example/utilities/routerview
           Python | main branch | Last scanned 5 min ago
```

- Back button: 13px `var(--font-body)`, `var(--text-secondary)`. Icon: left chevron (inline SVG). Hover: `var(--text-primary)`.
- Project name: 24px `var(--font-heading)` weight 700, `var(--text-primary)`.
- Path: 12px `var(--font-mono)` weight 400, `var(--text-muted)`.
- Meta line: 13px `var(--font-body)`, `var(--text-secondary)`. Runtime badge (same as card) + branch name + scan timestamp.
- "Scan Now" button: secondary style (same as "Scan Dir" in header).

Below: tabbed sub-views: **Activity** | **Commits** | **Branches** | **Dependencies**

Sub-tab style: same underline style as main nav tabs but slightly smaller (13px `var(--font-heading)` weight 500). Tab switch: content crossfades (`opacity 0 -> 1`, `var(--transition-fast)`).

#### Global Table Styling

All tables in sub-tabs share these styles:

- **Container**: `width: 100%`, no outer border. `border-radius: var(--radius-md)` on the wrapper with `overflow: hidden`.
- **Header row**: `background: var(--bg-secondary)`. Text: 12px `var(--font-body)` weight 600, `var(--text-muted)`, uppercase, tracking 0.5px. Padding: `10px 16px`. Bottom border: `1px solid var(--border-default)`.
- **Body rows**: Padding `12px 16px`. Alternating row backgrounds: odd rows `transparent`, even rows `rgba(255,255,255,0.02)`. Bottom border: `1px solid var(--border-default)` (except last row).
- **Row hover**: `background: var(--bg-card-hover)`. Transition: `background var(--transition-fast)`.
- **Empty state**: When a table has no data, show centered in the table area: a muted icon (24px, `var(--text-muted)`) + text (14px `var(--font-body)`, `var(--text-muted)`). Examples:
  - Commits: "No commits found"
  - Branches: "No branches found"
  - Dependencies: "No dependencies detected"

#### Activity Sub-tab (default)

**Mirrored / diverging area chart** (Recharts `<ComposedChart>` with `<Area>` components), 100% width, 300px height.

- X axis: dates (daily). Show tick labels every 7 days. Font: 11px `var(--font-mono)`, `var(--text-muted)`.
- Y axis: line count (positive above zero line, negative below). Font: 11px `var(--font-mono)`, `var(--text-muted)`.
- Zero line: `1px solid var(--border-default)`.
- Three series:
  - Insertions: **green area growing upward** from the zero line. Fill `var(--status-green)` at 20% opacity, stroke `var(--status-green)` at 100%, strokeWidth 1.5.
  - Deletions: **red area growing downward** from the zero line. Data values are negated (e.g., 45 deletions plotted as -45). Fill `var(--status-red)` at 20% opacity, stroke `var(--status-red)` at 100%, strokeWidth 1.5.
  - Net: **blue line overlay** (`var(--accent-blue)`), strokeWidth 2, no fill. Value = insertions - deletions (can be positive or negative).
- Implementation: Use Recharts `<AreaChart>` with `stackOffset="sign"`. The insertions `<Area>` uses raw positive values. The deletions `<Area>` uses negated values. Recharts handles the diverging layout automatically with `stackOffset="sign"`.
- Tooltip on hover: `var(--bg-card)` background, `var(--border-default)` border, `var(--radius-sm)`. Shows: date, insertions (green), deletions (red), net (blue), commits count. Font: 12px `var(--font-body)`.
- Time range selector above chart: [30d] [90d] [180d] [1y] [All]. Default 90d. These are buttons, active one has `var(--accent-blue)` background + white text, inactive has `transparent` background + `var(--text-secondary)`. Style: 12px `var(--font-heading)` weight 500, padding `4px 12px`, border-radius `var(--radius-sm)`. Group has `var(--bg-secondary)` background, `var(--border-default)` border, border-radius `var(--radius-md)`, padding `2px`.

#### Commits Sub-tab

Table with columns: Date | Message | +/- | Files

```
2026-03-09  fix: handle empty response from API    +45 -12   3 files
2026-03-08  feat: add caching layer                 +120 -8   5 files
```

- Date: 13px `var(--font-mono)`, `var(--text-secondary)`, show YYYY-MM-DD.
- Message: 14px `var(--font-body)`, `var(--text-primary)`, truncate at 80 chars.
- +/-: `var(--status-green)` for insertions, `var(--status-red)` for deletions, 13px `var(--font-mono)`.
- Files: 13px `var(--font-body)`, `var(--text-muted)`.
- Pagination: 25 per page. Show "Page 1 of 13" (13px `var(--font-body)` `var(--text-secondary)`) with prev/next buttons (secondary button style). Pagination bar below table, `margin-top: 16px`, `display: flex; justify-content: center; align-items: center; gap: 12px`.
- Row hover: per global table styling.

#### Branches Sub-tab

Table with columns: Branch | Last Commit | Status

```
main              2026-03-09    default
feature/auth      2025-12-01    stale (100 days)
bugfix/header     2026-02-28    active
```

- Branch name: 14px `var(--font-mono)`, `var(--text-primary)`.
- Last commit: 13px `var(--font-body)`, `var(--text-secondary)`.
- Status:
  - "default" -- blue badge: `var(--accent-blue)` text on `var(--accent-blue-dim)` background, 11px `var(--font-body)` weight 500, padding `2px 8px`, border-radius 4px.
  - "stale (N days)" -- orange badge: `var(--status-orange)` text on `var(--status-orange-bg)`, same sizing.
  - "active" -- no badge, just `var(--text-muted)` text.

Table sorted: default branch first, then by last_commit_date desc.

#### Dependencies Sub-tab

Table with columns: Package | Current | Latest | Status

```
fastapi           0.109.0    0.115.0    major update
requests          2.31.0     2.32.3     CVE-2024-35195
uvicorn           0.27.0     0.27.0     up to date
```

- Package name: 14px `var(--font-mono)`, `var(--text-primary)`.
- Versions: 13px `var(--font-mono)`. If current != latest, show latest in `var(--font-mono)` weight 600 (bold).
- Status:
  - "up to date": `var(--status-green)` text
  - "outdated": `var(--status-yellow)` text
  - "major update": `var(--status-orange)` text
  - "CVE-XXXX-XXXXX" (or advisory ID): `var(--status-red)` text, weight 600

Sort: vulnerable first, then major, then outdated, then ok.

Show "Last checked: 5 min ago" below table (13px `var(--font-body)` `var(--text-muted)`). Button "Check Now" (secondary style) triggers dep scan for this repo only.

### 5.6 Analytics Tab

Three sections stacked vertically with `gap: 32px`. Each section has a header: 18px `var(--font-heading)` weight 600, `var(--text-primary)`, `margin-bottom: 16px`.

#### Activity Heatmap

GitHub-style contribution grid. 52 columns (weeks) x 7 rows (days). Each cell is a 12px square with 2px gap.

Color scale (5 levels based on commit count relative to max, using blue to match accent):
- 0 commits: `var(--bg-secondary)`
- 1-25th percentile: `rgba(76,141,255,0.2)`
- 25-50th: `rgba(76,141,255,0.4)`
- 50-75th: `rgba(76,141,255,0.65)`
- 75-100th: `rgba(76,141,255,0.9)`

Day labels on left: Mon, Wed, Fri (skip Tue, Thu, Sat, Sun for space). Font: 11px `var(--font-body)`, `var(--text-muted)`.
Month labels on top: Jan, Feb, etc. Font: 11px `var(--font-body)`, `var(--text-muted)`.

Tooltip on hover: `var(--bg-card)` background, `var(--border-default)` border, `var(--radius-sm)`, padding `8px 12px`. Text: "March 9, 2026: 8 commits across 3 projects" in 12px `var(--font-body)`.

Cell hover: `outline: 2px solid var(--accent-blue)`, `outline-offset: -1px`.

#### Time Allocation (Stacked Area Chart)

Recharts `<AreaChart>` with `stackOffset="none"`.

- X axis: dates (weekly aggregation for 90d+ ranges, daily for shorter). Font: 11px `var(--font-mono)`, `var(--text-muted)`.
- Y axis: commit count. Font: 11px `var(--font-mono)`, `var(--text-muted)`.
- One series per repo that has activity in the range. Assign each repo a color from a palette of 10 distinct colors:
  ```
  #4c8dff, #34d399, #fbbf24, #f97316, #ef4444,
  #a78bfa, #ec4899, #06b6d4, #84cc16, #f43f5e
  ```
  If more than 10 repos, group the rest into "Other" (gray `var(--text-muted)`).
- Legend below chart: repo name + color swatch (8px circle). Clickable to toggle visibility. Font: 12px `var(--font-body)`, `var(--text-secondary)`. Active items `var(--text-primary)`. `display: flex; flex-wrap: wrap; gap: 12px 20px; margin-top: 12px`.
- Same time range selector as project detail activity chart.

#### Dependency Overlap Table

Table with columns: Package | Manager | Used In | Version Spread

```
fastapi     pip    8 repos    0.109.0 -- 0.115.0
express     npm    3 repos    4.18.0 -- 4.21.0
```

Uses global table styling. Additional column specs:
- Package: 14px `var(--font-mono)`, `var(--text-primary)`.
- Manager: 12px `var(--font-body)`, `var(--text-muted)`, uppercase.
- "Used In": shows count (13px `var(--font-body)` `var(--accent-blue)`), clickable to expand and show repo names + their versions. Expanded rows: indented 24px, 12px `var(--font-mono)` `var(--text-secondary)`, each repo on its own line. Expand/collapse icon: small chevron rotating 90 degrees on expand.
- "Version Spread": 13px `var(--font-mono)`, `var(--text-secondary)`. Shows min -- max version.
- Sorted by count desc.
- Only packages in 2+ repos shown.

### 5.7 Empty / Loading / Error States

**First launch (no repos registered):**

Centered in content area, `margin-top: 120px`.
```
  Welcome to Git Fleet

  Point this tool at a directory containing your git projects.

  [path input field: /Users/example/utilities]  [Scan]

  The tool will recursively find all git repositories.
```

- Title: 28px `var(--font-heading)` weight 700, `var(--text-primary)`.
- Subtitle: 14px `var(--font-body)`, `var(--text-secondary)`, `margin-top: 8px`.
- Input field: 400px wide, `var(--bg-input)` background, `var(--border-default)` border, border-radius `var(--radius-sm)`, `var(--font-mono)` 14px. Focus: `border-color: var(--accent-blue)`.
- Scan button: primary style (same as "Full Scan" in header).
- Help text: 12px `var(--font-body)`, `var(--text-muted)`, `margin-top: 12px`.
- On Windows, the placeholder path should auto-detect: show something like `C:\Users\username\projects` rather than a Unix path. Use the OS-appropriate example path based on `navigator.platform` or a value injected by the backend.

**Loading state (during quick scan):**

Show skeleton cards: same card dimensions (compact 3-row) but with animated pulse on gray rectangles where text would be. Use CSS keyframes:
```css
@keyframes pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.7; }
}
```
Skeleton rectangles: `var(--border-default)` background, border-radius 4px, `animation: pulse 1.5s ease-in-out infinite`. Vary widths to mimic text: header line 60%, commit line 80%, status line 50%.

**Full scan in progress:**

Two UI elements:

1. **Progress bar**: Slim bar below the nav tabs, full width. Background `var(--border-default)`, fill `var(--accent-blue)`. Height: 3px. Fill width = `(progress / total) * 100%`. Transition: `width 300ms ease-out`.

2. **Scan toast**: Floating notification, bottom-right corner, `position: fixed; bottom: 24px; right: 24px`.
   - Dimensions: 320px wide, auto height.
   - Background: `var(--bg-card)`.
   - Border: `1px solid var(--border-default)`.
   - Border-radius: `var(--radius-md)`.
   - Box-shadow: `0 8px 32px rgba(0,0,0,0.4)`.
   - Padding: `16px`.
   - Enter animation: slide in from right (`translateX(100%)` -> `translateX(0)`, `var(--transition-slow)`).
   - Content:
     - Header: "Scanning..." in 13px `var(--font-heading)` weight 600, `var(--text-primary)`.
     - Current repo: 12px `var(--font-mono)`, `var(--text-secondary)`.
     - Progress: mini progress bar (height 4px, full width of toast, same colors as main progress bar) + "12 / 42" count in 12px `var(--font-body)` `var(--text-muted)`, right-aligned.
   - On completion: text changes to "Scan complete", progress bar fills to 100% green (`var(--status-green)`). Toast auto-dismisses after 2 seconds (slides out to right).

**Error states:**

If a repo path no longer exists:
- Card shows red left border (4px `var(--status-red)`, overriding any freshness border) and last row text "Path not found" in `var(--status-red)` instead of the normal status row.
- Detail view shows same message with "Remove" and "Update Path" buttons. "Remove" is secondary style with `var(--status-red)` text. "Update Path" is secondary style with normal text.

If git command fails for a repo:
- Card still shows, with last cached data. Small badge "scan failed" at top-right corner of card: 10px `var(--font-body)` weight 600, `var(--status-red)` text on `var(--status-red-bg)`, padding `2px 6px`, border-radius 3px.

Network error (dep check):
- Show last cached data with "offline" indicator next to "Last checked" text: a small dot (6px circle, `var(--status-orange)`) + "offline" in `var(--status-orange)`.

### 5.8 Interactions, Routing, and Accessibility

**Client-side routing** using hash fragments:
- `#/` or `#/fleet` -- Fleet Overview
- `#/repo/{id}` -- Project Detail (default to Activity sub-tab)
- `#/repo/{id}/commits` -- Commits sub-tab
- `#/repo/{id}/branches` -- Branches sub-tab
- `#/repo/{id}/deps` -- Dependencies sub-tab
- `#/analytics` -- Analytics tab
- `#/deps` -- Dependencies cross-view (dep overlap + fleet-wide dep health)

Use a simple `window.onhashchange` listener + state variable, not a router library.

**View transitions:**
- Fleet -> Detail: content area fades in with `opacity: 0, translateY(8px)` -> `opacity: 1, translateY(0)` over `var(--transition-normal)`.
- Detail -> Fleet (back): same fade-in on the fleet content.
- Main tab switches (Fleet / Analytics / Dependencies): crossfade, `opacity 0 -> 1` over `var(--transition-fast)`.
- Sub-tab switches within detail view: crossfade, `opacity 0 -> 1` over `var(--transition-fast)`.

**Focus states (keyboard accessibility):**
- All interactive elements (buttons, tabs, cards, links, inputs, table rows) must have a visible `:focus-visible` style.
- Focus ring: `outline: 2px solid var(--accent-blue); outline-offset: 2px`.
- Cards: on focus, apply same visual treatment as hover (background + border change).
- Do not show focus ring on mouse click (`:focus-visible` handles this automatically in modern browsers).

**Keyboard navigation:**
- Tab through KPI cards, sort/filter controls, project cards.
- Enter/Space on a card navigates to detail view.
- Escape in detail view returns to fleet.

---

## 6. Scan Modes and Orchestration

### Quick Scan Flow (on page load)

```
1. GET /api/fleet
2. Backend runs quick scan for all registered repos (parallel, asyncio.gather)
3. Updates working_state table
4. Returns fleet data with sparklines from cached daily_stats
5. Frontend renders immediately
```

Concurrency: run up to 8 repos simultaneously (`asyncio.Semaphore(8)`).

### Full Scan Flow (on button click)

```
1. POST /api/fleet/scan  { "type": "full" }
2. Backend creates scan_log entry, returns scan_id
3. Frontend opens SSE connection to /api/fleet/scan/{scan_id}/progress
4. Backend processes repos sequentially (to avoid hammering disk):
   a. For each repo:
      - git log --after={last_full_scan_at} for incremental history
      - Parse and upsert daily_stats
      - git branch scan
      - Update last_full_scan_at
      - Send SSE progress event
5. On completion, send final SSE event with status=completed
6. Frontend refetches /api/fleet to refresh UI
```

### Dep Scan Flow

Same as full scan but `type=deps`. Only runs dependency detection + health checks. Separated because dep checks involve network calls (PyPI API, npm registry) and are slower.

---

## 7. Performance Targets

| Operation | Target | Approach |
|---|---|---|
| Quick scan (40 repos) | < 3 seconds | Parallel subprocess, semaphore(8) |
| Fleet overview render | < 200ms after data | Virtualize if > 100 repos; else plain render |
| Full scan (40 repos, incremental) | < 30 seconds | Sequential disk, parallel parse |
| Dep scan (40 repos) | < 60 seconds | Parallel network calls, semaphore(4) |
| Sparkline data query | < 50ms | Pre-aggregated weekly data in daily_stats |

---

## 8. Implementation Phases

### Phase 1: Skeleton + Fleet Overview

Deliverable: working app with fleet overview, project cards (no sparklines, no dep badges).

1. Bootstrap script (venv, deps, re-exec) — cross-platform (Windows + Unix)
2. SQLite schema init
3. FastAPI app with `/` serving HTML_TEMPLATE
4. `POST /api/repos` -- directory registration + recursive git repo discovery
5. `GET /api/fleet` -- quick scan + response
6. React SPA: header, nav tabs (only Fleet active), KPI row, project grid with compact 3-row cards
7. First-launch empty state with directory input
8. `GET /api/repos/{id}` -- detail endpoint
9. Project detail view: header + commits sub-tab (live git log query)

### Phase 2: History + Charts

1. Full scan endpoint + SSE progress
2. `git log` history parser into daily_stats
3. Sparklines on fleet cards (hover-reveal, from cached weekly aggregates)
4. Project detail Activity sub-tab with mirrored/diverging area chart
5. Branch scan + Branches sub-tab
6. Progress bar + scan toast UI during full scan

### Phase 3: Dependencies

1. Dependency file detection (requirements.txt, package.json, pyproject.toml)
2. Python outdated check via PyPI JSON API
3. Python vulnerability check via pip-audit (if available)
4. Node outdated check via npm outdated
5. Node vulnerability check via npm audit
6. Dependency health badges on cards (compact inline format)
7. Project detail Dependencies sub-tab

### Phase 4: Analytics

1. Heatmap endpoint + component
2. Time allocation endpoint + stacked area chart
3. Dependency overlap endpoint + expandable table
4. Analytics tab wiring

---

## 9. Edge Cases and Error Handling

| Scenario | Behavior |
|---|---|
| Registered path deleted from disk | Card shows error state with red left border. Quick scan marks it. Offer "Remove" button. |
| Repo has zero commits | Card shows "Empty repository" in commit message row. No sparkline. |
| Repo has no remote | Works fine; this tool is local-only. |
| Git not installed | Fail fast on startup with clear error message. Check via `shutil.which("git")`. |
| Very large repo (Linux kernel scale) | git log with `--after` keeps incremental scans fast. Initial scan may be slow; show progress. |
| Binary-heavy repo | `--shortstat` still works; insertions/deletions reflect binary changes as git reports them. |
| Shallow clone | `git log` returns available history. No error. |
| Concurrent scans | Reject second scan if one is in progress (return 409). |
| requirements.txt with `-r other.txt` includes | Follow one level of includes. Skip on circular reference. |
| package.json with no lockfile | `npm outdated` still works. `npm audit` may fail; skip gracefully. |
| Non-UTF8 commit messages | Use `errors='replace'` in subprocess output decoding. |
| Repo inside repo (submodules) | Only register the outer repo unless submodule is independently added. Discovery uses `git rev-parse --show-toplevel` to deduplicate. |
| Windows paths with spaces | All paths passed via `asyncio.create_subprocess_exec` (list form, not shell string), so spaces are handled correctly. |
| Windows long paths (>260 chars) | Use `\\?\` prefix or rely on Python 3.6+ long path support. `Path.resolve()` handles this. |
| Google Fonts CDN unreachable | Fonts fall back to system font stack. UI remains functional, just less polished. |
| Go workspace (`go.work`) | Treat each module in the workspace as a separate repo if independently registered. `go.mod` in each module dir is the detection signal. |
| Rust workspace (`Cargo.toml` with `[workspace]`) | Parse the top-level `Cargo.toml`. If it has `[workspace]`, collect deps from member `Cargo.toml` files. |
| `Cargo.lock` missing | `cargo outdated` and `cargo audit` may fail. Skip gracefully, same pattern as npm without lockfile. |
| `go.sum` missing | `go list -m -u -json all` still works. `govulncheck` may require `go mod download` first — skip if it fails. |
| Tool produces unexpected output | Catch JSON parse errors, log them, mark that check as failed in the UI. Never crash the scan. |
| Mixed-ecosystem repo | All detected ecosystems get independent dep parsing and health checks. Each ecosystem's deps shown separately in the deps table/badge. |

---

## 10. Things This Spec Intentionally Excludes

- **No authentication.** Local-only tool.
- **No background daemon.** Launch-and-check pattern.
- **No remote push/pull operations.** Read-only against git repos.
- **No file editing.** Pure observation dashboard.
- **No GitHub/GitLab API integration.** Repo-host-agnostic.
- **No dark/light theme toggle.** Dark only.
- **No mobile responsive design.** Desktop tool, min-width 1024px.

---

## 11. Cross-Platform Requirements

This tool must run identically on **Windows 10+**, **macOS 12+**, and **Linux** (any distro with Python 3.9+ and git installed).

### Python / Backend

| Concern | Approach |
|---|---|
| **File paths** | Always use `pathlib.Path`. Never construct paths with string concatenation or hardcoded `/`. `Path.resolve()` produces OS-native separators. |
| **Venv creation** | Use `python -m venv`. Venv Python location: `Scripts/python.exe` (Windows) vs `bin/python` (Unix). Detect via `sys.platform == "win32"`. |
| **Subprocess execution** | Always use `asyncio.create_subprocess_exec` with arguments as a list (never `shell=True`). This avoids shell escaping issues and handles spaces in paths. |
| **Executable lookup** | Use `shutil.which()` to find `git`, `npm`, `pip-audit`. Returns platform-correct paths (e.g., `git.exe` on Windows). |
| **Event loop (Windows)** | Python 3.8+ uses `ProactorEventLoop` by default on Windows, which supports `create_subprocess_exec`. No special setup needed. |
| **Line endings** | `git` output uses `\n` on all platforms. Decode with `.decode('utf-8', errors='replace')` and split on `\n`. |
| **Browser launch** | `webbrowser.open()` is cross-platform. Works on Windows (default browser), macOS (`open`), Linux (`xdg-open`). |
| **Home directory** | `Path.home()` returns the correct home on all platforms (`C:\Users\username` on Windows, `/Users/example` on macOS, `/home/username` on Linux). |
| **File permissions** | Do not use `os.chmod` or assume Unix permission bits. Venv creation and file I/O work without explicit permission changes on all platforms. |
| **Process re-exec** | When re-executing under the venv Python, use `os.execv` on Unix. On Windows, `os.execv` is unreliable — instead use `subprocess.run([venv_python, *sys.argv])` followed by `sys.exit()`. |
| **Temp files / atomicity** | If writing temp files (e.g., during DB migration), use `tempfile` module which handles OS-specific temp directories. |
| **Signal handling** | `SIGTERM`/`SIGINT` for graceful shutdown. On Windows, only `SIGINT` (Ctrl+C) is reliably delivered. Use `signal.signal(signal.SIGINT, handler)` and avoid `SIGTERM` on Windows. |

### Frontend / UI

| Concern | Approach |
|---|---|
| **Path display** | Display paths as-is from the backend. Windows paths use `\`, Unix paths use `/`. Do not normalize or convert. |
| **First-launch placeholder** | The backend should inject a sensible default path into the HTML template based on the OS. E.g., `C:\Users\username\projects` on Windows, `~/projects` on Unix. |
| **Font rendering** | JetBrains Mono and Geist Sans are loaded via Google Fonts CDN. Rendering is handled by the browser on each platform. Fallback fonts in the stack cover all platforms (`-apple-system` for macOS, `Segoe UI` for Windows, `system-ui` for Linux). |
| **Scrollbar styling** | The `::-webkit-scrollbar` CSS pseudo-elements work on Chrome/Edge (all platforms) and Safari. Firefox uses `scrollbar-color` and `scrollbar-width`. Provide both for cross-browser dark scrollbars. |

### Git

| Concern | Approach |
|---|---|
| **git executable** | `shutil.which("git")` finds `git.exe` on Windows, `git` on Unix. |
| **git -C** | Works identically on all platforms. Always pass the path as a string from `Path.resolve()`. |
| **git output encoding** | Git on Windows may output non-UTF8 in some locales. Always decode with `errors='replace'`. |
| **Symlinks** | Some repos may use symlinks. `Path.resolve()` follows symlinks, which is correct for deduplication. On Windows, symlinks require developer mode or admin privileges — if `Path.resolve()` fails, catch the error and use the unresolved path. |
