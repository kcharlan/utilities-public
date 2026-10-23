import pytest
from playwright.sync_api import sync_playwright, expect
from browser_errors import guard_browser_errors
from helpers import SESSION, REQUEST
import json
import copy
import re
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone
from test_opencode import database, CLOCK, SESSION as OPENCODE_SESSION
import sqlite3


def opencode_page(native, mutate=None):
    database(native)
    return source_page(native, mutate)


def test_opencode_source_hash_descendants_actions_and_version(page, native):
    def mutate(payload):
        row = next(r for r in payload["sessions"] if r["provider"] == "opencode")
        child = copy.deepcopy(row)
        child.update(id="synthetic-opencode-child", kind="subagent", parent_id=row["id"], children=[])
        foreign = copy.deepcopy(child)
        foreign.update(id="synthetic-foreign-child", provider="claude")
        row["children"] = [child["id"], foreign["id"]]
        payload["subagents"].update({child["id"]: child, foreign["id"]: foreign})
    payload = opencode_page(native, mutate)
    assert payload["meta"]["version"] == "0.4.1"
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        expect(page.locator('[data-version]')).to_have_text("colophon 0.4.1")
        page.goto(native.page.as_uri() + "#v=session&p=all&a=1&h=0&sort=cost&src=opencode&s=" + OPENCODE_SESSION)
        reader = page.locator("[data-reader]")
        expect(reader).to_have_attribute("data-provider", "opencode")
        expect(reader.locator('[data-subagent-id="synthetic-foreign-child"]')).to_have_count(0)
        expect(reader.get_by_role("link", name="Open in Codex")).to_have_count(0)
        expect(reader.get_by_role("button", name="Copy log path")).to_have_count(0)
        expect(reader.get_by_role("button", name="Copy Continue in CLI")).to_have_count(0)
        page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => window.syntheticCopied = text}, configurable: true})")
        reader.get_by_role("button", name="Copy session ID", exact=True).click()
        assert page.evaluate("window.syntheticCopied") == OPENCODE_SESSION
        page.get_by_role("searchbox").fill("synthetic")
        page.wait_for_timeout(250)
        page.get_by_role("button", name="Claude", exact=True).click()
        assert all(value in page.url for value in ["q=synthetic", "a=1", "h=0", "sort=cost", "p=all"]) and "&s=" not in page.url
        for provider, visible in [("codex", False), ("claude", False), ("opencode", True)]:
            page.goto(native.page.as_uri() + "#v=session&p=all&src=" + provider + "&s=synthetic-opencode-child")
            expect(page.locator("[data-reader]")).to_have_count(int(visible))
        assert requests == []


