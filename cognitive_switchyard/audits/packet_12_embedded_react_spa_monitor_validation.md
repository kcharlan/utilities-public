# Packet 12 Validation Audit

## Result

- Status: `validated`
- Packet: `plans/packet_12_embedded_react_spa_monitor.md`
- Date: `2026-03-10`

## Scope Check

- Packet repair stayed inside the packet-12 implementation files: `cognitive_switchyard/server.py`, `cognitive_switchyard/html_template.py`, `tests/test_server.py`, and `tests/test_html_template.py`.
- Tracker and audit updates were applied as required by the validator task.
- The worktree contains unrelated modified files outside packet 12's allowed set, but they were not used as packet-12 implementation evidence and were not edited as part of this repair.

## Defects Found And Repaired

### 1. Embedded SPA template was not runnable

- Evidence:
  - `cognitive_switchyard/html_template.py` rendered literal double braces in CSS and JSX, for example `body {{` and `const {{ useEffect... }}`, which makes the served document invalid.
- Repair:
  - Rewrote the embedded HTML template so the CSS and React/Babel code render with valid single-brace syntax while preserving the required design-token block and pinned CDN imports.

### 2. Packet-11 REST/WS monitor flows were not actually wired

- Evidence:
  - The previous SPA shell never subscribed to slot log streams, never loaded the full task feed, never loaded task-detail logs, and did not expose setup preflight/intake actions even though packet 12 claims those views.
  - The start path forced `window.location.reload()`, which violated the packet's client-side SPA requirement.
- Repair:
  - Added REST-driven loading for dashboard/tasks/intake/preflight/task-detail logs.
  - Added WebSocket slot subscriptions for worker-card/task-detail log streaming.
  - Added client-side session controls, intake open/reveal actions, history purge controls, and settings save flow without full-page reloads.

### 3. Root bootstrap promoted history-only sessions into the monitor bootstrap

- Evidence:
  - `_select_bootstrap_session()` fell back to the first session even when only completed history sessions existed, which would incorrectly treat history as the current monitor session.
- Repair:
  - Restricted bootstrap session selection to `running`, `paused`, or `created` sessions only; otherwise `current_session` remains `null`.

## Test Coverage Added

- `tests/test_html_template.py`
  - Valid CSS/React single-brace syntax instead of literal doubled braces
  - No `window.location.reload()` in the SPA
  - Required REST/WS wiring for setup/monitor/log streaming flows
- `tests/test_server.py`
  - Root bootstrap leaves `current_session`, `dashboard`, and `intake` empty when only history sessions exist

## Validation Commands

```bash
.venv/bin/python -m py_compile cognitive_switchyard/html_template.py cognitive_switchyard/server.py
.venv/bin/python -m pytest tests/test_html_template.py tests/test_server.py -q
```

## Outcome

- Packet 12 acceptance criteria now have decisive packet-scope evidence.
- No concrete packet-12 defect remains after repair.
- `plans/packet_status.md` and `plans/packet_status.json` were updated to `validated`.
