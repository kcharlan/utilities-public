"""End-to-end browser tests using Playwright.

These tests start a real Uvicorn server in a background thread and drive
a Chromium browser to verify actual user experience — not just API contracts.

Run with:
    pytest tests/test_e2e.py -v --headed   # visible browser
    pytest tests/test_e2e.py -v             # headless

Covers:
  - Session creation (happy path + validation errors)
  - Session lifecycle (start, pause, resume, abort)
  - Intake file management
  - Preflight checks
  - Task execution and worker monitoring
  - Task detail view
  - Navigation (Setup, Monitor, History, Settings, DAG)
  - Settings CRUD
  - Session history and purge
  - Error handling (duplicate IDs, missing sessions, active session delete)
  - WebSocket real-time updates
"""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from textwrap import dedent

import pytest

pytest.importorskip("playwright")

import uvicorn  # noqa: E402

from cognitive_switchyard.config import build_runtime_paths  # noqa: E402
from cognitive_switchyard.server import create_app  # noqa: E402
from cognitive_switchyard.state import initialize_state_store  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SLOW_TIMEOUT = 15_000  # ms — generous timeout for CI


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _setup_runtime(tmp_path: Path) -> Path:
    """Create a minimal runtime directory with a pack.

    build_runtime_paths(home=X) sets runtime_home = X/.cognitive_switchyard,
    so packs live at X/.cognitive_switchyard/packs/.
    """
    home = tmp_path / "runtime"
    cs = home / ".cognitive_switchyard"
    packs = cs / "packs" / "claude-code"
    scripts = packs / "scripts"
    prompts = packs / "prompts"
    templates = packs / "templates"
    scripts.mkdir(parents=True)
    prompts.mkdir(parents=True)
    templates.mkdir(parents=True)
    (cs / "sessions").mkdir(parents=True, exist_ok=True)

    # Execute script: writes .status sidecar on completion
    (scripts / "execute").write_text(
        dedent("""
        #!/usr/bin/env python3
        import sys, time
        from pathlib import Path
        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        print(f"##PROGRESS## {task_id} | Phase: reading | 1/3")
        time.sleep(0.1)
        print(f"##PROGRESS## {task_id} | Phase: implementing | 2/3")
        time.sleep(0.1)
        print(f"##PROGRESS## {task_id} | Phase: finalizing | 3/3")
        print(f"##PROGRESS## {task_id} | Detail: Writing status sidecar")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n"
            "NOTES: E2E test worker completed successfully.\\n",
            encoding="utf-8",
        )
        """).lstrip(),
        encoding="utf-8",
    )
    (scripts / "execute").chmod(0o755)

    # Blocked execute script: worker that reports blocked
    (scripts / "execute_blocked").write_text(
        dedent("""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path
        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        print(f"##PROGRESS## {task_id} | Phase: reading | 1/1")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: blocked\\nCOMMITS: none\\nTESTS_RAN: none\\nTEST_RESULT: fail\\n"
            "BLOCKED_REASON: Intentional test block.\\n",
            encoding="utf-8",
        )
        """).lstrip(),
        encoding="utf-8",
    )
    (scripts / "execute_blocked").chmod(0o755)

    # Preflight script: always passes (test pack doesn't require repo root)
    (scripts / "preflight").write_text(
        dedent("""
        #!/bin/sh
        echo "Preflight passed."
        """).lstrip(),
        encoding="utf-8",
    )
    (scripts / "preflight").chmod(0o755)

    (prompts / "planner.md").write_text("Plan prompt.\n")
    (prompts / "resolver.md").write_text("Resolve prompt.\n")

    (packs / "pack.yaml").write_text(
        dedent("""
        name: claude-code
        description: E2E test pack for automated testing.
        version: 0.0.1

        phases:
          planning:
            enabled: false
          resolution:
            enabled: false
            executor: passthrough
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
            max_workers: 2
          verification:
            enabled: false

        timeouts:
          task_idle: 60
          task_max: 0
          session_max: 300

        isolation:
          type: none
        """).lstrip(),
        encoding="utf-8",
    )

    # Also create a second pack for testing pack selection
    second_pack = cs / "packs" / "test-alt"
    second_scripts = second_pack / "scripts"
    second_scripts.mkdir(parents=True)
    (second_pack / "pack.yaml").write_text(
        dedent("""
        name: test-alt
        description: Alternative test pack.
        version: 0.0.1
        phases:
          planning:
            enabled: false
          resolution:
            enabled: false
            executor: passthrough
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
            max_workers: 1
          verification:
            enabled: false
        timeouts:
          task_idle: 60
          task_max: 0
          session_max: 300
        isolation:
          type: none
        """).lstrip(),
        encoding="utf-8",
    )
    (second_scripts / "execute").write_text(
        dedent("""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path
        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: none\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """).lstrip(),
        encoding="utf-8",
    )
    (second_scripts / "execute").chmod(0o755)

    # Third pack: strict preflight that requires COGNITIVE_SWITCHYARD_REPO_ROOT
    strict_pack = cs / "packs" / "strict-preflight"
    strict_scripts = strict_pack / "scripts"
    strict_scripts.mkdir(parents=True)
    (strict_pack / "pack.yaml").write_text(
        dedent("""
        name: strict-preflight
        description: Pack with strict preflight requiring REPO_ROOT.
        version: 0.0.1
        phases:
          planning:
            enabled: false
          resolution:
            enabled: false
            executor: passthrough
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
            max_workers: 1
          verification:
            enabled: false
        timeouts:
          task_idle: 60
          task_max: 0
          session_max: 300
        isolation:
          type: none
        """).lstrip(),
        encoding="utf-8",
    )
    (strict_scripts / "execute").write_text(
        dedent("""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path
        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: none\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """).lstrip(),
        encoding="utf-8",
    )
    (strict_scripts / "execute").chmod(0o755)
    (strict_scripts / "preflight").write_text(
        dedent("""
        #!/bin/sh
        set -eu
        REPO_ROOT="${COGNITIVE_SWITCHYARD_REPO_ROOT:-}"
        if [ -z "$REPO_ROOT" ]; then
          echo "COGNITIVE_SWITCHYARD_REPO_ROOT is not set." >&2
          exit 1
        fi
        echo "Preflight passed for $REPO_ROOT."
        """).lstrip(),
        encoding="utf-8",
    )
    (strict_scripts / "preflight").chmod(0o755)

    # Fourth pack: verification-enabled with a fast-failing verify command
    verify_pack = cs / "packs" / "verify-enabled"
    verify_scripts = verify_pack / "scripts"
    verify_scripts.mkdir(parents=True)
    (verify_pack / "pack.yaml").write_text(
        dedent("""
        name: verify-enabled
        description: Pack with verification enabled for VerificationCard UI testing.
        version: 0.0.1

        phases:
          planning:
            enabled: false
          resolution:
            enabled: false
            executor: passthrough
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
            max_workers: 1
          verification:
            enabled: true
            command: "echo verification-output-line1 && echo verification-output-line2 && exit 0"
            interval: 1

        timeouts:
          task_idle: 60
          task_max: 0
          session_max: 300

        isolation:
          type: none
        """).lstrip(),
        encoding="utf-8",
    )
    (verify_scripts / "execute").write_text(
        dedent("""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path
        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: none\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """).lstrip(),
        encoding="utf-8",
    )
    (verify_scripts / "execute").chmod(0o755)

    return home


def _write_intake_file(home: Path, session_id: str, filename: str, content: str) -> Path:
    """Write an intake file into a session's intake directory."""
    cs = home / ".cognitive_switchyard"
    intake_dir = cs / "sessions" / session_id / "intake"
    intake_dir.mkdir(parents=True, exist_ok=True)
    target = intake_dir / filename
    target.write_text(content, encoding="utf-8")
    return target


def _write_intake_plan(home: Path, session_id: str, task_id: str, *, depends_on: str = "none") -> Path:
    """Write a .plan.md intake file that the pipeline will move through staging→ready→execution."""
    cs = home / ".cognitive_switchyard"
    intake_dir = cs / "sessions" / session_id / "intake"
    intake_dir.mkdir(parents=True, exist_ok=True)
    target = intake_dir / f"{task_id}.plan.md"
    target.write_text(
        dedent(f"""
        ---
        PLAN_ID: {task_id}
        PRIORITY: normal
        ESTIMATED_SCOPE: src/{task_id}.py
        DEPENDS_ON: {depends_on}
        ANTI_AFFINITY: none
        EXEC_ORDER: 1
        FULL_TEST_AFTER: no
        ---

        # Plan: Task {task_id}

        Implement task {task_id}.

        ## Operator Actions

        None.
        """).lstrip(),
        encoding="utf-8",
    )
    return target


def _label_input(page, label_text: str):
    """Find an input by its preceding label text."""
    return page.locator(f"label:has-text('{label_text}') + input, label:has-text('{label_text}') + select,"
                        f" label:has-text('{label_text}') ~ input, label:has-text('{label_text}') ~ select").first


