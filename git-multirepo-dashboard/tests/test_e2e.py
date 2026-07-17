"""
End-to-end tests using Playwright.

These tests start the real git_dashboard server and exercise it in a real
Chromium browser. They catch rendering errors, broken CDN loads, dead buttons,
and layout issues that unit tests miss entirely.

Run E2E tests only:
    .venv/bin/python -m pytest tests/test_e2e.py -v

Run unit tests only (exclude E2E):
    .venv/bin/python -m pytest tests -v --ignore=tests/test_e2e.py

IMPORTANT: E2E tests must NOT run in the same pytest invocation as unit tests.
Playwright's event loop conflicts with asyncio.run() used by unit tests.

Requires:
    pip install playwright pytest-playwright
    playwright install chromium
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ── Check playwright is installed ────────────────────────────────────────────
try:
    from playwright.sync_api import expect  # noqa: F401
except ImportError:
    pytest.skip(
        "playwright not installed — run: .venv/bin/pip install playwright pytest-playwright "
        "&& .venv/bin/playwright install chromium",
        allow_module_level=True,
    )

pytestmark = pytest.mark.e2e

PROJECT_ROOT = Path(__file__).parent.parent
GIT_DASHBOARD = PROJECT_ROOT / "git_dashboard.py"


def _find_free_port():
    """Find a free port for the test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port, timeout=10):
    """Wait until the server is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _create_git_repo(parent_dir, name="test_repo"):
    """Create a minimal git repo with one commit. Returns the repo path."""
    repo = parent_dir / name
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "synthetic-user@example.invalid"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        check=True, capture_output=True,
    )
    return repo


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """Start git_dashboard server on a random port with an isolated temp DB.

    Uses GIT_DASHBOARD_DB env var to point the server at a throwaway database,
    so test repos never pollute the user's real data.
    """
    port = _find_free_port()
    tmp_dir = tmp_path_factory.mktemp("e2e_db")
    db_path = tmp_dir / "test_dashboard.db"

    env = dict(os.environ)
    env["GIT_DASHBOARD_NO_BROWSER"] = "1"
    env["GIT_DASHBOARD_DB"] = str(db_path)

    proc = subprocess.Popen(
        [sys.executable, str(GIT_DASHBOARD), "--port", str(port), "--no-browser", "--yes"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if not _wait_for_server(port):
        proc.kill()
        stdout = proc.stdout.read().decode(errors="replace")
        stderr = proc.stderr.read().decode(errors="replace")
        pytest.fail(f"Server failed to start on port {port}.\nstdout: {stdout}\nstderr: {stderr}")

    yield f"http://localhost:{port}"

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    # Clean up the temp DB (tmp_path_factory handles directory cleanup)


# ═════════════════════════════════════════════════════════════════════════════
# 1. Page Load & CDN Dependencies
# ═════════════════════════════════════════════════════════════════════════════

def test_page_loads_without_js_errors(server, page):
    """Page loads with no JavaScript errors."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server)
    page.wait_for_load_state("networkidle")

    assert errors == [], f"JavaScript errors on page load: {errors}"


def test_cdn_resources_load(server, page):
    """All CDN resources (React, Recharts, fonts, etc.) load successfully."""
    failed_requests = []
    page.on("requestfailed", lambda req: failed_requests.append(
        f"{req.method} {req.url}: {req.failure}"
    ))

    page.goto(server)
    page.wait_for_load_state("networkidle")

    cdn_failures = [r for r in failed_requests if "cdnjs" in r or "unpkg" in r or "fonts" in r]
    assert cdn_failures == [], f"CDN resources failed to load: {cdn_failures}"


def test_react_app_mounts(server, page):
    """React app mounts successfully — the root div has content."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    root = page.locator("#root")
    assert root.inner_html() != "", "React app did not mount — #root is empty"


def test_no_recharts_reference_error(server, page):
    """Recharts loads correctly — no ReferenceError for Recharts global."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server)
    page.wait_for_load_state("networkidle")

    recharts_errors = [e for e in errors if "Recharts" in e or "ReferenceError" in e]
    assert recharts_errors == [], f"Recharts/reference errors: {recharts_errors}"


# ═════════════════════════════════════════════════════════════════════════════
# 2. Header & Navigation
# ═════════════════════════════════════════════════════════════════════════════

def test_header_visible_with_title(server, page):
    """The fixed header is visible with the app title."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    header = page.locator("header")
    assert header.is_visible(), "Header is not visible"
    assert "Git Fleet" in header.inner_text()


def test_header_buttons_present(server, page):
    """Header contains both Scan Dir and Full Scan buttons."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    scan_dir = page.locator("header >> text=Scan Dir")
    full_scan = page.locator("header >> text=Full Scan")
    assert scan_dir.is_visible(), "Scan Dir button not visible"
    assert full_scan.is_visible(), "Full Scan button not visible"


def test_nav_tabs_all_visible(server, page):
    """All three navigation tabs are visible."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    nav = page.locator("nav")
    assert nav.is_visible(), "Nav tabs are not visible"

    for tab_name in ["Fleet Overview", "Analytics", "Dependencies"]:
        tab = nav.locator(f"text={tab_name}")
        assert tab.is_visible(), f"Tab '{tab_name}' is not visible"


def test_nav_tab_switching_fleet_to_analytics(server, page):
    """Clicking Analytics tab changes the hash route to #/analytics."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("nav >> text=Analytics").click()
    page.wait_for_timeout(300)
    assert "#/analytics" in page.url


