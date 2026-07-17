# launchmaster — Implementation Plan

> **Superseded:** This historical implementation plan predates the uv-managed PEP 723 launcher. The launcher no longer creates a private venv or bootstrap state file.

## Overview

A macOS launchd job dashboard and control center. Self-bootstrapping single-file Python app with embedded React SPA, following the routerview/editdb pattern.

**Runtime home:** `~/.launchmaster/`
**Venv:** `~/.launchmaster_venv/`
**Entry point:** `launchmaster/launchmaster` (single executable script)
**Default port:** 8200

---

## Step 1: Scaffold and Bootstrap

Create `launchmaster/launchmaster` with the self-bootstrapping skeleton.

### 1.1 File header and constants

```python
#!/usr/bin/env python3
"""launchmaster — macOS launchd Control Center"""

import os, sys, subprocess, socket

VENV_DIR = os.path.expanduser("~/.launchmaster_venv")
DATA_DIR = os.path.expanduser("~/.launchmaster")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
VERSION = "1.0.0"
DEFAULT_PORT = 8200

DEPENDENCIES = [
    "fastapi",
    "uvicorn[standard]",
    "python-multipart",
]
```

### 1.2 Bootstrap function with dependency refresh

Follow the `fid_div_conv` pattern — explicit state file tracking with automatic refresh on version bumps or Python upgrades.

**State file:** `~/.launchmaster/bootstrap_state.json`
```json
{
  "bootstrap_version": 1,
  "python_version": "3.12"
}
```

**Constants:**
```python
BOOTSTRAP_VERSION = 1  # Bump this to force dep refresh on next run
```

**Core logic:**
```python
def desired_bootstrap_state():
    return {
        "bootstrap_version": BOOTSTRAP_VERSION,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
    }

def read_bootstrap_state():
    state_file = os.path.join(DATA_DIR, "bootstrap_state.json")
    if not os.path.isfile(state_file):
        return None
    try:
        with open(state_file) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None

def write_bootstrap_state():
    os.makedirs(DATA_DIR, exist_ok=True)
    state_file = os.path.join(DATA_DIR, "bootstrap_state.json")
    with open(state_file, "w") as f:
        json.dump(desired_bootstrap_state(), f, indent=2)
```

**Bootstrap flow:**
```python
def bootstrap():
    venv_python = os.path.join(VENV_DIR, "bin", "python")
    in_target_venv = os.path.realpath(sys.prefix) == os.path.realpath(VENV_DIR)
    needs_refresh = (
        not os.path.isfile(venv_python)
        or read_bootstrap_state() != desired_bootstrap_state()
    )

    if not in_target_venv:
        if needs_refresh:
            if os.path.exists(VENV_DIR):
                import shutil
                shutil.rmtree(VENV_DIR)
            print("Setting up launchmaster environment...")
            subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])
            subprocess.check_call([
                os.path.join(VENV_DIR, "bin", "pip"), "install", "--quiet",
                *DEPENDENCIES
            ])
            write_bootstrap_state()
            print("Ready.")
        os.execv(venv_python, [venv_python] + sys.argv)

    # Already in target venv
    if needs_refresh:
        write_bootstrap_state()

bootstrap()  # Called at module level before third-party imports
```

**What triggers a refresh:**
- Missing venv (first run)
- Missing or corrupt `bootstrap_state.json`
- `BOOTSTRAP_VERSION` bumped in code (e.g., dependency added/removed)
- Python major.minor version changed (e.g., user upgrades 3.12 → 3.13)

**Informational commands skip bootstrap:** `--help` should work without mutating state:
```python
if "--help" in sys.argv or "-h" in sys.argv:
    # Skip bootstrap, just run argparse
    ...
```

### 1.3 Argument parsing

```python
def parse_args():
    parser = argparse.ArgumentParser(
        prog="launchmaster",
        description="launchmaster — macOS launchd Control Center"
    )
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()
```

### 1.4 Port scanning, browser launch, main()