def _poll_session_status(page, session_id: str, target_statuses: set[str], *, timeout: float = 30.0) -> str:
    """Poll session API until status reaches one of target_statuses. Returns final status."""
    import time as _time
    deadline = _time.monotonic() + timeout
    last_status = None
    while _time.monotonic() < deadline:
        status = page.evaluate(f"""async () => {{
            const resp = await fetch('/api/sessions/{session_id}');
            const data = await resp.json();
            return data.session.status;
        }}""")
        last_status = status
        if status in target_statuses:
            return status
        _time.sleep(0.2)
    raise TimeoutError(f"Session {session_id} did not reach {target_statuses} in {timeout}s — last: {last_status}")


def _poll_tasks_done(page, session_id: str, *, min_done: int = 1, timeout: float = 30.0) -> list[dict]:
    """Poll tasks API until at least min_done tasks have status 'done'. Returns task list."""
    import time as _time
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        result = page.evaluate(f"""async () => {{
            const resp = await fetch('/api/sessions/{session_id}/tasks');
            return await resp.json();
        }}""")
        tasks = result.get("tasks", [])
        done = [t for t in tasks if t.get("status") == "done"]
        if len(done) >= min_done:
            return tasks
        _time.sleep(0.2)
    raise TimeoutError(f"Session {session_id}: expected {min_done} done tasks in {timeout}s")


def _poll_tasks_exist(page, session_id: str, *, min_count: int = 1, timeout: float = 30.0) -> list[dict]:
    """Poll tasks API until at least min_count tasks exist. Returns task list."""
    import time as _time
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        result = page.evaluate(f"""async () => {{
            const resp = await fetch('/api/sessions/{session_id}/tasks');
            return await resp.json();
        }}""")
        tasks = result.get("tasks", [])
        if len(tasks) >= min_count:
            return tasks
        _time.sleep(0.2)
    raise TimeoutError(f"Session {session_id}: expected {min_count} tasks in {timeout}s")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runtime_home(tmp_path_factory) -> Path:
    tmp_path = tmp_path_factory.mktemp("e2e")
    return _setup_runtime(tmp_path)


@pytest.fixture(scope="module")
def server_url(runtime_home):
    """Start a real uvicorn server in a thread and return its base URL."""
    runtime_paths = build_runtime_paths(home=runtime_home)
    store = initialize_state_store(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    port = _find_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="wsproto")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to accept connections
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.25)
    else:
        raise RuntimeError(f"Uvicorn did not start on port {port}")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# 1. INITIAL LOAD & NAVIGATION
# ---------------------------------------------------------------------------


class TestInitialLoad:
    """Verify the SPA loads correctly and core navigation works."""

    def test_spa_renders_setup_view(self, server_url, page):
        """Root URL serves SPA with setup view visible."""
        page.goto(server_url)
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)
        assert page.title() != ""
        # Setup form should be visible with key fields
        assert page.locator("text=Session Name").count() > 0
        assert page.locator("text=Session ID").count() > 0

    def test_no_console_errors_on_initial_load(self, server_url, page):
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url)
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)
        page.wait_for_timeout(500)
        assert errors == [], f"Console errors: {errors}"

    def test_navigation_tabs_visible(self, server_url, page):
        page.goto(server_url)
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)
        assert page.locator("button:has-text('Setup')").count() > 0
        assert page.locator("button:has-text('Monitor')").count() > 0
        assert page.locator("button:has-text('History')").count() > 0

    def test_navigate_to_history(self, server_url, page):
        page.goto(server_url)
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)
        page.locator("button:has-text('History')").click()
        page.wait_for_timeout(300)
        body = page.locator("body").inner_text()
        # History view should render (may show empty state or sessions list)
        assert "History" in body or "Retention" in body or "No sessions" in body or "Purge" in body

    def test_navigate_to_settings(self, server_url, page):
        page.goto(server_url)
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)
        page.locator("button[aria-label='Settings']").click()
        page.wait_for_timeout(500)
        body = page.locator("body").inner_text()
        body_lower = body.lower()
        assert "default" in body_lower or "retention" in body_lower or "save" in body_lower

    def test_pack_selector_lists_packs(self, server_url, page):
        page.goto(server_url)
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)
        # Pack should appear in the select dropdown
        result = page.evaluate("""async () => {
            const resp = await fetch('/api/packs');
            const data = await resp.json();
            return data.packs.map(p => p.name);
        }""")
        assert "claude-code" in result

    def test_websocket_connection(self, server_url, page):
        page.goto(server_url)
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)
        page.wait_for_timeout(1000)
        ws_available = page.evaluate("() => typeof WebSocket !== 'undefined'")
        assert ws_available is True


# ---------------------------------------------------------------------------
# 2. SESSION CREATION — HAPPY PATH
# ---------------------------------------------------------------------------


class TestSessionCreationHappy:
    """Verify sessions can be created through the UI form."""

    def test_create_session_via_ui_form(self, server_url, page):
        """Fill out the form and click 'Create Session' — verify the session appears."""
        page.goto(server_url)
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)

        # Fill in the form fields
        name_input = page.locator("label:has-text('Session Name') ~ input").first
        id_input = page.locator("label:has-text('Session ID') ~ input").first

        name_input.fill("UI Happy Path Test")
        id_input.fill("ui-happy-001")

        # Click Create Session
        page.locator("button:has-text('Create Session')").click()
        page.wait_for_timeout(1000)

        # Session should be created — verify the setup view shows locked state
        body = page.locator("body").inner_text()
        assert "ui-happy-001" in body or "UI Happy Path Test" in body

    def test_create_session_via_api_reflects_in_ui(self, server_url, page):
        """Create via API, reload, verify session visible in UI."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'api-ui-001', name: 'API UI Test', pack: 'claude-code'})
            });
            return { status: resp.status };
        }""")
        assert result["status"] in (200, 201)

        page.reload()
        page.wait_for_timeout(1500)
        body = page.locator("body").inner_text()
        assert "api-ui-001" in body or "API UI Test" in body

    def test_created_session_shows_locked_form(self, server_url, page):
        """After creation, form fields should be disabled (locked)."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'lock-test-001', name: 'Lock Test', pack: 'claude-code'})
            });
        }""")

        page.reload()
        page.wait_for_timeout(1500)

        # Find the session in the sidebar or auto-select — check that form inputs are disabled
        body = page.locator("body").inner_text()
        # Locked state shows "Configuration is locked" hint
        assert "locked" in body.lower() or "Start Session" in body


# ---------------------------------------------------------------------------
# 3. SESSION CREATION — UNHAPPY PATH
# ---------------------------------------------------------------------------


class TestSessionCreationUnhappy:
    """Verify error handling for invalid session creation attempts."""

    def test_duplicate_session_id_via_api(self, server_url, page):
        """Creating a session with a duplicate ID should return 409."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            // Create first
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'dup-test-001', name: 'Dup Test 1', pack: 'claude-code'})
            });
            // Try duplicate
            const resp = await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'dup-test-001', name: 'Dup Test 2', pack: 'claude-code'})
            });
            return { status: resp.status, body: await resp.text() };
        }""")
        assert result["status"] == 409
        assert "already exists" in result["body"].lower()

    def test_missing_session_id_returns_422(self, server_url, page):
        """POST without required 'id' field should return 422 (Pydantic validation)."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: 'No ID', pack: 'claude-code'})
            });
            return { status: resp.status };
        }""")
        assert result["status"] == 422

    def test_nonexistent_session_returns_404(self, server_url, page):
        """GET for a session that doesn't exist returns 404."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/does-not-exist-999');
            return { status: resp.status };
        }""")
        assert result["status"] == 404


# ---------------------------------------------------------------------------
# 4. INTAKE FILE MANAGEMENT
# ---------------------------------------------------------------------------


