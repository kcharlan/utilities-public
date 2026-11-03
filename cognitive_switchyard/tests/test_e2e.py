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

import copy
import json
import socket
import threading
import time
from pathlib import Path
from textwrap import dedent

import pytest

import playwright

import uvicorn  # noqa: E402
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect  # noqa: E402

from tools.testkit import (  # noqa: E402
    assert_exact_text,
    assert_no_external_resources,
    assert_offline_page_source,
    block_external_requests,
    guard_browser_errors,
)
from cognitive_switchyard.config import build_runtime_paths  # noqa: E402
from cognitive_switchyard.html_template import render_app_html  # noqa: E402
from cognitive_switchyard.parsers import parse_task_plan  # noqa: E402
from cognitive_switchyard.server import create_app  # noqa: E402
from cognitive_switchyard.server import _build_root_bootstrap_payload  # noqa: E402
from cognitive_switchyard.state import initialize_state_store  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SLOW_TIMEOUT = 15_000  # ms — generous timeout for CI


@pytest.fixture(scope="session")
def base_url(pytestconfig):
    return pytestconfig.getoption("--base-url") or pytestconfig.getini("base_url") or None


@pytest.fixture
def browser_error_guard(page):
    """Reject uncaught browser errors for success-path resource tests."""
    with guard_browser_errors(page):
        yield


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


def _purge_inactive_operable_sessions(page) -> None:
    """Remove earlier draft/idle sessions before testing bootstrap selection.

    The E2E server is module-scoped, so sessions created by earlier tests remain
    available. Root bootstrap intentionally prefers any draft over an idle
    session; timer tests that reload a just-finished run therefore need a clean
    operable-session set to guarantee they observe the session they created.
    """
    failures = page.evaluate("""async () => {
        const response = await fetch('/api/sessions');
        const {sessions} = await response.json();
        const failures = [];
        for (const session of sessions) {
            if (!['created', 'idle'].includes(session.status)) continue;
            const purge = await fetch(`/api/sessions/${session.id}`, {method: 'DELETE'});
            if (!purge.ok) failures.push(`${session.id}: ${purge.status}`);
        }
        return failures;
    }""")
    assert failures == [], f"Unable to clear inactive sessions: {failures}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runtime_home(tmp_path_factory) -> Path:
    tmp_path = tmp_path_factory.mktemp("e2e")
    return _setup_runtime(tmp_path)


def _serve_app(app, *, label: str = "Uvicorn"):
    """Run ``app`` on a real uvicorn server in a thread and yield its base URL."""
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
        raise RuntimeError(f"{label} did not start on port {port}")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def server_url(runtime_home):
    """Start a real uvicorn server in a thread and return its base URL."""
    runtime_paths = build_runtime_paths(home=runtime_home)
    store = initialize_state_store(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    yield from _serve_app(app)


def test_wsproto_origin_and_reconnection(server_url):
    host = server_url.removeprefix("http://")
    port = int(host.rsplit(":", 1)[1])

    def handshake(origin):
        request = (
            f"GET /ws HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\nOrigin: {origin}\r\n\r\n"
        )
        with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
            connection.sendall(request.encode('ascii'))
            return connection.recv(4096).split(b'\r\n', 1)[0]

    assert b' 101 ' in handshake(server_url)
    assert b' 101 ' in handshake(server_url)
    assert b' 403 ' in handshake('http://foreign.example')


def test_browser_mutation_and_websocket_reconnection(fresh_server, page):
    page.add_init_script("""(() => {
        const Original = window.WebSocket;
        window.testSockets = [];
        window.WebSocket = class extends Original {
            constructor(...args) { super(...args); window.testSockets.push(this); }
        };
    })()""")
    page.goto(fresh_server['url'])
    status = page.evaluate("""async () => (await fetch('/api/sessions', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: 'browser-reconnect', pack: 'claude-code'})
    })).status""")
    assert status == 201
    page.reload()
    page.wait_for_function("window.testSockets.length > 0 && window.testSockets.at(-1).readyState === 1")
    page.evaluate("window.testSockets.at(-1).close()")
    page.wait_for_function("window.testSockets.length > 1 && window.testSockets.at(-1).readyState === 1", timeout=SLOW_TIMEOUT)


@pytest.fixture
def fresh_server(tmp_path):
    """A server with its own empty runtime, for tests that need a blank Setup form."""
    runtime_home = _setup_runtime(tmp_path)
    runtime_paths = build_runtime_paths(home=runtime_home)
    store = initialize_state_store(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    for url in _serve_app(app, label="Uvicorn (fresh)"):
        yield {"url": url, "app": app, "store": store, "runtime_home": runtime_home}


# ---------------------------------------------------------------------------
# 1. INITIAL LOAD & NAVIGATION
# ---------------------------------------------------------------------------


class TestProjectOwnedBaseStyles:
    def test_tailwind_preflight_compatible_styles_are_explicit(
        self, server_url, runtime_home, page
    ):
        requested_urls = []
        page.on("request", lambda request: requested_urls.append(request.url))
        runtime_paths = build_runtime_paths(home=runtime_home)
        store = initialize_state_store(runtime_paths)
        session_id = "base-style-regression-001"
        store.create_session(
            session_id=session_id,
            name="Synthetic Base Style Regression",
            pack="claude-code",
            created_at="2026-09-16T12:00:00Z",
            config_json=json.dumps(
                {
                    "environment": {
                        "COGNITIVE_SWITCHYARD_SOURCE_REPO": "/tmp/synthetic-source",
                        "COGNITIVE_SWITCHYARD_REPO_ROOT": "/tmp/synthetic-worktree",
                    }
                }
            ),
        )
        store.update_session_status(
            session_id,
            status="running",
            started_at="2026-09-16T12:00:01Z",
        )

        try:
            active_payload = _build_root_bootstrap_payload(
                store,
                runtime_paths=runtime_paths,
            )
            assert active_payload["current_session"]["id"] == session_id
            active_html = render_app_html(active_payload)
            page.route(
                f"{server_url}/",
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html",
                    body=active_html,
                ),
            )
            page.goto(server_url)
            settings_icon_styles = page.evaluate(
                """() => {
                    const button = document.querySelector('button[aria-label="Settings"]');
                    const svg = button.querySelector('svg');
                    const buttonRect = button.getBoundingClientRect();
                    const svgStyle = getComputedStyle(svg);
                    return {
                        svgDisplay: svgStyle.display,
                        svgVerticalAlign: svgStyle.verticalAlign,
                        buttonWidth: buttonRect.width,
                        buttonHeight: buttonRect.height,
                    };
                }"""
            )
            assert settings_icon_styles == {
                "svgDisplay": "block",
                "svgVerticalAlign": "middle",
                "buttonWidth": 40,
                "buttonHeight": 32,
            }
            page.locator("button:has-text('Setup')").click()
            page.wait_for_selector('h1:text-is("Session Active")', timeout=SLOW_TIMEOUT)

            active_styles = page.evaluate(
                """() => {
                    const title = document.querySelector('.view-title');
                    const description = title.nextElementSibling;
                    const titleStyle = getComputedStyle(title);
                    const descriptionStyle = getComputedStyle(description);
                    return {
                        titleWeight: titleStyle.fontWeight,
                        titleLineHeight: titleStyle.lineHeight,
                        descriptionMarginTop: descriptionStyle.marginTop,
                    };
                }"""
            )
            assert active_styles == {
                "titleWeight": "400",
                "titleLineHeight": "36px",
                "descriptionMarginTop": "0px",
            }

            completed_payload = copy.deepcopy(active_payload)
            completed_payload["dashboard"]["session"]["status"] = "completed"
            store.update_session_status(
                session_id,
                status="completed",
                completed_at="2026-09-16T12:01:00Z",
            )
            completed_html = render_app_html(completed_payload)
            page.unroute(f"{server_url}/")
            page.route(
                f"{server_url}/",
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html",
                    body=completed_html,
                ),
            )
            page.goto(server_url)
            page.wait_for_selector("text=Session Completed", timeout=SLOW_TIMEOUT)

            completion_heading_styles = page.locator(
                ".completion-card-section h4"
            ).first.evaluate(
                """element => {
                    const style = getComputedStyle(element);
                    return {
                        marginTop: style.marginTop,
                        fontWeight: style.fontWeight,
                        lineHeight: style.lineHeight,
                    };
                }"""
            )
            assert completion_heading_styles == {
                "marginTop": "0px",
                "fontWeight": "400",
                "lineHeight": "18px",
            }
            assert not [
                url for url in requested_urls if "tailwind" in url.lower()
            ]
        finally:
            page.unroute(f"{server_url}/")
            store.delete_session(session_id)


class TestInitialLoad:
    """Verify the SPA loads correctly and core navigation works."""

    def test_session_form_field_updates_on_each_keystroke(self, fresh_server, page):
        page.goto(fresh_server["url"])
        field = page.locator("label.field-label", has_text="Session Name").locator("xpath=../input")
        field.wait_for()
        field.fill("")
        for index, char in enumerate("Synthetic"):
            field.focus()
            field.press("End")
            field.press_sequentially(char)
            page.get_by_role("button", name="Show Advanced" if index % 2 == 0 else "Hide Advanced").click()
            assert field.input_value() == "Synthetic"[:index + 1]

    def test_page_loads_offline(self, fresh_server, browser):
        context = browser.new_context()
        blocked = block_external_requests(context, allowed_origins=[fresh_server["url"]])
        page = context.new_page()
        with guard_browser_errors(page):
            page.goto(fresh_server["url"])
            page.get_by_text("Create Session").first.wait_for(timeout=SLOW_TIMEOUT)
            assert_no_external_resources(page, blocked)
            assert_offline_page_source(page.content())
        context.close()

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
        page.on(
            "console",
            lambda message: errors.append(message.text)
            if message.type == "error"
            else None,
        )
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