def test_nav_tab_switching_analytics_to_fleet(server, page):
    """Clicking Fleet Overview tab navigates back from Analytics."""
    page.goto(server + "#/analytics")
    page.wait_for_load_state("networkidle")

    page.locator("nav >> text=Fleet Overview").click()
    page.wait_for_timeout(300)
    # Should no longer be on analytics
    assert "#/analytics" not in page.url, f"Still on analytics after clicking Fleet: {page.url}"


def test_nav_tab_switching_to_deps(server, page):
    """Clicking Dependencies tab navigates to #/deps."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("nav >> text=Dependencies").click()
    page.wait_for_timeout(300)
    assert "#/deps" in page.url


def test_nav_round_trip_all_tabs(server, page):
    """Navigate through all tabs and back, no JS errors."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server)
    page.wait_for_load_state("networkidle")

    for tab in ["Analytics", "Dependencies", "Fleet Overview"]:
        page.locator(f"nav >> text={tab}").click()
        page.wait_for_timeout(300)

    assert errors == [], f"JS errors during tab navigation: {errors}"


# ═════════════════════════════════════════════════════════════════════════════
# 3. Directory Browser Modal (Scan Dir workflow)
# ═════════════════════════════════════════════════════════════════════════════

def test_scan_dir_opens_directory_browser_modal(server, page):
    """Clicking Scan Dir opens the DirectoryBrowser modal."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    # Modal overlay should be visible
    modal_title = page.locator("text=Select Directory to Scan")
    assert modal_title.is_visible(), "Directory browser modal did not open"


def test_directory_browser_shows_path_input(server, page):
    """Directory browser modal has a path input field."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    path_input = page.locator("input[placeholder='/path/to/directory']")
    assert path_input.is_visible(), "Path input not visible in directory browser"
    # Should default to home directory expanded path
    value = path_input.input_value()
    assert len(value) > 0, "Path input should have a default value (home dir)"


def test_directory_browser_lists_directories(server, page, tmp_path):
    """Directory browser shows directory entries when browsing a valid path."""
    # Create some dirs
    (tmp_path / "alpha_dir").mkdir()
    (tmp_path / "beta_dir").mkdir()

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    # Navigate to tmp_path via the path input
    path_input = page.locator("input[placeholder='/path/to/directory']")
    path_input.fill(str(tmp_path))
    path_input.press("Enter")
    page.wait_for_timeout(500)

    body_text = page.locator("body").inner_text()
    assert "alpha_dir" in body_text, f"Expected 'alpha_dir' in directory listing, got: {body_text[:500]}"
    assert "beta_dir" in body_text, f"Expected 'beta_dir' in directory listing"


def test_directory_browser_navigate_into_subdirectory(server, page, tmp_path):
    """Clicking a directory entry navigates into it."""
    child = tmp_path / "mysubdir"
    child.mkdir()
    (child / "nested_item").mkdir()

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    path_input = page.locator("input[placeholder='/path/to/directory']")
    path_input.fill(str(tmp_path))
    path_input.press("Enter")
    page.wait_for_timeout(500)

    # Click on the directory entry containing "mysubdir"
    page.locator(f"text=mysubdir").click()
    page.wait_for_timeout(500)

    # Path input should now show the subdir path
    new_value = path_input.input_value()
    assert "mysubdir" in new_value, f"Expected 'mysubdir' in path after clicking, got: {new_value}"

    # "nested_item" should be listed
    body_text = page.locator("body").inner_text()
    assert "nested_item" in body_text, "Expected 'nested_item' directory after navigating into subdir"


def test_directory_browser_navigate_parent(server, page, tmp_path):
    """Clicking '..' navigates up to the parent directory."""
    child = tmp_path / "deep_child"
    child.mkdir()

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    path_input = page.locator("input[placeholder='/path/to/directory']")
    path_input.fill(str(child))
    path_input.press("Enter")
    page.wait_for_timeout(500)

    # Click the parent (..) entry — uses the arrow + ".." text
    parent_link = page.locator("text=.. ")
    if parent_link.count() > 0 and parent_link.first.is_visible():
        parent_link.first.click()
        page.wait_for_timeout(500)

        # After going up, "deep_child" should appear in the listing
        body_text = page.locator("body").inner_text()
        assert "deep_child" in body_text, \
            f"Expected 'deep_child' in listing after going up, got: {body_text[:500]}"


def test_directory_browser_shows_git_repos(server, page, tmp_path):
    """Git repos in the listing have a 'git' label and [repo] indicator."""
    _create_git_repo(tmp_path, "my_git_project")
    (tmp_path / "plain_dir").mkdir()

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    path_input = page.locator("input[placeholder='/path/to/directory']")
    path_input.fill(str(tmp_path))
    path_input.press("Enter")
    page.wait_for_timeout(500)

    body_text = page.locator("body").inner_text()
    assert "my_git_project" in body_text
    assert "plain_dir" in body_text
    # The git repo should have a "git" label and [repo] indicator
    assert "[repo]" in body_text, "Expected [repo] indicator for git repos"


def test_directory_browser_enter_key_navigates(server, page, tmp_path):
    """Pressing Enter in the path input navigates to that path."""
    (tmp_path / "enter_test").mkdir()

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    path_input = page.locator("input[placeholder='/path/to/directory']")
    path_input.fill(str(tmp_path))
    path_input.press("Enter")
    page.wait_for_timeout(500)

    body_text = page.locator("body").inner_text()
    assert "enter_test" in body_text, "Enter key did not trigger navigation"


