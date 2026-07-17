from __future__ import annotations

from textwrap import dedent

from cognitive_switchyard.html_template import render_app_html


def test_render_app_html_pins_required_react18_tailwind_lucide_and_reactflow_cdns() -> None:
    html = render_app_html({"ok": True})

    assert "https://unpkg.com/react@18.3.1/umd/react.development.js" in html
    assert "https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js" in html
    assert "https://unpkg.com/@babel/standalone@7.28.4/babel.min.js" in html
    assert "https://unpkg.com/lucide@0.542.0/dist/umd/lucide.min.js" in html
    assert "https://unpkg.com/reactflow@11.11.4/dist/umd/index.js" in html
    assert "https://unpkg.com/reactflow@11.11.4/dist/style.css" in html


def test_render_app_html_includes_required_google_fonts_import_and_design_token_block() -> None:
    html = render_app_html({"ok": True})

    assert '<link rel="preconnect" href="https://fonts.googleapis.com">' in html
    assert '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' in html
    assert (
        '<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">'
        in html
    )
    assert (
        dedent(
            """
            :root {
              /* === Background === */
              --bg-base: #0f1117;           /* Main page background - very dark blue-gray */
              --bg-surface: #161922;        /* Card/panel backgrounds */
              --bg-surface-raised: #1c1f2e; /* Elevated surfaces (modals, dropdowns) */
              --bg-surface-hover: #232738;  /* Hover state on interactive surfaces */
              --bg-input: #0c0e14;          /* Input field backgrounds */
              --bg-log: #0a0c10;            /* Log viewer background (darkest) */

              /* === Text === */
              --text-primary: #e8eaed;      /* Primary text - slightly warm white */
              --text-secondary: #8b8fa3;    /* Secondary/dimmed text */
              --text-muted: #4a4e63;        /* Very dimmed text (idle labels, timestamps) */
              --text-inverse: #0f1117;      /* Text on bright backgrounds */

              /* === Status Colors === */
              --status-done: #34d399;       /* Green - completed/healthy */
              --status-active: #f59e0b;     /* Amber - in progress */
              --status-ready: #3b82f6;      /* Blue - queued/ready */
              --status-blocked: #ef4444;    /* Red - error/blocked */
              --status-staged: #a78bfa;     /* Purple - staged/planning */
              --status-idle: #374151;       /* Dark gray - idle/inactive */
              --status-review: #f97316;     /* Orange - needs human review */

              /* === Status Glows (for box-shadow) === */
              --glow-done: rgba(52, 211, 153, 0.15);
              --glow-active: rgba(245, 158, 11, 0.15);
              --glow-blocked: rgba(239, 68, 68, 0.25);
              --glow-ready: rgba(59, 130, 246, 0.1);

              /* === Borders === */
              --border-subtle: #1e2231;     /* Default card/panel borders */
              --border-medium: #2a2f42;     /* Stronger separation */
              --border-focus: #3b82f6;      /* Focus ring color */

              /* === Typography === */
              --font-display: 'Space Grotesk', 'DM Sans', sans-serif;    /* Headers, labels */
              --font-mono: 'JetBrains Mono', 'IBM Plex Mono', monospace; /* Data, logs, IDs */
              --font-body: 'DM Sans', 'Space Grotesk', sans-serif;       /* Body text */

              /* === Font Sizes === */
              --text-xs: 0.6875rem;    /* 11px - timestamps, fine print */
              --text-sm: 0.75rem;      /* 12px - secondary labels */
              --text-base: 0.8125rem;  /* 13px - body text (dense UI) */
              --text-md: 0.875rem;     /* 14px - primary labels */
              --text-lg: 1rem;         /* 16px - section headers */
              --text-xl: 1.25rem;      /* 20px - page headers */
              --text-2xl: 1.5rem;      /* 24px - view titles */

              /* === Spacing === */
              --space-1: 4px;
              --space-2: 8px;
              --space-3: 12px;
              --space-4: 16px;
              --space-5: 20px;
              --space-6: 24px;
              --space-8: 32px;

              /* === Border Radius === */
              --radius-sm: 4px;
              --radius-md: 6px;
              --radius-lg: 8px;
              --radius-xl: 12px;

              /* === Transitions === */
              --transition-fast: 150ms ease;
              --transition-base: 250ms ease;
              --transition-slow: 400ms ease;

              /* === Z-index layers === */
              --z-base: 0;
              --z-cards: 10;
              --z-sticky: 20;
              --z-overlay: 30;
              --z-modal: 40;
              --z-tooltip: 50;

              /* === Layout === */
              --topbar-height: 48px;
              --pipeline-strip-height: 44px;
              --worker-card-min-height: 220px;
              --log-tail-lines: 5;          /* Number of visible lines in worker card log tail */
              --sidebar-width: 280px;       /* For views that use sidebar layout */
            }
            """
        ).strip()
        in html
    )