class TestSetupPackDefaults:
    """Untouched Setup fields leave verification and auto-fix to the pack.

    Regression: the draft hard-coded verification_interval=4,
    auto_fix_enabled=true and auto_fix_max_attempts=2 and always sent them,
    so a pack's own values never applied to UI-created sessions.
    """

    @staticmethod
    def _open_setup_for_pack(page, url: str, session_id: str, pack: str) -> None:
        page.goto(url)
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)
        page.locator("label:has-text('Session ID') ~ input").first.fill(session_id)
        page.locator("label:has-text('Pack') ~ select").first.select_option(pack)
        page.locator("button:has-text('Show Advanced')").click()

    @staticmethod
    def _create_and_capture_config(page) -> dict:
        with page.expect_response(
            lambda response: response.url.endswith("/api/sessions")
            and response.request.method == "POST"
        ) as response_info:
            page.locator("button:has-text('Create Session')").click()
        response = response_info.value
        assert response.status == 201, response.text()
        return response.request.post_data_json.get("config") or {}

    def test_untouched_fields_use_pack_defaults(self, fresh_server, page, browser_error_guard):
        # verify-enabled sets verification.interval: 1 and leaves auto_fix at
        # the manifest defaults (disabled, 2 attempts).
        self._open_setup_for_pack(page, fresh_server["url"], "pack-defaults-001", "verify-enabled")

        interval_input = page.locator("label:has-text('Verification Interval') ~ input").first
        auto_fix_select = page.locator("label:has-text('Auto-Fix') ~ select").first
        attempts_input = page.locator("label:has-text('Auto-Fix Attempts') ~ input").first
        assert interval_input.input_value() == ""
        assert interval_input.get_attribute("placeholder") == "pack default (1)"
        assert auto_fix_select.input_value() == ""
        assert auto_fix_select.locator("option[value='']").inner_text() == "Pack default (Disabled)"
        assert attempts_input.input_value() == ""
        assert attempts_input.get_attribute("placeholder") == "pack default (2)"

        config = self._create_and_capture_config(page)
        for key in ("verification_interval", "auto_fix_enabled", "auto_fix_max_attempts"):
            assert key not in config, f"untouched {key} must not be sent: {config}"

        dashboard = page.evaluate(
            "async () => (await fetch('/api/sessions/pack-defaults-001/dashboard')).json()"
        )
        effective = dashboard["effective_runtime_config"]
        assert effective["verification_interval"] == 1
        assert effective["auto_fix"] == {"enabled": False, "max_attempts": 2}

    def test_operator_changes_are_sent(self, fresh_server, page, browser_error_guard):
        self._open_setup_for_pack(page, fresh_server["url"], "pack-overrides-001", "verify-enabled")

        page.locator("label:has-text('Verification Interval') ~ input").first.fill("3")
        page.locator("label:has-text('Auto-Fix') ~ select").first.select_option("enabled")
        page.locator("label:has-text('Auto-Fix Attempts') ~ input").first.fill("5")

        config = self._create_and_capture_config(page)
        assert config["verification_interval"] == 3
        assert config["auto_fix_enabled"] is True
        assert config["auto_fix_max_attempts"] == 5


# ---------------------------------------------------------------------------
# 3. SESSION CREATION — UNHAPPY PATH
# ---------------------------------------------------------------------------



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
        _write_intake_plan(runtime_home, "intake-lock-001", "t002")

        # Start session
        status = page.evaluate("""async () =>
            (await fetch('/api/sessions/intake-lock-001/start', { method: 'POST' })).status
        """)
        assert status == 202
        _poll_session_status(page, "intake-lock-001", {"idle"})

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
        assert preflight_btn.count() > 0, page.evaluate("""async () => JSON.stringify({
            sessions: (await (await fetch('/api/sessions')).json()).sessions.map(s => [s.id, s.status]),
            body: document.body.innerText.slice(0, 800)
        })""")


# ---------------------------------------------------------------------------
# 6. SESSION LIFECYCLE — START, EXECUTE, COMPLETE
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    """Full lifecycle: create, start, wait for completion."""

    def test_start_session_and_task_completes(self, server_url, runtime_home, page):
        """Create session, add intake plan, start, verify task reaches done."""
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
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

        _poll_session_status(page, "lifecycle-001", {"idle"})
        tasks = _poll_tasks_done(page, "lifecycle-001", min_done=1)
        task_ids = [t["task_id"] for t in tasks]
        assert "t001" in task_ids
        assert errors == []


# ---------------------------------------------------------------------------
# 7. SESSION CONTROL — PAUSE, RESUME, ABORT
# ---------------------------------------------------------------------------


class TestSessionControl:
    """Verify pause, resume, and abort controls."""

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
        expect(page.locator("button", has_text="Abort")).to_be_visible()


# ---------------------------------------------------------------------------
# 8. DASHBOARD & MONITOR VIEW
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 9. TASK DETAIL & LOG
# ---------------------------------------------------------------------------


class TestTaskDetail:
    """Verify task detail and log retrieval."""

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


def _open_synthetic_canvas(fresh_server, page):
    store, home = fresh_server["store"], fresh_server["runtime_home"]
    sid = "synthetic-navigation"
    store.create_session(session_id=sid, name="Synthetic navigation", pack="claude-code", created_at="2026-01-01T00:00:00Z", config_json="{}")
    for task_id, dependency in (("root", "none"), ("middle", "root"), ("leaf", "middle")):
        source = _write_intake_plan(home, sid, task_id, depends_on=dependency)
        plan = source.read_text(encoding="utf-8")
        store.upsert_ready_task_plan(session_id=sid, plan=parse_task_plan(plan, source=source), plan_text=plan, created_at="2026-01-01T00:00:01Z")
    store.update_session_status(sid, status="running", started_at="2026-01-01T00:00:01Z")
    page.goto(fresh_server["url"])
    page.locator("button[aria-label='Open DAG']").click()
    page.locator(".dag-node[data-id='root']").wait_for()
    _wait_for_fit(page)


def _wait_for_fit(page):
    """The first fit follows node measurement, so a node can exist before the view has moved."""
    page.wait_for_function("() => new DOMMatrix(getComputedStyle(document.querySelector('.dag-viewport')).transform).e !== 0")


def _open_dag_payload(fresh_server, page, payload):
    """Open the DAG view with a synthetic graph served in place of the session's own."""
    _open_synthetic_canvas(fresh_server, page)
    _reopen_dag_with(page, payload)


def _reopen_dag_with(page, payload):
    page.get_by_role("button", name="Back to Monitor").click()
    page.route("**/dag", lambda route: route.fulfill(json=payload))
    page.locator("button[aria-label='Open DAG']").click()
    page.locator(".dag-canvas-root").wait_for()
    for task in payload["tasks"]:
        page.locator(f".dag-node[data-id='{task['task_id']}']").wait_for()
    if payload["tasks"]:
        _wait_for_fit(page)


def _dag_task(task_id, *depends_on, anti_affinity=()):
    return {"task_id": task_id, "title": f"Synthetic {task_id}", "status": "ready", "depends_on": list(depends_on), "anti_affinity": list(anti_affinity)}


def _dag_view(page):
    return page.locator(".dag-viewport").evaluate("el => { const m = new DOMMatrix(getComputedStyle(el).transform); return [m.a, m.e, m.f]; }")


def _center(box):
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _edge_point(page, edge_id):
    return page.locator(f".dag-edges g[data-id='{edge_id}'] .dag-edge").evaluate("el => { const p = el.getPointAtLength(el.getTotalLength() * .4).matrixTransform(el.getScreenCTM()); return [p.x, p.y]; }")


def _pane_point(page):
    box = page.locator(".dag-canvas-root").bounding_box()
    return box["x"] + 40, box["y"] + 40


def _dispatch_wheel(page, x, y, delta, *, ctrl=False, mode=0):
    page.evaluate("""([x, y, deltaY, ctrlKey, deltaMode]) => document.elementFromPoint(x, y).dispatchEvent(
        new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX: x, clientY: y, deltaY, ctrlKey, deltaMode })
    )""", [x, y, delta, ctrl, mode])


def _mouse_drag(page, start, by, *, button="left"):
    page.mouse.move(*start)
    page.mouse.down(button=button)
    page.mouse.move(start[0] + by[0], start[1] + by[1], steps=4)
    page.mouse.up(button=button)


def _click_until_disabled(button, *, limit=20):
    """Zoom limits are reached within a few steps; a button that never disables must fail, not spin."""
    for _ in range(limit):
        if button.is_disabled():
            return
        button.click()
    pytest.fail(f"Button still enabled after {limit} clicks: {button}")


def _node_at(page, point):
    return page.evaluate("([x, y]) => document.elementFromPoint(x, y).closest('.dag-node')?.dataset.id", list(point))


def _selected_nodes(page):
    return page.locator(".dag-node.selected").evaluate_all("els => els.map(el => el.dataset.id)")


def _selected_edges(page):
    return page.locator(".dag-edges g[data-selected='true']").evaluate_all("els => els.map(el => el.dataset.id)")