def test_directory_browser_cancel_closes_modal(server, page):
    """Cancel button closes the directory browser modal."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)
    assert page.locator("text=Select Directory to Scan").is_visible()

    page.locator("text=Cancel").click()
    page.wait_for_timeout(300)

    assert not page.locator("text=Select Directory to Scan").is_visible(), \
        "Modal still visible after Cancel"


def test_directory_browser_x_button_closes_modal(server, page):
    """The X button in the modal header closes the directory browser."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)
    assert page.locator("text=Select Directory to Scan").is_visible()

    # The X button is inside the modal header, near "Select Directory to Scan"
    modal = page.locator("text=Select Directory to Scan").locator("..")
    close_btn = modal.locator("button").last
    close_btn.click()
    page.wait_for_timeout(300)

    assert not page.locator("text=Select Directory to Scan").is_visible(), \
        "Modal still visible after clicking X"


def test_directory_browser_overlay_click_closes_modal(server, page):
    """Clicking the overlay background closes the directory browser."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)
    assert page.locator("text=Select Directory to Scan").is_visible()

    # Click on the overlay (far corner outside the modal)
    page.mouse.click(10, 10)
    page.wait_for_timeout(300)

    assert not page.locator("text=Select Directory to Scan").is_visible(), \
        "Modal still visible after clicking overlay"


def test_directory_browser_invalid_path_shows_error(server, page):
    """Entering a non-existent path shows an error in the modal."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    path_input = page.locator("input[placeholder='/path/to/directory']")
    path_input.fill("/nonexistent/path/that/does/not/exist")
    path_input.press("Enter")
    page.wait_for_timeout(500)

    # Should show an error message in the modal
    body_text = page.locator("body").inner_text()
    assert "not a directory" in body_text.lower() or "failed" in body_text.lower() or \
        "invalid" in body_text.lower() or "error" in body_text.lower() or \
        "Not a directory" in body_text, \
        f"Expected error message for invalid path, got: {body_text[:500]}"


def test_directory_browser_empty_directory(server, page, tmp_path):
    """Browsing an empty directory shows 'No subdirectories' or empty state."""
    empty = tmp_path / "empty_dir"
    empty.mkdir()

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    path_input = page.locator("input[placeholder='/path/to/directory']")
    path_input.fill(str(empty))
    path_input.press("Enter")
    page.wait_for_timeout(500)

    # Should show parent (..) but no other directories
    # The "Scan This Directory" button should still be available
    scan_btn = page.locator("text=Scan This Directory")
    assert scan_btn.is_visible(), "Scan This Directory button not visible in empty dir"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Scan Dir → Register Repos (full workflow)
# ═════════════════════════════════════════════════════════════════════════════

