"""File-URL integration gates for the built-page frontend stack."""

from pathlib import Path
import sys

from playwright.sync_api import expect, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
VENDOR = PROJECT_ROOT / "web" / "vendor"
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import guard_browser_errors
from tools.testkit import run_launcher
import json
import re
import shutil
import pytest
from tests.test_rules_v2 import synthetic_rules, write_synthetic


@pytest.fixture(autouse=True)
def private_scratch(tmp_path):
    assert not tmp_path.resolve().is_relative_to(REPO_ROOT.resolve())
    tmp_path.chmod(0o700)


def synthetic_root(tmp_path):
    root = tmp_path / "rules"
    for year in (2025, 2026):
        data = synthetic_rules()
        data["year"] = year
        write_synthetic(root / "federal" / f"{year}.yaml", data)
    data = synthetic_rules()
    data["year"] = 2025
    write_synthetic(root / "states" / "XF" / "2025.yaml", data)
    (root / "states" / "XE").mkdir()
    return root


def test_display_name_falls_back_to_directory_name(tmp_path):
    from taxkit.page import build_payload
    root = synthetic_root(tmp_path)
    data = synthetic_rules()
    data.pop("display_name", None)
    write_synthetic(root / "states" / "xn" / "2026.yaml", data)
    state = next(s for s in build_payload(root, rules_source="custom")["states"]
                 if s["code"] == "XN")
    assert state["display_name"] == "xn"


def test_broken_year_symlink_fails_build(tmp_path):
    root = synthetic_root(tmp_path)
    entry = root / "states" / "XB" / "2026.yaml"
    entry.parent.mkdir()
    entry.symlink_to("missing.yaml")
    result = run_launcher(PROJECT_ROOT / "tax2", "--no-browser", "--rules-dir", str(root))
    assert result.returncode == 1, result.stderr
    assert f"Invalid rules file {entry}:" in result.stderr
    assert not (tmp_path / "tax2-home" / "tax2.html").exists()


def test_non_regular_year_entry_fails_build(tmp_path):
    root = synthetic_root(tmp_path)
    entry = root / "federal" / "2027.yml"
    entry.mkdir()
    result = run_launcher(PROJECT_ROOT / "tax2", "--no-browser", "--rules-dir", str(root))
    assert result.returncode == 1, result.stderr
    assert f"Invalid rules file {entry}:" in result.stderr
    assert not (tmp_path / "tax2-home" / "tax2.html").exists()


def test_non_ascii_digit_year_ignored(tmp_path):
    from taxkit.page import build_payload
    root = synthetic_root(tmp_path)
    expected = build_payload(root, rules_source="custom", built_at="synthetic fixed time")
    (root / "federal" / "٢٠٢٦.yaml").write_text("invalid: [", encoding="utf-8")
    assert build_payload(root, rules_source="custom", built_at="synthetic fixed time") == expected


def test_bundled_payload_unchanged_by_discovery_refactor(monkeypatch, tmp_path):
    from taxkit.page import build_payload
    home = tmp_path / "runtime"
    home.mkdir(mode=0o700)
    config = home / "config.yaml"
    config.write_text("default_states: [GA]\nqif_overrides: {}\n")
    config.chmod(0o600)
    monkeypatch.setenv("TAX2_HOME", str(home))
    expected = json.loads((PROJECT_ROOT / "tests/fixtures/payload_bundled_baseline.json").read_text())
    actual = build_payload(PROJECT_ROOT / "tests/fixtures/parity/bundled/rules",
                           rules_source="custom", built_at="2026-01-01T00:00:00+00:00")
    assert actual == expected


def test_fifo_year_entry_rejected_before_read(monkeypatch, tmp_path):
    import os
    import taxkit.page as builder
    root = synthetic_root(tmp_path)
    entry = root / "federal" / "2027.yaml"
    os.mkfifo(entry)
    original = builder.load_rules

    def guarded_load(path):
        assert path != str(entry), "FIFO must be rejected before opening it"
        return original(path)

    monkeypatch.setattr(builder, "load_rules", guarded_load)
    with pytest.raises(ValueError, match=re.escape(f"Invalid rules file {entry}:")):
        builder.build_payload(root, rules_source="custom")