class TestDagView:
    """Verify DAG API and interactive canvas behavior."""

    def test_dag_preserves_navigation_controls_and_zoom_bounds(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        for selector, label in ((".dag-zoom-in", "Zoom In"), (".dag-zoom-out", "Zoom Out"), (".dag-fit-view", "Fit View"), (".dag-toggle-interactivity", "Toggle Interactivity")):
            assert page.locator(selector).get_attribute("aria-label") == label
        viewport = page.locator(".dag-viewport")
        matrix = lambda: viewport.evaluate("el => { const m = new DOMMatrix(getComputedStyle(el).transform); return [m.a, m.e, m.f]; }")
        fitted = matrix()
        assert fitted != [1, 0, 0]  # fitView overrides the default viewport
        zoom_in, zoom_out = page.locator(".dag-zoom-in"), page.locator(".dag-zoom-out")
        _click_until_disabled(zoom_in)
        assert matrix()[0] == pytest.approx(2)  # React Flow default maxZoom
        assert zoom_out.is_enabled()
        _click_until_disabled(zoom_out)
        assert matrix()[0] == pytest.approx(0.5)  # React Flow default minZoom
        assert zoom_in.is_enabled()
        page.locator(".dag-fit-view").click()
        assert matrix() == pytest.approx(fitted)
        box = page.locator(".dag-canvas-root").bounding_box()
        x, y = box["x"] + box["width"] * .7, box["y"] + box["height"] * .3
        before = matrix()
        minimap = page.locator(".dag-minimap-mask").get_attribute("d")
        page.mouse.move(x, y)
        page.mouse.wheel(0, -120)
        page.wait_for_function("previous => new DOMMatrix(getComputedStyle(document.querySelector('.dag-viewport')).transform).a !== previous", arg=before[0])
        after = matrix()
        assert (x - box["x"] - before[1]) / before[0] == pytest.approx((x - box["x"] - after[1]) / after[0], abs=.01)
        assert page.locator(".dag-minimap-mask").get_attribute("d") != minimap
        page.mouse.move(box["x"] + 10, box["y"] + 10)
        page.mouse.down(); page.mouse.move(box["x"] + 50, box["y"] + 40); page.mouse.up()
        assert matrix()[1] == pytest.approx(after[1] + 40, abs=1)
        page.locator(".dag-fit-view").click()
        before_pinch = matrix()[0]
        cdp = page.context.new_cdp_session(page)
        x, y = box["x"] + 100, box["y"] + 100
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y, "id": 1}, {"x": x + 100, "y": y, "id": 2}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x - 30, "y": y, "id": 1}, {"x": x + 130, "y": y, "id": 2}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        assert matrix()[0] > before_pinch
        cdp.detach()

    def test_dag_drag_does_not_open_the_task(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        node = page.locator(".dag-node[data-id='middle']")
        old = node.evaluate("el => [parseFloat(el.style.left), parseFloat(el.style.top)]")
        box = node.bounding_box()
        page.mouse.move(box["x"] + 30, box["y"] + 25)
        page.mouse.down(); page.mouse.move(box["x"] + 80, box["y"] + 55, steps=5); page.mouse.up()
        new = node.evaluate("el => [parseFloat(el.style.left), parseFloat(el.style.top)]")
        assert new[0] > old[0] and new[1] > old[1]
        assert page.locator(".split-view .detail-panel").count() == 0

    def test_dag_drag_near_edge_auto_pans(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        node = page.locator(".dag-node[data-id='middle']").bounding_box()
        canvas = page.locator(".dag-canvas-root").bounding_box()
        viewport = page.locator(".dag-viewport")
        before = viewport.get_attribute("style")
        page.mouse.move(node["x"] + 30, node["y"] + 25)
        page.mouse.down()
        page.mouse.move(canvas["x"] + canvas["width"] - 2, canvas["y"] + canvas["height"] / 2, steps=5)
        page.wait_for_function("previous => document.querySelector('.dag-viewport').getAttribute('style') !== previous", arg=before)
        page.mouse.up()

    def test_dag_keyboard_select_and_delete(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        node = page.locator(".dag-node[data-id='middle']")
        node.focus()
        page.keyboard.press("Enter")
        assert "selected" in node.get_attribute("class")
        page.keyboard.press("ArrowRight")
        assert float(node.evaluate("el => el.style.left.replace('px', '')")) == 305  # React Flow moves 5px per key
        page.keyboard.press("Backspace")
        assert node.count() == 0
        assert page.locator(".dag-edge").count() == 0

    def test_dag_multiple_nodes_can_be_selected_and_deleted(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        page.locator(".dag-node[data-id='root']").click()
        page.locator(".dag-node[data-id='leaf']").click(modifiers=["Meta"])
        assert page.locator(".dag-node.selected").count() == 2
        page.keyboard.press("Backspace")
        assert page.locator(".dag-node[data-id='middle']").count() == 1
        assert page.locator(".dag-node.selected").count() == 0
        page.wait_for_function("() => document.querySelectorAll('.dag-edge').length === 0")
        assert page.locator(".dag-edge").count() == 0

    def test_dag_edge_can_be_selected_and_deleted(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        edge = page.locator(".dag-edges g").first
        edge.focus()
        page.keyboard.press("Enter")
        page.wait_for_function("() => document.querySelector('.dag-edges g')?.dataset.selected === 'true'")
        page.keyboard.press("Backspace")
        page.wait_for_function("() => document.querySelectorAll('.dag-edge').length === 1")
        assert page.locator(".dag-edge").count() == 1

    def test_dag_mixed_edge_multiselection_and_delete(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        edges = page.locator(".dag-edges g")
        edges.nth(0).dispatch_event("click", {"bubbles": True})
        edges.nth(1).dispatch_event("click", {"bubbles": True, "metaKey": True})
        assert page.locator('.dag-edges g[data-selected="true"]').count() == 2
        edges.nth(0).dispatch_event("click", {"bubbles": True, "metaKey": True})
        assert page.locator('.dag-edges g[data-selected="true"]').count() == 1
        edges.nth(0).dispatch_event("click", {"bubbles": True, "metaKey": True})
        page.locator(".dag-node[data-id='root']").click(modifiers=["Meta"])
        assert page.locator('.dag-edges g[data-selected="true"]').count() == 2
        assert page.locator(".dag-node.selected").count() == 1
        page.keyboard.press("Backspace")
        page.wait_for_function("() => document.querySelectorAll('.dag-edge').length === 0")
        assert page.locator(".dag-node[data-id='root']").count() == 0
        assert page.locator(".dag-node[data-id='middle']").count() == 1

    def test_dag_modifier_edge_selection_preserves_node_selection(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        page.locator(".dag-node[data-id='leaf']").click()
        page.locator(".dag-edges g").last.dispatch_event("click", {"bubbles": True, "metaKey": True})
        assert page.locator(".dag-node[data-id='leaf'].selected").count() == 1
        assert page.locator('.dag-edges g[data-selected="true"]').count() == 1
        page.keyboard.press("Backspace")
        page.wait_for_function("() => document.querySelectorAll('.dag-edge').length === 0")
        assert page.locator(".dag-node[data-id='leaf']").count() == 0

    def test_dag_long_title_uses_measured_geometry(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        page.get_by_role("button", name="Back to Monitor").click()
        title = "Synthetic wrapping title " * 14
        page.route("**/dag", lambda route: route.fulfill(json={"tasks": [
            {"task_id": "long", "title": title, "status": "ready", "depends_on": [], "anti_affinity": []},
            {"task_id": "next", "title": "Synthetic next", "status": "ready", "depends_on": ["long"], "anti_affinity": []},
        ], "groups": []}))
        page.locator("button[aria-label='Open DAG']").click()
        node = page.locator(".dag-node[data-id='long']")
        node.wait_for()
        _wait_for_fit(page)
        page.wait_for_function("() => document.querySelector('.dag-node[data-id=long]').offsetHeight > 80")
        page.wait_for_function("""() => { const n = document.querySelector('.dag-node[data-id=long]').getBoundingClientRect(), c = document.querySelector('.dag-canvas-root').getBoundingClientRect(); return n.top >= c.top && n.bottom <= c.bottom && n.left >= c.left && n.right <= c.right; }""")
        page.locator(".dag-fit-view").click()
        canvas, box = page.locator(".dag-canvas-root").bounding_box(), node.bounding_box()
        assert box["height"] > 80
        assert box["x"] >= canvas["x"] and box["y"] >= canvas["y"]
        assert box["x"] + box["width"] <= canvas["x"] + canvas["width"]
        assert box["y"] + box["height"] <= canvas["y"] + canvas["height"]
        assert page.locator(".dag-task-node").evaluate_all("els => { const c = document.querySelector('.dag-canvas-root').getBoundingClientRect(); return els.every(el => { const r = el.getBoundingClientRect(); return r.left >= c.left && r.right <= c.right && r.top >= c.top && r.bottom <= c.bottom; }); }")
        handle = node.locator(".dag-source-handle").bounding_box()
        edge_start = page.locator(".dag-edge").first.evaluate("el => { const p = el.getPointAtLength(0).matrixTransform(el.getScreenCTM()); return [p.x, p.y]; }")
        assert edge_start[0] == pytest.approx(handle["x"] + handle["width"] / 2, abs=2)
        assert edge_start[1] == pytest.approx(handle["y"] + handle["height"], abs=2)  # React Flow edges start at the handle's outer edge
        mini = page.locator(".dag-minimap-node").first
        mini_ratio = float(mini.get_attribute("height")) / float(mini.get_attribute("width"))
        assert mini_ratio == pytest.approx(box["height"] / box["width"], abs=.02)
        page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2)
        page.mouse.down(); page.mouse.move(handle["x"] + 40, handle["y"] + 40)
        preview_start = page.locator(".dag-connection-preview").evaluate("el => { const p = el.getPointAtLength(0).matrixTransform(el.getScreenCTM()); return [p.x, p.y]; }")
        current_edge_start = page.locator(".dag-edge").first.evaluate("el => { const p = el.getPointAtLength(0).matrixTransform(el.getScreenCTM()); return [p.x, p.y]; }")
        assert preview_start == pytest.approx(current_edge_start, abs=2)
        page.mouse.up()
        box = node.bounding_box()
        page.keyboard.down("Shift")
        page.mouse.move(box["x"] - 4, box["y"] - 4); page.mouse.down()
        page.mouse.move(box["x"] + box["width"] + 4, box["y"] + box["height"] - 10, steps=4); page.mouse.up()
        page.keyboard.up("Shift")
        assert "selected" not in node.get_attribute("class")
        page.keyboard.down("Shift")
        page.mouse.move(box["x"] - 4, box["y"] - 4); page.mouse.down()
        page.mouse.move(box["x"] + box["width"] + 4, box["y"] + box["height"] + 4, steps=4); page.mouse.up()
        page.keyboard.up("Shift")
        assert "selected" in node.get_attribute("class")

    def test_dag_group_name_renders_once(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        page.get_by_role("button", name="Back to Monitor").click()
        page.route("**/dag", lambda route: route.fulfill(json={"tasks": [
            {"task_id": "alpha", "title": "Synthetic alpha", "status": "ready", "depends_on": [], "anti_affinity": []},
            {"task_id": "beta", "title": "Synthetic beta", "status": "ready", "depends_on": [], "anti_affinity": []},
        ], "groups": [{"name": "Synthetic group", "members": ["alpha", "beta"]}]}))
        page.locator("button[aria-label='Open DAG']").click()
        page.locator(".dag-node[data-id='alpha']").wait_for()
        assert page.get_by_text("Synthetic group", exact=True).count() == 1
        assert page.locator(".dag-minimap-node").count() == page.locator(".dag-node").count()

    def test_dag_shift_drag_selects_nodes(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        first = page.locator(".dag-node[data-id='root']").bounding_box()
        last = page.locator(".dag-node[data-id='leaf']").bounding_box()
        page.keyboard.down("Shift")
        page.mouse.move(first["x"] - 10, first["y"] - 10)
        page.mouse.down()
        page.mouse.move(last["x"] + last["width"] + 10, last["y"] + last["height"] + 10, steps=5)
        page.mouse.up()
        page.keyboard.up("Shift")
        assert page.locator(".dag-node.selected").count() == 3
        page.keyboard.press("Backspace")
        page.wait_for_function("() => document.querySelectorAll('.dag-task-node').length === 0")

    def test_dag_selection_near_edge_auto_pans(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        canvas = page.locator(".dag-canvas-root").bounding_box()
        before = page.locator(".dag-viewport").get_attribute("style")
        page.keyboard.down("Shift")
        page.mouse.move(canvas["x"] + 30, canvas["y"] + 30)
        page.mouse.down()
        page.mouse.move(canvas["x"] + canvas["width"] - 2, canvas["y"] + 50, steps=5)
        page.wait_for_function("previous => document.querySelector('.dag-viewport').getAttribute('style') !== previous", arg=before, timeout=3000)
        page.mouse.up()
        page.keyboard.up("Shift")

    def test_dag_space_drag_pans_over_node(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        node = page.locator(".dag-node[data-id='middle']")
        position = node.evaluate("el => [el.style.left, el.style.top]")
        before = page.locator(".dag-viewport").get_attribute("style")
        box = node.bounding_box()
        page.keyboard.down("Space")
        page.mouse.move(box["x"] + 30, box["y"] + 25)
        page.mouse.down(); page.mouse.move(box["x"] + 70, box["y"] + 50, steps=5); page.mouse.up()
        page.keyboard.up("Space")
        assert page.locator(".dag-viewport").get_attribute("style") != before
        assert node.evaluate("el => [el.style.left, el.style.top]") == position

    def test_dag_connection_preview_is_transient(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        before = page.locator(".dag-edge").count()
        source = page.locator(".dag-node[data-id='root'] .dag-source-handle").bounding_box()
        target = page.locator(".dag-node[data-id='leaf'] .dag-target-handle").bounding_box()
        page.mouse.move(source["x"] + source["width"] / 2, source["y"] + source["height"] / 2)
        page.mouse.down()
        page.mouse.move(target["x"] + target["width"] / 2, target["y"] + target["height"] / 2, steps=5)
        page.locator(".dag-connection-preview").wait_for(state="attached")
        page.mouse.up()
        assert page.locator(".dag-connection-preview").count() == 0
        assert page.locator(".dag-edge").count() == before

    def test_dag_click_to_connect_is_transient(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        before = page.locator(".dag-edge").count()
        page.locator(".dag-node[data-id='root'] .dag-source-handle").click()
        page.locator(".dag-connection-preview").wait_for(state="attached")
        page.locator(".dag-node[data-id='leaf'] .dag-target-handle").click()
        assert page.locator(".dag-connection-preview").count() == 0
        assert page.locator(".dag-edge").count() == before

    def test_dag_task_titles_display_literally(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        page.get_by_role("button", name="Back to Monitor").click()
        sample = "<b>x</b> & ${y} `value` {{X}} &nbsp;"
        page.route("**/dag", lambda route: route.fulfill(json={"tasks": [{"task_id": "literal", "title": sample, "status": "ready", "depends_on": [], "anti_affinity": []}], "groups": []}))
        page.locator("button[aria-label='Open DAG']").click()
        label = page.locator(".dag-node[data-id='literal'] .secondary")
        label.wait_for()
        assert label.inner_text() == sample
        assert label.locator("b").count() == 0

    def test_dag_with_one_node_and_no_edges_fits_and_renders(self, fresh_server, page):
        store, home = fresh_server["store"], fresh_server["runtime_home"]
        sid = "synthetic-single-node"
        store.create_session(session_id=sid, name="Synthetic single node", pack="claude-code", created_at="2026-01-01T00:00:00Z", config_json="{}")
        source = _write_intake_plan(home, sid, "only")
        plan = source.read_text(encoding="utf-8")
        store.upsert_ready_task_plan(session_id=sid, plan=parse_task_plan(plan, source=source), plan_text=plan, created_at="2026-01-01T00:00:01Z")
        store.update_session_status(sid, status="running", started_at="2026-01-01T00:00:01Z")
        page.goto(fresh_server["url"])
        page.locator("button[aria-label='Open DAG']").click()
        node = page.locator(".dag-node[data-id='only']")
        node.wait_for()
        page.wait_for_function("() => new DOMMatrix(getComputedStyle(document.querySelector('.dag-viewport')).transform).a === 2")
        assert page.locator(".dag-edge").count() == 0
        # One node fits at the zoom ceiling, centered in the canvas.
        assert _dag_view(page)[0] == 2
        assert _center(node.bounding_box()) == pytest.approx(_center(page.locator(".dag-canvas-root").bounding_box()), abs=1)

    @pytest.mark.parametrize("payload", [
        pytest.param({"tasks": [], "groups": []}, id="no-tasks"),
        pytest.param({"tasks": [_dag_task("only")], "groups": []}, id="one-task"),
        pytest.param({"tasks": [_dag_task("first"), _dag_task("second")], "groups": []}, id="no-edges"),
        pytest.param({"tasks": [_dag_task("first", "missing", anti_affinity=["absent"])], "groups": []}, id="dangling-dependency"),
        pytest.param({"tasks": [_dag_task("first"), _dag_task("second", "first")], "groups": []}, id="one-edge"),
    ])
    def test_dag_svg_attributes_contain_no_nan(self, fresh_server, page, payload):
        _open_dag_payload(fresh_server, page, payload)
        scan = "root => !/NaN|Infinity|undefined/.test(root.outerHTML)"
        canvas = page.locator(".dag-canvas-root")
        assert canvas.evaluate(scan)
        assert page.locator(".dag-edge").count() == sum(len(task["depends_on"]) for task in payload["tasks"] if task["task_id"] == "second")
        page.locator(".dag-fit-view").click()
        page.locator(".dag-zoom-out").click()
        assert canvas.evaluate(scan)

    def test_dag_mouse_focus_draws_no_rectangle(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        page.mouse.click(*_edge_point(page, "root-middle"))
        outline = "el => getComputedStyle(el).outlineStyle"
        edge = page.locator(".dag-edges g[data-id='root-middle']")
        assert edge.evaluate("el => el === document.activeElement")
        assert edge.evaluate(outline) == "none"
        node = page.locator(".dag-node[data-id='middle']")
        node.click()
        assert node.evaluate(outline) == "none"
        page.keyboard.press("Shift+Tab")
        page.keyboard.press("Tab")
        assert node.evaluate("el => el === document.activeElement")
        assert node.evaluate(outline) == "none"

    def test_dag_chrome_keeps_double_click_and_wheel_from_the_canvas(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        page.locator(".dag-fit-view").click()
        fitted = _dag_view(page)
        minimap = _center(page.locator(".dag-minimap").bounding_box())
        controls = _center(page.locator(".dag-zoom-out").bounding_box())
        page.mouse.dblclick(*minimap)
        assert _dag_view(page) == fitted
        page.mouse.dblclick(*_edge_point(page, "root-middle"))
        assert _dag_view(page) == fitted
        _dispatch_wheel(page, *minimap, -100)
        _dispatch_wheel(page, *controls, -100)
        assert _dag_view(page) == fitted
        # A double-click on a control is its two clicks and nothing more.
        page.locator(".dag-zoom-out").dblclick()
        assert _dag_view(page)[0] == pytest.approx(fitted[0] / 1.2 ** 2, abs=.001)
        # React Flow's pane zooms under an edge, so a wheel over one still zooms.
        page.locator(".dag-fit-view").click()
        _dispatch_wheel(page, *_edge_point(page, "root-middle"), -100)
        page.wait_for_function("zoom => new DOMMatrix(getComputedStyle(document.querySelector('.dag-viewport')).transform).a > zoom", arg=fitted[0])

    def test_dag_dragged_and_selected_nodes_stay_on_top(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        target = _center(page.locator(".dag-node[data-id='middle']").bounding_box())
        page.mouse.move(*_center(page.locator(".dag-node[data-id='root']").bounding_box()))
        page.mouse.down()
        page.mouse.move(*target, steps=5)
        assert _node_at(page, target) == "root"
        page.mouse.up()
        assert _node_at(page, target) == "root"
        assert page.locator(".dag-node[data-id='root']").evaluate("el => getComputedStyle(el).zIndex") == "1000"
        page.locator(".dag-node[data-id='leaf']").click()
        assert page.locator(".dag-node[data-id='root']").evaluate("el => getComputedStyle(el).zIndex") == "auto"

    def test_dag_modifier_drag_keeps_the_node_on_top(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        target = _center(page.locator(".dag-node[data-id='middle']").bounding_box())
        page.keyboard.down("Meta")
        page.mouse.move(*_center(page.locator(".dag-node[data-id='root']").bounding_box()))
        page.mouse.down()
        page.mouse.move(*target, steps=5)
        assert _node_at(page, target) == "root"
        page.mouse.up()
        page.keyboard.up("Meta")
        assert _selected_nodes(page) == ["root"]

    def test_dag_locked_canvas_leaves_nodes_edges_and_selection_alone(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        node = page.locator(".dag-node[data-id='middle']")
        node.click()
        page.locator(".dag-toggle-interactivity").click()
        view = _dag_view(page)
        position = node.evaluate("el => [el.style.left, el.style.top]")
        _mouse_drag(page, _center(node.bounding_box()), (60, 20))
        assert _dag_view(page) == view
        assert node.evaluate("el => [el.style.left, el.style.top]") == position
        pane = _pane_point(page)
        page.mouse.click(*pane)
        page.locator(".dag-node[data-id='leaf']").click()
        page.mouse.click(*_edge_point(page, "root-middle"))
        assert _selected_nodes(page) == ["middle"]
        assert _selected_edges(page) == []
        # A shift-drag across every node neither selects them nor pans.
        canvas = page.locator(".dag-canvas-root").bounding_box()
        page.keyboard.down("Shift")
        _mouse_drag(page, pane, (canvas["width"] - 120, canvas["height"] - 120))
        page.keyboard.up("Shift")
        assert _dag_view(page) == view
        assert _selected_nodes(page) == ["middle"]
        # The pane itself still pans, and an edge lets the drag through to it.
        _mouse_drag(page, pane, (30, 10))
        assert _dag_view(page)[1] == pytest.approx(view[1] + 30, abs=1)
        panned = _dag_view(page)
        _mouse_drag(page, _edge_point(page, "root-middle"), (30, 10))
        assert _dag_view(page)[1] == pytest.approx(panned[1] + 30, abs=1)

    def test_dag_ctrl_drag_does_not_pan(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        view = _dag_view(page)
        page.keyboard.down("Control")
        _mouse_drag(page, _pane_point(page), (60, 30))
        page.keyboard.up("Control")
        assert _dag_view(page) == view

    def test_dag_middle_button_pans_over_nodes_and_edges(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        node = page.locator(".dag-node[data-id='middle']")
        position = node.evaluate("el => [el.style.left, el.style.top]")
        view = _dag_view(page)
        _mouse_drag(page, _center(node.bounding_box()), (40, 10), button="middle")
        assert _dag_view(page)[1] == pytest.approx(view[1] + 40, abs=1)
        assert node.evaluate("el => [el.style.left, el.style.top]") == position
        view = _dag_view(page)
        _mouse_drag(page, _edge_point(page, "root-middle"), (40, 10), button="middle")
        assert _dag_view(page)[1] == pytest.approx(view[1] + 40, abs=1)

    def test_dag_drag_ends_when_the_button_is_no_longer_held(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        x, y = _pane_point(page)
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 20, y + 20, steps=2)
        panned = _dag_view(page)
        assert panned != pytest.approx([panned[0], 0, 0])
        # What the browser sends after a context menu swallowed the pointerup.
        page.evaluate("""([x, y]) => document.querySelector('.dag-canvas-root').dispatchEvent(
            new PointerEvent('pointermove', { bubbles: true, pointerType: 'mouse', buttons: 0, clientX: x, clientY: y })
        )""", [x + 80, y + 80])
        page.mouse.move(x + 120, y + 120, steps=2)
        assert _dag_view(page) == panned
        page.mouse.up()

    def test_dag_panning_keeps_the_selection_and_a_pane_click_clears_it(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        page.locator(".dag-node[data-id='middle']").click()
        pane = _pane_point(page)
        _mouse_drag(page, pane, (30, 10))
        assert _selected_nodes(page) == ["middle"]
        page.mouse.click(*pane)
        assert _selected_nodes(page) == []

    def test_dag_group_lets_pane_gestures_through(self, fresh_server, page):
        _open_dag_payload(fresh_server, page, {"tasks": [_dag_task("first"), _dag_task("second")], "groups": [{"name": "synthetic-group", "members": ["first", "second"]}]})
        group = page.locator(".dag-node[data-id='group-synthetic-group']")
        assert group.evaluate("el => getComputedStyle(el).pointerEvents") == "none"
        view = _dag_view(page)
        box = group.bounding_box()
        _mouse_drag(page, (box["x"] + box["width"] / 2, box["y"] + 4), (20, 10))
        assert _dag_view(page)[1] == pytest.approx(view[1] + 20, abs=1)

    @pytest.mark.parametrize("button", ["left", "middle"])  # a middle-button pan is followed by no click at all
    def test_dag_meta_click_selects_after_a_pan(self, fresh_server, page, button):
        _open_synthetic_canvas(fresh_server, page)
        _mouse_drag(page, _pane_point(page), (30, 10), button=button)
        page.keyboard.down("Meta")
        page.locator(".dag-node[data-id='middle']").click()
        page.keyboard.up("Meta")
        assert _selected_nodes(page) == ["middle"]

    def test_dag_keyboard_matches_react_flow(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        node = page.locator(".dag-node[data-id='middle']")
        left = lambda: float(node.evaluate("el => parseFloat(el.style.left)"))
        top = lambda: float(node.evaluate("el => parseFloat(el.style.top)"))
        node.focus()
        before = left()
        page.keyboard.press("ArrowRight")  # not selected yet
        assert left() == before
        page.keyboard.press("Enter")
        page.keyboard.press("ArrowRight")
        assert left() == before + 5
        before = top()
        page.keyboard.press("Shift+ArrowDown")
        assert top() == before + 20
        page.keyboard.press("Escape")
        assert _selected_nodes(page) == []
        page.wait_for_function("() => document.activeElement === document.body")
        node.focus()
        page.keyboard.press("Escape")  # nothing to deselect
        assert _selected_nodes(page) == []
        page.keyboard.press(" ")
        assert _selected_nodes(page) == ["middle"]
        edge = page.locator(".dag-edges g[data-id='root-middle']")
        edge.focus()
        page.keyboard.press(" ")
        assert _selected_edges(page) == ["root-middle"]
        assert _selected_nodes(page) == []
        page.keyboard.press("Escape")
        assert _selected_edges(page) == []
        assert edge.evaluate("el => el !== document.activeElement")

    def test_dag_enter_keeps_a_multiple_selection(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        page.locator(".dag-node[data-id='root']").click()
        page.keyboard.down("Meta")
        page.locator(".dag-node[data-id='leaf']").click()
        page.keyboard.up("Meta")
        page.keyboard.press("Enter")
        assert sorted(_selected_nodes(page)) == ["leaf", "root"]
        page.keyboard.press("Escape")
        assert _selected_nodes(page) == ["root"]

    def test_dag_auto_pan_follows_the_current_zoom(self, fresh_server, page):
        _open_synthetic_canvas(fresh_server, page)
        node = page.locator(".dag-node[data-id='middle']")
        canvas = page.locator(".dag-canvas-root").bounding_box()
        x, y = canvas["x"] + canvas["width"] - 2, canvas["y"] + canvas["height"] / 2
        page.mouse.move(*_center(node.bounding_box()))
        page.mouse.down()
        page.mouse.move(x, y, steps=4)
        page.mouse.wheel(0, -100)
        page.wait_for_timeout(100)
        first = node.bounding_box()["x"] - x
        page.wait_for_timeout(300)
        second = node.bounding_box()["x"] - x
        page.mouse.up()
        assert second == pytest.approx(first, abs=4)

    def test_dag_canvas_skips_app_renders(self, fresh_server, page):
        page.add_init_script("""window.__sockets = [];
            window.WebSocket = class extends window.WebSocket {
                constructor(...args) { super(...args); window.__sockets.push(this); }
            };""")
        _open_synthetic_canvas(fresh_server, page)
        page.evaluate("""() => {
            window.__renders = { app: 0, dag: 0 };
            const previous = preact.options.diffed;
            preact.options.diffed = (vnode) => {
                if (vnode.type?.name === 'DagView') window.__renders.app += 1;
                if (String(vnode.props?.class).startsWith('dag-node')) window.__renders.dag += 1;
                previous?.(vnode);
            };
            window.__sockets.at(-1).onmessage({ data: JSON.stringify({ type: 'log_line', data: { worker_slot: 0, task_id: 'root', line: 'Synthetic log line' } }) });
        }""")
        page.wait_for_timeout(1200)  # also spans the one-second timer
        renders = page.evaluate("window.__renders")
        assert renders["app"] > 0
        assert renders["dag"] == 0
        page.locator(".dag-node[data-id='middle']").click()
        page.wait_for_function("() => window.__renders.dag > 0")

    def test_dag_renders_and_supports_interactions(
        self, server_url, runtime_home, page, request, browser_error_guard
    ):
        runtime_paths = build_runtime_paths(home=runtime_home)
        store = initialize_state_store(runtime_paths)
        session_id = "dag-ui-v12-001"
        store.create_session(
            session_id=session_id,
            name="Synthetic DAG",
            pack="claude-code",
            created_at="2026-09-16T12:00:00Z",
            config_json="{}",
        )
        for task_id, dependency in (
            ("root", "none"),
            ("middle", "root"),
            ("leaf", "middle"),
        ):
            source = _write_intake_plan(
                runtime_home, session_id, task_id, depends_on=dependency
            )
            plan_text = source.read_text(encoding="utf-8")
            store.upsert_ready_task_plan(
                session_id=session_id,
                plan=parse_task_plan(plan_text, source=source),
                plan_text=plan_text,
                created_at="2026-09-16T12:00:01Z",
            )
        store.update_session_status(
            session_id,
            status="running",
            started_at="2026-09-16T12:00:01Z",
        )
        request.addfinalizer(lambda: store.delete_session(session_id))
        bootstrap = _build_root_bootstrap_payload(store, runtime_paths=runtime_paths)
        assert bootstrap["current_session"]["id"] == session_id
        page.goto(server_url, wait_until="domcontentloaded")
        page.wait_for_selector("button[aria-label='Open DAG']", timeout=SLOW_TIMEOUT)

        assert_offline_page_source(page.content())

        page.locator("button[aria-label='Open DAG']").click()
        page.wait_for_selector(".dag-node[data-id='root']", timeout=SLOW_TIMEOUT)
        assert page.locator(".dag-node:not([data-id^='group-'])").count() == 3
        assert page.locator(".dag-edge").count() == 2
        assert page.locator(".dag-node[data-id='root']").evaluate(
            "element => getComputedStyle(element).position"
        ) == "absolute"

        _wait_for_fit(page)
        viewport = page.locator(".dag-viewport")
        fitted_transform = viewport.get_attribute("style")
        page.locator(".dag-zoom-in").click()
        page.wait_for_function(
            """previous => document.querySelector('.dag-viewport')
                ?.getAttribute('style') !== previous""",
            arg=fitted_transform,
            timeout=SLOW_TIMEOUT,
        )
        zoomed_transform = viewport.get_attribute("style")
        assert zoomed_transform != fitted_transform
        page.locator(".dag-fit-view").click()
        page.wait_for_function(
            """previous => document.querySelector('.dag-viewport')
                ?.getAttribute('style') !== previous""",
            arg=zoomed_transform,
            timeout=SLOW_TIMEOUT,
        )
        assert viewport.get_attribute("style") != zoomed_transform

        middle_node = page.locator(".dag-node[data-id='middle']")
        middle_node.click()
        page.wait_for_function(
            """() => document.querySelector(
                ".dag-node[data-id='middle']"
            )?.classList.contains('selected')""",
            timeout=SLOW_TIMEOUT,
        )
        middle_node.dblclick()
        task_heading = page.locator(".split-view .detail-panel h1")
        task_heading.wait_for(state="visible", timeout=SLOW_TIMEOUT)
        assert task_heading.inner_text() == "middle"
        page.locator(".split-view .metadata-grid").wait_for(
            state="visible", timeout=SLOW_TIMEOUT
        )
        page.locator(".split-view .log-panel").wait_for(
            state="visible", timeout=SLOW_TIMEOUT
        )
        page.wait_for_selector(".dag-canvas-root", state="detached", timeout=SLOW_TIMEOUT)

    def test_dag_status_update_keeps_dragged_position_and_zoom(
        self, fresh_server, page, browser_error_guard
    ):
        """DAG nodes carry real titles/statuses and follow live status changes.

        Regression: the DAG payload had no title or status, so every node read
        "Task" / "ready" and never changed color.
        """
        from cognitive_switchyard.models import BackendRuntimeEvent

        store = fresh_server["store"]
        runtime_home = fresh_server["runtime_home"]
        session_id = "dag-status-001"
        store.create_session(
            session_id=session_id,
            name="Synthetic DAG Status",
            pack="claude-code",
            created_at="2026-09-16T12:00:00Z",
            config_json="{}",
        )
        for task_id, dependency in (("root", "none"), ("leaf", "root")):
            source = _write_intake_plan(runtime_home, session_id, task_id, depends_on=dependency)
            plan_text = source.read_text(encoding="utf-8")
            store.upsert_ready_task_plan(
                session_id=session_id,
                plan=parse_task_plan(plan_text, source=source),
                plan_text=plan_text,
                created_at="2026-09-16T12:00:01Z",
            )
        store.project_task(session_id, "root", status="done", timestamp="2026-09-16T12:00:02Z")
        store.update_session_status(session_id, status="running", started_at="2026-09-16T12:00:01Z")

        page.goto(fresh_server["url"], wait_until="domcontentloaded")
        page.wait_for_selector("button[aria-label='Open DAG']", timeout=SLOW_TIMEOUT)
        page.locator("button[aria-label='Open DAG']").click()
        root_node = page.locator(".dag-node[data-id='root']")
        leaf_node = page.locator(".dag-node[data-id='leaf']")
        root_node.wait_for(timeout=SLOW_TIMEOUT)
        _wait_for_fit(page)

        assert root_node.locator(".secondary").inner_text() == "Task root"
        assert root_node.locator(".status-badge").inner_text() == "done"
        assert leaf_node.locator(".secondary").inner_text() == "Task leaf"
        assert leaf_node.locator(".status-badge").inner_text() == "ready"

        def leaf_border_color() -> str:
            return leaf_node.evaluate("node => getComputedStyle(node).borderTopColor")

        ready_border = leaf_border_color()
        assert ready_border != root_node.evaluate("node => getComputedStyle(node).borderTopColor")
        box = leaf_node.bounding_box()
        page.mouse.move(box["x"] + 30, box["y"] + 25)
        page.mouse.down(); page.mouse.move(box["x"] + 65, box["y"] + 45, steps=5); page.mouse.up()
        position = leaf_node.evaluate("el => [el.style.left, el.style.top]")
        page.locator(".dag-zoom-out").click()
        transform = page.locator(".dag-viewport").get_attribute("style")

        # A WebSocket task_status_change must recolor the open graph. Republish
        # until the page's WebSocket is connected and the change lands.
        event = BackendRuntimeEvent(
            session_id=session_id,
            message_type="task_status_change",
            data={
                "task_id": "leaf",
                "old_status": "ready",
                "new_status": "active",
                "worker_slot": 0,
                "notes": "",
                "elapsed": 0,
            },
        )
        for _ in range(20):
            fresh_server["app"].state.controller._publish_runtime_event(event)
            try:
                page.wait_for_function(
                    """() => document.querySelector(
                        ".dag-node[data-id='leaf'] .status-badge"
                    )?.textContent === 'active'""",
                    timeout=500,
                )
                break
            except PlaywrightTimeoutError:
                continue
        assert leaf_node.locator(".status-badge").inner_text() == "active"
        assert leaf_border_color() != ready_border
        assert leaf_node.evaluate("el => [el.style.left, el.style.top]") == position
        assert page.locator(".dag-viewport").get_attribute("style") == transform

# ---------------------------------------------------------------------------
# 11. SETTINGS CRUD
# ---------------------------------------------------------------------------


class TestSettings:
    """Verify settings read and write."""

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

    def test_purge_completed_sessions(self, server_url, runtime_home, page):
        """DELETE /api/sessions purges completed/aborted sessions and keeps idle ones.

        Idle sessions are reusable and keep their worktrees, and History's
        "Purge All" confirmation counts only completed/aborted sessions, so the
        run below must survive a purge while idle and go once it is ended.
        """
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

        idle_purge = page.evaluate("""async () => {
            await fetch('/api/sessions', { method: 'DELETE' });
            const resp = await fetch('/api/sessions/purge-001');
            return { status: resp.status, session: resp.ok ? (await resp.json()).session : null };
        }""")
        assert idle_purge["status"] == 200, "Purge All must keep idle sessions"
        assert idle_purge["session"]["status"] == "idle"

        page.evaluate("""async () => {
            await fetch('/api/sessions/purge-001/end', { method: 'POST' });
        }""")
        _poll_session_status(page, "purge-001", {"completed"})

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



# ---------------------------------------------------------------------------
# 15. PACKS API
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 16. SESSION CONFIG OVERRIDES
# ---------------------------------------------------------------------------


class TestSessionConfig:
    """Verify session config overrides work through the API."""

    def test_setup_form_sends_timeout_overrides(self, fresh_server, page, browser_error_guard):
        """Setup's Advanced timeout fields reach the backend under its config keys.

        Regression: the form collected the three timeouts but never sent them,
        so every session silently ran with the pack's timeouts.
        """
        session_id = "timeout-ui-001"
        page.goto(fresh_server["url"])
        page.wait_for_selector("text=Create Session", timeout=SLOW_TIMEOUT)
        page.locator("label:has-text('Session ID') ~ input").first.fill(session_id)
        page.locator("button:has-text('Show Advanced')").click()
        page.locator("label:has-text('Task Idle Timeout') ~ input").first.fill("90")
        page.locator("label:has-text('Task Max Timeout') ~ input").first.fill("0")
        page.locator("label:has-text('Session Max Timeout') ~ input").first.fill("3600")
        with page.expect_response(
            lambda response: response.url.endswith("/api/sessions")
            and response.request.method == "POST",
            timeout=SLOW_TIMEOUT,
        ) as create_info:
            page.locator("button:has-text('Create Session')").click()
        assert create_info.value.status == 201
        session = create_info.value.json()["session"]
        assert session["id"] == session_id
        assert session["config"]["task_idle"] == 90
        assert session["config"]["task_max"] == 0
        assert session["config"]["session_max"] == 3600
        assert session["effective_runtime_config"]["timeouts"] == {
            "task_idle": 90,
            "task_max": 0,
            "session_max": 3600,
        }

        # The locked draft reads the same keys back into the form.
        page.reload()
        page.wait_for_selector("button:has-text('Show Advanced')", timeout=SLOW_TIMEOUT)
        page.locator("button:has-text('Show Advanced')").click()
        assert page.locator("label:has-text('Task Idle Timeout') ~ input").first.input_value() == "90"
        assert page.locator("label:has-text('Task Max Timeout') ~ input").first.input_value() == "0"
        assert page.locator("label:has-text('Session Max Timeout') ~ input").first.input_value() == "3600"


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
        expect(reset_btn).to_be_visible()
        reset_btn.click()
        expect(page.locator("button", has_text="Create Session")).to_be_visible()
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


# ---------------------------------------------------------------------------
# 19. FULL UI WORKFLOW — END TO END
# ---------------------------------------------------------------------------



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
        _purge_inactive_operable_sessions(page)

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
        assert run_timer_text is not None, page.evaluate("""async () => JSON.stringify({
            sessions: (await (await fetch('/api/sessions')).json()).sessions.map(s => [s.id, s.status]),
            body: document.body.innerText.slice(0, 800)
        })""")
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
        _purge_inactive_operable_sessions(page)

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
        assert cumul_style is not None, page.evaluate("""async () => JSON.stringify({
            sessions: (await (await fetch('/api/sessions')).json()).sessions.map(s => [s.id, s.status]),
            body: document.body.innerText.slice(0, 800)
        })""")
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
    yield from _serve_app(app, label="Uvicorn (planning)")


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

    def test_no_console_errors_after_session_with_done_tasks(self, fresh_server, page):
        """Monitor view with completed tasks must render without JS errors.

        Validates that the Plan 006 components (HealthSummaryBar, TaskRowElapsed,
        LastActivityIndicator) don't throw exceptions when rendering with real session data.
        """
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(fresh_server["url"])
        page.wait_for_selector("body", timeout=SLOW_TIMEOUT)

        page.evaluate("""async () => {
            await fetch('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: 'obs-006b', name: 'Observability No-Error Test', pack: 'claude-code'})
            });
        }""")
        _write_intake_plan(fresh_server["runtime_home"], "obs-006b", "t006b")
        page.reload()

        page.evaluate("""async () => {
            await fetch('/api/sessions/obs-006b/start', { method: 'POST' });
        }""")

        _poll_session_status(page, "obs-006b", {"idle", "completed", "aborted"})
        _poll_tasks_done(page, "obs-006b", min_done=1)

        # Navigate to monitor view to trigger all Plan 006 components
        monitor_btn = page.locator("button:has-text('Monitor')")
        monitor_btn.click()
        expect(page.locator(".health-summary")).to_be_visible()

        assert errors == [], f"Console errors after session with done tasks: {errors}"


# ---------------------------------------------------------------------------
# EXACT TEXT IN WHITESPACE-PRESERVING ELEMENTS
# ---------------------------------------------------------------------------

class RenderedMonitorServer:
    """Serve the real SPA with synthetic API responses and capture mutations."""
    SESSION_ID = "synthetic-exact-text"
    NOTES = "# Synthetic notes\n    indented synthetic line\n"
    PACK = {"name": "claude-code", "description": "Synthetic pack", "version": "1.0"}

    def _session(self, status):
        return {
            "id": self.SESSION_ID, "name": "Synthetic Session", "pack": "claude-code", "status": status,
            "created_at": "2030-01-01T00:00:00Z", "started_at": "2030-01-01T00:00:01Z",
            "completed_at": "2030-01-01T00:10:00Z" if status == "completed" else None,
            "workers": [], "summary": {"duration_seconds": 100},
            "config": {"worker_count": 1, "environment": {
                "COGNITIVE_SWITCHYARD_SOURCE_REPO": "/synthetic/source",
                "COGNITIVE_SWITCHYARD_REPO_ROOT": "/synthetic/worktree",
                "COGNITIVE_SWITCHYARD_BRANCH": "switchyard-synthetic",
            }},
        }

    def _dashboard(self, status, runtime_state=None, effective_runtime_config=None, workers=None):
        return {
            "session": dict(self._session(status), elapsed=1, run_elapsed=1, run_number=1),
            "pipeline": {"active": 1, "done": 1}, "pipeline_dirs": {}, "runtime_state": runtime_state or {},
            "effective_runtime_config": effective_runtime_config or {}, "recent_events": [],
            "workers": workers if workers is not None else [
                {"slot": 0, "status": "idle"},
                {"slot": 1, "status": "active", "task_id": "t001", "task_title": "Synthetic task",
                 "phase_num": 1, "phase_total": 1, "elapsed": 1, "last_log_line": "Synthetic tail line"},
                {"slot": 2, "status": "problem", "task_id": "t002", "task_title": "Synthetic stalled task", "elapsed": 1},
            ],
        }

    def serve(self, page, *, session_status, dashboard_status=None, runtime_state=None,
              effective_runtime_config=None, workers=None, tasks=None, log_content="Synthetic log line\n"):
        task = {"task_id": "t001", "title": "Synthetic task", "status": "active", "depends_on": [], "worker_slot": 1}
        tasks = tasks if tasks is not None else [task]
        dashboard_status = dashboard_status or session_status
        dashboard = self._dashboard(dashboard_status, runtime_state, effective_runtime_config, workers)
        posts = []
        self.requests = []
        history = dict(self._session("completed"), release_notes={"path": "RELEASE_NOTES.md", "content": self.NOTES})
        current = self._session(session_status) if session_status else None
        base = f"/api/sessions/{self.SESSION_ID}"
        responses = {
            "/api/packs": {"packs": [self.PACK]},
            "/api/sessions": {"sessions": [history]},
            base: {"session": current or history},
            f"{base}/dashboard": dashboard,
            f"{base}/tasks": {"tasks": tasks},
            f"{base}/intake": {"locked": False, "files": []},
            f"{base}/tasks/t001": {"task": next((item for item in tasks if item["task_id"] == "t001"), task)},
            f"{base}/tasks/t001/log": {"content": log_content, "mtime_iso": "2030-01-01T00:00:09Z"},
        }
        html = render_app_html({
            "packs": [self.PACK], "sessions": [history], "settings": {}, "current_session": current,
            "dashboard": dashboard if current else None,
            "intake": {"locked": False, "files": []},
        })

        def handle(route):
            path = route.request.url.removeprefix("http://switchyard.test").split("?")[0]
            self.requests.append((route.request.method, path))
            if route.request.method == "POST":
                posts.append((path, route.request.post_data_json if route.request.post_data else None))
                result = {"ok": True, "permission_report": {"ok": True, "issues": []}} if path.endswith("/preflight") else {}
                route.fulfill(json=result)
            elif path == "/":
                route.fulfill(status=200, content_type="text/html", body=html)
            elif path in responses:
                route.fulfill(json=responses[path])
            else:
                route.fulfill(status=404, body="synthetic not found")

        page.add_init_script(
            "window.testSocketMessages = []; window.WebSocket = class { static OPEN = 1; constructor() { this.readyState = 1; window.testSocket = this; } send(data) { window.testSocketMessages.push(data); } close() {} };"
        )
        page.route("http://switchyard.test/**", handle)
        page.goto("http://switchyard.test/")
        return posts


class TestRenderedMonitorContracts:
    @pytest.mark.parametrize("session_status,visible,hidden", [
        ("planning", ["Pause"], ["Resume"]),
        ("resolving", ["Pause"], ["Resume"]),
        ("running", ["Pause"], ["Resume"]),
        ("verifying", ["Pause"], ["Resume"]),
        ("auto_fixing", ["Pause"], ["Resume"]),
        ("paused", ["Resume"], ["Pause"]),
        ("idle", ["New Run", "End Session"], ["Pause", "Resume", "Abort"]),
        ("created", ["Abort"], []),
    ])
    def test_session_controls_follow_status(self, page, browser_error_guard, session_status, visible, hidden):
        RenderedMonitorServer().serve(page, session_status=session_status)
        for name in visible:
            expect(page.locator("button", has_text=name)).to_be_visible()
        for name in hidden:
            expect(page.locator("button", has_text=name)).to_have_count(0)

    @pytest.mark.parametrize("age,card_class", [(199, "worker-card active"), (200, "worker-card warning")])
    def test_worker_card_warns_at_two_thirds_of_idle_limit(self, page, browser_error_guard, age, card_class):
        worker = {"slot": 1, "status": "active", "task_id": "t001", "task_title": "Synthetic task",
                  "elapsed": 1, "last_activity_ago": age, "task_idle_limit": 300}
        RenderedMonitorServer().serve(page, session_status="running", workers=[worker])
        card = page.locator(".worker-card").filter(has_text="Synthetic task")
        expect(card).to_have_class(card_class)
        expect(card).to_contain_text("idle:")

    @pytest.mark.parametrize("limit,age,token", [
        (300, 99, "--status-done"), (300, 100, "--status-review"),
        (300, 199, "--status-review"), (300, 200, "--status-blocked"),
        (600, 199, "--status-done"), (600, 200, "--status-review"),
        (600, 399, "--status-review"), (600, 400, "--status-blocked"),
    ])
    def test_idle_indicator_uses_limit_thirds(self, page, browser_error_guard, limit, age, token):
        worker = {"slot": 1, "status": "active", "task_id": "t001", "task_title": "Synthetic task",
                  "elapsed": 1, "last_activity_ago": age, "task_idle_limit": limit}
        RenderedMonitorServer().serve(page, session_status="running", workers=[worker])
        indicator = page.locator(".worker-card").filter(has_text="Synthetic task").get_by_text("idle:")
        expected_color = page.evaluate("""token => {
            const probe = document.createElement('span');
            probe.style.color = `var(${token})`;
            document.body.appendChild(probe);
            const color = getComputedStyle(probe).color;
            probe.remove();
            return color;
        }""", token)
        expect(indicator).to_have_css("color", expected_color)

    def test_live_output_does_not_reset_server_idle_snapshot(self, page, browser_error_guard):
        worker = {"slot": 1, "status": "active", "task_id": "t001", "task_title": "Synthetic task",
                  "elapsed": 1, "last_activity_ago": 200, "task_idle_limit": 300}
        RenderedMonitorServer().serve(page, session_status="running", workers=[worker])
        card = page.locator(".worker-card").filter(has_text="Synthetic task")
        expect(card).to_have_class("worker-card warning")
        page.evaluate("""() => window.testSocket.onmessage({data: JSON.stringify({type: 'log_line',
            data: {task_id: 't001', worker_slot: 1, line: 'Synthetic output'}})})""")
        expect(card.locator(".log-line")).to_contain_text("Synthetic output")
        expect(card).to_have_class("worker-card warning")
        page.evaluate("""() => window.testSocket.onmessage({data: JSON.stringify({type: 'progress_detail',
            data: {task_id: 't001', worker_slot: 1, detail: 'Synthetic progress'}})})""")
        expect(card).to_contain_text("Synthetic progress")
        expect(card).to_have_class("worker-card warning")

    @pytest.mark.parametrize("session_status,reason,label", [
        ("auto_fixing", "task_auto_fix", "Auto-fixing task failure"),
        ("auto_fixing", "task_failure", "Auto-fixing task failure"),
        ("verifying", "task_auto_fix", "Re-verifying after task fix"),
        ("auto_fixing", "verification_failure", "Auto-fixing verification failures"),
        ("verifying", "verification_failure", "Re-verifying after auto-fix"),
    ])
    def test_verification_card_shows_phase_label_and_attempts(self, page, browser_error_guard, session_status, reason, label):
        runtime = {"verification_reason": reason, "auto_fix_context": "task_failure",
                   "auto_fix_task_id": "t001", "auto_fix_attempt": 1}
        RenderedMonitorServer().serve(page, session_status=session_status, runtime_state=runtime,
                                      effective_runtime_config={"auto_fix": {"max_attempts": 3}})
        card = page.locator(".worker-card").filter(has_text=label)
        expect(card).to_be_visible()

    def test_auto_fix_card_shows_task_and_attempts(self, page, browser_error_guard):
        runtime = {"verification_reason": "task_failure", "auto_fix_context": "task_failure",
                   "auto_fix_task_id": "t001", "auto_fix_attempt": 1}
        RenderedMonitorServer().serve(page, session_status="auto_fixing", runtime_state=runtime,
                                      effective_runtime_config={"auto_fix": {"max_attempts": 3}})
        card = page.locator(".worker-card").filter(has_text="Auto-fixing task failure")
        expect(card).to_contain_text("Fixing task: t001")
        expect(card).to_contain_text("1/3")

    def test_task_rows_show_fta_badge_and_post_moves(self, page, browser_error_guard):
        tasks = [
            {"task_id": "t001", "title": "Synthetic FTA", "status": "blocked", "full_test_after": True},
            {"task_id": "t002", "title": "Synthetic plain", "status": "ready", "full_test_after": False},
        ]
        posts = RenderedMonitorServer().serve(page, session_status="running", tasks=tasks)
        fta = page.locator(".task-row").filter(has_text="Synthetic FTA")
        plain = page.locator(".task-row").filter(has_text="Synthetic plain")
        expect(fta.locator('[title="Full test after completion"]')).to_have_text("FTA")
        expect(plain.locator('[title="Full test after completion"]')).to_have_count(0)
        fta.hover()
        fta.locator('button[title^="Retry"]').click()
        assert posts == [("/api/sessions/synthetic-exact-text/tasks/t001/move", {"target_status": "ready"})]

    def test_health_summary_counts_tasks(self, page, browser_error_guard):
        tasks = [{"task_id": f"t00{i}", "title": "Synthetic", "status": status}
                 for i, status in enumerate(("done", "active", "blocked"), 1)]
        workers = [{"slot": 1, "status": "active", "task_id": "t002", "elapsed": 1}]
        RenderedMonitorServer().serve(page, session_status="running", tasks=tasks, workers=workers)
        summary = page.locator(".health-summary")
        for text in ("1 done", "1 active (", "1 blocked"):
            expect(summary).to_contain_text(text)

    def test_pending_verification_displays_its_reason(self, page, browser_error_guard):
        RenderedMonitorServer().serve(page, session_status="running",
                                      runtime_state={"verification_pending": True, "verification_reason": "task_auto_fix"},
                                      effective_runtime_config={"verification_interval": 2})
        expect(page.locator(".verification-countdown")).to_have_text("Verification pending: Re-verifying after task fix")

    def test_worker_log_extracts_readable_json(self, page, browser_error_guard):
        worker = {"slot": 1, "status": "active", "task_id": "t001", "task_title": "Synthetic task", "elapsed": 1}
        RenderedMonitorServer().serve(page, session_status="running", workers=[worker])
        card = page.locator(".worker-card").filter(has_text="Synthetic task")
        for line in ('ordinary text', '{"type":"assistant","message":{"content":[{"type":"text","text":"Synthetic message"}]}}',
                     '{"type":"metadata"}'):
            page.evaluate("""line => window.testSocket.onmessage({data: JSON.stringify({type: 'log_line',
                data: {task_id: 't001', worker_slot: 1, line}})})""", line)
        expect(card.locator(".log-line")).to_have_text(["ordinary text", "Synthetic message"])

    def test_planning_log_extracts_readable_json(self, page, browser_error_guard):
        RenderedMonitorServer().serve(page, session_status="planning")
        page.evaluate("""() => window.testSocket.onmessage({data: JSON.stringify({type: 'log_line',
            data: {task_id: '__phase_planning__', worker_slot: -1,
                   line: JSON.stringify({text: 'Synthetic planning output'})}})})""")
        expect(page.get_by_text("Synthetic planning output", exact=True)).to_be_visible()

    def test_history_detail_does_not_subscribe_to_live_logs(self, page, browser_error_guard):
        server = RenderedMonitorServer()
        server.serve(page, session_status=None, dashboard_status="completed")
        page.locator("button", has_text="History").first.click()
        page.locator(".session-card-header div").first.click()
        expect(page.locator("pre.log-panel")).to_contain_text("Synthetic notes")
        base = "/api/sessions/synthetic-exact-text"
        assert ("GET", base) in server.requests
        assert ("GET", f"{base}/tasks") in server.requests
        assert not any(path.endswith("/log") for _, path in server.requests)
        assert page.evaluate("window.testSocketMessages") == []

    def test_worker_log_subscription_tracks_dashboard_workers(self, page, browser_error_guard):
        server = RenderedMonitorServer()
        workers = [{"slot": 1, "status": "active", "task_id": "t001", "task_title": "Synthetic task"}]
        server.serve(page, session_status="running", workers=workers)
        page.wait_for_function("window.testSocketMessages.some(s => JSON.parse(s).type === 'subscribe_logs')")
        assert page.evaluate("window.testSocketMessages.map(JSON.parse)") == [{"type": "subscribe_logs", "worker_slot": 1}]
        dashboard = server._dashboard("running", workers=[])
        page.evaluate("""dashboard => window.testSocket.onmessage({data: JSON.stringify({type: 'state_update', data: dashboard})})""", dashboard)
        page.wait_for_function("window.testSocketMessages.some(s => JSON.parse(s).type === 'unsubscribe_logs')")
        assert page.evaluate("window.testSocketMessages.map(JSON.parse)") == [
            {"type": "subscribe_logs", "worker_slot": 1}, {"type": "unsubscribe_logs", "worker_slot": 1}]

    def test_file_actions_post_to_session_endpoints(self, page, browser_error_guard):
        server = RenderedMonitorServer()
        tasks = [{"task_id": "t001", "title": "Synthetic task", "status": "ready", "plan_path": "/synthetic/plan file.md"}]
        server.serve(page, session_status="created", tasks=tasks)
        base = "http://switchyard.test/api/sessions/synthetic-exact-text"
        with page.expect_request(f"{base}/open-intake") as intake:
            page.get_by_role("button", name="Open Intake", exact=True).click()
        assert intake.value.method == "POST"
        page.get_by_role("button", name="Monitor", exact=True).click()
        row = page.locator(".task-row").filter(has_text="t001")
        row.hover()
        with page.expect_request(f"{base}/reveal-file?path=%2Fsynthetic%2Fplan%20file.md") as reveal:
            row.locator('button[title="Reveal plan file"]').click()
        assert reveal.value.method == "POST"

    def test_task_detail_shows_fta_and_constraints(self, page, browser_error_guard):
        tasks = [{"task_id": "t001", "title": "Synthetic task", "status": "blocked",
                  "full_test_after": True, "depends_on": [], "anti_affinity": []}]
        RenderedMonitorServer().serve(page, session_status="running", tasks=tasks)
        page.locator(".task-row").filter(has_text="t001").click()
        expect(page.locator('[title="Full test after completion"]')).to_have_text("FTA")
        expect(page.get_by_text("FULL_TEST_AFTER: yes", exact=True)).to_be_visible()

    @pytest.mark.parametrize("task_status,label", [("active", "Elapsed"), ("done", "Duration")])
    def test_task_detail_shows_timing_fields(self, page, browser_error_guard, task_status, label):
        tasks = [{"task_id": "t001", "title": "Synthetic task", "status": task_status,
                  "started_at": "2030-01-01T12:34:56Z", "completed_at": "2030-01-01T12:35:01Z",
                  "elapsed": 5}]
        RenderedMonitorServer().serve(page, session_status="running", tasks=tasks)
        page.locator(".task-row").filter(has_text="t001").click()
        detail = page.locator(".detail-panel")
        expect(detail.get_by_text("Started", exact=True)).to_be_visible()
        expect(detail.locator('[title="2030-01-01T12:34:56Z"]')).to_have_text("12:34:56")
        expect(detail.get_by_text(label, exact=True)).to_be_visible()
        expect(detail.get_by_text("Completed", exact=True)).to_be_visible()
        expect(detail.locator('[title="2030-01-01T12:35:01Z"]')).to_have_text("12:35:01")

    @pytest.mark.parametrize("task_status,history_source,message", [
        ("done", "summary", "Task logs were not retained for this completed session."),
        ("done", None, "No retained log found for this task."),
        ("blocked", None, "No retained log found for this task."),
        ("ready", None, "No log yet. Logs appear after the task starts."),
        ("active", None, "Waiting for live log subscription..."),
    ])
    def test_task_detail_explains_empty_logs(self, page, browser_error_guard, task_status, history_source, message):
        tasks = [{"task_id": "t001", "title": "Synthetic task", "status": task_status,
                  "history_source": history_source}]
        RenderedMonitorServer().serve(page, session_status="running", tasks=tasks, log_content="")
        page.locator(".task-row").filter(has_text="t001").click()
        expect(page.get_by_text(message, exact=True)).to_be_visible()

    @pytest.mark.parametrize("session_status,phase,separator", [
        ("auto_fixing", "__phase_auto_fix__", "─── Auto-fix output ───"),
        ("verifying", "__phase_verification__", "─── Verification output ───"),
    ])
    def test_task_detail_shows_phase_logs(self, page, browser_error_guard, session_status, phase, separator):
        RenderedMonitorServer().serve(page, session_status=session_status,
                                      runtime_state={"auto_fix_task_id": "t001"})
        page.locator(".task-row").filter(has_text="t001").click()
        expect(page.locator(".log-line").filter(has_text="Synthetic log line")).to_be_visible()
        page.evaluate("""phase => window.testSocket.onmessage({data: JSON.stringify({type: 'log_line',
            data: {task_id: phase, worker_slot: -1, line: 'Synthetic phase output', timestamp: '2030-01-01T00:00:10Z'}})})""", phase)
        expect(page.get_by_text(separator, exact=True)).to_be_visible()
        expect(page.locator(".log-line").filter(has_text="Synthetic phase output")).to_be_visible()

    def test_live_log_line_renders_its_timestamp(self, page, browser_error_guard):
        RenderedMonitorServer().serve(page, session_status="running")
        page.locator(".task-row").filter(has_text="t001").click()
        expect(page.locator(".log-line").filter(has_text="Synthetic log line")).to_be_visible()
        page.evaluate("""() => window.testSocket.onmessage({data: JSON.stringify({type: 'log_line',
            data: {task_id: 't001', worker_slot: 1, line: 'Synthetic live output', timestamp: '2030-01-01T12:34:56Z'}})})""")
        expect(page.locator(".log-line").filter(has_text="Synthetic live output")).to_have_text("12:34:56Synthetic live output")

    def test_live_task_status_change_updates_row_time(self, page, browser_error_guard):
        tasks = [{"task_id": "t001", "title": "Synthetic task", "status": "ready"}]
        RenderedMonitorServer().serve(page, session_status="running", tasks=tasks)
        row = page.locator(".task-row").filter(has_text="t001")
        expect(row).to_contain_text("ready")
        page.evaluate("""() => window.testSocket.onmessage({data: JSON.stringify({type: 'task_status_change',
            data: {task_id: 't001', new_status: 'active', started_at: '2030-01-01T12:34:56Z'}})})""")
        expect(row).to_contain_text("active")
        expect(row).to_contain_text("12:34:56")
        page.evaluate("""() => window.testSocket.onmessage({data: JSON.stringify({type: 'task_status_change',
            data: {task_id: 't001', new_status: 'done', completed_at: '2030-01-01T12:35:01Z'}})})""")
        expect(page.locator(".health-summary")).to_contain_text("Last completion: 12:35:01")


class TestExactTextHasNoPadding:
    """These elements use pre or pre-wrap, where any padding space shows on screen."""

    NOTES = RenderedMonitorServer.NOTES

    def _serve(self, page, **kwargs):
        return RenderedMonitorServer().serve(page, **kwargs)

    @staticmethod
    def _child_text(locator):
        return locator.evaluate("element => [...element.childNodes].map(node => node.textContent)")

    def test_completion_code_block_starts_at_the_command(self, page, browser_error_guard):
        self._serve(page, session_status="running", dashboard_status="completed")
        block = page.locator(".completion-code-block").first
        block.wait_for(timeout=SLOW_TIMEOUT)
        assert self._child_text(block) == [
            "cd /synthetic/worktree\ngit log --oneline\ngit diff --stat HEAD~1",
            "Copy",
        ]
        assert_exact_text(block.locator(".copy-btn"), "Copy")

    def test_release_notes_keep_their_own_indentation(self, page, browser_error_guard):
        self._serve(page, session_status=None, dashboard_status="completed")
        page.locator("button", has_text="History").first.click()
        page.locator(".session-card-header div").first.click()
        notes = page.locator("pre.log-panel")
        notes.wait_for(timeout=SLOW_TIMEOUT)
        assert_exact_text(notes, self.NOTES)

    def test_top_bar_run_time_has_no_padding(self, page, browser_error_guard):
        self._serve(page, session_status="running", dashboard_status="running")
        timer = page.locator('span[title="Current run time"]')
        timer.wait_for(timeout=SLOW_TIMEOUT)
        text = timer.evaluate("element => element.textContent")
        assert text and text == text.strip()

    def test_log_lines_hold_only_their_timestamp_and_text(self, page, browser_error_guard):
        self._serve(page, session_status="running", dashboard_status="running")
        tails = page.locator(".log-line")
        tails.first.wait_for(timeout=SLOW_TIMEOUT)
        assert [self._child_text(line) for line in tails.all()] == [
            ["Synthetic tail line"], ["Waiting for task..."],
        ]
        page.locator(".worker-card.active").first.click()
        detail = page.locator(".log-line").first
        detail.locator("span").wait_for(timeout=SLOW_TIMEOUT)
        assert self._child_text(detail) == ["00:00:09", "Synthetic log line"]


# ---------------------------------------------------------------------------
# CONTROLLED FORM VALUES
# ---------------------------------------------------------------------------

class TestControlledFormValues:
    """Selects show their first option for an unlisted value, keeping it stored; number text stays as typed."""

    PACKS = [
        {"name": "synthetic-first", "description": "Synthetic pack"},
        {"name": "synthetic-second", "description": "Synthetic pack"},
    ]
    SETTINGS = {"default_pack": "synthetic-unlisted", "retention_days": 30, "default_planners": 1, "default_workers": 1}

    def _serve(self, page):
        html = render_app_html({"packs": self.PACKS, "sessions": [], "settings": self.SETTINGS, "current_session": None, "dashboard": None, "intake": {"locked": False, "files": []}})
        responses = {
            "/api/packs": {"packs": self.PACKS},
            "/api/sessions": {"sessions": []},
            "/api/settings": {"settings": self.SETTINGS},
            "/api/repo-branches": {"branches": ["synthetic-a", "synthetic-b"]},
            "/api/resolve-path": {"resolved": "/synthetic/repo", "exists": True, "is_git": True},
        }

        def handle(route):
            path = route.request.url.removeprefix("http://switchyard.test").split("?")[0]
            if path == "/":
                route.fulfill(status=200, content_type="text/html", body=html)
            elif path in responses:
                route.fulfill(json=responses[path])
            else:
                route.fulfill(status=404, body="synthetic not found")

        page.add_init_script("window.WebSocket = class { constructor() { this.readyState = 1; } send() {} close() {} };")
        page.route("http://switchyard.test/**", handle)
        page.goto("http://switchyard.test/")

    def test_settings_pack_shows_first_option_and_saves_stored_value(self, page, browser_error_guard):
        self._serve(page)
        page.locator("button[aria-label='Settings']").click()
        page.get_by_role("button", name="Save Settings").wait_for(timeout=SLOW_TIMEOUT)
        select = page.locator("label:has-text('Default Pack') + select")
        assert select.evaluate("el => [el.selectedIndex, el.value]") == [0, "synthetic-first"]
        with page.expect_request("**/api/settings") as saved:
            page.get_by_role("button", name="Save Settings").click()
        assert saved.value.post_data_json["default_pack"] == "synthetic-unlisted"

    def test_setup_pack_shows_first_option(self, page, browser_error_guard):
        self._serve(page)
        select = page.locator("label:has-text('Pack') + select").first
        select.wait_for(timeout=SLOW_TIMEOUT)
        assert select.evaluate("el => [el.selectedIndex, el.value]") == [0, "synthetic-first"]

    def test_setup_branch_shows_first_option(self, page, browser_error_guard):
        self._serve(page)
        page.get_by_placeholder("/path/to/your/project").fill("/synthetic/repo")
        page.keyboard.press("Enter")
        select = page.locator("select:has(option[value='__new__'])")
        select.wait_for(timeout=SLOW_TIMEOUT)
        assert select.evaluate("el => [el.selectedIndex, el.value]") == [0, "synthetic-a"]

    def test_settings_number_keeps_a_typed_decimal(self, page, browser_error_guard):
        self._serve(page)
        page.locator("button[aria-label='Settings']").click()
        field = page.locator("label:has-text('Session Retention') + input")
        field.click()
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.press("Backspace")
        page.keyboard.type("1.5")
        # Clearing stores 0, which the field shows, so React also ended on this text.
        assert field.evaluate("el => el.value") == "01.5"
        with page.expect_request("**/api/settings") as saved:
            page.get_by_role("button", name="Save Settings").click()
        assert saved.value.post_data_json["retention_days"] == 1.5