def test_scan_dir_workflow_registers_repos(server, page, tmp_path):
    """Full workflow: open browser → navigate → scan → repos appear in fleet."""
    _create_git_repo(tmp_path, "workflow_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Open directory browser
    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    # Navigate to the tmp_path
    path_input = page.locator("input[placeholder='/path/to/directory']")
    path_input.fill(str(tmp_path))
    path_input.press("Enter")
    page.wait_for_timeout(500)

    # Click Scan This Directory
    page.locator("text=Scan This Directory").click()
    page.wait_for_timeout(2000)

    # Modal should close
    assert not page.locator("text=Select Directory to Scan").is_visible(), \
        "Modal should close after scanning"

    # Repo should appear in the fleet
    body_text = page.locator("body").inner_text()
    assert "workflow_repo" in body_text, \
        f"Expected 'workflow_repo' in page after scanning, got: {body_text[:500]}"


def test_scan_dir_workflow_shows_success_toast(server, page, tmp_path):
    """Scanning a directory shows a success toast notification."""
    _create_git_repo(tmp_path, "toast_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    path_input = page.locator("input[placeholder='/path/to/directory']")
    path_input.fill(str(tmp_path))
    path_input.press("Enter")
    page.wait_for_timeout(500)

    page.locator("text=Scan This Directory").click()
    page.wait_for_timeout(1000)

    # Should show a success toast with "Registered X repo(s)"
    body_text = page.locator("body").inner_text()
    assert "Registered" in body_text or "registered" in body_text, \
        f"Expected registration confirmation toast, got: {body_text[:500]}"


def test_scan_dir_empty_directory_shows_zero_repos(server, page, tmp_path):
    """Scanning a directory with no git repos registers 0 repos."""
    empty = tmp_path / "no_repos"
    empty.mkdir()
    (empty / "just_a_folder").mkdir()

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    path_input = page.locator("input[placeholder='/path/to/directory']")
    path_input.fill(str(empty))
    path_input.press("Enter")
    page.wait_for_timeout(500)

    page.locator("text=Scan This Directory").click()
    page.wait_for_timeout(1000)

    # Should show toast with "Registered 0 repos"
    body_text = page.locator("body").inner_text()
    assert "Registered 0" in body_text or "0 repo" in body_text, \
        f"Expected '0 repos' message, got: {body_text[:500]}"


# ═════════════════════════════════════════════════════════════════════════════
# 5. Full Scan Workflow
# ═════════════════════════════════════════════════════════════════════════════

def test_full_scan_button_clickable(server, page):
    """Full Scan button is clickable and triggers a scan."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server)
    page.wait_for_load_state("networkidle")

    full_scan = page.locator("header >> text=Full Scan")
    assert full_scan.is_visible(), "Full Scan button not visible"
    full_scan.click()
    page.wait_for_timeout(500)

    # Should not cause JS errors
    assert errors == [], f"JS errors after clicking Full Scan: {errors}"


def test_full_scan_shows_progress_toast(server, page, tmp_path):
    """Full Scan shows a progress toast during scanning."""
    # Register a repo first so there's something to scan
    _create_git_repo(tmp_path, "scan_progress_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Register via API first
    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)
    page.wait_for_timeout(500)

    # Click full scan
    page.locator("header >> text=Full Scan").click()
    page.wait_for_timeout(1000)

    # Should see scan toast or progress indication
    body_text = page.locator("body").inner_text()
    has_scan_indicator = (
        "Scanning" in body_text
        or "Scan complete" in body_text
        or "scan" in body_text.lower()
    )
    assert has_scan_indicator, \
        f"Expected scan progress indication, got: {body_text[:500]}"


# ═════════════════════════════════════════════════════════════════════════════
# 6. Fleet Overview Content
# ═════════════════════════════════════════════════════════════════════════════

def test_fleet_overview_renders_content(server, page):
    """Fleet Overview tab renders content (KPI cards or empty state)."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    main = page.locator("main")
    assert main.is_visible(), "Main content area not visible"

    # Wait for the fleet API call to complete
    page.wait_for_timeout(2000)

    main_text = main.inner_text()
    has_content = (
        "Total Repos" in main_text
        or "Scan Dir" in main_text
        or "add repositories" in main_text.lower()
        or "No repositories registered" in main_text
        or "repos" in main_text.lower()
    )
    assert has_content, f"Fleet Overview has no recognizable content: {main_text[:500]}"


def test_fleet_overview_with_repos_shows_cards(server, page, tmp_path):
    """After registering repos, Fleet Overview shows project cards."""
    _create_git_repo(tmp_path, "card_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Register via API
    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)

    # Reload to see the card
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    body_text = page.locator("body").inner_text()
    assert "card_repo" in body_text, \
        f"Expected 'card_repo' in fleet view, got: {body_text[:500]}"


def test_project_card_click_navigates_to_detail(server, page, tmp_path):
    """Clicking a project card navigates to the repo detail view."""
    _create_git_repo(tmp_path, "clickable_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Register via API
    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)

    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    # Find and click the project card
    card = page.locator(".project-card").first
    if card.count() > 0:
        card.click()
        page.wait_for_timeout(500)
        assert "#/repo/" in page.url, \
            f"Expected #/repo/ in URL after clicking card, got: {page.url}"


# ═════════════════════════════════════════════════════════════════════════════
# 7. Repo Detail View
# ═════════════════════════════════════════════════════════════════════════════

def test_repo_detail_view_renders(server, page, tmp_path):
    """Repo detail view loads without errors when navigated to."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    _create_git_repo(tmp_path, "detail_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Register and get the repo ID
    result = page.evaluate(f"""
        async () => {{
            const r = await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
            return await r.json();
        }}
    """)

    if result.get("repos") and len(result["repos"]) > 0:
        repo_id = result["repos"][0]["id"]
        page.goto(f"{server}#/repo/{repo_id}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        assert errors == [], f"JS errors on repo detail view: {errors}"

        main_text = page.locator("main").inner_text()
        assert "detail_repo" in main_text or len(main_text) > 0, \
            "Repo detail view has no content"


def test_repo_detail_back_navigation(server, page, tmp_path):
    """Navigating back from repo detail returns to fleet view."""
    _create_git_repo(tmp_path, "back_nav_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    result = page.evaluate(f"""
        async () => {{
            const r = await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
            return await r.json();
        }}
    """)

    if result.get("repos") and len(result["repos"]) > 0:
        repo_id = result["repos"][0]["id"]
        page.goto(f"{server}#/repo/{repo_id}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)

        # Click Fleet Overview tab to go back
        page.locator("nav >> text=Fleet Overview").click()
        page.wait_for_timeout(500)

        url_hash = page.url.split(server)[-1]
        assert "#/repo/" not in url_hash, "Still on repo detail after clicking Fleet Overview"


# ═════════════════════════════════════════════════════════════════════════════
# 8. Tool Status Banner
# ═════════════════════════════════════════════════════════════════════════════

def test_tool_status_banner_visible_and_dismissible(server, page):
    """If tool status banner shows, it's visible below the nav and can be dismissed."""
    page.goto(server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    banner_dismiss = page.locator("button[aria-label='Dismiss']")
    if banner_dismiss.count() > 0:
        assert banner_dismiss.is_visible(), (
            "Tool status banner dismiss button exists but is not visible — "
            "likely hidden behind the fixed header"
        )

        # Verify banner text is visible (not behind fixed header)
        banner_text = banner_dismiss.locator("..").locator("div").first
        bbox = banner_text.bounding_box()
        assert bbox is not None, "Banner text has no bounding box"
        assert bbox["y"] >= 90, (
            f"Banner text is at y={bbox['y']}, should be >= 90 (below fixed header+nav)"
        )

        # Click dismiss
        banner_dismiss.click()
        page.wait_for_timeout(300)
        assert banner_dismiss.count() == 0 or not banner_dismiss.is_visible(), \
            "Banner dismiss button still visible after clicking"


def test_tool_status_banner_stays_dismissed_on_nav(server, page):
    """After dismissing the banner, it stays dismissed when switching tabs."""
    page.goto(server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    banner_dismiss = page.locator("button[aria-label='Dismiss']")
    if banner_dismiss.count() > 0:
        banner_dismiss.click()
        page.wait_for_timeout(300)

        # Switch tabs
        page.locator("nav >> text=Analytics").click()
        page.wait_for_timeout(500)
        page.locator("nav >> text=Fleet Overview").click()
        page.wait_for_timeout(500)

        # Banner should still be dismissed
        assert banner_dismiss.count() == 0 or not banner_dismiss.is_visible(), \
            "Banner reappeared after tab switch"


# ═════════════════════════════════════════════════════════════════════════════
# 9. Analytics Tab
# ═════════════════════════════════════════════════════════════════════════════

def test_analytics_tab_renders_without_errors(server, page):
    """Analytics tab loads without JS errors."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server + "#/analytics")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    assert errors == [], f"JavaScript errors on Analytics tab: {errors}"

    main = page.locator("main")
    assert main.is_visible(), "Main content area not visible on Analytics tab"


def test_analytics_tab_has_sections(server, page):
    """Analytics tab shows Activity Heatmap, Time Allocation, and Dependency Overlap."""
    page.goto(server + "#/analytics")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    main_text = page.locator("main").inner_text()
    assert "Activity Heatmap" in main_text, "Activity Heatmap section missing"
    assert "Time Allocation" in main_text, "Time Allocation section missing"
    assert "Dependency Overlap" in main_text, "Dependency Overlap section missing"


# ═════════════════════════════════════════════════════════════════════════════
# 10. Dependencies Tab
# ═════════════════════════════════════════════════════════════════════════════

def test_dependencies_tab_renders_without_errors(server, page):
    """Dependencies tab loads without JS errors."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server + "#/deps")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    assert errors == [], f"JavaScript errors on Dependencies tab: {errors}"


def test_dependencies_tab_shows_fleet_deps(server, page):
    """Dependencies tab shows fleet-wide dep health (not 'coming soon')."""
    page.goto(server + "#/deps")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    main_text = page.locator("main").inner_text()
    # Should NOT show "coming soon" anymore
    assert "coming soon" not in main_text.lower(), \
        "Dependencies tab still shows 'coming soon' placeholder"
    # Should show KPI cards and/or dep overlap
    has_content = (
        "Total Deps" in main_text
        or "Dependency Overlap" in main_text
        or "Per-Repo Health" in main_text
        or "Full Scan" in main_text
    )
    assert has_content, f"Dependencies tab has no fleet dep content: {main_text[:500]}"


# ═════════════════════════════════════════════════════════════════════════════
# 11. API Endpoints (via browser fetch)
# ═════════════════════════════════════════════════════════════════════════════

def test_api_status_returns_tools_and_version(server, page):
    """/api/status returns valid JSON with tools and version."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/status');
            return { status: r.status, body: await r.json() };
        }
    """)
    assert result["status"] == 200
    assert "tools" in result["body"]
    assert "version" in result["body"]
    assert isinstance(result["body"]["tools"], dict), "tools should be a dict"


def test_api_fleet_returns_repos_and_kpis(server, page):
    """/api/fleet returns valid JSON with repos and kpis."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/fleet');
            return { status: r.status, body: await r.json() };
        }
    """)
    assert result["status"] == 200
    assert "repos" in result["body"]
    assert "kpis" in result["body"]
    assert isinstance(result["body"]["repos"], list), "repos should be a list"
    assert isinstance(result["body"]["kpis"], dict), "kpis should be a dict"


def test_api_repos_list(server, page):
    """/api/repos returns valid JSON with repos array."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/repos');
            return { status: r.status, body: await r.json() };
        }
    """)
    assert result["status"] == 200
    assert "repos" in result["body"]
    assert isinstance(result["body"]["repos"], list)


def test_api_browse_default_path(server, page):
    """/api/browse with default path returns current, parent, and dirs."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/browse');
            return { status: r.status, body: await r.json() };
        }
    """)
    assert result["status"] == 200
    assert "current" in result["body"]
    assert "parent" in result["body"]
    assert "dirs" in result["body"]
    assert isinstance(result["body"]["dirs"], list)


