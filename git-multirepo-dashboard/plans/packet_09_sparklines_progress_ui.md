# Packet 09: Sparklines & Scan Progress UI

## Why This Packet Exists

The fleet overview cards currently show empty sparklines and the "Full Scan" button is a no-op. This packet populates sparkline data from `daily_stats` and wires the existing SSE scan infrastructure (packet 08) to visible progress indicators.

## Scope

- **Backend: Sparkline data population** — `compute_sparklines(db)` function that bulk-queries `daily_stats` for 13-week commit counts per repo, wired into `GET /api/fleet` response (replacing the `sparkline: []` placeholder).
- **Frontend: "Full Scan" button wiring** — Click triggers `POST /api/fleet/scan`, opens `EventSource` to SSE endpoint, manages scan lifecycle state at `App` level.
- **Frontend: ScanProgressBar component** — 3px slim bar below nav tabs, full width, animated fill proportional to scan progress.
- **Frontend: ScanToast component** — Fixed-position floating notification (bottom-right), shows current repo name, mini progress bar, repo count. Auto-dismisses 2s after completion.
- **Frontend: Fleet data refetch** — On scan completion, refetch `GET /api/fleet` to refresh cards with updated data.

## Non-Goals

- "Scan Dir" button wiring (directory input dialog is a separate concern)
- Project detail view (packet 10)
- Error states for failed scans (packet 22) — this packet handles the happy path only
- Dependency scan progress (type="deps" remains a no-op per packet 08)
- Analytics tab (packets 18–21)

## Relevant Design Doc Sections

- §5.4 (lines 891–897): Hover sparkline overlay spec (13-week commit counts, Recharts AreaChart)
- §5.7 (lines 1115–1133): Full scan progress bar and toast spec (dimensions, colors, animations, content)
- §4 (lines 485–496): SSE progress endpoint response shape
- §4 (lines 463): Sparkline data definition (13 integers, index 0 = oldest week)
- §6 (lines 1193–1208): Full scan flow (button click → POST → SSE → refetch)

## Allowed Files

- `git_dashboard.py`
- `tests/test_sparklines_progress.py` (new)

## Tests to Write First

### Backend tests

1. **`test_compute_sparklines_empty`** — No `daily_stats` rows → returns empty dict (or all repos get `[0]*13`).

2. **`test_compute_sparklines_single_repo`** — Insert `daily_stats` rows for one repo spanning 3 weeks. Call `compute_sparklines(db)`. Verify: result has repo_id key, value is list of exactly 13 ints, weeks with data have correct commit sums, weeks without data are 0.

3. **`test_compute_sparklines_multiple_repos`** — Insert rows for 2 repos with different date ranges. Verify each repo gets its own 13-element array with independent data.

4. **`test_compute_sparklines_old_data_excluded`** — Insert rows older than 91 days. Verify they do not appear in sparkline arrays.

5. **`test_fleet_endpoint_sparkline_populated`** — Register a repo, insert `daily_stats` for it, call `GET /api/fleet`. Verify the repo's `sparkline` field is a list of 13 integers (not empty `[]`).

### Frontend / template tests

6. **`test_scan_progress_bar_component_exists`** — `HTML_TEMPLATE` contains a component named `ScanProgressBar`.

7. **`test_scan_toast_component_exists`** — `HTML_TEMPLATE` contains a component named `ScanToast`.

8. **`test_full_scan_button_wired`** — The "Full Scan" button's `onClick` is not `() => {}` (empty no-op). It should reference a scan-triggering function.

9. **`test_scan_progress_uses_sse_endpoint`** — `HTML_TEMPLATE` contains reference to `/api/fleet/scan/` (the SSE endpoint path) and `EventSource`.

10. **`test_fleet_refetch_on_completion`** — `HTML_TEMPLATE` contains logic to refetch `/api/fleet` after scan completion (search for fetch call to `/api/fleet` in scan completion handler).

## Implementation Notes

### Sparkline computation

```python
async def compute_sparklines(db) -> dict:
    """Bulk-compute 13-week commit sparklines for all repos."""
    import datetime
    today = datetime.date.today()
    # 13 weeks = 91 days. Align to Monday of the oldest week.
    start = today - datetime.timedelta(days=90)  # 91-day window (today inclusive)

    cursor = await db.execute(
        "SELECT repo_id, date, commits FROM daily_stats WHERE date >= ?",
        (start.isoformat(),)
    )
    rows = await cursor.fetchall()

    sparklines = {}
    for repo_id, date_str, commits in rows:
        d = datetime.date.fromisoformat(date_str)
        week_idx = min((d - start).days // 7, 12)
        if week_idx < 0:
            continue
        if repo_id not in sparklines:
            sparklines[repo_id] = [0] * 13
        sparklines[repo_id][week_idx] += commits

    return sparklines
```