def test_render_app_html_escapes_bootstrap_json_for_inline_use() -> None:
    html = render_app_html(
        {
            "danger": "</script><script>alert('xss')</script>",
            "ampersand": "A&B",
        }
    )

    assert "</script><script>alert('xss')</script>" not in html
    assert "\\u003c/script\\u003e\\u003cscript\\u003ealert('xss')\\u003c/script\\u003e" in html
    assert "A\\u0026B" in html


def test_render_app_html_uses_valid_single_brace_css_and_react_syntax() -> None:
    html = render_app_html({"ok": True})

    assert "body {" in html
    assert "const { useEffect, useMemo, useRef, useState } = React;" in html
    assert "body {{" not in html
    assert "const {{ useEffect, useMemo, useRef, useState }} = React;" not in html
    assert "window.location.reload" not in html


def test_render_app_html_wires_setup_monitor_and_log_stream_contracts() -> None:
    html = render_app_html({"ok": True})

    assert 'type: "subscribe_logs"' in html
    assert 'type: "unsubscribe_logs"' in html
    assert "/api/sessions/${sessionId}/dashboard" in html
    assert "/api/sessions/${sessionId}/tasks" in html
    assert "/api/sessions/${sessionId}/intake" in html
    assert "/api/sessions/${sessionId}/preflight" in html
    assert "/api/sessions/${currentSession.id}/tasks/${taskId}/log?offset=0&limit=400" in html
    assert "/api/sessions/${currentSession.id}/open-intake" in html
    assert "/api/sessions/${currentSession.id}/reveal-file?path=${encodeURIComponent(path)}" in html
    assert "Create Session" in html
    assert "Run Preflight" in html
    assert "Start Session" in html
    assert "Pause" in html
    assert "Resume" in html
    assert "Abort" in html


def test_history_view_opens_trimmed_completed_session_without_requesting_live_task_log_streams() -> None:
    html = render_app_html({"ok": True})

    assert 'async function loadHistorySession(sessionId)' in html
    assert 'requestJson(`/api/sessions/${sessionId}`)' in html
    assert 'requestJson(`/api/sessions/${sessionId}/tasks`)' in html
    assert 'setView("history")' in html
    assert 'await loadHistorySession(session.id);' in html
    assert 'await loadSessionData(session.id, { includePreflight: session.status === "created" });' not in html
    assert 'const protocol = window.location.protocol === "https:" ? "wss" : "ws";' in html


def test_history_view_renders_release_notes_panel_for_completed_session_detail() -> None:
    html = render_app_html({"ok": True})

    assert "Release Notes" in html
    assert "selectedSession?.release_notes?.content" in html
    assert "selectedSession.release_notes.content" in html


def test_pause_button_visible_for_all_active_statuses_not_gated_on_running_only() -> None:
    """Regression: pause button must show during planning/resolving, not just running."""
    html = render_app_html({"ok": True})

    # The pause condition must include planning and resolving, not just running
    assert (
        '["planning", "resolving", "running", "verifying", "auto_fixing"].includes(currentSession?.status)'
        in html
    )
    # The old gating condition must NOT appear
    assert 'currentSession?.status === "running"' not in html
    # The resume button must be gated on paused only (not verifying/auto_fixing)
    assert 'currentSession?.status === "paused"' in html