- `find_free_port(preferred, max_attempts=20)` — stdlib socket bind scan
- `main()` → `os.makedirs(DATA_DIR, exist_ok=True)`, `os.makedirs(BACKUP_DIR, exist_ok=True)`, resolve port, start browser thread (unless `--no-browser`), run uvicorn

### 1.5 Verification

- `./launchmaster --help` runs cleanly without installing deps
- First run creates venv, installs deps, re-execs
- Second run starts immediately (deps cached)

---

## Step 2: launchd Discovery Engine

Build the core backend that discovers and queries launchd jobs. All functions in this step are pure Python (no FastAPI yet).

### 2.1 Plist directory scanner

```python
PLIST_DIRS = {
    "user-agent":    os.path.expanduser("~/Library/LaunchAgents"),
    "global-agent":  "/Library/LaunchAgents",
    "system-daemon": "/Library/LaunchDaemons",
    "apple-agent":   "/System/Library/LaunchAgents",
    "apple-daemon":  "/System/Library/LaunchDaemons",
}
```

Function `discover_plists() -> list[dict]`:
- Walk each directory, find all `*.plist` files
- For each plist, parse with `plistlib.load()` (stdlib, binary and XML plist support)
- Extract: `Label`, `ProgramArguments` or `Program`, `RunAtLoad`, `KeepAlive`, `StartInterval`, `StartCalendarInterval`, `WatchPaths`, `StandardOutPath`, `StandardErrorPath`, `WorkingDirectory`, `EnvironmentVariables`, `Disabled`
- Map each to a domain based on which directory it came from
- Return list of dicts with parsed plist data + file path + domain

Handle errors gracefully:
- Permission denied on `/System/Library/` or `/Library/` → skip with warning, don't crash
- Malformed plist → include in list with `parse_error` field
- Missing directory → skip silently

### 2.2 Runtime state via launchctl

Function `get_launchctl_state() -> dict[str, dict]`:
- Run `launchctl list` → parse output (tab-separated: PID, Status, Label)
- Returns `{label: {"pid": int|None, "last_exit": int|None}}`
- PID column is `-` when not running → map to `None`
- Status column is last exit code (0 = clean, nonzero = error, `-` = never run)

Function `get_job_blame(label: str) -> str|None`:
- Run `launchctl blame gui/{uid}/{label}` (for user-domain jobs) or `system/{label}` (for system-domain)
- Parse the output for the blame reason
- Return the string or None if unavailable
- Get uid via `os.getuid()`

Function `get_job_detail(label: str) -> dict`:
- Run `launchctl print gui/{uid}/{label}` or `system/{label}`
- Parse output for detailed state (state, last exit status, path, environment)
- This is supplemental — used when detail panel opens, not on every poll

### 2.3 Merge plist + runtime state

Function `build_job_list(include_apple: bool = False) -> list[dict]`:
- Call `discover_plists()` to get all configured jobs
- Call `get_launchctl_state()` to get runtime state
- Merge by label: join plist config with runtime PID/exit status
- Also detect "loaded but no plist" jobs (orphans) from launchctl list
- Compute derived fields:
  - `status`: running | idle | failed | disabled | unloaded (same logic as prototype)
  - `schedule_human`: human-readable schedule string from plist keys
  - `is_apple`: `domain.startswith("apple")`
- Optionally filter out Apple jobs based on `include_apple`

### 2.4 Schedule humanizer

Function `humanize_schedule(plist_data: dict) -> str`:
- If `KeepAlive` → "Always running (KeepAlive)"
- If `StartInterval` → "Every N minutes/hours/seconds" (convert intelligently)
- If `StartCalendarInterval` → parse Hour/Minute/Weekday/Day into "Mondays, Wednesdays at 6:00 AM" etc.
  - Handle array of dicts (multi-day) vs single dict
- If `WatchPaths` → "Watching: path1, path2"
- If `RunAtLoad` only → "Run at load"
- Fallback: "Manual"