@pytest.mark.parametrize("extension, winner", [("yaml", "2026.yaml"), ("yml", "002026.yml")])
def test_leading_zero_duplicate_precedence(tmp_path, extension, winner):
    from taxkit.page import build_payload
    root = synthetic_root(tmp_path)
    for prefix in ("002026", "02026", "2026"):
        data = synthetic_rules()
        data["display_name"] = f"{prefix}.{extension}"
        write_synthetic(root / "states" / "XF" / f"{prefix}.{extension}", data)
    state = build_payload(root, rules_source="custom")["states"][1]
    assert state["rules"]["2026"]["display_name"] == winner


def test_regular_year_symlink_is_valid(tmp_path):
    from taxkit.page import build_payload
    root = synthetic_root(tmp_path)
    (root / "federal" / "2027.yaml").symlink_to("2026.yaml")
    payload = build_payload(root, rules_source="custom")
    assert payload["federal"]["2027"] == payload["federal"]["2026"]


def test_shadowed_leading_zero_candidate_still_validates(tmp_path):
    from taxkit.page import build_payload
    root = synthetic_root(tmp_path)
    entry = root / "federal" / "002026.yml"
    entry.write_text("invalid: [")
    with pytest.raises(ValueError, match=re.escape(str(entry))):
        build_payload(root, rules_source="custom")


def test_payload_schema_sorting_projection_and_unchanged_config(monkeypatch, tmp_path):
    from taxkit.page import build_payload
    home = tmp_path / "runtime"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("TAX2_HOME", str(home))
    config = home / "config.yaml"
    config.write_text('default_states: [XF]\nqif_overrides:\n  " xtest ": {state_expense: "synthetic", unknown: 7}\n')
    config.chmod(0o600)
    before = (config.read_bytes(), config.stat().st_mtime_ns)
    payload = build_payload(synthetic_root(tmp_path), rules_source="custom", built_at="2026-01-01T00:00:00+00:00")
    assert set(payload) == {"schema", "app", "built_at", "rules_source", "federal", "states", "config"}
    assert payload["schema"] == 1
    assert payload["app"] == {"name": "Tax2", "version": "3.0"}
    assert list(payload["federal"]) == ["2025", "2026"]
    assert [state["code"] for state in payload["states"]] == ["XE", "XF"]
    assert payload["states"][0] == {"code": "XE", "display_name": "XE", "years": [], "qif": None, "rules": {}}
    assert payload["states"][1]["years"] == [2025]
    assert "2026" not in payload["states"][1]["rules"]
    assert payload["config"] == {"default_states": ["XF"], "qif_overrides": {"XTEST": {"state_expense": "synthetic"}}}
    assert payload["federal"]["2026"]["components"][0]["applies_to"] == ["earned", "unearned"]
    assert str(tmp_path) not in json.dumps(payload)
    assert (config.read_bytes(), config.stat().st_mtime_ns) == before


@pytest.mark.parametrize("failure", ["older", "shadow", "missing_federal", "no_state", "empty_components", "basis", "nan"])
def test_complete_inventory_fails(monkeypatch, tmp_path, failure):
    from taxkit.page import build_payload
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    root = synthetic_root(tmp_path)
    expected = "2026.yml" if failure == "shadow" else "2025.yaml"
    if failure in ("older", "shadow"):
        path = root / "federal" / ("2026.yml" if failure == "shadow" else "2025.yaml")
        path.write_text("invalid: [")
    elif failure == "missing_federal":
        shutil.rmtree(root / "federal")
        expected = "federal"
    elif failure == "no_state":
        shutil.rmtree(root / "states" / "XF")
        expected = "state"
    else:
        data = synthetic_rules()
        if failure == "empty_components": data["components"] = []
        elif failure == "basis": data["components"][0]["applies_to"] = []
        else: data["credits"] = [{"name": "synthetic", "amount": float("nan")}]
        write_synthetic(root / "states" / "XF" / "2025.yaml", data)
    with pytest.raises(ValueError, match=expected):
        build_payload(root, rules_source="custom")


def test_duplicate_extensions_and_latest_metadata(monkeypatch, tmp_path):
    from taxkit.page import build_payload
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    root = synthetic_root(tmp_path)
    data = synthetic_rules()
    data.update(display_name="Synthetic Latest", qif={"state_transfer": "[Synthetic]"})
    write_synthetic(root / "states" / "XF" / "2026.yaml", data)
    data["display_name"] = "Wrong extension"
    write_synthetic(root / "states" / "XF" / "2026.yml", data)
    state = build_payload(root, rules_source="bundled")["states"][1]
    assert state["years"] == [2025, 2026]
    assert state["display_name"] == "Synthetic Latest"
    assert state["qif"] == {"state_expense": None, "state_transfer": "[Synthetic]"}