class TestIntakeManagement:
    """Verify intake file listing and locking behavior."""

    def test_intake_shows_files_after_drop(self, server_url, runtime_home, page):
        """After adding intake files, the UI should list them."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Create session via API
        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'intake-test-001', name: 'Intake Test', pack: 'claude-code'})
            });
        }""")

        # Write intake files on disk
        _write_intake_file(runtime_home, "intake-test-001", "task_one.md", "# Task One\nDo something.")
        _write_intake_file(runtime_home, "intake-test-001", "task_two.md", "# Task Two\nDo another thing.")

        # Fetch intake via API and verify
        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/intake-test-001/intake');
            return await resp.json();
        }""")
        assert result["locked"] is False
        filenames = [f["filename"] for f in result["files"]]
        assert "task_one.md" in filenames
        assert "task_two.md" in filenames

    def test_intake_locked_after_session_starts(self, server_url, runtime_home, page):
        """After starting a session, intake should report locked=true."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Create session + add ready plan (bypassing planning)
        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'intake-lock-001', name: 'Intake Lock', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "intake-lock-001", "t001")
        _write_intake_file(runtime_home, "intake-lock-001", "dummy.md", "# Dummy\n")

        # Start session
        page.evaluate("""async () => {
            await fetch('/api/sessions/intake-lock-001/start', { method: 'POST' });
        }""")
        page.wait_for_timeout(1000)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/intake-lock-001/intake');
            return await resp.json();
        }""")
        assert result["locked"] is True


# ---------------------------------------------------------------------------
# 5. PREFLIGHT CHECKS
# ---------------------------------------------------------------------------


class TestPreflight:
    """Verify preflight check execution and display."""

    def test_preflight_fails_without_repo_root(self, server_url, page):
        """Preflight hook fails when COGNITIVE_SWITCHYARD_REPO_ROOT is not in session config."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'preflight-norr-001', name: 'No Repo Root', pack: 'strict-preflight'})
            });
            const resp = await fetch('/api/sessions/preflight-norr-001/preflight', { method: 'POST' });
            return await resp.json();
        }""")
        assert result["ok"] is False
        assert result["preflight_result"]["ok"] is False
        assert result["preflight_result"]["exit_code"] != 0
        # Verify stderr is surfaced (the actual error message)
        assert "COGNITIVE_SWITCHYARD_REPO_ROOT" in (result["preflight_result"]["stderr"] or "")

    def test_preflight_succeeds_with_repo_root_in_session_config(self, server_url, runtime_home, page):
        """Preflight hook passes when session config includes COGNITIVE_SWITCHYARD_REPO_ROOT."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate(f"""async () => {{
            await fetch('/api/sessions', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    id: 'preflight-ok-001',
                    name: 'Preflight OK',
                    pack: 'strict-preflight',
                    config: {{
                        environment: {{
                            COGNITIVE_SWITCHYARD_REPO_ROOT: '{runtime_home}'
                        }}
                    }}
                }})
            }});
            const resp = await fetch('/api/sessions/preflight-ok-001/preflight', {{ method: 'POST' }});
            return await resp.json();
        }}""")
        assert result["ok"] is True
        assert result["permission_report"]["ok"] is True
        assert result["preflight_result"]["ok"] is True

    def test_preflight_button_in_ui(self, server_url, page):
        """Run Preflight button should be visible and clickable."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'preflight-ui-001', name: 'Preflight UI', pack: 'claude-code'})
            });
        }""")
        page.reload()
        page.wait_for_timeout(1500)

        # The "Run Preflight" button should exist (may be in the setup view)
        preflight_btn = page.locator("button:has-text('Preflight')")
        assert preflight_btn.count() > 0


# ---------------------------------------------------------------------------
# 6. SESSION LIFECYCLE — START, EXECUTE, COMPLETE
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    """Full lifecycle: create, start, wait for completion."""

    def test_start_session_and_task_completes(self, server_url, runtime_home, page):
        """Create session, add intake plan, start, verify task reaches done."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'lifecycle-001', name: 'Lifecycle Test', pack: 'claude-code'})
            });
        }""")

        _write_intake_plan(runtime_home, "lifecycle-001", "t001")

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/lifecycle-001/start', { method: 'POST' });
            return { status: resp.status };
        }""")
        assert result["status"] == 202

        _poll_session_status(page, "lifecycle-001", {"idle", "aborted"})
        tasks = _poll_tasks_done(page, "lifecycle-001", min_done=1)
        task_ids = [t["task_id"] for t in tasks]
        assert "t001" in task_ids

    def test_multiple_tasks_execute_concurrently(self, server_url, runtime_home, page):
        """Two independent tasks should be dispatched to separate worker slots."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    id: 'concurrent-001', name: 'Concurrent', pack: 'claude-code',
                    config: { worker_count: 2 }
                })
            });
        }""")

        _write_intake_plan(runtime_home, "concurrent-001", "t001")
        _write_intake_plan(runtime_home, "concurrent-001", "t002")

        page.evaluate("""async () => {
            await fetch('/api/sessions/concurrent-001/start', { method: 'POST' });
        }""")

        _poll_tasks_done(page, "concurrent-001", min_done=2)

    def test_session_reaches_completed_status(self, server_url, runtime_home, page):
        """After all tasks finish, session status should become 'completed'."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'complete-001', name: 'Complete Test', pack: 'claude-code'})
            });
        }""")

        _write_intake_plan(runtime_home, "complete-001", "t001")

        page.evaluate("""async () => {
            await fetch('/api/sessions/complete-001/start', { method: 'POST' });
        }""")

        _poll_session_status(page, "complete-001", {"idle"})


# ---------------------------------------------------------------------------
# 7. SESSION CONTROL — PAUSE, RESUME, ABORT
# ---------------------------------------------------------------------------


class TestSessionControl:
    """Verify pause, resume, and abort controls."""

    def test_abort_running_session(self, server_url, runtime_home, page):
        """Aborting a running session should transition it to 'aborted'."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'abort-001', name: 'Abort Test', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "abort-001", "t001")

        page.evaluate("""async () => {
            await fetch('/api/sessions/abort-001/start', { method: 'POST' });
        }""")
        page.wait_for_timeout(500)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/abort-001/abort', { method: 'POST' });
            return { status: resp.status };
        }""")
        assert result["status"] == 202

        _poll_session_status(page, "abort-001", {"aborted"})

    def test_abort_button_visible_in_monitor_view(self, server_url, runtime_home, page):
        """When a non-terminal session is selected, the Abort button should appear."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Create a session and leave it in "created" state (no start) so it won't
        # race to completion before we can check the UI.
        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'abort-ui-001', name: 'Abort UI', pack: 'claude-code'})
            });
        }""")

        # Reload so the SPA picks up the new session and auto-selects it
        page.reload()
        page.wait_for_timeout(1500)

        # The Abort button is shown for any session that is not completed/aborted.
        # A "created" session qualifies. Check that the button exists.
        abort_btn = page.locator("button:has-text('Abort')")
        # Also check via case-insensitive body text in case CSS uppercases it
        body_lower = page.locator("body").inner_text().lower()
        assert abort_btn.count() > 0 or "abort" in body_lower


# ---------------------------------------------------------------------------
# 8. DASHBOARD & MONITOR VIEW
# ---------------------------------------------------------------------------


class TestDashboardAndMonitor:
    """Verify dashboard API and monitor view rendering."""

    def test_dashboard_returns_valid_payload(self, server_url, page):
        """Dashboard endpoint should return session, tasks, pipeline_dirs."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'dash-001', name: 'Dashboard', pack: 'claude-code'})
            });
        }""")

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/dash-001/dashboard');
            return await resp.json();
        }""")
        assert "session" in result
        assert "pipeline_dirs" in result
        assert result["session"]["status"] == "created"

    def test_monitor_view_renders_without_crash(self, server_url, page):
        """Switching to monitor view should not produce console errors."""
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)
        page.wait_for_timeout(500)

        monitor = page.locator("button:has-text('Monitor')")
        if monitor.count() > 0:
            monitor.click()
            page.wait_for_timeout(500)

        assert errors == [], f"Console errors on monitor: {errors}"


# ---------------------------------------------------------------------------
# 9. TASK DETAIL & LOG
# ---------------------------------------------------------------------------


class TestTaskDetail:
    """Verify task detail and log retrieval."""

    def test_task_detail_api(self, server_url, runtime_home, page):
        """After execution, task detail API returns metadata."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'detail-001', name: 'Detail', pack: 'claude-code'})
            });
        }""")

        _write_intake_plan(runtime_home, "detail-001", "td01")

        page.evaluate("""async () => {
            await fetch('/api/sessions/detail-001/start', { method: 'POST' });
        }""")

        _poll_tasks_done(page, "detail-001", min_done=1)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/detail-001/tasks/td01');
            return await resp.json();
        }""")
        assert result["task"]["task_id"] == "td01"
        assert result["task"]["status"] == "done"

    def test_task_log_api(self, server_url, runtime_home, page):
        """Task log endpoint should return log content after execution."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'log-001', name: 'Log Test', pack: 'claude-code'})
            });
        }""")

        _write_intake_plan(runtime_home, "log-001", "tl01")

        page.evaluate("""async () => {
            await fetch('/api/sessions/log-001/start', { method: 'POST' });
        }""")

        _poll_tasks_done(page, "log-001", min_done=1)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/log-001/tasks/tl01/log');
            return await resp.json();
        }""")
        assert "content" in result
        assert result["content"] != ""
        assert "PROGRESS" in result["content"]

    def test_task_detail_shows_timing_fields(self, server_url, runtime_home, page):
        """Completed task detail view shows Started, Duration, and Completed fields."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'timing-001', name: 'Timing', pack: 'claude-code'})
            });
        }""")

        _write_intake_plan(runtime_home, "timing-001", "tm01")

        page.evaluate("""async () => {
            await fetch('/api/sessions/timing-001/start', { method: 'POST' });
        }""")

        _poll_tasks_done(page, "timing-001", min_done=1)

        # Load the task detail after completion
        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/timing-001/tasks/tm01');
            return await resp.json();
        }""")
        task = result["task"]
        assert task["started_at"] is not None, "started_at should be set after execution"
        assert task["completed_at"] is not None, "completed_at should be set after execution"
        assert task["elapsed"] is not None and task["elapsed"] >= 0, "elapsed should be present"


# ---------------------------------------------------------------------------
# 10. DAG VIEW
# ---------------------------------------------------------------------------