### 2.5 Verification

- Write a small test: call `build_job_list(include_apple=True)` and print results
- Verify it finds real jobs on the system
- Verify Apple jobs are correctly tagged
- Verify failed jobs have non-zero exit codes and blame text

---

## Step 3: Job Control Operations

Backend functions that execute launchctl commands to control jobs. Each function returns a result dict `{"success": bool, "message": str}`.

### 3.1 Core control functions

All commands use `subprocess.run()` with `capture_output=True, text=True, timeout=10`.

The UID for user-domain: `os.getuid()`. The domain target format:
- User agents: `gui/{uid}/{label}`
- System daemons: `system/{label}`

```python
async def start_job(label: str, domain: str) -> dict
```
- `launchctl kickstart -p gui/{uid}/{label}` (for user domain)
- `-p` flag prints PID of started job

```python
async def stop_job(label: str, domain: str) -> dict
```
- `launchctl kill SIGTERM gui/{uid}/{label}`
- If that fails, try `launchctl kill SIGKILL`

```python
async def reload_job(label: str, domain: str, plist_path: str) -> dict
```
- Composite operation:
  1. `launchctl bootout gui/{uid}/{label}` (unload)
  2. Brief `asyncio.sleep(0.5)`
  3. `launchctl bootstrap gui/{uid} {plist_path}` (load)
- Report success/failure of each step

```python
async def enable_job(label: str, domain: str) -> dict
```
- `launchctl enable gui/{uid}/{label}`

```python
async def disable_job(label: str, domain: str) -> dict
```
- `launchctl disable gui/{uid}/{label}`

```python
async def load_job(plist_path: str, domain: str) -> dict
```
- `launchctl bootstrap gui/{uid} {plist_path}` (modern API) or fallback to `launchctl load {plist_path}`

```python
async def unload_job(label: str, domain: str, plist_path: str) -> dict
```
- `launchctl bootout gui/{uid}/{label}` or fallback to `launchctl unload {plist_path}`

```python
async def run_now(label: str, domain: str) -> dict
```
- `launchctl kickstart gui/{uid}/{label}` — one-shot execution, works even if job isn't scheduled to run
- Different from `start_job` only semantically (same underlying command)

### 3.2 Plist CRUD operations

```python
async def save_plist(plist_path: str, content: str) -> dict
```
- Validate XML plist by attempting `plistlib.loads(content.encode())`
- If valid, write to `plist_path`
- If writing to `/Library/` or `/System/`, this will require elevated permissions → return appropriate error message

```python
async def create_job(plist_data: dict, domain: str) -> dict
```
- Build plist XML from the dict (using `plistlib.dumps()`)
- Determine target directory from domain
- Write plist file to `{target_dir}/{label}.plist`
- Auto-load via `load_job()`

```python
async def delete_job(label: str, domain: str, plist_path: str) -> dict
```
- **Backup first**: copy plist to `~/.launchmaster/backups/{label}.{timestamp}.plist`
- Unload if currently loaded
- Delete plist file
- Return backup path in response

```python
async def export_job(plist_path: str) -> str
```
- Read and return plist file contents as string

```python
async def import_job(content: str, domain: str) -> dict
```
- Validate plist XML
- Extract label from plist
- Write to appropriate directory
- Auto-load

### 3.3 Backup management

```python
def backup_plist(plist_path: str) -> str
```
- Copy plist to `BACKUP_DIR/{label}.{YYYYMMDD_HHMMSS}.plist`
- Return backup file path

```python
def list_backups() -> list[dict]
```
- Scan `BACKUP_DIR` for `*.plist` files
- Return list of `{"label": ..., "timestamp": ..., "path": ...}`

### 3.4 Verification

- Test each control function against a test plist (create a dummy `com.launchmaster.test` job)
- Verify start/stop/reload cycle works
- Verify delete creates backup
- Verify create generates valid plist and loads it

---

## Step 4: Log Reader

### 4.1 File-based log reader