def test_render_json_roundtrip_and_source_order():
    from taxkit.page import render_page
    payload = {"synthetic": "</script> café {{CSS}} {{PAYLOAD}}"}
    page = render_page(payload).decode()
    data = re.search(r'<script id="tax2-data" type="application/json">(.*?)</script>', page, re.S).group(1)
    assert "<" not in data
    assert json.loads(data) == payload
    assert "\\u003c" in data
    assert not re.search(r'<(?:script|link)[^>]*(?:src|href)=', page)
    assert "fetch(" not in page
    positions = [page.index((PROJECT_ROOT / "web" / name).read_text())
                 for name in ("vendor/preact.umd.js", "vendor/hooks.umd.js", "vendor/htm.umd.js", "engine.js", "app.js")]
    assert positions == sorted(positions)


@pytest.mark.parametrize("asset", ["engine.js", "app.js", "styles.css", "vendor/preact.umd.js", "vendor/hooks.umd.js", "vendor/htm.umd.js", "vendor/preact.LICENSE", "vendor/htm.LICENSE"])
def test_raw_assets_reject_script_close(monkeypatch, tmp_path, asset):
    import taxkit.page as builder
    assets = tmp_path / "web"
    shutil.copytree(PROJECT_ROOT / "web", assets)
    (assets / asset).write_text("synthetic </ScRiPt dangerous")
    monkeypatch.setattr(builder, "ASSET_ROOT", assets)
    with pytest.raises(ValueError, match=re.escape(asset)):
        builder.render_page({})


def test_inline_preact_htm_hooks_work_offline(tmp_path):
    """Classic UMD scripts render and update state without external requests."""
    assert not tmp_path.resolve().is_relative_to(REPO_ROOT.resolve())
    scripts = []
    for name in ("preact.umd.js", "hooks.umd.js", "htm.umd.js"):
        source = VENDOR / name
        assert source.is_file(), f"Missing vendored frontend asset: {name}"
        scripts.append(f"<script>{source.read_text(encoding='utf-8')}</script>")
    for name in ("preact.LICENSE", "htm.LICENSE"):
        assert (VENDOR / name).read_text(encoding="utf-8").strip()

    probe = tmp_path / "inline-probe.html"
    probe.write_text(
        '<!doctype html><html><head><meta charset="utf-8"></head><body>'
        '<div id="app"></div>'
        + "".join(scripts)
        + """
        <script>
        const html = htm.bind(preact.h);
        function Probe() {
            const [count, setCount] = preactHooks.useState(0);
            return html`<button onClick=${() => setCount(value => value + 1)}>
                Synthetic count: ${count}
            </button>`;
        }
        preact.render(html`<${Probe} />`, document.getElementById('app'));
        </script></body></html>
        """,
        encoding="utf-8",
    )
    probe.chmod(0o600)

    non_file_requests = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(service_workers="block")

            def route_request(route):
                if route.request.url.startswith("file:"):
                    route.continue_()
                else:
                    route.abort()

            def record_request(request):
                if not request.url.startswith("file:"):
                    non_file_requests.append(request.url)

            context.on("request", record_request)
            context.route("**/*", route_request)
            page = context.new_page()
            with guard_browser_errors(page):
                page.goto(probe.as_uri())
                assert page.evaluate("typeof window.preactHooks.useState") == "function"
                button = page.get_by_role("button", name="Synthetic count: 0")
                expect(button).to_be_visible()
                button.click()
                expect(page.get_by_role("button", name="Synthetic count: 1")).to_be_visible()
                assert non_file_requests == []
        finally:
            browser.close()


def test_rendered_payload_and_engine_compute_offline(monkeypatch, tmp_path):
    from taxkit.page import build_payload, render_page
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    payload = build_payload(synthetic_root(tmp_path), rules_source="custom")
    path = tmp_path / "synthetic-page.html"
    path.write_bytes(render_page(payload))
    path.chmod(0o600)
    requests = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(service_workers="block")
        context.on("request", lambda request: requests.append(request.url)
                   if not request.url.startswith("file:") else None)
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith("file:") else route.abort())
        page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri())
            result = page.evaluate("""() => Tax2Engine.computeMonthly({earnedCents:10000,
                unearnedCents:0,filingStatus:'single',year:2025,
                states:[{code:'XF',allocation_pct:100}]},
                JSON.parse(document.getElementById('tax2-data').textContent))""")
            assert result["gross_cents"] == 10000
            assert result["net_cents"] == 10000 - result["total_monthly_cents"]
            assert requests == []
        browser.close()