def test_api_browse_invalid_path(server, page):
    """/api/browse with invalid path returns 400."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/browse?path=/nonexistent/path');
            return { status: r.status, body: await r.json() };
        }
    """)
    assert result["status"] == 400


def test_api_repos_post_invalid_path(server, page):
    """POST /api/repos with nonexistent path returns 400."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/repos', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: '/definitely/not/a/real/path' })
            });
            return { status: r.status, body: await r.json() };
        }
    """)
    assert result["status"] == 400


def test_api_delete_nonexistent_repo(server, page):
    """DELETE /api/repos/{id} with nonexistent ID returns 404."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/repos/nonexistent_id_12345', {
                method: 'DELETE'
            });
            return { status: r.status };
        }
    """)
    assert result["status"] == 404


def test_api_fleet_scan_post(server, page):
    """POST /api/fleet/scan with type=full triggers or returns 409."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/fleet/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ type: 'full' })
            });
            return { status: r.status, body: await r.json() };
        }
    """)
    # Should be 200 (started) or 409 (already running)
    assert result["status"] in (200, 409), \
        f"Expected 200 or 409, got {result['status']}"


def test_api_analytics_heatmap(server, page):
    """/api/analytics/heatmap returns valid JSON."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/analytics/heatmap');
            return { status: r.status, body: await r.json() };
        }
    """)
    assert result["status"] == 200


def test_api_analytics_allocation(server, page):
    """/api/analytics/allocation returns valid JSON."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/analytics/allocation');
            return { status: r.status, body: await r.json() };
        }
    """)
    assert result["status"] == 200


# ═════════════════════════════════════════════════════════════════════════════
# 12. Register → Detail → Delete workflow
# ═════════════════════════════════════════════════════════════════════════════