```python
async def read_log(path: str, tail_lines: int = 200) -> list[str]
```
- Read last N lines from `StandardOutPath` or `StandardErrorPath`
- Handle: file doesn't exist, permission denied, file is empty
- Return lines as list of strings

### 4.2 Unified log query

```python
async def read_unified_log(label: str, limit: int = 100) -> list[str]
```
- Run: `log show --predicate 'process == "{label}"' --last 1h --style compact --info`
- Parse output lines
- Limit to last N entries
- Handle timeout (unified log can be slow) — use 5-second timeout

### 4.3 Verification

- Test against a known job with log files
- Test unified log query
- Verify graceful handling when log files don't exist

---

## Step 5: FastAPI REST API

### 5.1 App setup with lifespan

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(application):
    # Startup: initial job scan, start background poll task
    global _cached_jobs
    _cached_jobs = build_job_list(include_apple=True)
    asyncio.create_task(_poll_loop())
    yield
    # Shutdown: nothing needed

app = FastAPI(title="launchmaster", version=VERSION, lifespan=lifespan)
```

### 5.2 Endpoints

**Job listing:**
```
GET /api/jobs?include_apple=true
```
Returns the cached job list. Query param controls Apple job inclusion.

**Job detail:**
```
GET /api/jobs/{label}
```
Returns full detail for one job (calls `get_job_detail()` for extra info).

**Job control:**
```
POST /api/jobs/{label}/start
POST /api/jobs/{label}/stop
POST /api/jobs/{label}/restart    (alias for reload)
POST /api/jobs/{label}/reload
POST /api/jobs/{label}/enable
POST /api/jobs/{label}/disable
POST /api/jobs/{label}/load
POST /api/jobs/{label}/unload
POST /api/jobs/{label}/run-now
```
Each returns `{"success": bool, "message": str}`. After any control action, trigger a re-scan of job state.

**Plist operations:**
```
GET  /api/jobs/{label}/plist          → raw plist content
PUT  /api/jobs/{label}/plist          → save edited plist (body: {"content": "..."})
POST /api/jobs/{label}/export         → download plist as file
DELETE /api/jobs/{label}              → delete job (auto-backup)
```

**Create / Import:**
```
POST /api/jobs                        → create new job (body: plist_data dict + domain)
POST /api/jobs/import                 → import plist (body: {"content": "...", "domain": "..."})
```

**Logs:**
```
GET /api/jobs/{label}/logs/stdout?lines=200
GET /api/jobs/{label}/logs/stderr?lines=200
GET /api/jobs/{label}/logs/unified?lines=100
```

**Backups:**
```
GET /api/backups                      → list all backups
POST /api/backups/{filename}/restore  → restore a backup
```

**Settings:**
```
GET  /api/settings                    → read config.json
PUT  /api/settings                    → write config.json
```

**Health:**
```
GET /api/health                       → {"status": "ok", "version": "1.0.0", "job_count": N}
```

**SPA:**
```
GET /                                 → serve HTML_TEMPLATE
```

### 5.3 Background polling

```python
_cached_jobs = []
_ws_clients: set[WebSocket] = set()

async def _poll_loop():
    """Periodically re-scan job state and push to WebSocket clients."""
    global _cached_jobs
    while True:
        await asyncio.sleep(config.get("poll_interval", 5))
        new_jobs = build_job_list(include_apple=True)
        if new_jobs != _cached_jobs:
            _cached_jobs = new_jobs
            await _broadcast_jobs()

async def _broadcast_jobs():
    """Push current job list to all connected WebSocket clients."""
    data = json.dumps({"type": "jobs", "data": _cached_jobs})
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(data)
        except Exception:
            dead.add(ws)
    _ws_clients -= dead
```

### 5.4 WebSocket endpoint

```python
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    try:
        # Send initial state
        await ws.send_text(json.dumps({"type": "jobs", "data": _cached_jobs}))
        # Keep alive, receive commands
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "refresh":
                _cached_jobs = build_job_list(include_apple=True)
                await _broadcast_jobs()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)