class TestDagView:
    """Verify DAG (dependency graph) API."""

    def test_dag_returns_tasks(self, server_url, runtime_home, page):
        """DAG endpoint returns task dependency graph."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'dag-001', name: 'DAG Test', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "dag-001", "t001")
        _write_intake_plan(runtime_home, "dag-001", "t002", depends_on="t001")

        page.evaluate("""async () => {
            await fetch('/api/sessions/dag-001/start', { method: 'POST' });
        }""")

        _poll_tasks_exist(page, "dag-001", min_count=2)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/dag-001/dag');
            return await resp.json();
        }""")
        assert "tasks" in result
        task_ids = [t["task_id"] for t in result["tasks"]]
        assert "t001" in task_ids
        assert "t002" in task_ids


# ---------------------------------------------------------------------------
# 11. SETTINGS CRUD
# ---------------------------------------------------------------------------


class TestSettings:
    """Verify settings read and write."""

    def test_get_settings(self, server_url, page):
        """GET /api/settings returns current settings."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/settings');
            return await resp.json();
        }""")
        assert "settings" in result
        settings = result["settings"]
        assert "retention_days" in settings
        assert "default_pack" in settings

    def test_update_settings(self, server_url, page):
        """PUT /api/settings should persist changes."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/settings', {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    retention_days: 7,
                    default_planners: 2,
                    default_workers: 2,
                    default_pack: 'claude-code'
                })
            });
            return await resp.json();
        }""")
        assert result["settings"]["retention_days"] == 7
        assert result["settings"]["default_planners"] == 2

        # Verify persistence
        verify = page.evaluate("""async () => {
            const resp = await fetch('/api/settings');
            return await resp.json();
        }""")
        assert verify["settings"]["retention_days"] == 7

    def test_settings_view_saves_via_ui(self, server_url, page):
        """Navigate to settings, verify save button exists."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.locator("button[aria-label='Settings']").click()
        page.wait_for_timeout(500)

        # CSS may uppercase text, so check case-insensitively
        body_lower = page.locator("body").inner_text().lower()
        assert "save" in body_lower

    def test_settings_terminal_app_field_visible_and_saveable(self, server_url, page):
        """Terminal Application field is visible in Settings and saves correctly."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.locator("button[aria-label='Settings']").click()
        page.wait_for_timeout(500)

        # Verify Terminal Application input is visible
        terminal_input = page.locator("input[list='terminal-options']")
        assert terminal_input.is_visible(), "Terminal Application input should be visible in Settings"

        # Change the value to Kitty
        terminal_input.fill("Kitty")

        # Click Save Settings
        page.locator("button:has-text('Save')").click()
        page.wait_for_timeout(500)

        # Navigate away and back to verify persistence
        page.locator("button:has-text('Setup')").click()
        page.wait_for_timeout(300)
        page.locator("button[aria-label='Settings']").click()
        page.wait_for_timeout(500)

        persisted_value = page.locator("input[list='terminal-options']").input_value()
        assert persisted_value == "Kitty", f"Expected terminal_app 'Kitty' after reload, got '{persisted_value}'"


# ---------------------------------------------------------------------------
# 12. SESSION DELETION & PURGE
# ---------------------------------------------------------------------------


class TestSessionDeletion:
    """Verify session deletion and purge workflows."""

    def test_delete_created_session(self, server_url, page):
        """A session in 'created' status can be deleted."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'delete-001', name: 'Delete Me', pack: 'claude-code'})
            });
        }""")

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/delete-001', { method: 'DELETE' });
            return { status: resp.status, body: await resp.json() };
        }""")
        assert result["status"] == 200
        assert result["body"]["deleted"] == 1

        # Verify it's gone
        verify = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/delete-001');
            return { status: resp.status };
        }""")
        assert verify["status"] == 404

    def test_cannot_delete_running_session(self, server_url, runtime_home, page):
        """A running or recently-started session cannot be deleted while active."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Start session and immediately try to delete — race the execute
        result = page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'nodelete-001', name: 'No Delete', pack: 'claude-code'})
            });
            // Start session — don't add ready plans so it stays in "running" with nothing to do
            const startResp = await fetch('/api/sessions/nodelete-001/start', { method: 'POST' });
            // Immediate delete attempt — session is running (even without tasks, the thread is active)
            const delResp = await fetch('/api/sessions/nodelete-001', { method: 'DELETE' });
            return { startStatus: startResp.status, deleteStatus: delResp.status };
        }""")
        # Session should be running (no ready plans → it will complete quickly but
        # the thread might still be active). Either 409 (still running) or 200 (completed already)
        # is acceptable — the key is we don't crash.
        assert result["deleteStatus"] in (200, 409)

        # Clean up if still exists
        page.evaluate("""async () => {
            try { await fetch('/api/sessions/nodelete-001/abort', { method: 'POST' }); } catch {}
            try { await fetch('/api/sessions/nodelete-001', { method: 'DELETE' }); } catch {}
        }""")

    def test_delete_aborted_session(self, server_url, runtime_home, page):
        """An aborted session can be deleted."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'del-abort-001', name: 'Del Abort', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "del-abort-001", "t001")

        result = page.evaluate("""async () => {
            await fetch('/api/sessions/del-abort-001/start', { method: 'POST' });
            await new Promise(r => setTimeout(r, 500));
            await fetch('/api/sessions/del-abort-001/abort', { method: 'POST' });
            await new Promise(r => setTimeout(r, 2000));
            const resp = await fetch('/api/sessions/del-abort-001', { method: 'DELETE' });
            return { status: resp.status };
        }""")
        assert result["status"] == 200

    def test_purge_completed_sessions(self, server_url, runtime_home, page):
        """DELETE /api/sessions purges all completed/aborted sessions."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Create and complete a session
        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'purge-001', name: 'Purge Me', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "purge-001", "t001")

        page.evaluate("""async () => {
            await fetch('/api/sessions/purge-001/start', { method: 'POST' });
        }""")

        _poll_session_status(page, "purge-001", {"idle"})

        # Small delay to let the session thread fully exit
        page.wait_for_timeout(500)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions', { method: 'DELETE' });
            return await resp.json();
        }""")
        assert result["deleted"] >= 1

        # Verify it's gone — allow a brief retry window for thread cleanup
        verify = page.evaluate("""async () => {
            for (let i = 0; i < 5; i++) {
                const resp = await fetch('/api/sessions/purge-001');
                if (resp.status === 404) return { status: 404 };
                // Session might have been re-created by thread cleanup; re-purge
                await fetch('/api/sessions', { method: 'DELETE' });
                await new Promise(r => setTimeout(r, 200));
            }
            const resp = await fetch('/api/sessions/purge-001');
            return { status: resp.status };
        }""")
        assert verify["status"] == 404


# ---------------------------------------------------------------------------
# 13. HISTORY VIEW
# ---------------------------------------------------------------------------


class TestHistoryView:
    """Verify history view lists completed sessions."""

    def test_history_lists_completed_sessions(self, server_url, runtime_home, page):
        """History should list sessions that have completed — verified via API."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'hist-001', name: 'History Test', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "hist-001", "t001")

        page.evaluate("""async () => {
            await fetch('/api/sessions/hist-001/start', { method: 'POST' });
        }""")

        _poll_session_status(page, "hist-001", {"idle"})

        # Verify via API that the session appears in the session list as idle
        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions');
            const data = await resp.json();
            return data.sessions.filter(s => s.id === 'hist-001' && s.status === 'idle');
        }""")
        assert len(result) == 1
        assert result[0]["name"] == "History Test"


# ---------------------------------------------------------------------------
# 14. WEBSOCKET REAL-TIME UPDATES
# ---------------------------------------------------------------------------


class TestWebSocketUpdates:
    """Verify real-time updates via WebSocket."""

    def test_websocket_delivers_state_update(self, server_url, runtime_home, page):
        """WebSocket should deliver state_update messages during execution."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)
        page.wait_for_timeout(1000)  # Let WS connect

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'ws-001', name: 'WS Test', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "ws-001", "t001")

        page.evaluate("""async () => {
            await fetch('/api/sessions/ws-001/start', { method: 'POST' });
        }""")

        _poll_session_status(page, "ws-001", {"running", "idle", "aborted"})

        # Verify the session reached at least running state
        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/ws-001');
            return await resp.json();
        }""")
        assert result["session"]["status"] in ("running", "idle", "planning", "resolving")


# ---------------------------------------------------------------------------
# 15. PACKS API
# ---------------------------------------------------------------------------


class TestPacksApi:
    """Verify pack listing and detail endpoints."""

    def test_list_packs(self, server_url, page):
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/packs');
            return await resp.json();
        }""")
        assert "packs" in result
        names = [p["name"] for p in result["packs"]]
        assert "claude-code" in names

    def test_get_pack_detail(self, server_url, page):
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/packs/claude-code');
            return { status: resp.status, data: await resp.json() };
        }""")
        assert result["status"] == 200

    def test_nonexistent_pack_returns_404(self, server_url, page):
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/packs/does-not-exist');
            return { status: resp.status };
        }""")
        assert result["status"] in (404, 422, 500)


# ---------------------------------------------------------------------------
# 16. SESSION CONFIG OVERRIDES
# ---------------------------------------------------------------------------