Wire into the fleet endpoint: call `compute_sparklines(db)` once, then for each repo, set `sparkline = sparklines.get(repo_id, [0]*13)`.

### SparklineOverlay data format

The `SparklineOverlay` component already exists from packet 05. Verify it transforms the integer array into Recharts data format (e.g., `sparkline.map((v, i) => ({week: i, commits: v}))`). If it already does this, no changes needed. If not, adjust the mapping.

### Scan state architecture

Scan state must live at the `App` component level because three separate UI areas consume it:
- **Header**: "Full Scan" button (trigger + disable while scanning)
- **Below NavTabs**: ScanProgressBar (reads progress/total)
- **Fixed overlay**: ScanToast (reads progress/total, current repo, status)

State shape:
```javascript
const [scanState, setScanState] = useState({
  active: false,
  scanId: null,
  progress: 0,
  total: 0,
  currentRepo: '',
  status: 'idle'  // 'idle' | 'scanning' | 'completed' | 'failed'
});
```

### Full Scan button handler

```javascript
async function handleFullScan() {
  if (scanState.active) return;
  const res = await fetch('/api/fleet/scan', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({type: 'full'})
  });
  if (res.status === 409) return; // Already scanning
  const {scan_id} = await res.json();
  setScanState({active: true, scanId: scan_id, progress: 0, total: 0, currentRepo: '', status: 'scanning'});

  const es = new EventSource(`/api/fleet/scan/${scan_id}/progress`);
  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    setScanState(prev => ({...prev, ...data}));
    if (data.status === 'completed' || data.status === 'failed') {
      es.close();
      // Refetch fleet data
      setTimeout(() => setScanState({active: false, scanId: null, progress: 0, total: 0, currentRepo: '', status: 'idle'}), 2000);
    }
  };
}
```

### ScanProgressBar

Renders only when `scanState.active || scanState.status === 'completed'`. Positioned between NavTabs and content. Height 3px. Background `var(--border-default)`, fill `var(--accent-blue)`. On completion, fill turns `var(--status-green)`.

### ScanToast

Renders only when `scanState.active || scanState.status === 'completed'`. Fixed position `bottom: 24px; right: 24px`. 320px wide. Enters with `translateX(100%) → translateX(0)` animation. Shows:
- "Scanning..." header (or "Scan complete")
- Current repo name in mono font
- Mini progress bar (4px) + "N / M" count
- Auto-dismisses after 2s on completion (slide out to right)

Use CSS `@keyframes` for enter/exit animations. Track a `visible` state that transitions after completion timeout.

## Acceptance Criteria

1. `compute_sparklines(db)` returns a dict mapping repo_id to a 13-element list of integers.
2. `GET /api/fleet` returns `sparkline` as a 13-element list of integers for each repo (not `[]`).
3. Repos with no `daily_stats` data get `[0, 0, ..., 0]` (13 zeros) as their sparkline.
4. Sparkline data older than 91 days is excluded.
5. `SparklineOverlay` renders visible bar chart data on card hover when sparkline has non-zero values.
6. Clicking "Full Scan" sends `POST /api/fleet/scan` with `{"type": "full"}`.
7. After POST succeeds, an `EventSource` connection opens to the SSE progress endpoint.
8. `ScanProgressBar` appears below nav tabs during scan, width proportional to `progress/total`.
9. `ScanToast` appears at bottom-right during scan, shows current repo name and progress count.
10. On scan completion, progress bar fills to 100% and turns green.
11. On scan completion, toast text changes to "Scan complete" and auto-dismisses after ~2 seconds.
12. On scan completion (or shortly after), `GET /api/fleet` is refetched to refresh the fleet overview.
13. "Full Scan" button is disabled (or no-ops) while a scan is active.
14. All new tests pass. All existing 154 tests still pass (no regressions).

## Validation Focus Areas

- Verify sparkline data is computed correctly by inserting known daily_stats and checking the 13-element array math (week boundaries, oldest-first ordering).
- Verify SSE connection lifecycle: opens on scan start, receives events, closes on completion/failure.
- Verify toast auto-dismiss timing (should disappear ~2s after completion, not instantly).
- Verify fleet data refreshes after scan (cards should show updated commit counts, sparklines).
- Check that the "Full Scan" button correctly handles the 409 (already scanning) case by not opening a second EventSource.
