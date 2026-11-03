"""
End-to-end tests using Playwright.

These tests start the real git_dashboard server and exercise it in a real
Chromium browser. They catch rendering errors, external asset requests, dead buttons,
and layout issues that unit tests miss entirely.

Run the complete suite from the repository root:
    UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py git_fleet

IMPORTANT: E2E tests must NOT run in the same pytest invocation as unit tests.
The runner preserves separate invocations because Playwright's event loop
conflicts with asyncio.run() used by unit tests.

If Chromium is missing, install it once with:
    UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py git_fleet --install-browsers
"""

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

# ── Check playwright is installed ────────────────────────────────────────────
try:
    from playwright.sync_api import expect  # noqa: F401
except ImportError:
    pytest.skip(
        "playwright not installed — run from the repository root: "
        "UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py git_fleet",
        allow_module_level=True,
    )

pytestmark = pytest.mark.e2e

PROJECT_ROOT = Path(__file__).parent.parent
REPO_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import (  # noqa: E402
    assert_fonts_loaded,
    assert_no_external_resources,
    assert_offline_page_source,
    block_external_requests,
    capture_browser_errors,
    guard_browser_errors,
)

GIT_DASHBOARD = PROJECT_ROOT / "git_dashboard.py"


@pytest.fixture(scope="session")
def browser_type_launch_args():
    return {"headless": True}