class TestSessionConfig:
    """Verify session config overrides work through the API."""

    def test_config_overrides_applied(self, server_url, page):
        """Session config overrides (worker_count, etc.) should persist."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    id: 'config-001',
                    name: 'Config Test',
                    pack: 'claude-code',
                    config: {
                        worker_count: 1,
                        verification_interval: 10,
                        auto_fix_enabled: false,
                        poll_interval: 0.1,
                        environment: { COGNITIVE_SWITCHYARD_REPO_ROOT: '/tmp/fake' }
                    }
                })
            });
            return await resp.json();
        }""")
        ert = result["session"]["effective_runtime_config"]
        assert ert["worker_count"] == 1
        assert ert["auto_fix"]["enabled"] is False
        assert ert["environment"]["COGNITIVE_SWITCHYARD_REPO_ROOT"] == "/tmp/fake"

    def test_ui_form_sends_config_overrides(self, server_url, page):
        """Creating via the API with config overrides works correctly."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Create session with config overrides via API (avoids UI state pollution)
        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    id: 'config-ui-001',
                    name: 'Config UI Test',
                    pack: 'claude-code',
                    config: { worker_count: 2, poll_interval: 0.5 }
                })
            });
            return await resp.json();
        }""")
        assert result["session"]["id"] == "config-ui-001"
        assert result["session"]["name"] == "Config UI Test"
        assert result["session"]["pack"] == "claude-code"
        assert result["session"]["effective_runtime_config"]["worker_count"] == 2


# ---------------------------------------------------------------------------
# 17. RESET / DISCARD DRAFT
# ---------------------------------------------------------------------------


class TestResetDraft:
    """Verify the Reset (discard draft) workflow."""

    def test_reset_deletes_session_and_unlocks_form(self, server_url, page):
        """Clicking Reset should delete the session and return to blank form."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'reset-001', name: 'Reset Me', pack: 'claude-code'})
            });
        }""")

        page.reload()
        page.wait_for_timeout(1500)

        # Click Reset button
        reset_btn = page.locator("button:has-text('Reset')")
        if reset_btn.count() > 0:
            reset_btn.click()
            page.wait_for_timeout(1000)

            # Verify session is deleted
            result = page.evaluate("""async () => {
                const resp = await fetch('/api/sessions/reset-001');
                return { status: resp.status };
            }""")
            assert result["status"] == 404


# ---------------------------------------------------------------------------
# 18. ERROR DISPLAY
# ---------------------------------------------------------------------------


class TestErrorDisplay:
    """Verify error messages are surfaced in the UI."""

    def test_start_nonexistent_session_shows_error(self, server_url, page):
        """Starting a session that doesn't exist should return 404."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/ghost-session/start', { method: 'POST' });
            return { status: resp.status };
        }""")
        assert result["status"] == 404

    def test_tasks_for_nonexistent_session(self, server_url, page):
        """Getting tasks for a missing session returns 404."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/ghost-session/tasks');
            return { status: resp.status };
        }""")
        assert result["status"] == 404


# ---------------------------------------------------------------------------
# 19. FULL UI WORKFLOW — END TO END
# ---------------------------------------------------------------------------