```

### 5.5 Verification

- Start the server, hit `/api/health` → returns OK
- Hit `/api/jobs` → returns real job list from the system
- Test control endpoints against a test job
- Test WebSocket connection receives updates

---

## Step 6: Embedded React SPA — Core Layout and Status

Port the design prototype into `HTML_TEMPLATE`. Build incrementally.

### 6.1 HTML shell

Copy the structure from the prototype:
- CDN imports: React 18, ReactDOM 18, Babel Standalone, Lucide
- CSS variables, fonts (Chakra Petch + IBM Plex Mono), all the styles from the prototype
- `<div id="root">`, `<script type="text/babel">`

Inline SVG icons approach: Use the same `AppleLogo` SVG component from the prototype. For other icons, keep using Lucide CDN (it works in the prototype).

### 6.2 WebSocket hook

```javascript
function useWebSocket(url) {
  const [jobs, setJobs] = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => { setConnected(false); setTimeout(connect, 3000); };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === 'jobs') setJobs(msg.data);
      };
    };
    connect();
    return () => wsRef.current?.close();
  }, [url]);

  const refresh = () => wsRef.current?.send(JSON.stringify({type: 'refresh'}));
  return { jobs, connected, refresh };
}
```

### 6.3 API helper

```javascript
async function api(path, options = {}) {
  const resp = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  return resp.json();
}
```

### 6.4 App shell, topbar, status cards

Port directly from prototype:
- `App` component with state management
- Topbar with brand, WS status indicator, Import/New Job/Refresh/Settings buttons
- `StatusCards` component — clickable counts for Running/Idle/Failed/Disabled/Unloaded
- Wire status card clicks to filter state

### 6.5 Failed jobs alert panel

Port `FailedPanel` from prototype:
- Collapsible, red glow animation
- Each failed job row: label, exit code, blame, Logs/Edit/Reload buttons
- Clicking row body opens detail panel on Info tab
- Clicking Logs button opens detail panel on Logs tab
- Clicking Edit button opens detail panel on Edit tab

### 6.6 Verification

- Server starts, browser opens, shows status cards with real job counts
- Failed panel shows if any jobs have non-zero exit codes
- WebSocket indicator shows "Live" when connected

---

## Step 7: Embedded React SPA — Job Table and Filters

### 7.1 Filter bar

Port from prototype:
- Search input with clear button (amber "x clear" pill) and Esc-to-clear
- Domain dropdown (All / User / Global / System / Apple when visible)
- Apple Jobs toggle (disabled when domain dropdown = Apple)
- Status filter chips
- Keyboard shortcut hint

### 7.2 Job table

Port from prototype:
- Sortable columns: Status, Label, Domain, Schedule, PID, Last Exit
- Apple rows: amber tint background, 3px amber left border, amber Apple SVG icon, italic gold label text, amber domain badge
- Status dots with glow effects
- Row hover reveals action buttons: Start, Stop, Run Now, Reload, Edit, Logs, Export, Delete
- Checkbox multi-select with select-all header checkbox
- Row click opens detail panel

### 7.3 Pagination

Port from prototype:
- `PAGE_SIZE = 25`
- First / Prev / Next / Last text buttons with visible borders
- Click "Page X of Y" to type a page number
- Job count + "per page" display
- Reset to page 1 on filter change

### 7.4 Bulk action bar

Port from prototype:
- Appears when rows are selected
- Start All, Stop All, Reload All, Enable, Disable, Delete buttons
- Clear Selection button

### 7.5 Wire to real API

All action buttons call the REST API:
```javascript
const handleStart = async (label) => {
  const result = await api(`/jobs/${encodeURIComponent(label)}/start`, { method: 'POST' });
  addToast(result.success ? 'success' : 'error', result.message);
};
```

After any action, the WebSocket will push updated state automatically (backend re-scans after control operations).

### 7.6 Verification

- Table shows real jobs from the system
- Sorting works on all columns
- Filters work (search, domain, status, Apple toggle)
- Pagination works with 25+ jobs
- Apple rows are visually distinct (amber treatment)
- Action buttons trigger real launchctl operations and toast results

---

## Step 8: Embedded React SPA — Detail Panel

### 8.1 Slide-out panel structure

Port from prototype:
- Panel overlay + slide-in animation
- Header: status dot, label, action buttons (Start, Stop, Run Now, Reload), close X
- Tabs: Info, Logs, Edit Plist (in this order)
- `initialTab` prop for direct tab targeting from failed panel buttons

### 8.2 Info tab

- Info grid: Label, Status, Domain, Plist path, Schedule, Loaded, Enabled, Last Exit, Blame, Stdout path, Stderr path
- Action buttons: Enable/Disable toggle, Load/Unload, Export Plist, Delete Job
- Delete triggers confirmation dialog first, then backup + delete

### 8.3 Logs tab

- Tabbed: stderr, stdout, unified
- Fetch from `/api/jobs/{label}/logs/{type}`
- Auto-scroll / follow mode toggle
- Search within logs (client-side filter)
- Color-coded: error lines red, warning lines amber, timestamps gray

### 8.4 Edit Plist tab

- Fetch plist content from `/api/jobs/{label}/plist`
- Full textarea editor (monospace, syntax appropriate)
- "Modified" indicator when content changes
- Save button → `PUT /api/jobs/{label}/plist`
- Save & Reload button → save then reload
- Show validation errors if plist XML is malformed

### 8.5 Verification

- Click any job row → panel slides in with correct info
- Logs tab loads real log content
- Edit tab loads and saves real plist content
- Save & Reload actually reloads the job
- Delete backs up and removes the job

---

## Step 9: Embedded React SPA — Create Job Modal

### 9.1 Form step

Port from prototype:
- Label, Program, Arguments (multi-line)
- Domain dropdown
- Schedule section with type selector: None, Interval, Calendar, Watch Paths
  - Interval: seconds input with human-readable conversion
  - Calendar: Hour, Minute, Weekday pills (multi-select), Day of Month (clamped 1-31 with "Any" clear button)
  - Watch Paths: multi-line input
  - Live preview text
- Stdout/Stderr path inputs
- Working directory
- RunAtLoad / KeepAlive toggles

### 9.2 Preview step

- Generated plist XML preview
- Multi-weekday generates array of `StartCalendarInterval` dicts
- Back button to return to form

### 9.3 Create & Load

- POST to `/api/jobs` with form data
- Backend generates plist, writes file, loads job
- Toast success/error
- Close modal on success

### 9.4 Verification

- Create a test job through the UI
- Verify plist file appears in correct directory
- Verify job is loaded and visible in the table
- Verify schedule types generate correct plist XML

---

## Step 10: Embedded React SPA — Settings, Import/Export, Toasts, Keyboard Shortcuts

### 10.1 Settings modal

- Poll interval (seconds)
- Show Apple Jobs toggle
- Dark/Light mode toggle
- Confirm before destructive actions toggle
- Confirm before modifying Apple jobs toggle
- Keyboard shortcut reference table
- Persist settings to `/api/settings` → `config.json`

### 10.2 Import flow

- Import button in topbar
- File picker (HTML `<input type="file" accept=".plist">`)
- Read file content, POST to `/api/jobs/import`
- Show result toast

### 10.3 Export flow

- Export button in detail panel and row actions
- `GET /api/jobs/{label}/export` → trigger browser download
- Use `Content-Disposition: attachment; filename="{label}.plist"` header

### 10.4 Confirmation dialogs

- Delete: "Delete {label}? A backup will be saved to ~/.launchmaster/backups/"
- Unload running job: "This job is currently running. Unloading will stop it."
- Apple job modification: "This is an Apple system job. Modifying it may affect system stability."
- Controlled by settings toggles

### 10.5 Toast notifications

- Success (green), Error (red), Warning (amber)
- Auto-dismiss after 4 seconds
- Manual dismiss via X button
- Slide-in animation from right

### 10.6 Keyboard shortcuts

Global handler (skip when input/textarea focused):
- `n` → open Create Job modal
- `/` → focus search bar
- `Esc` → close panel/modal, or clear search if focused
- `?` → open Settings (shortcuts reference)

### 10.7 Verification

- Settings persist across page reloads
- Import a previously exported plist file
- Export downloads a valid plist file
- Confirmation dialogs appear for destructive actions
- Toasts show for all operations
- Keyboard shortcuts work

---

## Step 11: Testing

### 11.1 Create test infrastructure

Create `launchmaster/tests/` directory with:
- `conftest.py` — pytest fixtures, test plist creation/cleanup
- `test_discovery.py` — tests for plist scanning and state merging
- `test_control.py` — tests for launchctl operations (using a test job)
- `test_api.py` — FastAPI TestClient tests for all endpoints
- `test_schedule.py` — tests for schedule humanizer
- `test_plist.py` — tests for plist CRUD (create, save, validate, backup)

### 11.2 Test job fixture

Create a test plist `com.launchmaster.test-fixture` that:
- Runs a simple command (`/usr/bin/true` or `/bin/echo`)
- Has a known schedule, log paths, etc.
- Is created in `~/Library/LaunchAgents/` at test setup and removed at teardown

### 11.3 Key test scenarios

**Discovery:**
- Finds jobs in `~/Library/LaunchAgents/`
- Correctly categorizes domains
- Handles malformed plist gracefully
- Merges runtime state from launchctl

**Control:**
- Load/unload cycle
- Start/stop/reload cycle
- Enable/disable
- Run Now (kickstart)

**CRUD:**
- Create job generates valid plist XML
- Multi-weekday generates correct `StartCalendarInterval` array
- Delete creates backup before removing
- Export returns file content
- Import writes and loads

**Schedule humanizer:**
- Interval → "Every 5 minutes"
- Calendar single day → "Sundays at 6:00 AM"
- Calendar multi-day → "Mon, Wed, Fri at 9:00"
- WatchPaths → "Watching: ~/Downloads"
- KeepAlive → "Always running (KeepAlive)"

**API:**
- GET /api/jobs returns list
- POST control endpoints return success/error
- PUT plist validates XML before saving
- GET logs returns lines or graceful error
- WebSocket connection receives job updates

### 11.4 Verification

- Full test suite passes: `pytest tests/ -v`
- No test uses mocks for launchctl — these are integration tests against the real system
- Cleanup fixture removes all test artifacts

---

## Step 12: Documentation and Polish

### 12.1 README.md

- What it is, screenshot placeholder
- Installation: "copy the script, run it"
- Usage: CLI flags, keyboard shortcuts
- How it works: launchd overview, what each control action does
- Backup/restore workflow

### 12.2 Error handling audit

- All subprocess calls have timeouts
- All file operations handle permission errors
- WebSocket reconnects on disconnect
- API returns structured errors, never 500s

### 12.3 Security considerations

- Only binds to 127.0.0.1 by default
- Apple job modifications require explicit confirmation
- Backups before destructive operations
- No secrets in state files

---

## File Structure (Final)

```
launchmaster/
├── launchmaster              # Single executable script (~3000-4000 lines)
├── README.md
├── design/
│   └── ui_prototype.html     # Design prototype (already exists)
├── docs/
│   └── implementation_plan.md
└── tests/
    ├── conftest.py
    ├── test_discovery.py
    ├── test_control.py
    ├── test_api.py
    ├── test_schedule.py
    └── test_plist.py
```

Runtime:
```
~/.launchmaster/
├── config.json               # Settings (poll interval, UI prefs)
└── backups/                  # Auto-backups before delete
    └── com.example.tool.20260313_143201.plist

~/.launchmaster_venv/         # Private Python venv
```