def test_verification_card_reads_auto_fix_max_attempts_from_nested_path() -> None:
    """Regression: effectiveConfig.auto_fix_max_attempts (flat) was undefined; must use nested path."""
    html = render_app_html({"ok": True})

    # Must use the nested read that matches to_dict()'s "auto_fix.max_attempts" structure
    assert "effectiveConfig.auto_fix?.max_attempts" in html
    # Must NOT use the flat key that evaluates to undefined
    assert "effectiveConfig.auto_fix_max_attempts" not in html


def test_task_detail_view_contains_timing_field_labels_and_elapsed_field_component() -> None:
    html = render_app_html({"ok": True})

    # Static labels rendered as JSX literals
    assert 'field-label">Started' in html
    assert 'field-label">Completed' in html
    # ElapsedField renders label dynamically; verify the string literals exist in the component
    assert '"Elapsed"' in html
    assert '"Duration"' in html
    # The ElapsedField component definition is present
    assert "function ElapsedField" in html


def test_task_row_renders_fta_badge_for_full_test_after_tasks() -> None:
    """Regression: task rows must display FTA badge when full_test_after is true."""
    html = render_app_html({"ok": True})

    # FTA badge text and its tooltip title attribute must appear in the task row rendering code
    assert ">FTA<" in html, "FTA badge text must be present in task row JSX"
    assert 'title="Full test after completion"' in html, (
        "FTA badge must have a descriptive title attribute for tooltip"
    )
    # Badge is conditional on task.full_test_after — the condition must be present
    assert "task.full_test_after" in html, (
        "FTA badge must be gated on task.full_test_after flag"
    )


def test_task_detail_view_shows_fta_badge_and_constraint_row() -> None:
    """Regression: detail view must show FTA badge near status and in constraints."""
    html = render_app_html({"ok": True})

    # FTA badge appears in the detail header (near status badge, inside TaskDetailView)
    # The task-list badge and detail badge both use the same title attribute
    assert 'title="Full test after completion"' in html

    # FULL_TEST_AFTER constraint row exists in the constraints section
    assert "FULL_TEST_AFTER:" in html, (
        "Constraints section must include FULL_TEST_AFTER alongside DEPENDS_ON and ANTI_AFFINITY"
    )
    assert "task.full_test_after" in html


def test_verification_countdown_uses_shared_reason_label_helper() -> None:
    """Regression: verification countdown must use verificationReasonLabel helper, not inline chain."""
    html = render_app_html({"ok": True})

    # The shared helper function must be defined
    assert "function verificationReasonLabel" in html, (
        "verificationReasonLabel helper must be defined as a standalone function"
    )
    # The countdown section must call it for the pending-state display (passing sessionStatus for phase-aware labels)
    assert "verificationReasonLabel(runtimeState.verification_reason, sessionStatus)" in html, (
        "Countdown section must call verificationReasonLabel with sessionStatus for phase-aware labels"
    )
    # The VerificationCard must also use it (no inline ternary chain left)
    assert "verificationReasonLabel(reason, sessionStatus)" in html, (
        "VerificationCard must call verificationReasonLabel with sessionStatus for phase-aware labels"
    )


def test_verification_reason_label_is_phase_aware() -> None:
    """Regression: verificationReasonLabel must return different labels for auto_fixing vs verifying."""
    html = render_app_html({"ok": True})

    # Function signature must accept sessionStatus parameter
    assert "function verificationReasonLabel(reason, sessionStatus)" in html, (
        "verificationReasonLabel must accept sessionStatus as second parameter"
    )
    # Auto-fix phase labels must be present in the template
    assert '"Auto-fixing verification failures"' in html, (
        'verification_failure during auto_fixing must produce "Auto-fixing verification failures"'
    )
    assert '"Auto-fixing task failure"' in html, (
        'task_failure/task_auto_fix during auto_fixing must produce "Auto-fixing task failure"'
    )
    # Verifying phase labels must be present in the template
    assert '"Re-verifying after auto-fix"' in html, (
        'verification_failure during verifying must produce "Re-verifying after auto-fix"'
    )
    assert '"Re-verifying after task fix"' in html, (
        'task_failure/task_auto_fix during verifying must produce "Re-verifying after task fix"'
    )
    # The old misleading static label must not appear
    assert '"Re-verifying after auto-fix attempt"' not in html, (
        'Old static label "Re-verifying after auto-fix attempt" must be replaced by phase-aware labels'
    )