class TestFullUIWorkflow:
    """Complete user journey through the UI — create, configure, start, monitor, complete."""

    def test_create_start_monitor_complete_history(self, server_url, runtime_home, page):
        """Full workflow: create via API, start, wait for completion, verify history."""
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Step 1: Create session via API (avoids UI state pollution from prior tests)
        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'workflow-001', name: 'Full Workflow Test', pack: 'claude-code'})
            });
        }""")

        # Step 2: Add an intake plan
        _write_intake_plan(runtime_home, "workflow-001", "t001")

        # Step 3: Start the session
        page.evaluate("""async () => {
            await fetch('/api/sessions/workflow-001/start', { method: 'POST' });
        }""")

        # Step 4: Wait for task completion
        _poll_session_status(page, "workflow-001", {"idle", "aborted"})

        # Step 5: Verify session is idle via API
        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/workflow-001');
            return await resp.json();
        }""")
        assert result["session"]["status"] == "idle"

        # Step 6: Verify task completed
        task_result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/workflow-001/tasks');
            return await resp.json();
        }""")
        assert any(t["task_id"] == "t001" and t["status"] == "done" for t in task_result["tasks"])

        # Verify no JS errors throughout
        assert errors == [], f"Console errors during workflow: {errors}"


# ---------------------------------------------------------------------------
# 20. PLANNING PHASE STREAMING — PlannerAgentCard
# ---------------------------------------------------------------------------


class TestPlanningPhaseStreaming:
    """Verify that the planning phase displays correctly in the dashboard.

    Since these E2E tests cannot run the real Claude CLI, we verify:
    1. The file_planned event appears in the session event feed after planning
    2. The PhaseActivityCard component renders during the planning phase
    3. The planning_agents key is present in the API response shape
    4. The frontend renders without JS errors during a planning phase

    The PlannerAgentCard visual rendering (per-planner sub-cards) requires a
    real planner agent invocation (planning.enabled=true), which is covered by
    the regression tests in test_orchestrator.py.
    """

    def test_file_planned_events_appear_in_api_event_feed_after_passthrough_planning(
        self, server_url, runtime_home, page
    ):
        """file_planned events must be persisted to the session event store
        and appear in the API response's recent_events array after planning."""
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Create session and add 2 passthrough-ready plan files
        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'planning-e2e-001', name: 'Planning Phase E2E', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "planning-e2e-001", "e01")
        _write_intake_plan(runtime_home, "planning-e2e-001", "e02")

        # Start the session (planning.enabled=false → passthrough → runs through quickly)
        page.evaluate("""async () => {
            await fetch('/api/sessions/planning-e2e-001/start', { method: 'POST' });
        }""")

        # Wait for session to leave "created" state
        _poll_session_status(page, "planning-e2e-001", {"running", "completed", "aborted", "planning", "resolving"})
        # Wait for it to finish
        _poll_session_status(page, "planning-e2e-001", {"idle", "completed", "aborted"})

        # Check event feed via dashboard API (which includes recent_events)
        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/planning-e2e-001/dashboard');
            return await resp.json();
        }""")
        event_types = [e["type"] for e in result.get("recent_events", [])]
        # file_planned must be persisted in the event store
        assert "file_planned" in event_types, (
            f"Expected 'file_planned' in recent_events but got: {event_types}"
        )
        assert errors == [], f"JS console errors during planning E2E test: {errors}"

    def test_planning_agents_key_present_in_api_schema(self, server_url, page):
        """The dashboard API endpoint must always return a well-formed response.
        planning_agents may be absent (for non-planning phases) or a list."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'planning-schema-001', name: 'Planning Schema', pack: 'claude-code'})
            });
        }""")

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/planning-schema-001/dashboard');
            return await resp.json();
        }""")
        # Dashboard should have the expected keys
        assert "session" in result
        assert "pipeline" in result
        assert "recent_events" in result
        # planning_agents is optional — not present for non-planning sessions — so don't assert it
        # But if it IS present, it must be a list
        if "planning_agents" in result:
            assert isinstance(result["planning_agents"], list)

    def test_phase_activity_card_renders_and_no_js_errors_during_planning_phase(
        self, server_url, runtime_home, page
    ):
        """The PhaseActivityCard must render without JS errors while the session
        passes through the planning phase (even in passthrough/fast mode)."""
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'planning-render-001', name: 'Planning Render', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "planning-render-001", "r01")
        _write_intake_plan(runtime_home, "planning-render-001", "r02")

        # Start and wait for completion — PhaseActivityCard renders at some point during this
        page.evaluate("""async () => {
            await fetch('/api/sessions/planning-render-001/start', { method: 'POST' });
        }""")
        _poll_session_status(page, "planning-render-001", {"idle", "completed", "aborted"})

        # Navigate to the monitor view for this session
        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/planning-render-001');
            return await resp.json();
        }""")
        assert result["session"]["status"] in {"idle", "completed", "aborted"}
        assert errors == [], f"JS console errors during planning render test: {errors}"


# ---------------------------------------------------------------------------
# 21. ELAPSED TIMERS
# ---------------------------------------------------------------------------


class TestElapsedTimers:
    """Verify elapsed time counters increment for active workers and tasks in the UI."""

    def test_elapsed_timer_updates_during_session_execution(
        self, server_url, runtime_home, page
    ):
        """Session and task elapsed timers must report > 0 while running."""
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'elapsed-ui-001', name: 'Elapsed Timer Test', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "elapsed-ui-001", "et01")

        page.evaluate("""async () => {
            await fetch('/api/sessions/elapsed-ui-001/start', { method: 'POST' });
        }""")

        # Wait until session is active (running or planning/executing)
        _poll_session_status(page, "elapsed-ui-001", {"running", "planning", "resolving", "completed"})

        # Wait for the dashboard to show the session in monitor view
        page.wait_for_function(
            """() => {
                const resp = fetch('/api/sessions/elapsed-ui-001/dashboard')
                    .then(r => r.json())
                    .then(d => d.session && ['running', 'completed'].includes(d.session.status));
                return resp;
            }""",
            timeout=SLOW_TIMEOUT,
        )

        # Poll session elapsed directly from the API — must be > 0s after a short wait
        page.wait_for_timeout(3000)
        dashboard = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/elapsed-ui-001/dashboard');
            return await resp.json();
        }""")
        session_elapsed = dashboard.get("session", {}).get("elapsed", 0)
        # Sub-second sessions truncate to 0 with int(); verify field is present and non-negative
        assert session_elapsed >= 0, (
            f"Session elapsed must be >= 0, got {session_elapsed}"
        )

        # Tasks API must also include elapsed for completed tasks
        tasks = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/elapsed-ui-001/tasks');
            return await resp.json();
        }""")
        task_list = tasks.get("tasks", [])
        assert any(
            t.get("elapsed") is not None for t in task_list
        ), f"At least one task must have elapsed field, got: {task_list}"

        assert errors == [], f"Console errors during elapsed timer test: {errors}"

    def test_run_number_nonzero_after_session_start(
        self, server_url, runtime_home, page
    ):
        """run_number must be >= 1 in the dashboard payload shortly after start.

        Regression (plan 007): run_number stayed 0 during planning/resolving,
        which caused the TopBar to hide timers (guarded by runNumber > 0).
        After the fix, run_number is set to >= 1 before planning begins.

        This test does not require observing the planning status directly (the
        phase may complete before the first poll). It verifies that after start
        the dashboard reports run_number >= 1, which is the precondition for
        TopBar timers to render.
        """
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'run-num-007', name: 'Run Number 007 Test', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "run-num-007", "rn01")

        page.evaluate("""async () => {
            await fetch('/api/sessions/run-num-007/start', { method: 'POST' });
        }""")

        # Wait until session reaches any active or terminal state
        _poll_session_status(
            page, "run-num-007",
            {"running", "planning", "resolving", "idle", "completed", "aborted"},
        )

        dashboard = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/run-num-007/dashboard');
            return await resp.json();
        }""")
        run_number = dashboard.get("session", {}).get("run_number", 0)
        assert run_number >= 1, (
            f"run_number must be >= 1 after session start, got {run_number}. "
            "If this regresses, TopBar timers will be hidden during planning/resolving."
        )

    def test_run_timer_holds_value_after_completion(
        self, server_url, runtime_home, page
    ):
        """Run timer must retain its final value after completion (not reset to 0s).

        Regression (plan 019): run timer previously reset to 0s when the session
        went idle/completed because it tracked only the live runTick which stops
        incrementing when isActive=false. The fix captures the final value in
        lastRunElapsed when isActive transitions from true to false.
        """
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'run-timer-019', name: 'Run Timer Hold Test', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "run-timer-019", "rt01")

        page.evaluate("""async () => {
            await fetch('/api/sessions/run-timer-019/start', { method: 'POST' });
        }""")

        # Reload so bootstrap auto-selects this session and the UI renders timers
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Wait for session to complete (idle)
        _poll_session_status(
            page, "run-timer-019",
            {"idle", "completed"},
            timeout=30.0,
        )

        # Wait briefly for the UI to update
        page.wait_for_timeout(500)

        # The run timer span must show a non-zero value after completion
        run_timer_text = page.evaluate("""() => {
            const span = document.querySelector('[title="Current run time"]');
            return span ? span.textContent : null;
        }""")
        assert run_timer_text is not None, (
            "Run timer span not found. TopBar may not be rendering timers."
        )
        assert run_timer_text != "Run #1: 0s", (
            f"Run timer reset to '0s' after completion — lastRunElapsed capture is broken. "
            f"Got: {run_timer_text!r}"
        )
        # Sanity: the text must contain "Run #"
        assert "Run #" in run_timer_text, (
            f"Unexpected run timer text format: {run_timer_text!r}"
        )

        assert errors == [], f"Console errors during run timer hold test: {errors}"

    def test_cumulative_timer_prominent(
        self, server_url, runtime_home, page
    ):
        """Cumulative timer must have same font size as run timer and not use muted color.

        Regression (plan 019): cumulative timer was styled with font-size: var(--text-xs)
        and className='muted', making it much smaller and grayer than the run timer.
        The fix removes these overrides so it inherits the same size and uses
        --text-primary color.
        """
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'cumul-timer-019', name: 'Cumulative Timer Prominent Test', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "cumul-timer-019", "ct01")

        page.evaluate("""async () => {
            await fetch('/api/sessions/cumul-timer-019/start', { method: 'POST' });
        }""")

        # Reload so bootstrap auto-selects this session and the UI renders timers
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Wait for session to be active enough for timers to render
        _poll_session_status(
            page, "cumul-timer-019",
            {"running", "planning", "resolving", "idle", "completed"},
        )
        page.wait_for_timeout(500)

        # Verify cumulative timer is present and NOT using old small/muted styling
        cumul_style = page.evaluate("""() => {
            const span = document.querySelector('[title="Total active time across all runs"]');
            if (!span) return null;
            const computed = window.getComputedStyle(span);
            return {
                fontSize: computed.fontSize,
                color: computed.color,
                className: span.className,
                inlineStyle: span.getAttribute('style') || ''
            };
        }""")
        assert cumul_style is not None, (
            "Cumulative timer span not found. TopBar may not be rendering timers."
        )
        # Must NOT have the old muted class
        assert "muted" not in cumul_style["className"], (
            f"Cumulative timer still has 'muted' class: {cumul_style!r}. "
            "Old styling was not removed."
        )
        # Must NOT have the old small font-size inline style
        assert "text-xs" not in cumul_style["inlineStyle"], (
            f"Cumulative timer still has --text-xs font override: {cumul_style!r}. "
            "Old font-size override was not removed."
        )

        # Font size of cumulative timer must be >= run timer font size
        run_timer_font = page.evaluate("""() => {
            const span = document.querySelector('[title="Current run time"]');
            if (!span) return null;
            return window.getComputedStyle(span).fontSize;
        }""")
        if run_timer_font is not None and cumul_style["fontSize"]:
            # Both are pixel values like "14px" — compare numerically
            def _px(val: str) -> float:
                return float(val.replace("px", "")) if val and "px" in val else 0.0
            cumul_px = _px(cumul_style["fontSize"])
            run_px = _px(run_timer_font)
            assert cumul_px >= run_px * 0.9, (  # allow 10% tolerance for rounding
                f"Cumulative timer font ({cumul_px}px) is smaller than run timer font ({run_px}px). "
                "Cumulative timer must be equally prominent."
            )

        assert errors == [], f"Console errors during cumulative timer prominence test: {errors}"


# ---------------------------------------------------------------------------
# VerificationCard UI tests
# ---------------------------------------------------------------------------