def test_long_running_scan_keeps_browser_progress(page, tmp_path):
    """An idle interval during real scan work must not end the browser stream."""
    repo = _create_git_repo(tmp_path, "slow_repo")
    db_path = tmp_path / "state.db"
    timeout_seen = tmp_path / "timeout-seen"
    release = tmp_path / "release"
    script = tmp_path / "server.py"
    script.write_text('''
import asyncio, sqlite3, sys
from pathlib import Path
import uvicorn
sys.path.insert(0, sys.argv[1])
import git_dashboard as app
app.DB_PATH = Path(sys.argv[2])
app.init_schema(app.DB_PATH)
with sqlite3.connect(app.DB_PATH) as db:
    db.execute("INSERT INTO repositories (id, name, path, added_at) VALUES ('r', 'slow_repo', ?, 'x')", (sys.argv[3],))
seen, release = Path(sys.argv[4]), Path(sys.argv[5])
real_asyncio = asyncio
class AsyncioProxy:
    def __getattr__(self, name):
        return getattr(real_asyncio, name)
    async def wait_for(self, coro, timeout):
        try:
            return await real_asyncio.wait_for(coro, timeout=0.1 if timeout == 60 else timeout)
        except real_asyncio.TimeoutError:
            seen.touch()
            raise
app.asyncio = AsyncioProxy()
async def slow_history(*args):
    while not release.exists():
        await real_asyncio.sleep(0.01)
async def no_op(*args):
    pass
app.run_full_history_scan = slow_history
app.run_branch_scan = no_op
app.run_dep_scan_for_repo = no_op
uvicorn.run(app.app, host="127.0.0.1", port=int(sys.argv[6]), log_level="error")
''')
    port = _find_free_port()
    env = dict(os.environ, GIT_DASHBOARD_NO_BROWSER="1")
    proc = subprocess.Popen(
        [sys.executable, str(script), str(PROJECT_ROOT), str(db_path), str(repo),
         str(timeout_seen), str(release), str(port)], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        assert _wait_for_server(port)
        page.goto(f"http://127.0.0.1:{port}")
        page.locator("header >> text=Full Scan").click()
        deadline = time.monotonic() + 10
        while not timeout_seen.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert timeout_seen.exists(), "stream did not reach the idle interval"
        expect(page.locator("header >> text=Full Scan")).to_be_disabled()
        assert "Scan failed" not in page.locator("body").inner_text()
        release.touch()
        expect(page.get_by_text("Scan complete", exact=False).first).to_be_visible(timeout=10000)
    finally:
        release.touch()
        proc.terminate()
        proc.wait(timeout=10)


def test_page_loads_offline(browser, server):
    context = browser.new_context()
    blocked = block_external_requests(context, allowed_origins=[server])
    page = context.new_page()
    try:
        with guard_browser_errors(page):
            page.goto(server, wait_until="domcontentloaded")
            expect(page.locator("header")).to_be_visible(timeout=10000)
            assert_fonts_loaded(page, ["Geist", "JetBrains Mono"])
            assert_no_external_resources(page, blocked)
            assert_offline_page_source(page.content())
    finally:
        context.close()


@pytest.fixture(autouse=True)
def fail_on_unexpected_browser_errors(page, request):
    """Fail on browser errors, except exact HTTP failures a test intentionally causes."""
    errors = capture_browser_errors(page)
    error_responses = []
    page.on(
        "response",
        lambda response: error_responses.append((response.status, response.url))
        if response.status >= 400
        else None,
    )
    yield
    expected_http_errors = []
    for marker in request.node.iter_markers("allows_http_error"):
        status, count, endpoint_pattern = marker.args
        pattern = re.compile(
            rf"Failed to load resource: the server responded "
            rf"with a status of {status} \([^\n]+\)"
        )
        matches = [error for error in errors if pattern.fullmatch(error)]
        assert len(matches) == count, (
            f"Expected {count} browser HTTP {status} errors, got {len(matches)}: {errors}"
        )
        response_matches = [
            (response_status, url)
            for response_status, url in error_responses
            if response_status == status and re.search(endpoint_pattern, url)
        ]
        assert len(response_matches) == count, (
            f"Expected {count} HTTP {status} responses matching {endpoint_pattern!r}, "
            f"got {response_matches}; all error responses: {error_responses}"
        )
        expected_http_errors.extend(matches)
    unexpected = errors.copy()
    for expected in expected_http_errors:
        unexpected.remove(expected)
    assert unexpected == [], "Unexpected browser errors:\n" + "\n".join(unexpected)


def _open_app(page, url):
    """Navigate and wait for the mounted shell."""
    page.goto(url, wait_until="domcontentloaded")
    # DOMContentLoaded can precede the application mount.
    expect(page.locator("header")).to_be_visible(timeout=30000)


# Selector hooks for scripts and tests; none of them carries a style of its own.
CHART_HOOK_CLASSES = (
    "activity-chart", "allocation-chart", "detail-content", "svgc-area", "svgc-curve", "svgc-grid-horizontal",
    "svgc-grid-vertical", "svgc-point", "svgc-reference-line", "svgc-x-axis-line",
)


def _assert_charts_finite(page):
    for chart in page.locator(".svgc-wrapper").evaluate_all("nodes => nodes.map(node => node.outerHTML)"):
        assert not re.search(r"NaN|Infinity|undefined", chart), chart[:500]


def _assert_tooltip_readable_in_viewport(page, tooltip):
    tooltip.wait_for(state="visible")
    page.wait_for_function("""() => {
        const el = document.querySelector('.svgc-tooltip');
        if (!el) return false;
        const r = el.getBoundingClientRect();
        const chart = el.parentElement.getBoundingClientRect();
        return r.left >= Math.max(0, chart.left) && r.top >= Math.max(0, chart.top) &&
               r.right <= Math.min(innerWidth, chart.right) && r.bottom <= Math.min(innerHeight, chart.bottom);
    }""")
    assert tooltip.bounding_box()
    assert tooltip.evaluate("el => el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight")
    assert tooltip.evaluate("""el => [...el.querySelectorAll('div')].every(div =>
        [...div.childNodes].filter(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim())
          .every(node => { const range = document.createRange(); range.selectNodeContents(node);
                           return range.getClientRects().length === 1; }))""")


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


@pytest.fixture(scope="session")
def base_url():
    """Supply Playwright's optional URL without its deprecated fixture."""
    return None


@pytest.fixture(scope="module")
def server_context(tmp_path_factory):
    """Start git_dashboard server on a random port with an isolated temp DB.

    Uses GIT_DASHBOARD_DB env var to point the server at a throwaway database,
    so test repos never pollute the user's real data.
    """
    port = _find_free_port()
    tmp_dir = tmp_path_factory.mktemp("e2e_db")
    db_path = tmp_dir / "test_dashboard.db"
    server_home = tmp_path_factory.mktemp("e2e_server_home")

    env = dict(os.environ)
    env["HOME"] = str(server_home)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
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

    yield {"url": f"http://localhost:{port}", "db_path": db_path, "home": server_home}

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    # Clean up the temp DB (tmp_path_factory handles directory cleanup)


@pytest.fixture(scope="module")
def server(server_context):
    """Preserve the URL-only fixture used by existing callers."""
    return server_context['url']


def test_fleet_browser_refresh_scans_synthetic_repo(page, server_context, tmp_path):
    import sqlite3
    repo = _create_git_repo(tmp_path, 'synthetic-refresh')
    with sqlite3.connect(server_context['db_path']) as db:
        db.execute("INSERT INTO repositories (id,name,path,added_at) VALUES (?,?,?,?)",
                   ('synthetic-refresh', 'synthetic-refresh', str(repo), '2026-01-01'))
    try:
        with page.expect_response(lambda r: r.url.endswith('/api/fleet/refresh') and r.request.method == 'POST') as response:
            _open_app(page, server_context['url'])
        assert response.value.status == 200
        expect(page.get_by_text('synthetic-refresh', exact=True)).to_be_visible()
        with sqlite3.connect(server_context['db_path']) as db:
            assert db.execute("SELECT checked_at FROM working_state WHERE repo_id=?", ('synthetic-refresh',)).fetchone()[0]
    finally:
        with sqlite3.connect(server_context['db_path']) as db:
            db.execute('DELETE FROM working_state WHERE repo_id=?', ('synthetic-refresh',))
            db.execute('DELETE FROM repositories WHERE id=?', ('synthetic-refresh',))


def test_card_shows_status_failed_badge(page, server_context, tmp_path):
    import sqlite3
    repo = _create_git_repo(tmp_path, 'synthetic-corrupt')
    (repo / '.git' / 'index').write_bytes(b'synthetic corrupt index')
    with sqlite3.connect(server_context['db_path']) as db:
        db.execute("INSERT INTO repositories (id,name,path,added_at) VALUES (?,?,?,?)",
                   ('synthetic-corrupt', 'synthetic-corrupt', str(repo), '2026-01-01'))
    try:
        _open_app(page, server_context['url'])
        card = page.locator('.project-card').filter(has_text='synthetic-corrupt')
        badge = card.get_by_text('status failed', exact=True)
        expect(badge).to_be_visible()
        badge.hover()
        expect(badge).to_be_visible()
        assert badge.get_attribute('title')
        expect(card.get_by_text('Clean', exact=True)).to_have_count(0)
    finally:
        with sqlite3.connect(server_context['db_path']) as db:
            db.execute('PRAGMA foreign_keys = ON')
            db.execute('DELETE FROM repositories WHERE id=?', ('synthetic-corrupt',))


@pytest.fixture
def seeded_coverage(server_context, dependency_report_seed, tmp_path):
    import sqlite3
    import uuid
    repo_id = 'synthetic-' + uuid.uuid4().hex
    repo_path = _create_git_repo(tmp_path, 'synthetic-coverage')
    dependency_report_seed['seed'](server_context['db_path'], repo_id, repo_path)
    yield dict(dependency_report_seed, repo_id=repo_id, **server_context)
    with sqlite3.connect(server_context['db_path']) as db:
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('DELETE FROM repositories WHERE id=?', (repo_id,))


def _open_coverage(page, seeded):
    _open_app(page, seeded['url'] + '/#/repo/' + seeded['repo_id'] + '/deps')
    expect(page.get_by_role('button', name='Export JSON')).to_be_visible()


def _download_text(page, button):
    with page.expect_download() as download:
        page.get_by_role('button', name=button, exact=True).click()
    return Path(download.value.path()).read_text()


def test_deps_tab_reports_partial_coverage(page, seeded_coverage):
    seeded = seeded_coverage
    _open_coverage(page, seeded)
    expect(page.get_by_test_id('dep-coverage')).to_contain_text(f"{seeded['summary']['unchecked']} not checked")
    expect(page.get_by_test_id('dep-not-checked')).to_contain_text('synthetic-partial-vuln')
    expect(page.get_by_test_id('dep-not-checked')).to_contain_text('synthetic-partial-major')
    expect(page.get_by_test_id('dep-not-checked')).to_contain_text('synthetic-partial-outdated')
    expect(page.get_by_test_id('dep-all')).to_contain_text('evaluated 1.5 (floating)')
    expect(page.get_by_text('No issues found — all dependencies are up to date.')).to_have_count(0)
    expect(page.get_by_test_id('dep-all')).to_contain_text('>=1,<2')
    attention = page.locator('section').filter(has=page.get_by_role('heading', name='Attention Required', exact=True))
    expect(attention.locator('tbody tr').first.locator('td').first).to_have_text('synthetic-partial-vuln')
    # Metadata and version must be reloaded after Check Now, not stale parent props.
    detail_url = f"**/api/repos/{seeded['repo_id']}"
    detail = page.request.get(seeded['url'] + '/api/repos/' + seeded['repo_id']).json()
    detail['working_state']['missing_dep_tools'] = [dict(tool='synthetic-refreshed', description='Synthetic refresh')]
    detail['working_state']['dep_manifests'].append(dict(path='refreshed-empty.txt', kind='requirements', dependencies=0, error=None))
    status = page.request.get(seeded['url'] + '/api/status').json()
    status['version'] = 'synthetic-refreshed-version'
    groups = page.request.get(seeded['url'] + '/api/repos/' + seeded['repo_id'] + '/deps').json()
    page.route(detail_url, lambda route: route.fulfill(json=detail))
    page.route('**/api/status', lambda route: route.fulfill(json=status))
    page.route(f"**/api/repos/{seeded['repo_id']}/scan/deps", lambda route: route.fulfill(json=groups))
    page.get_by_role('button', name='Check Now', exact=True).click()
    expect(page.get_by_text('synthetic-refreshed — Synthetic refresh', exact=True)).to_be_visible()
    report = json.loads(_download_text(page, 'Export JSON'))
    assert report['git_fleet_version'] == status['version']
    assert report['manifests'] == detail['working_state']['dep_manifests']


def test_markdown_export_includes_coverage_and_inventory(page, seeded_coverage):
    _open_coverage(page, seeded_coverage)
    md = _download_text(page, 'Export MD')
    assert md.startswith('# Dependency Report')
    for section in ('Attention Required', 'Not Checked', 'All Dependencies', 'Manifests Scanned', 'Scope'):
        assert '## ' + section in md
    for row in seeded_coverage['rows']:
        for field in ('name', 'declared_spec', 'outdated_state', 'vuln_state'):
            assert row[field] in md
        if row['check_note']:
            assert row['check_note'] in md
    for manifest in seeded_coverage['manifests']:
        assert manifest['path'] in md
        if manifest['error']:
            assert manifest['error'] in md
    assert f"Not checked: {seeded_coverage['summary']['unchecked']}" in md
    assert 'Synthetic coverage repository' in md
    assert '2026-01-02T03:04:05+00:00' in md


def test_json_export_obeys_report_contract(page, seeded_coverage):
    _open_coverage(page, seeded_coverage)
    report = json.loads(_download_text(page, 'Export JSON'))
    assert report['format'] == 'git-fleet-dependency-report'
    assert report['format_version'] == 2
    assert report['summary'] == seeded_coverage['summary']
    assert report['manifests'] == seeded_coverage['manifests']
    assert report['missing_tools'] == seeded_coverage['missing_tools']
    assert report['repo'] == dict(id=seeded_coverage['repo_id'], name='Synthetic coverage repository')
    status = page.request.get(seeded_coverage['url'] + '/api/status').json()
    assert report['git_fleet_version'] == status['version']
    assert report['scope'] == status['dependency_scope']
    assert report['generated_at']
    assert len([r for g in report['groups'] for r in g['packages']]) == len(seeded_coverage['rows'])


def test_overlap_lists_manifest_uses_without_duplicate_keys(page, seeded_coverage):
    messages = []
    page.on('console', lambda message: messages.append(message.text))
    _open_app(page, seeded_coverage['url'] + '/#/deps')
    overlap = page.locator('tr').filter(has=page.get_by_text('synthetic-clean', exact=True))
    overlap.get_by_text('2 uses in 1 repos', exact=False).click()
    expect(page.get_by_text('Synthetic coverage repository — requirements.txt — 1.0', exact=True)).to_be_visible()
    expect(page.get_by_text('Synthetic coverage repository — nested/pyproject.toml — 2.0', exact=True)).to_be_visible()
    assert not any('same key' in m or 'unique "key"' in m for m in messages)


def test_fleet_kpi_displays_unchecked_coverage(page, seeded_coverage):
    _open_app(page, seeded_coverage['url'])
    expect(page.get_by_text('Not Checked', exact=True)).to_be_visible()
    expect(page.get_by_text('Not Checked', exact=True).locator('..').locator('div').first).to_have_text(str(seeded_coverage['summary']['unchecked']))
    expect(page.locator('[title*="not checked"]').first).to_be_visible()
    page.locator('nav').get_by_role('link', name='Dependencies', exact=True).click()
    expect(page).to_have_url(re.compile(r'/#/deps$'))
    expect(page.get_by_role('heading', name='Per-Repo Health', exact=True)).to_be_visible()
    expect(page.get_by_text('Not Checked', exact=True).first).to_be_visible()
    expect(page.get_by_text('Not Checked', exact=True).first.locator('..').locator('div').first).to_have_text(str(seeded_coverage['summary']['unchecked']))


@pytest.mark.parametrize('clean_row', [False, True])
@pytest.mark.parametrize('failure', ['inventory', 'missing_tool'])
def test_fleet_retains_repository_coverage_without_unchecked_rows(page, seeded_coverage, clean_row, failure):
    """Repository analysis failures survive zero rows and fully checked declarations."""
    import sqlite3
    seeded = seeded_coverage
    with sqlite3.connect(seeded['db_path']) as db:
        db.execute('DELETE FROM dependencies WHERE repo_id=?', (seeded['repo_id'],))
        if clean_row:
            db.execute("INSERT INTO dependencies (repo_id,name,manager,source_path,declared_spec,current_version,latest_version,severity,outdated_state,vuln_state) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (seeded['repo_id'], 'synthetic-clean-widget', 'npm', 'package.json', '^1.0.0', '1.0.0', '1.0.0', 'ok', 'checked', 'checked'))
        tools = [] if failure == 'inventory' else [dict(tool='synthetic-auditor', description='Synthetic absent tool')]
        manifests = [dict(path='synthetic-broken.toml', kind='pyproject', dependencies=0, error='Synthetic parse failure')] if failure == 'inventory' else []
        db.execute('UPDATE working_state SET dep_check_error=?,missing_dep_tools=?,dep_manifests=? WHERE repo_id=?',
                   (int(failure == 'inventory'), json.dumps(tools), json.dumps(manifests), seeded['repo_id']))
    _open_app(page, seeded['url'])
    card = page.locator('.project-card').filter(has=page.get_by_text('Synthetic coverage repository', exact=True))
    expect(card.locator('[title*="Incomplete coverage"]')).to_be_visible()
    expect(card.locator('[title="All declarations fully checked"]')).to_have_count(0)
    if failure == 'inventory':
        expect(card.locator('[title*="analysis error"]')).to_be_visible()
    else:
        expect(card.locator('[title*="synthetic-auditor"]')).to_be_visible()
    page.locator('nav').get_by_role('link', name='Dependencies', exact=True).click()
    row = page.locator('.table-row').filter(has=page.get_by_text('Synthetic coverage repository', exact=True))
    expect(row).to_be_visible()
    expect(row.locator('[title*="Incomplete coverage"]')).to_be_visible()
    expect(row.locator('span').last).to_have_text('0')
    expect(page.get_by_text('Not Checked', exact=True).first.locator('..').locator('div').first).to_have_text('0')
    expect(page.get_by_text('No dependencies detected. Run a Full Scan to discover dependencies in your repos.')).to_have_count(0)


def test_empty_inventory_remains_exportable_and_incomplete(page, seeded_coverage):
    import sqlite3
    with sqlite3.connect(seeded_coverage['db_path']) as db:
        db.execute('DELETE FROM dependencies WHERE repo_id=?', (seeded_coverage['repo_id'],))
    _open_coverage(page, seeded_coverage)
    expect(page.get_by_test_id('dep-coverage')).to_contain_text('Incomplete coverage')
    expect(page.get_by_test_id('dep-coverage')).to_contain_text(f"{len(seeded_coverage['manifests'])} manifests")
    expect(page.get_by_text('No dependencies detected', exact=True)).to_be_visible()
    expect(page.get_by_text('Newest declaration check: No declaration check timestamp available', exact=False)).to_be_visible()
    expect(page.get_by_text('Last checked: Not scanned', exact=False)).to_have_count(0)
    report = json.loads(_download_text(page, 'Export JSON'))
    assert report['summary']['declarations'] == 0
    assert report['summary']['manifests'] == len(seeded_coverage['manifests'])
    assert report['manifests'] == seeded_coverage['manifests']
    md = _download_text(page, 'Export MD')
    assert 'Synthetic read failure' in md
    assert 'Newest declaration check: No declaration check timestamp available' in md
    assert 'Newest scan: Not scanned' not in md


def test_clean_banner_requires_both_checks(page, seeded_coverage):
    import sqlite3
    with sqlite3.connect(seeded_coverage['db_path']) as db:
        db.execute("UPDATE dependencies SET severity='ok',outdated_state='checked',vuln_state='unchecked' WHERE repo_id=?", (seeded_coverage['repo_id'],))
        db.execute("UPDATE working_state SET dep_check_error=0,missing_dep_tools='[]',dep_manifests='[]' WHERE repo_id=?", (seeded_coverage['repo_id'],))
    _open_coverage(page, seeded_coverage)
    expect(page.get_by_text('No issues found — all dependencies are up to date.', exact=True)).to_have_count(0)
    expect(page.get_by_test_id('dep-coverage')).to_contain_text('Incomplete coverage')
    with sqlite3.connect(seeded_coverage['db_path']) as db:
        db.execute("UPDATE dependencies SET vuln_state='checked' WHERE repo_id=?", (seeded_coverage['repo_id'],))
    page.reload(wait_until='domcontentloaded')
    expect(page.get_by_text('No issues found — all dependencies are up to date.', exact=True)).to_be_visible()


# ═════════════════════════════════════════════════════════════════════════════
# 1. Page Load & Offline Assets
# ═════════════════════════════════════════════════════════════════════════════

def test_page_loads_without_js_errors(server, page):
    """Page loads without uncaught exceptions or console errors."""
    _open_app(page, server)


def test_page_resources_load(server, page):
    """The page loads without failed resource requests."""
    failed_requests = []
    page.on("requestfailed", lambda req: failed_requests.append(
        f"{req.method} {req.url}: {req.failure}"
    ))

    _open_app(page, server)

    assert failed_requests == [], f"Resources failed to load: {failed_requests}"


def test_app_mounts(server, page):
    """The app mounts successfully — the root div has content."""
    _open_app(page, server)

    root = page.locator("#root")
    assert root.inner_html() != "", "App did not mount — #root is empty"


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


def test_directory_browser_shows_path_input(server_context, page):
    """Directory browser modal has a path input field."""
    page.goto(server_context['url'])
    page.wait_for_load_state("networkidle")

    page.locator("header >> text=Scan Dir").click()
    page.wait_for_timeout(500)

    path_input = page.locator("input[placeholder='/path/to/directory']")
    assert path_input.is_visible(), "Path input not visible in directory browser"
    expect(path_input).to_have_value(str(server_context['home'].resolve()))


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
    parent_link = page.get_by_text("← ..", exact=True)
    expect(parent_link).to_be_visible()
    parent_link.click()
    expect(page.get_by_text("deep_child", exact=True)).to_be_visible()


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


@pytest.mark.allows_http_error(
    400, 1, r"/api/browse\?path=%2Fnonexistent%2Fpath%2Fthat%2Fdoes%2Fnot%2Fexist$"
)
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


def test_keyboard_card_enter_opens_detail_and_escape_returns(server, page, tmp_path):
    """Keyboard users can see focus, open a card, and return to the fleet."""
    _create_git_repo(tmp_path, "keyboard_repo")
    page.goto(server)
    assert page.evaluate("""async path => (await fetch('/api/repos', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path})
    })).ok""", str(tmp_path))
    page.reload()
    card = page.locator('.project-card[aria-label="View keyboard_repo details"]')
    expect(card).to_be_visible()
    expect(card).to_have_attribute("role", "button")
    expect(card).to_have_accessible_name(re.compile("keyboard_repo"))
    for _ in range(30):
        page.keyboard.press("Tab")
        if card.evaluate("element => element === document.activeElement"):
            break
    else:
        pytest.fail("Project card was not reachable by Tab")
    assert card.evaluate("element => element.matches(':focus-visible')")
    assert card.evaluate("element => getComputedStyle(element).outlineStyle") != "none"
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"#/repo/"))
    expect(page.get_by_role("button", name="Back to fleet")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page).to_have_url(re.compile(r"#/fleet$"))
    expect(card).to_be_visible()
    for _ in range(30):
        page.keyboard.press("Tab")
        if card.evaluate("element => element === document.activeElement"):
            break
    else:
        pytest.fail("Project card was not reachable by Tab after returning")
    page.keyboard.press("Space")
    expect(page).to_have_url(re.compile(r"#/repo/"))


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
    expect(card).to_be_visible()
    card.click()
    expect(page).to_have_url(re.compile(r"#/repo/"))


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
    """The tool status banner is visible below the nav and can be dismissed."""
    page.route('**/api/status', lambda route: route.fulfill(json={"tools": {"synthetic": False}, "version": "synthetic"}))
    page.goto(server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    banner_dismiss = page.get_by_role("button", name="Dismiss", exact=True)
    expect(banner_dismiss).to_be_visible()
    banner_text = banner_dismiss.locator("..").locator("div").first
    expect(banner_text).to_be_visible()
    bbox = banner_text.bounding_box()
    assert bbox is not None, "Banner text has no bounding box"
    assert bbox["y"] >= 90, (
        f"Banner text is at y={bbox['y']}, should be >= 90 (below fixed header+nav)"
    )
    banner_dismiss.click()
    expect(banner_dismiss).not_to_be_visible()


def test_tool_status_banner_stays_dismissed_on_nav(server, page):
    """After dismissing the banner, it stays dismissed when switching tabs."""
    page.route('**/api/status', lambda route: route.fulfill(json={"tools": {"synthetic": False}, "version": "synthetic"}))
    page.goto(server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    banner_dismiss = page.get_by_role("button", name="Dismiss", exact=True)
    expect(banner_dismiss).to_be_visible()
    banner_dismiss.click()
    expect(banner_dismiss).not_to_be_visible()
    page.locator("nav >> text=Analytics").click()
    page.locator("nav >> text=Fleet Overview").click()
    expect(banner_dismiss).not_to_be_visible()


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


def test_repo_sparkline_renders_responsively(server, page):
    """The fleet sparkline draws a real area path within its card."""
    page.route(
        "**/api/fleet",
        lambda route: route.fulfill(json={
            "repos": [{
                "id": "synthetic-repo",
                "name": "Synthetic Repo",
                "path": "/tmp/synthetic-repo",
                "path_exists": True,
                "current_branch": "main",
                "last_commit_date": date.today().isoformat(),
                "sparkline": [0, 2, 1, 4, 3, 5, 2, 6, 4, 7, 3, 8, 5],
            }],
            "kpis": {"total_repos": 1},
        }),
    )

    page.goto(server)
    card = page.locator(".project-card")
    card.wait_for()
    card.hover()

    chart = card.locator(".svgc-wrapper")
    area = card.locator("path.svgc-area")
    chart.wait_for(state="visible")
    chart_box = chart.bounding_box()
    card_box = card.bounding_box()
    assert chart_box and chart_box["width"] > 0 and chart_box["height"] > 0
    assert card_box and chart_box["width"] <= card_box["width"] + 1
    assert area.get_attribute("d"), "Sparkline area path was not drawn"


def test_project_filter_updates_on_each_keystroke(server, page):
    repos = [{'id': name, 'name': name, 'path': '/tmp/' + name,
              'path_exists': True, 'sparkline': [0, 1]} for name in ('Alpha', 'Beta')]
    page.route('**/api/fleet', lambda route: route.fulfill(json={'repos': repos, 'kpis': {}}))
    _open_app(page, server)
    field = page.get_by_placeholder('Filter projects...')
    field.press_sequentially('Al')
    expect(page.locator('.project-card')).to_have_count(1)
    expect(page.locator('.project-card')).to_contain_text('Alpha')
    field.press('Backspace')
    expect(page.locator('.project-card')).to_have_count(2)


def test_card_sparkline_appears_on_hover_and_keyboard_focus(server, page):
    page.route('**/api/fleet', lambda route: route.fulfill(json={'repos': [{
        'id': 'synthetic', 'name': 'Synthetic', 'path': '/tmp/synthetic',
        'path_exists': True, 'sparkline': [0, 3, 1]}], 'kpis': {}}))
    _open_app(page, server)
    card = page.locator('.project-card')
    overlay = card.locator('.svgc-responsive').locator('..')
    card.hover()
    page.wait_for_function('(el) => getComputedStyle(el).transform === "matrix(1, 0, 0, 1, 0, 0)"', arg=overlay.element_handle())
    page.mouse.move(0, 0)
    page.wait_for_function('(el) => getComputedStyle(el).transform === "matrix(1, 0, 0, 1, 0, 32)"', arg=overlay.element_handle())
    card.focus()
    page.wait_for_function('(el) => getComputedStyle(el).transform === "matrix(1, 0, 0, 1, 0, 0)"', arg=overlay.element_handle())


def test_activity_chart_renders_with_no_history_and_one_day(server, page):
    today = date.today().isoformat()
    history_rows = []
    page.route('**/api/repos/synthetic', lambda route: route.fulfill(json={
        'id': 'synthetic', 'name': 'Synthetic', 'path': '/tmp/synthetic',
        'path_exists': True, 'working_state': {}}))
    page.route('**/api/repos/synthetic/history*', lambda route: route.fulfill(json={'data': history_rows}))
    _open_app(page, server + '#/repo/synthetic')
    page.get_by_role('button', name='All', exact=True).click()
    expect(page.locator('.svgc-wrapper')).to_be_visible()
    _assert_charts_finite(page)
    history_rows.append({'date': today, 'commits': 1, 'insertions': 3, 'deletions': 1})
    assert page.evaluate("async () => (await fetch('/api/repos/synthetic/history?days=90')).status") == 200
    page.reload()
    page.get_by_role('button', name='All', exact=True).click()
    paths = page.locator('.svgc-wrapper path')
    expect(paths.first).to_be_visible()
    _assert_charts_finite(page)


def test_hiding_every_allocation_series_leaves_a_valid_chart(server, page):
    page.route('**/api/analytics/allocation*', lambda route: route.fulfill(json={'series': [
        {'repo_id': 'synthetic', 'name': 'Synthetic', 'data': [{'date': date.today().isoformat(), 'commits': 2}]}]}))
    _open_app(page, server + '#/analytics')
    page.get_by_role('button', name='Synthetic', exact=True).click()
    paths = page.locator('.svgc-wrapper path.svgc-area')
    expect(paths.first).to_have_attribute('fill-opacity', '0')
    box = page.locator('.svgc-wrapper').bounding_box()
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    expect(page.locator('.svgc-tooltip')).to_contain_text('Synthetic')
    _assert_charts_finite(page)


def test_constrained_chart_tooltip_scrolls_and_keeps_focus(server, page):
    _open_app(page, server)
    page.evaluate("""() => {
      const host = document.createElement('div');
      host.id = 'synthetic-tooltip-chart';
      Object.assign(host.style, {position:'fixed', right:'12px', bottom:'12px', width:'220px', zIndex:'1000'});
      document.body.appendChild(host);
      const h = preact.h;
      preact.render(h(svgCharts.CartesianChart, {
        data:[{date:'synthetic-latest', value:2}], xKey:'date', height:80,
        series:[{key:'value', color:'#4c8dff'}],
        tooltip:({label, payload}) => h('div', {style:{background:'#fff', color:'#000'}},
          h('div', null, label + ': ' + payload[0].value),
          Array.from({length:100}, (_, i) => h('div', null, 'Synthetic row ' + i)))
      }), host);
    }""")
    chart = page.locator('#synthetic-tooltip-chart .svgc-wrapper')
    box = chart.bounding_box()
    page.mouse.move(box['x'] + box['width'] - 12, box['y'] + 30)
    tooltip = chart.get_by_role('region', name='Chart tooltip')
    expect(tooltip).to_be_visible()
    assert tooltip.evaluate('el => el.scrollHeight > el.clientHeight')
    assert 'synthetic-latest: 2' in tooltip.inner_text()
    tooltip.focus()
    page.mouse.move(0, 0)
    expect(tooltip).to_be_focused()
    page.keyboard.press('ArrowDown')
    page.wait_for_function("document.querySelector('#synthetic-tooltip-chart .svgc-tooltip')?.scrollTop > 0")
    page.wait_for_timeout(500)
    before = tooltip.evaluate('el => el.scrollTop')
    tooltip.hover()
    page.mouse.wheel(0, 400)
    page.wait_for_function("before => document.querySelector('#synthetic-tooltip-chart .svgc-tooltip')?.scrollTop > before", arg=before)
    page.mouse.wheel(0, 2000)
    page.wait_for_function("""() => { const el = document.querySelector('#synthetic-tooltip-chart .svgc-tooltip');
        return el && el.scrollTop + el.clientHeight >= el.scrollHeight - 1; }""", timeout=3000)
    assert 'Synthetic row 99' in tooltip.inner_text()
    last = tooltip.get_by_text('Synthetic row 99', exact=True).bounding_box()
    bounds = tooltip.bounding_box()
    assert last['y'] >= bounds['y'] and last['y'] + last['height'] <= bounds['y'] + bounds['height']
    assert 'synthetic-latest: 2' in tooltip.inner_text()
    page.locator('header button').first.focus()
    expect(tooltip).to_have_count(0)


def test_activity_chart_renders_signed_areas_axes_and_custom_tooltip(server, page):
    """Activity chart plots both signs and exposes its custom hover details."""
    today = date.today()
    history = [
        {"date": (today - timedelta(days=2)).isoformat(), "commits": 2,
         "insertions": 12, "deletions": 3, "files_changed": 2},
        {"date": (today - timedelta(days=1)).isoformat(), "commits": 1,
         "insertions": 5, "deletions": 9, "files_changed": 1},
        {"date": today.isoformat(), "commits": 3,
         "insertions": 10, "deletions": 4, "files_changed": 3},
    ]
    page.route(
        "**/api/repos/synthetic-repo",
        lambda route: route.fulfill(json={
            "id": "synthetic-repo", "name": "Synthetic Repo",
            "path": "/tmp/synthetic-repo", "path_exists": True,
            "runtime": "python", "default_branch": "main",
            "working_state": {"current_branch": "main"},
        }),
    )
    page.route(
        "**/api/repos/synthetic-repo/history*",
        lambda route: route.fulfill(json={
            "repo_id": "synthetic-repo", "days": 90, "data": history,
        }),
    )

    page.goto(server + "#/repo/synthetic-repo")
    chart = page.locator(".detail-content .svgc-wrapper")
    chart.wait_for(state="visible")
    assert chart.locator('.svgc-grid-horizontal').count() > 0
    assert chart.locator('.svgc-grid-vertical').count() == 0
    axis_line = chart.locator('.svgc-x-axis-line')
    assert axis_line.count() == 1
    assert float(axis_line.get_attribute('x2')) > float(axis_line.get_attribute('x1'))
    assert axis_line.evaluate("el => getComputedStyle(el).stroke") != 'none'

    container_box = page.locator(".detail-content .svgc-responsive").bounding_box()
    chart_box = chart.bounding_box()
    assert container_box and chart_box
    assert abs(container_box["width"] - chart_box["width"]) <= 2

    area_paths = chart.locator("path.svgc-area")
    assert area_paths.count() >= 2
    assert all(area_paths.nth(i).get_attribute("d") for i in range(2))
    axis_labels = [label for label in chart.locator("svg text").all_text_contents() if label]
    assert any(re.fullmatch(r"\d{4}-\d{2}-\d{2}", label) for label in axis_labels)
    assert any(re.fullmatch(r"-?\d+", label) for label in axis_labels)
    tick = chart.locator('svg text').first
    assert tick.evaluate("el => getComputedStyle(el).fontFamily").startswith('"JetBrains Mono"')
    assert tick.evaluate("el => getComputedStyle(el).fontSize") == '11px'
    assert tick.bounding_box()['x'] >= chart.bounding_box()['x']

    zero_line = chart.locator(".svgc-reference-line").bounding_box()
    positive = area_paths.nth(0).bounding_box()
    negative = area_paths.nth(1).bounding_box()
    assert zero_line and positive and negative
    assert positive["y"] < zero_line["y"]
    assert negative["y"] + negative["height"] > zero_line["y"]

    chart.scroll_into_view_if_needed()
    chart_box = chart.bounding_box()
    page.mouse.move(chart_box["x"] + chart_box["width"] - 8,
                    chart_box["y"] + chart_box["height"] - 34)
    tooltip = page.locator(".svgc-tooltip")
    _assert_tooltip_readable_in_viewport(page, tooltip)
    tooltip_text = tooltip.inner_text()
    assert today.isoformat() in tooltip_text
    assert "+10 insertions" in tooltip_text
    assert "-4 deletions" in tooltip_text
    assert "net +6" in tooltip_text
    assert "3 commits" in tooltip_text


def test_activity_gap_fill_uses_browser_local_calendar_day(server, browser):
    """Late UTC hours must not add a synthetic next-local-day data point."""
    context = browser.new_context(timezone_id="America/New_York")
    page = context.new_page()
    try:
        page.add_init_script("""
            const NativeDate = Date;
            const fixedNow = NativeDate.parse('2026-09-17T02:30:00Z');
            class FixedDate extends NativeDate {
                constructor(...args) {
                    super(...(args.length ? args : [fixedNow]));
                }
                static now() { return fixedNow; }
            }
            window.Date = FixedDate;
        """)
        page.route(
            "**/api/repos/synthetic-boundary",
            lambda route: route.fulfill(json={
                "id": "synthetic-boundary",
                "name": "Synthetic Boundary Repo",
                "path": "/tmp/synthetic-boundary",
                "path_exists": True,
                "runtime": "python",
                "default_branch": "main",
                "working_state": {"current_branch": "main"},
            }),
        )
        page.route(
            "**/api/repos/synthetic-boundary/history*",
            lambda route: route.fulfill(json={
                "repo_id": "synthetic-boundary",
                "days": 90,
                "data": [{
                    "date": "2026-09-16",
                    "commits": 3,
                    "insertions": 10,
                    "deletions": 4,
                    "files_changed": 3,
                }],
            }),
        )

        with guard_browser_errors(page):
            _open_app(page, server + "#/repo/synthetic-boundary")
            chart = page.locator(".detail-content .svgc-wrapper")
            chart.wait_for(state="visible")
            chart_box = chart.bounding_box()
            assert chart_box
            page.mouse.move(
                chart_box["x"] + chart_box["width"] - 8,
                chart_box["y"] + chart_box["height"] / 2,
            )
            tooltip = page.locator(".svgc-tooltip")
            tooltip.wait_for(state="visible")
            assert "2026-09-16" in tooltip.inner_text()
            assert "2026-09-17" not in tooltip.inner_text()
    finally:
        context.close()


def test_time_allocation_chart_renders_stack_axes_and_tooltip(server, page):
    """Time allocation draws stacked areas and labels its hover payload."""
    today = date.today()
    active_week = (today - timedelta(days=today.weekday())).isoformat()
    dates = [(today - timedelta(days=offset)).isoformat() for offset in (21, 14, 7, 0)]
    page.route(
        "**/api/analytics/allocation*",
        lambda route: route.fulfill(json={"series": [
            {"repo_id": "alpha", "name": "Synthetic Alpha", "data": [
                {"date": day, "commits": commits}
                for day, commits in zip(dates, (2, 5, 3, 7))
            ]},
            {"repo_id": "beta", "name": "Synthetic Beta", "data": [
                {"date": day, "commits": commits}
                for day, commits in zip(dates, (1, 2, 4, 4))
            ]},
        ]}),
    )

    page.goto(server + "#/analytics")
    heading = page.get_by_role("heading", name="Time Allocation")
    chart = heading.locator("xpath=../following-sibling::*[1]").locator(".svgc-wrapper")
    chart.wait_for(state="visible")
    assert chart.locator('.svgc-grid-horizontal').count() > 0
    assert chart.locator('.svgc-grid-vertical').count() > 0
    assert chart.locator('.svgc-x-axis-line').count() == 0
    assert chart.locator("path.svgc-area").count() == 2
    curves = chart.locator("path.svgc-curve")
    assert curves.count() == 2
    curve_endpoints = curves.evaluate_all("""
        paths => paths.map(path => {
            const length = path.getTotalLength();
            const point = path.getPointAtLength(length);
            return { x: point.x, y: point.y };
        })
    """)
    assert curve_endpoints[0]["x"] == pytest.approx(curve_endpoints[1]["x"], abs=1)
    assert curve_endpoints[1]["y"] < curve_endpoints[0]["y"], (
        "Synthetic Beta's final value (4) must render above Synthetic Alpha's "
        "final value (7), proving the second area uses the cumulative stacked value (11)"
    )
    axis_labels = [label for label in chart.locator("svg text").all_text_contents() if label]
    assert any(re.fullmatch(r"\d{4}-\d{2}-\d{2}", label) for label in axis_labels)
    assert any(re.fullmatch(r"\d+", label) for label in axis_labels)
    assert max(int(label) for label in axis_labels if re.fullmatch(r"\d+", label)) == 12
    tick = chart.locator('svg text').first
    assert tick.evaluate("el => getComputedStyle(el).fontFamily").startswith('"JetBrains Mono"')
    assert tick.evaluate("el => getComputedStyle(el).fontSize") == '11px'
    assert tick.bounding_box()['x'] >= chart.bounding_box()['x']

    box = chart.bounding_box()
    assert box and box["width"] > 200 and box["height"] == pytest.approx(260, abs=2)
    chart.scroll_into_view_if_needed()
    box = chart.bounding_box()
    page.mouse.move(box["x"] + box["width"] - 12, box["y"] + box["height"] - 34)
    tooltip = page.locator(".svgc-tooltip")
    _assert_tooltip_readable_in_viewport(page, tooltip)
    tooltip_text = tooltip.inner_text()
    assert active_week in tooltip_text
    assert re.search(r"Synthetic Alpha : 7(?:\D|$)", tooltip_text)
    assert re.search(r"Synthetic Beta : 4(?:\D|$)", tooltip_text)
    assert tooltip_text.index("Synthetic Alpha") < tooltip_text.index("Synthetic Beta")


ALLOCATION_NAMES = ("Synthetic Delta", "Synthetic Alpha", "Synthetic Charlie", "Synthetic Bravo")


def _mock_allocation(page, weeks=4, names=ALLOCATION_NAMES):
    today = date.today()
    dates = [(today - timedelta(days=(weeks - i - 1) * 7)).isoformat() for i in range(weeks)]
    series = [{"repo_id": name, "name": name, "data": [
        {"date": day, "commits": index + i + 1} for i, day in enumerate(dates)]}
        for index, name in enumerate(names)]
    page.route("**/api/analytics/allocation*", lambda route: route.fulfill(json={"series": series}))


def _allocation_chart(page):
    heading = page.get_by_role("heading", name="Time Allocation")
    return heading.locator("xpath=../following-sibling::*[1]")


def _mock_activity(page, history):
    page.route("**/api/repos/synthetic-repo", lambda route: route.fulfill(json={
        "id": "synthetic-repo", "name": "Synthetic Repo", "path": "/tmp/synthetic-repo",
        "path_exists": True, "runtime": "python", "default_branch": "main",
        "working_state": {"current_branch": "main"}}))
    page.route("**/api/repos/synthetic-repo/history*", lambda route: route.fulfill(json={"data": history}))


def _activity_history(rows):
    today = date.today()
    return [{"date": (today - timedelta(days=len(rows) - i - 1)).isoformat(), "commits": 1,
             "insertions": ins, "deletions": dels, "files_changed": 1}
            for i, (ins, dels) in enumerate(rows)]


def test_allocation_tooltip_keeps_old_order_hidden_rows_and_separator(server, page):
    _mock_allocation(page)
    _open_app(page, server + "#/analytics")
    chart = _allocation_chart(page)
    wrapper = chart.locator(".svgc-wrapper")
    wrapper.wait_for()
    page.get_by_role("button", name="Synthetic Charlie", exact=True).click()
    box = wrapper.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    tooltip = chart.locator(".svgc-tooltip")
    expect(tooltip).to_be_visible()
    rows = [line for line in tooltip.inner_text().splitlines() if line.startswith("Synthetic")]
    assert [row.split(" : ")[0] for row in rows] == sorted(ALLOCATION_NAMES)
    expect(chart.locator(".svgc-active-dot")).to_have_count(4)


def test_allocation_outlines_and_nice_axis_match_the_old_chart(server, page):
    _mock_allocation(page, weeks=4, names=("Synthetic Alpha",))
    _open_app(page, server + "#/analytics")
    wrapper = _allocation_chart(page).locator(".svgc-wrapper")
    wrapper.wait_for()
    expect(wrapper.locator("path.svgc-curve")).to_have_attribute("stroke-width", "1")
    labels = [text for text in wrapper.locator("svg text").all_text_contents() if re.fullmatch(r"\d+", text)]
    assert labels == ["0", "1", "2", "3", "4"]


def test_allocation_labels_never_collide_at_narrow_width(server, page):
    page.set_viewport_size({"width": 390, "height": 800})
    _mock_allocation(page, weeks=26, names=("Synthetic Alpha", "Synthetic Beta"))
    _open_app(page, server + "#/analytics")
    wrapper = _allocation_chart(page).locator(".svgc-wrapper")
    wrapper.wait_for()
    labels = wrapper.locator("svg text").evaluate_all(r"""nodes => nodes
        .filter(n => /^\d{4}-\d\d-\d\d$/.test(n.textContent)).map(n => n.getBoundingClientRect().toJSON())""")
    assert len(labels) >= 2
    assert all(first["right"] <= second["left"] for first, second in zip(labels, labels[1:]))
    box = wrapper.bounding_box()
    assert labels[-1]["right"] <= box["x"] + box["width"] + .5


@pytest.mark.parametrize("view", ["activity", "allocation"])
def test_chart_keyboard_reading_and_hover_marks(server, page, view):
    if view == "activity":
        _mock_activity(page, _activity_history([(5, 2), (9, 1), (3, 4)]))
        _open_app(page, server + "#/repo/synthetic-repo")
        host = page.locator(".detail-content")
        dots = 3
    else:
        _mock_allocation(page, names=("Synthetic Alpha", "Synthetic Beta"))
        _open_app(page, server + "#/analytics")
        host = _allocation_chart(page)
        dots = 2
    surface = host.locator('svg[role="application"]')
    surface.wait_for()
    surface.focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    expect(surface).to_be_focused()
    tooltip = host.locator(".svgc-tooltip")
    expect(tooltip).to_be_visible()
    first = tooltip.inner_text()
    expect(host.locator(".svgc-active-dot")).to_have_count(dots)
    page.keyboard.press("ArrowRight")
    expect(tooltip).not_to_have_text(first)
    page.keyboard.press("Tab")
    expect(tooltip).to_have_count(0)
    surface.scroll_into_view_if_needed()
    box = surface.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(host.locator(".svgc-cursor")).to_have_count(1)
    expect(host.locator(".svgc-active-dot")).to_have_count(dots)
    page.mouse.move(box["x"] + 5, box["y"] + box["height"] / 2)
    expect(host.locator(".svgc-cursor")).to_have_count(0)
    expect(tooltip).to_have_count(0)


def test_activity_axis_uses_the_old_symmetric_ticks(server, page):
    _mock_activity(page, _activity_history([(130, 100), (60, 20), (10, 5)]))
    _open_app(page, server + "#/repo/synthetic-repo")
    wrapper = page.locator(".detail-content .svgc-wrapper")
    wrapper.wait_for()
    labels = [text for text in wrapper.locator("svg text").all_text_contents() if re.fullmatch(r"\d+", text)]
    assert labels == ["130", "65", "0", "65", "130"]


def test_all_zero_activity_uses_the_old_axis(server, page):
    _mock_activity(page, _activity_history([(0, 0), (0, 0), (0, 0)]))
    _open_app(page, server + "#/repo/synthetic-repo")
    wrapper = page.locator(".detail-content .svgc-wrapper")
    wrapper.wait_for()
    labels = [text for text in wrapper.locator("svg text").all_text_contents() if re.fullmatch(r"\d+", text)]
    assert labels == ["0", "1", "2", "3", "4"]
    _assert_charts_finite(page)


@pytest.mark.parametrize("sparkline,start", [([0, 0, 0], "M0,28"), ([5], "M"), ([], None)], ids=["zeros", "single", "empty"])
def test_sparkline_fill_and_degenerate_data(server, page, sparkline, start):
    page.route("**/api/fleet", lambda route: route.fulfill(json={"repos": [{
        "id": "synthetic", "name": "Synthetic", "path": "/tmp/synthetic",
        "path_exists": True, "sparkline": sparkline}], "kpis": {}}))
    _open_app(page, server)
    card = page.locator(".project-card")
    card.hover()
    if start is None:
        expect(card.locator(".svgc-wrapper")).to_have_count(0)
        return
    curve = card.locator("path.svgc-curve")
    expect(curve).to_have_attribute("d", re.compile("^" + start))
    expect(card.locator("path.svgc-area")).to_have_attribute("fill-opacity", "0.6")
    assert card.locator('svg[role="application"]').count() == 0
    _assert_charts_finite(page)


def test_chart_views_have_no_unstyled_classes(server, page):
    from tools.testkit import assert_classes_styled
    _mock_allocation(page, names=("Synthetic Alpha", "Synthetic Beta"))
    _mock_activity(page, _activity_history([(5, 2), (9, 1)]))
    _open_app(page, server + "#/analytics")
    _allocation_chart(page).locator(".svgc-wrapper").wait_for()
    assert_classes_styled(page, ignore=CHART_HOOK_CLASSES)
    _open_app(page, server + "#/repo/synthetic-repo")
    page.locator(".detail-content .svgc-wrapper").wait_for()
    assert_classes_styled(page, ignore=CHART_HOOK_CLASSES)


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
    page.goto(server + "#/nonexistent/route")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    # Should fall back to fleet view, not crash
    root = page.locator("#root")
    assert root.inner_html() != "", "App crashed on invalid route"


@pytest.mark.allows_http_error(
    404, 2, r"/api/repos/does_not_exist_12345(?:$|/history\?days=90$)"
)
def test_nonexistent_repo_detail_does_not_crash(server, page):
    """Navigating to a nonexistent repo ID doesn't crash."""
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
    expect(card).to_be_visible()
    card.hover()
    remove_btn = card.locator("button[aria-label*='Remove']")
    expect(remove_btn).to_be_visible()


def test_delete_repo_from_card(server, page, tmp_path):
    """Clicking the delete button on a card removes the repo from the fleet."""
    _create_git_repo(tmp_path, "aaa_delete_decoy")
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

    # Sort by name so a known decoy precedes the target regardless of dates.
    page.get_by_role("button", name="Last active").click()
    page.get_by_text("Name A-Z", exact=True).click()
    expect(page.locator(".project-card").first).to_contain_text("aaa_delete_decoy")

    # Confirm the repo is visible
    body_text = page.locator("body").inner_text()
    assert "del_card_repo" in body_text, "Repo not found before delete"

    # Hover the card and click delete
    card = page.locator('.project-card[aria-label="View del_card_repo details"]')
    expect(card).to_be_visible()
    card.hover()
    page.on("dialog", lambda dialog: dialog.accept())
    remove_btn = card.locator("button[aria-label*='Remove']")
    expect(remove_btn).to_be_visible()
    remove_btn.click()
    expect(page.get_by_text("del_card_repo", exact=True)).not_to_be_visible()


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
    expect(card).to_be_visible()
    remove_btn = card.locator("button.card-delete-btn")
    expect(remove_btn).to_have_count(1)
    expect(remove_btn).to_have_css("opacity", "0")
    card.hover()
    expect(remove_btn).to_have_css("opacity", "1")


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
    expect(card).to_be_visible()
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
    assert branches_data["branches"], "Expected at least one scanned branch"
    for b in branches_data["branches"]:
        name = b["name"]
        assert "%x00" not in name, f"Branch name contains literal %x00: {name}"
        assert "%00" not in name, f"Branch name contains encoded null: {name}"
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