def test_filter_log_line_helper_is_present_in_rendered_html() -> None:
    """Regression: filterLogLine helper must exist in the rendered HTML."""
    html = render_app_html({"ok": True})

    assert "function filterLogLine" in html, (
        "filterLogLine helper must be defined as a standalone function in the rendered HTML"
    )


def test_filter_log_line_old_inline_json_filter_is_gone() -> None:
    """Regression: PhaseActivityCard must use shared filterLogLine, not the old inline JSON filter."""
    html = render_app_html({"ok": True})

    # The old inline suppress-all pattern must be removed
    assert "try { JSON.parse(line); return false; }" not in html, (
        "Old inline JSON filter in PhaseActivityCard must be replaced by the shared filterLogLine helper"
    )


def test_task_logs_websocket_handler_stores_objects_with_line_and_ts_fields() -> None:
    """Regression: taskLogs WebSocket log_line handler must store {line, ts} objects, not bare strings."""
    html = render_app_html({"ok": True})

    # The handler must store an object with both line and ts fields from messagePayload.data
    assert "{ line: messagePayload.data.line, ts: messagePayload.data.timestamp || null }" in html, (
        "WebSocket log_line handler must store {line, ts} objects so timestamps can be rendered in TaskDetailView"
    )
    # The old pattern storing bare strings must be gone
    assert "[...(current[taskId] || []), messagePayload.data.line]" not in html, (
        "WebSocket log_line handler must not store bare strings — must store {line, ts} objects"
    )


def test_task_status_change_sse_handler_spreads_started_at_and_completed_at() -> None:
    """Regression: task_status_change SSE handler must spread started_at and completed_at
    from payload into task state so TaskRowElapsed ticks for tasks activated after initial fetch."""
    html = render_app_html({"ok": True})

    assert "started_at: messagePayload.data.started_at ?? task.started_at" in html, (
        "task_status_change handler must spread started_at from payload so TaskRowElapsed activates its interval"
    )
    assert "completed_at: messagePayload.data.completed_at ?? task.completed_at" in html, (
        "task_status_change handler must spread completed_at from payload"
    )


def test_task_logs_rest_fetch_stores_objects_with_ts_null() -> None:
    """Regression: REST log fetch must wrap splitLogContent strings in {line, ts} objects using mtime_iso fallback."""
    html = render_app_html({"ok": True})

    # The REST path must map strings to objects with ts from mtime_iso (fallback to null)
    assert "splitLogContent(logPayload.content).map((line) => ({ line, ts: logPayload.mtime_iso || null }))" in html, (
        "REST log fetch must produce {line, ts: logPayload.mtime_iso || null} objects to match the taskLogs shape"
    )


def test_task_detail_view_renders_timestamp_prefix_on_log_lines() -> None:
    """Regression: TaskDetailView log panel must render HH:MM:SS timestamp prefix from entry.ts."""
    html = render_app_html({"ok": True})

    # The timestamp span must be rendered conditionally on entry.ts
    assert "entry.ts ? <span" in html, (
        "TaskDetailView must render a timestamp span when entry.ts is present"
    )
    # The timestamp must be sliced to HH:MM:SS (chars 11-19 of an ISO 8601 string)
    assert "entry.ts.slice(11, 19)" in html, (
        "Timestamp must be extracted via .slice(11, 19) from ISO 8601 string"
    )
    # isProgressLine and isProblemLine must receive entry.line (string), not the entry object
    assert "isProgressLine(entry.line)" in html, (
        "isProgressLine must receive entry.line string, not the entry object"
    )
    assert "isProblemLine(entry.line)" in html, (
        "isProblemLine must receive entry.line string, not the entry object"
    )


def test_task_detail_view_accepts_phase_log_props() -> None:
    """Regression: TaskDetailView must accept taskLogs, sessionStatus, and runtimeState props."""
    html = render_app_html({"ok": True})

    # Function signature must include the new props
    assert "function TaskDetailView({ task, currentSession, logLines, taskLogs, sessionStatus, runtimeState, searchValue, onSearchChange, onBack, onMoveTask, onRevealFile })" in html, (
        "TaskDetailView must accept taskLogs, sessionStatus, runtimeState, onMoveTask, and onRevealFile props"
    )