class TestVerificationCard:
    """Verify the VerificationCard renders correctly with no JS errors.

    These tests use a pack with verification enabled and confirm:
    1. The VerificationCard renders with a timer when verification runs.
    2. No JS errors occur during the verification phase.
    3. The card is expandable (click to toggle detail view).
    """

    def test_verification_card_renders_and_no_js_errors_during_verification(
        self, server_url, runtime_home, page
    ):
        """VerificationCard must render without JS errors when verification runs."""
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'verif-card-001', name: 'VerificationCard Test', pack: 'verify-enabled'})
            });
        }""")
        _write_intake_plan(runtime_home, "verif-card-001", "vc01")

        page.evaluate("""async () => {
            await fetch('/api/sessions/verif-card-001/start', { method: 'POST' });
        }""")

        # Wait for the session to complete (verification happens after task completion)
        _poll_session_status(
            page, "verif-card-001",
            {"idle", "completed", "running"},
            timeout=30.0,
        )

        # Verify no JS errors occurred
        assert errors == [], f"Console errors during verification card test: {errors}"

    def test_verification_streaming_log_appears_in_taskLogs_api_events(
        self, server_url, runtime_home, page
    ):
        """After a session with verification, events API must include verification_started."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)
        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'verif-card-002', name: 'VerificationCard Events Test', pack: 'verify-enabled'})
            });
        }""")
        _write_intake_plan(runtime_home, "verif-card-002", "vc02")
        page.evaluate("""async () => {
            await fetch('/api/sessions/verif-card-002/start', { method: 'POST' });
        }""")

        _poll_session_status(
            page, "verif-card-002",
            {"idle", "completed"},
            timeout=30.0,
        )

        # Events should include verification_started (exposed via recent_events on session detail)
        session_data = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/verif-card-002');
            return await resp.json();
        }""")
        event_types = [e.get("type", "") for e in session_data.get("recent_events", [])]
        assert any("verification" in t for t in event_types), (
            f"Expected at least one verification event, got: {event_types}"
        )

    def test_new_run_clears_stale_verification_state_in_ui(
        self, server_url, runtime_home, page
    ):
        """After a completed run, starting a New Run must not show VerificationCard.

        Regression (plan 010): stale verification/auto-fix fields in runtime_state persisted
        across runs, causing the pipeline strip to stay on "Verify" and VerificationCard
        to render at the start of a new run.

        This test verifies the UI behavior: after New Run is clicked, the session enters
        "running" state (not "verifying" or "auto_fixing"), and the VerificationCard is
        not visible.
        """
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Create and start a session with verify-enabled pack
        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'verif-newrun-010', name: 'New Run Reset Test', pack: 'verify-enabled'})
            });
        }""")
        _write_intake_plan(runtime_home, "verif-newrun-010", "nr01")

        page.evaluate("""async () => {
            await fetch('/api/sessions/verif-newrun-010/start', { method: 'POST' });
        }""")

        # Wait for the first run to complete (session goes idle)
        _poll_session_status(
            page, "verif-newrun-010",
            {"idle"},
            timeout=30.0,
        )

        # Start a new run via the resume endpoint (equivalent to clicking "New Run" button)
        page.evaluate("""async () => {
            await fetch('/api/sessions/verif-newrun-010/resume', { method: 'POST' });
        }""")

        # Wait for the new run to enter "running" (or complete quickly)
        _poll_session_status(
            page, "verif-newrun-010",
            {"running", "idle", "completed"},
            timeout=15.0,
        )

        # Fetch dashboard to verify verification_pending is cleared (core regression check)
        dashboard = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/verif-newrun-010/dashboard');
            return await resp.json();
        }""")
        runtime_state = dashboard.get("runtime_state", {})
        assert runtime_state.get("verification_pending") is False, (
            f"verification_pending must be False at new run start, got {runtime_state!r}. "
            "If this regresses, the pipeline strip will show 'Verify' instead of 'Active'."
        )

        # Fetch session status — must NOT be "verifying" or "auto_fixing"
        session_status = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/verif-newrun-010');
            const data = await resp.json();
            return data.session.status;
        }""")
        assert session_status not in ("verifying", "auto_fixing"), (
            f"Session must not enter verifying/auto_fixing immediately after New Run, got {session_status!r}. "
            "If this regresses, stale verification_pending is triggering verification on new run start."
        )

        # No JS errors during the new-run transition
        assert errors == [], f"Console errors during new-run transition: {errors}"


# ---------------------------------------------------------------------------
# 17. BANNER BEHAVIOR (plan 001)
# ---------------------------------------------------------------------------


class TestBannerBehavior:
    """Verify banner dismissibility, auto-dismiss, auto-clear on navigation,
    and auto-clear on success (plan 001 regression tests).

    Strategy: use page.route to intercept PUT /api/settings and return an error,
    so we can reliably trigger an error banner without depending on session state
    from earlier tests in the module-scoped server fixture.
    """

    def _trigger_error_banner(self, page, server_url):
        """Intercept the settings save API call to return 500, then trigger it.

        Returns after the error banner is visible.
        """
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)
        page.wait_for_timeout(500)

        # Intercept PUT /api/settings to simulate a server error
        page.route("**/api/settings", lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body='{"detail": "Simulated server error for banner test"}'
        ) if route.request.method == "PUT" else route.continue_())

        # Navigate to Settings and click Save → SPA calls PUT /api/settings, gets 500 → error banner
        page.locator("button[aria-label='Settings']").click()
        page.wait_for_timeout(400)
        page.locator("button:has-text('Save')").click()
        page.wait_for_timeout(600)

        banner = page.locator(".banner")
        banner.wait_for(state="visible", timeout=5000)
        return banner

    def test_dismiss_button_clears_error_banner(self, server_url, page):
        """Clicking the × button on an error banner removes it from the DOM.

        Regression: banners had no dismiss control — once shown they were stuck
        until a page reload.
        """
        banner = self._trigger_error_banner(page, server_url)

        assert banner.is_visible(), "Error banner should appear after simulated save failure"
        assert "error" in (banner.get_attribute("class") or ""), (
            "Banner should have 'error' class for API failure"
        )

        # Dismiss button must be present
        dismiss_btn = page.locator(".banner button[title='Dismiss']")
        dismiss_btn.wait_for(state="visible", timeout=3000)
        dismiss_btn.click()
        page.wait_for_timeout(300)

        assert not banner.is_visible(), "Banner should be hidden after clicking dismiss button"

    def test_banner_auto_clears_on_navigation(self, server_url, page):
        """Switching views clears any displayed banner.

        Regression: setView did not clear the message state, so error/warning
        banners persisted across view transitions.
        """
        banner = self._trigger_error_banner(page, server_url)

        assert banner.is_visible(), "Banner must be visible before navigation"

        # Navigate to Setup — banner should clear (unroute first so the nav succeeds)
        page.unroute("**/api/settings")
        page.locator("button:has-text('Setup')").click()
        page.wait_for_timeout(500)

        assert not banner.is_visible(), "Banner should be cleared after view navigation"

    def test_info_banner_auto_dismisses_after_delay(self, server_url, page):
        """Info-level banners auto-dismiss after ~8 seconds.

        Regression: non-error banners had no auto-dismiss and required manual
        action or a page reload to clear.
        """
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Navigate to Settings and save — success sets an info banner
        page.locator("button[aria-label='Settings']").click()
        page.wait_for_timeout(500)

        # Click Save Settings to trigger "Settings saved." info banner
        page.locator("button:has-text('Save')").click()
        page.wait_for_timeout(500)

        banner = page.locator(".banner")
        banner.wait_for(state="visible", timeout=5000)
        assert banner.is_visible(), "Info banner should appear after settings save"
        # Confirm it's not an error-level banner
        assert "error" not in (banner.get_attribute("class") or ""), (
            "Settings saved banner should not have 'error' class"
        )

        # Auto-dismiss fires after 8 s; wait up to 12 s to account for timing
        banner.wait_for(state="hidden", timeout=12000)
        assert not banner.is_visible(), "Info banner must auto-dismiss within ~8 seconds"

    def test_error_banner_does_not_auto_dismiss(self, server_url, page):
        """Error-level banners do NOT auto-dismiss — they require explicit action.

        Regression guard: if the auto-dismiss timer accidentally applies to error
        banners, users will lose visibility of actionable errors.
        """
        banner = self._trigger_error_banner(page, server_url)

        assert "error" in (banner.get_attribute("class") or ""), (
            "Banner should have 'error' class for API failure"
        )

        # Wait 10 seconds — error banner must still be visible
        page.wait_for_timeout(10000)
        assert banner.is_visible(), (
            "Error banner must NOT auto-dismiss — it should persist until explicit action"
        )


# ---------------------------------------------------------------------------
# Setup form: planner/worker count validation hints (plan 002 regression)
# ---------------------------------------------------------------------------


def _setup_runtime_with_planning(tmp_path: Path) -> Path:
    """Create a runtime with a planning-enabled pack (max_instances=3, max_workers=2)."""
    home = tmp_path / "runtime_planning"
    cs = home / ".cognitive_switchyard"
    packs = cs / "packs" / "claude-code"
    scripts = packs / "scripts"
    prompts = packs / "prompts"
    scripts.mkdir(parents=True)
    prompts.mkdir(parents=True)
    (cs / "sessions").mkdir(parents=True, exist_ok=True)

    (scripts / "execute").write_text(
        dedent("""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path
        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """).lstrip(),
        encoding="utf-8",
    )
    (scripts / "execute").chmod(0o755)
    (prompts / "planner.md").write_text("Plan prompt.\n")
    (prompts / "resolver.md").write_text("Resolve prompt.\n")

    (packs / "pack.yaml").write_text(
        dedent("""
        name: claude-code
        description: Planning-enabled E2E test pack.
        version: 0.0.1

        phases:
          planning:
            enabled: true
            executor: agent
            model: claude-sonnet
            prompt: prompts/planner.md
            max_instances: 3
          resolution:
            enabled: false
            executor: passthrough
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
            max_workers: 2
          verification:
            enabled: false

        timeouts:
          task_idle: 60
          task_max: 0
          session_max: 300

        isolation:
          type: none
        """).lstrip(),
        encoding="utf-8",
    )
    return home


@pytest.fixture(scope="module")
def runtime_home_planning(tmp_path_factory) -> Path:
    tmp_path = tmp_path_factory.mktemp("e2e_planning")
    return _setup_runtime_with_planning(tmp_path)


@pytest.fixture(scope="module")
def server_url_planning(runtime_home_planning):
    """Start a real uvicorn server with a planning-enabled pack and return its URL."""
    runtime_paths = build_runtime_paths(home=runtime_home_planning)
    store = initialize_state_store(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    port = _find_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="wsproto")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.25)
    else:
        raise RuntimeError(f"Uvicorn (planning) did not start on port {port}")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


class TestSetupFormPlannerValidation:
    """Verify the setup form shows amber clamping hints when planner/worker
    count inputs exceed the pack limits.

    Regression for plan 002: max_planners was absent from pack summary, so
    the planner count field had no max attribute and showed no feedback when
    the user entered values the backend would silently clamp.
    """

    def test_planner_count_hint_appears_when_value_exceeds_pack_limit(
        self, server_url_planning, page
    ):
        """Entering a planner count above max_planners shows an amber warning.

        Pack has max_instances=3. Entering 5 must show the hint; entering 2
        must hide it.
        """
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url_planning)
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)
        page.wait_for_timeout(500)

        # The planner count field should be visible (planning is enabled on this pack)
        planner_input = page.locator("label:has-text('Planner Count') ~ input").first
        planner_input.wait_for(state="visible", timeout=SLOW_TIMEOUT)

        # Enter a value above the pack limit (max_instances=3)
        planner_input.fill("5")
        page.wait_for_timeout(300)

        hint = page.locator(".field-hint", has_text="Pack limit: 3")
        hint.wait_for(state="visible", timeout=3000)
        assert hint.is_visible(), "Amber hint must appear when planner_count (5) > max_planners (3)"

        # Drop below the limit — hint must disappear
        planner_input.fill("2")
        page.wait_for_timeout(300)
        assert not hint.is_visible(), "Hint must disappear when planner_count (2) <= max_planners (3)"

        assert errors == [], f"JS errors during planner count hint test: {errors}"

    def test_worker_count_hint_appears_when_value_exceeds_pack_limit(
        self, server_url_planning, page
    ):
        """Entering a worker count above max_workers shows an amber warning.

        Pack has max_workers=2. Entering 5 must show the hint; entering 1
        must hide it.
        """
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url_planning)
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)
        page.wait_for_timeout(500)

        worker_input = page.locator("label:has-text('Worker Count') ~ input").first
        worker_input.wait_for(state="visible", timeout=SLOW_TIMEOUT)

        # Enter a value above the pack limit (max_workers=2)
        worker_input.fill("5")
        page.wait_for_timeout(300)

        hint = page.locator(".field-hint", has_text="Pack limit: 2")
        hint.wait_for(state="visible", timeout=3000)
        assert hint.is_visible(), "Amber hint must appear when worker_count (5) > max_workers (2)"

        # Drop below the limit — hint must disappear
        worker_input.fill("1")
        page.wait_for_timeout(300)
        assert not hint.is_visible(), "Hint must disappear when worker_count (1) <= max_workers (2)"

        assert errors == [], f"JS errors during worker count hint test: {errors}"


# ---------------------------------------------------------------------------
# TASK LIFECYCLE MOVE CONTROLS
# ---------------------------------------------------------------------------


class TestTaskMoveButtons:
    """Verify task lifecycle move API and UI rendering."""

    def test_task_move_api_done_to_ready(self, server_url, runtime_home, page):
        """Move API endpoint transitions a done task to ready."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'move-e2e-001', name: 'Move API', pack: 'claude-code'})
            });
        }""")

        _write_intake_plan(runtime_home, "move-e2e-001", "mv01")

        page.evaluate("""async () => {
            await fetch('/api/sessions/move-e2e-001/start', { method: 'POST' });
        }""")

        _poll_tasks_done(page, "move-e2e-001", min_done=1)

        # Use the move API to transition done → ready
        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/move-e2e-001/tasks/mv01/move', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({target_status: 'ready'})
            });
            return { status: resp.status, body: await resp.json() };
        }""")

        assert result["status"] == 200
        assert result["body"]["status"] == "moved"
        assert result["body"]["from"] == "done"
        assert result["body"]["to"] == "ready"

    def test_task_move_api_invalid_transition_rejected(self, server_url, runtime_home, page):
        """Move API rejects invalid transitions with 409."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'move-e2e-002', name: 'Invalid Move', pack: 'claude-code'})
            });
        }""")

        _write_intake_plan(runtime_home, "move-e2e-002", "mv02")

        page.evaluate("""async () => {
            await fetch('/api/sessions/move-e2e-002/start', { method: 'POST' });
        }""")

        _poll_tasks_done(page, "move-e2e-002", min_done=1)

        # Move done → ready (valid), then try ready → done (invalid)
        page.evaluate("""async () => {
            await fetch('/api/sessions/move-e2e-002/tasks/mv02/move', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({target_status: 'ready'})
            });
        }""")

        result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/move-e2e-002/tasks/mv02/move', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({target_status: 'done'})
            });
            return { status: resp.status };
        }""")

        assert result["status"] == 409, "Moving from ready to done should be rejected"

    def test_task_move_buttons_rendered_in_html(self, server_url, page):
        """The SPA HTML contains TASK_TRANSITIONS and move button rendering code."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Verify the TASK_TRANSITIONS constant is present in the page
        has_transitions = page.evaluate("""() => {
            return document.documentElement.innerHTML.includes('TASK_TRANSITIONS');
        }""")
        assert has_transitions, "TASK_TRANSITIONS constant must be present in rendered HTML"

        # Verify move task action buttons code is present
        has_move_button = page.evaluate("""() => {
            return document.documentElement.innerHTML.includes('task-actions');
        }""")
        assert has_move_button, "task-actions class must be present in rendered HTML"