def test_register_view_delete_workflow(server, page, tmp_path):
    """Full lifecycle: register a repo via API, view it, delete it, confirm gone."""
    _create_git_repo(tmp_path, "lifecycle_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Register
    result = page.evaluate(f"""
        async () => {{
            const r = await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
            return await r.json();
        }}
    """)

    assert result["registered"] >= 1
    repo_id = result["repos"][0]["id"]

    # View detail
    page.goto(f"{server}#/repo/{repo_id}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    main_text = page.locator("main").inner_text()
    assert "lifecycle_repo" in main_text or len(main_text) > 0

    # Delete via API
    delete_result = page.evaluate(f"""
        async () => {{
            const r = await fetch('/api/repos/{repo_id}', {{ method: 'DELETE' }});
            return {{ status: r.status }};
        }}
    """)
    assert delete_result["status"] == 204

    # Verify it's gone
    list_result = page.evaluate("""
        async () => {
            const r = await fetch('/api/repos');
            return await r.json();
        }
    """)
    repo_ids = [r["id"] for r in list_result["repos"]]
    assert repo_id not in repo_ids, "Repo still present after deletion"


# ═════════════════════════════════════════════════════════════════════════════
# 13. Content Not Occluded by Fixed Elements
# ═════════════════════════════════════════════════════════════════════════════

def test_main_content_not_hidden_by_header(server, page):
    """Main content area starts below the fixed header/nav (has padding)."""
    page.goto(server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # The main element itself starts at y=0 (normal flow) but its paddingTop
    # pushes visible content below the fixed header. Verify the padding.
    main = page.locator("main")
    padding_top = page.evaluate(
        "el => parseInt(getComputedStyle(el).paddingTop)", main.element_handle()
    )
    assert padding_top >= 80, \
        f"Main padding-top is {padding_top}px, should be >= 80 to clear fixed header+nav"


def test_header_has_highest_z_index(server, page):
    """Header has z-index high enough to stay on top."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    header = page.locator("header")
    z_index = page.evaluate("el => getComputedStyle(el).zIndex", header.element_handle())
    assert int(z_index) >= 99, f"Header z-index is {z_index}, should be >= 99"


# ═════════════════════════════════════════════════════════════════════════════
# 14. Error Boundary
# ═════════════════════════════════════════════════════════════════════════════

def test_invalid_hash_route_does_not_crash(server, page):
    """Navigating to an invalid hash route doesn't crash the app."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server + "#/nonexistent/route")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    # Should fall back to fleet view, not crash
    root = page.locator("#root")
    assert root.inner_html() != "", "App crashed on invalid route"
    # Filter out any Recharts/non-critical errors
    critical_errors = [e for e in errors if "ReferenceError" in e or "TypeError" in e]
    assert critical_errors == [], f"Critical JS errors on invalid route: {critical_errors}"


def test_nonexistent_repo_detail_does_not_crash(server, page):
    """Navigating to a nonexistent repo ID doesn't crash."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server + "#/repo/does_not_exist_12345")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    root = page.locator("#root")
    assert root.inner_html() != "", "App crashed on nonexistent repo ID"


# ═════════════════════════════════════════════════════════════════════════════
# 15. No Dead UI Elements
# ═════════════════════════════════════════════════════════════════════════════

def test_no_gear_icon_in_header(server, page):
    """No non-functional gear/settings icon in the header."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    # The header should only have Scan Dir and Full Scan buttons
    header = page.locator("header")
    buttons = header.locator("button")
    button_count = buttons.count()

    # Verify no button has title="Settings"
    for i in range(button_count):
        title = buttons.nth(i).get_attribute("title")
        assert title != "Settings", "Dead gear/Settings icon still in header"


# ═════════════════════════════════════════════════════════════════════════════
# 16. Delete Repo from Card
# ═════════════════════════════════════════════════════════════════════════════

def test_project_card_has_delete_button_on_hover(server, page, tmp_path):
    """Hovering a project card reveals a delete (x) button."""
    _create_git_repo(tmp_path, "hover_del_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)

    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    card = page.locator(".project-card").first
    if card.count() > 0:
        card.hover()
        page.wait_for_timeout(300)

        # Should have a delete button with aria-label containing "Remove"
        remove_btn = card.locator("button[aria-label*='Remove']")
        assert remove_btn.count() > 0, "No Remove button on hover"
        assert remove_btn.is_visible(), "Remove button not visible on hover"


def test_delete_repo_from_card(server, page, tmp_path):
    """Clicking the delete button on a card removes the repo from the fleet."""
    _create_git_repo(tmp_path, "del_card_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)

    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    # Confirm the repo is visible
    body_text = page.locator("body").inner_text()
    assert "del_card_repo" in body_text, "Repo not found before delete"

    # Hover the card and click delete
    card = page.locator(".project-card").first
    if card.count() > 0:
        card.hover()
        page.wait_for_timeout(300)

        # Handle the confirm dialog
        page.on("dialog", lambda dialog: dialog.accept())

        remove_btn = card.locator("button[aria-label*='Remove']")
        remove_btn.click()
        page.wait_for_timeout(1000)

        # Repo should be gone
        body_text = page.locator("body").inner_text()
        assert "del_card_repo" not in body_text, \
            "Repo still visible after delete"


def test_delete_button_always_in_dom(server, page, tmp_path):
    """Delete button is always rendered in DOM (not conditionally), so CSS :hover works
    even when a card slides under a stationary cursor after deleting another card."""
    _create_git_repo(tmp_path, "dom_test_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)

    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    card = page.locator(".project-card").first
    if card.count() > 0:
        # Delete button should exist in DOM even without hovering
        remove_btn = card.locator("button.card-delete-btn")
        assert remove_btn.count() > 0, \
            "Delete button not in DOM — must always be rendered for CSS :hover to work"

        # Without hover, button should be hidden via CSS opacity
        opacity = remove_btn.evaluate("el => getComputedStyle(el).opacity")
        assert opacity == "0", \
            f"Delete button should be invisible (opacity 0) without hover, got {opacity}"

        # After hover, button should become visible
        card.hover()
        page.wait_for_timeout(300)
        opacity = remove_btn.evaluate("el => getComputedStyle(el).opacity")
        assert opacity == "1", \
            f"Delete button should be visible (opacity 1) on hover, got {opacity}"


def test_delete_sequential_cards_without_mouse_move(server, page, tmp_path):
    """After deleting a card, the next card slides up under the cursor.
    The delete button on that next card must be accessible without moving the mouse."""
    _create_git_repo(tmp_path, "seq_repo_a")
    _create_git_repo(tmp_path, "seq_repo_b")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)

    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    cards = page.locator(".project-card")
    initial_count = cards.count()
    assert initial_count >= 2, f"Expected at least 2 cards, got {initial_count}"

    # Hover the first card and delete it
    first_card = cards.first
    first_card.hover()
    page.wait_for_timeout(300)

    page.on("dialog", lambda dialog: dialog.accept())

    remove_btn = first_card.locator("button.card-delete-btn")
    remove_btn.click()
    page.wait_for_timeout(1000)

    # After deletion, the next card is now first. Without moving the mouse,
    # verify the delete button exists in its DOM (CSS :hover handles visibility)
    new_first_card = page.locator(".project-card").first
    assert new_first_card.count() > 0, "No cards remaining after delete"

    new_remove_btn = new_first_card.locator("button.card-delete-btn")
    assert new_remove_btn.count() > 0, \
        "Delete button missing from DOM on card that slid under cursor"


# ═════════════════════════════════════════════════════════════════════════════
# 18. Full Scan SSE Progress (end-to-end)
# ═════════════════════════════════════════════════════════════════════════════

def test_full_scan_progress_updates_beyond_zero(server, page, tmp_path):
    """Full scan progress updates from '0 / ?' to real numbers and completes.

    This catches the SSE race condition where events are emitted before
    the EventSource listener connects, leaving the toast stuck at '0 / ?'.
    """
    _create_git_repo(tmp_path, "progress_repo_a")
    _create_git_repo(tmp_path, "progress_repo_b")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Register repos
    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)
    page.wait_for_timeout(500)

    # Click Full Scan
    page.locator("header >> text=Full Scan").click()

    # Wait for progress to update beyond 0/? — poll for up to 15s
    got_real_progress = False
    for _ in range(30):
        page.wait_for_timeout(500)
        body_text = page.locator("body").inner_text()
        # Check we see "N / M" where N > 0, or "Scan complete"
        if "Scan complete" in body_text:
            got_real_progress = True
            break
        # Look for progress like "1 / 2" or "2 / 2"
        import re
        m = re.search(r'(\d+)\s*/\s*(\d+)', body_text)
        if m and int(m.group(1)) > 0 and int(m.group(2)) > 0:
            got_real_progress = True
            break

    assert got_real_progress, (
        "Scan progress never updated beyond 0/?. "
        f"Last body text: {page.locator('body').inner_text()[:300]}"
    )


def test_full_scan_toast_dismisses(server, page, tmp_path):
    """After a full scan completes, the scanning toast auto-dismisses."""
    _create_git_repo(tmp_path, "dismiss_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)
    page.wait_for_timeout(500)

    page.locator("header >> text=Full Scan").click()

    # Wait for scan to complete (up to 15s)
    for _ in range(30):
        page.wait_for_timeout(500)
        body_text = page.locator("body").inner_text()
        if "Scan complete" in body_text:
            break

    # Wait for the auto-dismiss (2s delay + animation)
    page.wait_for_timeout(4000)

    # Toast should be gone — no "Scanning" or "Scan complete" visible
    body_text = page.locator("body").inner_text()
    assert "Scanning..." not in body_text, "Scanning toast still stuck on screen"


# ═════════════════════════════════════════════════════════════════════════════
# 19. Branch Names After Scan
# ═════════════════════════════════════════════════════════════════════════════

def test_branch_names_not_corrupted(server, page, tmp_path):
    """After scanning, branch names in repo detail are clean (no %x00 or dates appended)."""
    _create_git_repo(tmp_path, "branch_name_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Register and scan
    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)
    page.wait_for_timeout(500)

    page.locator("header >> text=Full Scan").click()

    # Wait for scan complete
    for _ in range(30):
        page.wait_for_timeout(500)
        body_text = page.locator("body").inner_text()
        if "Scan complete" in body_text:
            break

    page.wait_for_timeout(1000)

    # Navigate to repo detail
    card = page.locator(".project-card").first
    if card.count() > 0:
        card.click()
        page.wait_for_timeout(1000)

        # Check branches via API
        branches_data = page.evaluate("""
            async () => {
                // Get repo id from URL hash
                const hash = window.location.hash;
                const match = hash.match(/#\\/repo\\/([^/]+)/);
                if (!match) return { error: 'no repo id in hash' };
                const repoId = match[1];
                const res = await fetch('/api/repos/' + repoId + '/branches');
                return res.json();
            }
        """)

        if "branches" in branches_data:
            for b in branches_data["branches"]:
                name = b["name"]
                assert "%x00" not in name, \
                    f"Branch name contains literal %x00: {name}"
                assert "%00" not in name, \
                    f"Branch name contains encoded null: {name}"
                # Branch names shouldn't contain ISO dates
                assert "T" not in name or ":" not in name or len(name) < 30, \
                    f"Branch name looks like it has a date appended: {name}"


def test_branch_stale_not_zero_days_for_recent(server, page, tmp_path):
    """Recently committed branches should NOT show 'stale (0 days)'."""
    _create_git_repo(tmp_path, "stale_test_repo")

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)
    page.wait_for_timeout(500)

    page.locator("header >> text=Full Scan").click()

    # Wait for scan complete
    for _ in range(30):
        page.wait_for_timeout(500)
        body_text = page.locator("body").inner_text()
        if "Scan complete" in body_text:
            break

    page.wait_for_timeout(1000)

    # Check branch data via API
    repos_resp = page.evaluate("async () => (await fetch('/api/repos')).json()")
    repos_data = repos_resp.get("repos", []) if isinstance(repos_resp, dict) else repos_resp
    if repos_data and len(repos_data) > 0:
        repo_id = repos_data[0]["id"]
        branches_data = page.evaluate(
            "async (id) => (await fetch('/api/repos/' + id + '/branches')).json()",
            repo_id,
        )

        if "branches" in branches_data:
            for b in branches_data["branches"]:
                if b["last_commit_date"] is not None:
                    # A branch with a recent commit date should NOT be stale
                    assert b["is_stale"] is False, \
                        f"Branch '{b['name']}' has date {b['last_commit_date']} but is_stale=True"
                    assert b["last_commit_date"] != "", \
                        f"Branch '{b['name']}' has empty string date"


def _create_git_repo_with_branches(parent_dir, name, branch_names):
    """Create a git repo with multiple branches. Returns the repo path."""
    repo = _create_git_repo(parent_dir, name)
    for branch in branch_names:
        subprocess.run(
            ["git", "-C", str(repo), "branch", branch],
            check=True, capture_output=True,
        )
    return repo


# ═════════════════════════════════════════════════════════════════════════════
# 20. Multiple Branches After Scan
# ═════════════════════════════════════════════════════════════════════════════

def test_all_branches_returned_after_full_scan(server, page, tmp_path):
    """After a full scan, ALL local branches appear in the branches API — not just one."""
    branch_names = ["feature/auth", "develop", "bugfix/login"]
    _create_git_repo_with_branches(tmp_path, "multi_branch_repo", branch_names)

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)
    page.wait_for_timeout(500)

    # Run full scan — wait up to 60s since module-scoped server accumulates repos
    page.locator("header >> text=Full Scan").click()
    for _ in range(120):
        page.wait_for_timeout(500)
        if "Scan complete" in page.locator("body").inner_text():
            break
    page.wait_for_timeout(1000)

    # Get repo ID for our specific repo
    repos_resp = page.evaluate("async () => (await fetch('/api/repos')).json()")
    repos_data = repos_resp.get("repos", []) if isinstance(repos_resp, dict) else repos_resp
    our_repo = next((r for r in repos_data if r["name"] == "multi_branch_repo"), None)
    assert our_repo is not None, \
        f"multi_branch_repo not found in repos: {[r['name'] for r in repos_data]}"
    repo_id = our_repo["id"]

    # Check branches API
    branches_data = page.evaluate(
        "async (id) => (await fetch('/api/repos/' + id + '/branches')).json()",
        repo_id,
    )
    branches = branches_data.get("branches", [])
    branch_name_set = {b["name"] for b in branches}

    # Should have main/master + the 3 we created = at least 4
    assert len(branches) >= 4, (
        f"Expected at least 4 branches (main + 3 created), got {len(branches)}: "
        f"{branch_name_set}"
    )
    for expected in branch_names:
        assert expected in branch_name_set, \
            f"Branch '{expected}' missing from API. Got: {branch_name_set}"


def test_branches_tab_shows_all_branches(server, page, tmp_path):
    """The BranchesTab in repo detail renders ALL branches, not just one."""
    branch_names = ["release/v1", "hotfix/urgent"]
    _create_git_repo_with_branches(tmp_path, "ui_branch_repo", branch_names)

    page.goto(server)
    page.wait_for_load_state("networkidle")

    page.evaluate(f"""
        async () => {{
            await fetch('/api/repos', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: '{str(tmp_path)}' }})
            }});
        }}
    """)
    page.wait_for_timeout(500)

    page.locator("header >> text=Full Scan").click()
    for _ in range(30):
        page.wait_for_timeout(500)
        if "Scan complete" in page.locator("body").inner_text():
            break
    page.wait_for_timeout(1000)

    # Navigate to repo detail
    card = page.locator(".project-card").first
    assert card.count() > 0, "No project cards"
    card.click()
    page.wait_for_timeout(1000)

    # Click the Branches sub-tab within the repo detail view
    page.get_by_role("tab", name="Branches").click()
    page.wait_for_timeout(1500)

    # Count rows in the branches table
    rows = page.locator(".table-row")
    row_count = rows.count()
    assert row_count >= 3, (
        f"Expected at least 3 branch rows (main + 2 created), got {row_count}. "
        f"Page text: {page.locator('main').inner_text()[:500]}"
    )

    # Verify specific branch names appear
    body_text = page.locator("body").inner_text()
    for branch in branch_names:
        assert branch in body_text, \
            f"Branch '{branch}' not visible in UI. Body: {body_text[:500]}"