def test_task_detail_view_computes_effective_log_lines_with_phase_separator() -> None:
    """Regression: when auto_fixing and isTargetTask, effectiveLogLines must append phase lines after separator."""
    html = render_app_html({"ok": True})

    # The effectiveLogLines memo must be present
    assert "effectiveLogLines" in html, (
        "TaskDetailView must compute effectiveLogLines combining base and phase logs"
    )
    # The phase key selection logic must be present
    assert '__phase_auto_fix__' in html, (
        "effectiveLogLines must select __phase_auto_fix__ key during auto_fixing"
    )
    assert '__phase_verification__' in html, (
        "effectiveLogLines must select __phase_verification__ key during verifying"
    )
    # The separator strings must be present
    assert '"─── Auto-fix output ───"' in html, (
        "effectiveLogLines must append an auto-fix separator line before phase logs"
    )
    assert '"─── Verification output ───"' in html, (
        "effectiveLogLines must append a verification separator line before phase logs"
    )
    # The render must use effectiveLogLines, not raw logLines
    assert "effectiveLogLines.length ? effectiveLogLines" in html, (
        "TaskDetailView log panel must render effectiveLogLines, not raw logLines"
    )


def test_task_detail_view_uses_state_aware_empty_log_messages() -> None:
    html = render_app_html({"ok": True})

    assert 'task.history_source === "summary"' in html, (
        "TaskDetailView must distinguish summary/history tasks when choosing an empty-log message"
    )
    assert 'task.status === "active"' in html, (
        "TaskDetailView must preserve the live-subscription placeholder for active tasks"
    )
    assert 'task.status === "done" || task.status === "blocked"' in html, (
        "TaskDetailView must surface a retained-log message for completed or blocked live tasks"
    )
    assert "Task logs were not retained for this completed session." in html, (
        "Summary tasks must show an explicit retained-history message"
    )
    assert "No retained log found for this task." in html, (
        "Completed or blocked live tasks must show an explicit missing-log message"
    )
    assert "No log yet. Logs appear after the task starts." in html, (
        "Pre-start task states must show a no-log-yet message"
    )


def test_task_detail_view_separator_line_styled_distinctly() -> None:
    """Regression: separator lines must have a distinct CSS class."""
    html = render_app_html({"ok": True})

    # The separator CSS class must be applied when line starts with ───
    assert 'entry.line.startsWith("───") ? "separator"' in html, (
        "Log lines starting with ─── must receive the 'separator' CSS class"
    )
    # The CSS rule for separator must exist
    assert ".log-line.separator" in html, (
        ".log-line.separator CSS rule must be defined"
    )


def test_task_detail_view_passes_phase_props_at_call_site() -> None:
    """Regression: TaskDetailView call site must forward taskLogs, sessionStatus, and runtimeState."""
    html = render_app_html({"ok": True})

    # The call site must pass all three new props
    assert "taskLogs={taskLogs}" in html, (
        "TaskDetailView call site must pass taskLogs prop"
    )
    assert "sessionStatus={appSessionStatus}" in html, (
        "TaskDetailView call site must pass sessionStatus as appSessionStatus"
    )
    assert "runtimeState={appRuntimeState}" in html, (
        "TaskDetailView call site must pass runtimeState as appRuntimeState"
    )


def test_app_level_session_status_and_runtime_state_computed() -> None:
    """Regression: App must compute appSessionStatus and appRuntimeState for passing to TaskDetailView."""
    html = render_app_html({"ok": True})

    assert 'const appSessionStatus = dashboard?.session?.status || currentSession?.status || "created"' in html, (
        "App must compute appSessionStatus from dashboard or currentSession"
    )
    assert "const appRuntimeState = dashboard?.runtime_state || {}" in html, (
        "App must compute appRuntimeState from dashboard.runtime_state"
    )


def test_render_app_html_includes_last_activity_indicator_component() -> None:
    """Regression: Plan 006 — worker cards must include LastActivityIndicator component."""
    html = render_app_html({"ok": True})

    assert "function LastActivityIndicator(" in html, (
        "LastActivityIndicator component must be defined in the app HTML"
    )
    assert "last_activity_ago" in html, (
        "last_activity_ago field must be referenced in the app HTML"
    )
    assert "task_idle_limit" in html, (
        "task_idle_limit field must be referenced in the app HTML"
    )