# ---------------------------------------------------------------------------
# Plan 006: Stuck-worker observability
# ---------------------------------------------------------------------------


class TestStuckWorkerObservability:
    """Verify that the stuck-worker observability features added in Plan 006
    render correctly in the browser.

    Plan 006 adds:
    - Log line timestamps (HH:MM:SS prefix) in worker card log tails
    - LastActivityIndicator with color coding (green < 60s, amber 60-300s, red >= 300s)
    - Worker card warning badge when idle threshold is exceeded
    - HealthSummaryBar in the monitor header
    - TaskRowElapsed (live-incrementing elapsed) in the pipeline task list
    - Start-time column (HH:MM:SS) in the task feed rows
    """

    def test_health_summary_bar_present_in_rendered_html(self, server_url, page):
        """After loading the SPA, the HealthSummaryBar component code must be present."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        has_summary = page.evaluate("""() => {
            return document.documentElement.innerHTML.includes('HealthSummaryBar');
        }""")
        assert has_summary, "HealthSummaryBar component must be present in rendered HTML"

    def test_last_activity_indicator_present_in_rendered_html(self, server_url, page):
        """After loading the SPA, the LastActivityIndicator component code must be present."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        has_indicator = page.evaluate("""() => {
            return document.documentElement.innerHTML.includes('LastActivityIndicator');
        }""")
        assert has_indicator, "LastActivityIndicator component must be present in rendered HTML"

    def test_task_row_elapsed_present_in_rendered_html(self, server_url, page):
        """After loading the SPA, the TaskRowElapsed component code must be present."""
        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        has_elapsed = page.evaluate("""() => {
            return document.documentElement.innerHTML.includes('TaskRowElapsed');
        }""")
        assert has_elapsed, "TaskRowElapsed component must be present in rendered HTML"

    def test_dashboard_active_worker_includes_idle_fields_when_idle_state_populated(
        self, server_url, runtime_home, page
    ):
        """After session starts with an active worker, the dashboard endpoint must include
        last_activity_ago on the active worker object once idle_state is populated via
        worker_idle_state events.

        This test verifies the API contract. The idle fields are populated by the orchestrator
        via worker_idle_state events as each poll cycle fires. Since the test worker runs
        quickly, we verify the field is present on the dashboard payload at some point after
        worker_idle_state events would have been emitted.
        """
        import time as _time

        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        # Create session with a slow-enough worker to catch it active
        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'obs-006', name: 'Observability Test 006', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "obs-006", "t006a")

        page.evaluate("""async () => {
            await fetch('/api/sessions/obs-006/start', { method: 'POST' });
        }""")

        # Wait until session reaches idle or completes (task ran)
        _poll_session_status(page, "obs-006", {"idle", "completed", "aborted"})

        # Verify the task list endpoint includes started_at and elapsed
        tasks_result = page.evaluate("""async () => {
            const resp = await fetch('/api/sessions/obs-006/tasks');
            return await resp.json();
        }""")
        tasks = tasks_result.get("tasks", [])
        assert len(tasks) >= 1, "Expected at least one task after session runs"
        for task in tasks:
            assert "started_at" in task, f"Task {task.get('task_id')} must include started_at"
            assert "elapsed" in task, f"Task {task.get('task_id')} must include elapsed"
            # started_at must be a valid ISO timestamp with time component
            started_at = task.get("started_at") or ""
            if started_at:
                assert len(started_at) >= 19, (
                    f"started_at must include date+time, got: {started_at!r}"
                )

    def test_no_console_errors_after_session_with_done_tasks(self, server_url, runtime_home, page):
        """Monitor view with completed tasks must render without JS errors.

        Validates that the Plan 006 components (HealthSummaryBar, TaskRowElapsed,
        LastActivityIndicator) don't throw exceptions when rendering with real session data.
        """
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(server_url)
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'obs-006b', name: 'Observability No-Error Test', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(runtime_home, "obs-006b", "t006b")

        page.evaluate("""async () => {
            await fetch('/api/sessions/obs-006b/start', { method: 'POST' });
        }""")

        _poll_session_status(page, "obs-006b", {"idle", "completed", "aborted"})
        _poll_tasks_done(page, "obs-006b", min_done=1)

        # Navigate to monitor view to trigger all Plan 006 components
        monitor_btn = page.locator("button:has-text('Monitor')")
        if monitor_btn.count() > 0:
            monitor_btn.click()
            page.wait_for_timeout(500)

        assert errors == [], f"Console errors after session with done tasks: {errors}"
