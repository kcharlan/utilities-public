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

@pytest.fixture
def page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        # Native action links remain inert even if a test accidentally clicks one.
        page.add_init_script("document.addEventListener('click', e => { const a=e.target.closest('a'); if(a && !/^(file:|#)/.test(a.getAttribute('href') || '')) { e.preventDefault(); e.stopImmediatePropagation(); } }, true)")
        try:
            yield page
        finally:
            context.close()
            browser.close()

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