def test_render_app_html_includes_health_summary_bar_component() -> None:
    """Regression: Plan 006 — monitor header must include HealthSummaryBar component."""
    html = render_app_html({"ok": True})

    assert "function HealthSummaryBar(" in html, (
        "HealthSummaryBar component must be defined in the app HTML"
    )
    assert "<HealthSummaryBar" in html, (
        "HealthSummaryBar must be rendered in MonitorView"
    )


def test_render_app_html_includes_task_row_elapsed_component() -> None:
    """Regression: Plan 006 — task feed rows must use TaskRowElapsed component."""
    html = render_app_html({"ok": True})

    assert "function TaskRowElapsed(" in html, (
        "TaskRowElapsed component must be defined in the app HTML"
    )
    assert "<TaskRowElapsed" in html, (
        "TaskRowElapsed must be rendered in the task feed"
    )


def test_render_app_html_worker_card_warning_state_logic() -> None:
    """Regression: Plan 006 — worker cards must compute isIdleWarning and apply warning stateClass."""
    html = render_app_html({"ok": True})

    assert "isIdleWarning" in html, (
        "isIdleWarning must be computed in worker card rendering"
    )
    assert '"worker-card warning"' in html, (
        "Worker card must use 'worker-card warning' class when idle warning is active"
    )


def test_idle_indicator_uses_dynamic_thresholds() -> None:
    """Regression: Plan 002 — LastActivityIndicator must use dynamic thirds from task_idle_limit."""
    html = render_app_html({"ok": True})

    # Dynamic threshold divisions must be present
    assert "limit / 3" in html, (
        "LastActivityIndicator must compute thirdLow as limit / 3"
    )
    assert "(limit * 2) / 3" in html, (
        "LastActivityIndicator must compute thirdHigh as (limit * 2) / 3"
    )

    # Old hardcoded thresholds must be gone from the component
    assert "ago < 60" not in html, (
        "Hardcoded 60s threshold must not appear in the rendered HTML"
    )
    assert "ago < 300" not in html, (
        "Hardcoded 300s threshold must not appear in the rendered HTML"
    )

    # New keyframe animation names must be present
    assert "pulse-idle-amber" in html, (
        "@keyframes pulse-idle-amber must be defined and referenced in the rendered HTML"
    )
    assert "pulse-idle-red" in html, (
        "@keyframes pulse-idle-red must be defined and referenced in the rendered HTML"
    )
    assert "@keyframes pulse-idle-amber" in html, (
        "@keyframes pulse-idle-amber CSS rule must appear in the rendered HTML"
    )
    assert "@keyframes pulse-idle-red" in html, (
        "@keyframes pulse-idle-red CSS rule must appear in the rendered HTML"
    )

    # Amber tier must use --status-review
    assert "--status-review" in html, (
        "Amber idle tier must use var(--status-review) color"
    )

    # Red tier must use fontWeight: 600
    assert "fontWeight: 600" in html, (
        "Red idle tier must use fontWeight: 600"
    )


def test_idle_tracked_server_side_not_client() -> None:
    """Regression: idle tracking uses server-side last_activity_ago from state_update
    snapshots, not client-side resets.  The client must NOT set last_activity_ago: 0
    in log_line or progress_detail handlers — that fights with the server's value."""
    html = render_app_html({"ok": True})

    # Client-side handlers should NOT contain last_activity_ago: 0 overrides.
    # The server computes the correct value and sends it via state_update.
    assert "last_activity_ago: 0" not in html, (
        "Client must not reset last_activity_ago — server tracks idle state"
    )


def test_idle_warning_uses_two_thirds_threshold() -> None:
    """Regression: Plan 002 — isIdleWarning must use ⅔ threshold, not 80%."""
    html = render_app_html({"ok": True})

    assert "task_idle_limit * 0.8" not in html, (
        "isIdleWarning must not use the old 0.8 (80%) threshold"
    )
    assert "(worker.task_idle_limit * 2) / 3" in html, (
        "isIdleWarning must use the (worker.task_idle_limit * 2) / 3 threshold"
    )