def test_opencode_provider_shares_colors_ties_and_phone(page, native):
    def mutate(payload):
        for row in payload["sessions"]:
            row["workspace"] = "synthetic-shared-workspace"
            row["buckets"] = [[CLOCK // 900000, "synthetic-shared-model", "standard", 10, 0, 0, 0, 0, 1, row["provider"]]]
            # A second day distinguishes a Claude/OpenCode tie from a three-way tie.
            row["buckets"].append([(CLOCK + 86400000) // 900000, "synthetic-shared-model", "standard", 0 if row['provider'] == 'codex' else 10, 0, 0, 0, 0, 0, row['provider']])
        payload["meta"]["sources"]["claude"]["token_data_from_ms"] = CLOCK + 100000
    opencode_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.goto(native.page.as_uri() + "#p=all")
        for provider in ["codex", "claude", "opencode"]:
            share = page.locator('[data-kpi="tokens"] [data-provider="' + provider + '"]')
            value = 10 if provider == "codex" else 20
            expect(share).to_have_attribute("data-share", str(value))
            assert float(share.evaluate("e => parseFloat(e.style.width)")) == pytest.approx(value * 2, abs=.001)
            expect(page.locator('.bar-fill[data-provider="' + provider + '"]')).to_have_count(1)
        page.get_by_role("button", name="Calendar tokens", exact=True).click()
        expect(page.locator('[data-day="2026-01-02"]')).to_have_attribute("data-provider", "codex")
        expect(page.locator('[data-day="2026-01-03"]')).to_have_attribute("data-provider", "claude")
        page.evaluate("window.__colophonTest.state.writeState({...window.__colophonTest.state.readState(), src:'opencode'})")
        expect(page.locator('[data-day="2026-01-02"]')).to_have_attribute("data-provider", "opencode")
        assert page.locator('.brand').evaluate("e => getComputedStyle(e).color") == "rgb(215, 166, 255)"
        assert page.locator('[data-day="2026-01-02"]').evaluate("e => getComputedStyle(e).backgroundColor") in ["rgb(46, 33, 66)", "rgb(83, 58, 122)", "rgb(143, 104, 198)", "rgb(215, 166, 255)"]
        expect(page.locator('[data-token-boundary]')).to_have_count(0)
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=native.root / "opencode-phone.png", full_page=True)
        page.goto(native.page.as_uri() + "#p=custom&from=2025-01-01&to=2025-01-02&src=opencode")
        for share in page.locator('.provider-shares span').all():
            assert share.evaluate("e => e.style.width") == "0%"
        assert requests == []


@pytest.mark.parametrize('missing_cost', [False, True])
def test_opencode_native_residual_outside_and_mixed_rate_tooltips(page, native, missing_cost):
    path = database(native, tokens=30, cost=.5)
    with sqlite3.connect(path) as db:
        value = json.loads(db.execute("SELECT data FROM session_message WHERE type='assistant'").fetchone()[0])
        value.update(tokens={'input': 10, 'output': 0}, cost=.25)
        if missing_cost:
            del value['cost']
        db.execute("UPDATE session_message SET data=? WHERE type='assistant'", (json.dumps(value),))
        db.execute("INSERT INTO migration VALUES ('99999999999999_synthetic_future',?)", (CLOCK,))
    def mutate(payload):
        shared = next(b[1] for r in payload['sessions'] if r['provider'] == 'opencode' for b in r['buckets'] if b[1] == 'synthetic-provider/synthetic-model')
        for row in payload['sessions']:
            if row['provider'] == 'opencode':
                continue
            row['buckets'] = [[CLOCK // 900000, shared, 'standard', 10, 0, 0, 0, 0, None, row['provider']]]
            row['own_usage'].update(cost_usd=None, unpriced_tokens=10, priced_by=[])
        claude = next(r for r in payload['sessions'] if r['provider'] == 'claude')
        claude['own_usage']['priced_by'] = [['claude:synthetic-rate', 0, 'fast']]
        payload['models']['claude:synthetic-rate'] = {'periods': [{'effective_from_ms': None, 'source': 'curated'}]}
    source_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.locator('[data-session-id="' + OPENCODE_SESSION + '"]').click()
        reader = page.locator('[data-reader]')
        for locator in [reader.locator('[data-reader-stat="cost"]'), reader.locator('[data-turn-cost]').first, reader.locator('[data-outside-usage]')]:
            title = locator.get_attribute('title')
            assert 'OpenCode catalog estimate' in title and 'rate period unknown' not in title
        if missing_cost:
            assert 'unpriced' in reader.locator('[data-turn-cost]').first.get_attribute('title')
        page.locator('.brand').click()
        title = page.locator('[data-model]').filter(has_text='synthetic-provider/synthetic-model').get_attribute('title')
        assert all(text in title for text in ['OpenCode catalog estimate', 'rate period unknown', 'unpriced', 'claude:synthetic-rate', 'fast']), title
        assert requests == []


def test_opencode_native_cross_session_overflow_preserves_individual_costs(page, native):
    database(native, cost=1.2e308)
    database(native, 'opencode-other.db', session='synthetic-other', cost=1.2e308)
    assert native.build().returncode == 0
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.goto(native.page.as_uri() + '#p=all&src=opencode')
        expect(page.locator('[data-kpi="cost"] .kpi-value')).to_have_text('costs unavailable')
        expect(page.locator('[data-cost-aggregate]')).to_contain_text('OpenCode total')
        for row in native.payload()['sessions']:
            assert row['own_usage']['cost_usd'] == 1.2e308
        assert 'Infinity' not in page.locator('body').inner_text()
        assert requests == []


def test_opencode_zero_provider_shares_and_reader_overflow(page, native):
    def mutate(payload):
        for row in payload['sessions']:
            row['workspace'] = 'synthetic-zero-workspace'
            for turn in row['turns']:
                turn.update(end_ms=turn['start_ms'], duration_ms=0)
            row['buckets'] = [[CLOCK // 900000, 'synthetic-model', 'standard', 0, 0, 0, 0, 0, 0, row['provider']]]
        row = next(r for r in payload['sessions'] if r['provider'] == 'opencode')
        row['own_usage']['cost_usd'] = 1.2e308
        child = copy.deepcopy(row)
        child.update(id='synthetic-overflow-child', kind='subagent', children=[])
        row['children'] = [child['id']]
        payload['subagents'][child['id']] = child
    opencode_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.goto(native.page.as_uri() + '#p=all')
        for selector in ['[data-kpi="tokens"] .provider-shares span', '.bar-fill']:
            assert page.locator(selector).evaluate_all("nodes => nodes.length === 3 && nodes.every(e => e.style.width === '0%')")
        page.goto(native.page.as_uri() + '#v=session&p=all&src=opencode&s=' + OPENCODE_SESSION)
        expect(page.locator('[data-reader-stat="cost"] .reader-stat-value')).to_have_text('costs unavailable')
        expect(page.locator('[data-cost-aggregate]')).to_contain_text('reader ' + OPENCODE_SESSION)
        assert requests == []


@pytest.mark.parametrize("status", ["disabled", "absent", "unsupported", "unreadable", "ok"])
def test_opencode_source_states_structured_diagnostics_and_preview(page, native, status):
    def mutate(payload):
        payload["meta"]["sources"]["opencode"].update(status=status, databases=[
            {"path": "/synthetic/good.db", "status": "ok", "reason": None, "primary": True, "untested": True, "latest_migration": "synthetic-future", "accepted_sessions": 1, "accepted_messages": 2},
            {"path": "/synthetic/bad.db", "status": "unreadable", "reason": "Synthetic read failure"},
            {"path": "/synthetic/opencode-next.db", "status": "skipped", "reason": "Synthetic preview skip"}])
        payload["diagnostics"].update(opencode_unknown_message_types={"synthetic-future": 3},
            opencode_requests_without_usage={"synthetic-provider": 2}, opencode_cost_without_tokens=1,
            opencode_untested_schema=[{"path": "/synthetic/good.db", "latest_migration": "synthetic-future"}],
            opencode_rollup_residuals={"synthetic-session": {"session": "synthetic-session", "database": "/synthetic/good.db", "input": 4, "cost": None, "date": CLOCK, "date_basis": "session_start"}})
    opencode_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        footer = page.locator('#colophon-footer')
        expect(footer.locator('[data-diagnostic="opencode_unknown_message_types"] summary')).to_contain_text("3")
        expect(footer.locator('[data-diagnostic="opencode_requests_without_usage"] summary')).to_contain_text("2")
        expect(footer.locator('[data-diagnostic="opencode_rollup_residuals"] summary')).to_contain_text("1")
        footer.locator('[data-diagnostic="opencode_rollup_residuals"]').evaluate("e => e.open = true")
        expect(footer).to_contain_text("date_basis: session_start")
        expect(footer).to_contain_text("display convention")
        footer.locator('[data-opencode-databases]').evaluate("e => e.open = true")
        expect(footer).to_contain_text("/synthetic/opencode-next.db")
        expect(footer).to_contain_text("Synthetic read failure")
        assert "[object Object]" not in footer.text_content()
        page.get_by_role('button', name="OpenCode" + (" · no data" if status != "ok" else ""), exact=True).click()
        if status != "ok":
            expected = {"disabled": "--no-opencode", "absent": "Checked", "unsupported": "unsupported", "unreadable": "unreadable"}[status]
            expect(page.locator('.empty-state')).to_contain_text(expected)
        assert requests == []


@pytest.mark.parametrize("session_archived,project_archived,label", [
    (True, False, "ARCHIVED"), (False, True, "ARCHIVED (PROJECT)"), (True, True, "ARCHIVED")])
def test_opencode_native_database_archive_reader_and_estimates(page, native, session_archived, project_archived, label):
    path = database(native, archived=CLOCK if session_archived else None, project_archived=CLOCK if project_archived else None)
    assert native.build().returncode == 0
    assert native.payload()['sessions'][0]['archive_reason'] == ('session' if session_archived else 'project')
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        row = page.locator('[data-session-id="' + OPENCODE_SESSION + '"]')
        expect(row.locator('.tag')).to_have_text(label)
        page.locator('.brand').click()
        recent = page.locator('.recent-row[data-session-id="' + OPENCODE_SESSION + '"]')
        expect(recent.locator('.session-title')).to_have_text('Synthetic OpenCode kite · ' + label)
        recent.locator('.session-title').click()
        reader = page.locator('[data-reader]')
        expect(reader.locator('.reader-header .tag')).to_have_text(label)
        expect(reader).to_contain_text("Synthetic kite done")
        expect(reader.locator('[data-reader-stat="cost"]')).to_contain_text("$0.25")
        for locator in [reader.locator('[data-reader-stat="cost"]'), reader.locator('[data-turn-cost]').first]:
            title = locator.get_attribute('title')
            assert "OpenCode catalog estimate" in title and "rate period unknown" not in title
        expect(reader.get_by_role("button", name="Copy Continue in CLI")).to_have_count(0)
        expect(reader.get_by_role("button", name="Copy log path")).to_have_count(0)
        expect(reader.get_by_role("link", name="Open in Codex")).to_have_count(0)
        expect(reader.get_by_role("button", name="Copy session ID", exact=True)).to_have_count(1)
        page.set_viewport_size({"width": 375, "height": 812})
        page.wait_for_function("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator('[data-turn-card]').evaluate_all("nodes => nodes.every(e => e.getBoundingClientRect().right <= innerWidth)")
        page.get_by_role('button', name='archived: shown', exact=True).click()
        expect(page.locator('[data-list-row]')).to_have_count(0)
        assert path.is_file() and requests == []


def test_opencode_mixed_model_tooltips_and_finite_aggregate_overflow(page, native):
    def mutate(payload):
        for row in payload['sessions']:
            row['buckets'] = [[CLOCK // 900000, 'synthetic-shared', 'standard', 10, 0, 0, 0, 0, 1.2e308, row['provider']]]
            row['own_usage'].update(cost_usd=1.2e308, priced_by=[])
    opencode_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.goto(native.page.as_uri() + '#p=all')
        expect(page.locator('[data-kpi="cost"] .kpi-value')).to_contain_text('costs unavailable')
        expect(page.locator('[data-cost-aggregate]')).to_contain_text('cost aggregate unavailable')
        model = page.locator('[data-model="synthetic-shared"]')
        assert 'OpenCode catalog estimate' in model.get_attribute('title')
        assert 'rate period unknown' in model.get_attribute('title')
        assert 'Infinity' not in page.locator('body').inner_text()
        assert page.locator('.provider-shares span').evaluate_all("nodes => nodes.every(e => !/NaN|Infinity/.test(e.style.width))")
        page.get_by_role('button', name='OpenCode', exact=True).click()
        assert 'rate period unknown' not in page.locator('[data-model="synthetic-shared"]').get_attribute('title')
        assert 'unavailable' not in page.locator('[data-kpi="cost"] .kpi-value').inner_text()
        assert requests == []

def browser_page(**context_options):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(**context_options)
        page = context.new_page()
        # Native action links remain inert even if a test accidentally clicks one.
        page.add_init_script("document.addEventListener('click', e => { const a=e.target.closest('a'); if(a && !/^(file:|#)/.test(a.getAttribute('href') || '')) { e.preventDefault(); e.stopImmediatePropagation(); } }, true)")
        try:
            yield page
        finally:
            context.close()
            browser.close()

@pytest.fixture
def page():
    yield from browser_page()

@pytest.fixture
def zoned_page():
    """Period boundaries are local calendar days, so these cases pin the browser zone."""
    yield from browser_page(timezone_id="America/New_York")

def open_native(page, native_page):
    requests = []
    def intercept(route):
        if route.request.url.startswith("file://"):
            route.continue_()
        else:
            requests.append(route.request.url)
            route.abort()
    page.route("**/*", intercept)
    page.goto(native_page.as_uri() + "#v=list&p=all")
    return requests

def source_page(native, mutate=None):
    """Change only invented payload facts to exercise additive page contracts."""
    native.session()
    native.claude_session()
    result = native.build()
    assert result.returncode == 0, result.stderr
    payload = native.payload()
    if mutate:
        mutate(payload)
    html = native.page.read_text()
    html = re.sub(r'(<script[^>]*id="colophon-data"[^>]*>).*?(</script>)',
                  lambda match: match[1] + json.dumps(payload).replace("<", "\\u003c") + match[2], html, flags=re.S)
    native.page.write_text(html)
    return payload

def test_source_switch_hash_filters_and_direct_agents(page, native):
    def mutate(payload):
        parent = next(row for row in payload["sessions"] if row["provider"] == "claude")
        agent = copy.deepcopy(parent)
        agent.update(id="synthetic-claude/agent-invented", parent_id=parent["id"], label="Synthetic child", children=[])
        agent.pop("kind", None)
        parent["children"] = [agent["id"]]
        payload["subagents"][agent["id"]] = agent
        # Legacy rows without provider remain Codex.
        next(row for row in payload["sessions"] if row["provider"] == "codex").pop("provider")
    source_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        expect(page.get_by_role("group", name="Source")).to_be_visible()
        expect(page).to_have_url(re.compile(r"src=all"))
        page.get_by_role("button", name="Claude", exact=True).click()
        expect(page.locator("[data-list-row]")).to_have_count(1)
        page.locator('[data-session-id="synthetic-claude"]').click()
        page.get_by_role("searchbox").fill("synthetic")
        page.wait_for_timeout(250)
        page.get_by_role("button", name="Codex", exact=True).click()
        expect(page.locator("[data-reader]")).to_have_count(0)
        assert "q=synthetic" in page.url and "&s=" not in page.url
        page.goto(native.page.as_uri() + "#v=session&p=all&src=codex&s=synthetic-claude%2Fagent-invented")
        expect(page.locator("[data-reader]")).to_have_count(0)
        page.goto(native.page.as_uri() + "#v=session&p=all&src=claude&s=synthetic-claude%2Fagent-invented")
        expect(page.locator('[data-reader="synthetic-claude/agent-invented"]')).to_be_visible()
        assert requests == []

def test_source_no_data_snapshot_footer_and_phone(page, native):
    def mutate(payload):
        payload["meta"]["sources"]["codex"].update(status="absent", logs=3)
        payload["meta"]["sources"]["claude"].update(logs=7, token_data_from_ms=1767355200000)
        payload["diagnostics"]["claude_unknown_record_types"] = {"synthetic_future": 4}
    source_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        expect(page.locator("#snapshot-meta")).to_contain_text("10 logs")
        expect(page.locator('[data-diagnostic="claude_unknown_record_types"]')).to_contain_text("4")
        expect(page.locator("#colophon-footer")).to_contain_text("Claude's log format may have changed")
        expect(page.locator("#colophon-footer")).to_contain_text(native.codex.as_posix())
        page.get_by_role("button", name="Codex · no data", exact=True).click()
        expect(page.locator(".empty-state")).to_contain_text(native.codex.as_posix())
        page.get_by_role("button", name="Claude", exact=True).click()
        page.locator(".brand").click()
        expect(page.locator("[data-token-boundary]")).to_be_visible()
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert requests == []

def test_claude_continue_shell_roundtrip_and_eligibility(page, native):
    cwd = native.root / "synthetic cwd's ; $(false)"
    cwd.mkdir()
    config = str(native.root / "synthetic config's & $(false)")
    identity = "synthetic-id's ; $(false)"
    def mutate(payload):
        row = next(row for row in payload["sessions"] if row["provider"] == "claude")
        row.update(id=identity, cwd=str(cwd), resume_config_dir=config)
        row["turns"][0]["requests"][0]["kind"] = "command"
    source_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.locator('[data-list-row][data-provider="claude"]').click()
        reader = page.locator("[data-reader]")
        expect(reader.locator(".request-meta")).to_contain_text("command")
        page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => window.syntheticCopied = text}, configurable: true})")
        reader.get_by_role("button", name="Copy Continue in CLI").click()
        expect(reader.locator(".copy-status")).to_contain_text("copied")
        command = page.evaluate("window.syntheticCopied")
        stubdir = native.root / "synthetic-bin"
        stubdir.mkdir()
        stub = stubdir / "claude"
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$CLAUDE_CONFIG_DIR" "$#" "$@"\n')
        stub.chmod(0o700)
        # Isolated PATH contains only the invented stub; no actual CLI can run.
        result = subprocess.run(["/bin/sh", "-c", command], env={"PATH": str(stubdir)}, text=True, capture_output=True, timeout=5)
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [str(cwd), config, "2", "--resume", identity]
        expect(reader.get_by_role("link", name="Open in Codex")).to_have_count(0)
        assert requests == []

@pytest.mark.parametrize("changes,allow", [({}, True), ({"archived": True}, True),
    ({"resume_config_dir": None}, False), ({"cwd": ""}, False), ({"history_only": True}, False),
    ({"flags": ["transcript_deleted"]}, False), ({"kind": "orphan", "agent_path": "synthetic-agent"}, False),
    ({"kind": None}, False), ({"cwd": "relative-synthetic"}, False)])
def test_claude_action_lifecycle(page, native, changes, allow):
    def mutate(payload):
        row = next(row for row in payload["sessions"] if row["provider"] == "claude")
        row.update(changes)
    source_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.locator('[data-session-id="synthetic-claude"]').click()
        reader = page.locator("[data-reader]")
        expect(reader.get_by_role("button", name="Copy Continue in CLI")).to_have_count(int(allow))
        expect(reader.get_by_role("button", name="Copy session ID", exact=True)).to_have_count(1)
        deleted = changes.get("history_only") or "transcript_deleted" in changes.get("flags", [])
        expect(reader.get_by_role("button", name="Copy log path", exact=True)).to_have_count(0 if deleted else 1)
        assert requests == []

@pytest.mark.parametrize("flag", ["live", "archived", "subagent"])
def test_claude_action_support_flags(page, native, flag):
    def mutate(payload):
        row = next(row for row in payload["sessions"] if row["provider"] == "claude")
        if flag == "archived":
            row["archived"] = True
        if flag == "subagent":
            row.update(kind="orphan", agent_path="synthetic-agent")
        payload["meta"]["links"]["claude_continue_in_cli"][flag] = flag == "subagent"
    source_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.locator('[data-session-id="synthetic-claude"]').click()
        expect(page.locator("[data-reader]").get_by_role("button", name="Copy Continue in CLI")).to_have_count(int(flag == "subagent"))
        assert requests == []

def test_source_disabled_and_hash_normalization(page, native):
    def mutate(payload):
        payload["meta"]["sources"]["claude"]["status"] = "disabled"
    source_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        for raw in ["src=invalid", "src=claude&src=codex", "src=%zz"]:
            page.goto(native.page.as_uri() + "#p=all&" + raw)
            expect(page.get_by_role("button", name="All", exact=True)).to_have_attribute("aria-pressed", "true")
        page.get_by_role("button", name="Claude · no data", exact=True).click()
        expect(page.locator(".empty-state")).to_have_text("Claude disabled by --no-claude")
        page.reload()
        expect(page.get_by_role("button", name="Claude · no data", exact=True)).to_have_attribute("aria-pressed", "true")
        assert requests == []

@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_source_unpriced_is_independent_from_availability(page, native, provider):
    def mutate(payload):
        for row in payload["sessions"]:
            row["buckets"] = [[1767355200000 // 900000, "synthetic-model-" + row["provider"], "standard", 10, 0, 0, 2, 0,
                               None if row["provider"] == provider else 1, row["provider"]]]
            row["own_usage"].update(input=10, output=2, cost_usd=None if row["provider"] == provider else 1,
                                    unpriced_tokens=12 if row["provider"] == provider else 0)
    source_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.goto(native.page.as_uri() + "#p=all&src=" + provider)
        expect(page.locator('[data-kpi="cost"]')).to_contain_text("+ unpriced")
        assert "unavailable" not in page.locator('[data-kpi="cost"]').inner_text()
        page.get_by_role("button", name="All", exact=True).click()
        expect(page.locator('[data-kpi="cost"]')).to_contain_text("$1.00 + unpriced")
        other = "Codex" if provider == "claude" else "Claude"
        page.get_by_role("button", name=other, exact=True).click()
        expect(page.locator('[data-kpi="cost"]')).to_contain_text("$1.00")
        assert "unpriced" not in page.locator('[data-kpi="cost"]').inner_text()
        assert requests == []

def test_claude_absent_checked_paths(page, native):
    def mutate(payload):
        payload["meta"]["sources"]["claude"].update(status="absent", roots=["/synthetic/checked-projects"], history_path="/synthetic/checked-history.jsonl")
    source_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        expect(page.locator("#colophon-footer")).to_contain_text("/synthetic/checked-projects, /synthetic/checked-history.jsonl")
        page.get_by_role("button", name="Claude · no data", exact=True).click()
        expect(page.locator(".empty-state")).to_contain_text("/synthetic/checked-projects, /synthetic/checked-history.jsonl")
        assert requests == []

def test_source_metric_colors_splits_and_cost_states(page, native, monkeypatch):
    captures = []
    original_screenshot = page.screenshot
    def isolated_screenshot(*args, **kwargs):
        destination = Path(kwargs["path"])
        # Check before writing: a regression must not overwrite shared evidence.
        assert destination.parent == native.root
        assert destination not in captures
        captures.append(destination)
        return original_screenshot(*args, **kwargs)
    monkeypatch.setattr(page, "screenshot", isolated_screenshot)
    def mutate(payload):
        payload["meta"]["sources"]["codex"]["costs"]["available"] = False
        claude = next(row for row in payload["sessions"] if row["provider"] == "claude")
        codex = next(row for row in payload["sessions"] if row["provider"] == "codex")
        claude["workspace"] = codex["workspace"]
        claude["buckets"] = [[1767355200000 // 900000, "synthetic-claude-model", "fast", 500, 100, 50, 20, 0, 2, "claude"]]
        claude["own_usage"].update(input=500, output=20, cost_usd=2, priced_by=[["claude:bundled/synthetic-model", 0, "fast"]])
        payload["models"]["claude:bundled/synthetic-model"] = {"periods": [{"effective_from_ms": None, "source": "curated"}]}
    source_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.locator(".brand").click()
        expect(page.locator("#snapshot-meta")).to_contain_text("catalog unavailable")
        expect(page.locator('[data-kpi="cost"]')).to_contain_text("$2.00 · codex costs unavailable")
        expect(page.locator('[data-kpi="cost"] .cost-note')).to_contain_text("codex costs unavailable")
        expect(page.locator('[data-kpi="tokens"] [data-provider="codex"]')).to_have_attribute("data-share", "150")
        expect(page.locator('[data-kpi="tokens"] [data-provider="claude"]')).to_have_attribute("data-share", "520")
        expect(page.locator('[data-workspace] .bar-fill[data-provider="codex"]')).to_have_count(1)
        expect(page.locator('[data-workspace] .bar-fill[data-provider="claude"]')).to_have_count(1)
        page.get_by_role("button", name="Calendar tokens", exact=True).click()
        cell = page.locator('[data-day="2026-01-02"]')
        expect(cell).to_have_attribute("data-provider", "claude")
        assert cell.evaluate("e => getComputedStyle(e).backgroundColor") in ["rgb(28, 53, 80)", "rgb(42, 90, 133)", "rgb(92, 148, 200)", "rgb(156, 200, 255)"]
        page.get_by_role("button", name="Calendar sessions", exact=True).click()
        expect(page.locator('[data-day="2026-01-02"]')).to_have_attribute("data-provider", "codex")
        model = page.locator('[data-model="synthetic-claude-model"]')
        expect(model).to_have_attribute("data-provider", "claude")
        assert "fast" in model.get_attribute("title")
        page.get_by_role("button", name="Claude", exact=True).click()
        expect(page.locator('[data-kpi="cost"]')).to_contain_text("$2.00")
        assert "unavailable" not in page.locator('[data-kpi="cost"]').inner_text()
        assert page.locator(".brand").evaluate("e => getComputedStyle(e).color") == "rgb(156, 200, 255)"
        page.get_by_role("button", name="Codex", exact=True).click()
        expect(page.locator('[data-kpi="cost"]')).to_contain_text("costs unavailable")
        page.get_by_role("button", name="All", exact=True).click()
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.screenshot(path=native.root / "task6-desktop.png", full_page=True)
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), page.evaluate("[...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > innerWidth).map(e => [e.className, e.getBoundingClientRect().right])")
        assert page.locator(".hour-grid .axis").evaluate_all("nodes => nodes.every(e => e.getBoundingClientRect().height <= 13)")
        assert page.locator('[data-kpi="cost"] .cost-note').evaluate("e => parseFloat(getComputedStyle(e).fontSize)") == 9
        page.screenshot(path=native.root / "task6-phone.png", full_page=True)
        assert len(captures) == 2 and all(path.is_file() for path in captures)
        assert requests == []

def test_native_page_renders_and_filters_synthetic_session(page, native_page):
    with guard_browser_errors(page):
        requests = open_native(page, native_page)
        expect(page).to_have_title("Colophon")
        row = page.locator(f'[data-session-id="{SESSION}"]')
        expect(row).to_have_count(1)
        expect(row).to_contain_text("Synthetic violet kite")
        row.click()
        reader = page.locator(f'[data-reader="{SESSION}"]')
        expect(reader).to_be_visible()
        expect(reader).to_contain_text(REQUEST)
        expect(reader).to_contain_text("Synthetic kite complete")
        page.locator(".breadcrumb").get_by_role("button", name="sessions", exact=True).click()
        search = page.get_by_role("searchbox", name="Search titles and requests")
        search.fill("synthetic-does-not-match")
        expect(page.locator("[data-list-row]")).to_have_count(0)
        expect(page.get_by_text("No sessions match the active filters")).to_be_visible()
        search.fill("violet kite")
        expect(page.locator("[data-list-row]")).to_have_count(1)
        assert requests == []

def test_long_workspace_names_wrap_and_session_list_resizes(page, native):
    long_name = "~/synthetic/" + "deeply-nested-folder/" * 6 + "synthetic-leaf (no repo)"
    def mutate(payload):
        for row in payload["sessions"]:
            payload["workspaces"][row["workspace"]]["name"] = long_name
    source_page(native, mutate)
    clipped = "nodes => nodes.filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.className)"
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.locator(".brand").click()
        labels = page.locator(".bar-label")
        expect(labels.first).to_have_text(long_name)
        assert labels.evaluate_all(clipped) == []
        page.goto(native.page.as_uri() + "#v=session&p=all&s=" + SESSION)
        expect(page.locator(f'[data-reader="{SESSION}"]')).to_be_visible()
        assert page.locator(".list-workspace, .list-row .session-title").evaluate_all(clipped) == []
        session_list, reader = page.locator(".session-list"), page.locator("[data-reader]")
        splitter = page.get_by_role("separator", name="Resize session list")
        width = lambda: session_list.bounding_box()["width"]
        stored = lambda: page.evaluate("localStorage.getItem('colophon.sessionListWidth')")
        start = width()
        box = splitter.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + 40
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 150, y, steps=6)
        page.mouse.up()
        assert abs(width() - (start + 150)) <= 2
        assert int(stored()) == round(width())
        page.reload()
        expect(reader).to_be_visible()
        assert abs(width() - (start + 150)) <= 2
        splitter.focus()
        before = width()
        page.keyboard.press("ArrowLeft")
        assert abs(width() - (before - 24)) <= 2
        # Dragging past the reserve (splitter, gaps and reader) stops at the clamp.
        box = splitter.bounding_box()
        page.mouse.move(box["x"] + 4, box["y"] + 40)
        page.mouse.down()
        page.mouse.move(page.viewport_size["width"], box["y"] + 40, steps=4)
        page.mouse.up()
        assert reader.bounding_box()["width"] >= 330
        splitter.dblclick()
        assert abs(width() - start) <= 2
        assert stored() is None
        page.set_viewport_size({"width": 375, "height": 812})
        expect(splitter).to_be_hidden()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert requests == []

def test_native_page_is_self_contained_and_error_free(page, native_page):
    html = native_page.read_text()
    for marker in ("@@FONTS@@", "@@CSS@@", "@@JS@@", "@@DATA@@"):
        assert marker not in html
    with guard_browser_errors(page):
        requests = open_native(page, native_page)
        expect(page.locator("#colophon-app")).not_to_be_empty()
        assert page.locator("script[src], link[rel=stylesheet][href]").count() == 0
        assert page.locator("#colophon-data").count() == 1
        page.wait_for_timeout(300)
        assert requests == []

def test_claude_reader_never_offers_codex_actions(page, native):
    native.claude_session()
    result = native.build()
    assert result.returncode == 0, result.stderr
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.locator('[data-session-id="synthetic-claude"]').click()
        reader = page.locator('[data-reader="synthetic-claude"]')
        expect(reader).to_be_visible()
        expect(reader).to_contain_text("Synthetic Claude kite complete")
        expect(reader.get_by_role("link", name="Open in Codex")).to_have_count(0)
        # D12 now enables primary CLI transcripts with established provenance.
        expect(reader.get_by_role("button", name="Copy Continue in CLI")).to_have_count(1)
        expect(reader.get_by_role("button", name="Copy session ID", exact=True)).to_have_count(1)
        assert requests == []

def test_claude_costs_and_tooltips_survive_unavailable_codex(page, native):
    native.session()
    source = native.claude_session()
    records = [json.loads(line) for line in source.read_text().splitlines()]
    records[-1]["message"]["model"] = "claude-opus-4-6"
    records[-1]["message"]["usage"] = {"input_tokens": 17, "output_tokens": 7, "speed": "fast"}
    now = datetime.now(timezone.utc)
    for index, record in enumerate(records):
        record["timestamp"] = (now - timedelta(seconds=3-index)).isoformat().replace("+00:00", "Z")
    records[-1]["message"]["stop_reason"] = None
    source.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in records))
    native.runtime.mkdir()
    (native.runtime / "price-history.json").write_text("synthetic-invalid-ledger")
    result = native.build()
    assert result.returncode == 0, result.stderr
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.locator('[data-session-id="synthetic-claude"]').click()
        cost = page.locator('[data-reader="synthetic-claude"] [data-reader-stat="cost"]')
        expect(cost).to_contain_text("$0.00")
        assert "claude:bundled/claude-opus-4-6" in cost.get_attribute("title")
        assert "fast" in cost.get_attribute("title")
        assert "costs unavailable" not in cost.inner_text()
        page.goto(native.page.as_uri() + "#p=all")
        expect(page.locator('[data-kpi="cost"]')).to_contain_text("codex costs unavailable")
        expect(page.locator('[data-kpi="cost"] .live')).to_contain_text("LIVE")
        model = page.locator('[data-model="claude-opus-4-6"]')
        expect(model).to_contain_text("$0.00")
        assert "fast" in model.get_attribute("title")
        assert requests == []

def test_history_toggle_tags_direct_hashes_and_activity(page, native):
    def mutate(payload):
        parent = next(row for row in payload["sessions"] if row["provider"] == "claude")
        parent["history_only"] = True
        agent = copy.deepcopy(parent)
        agent.update(id="synthetic-history-agent", parent_id=parent["id"], children=[])
        parent["children"] = [agent["id"]]
        payload["subagents"][agent["id"]] = agent
    source_page(native, mutate)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        expect(page.get_by_role("button", name="history only: shown", exact=True)).to_be_visible()
        expect(page.locator('[data-session-id="synthetic-claude"]')).to_contain_text("HISTORY ONLY")
        page.get_by_role("button", name="history only: shown", exact=True).click()
        expect(page.locator('[data-session-id="synthetic-claude"]')).to_have_count(0)
        page.goto(native.page.as_uri() + "#v=session&p=all&h=0&s=synthetic-history-agent")
        expect(page.locator("[data-reader]")).to_have_count(0)
        page.goto(native.page.as_uri() + "#v=session&p=all&h=1&s=synthetic-claude")
        reader = page.locator('[data-reader="synthetic-claude"]')
        expect(reader).to_contain_text("HISTORY ONLY")
        expect(reader.get_by_role("button", name="Copy Continue in CLI", exact=True)).to_have_count(0)
        expect(reader.get_by_role("button", name="Copy log path", exact=True)).to_have_count(0)
        expect(reader.get_by_role("button", name="Copy session ID", exact=True)).to_be_visible()
        page.goto(native.page.as_uri() + "#v=overview&p=all&src=claude")
        expect(page.locator("[data-recent]")).to_contain_text("HISTORY ONLY")
        assert requests == []

def test_real_history_period_hour_grid_zero_usage_and_actions(page, native):
    native.codex.rmdir()
    config = native.home / ".claude"
    config.mkdir()
    history = config / "history.jsonl"
    history.write_text("".join(json.dumps({"sessionId": "synthetic-history", "display": prompt,
        "timestamp": stamp, "project": "/synthetic/history"}) + "\n" for prompt, stamp in [
        ("Synthetic first history prompt", 1767355200000), ("Synthetic second history prompt", 1767355205000)]))
    result = native.build()
    assert result.returncode == 0, result.stderr
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.goto(native.page.as_uri() + "#v=overview&p=custom&from=2026-01-02&to=2026-01-02&src=claude")
        expect(page.locator('[data-how="4-7"]')).to_have_attribute("title", "Fri 7:00 · 2 turns")
        expect(page.locator('[data-kpi="tokens"] .kpi-value')).to_contain_text("0")
        expect(page.locator('[data-kpi="active_ms"] .kpi-value')).to_contain_text("0")
        page.locator('[data-how="4-7"]').click()
        expect(page.locator('[data-list-row]')).to_have_count(1)
        page.locator('[data-list-row]').click()
        reader = page.locator('[data-reader="synthetic-history"]')
        expect(reader).to_contain_text("Synthetic first history prompt")
        expect(reader).to_contain_text("Synthetic second history prompt")
        expect(reader.get_by_role("button", name="Copy Continue in CLI", exact=True)).to_have_count(0)
        expect(reader.get_by_role("button", name="Copy log path", exact=True)).to_have_count(0)
        page.get_by_role("button", name="history only: shown", exact=True).click()
        expect(page.locator("[data-reader]")).to_have_count(0)
        assert "from=2026-01-02" in page.url and "how=4-7" in page.url
        page.goto(native.page.as_uri() + "#v=list&p=custom&from=2026-01-03&to=2026-01-03")
        expect(page.locator('[data-list-row]')).to_have_count(0)
        assert requests == []

# 2026-03-15 12:00 in New York; the synthetic sessions start on 2026-01-02.
PERIOD_SNAPSHOT_MS = int(datetime(2026, 3, 15, 16, tzinfo=timezone.utc).timestamp() * 1000)

def period_page(native):
    def mutate(payload):
        payload["meta"]["generated_at_ms"] = PERIOD_SNAPSHOT_MS
    source_page(native, mutate)

def test_period_dial_defaults_to_mtd_steps_and_returns_home(zoned_page, native):
    page = zoned_page
    period_page(native)
    dial, label = page.get_by_role("group", name="Period range"), page.locator("[data-period-label]")
    sessions = page.locator('[data-kpi="sessions"]')
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.goto(native.page.as_uri() + "#v=overview")
        expect(page).to_have_url(re.compile(r"p=mtd"))
        expect(page.get_by_role("button", name="MTD", exact=True)).to_have_attribute("aria-pressed", "true")
        expect(label).to_have_text(re.compile(r"^March 2026\s*to date$"))
        expect(dial.get_by_role("button", name="Next month")).to_be_disabled()
        expect(sessions.locator(".kpi-value")).to_have_attribute("data-value", "0")
        expect(sessions.locator(".kpi-delta")).to_have_text("▲ 0 vs Feb 1–15")
        dial.get_by_role("button", name="Previous month").click()
        expect(label).to_have_text("February 2026")
        expect(dial).to_have_attribute("data-motion", "back")
        expect(page).to_have_url(re.compile(r"o=-1"))
        expect(sessions.locator(".kpi-delta")).to_have_text(re.compile(r"vs January 2026$"))
        page.locator("body").press("[")
        expect(label).to_have_text("January 2026")
        expect(page).to_have_url(re.compile(r"o=-2"))
        expect(sessions.locator(".kpi-value")).to_have_attribute("data-value", "2")
        expect(sessions.locator(".kpi-delta")).to_have_text(re.compile(r"vs December 2025$"))
        expect(dial.get_by_role("button", name="Previous month")).to_be_disabled()
        expect(dial.get_by_role("button", name="Next month")).to_be_enabled()
        # Choosing MTD again returns to the current month from any distance.
        page.get_by_role("button", name="MTD", exact=True).click()
        expect(label).to_have_text(re.compile(r"^March 2026\s*to date$"))
        expect(dial).to_have_attribute("data-motion", "forward-far")
        assert "o=" not in page.url
        page.go_back()
        expect(label).to_have_text("January 2026")
        page.get_by_role("button", name="QTD", exact=True).click()
        expect(label).to_have_text(re.compile(r"^Q1 2026\s*to date$"))
        assert "o=" not in page.url
        expect(sessions.locator(".kpi-value")).to_have_attribute("data-value", "2")
        expect(dial.get_by_role("button", name="Previous quarter")).to_be_disabled()
        expect(dial.get_by_role("button", name="Next quarter")).to_be_disabled()
        page.get_by_role("button", name="YTD", exact=True).click()
        expect(label).to_have_text(re.compile(r"^2026\s*to date$"))
        expect(dial.get_by_role("button", name="Previous year")).to_be_disabled()
        page.get_by_role("button", name="30D", exact=True).click()
        expect(label).to_have_text("Feb 14 – Mar 15")
        expect(sessions.locator(".kpi-delta")).to_have_text(re.compile(r"vs prior 30D$"))
        for name in ["Previous period", "Next period"]:
            expect(dial.get_by_role("button", name=name)).to_be_disabled()
        page.get_by_role("button", name="ALL", exact=True).click()
        expect(label).to_have_text("All time")
        page.get_by_role("button", name="30D", exact=True).click()
        assert requests == []

def test_period_custom_starts_from_shown_range_and_shifts(zoned_page, native):
    page = zoned_page
    period_page(native)
    dial = page.get_by_role("group", name="Period range")
    start, end = dial.get_by_label("From date"), dial.get_by_label("To date")
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.goto(native.page.as_uri() + "#v=overview&p=mtd&o=-1")
        page.get_by_role("button", name="Custom", exact=True).click()
        expect(start).to_have_value("2026-02-01")
        expect(end).to_have_value("2026-02-28")
        expect(page.locator("[data-period-label]")).to_be_hidden()
        page.goto(native.page.as_uri() + "#v=overview&p=30d")
        page.get_by_role("button", name="Custom", exact=True).click()
        expect(start).to_have_value("2026-02-14")
        expect(end).to_have_value("2026-03-15")
        expect(dial.get_by_role("button", name="Next range")).to_be_disabled()
        dial.get_by_role("button", name="Previous range").click()
        expect(start).to_have_value("2026-01-15")
        expect(end).to_have_value("2026-02-13")
        assert "from=2026-01-15" in page.url and "to=2026-02-13" in page.url
        page.locator("body").press("]")
        expect(end).to_have_value("2026-03-15")
        # Keys typed into a field never step the period.
        page.get_by_role("searchbox").press("[")
        expect(start).to_have_value("2026-02-14")
        assert requests == []

def test_period_offsets_normalize_and_cross_year_boundaries(zoned_page, native):
    page = zoned_page
    period_page(native)
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        for raw, kept in [("p=qtd&o=-3", True), ("p=30d&o=-1", False), ("p=mtd&o=1", False), ("p=mtd&o=-0", False), ("p=ytd&o=x", False)]:
            page.goto(native.page.as_uri() + "#v=overview&" + raw)
            expect(page).to_have_url(re.compile(r"p=" + raw[2:5]))
            assert ("o=" in page.url) == kept, raw
        cases = page.evaluate("""() => {
          const t = window.__colophonTest.time, now = new Date(2026, 0, 10, 12).getTime();
          const show = w => w && [t.localDayKey(w.from), t.localDayKey(w.to - 1)];
          return Object.fromEntries([["mtd"], ["mtd", "-1"], ["qtd"], ["qtd", "-1"], ["qtd", "-4"], ["ytd", "-1"], ["30d", "-1"]].map(([p, o]) => {
            const w = t.periodWindow(p, now, {o});
            return [p + (o || ""), [show(w), show(t.previousWindow(p, w, now, {o}))]];
          }));
        }""")
        assert cases == {
            "mtd": [["2026-01-01", "2026-01-10"], ["2025-12-01", "2025-12-10"]],
            "mtd-1": [["2025-12-01", "2025-12-31"], ["2025-11-01", "2025-11-30"]],
            "qtd": [["2026-01-01", "2026-01-10"], ["2025-10-01", "2025-10-10"]],
            "qtd-1": [["2025-10-01", "2025-12-31"], ["2025-07-01", "2025-09-30"]],
            "qtd-4": [["2025-01-01", "2025-03-31"], ["2024-10-01", "2024-12-31"]],
            "ytd-1": [["2025-01-01", "2025-12-31"], ["2024-01-01", "2024-12-31"]],
            "30d-1": [["2025-12-12", "2026-01-10"], ["2025-11-12", "2025-12-11"]],
        }
        assert requests == []
