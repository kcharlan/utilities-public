"""The built page in offline Chromium, opened from file://. Synthetic data only."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pytest
from playwright.sync_api import expect, sync_playwright

from helpers import MAKER, ladder_models, model, snapshot

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
from tools.testkit import (  # noqa: E402
    assert_fonts_loaded,
    assert_no_external_resources,
    block_external_requests,
    guard_browser_errors,
)

NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
CONFIG = {"op_item": "", "op_vault": "", "op_field": "credential", "max_age_hours": 12}
FRONTIER = ["Beta Test 1 Medium", "Beta Test 1 High", "Alpha Test 1 Medium",
            "Beta Test 1 XHigh", "Alpha Test 1 High", "Alpha Test 1 Max"]
FINDINGS = [
    "Beta Test 1 Max is dominated: Alpha Test 1 High scores 3 higher for $0.50 less per task.",
    "Alpha Test 1 XHigh is dominated: Alpha Test 1 High scores the same for $3.00 less per task.",
    "Cheapest step on the frontier: Beta Test 1 Medium to Beta Test 1 High, $0.10 per point.",
    "Most expensive step on the frontier: Alpha Test 1 High to Alpha Test 1 Max, $3.00 per point.",
    "Alpha Test 1 High to XHigh adds $3.00 per task and no points.",
]
MARKUP = 'Zeta <img src=x onerror=alert(1)> & "Q"'


def payload_for(ml, models=None, *, previous=None, checked=None):
    snap = snapshot(models if models is not None else ladder_models(),
                    when=(NOW - timedelta(hours=2)).isoformat(),
                    checked=checked)
    return ml.build_payload(snap, previous, CONFIG)


@pytest.fixture(scope="module")
def chromium():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def open_page(chromium, ml, tmp_path):
    assert not tmp_path.resolve().is_relative_to(PROJECT.parent.resolve())
    opened = []

    def _open(payload=None, *, fragment="", color_scheme="light", width=1280, height=900, init_script=None):
        payload = payload or payload_for(ml)
        path = tmp_path / f"page-{len(opened)}.html"
        path.write_bytes(ml.render_page(payload))
        context = chromium.new_context(viewport={"width": width, "height": height},
                                       color_scheme=color_scheme, service_workers="block")
        context.set_offline(True)
        blocked = block_external_requests(context)
        if init_script:
            context.add_init_script(init_script)
        page = context.new_page()
        page.clock.set_fixed_time(NOW)
        dialogs = []
        page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
        guard = guard_browser_errors(page)
        guard.__enter__()
        opened.append((context, page, guard, blocked, dialogs))
        page.goto(path.as_uri() + fragment)
        expect(page.locator("#status-age")).to_be_visible()
        return page

    yield _open
    for context, page, guard, blocked, dialogs in opened:
        guard.__exit__(None, None, None)
        assert_no_external_resources(page, blocked)
        assert dialogs == []
        context.close()


def texts(page, selector):
    return page.locator(selector).evaluate_all("els => els.map(e => e.textContent.trim())")


def compare(page):
    page.click("#tab-compare")
    expect(page.locator("#tab-compare")).to_have_attribute("aria-selected", "true")


def add(page, query):
    if not page.locator("#model-search").is_visible():
        page.click("#add-model")
    page.fill("#model-search", query)
    page.press("#model-search", "Enter")


def pareto_rows(page):
    return page.locator("#pareto-table tbody tr").evaluate_all("""rows => rows.map(r => ({
        label: r.querySelector('[data-c=label]').textContent.trim(),
        status: r.querySelector('[data-c=status]').textContent.trim(),
        reason: r.querySelector('.reason') ? r.querySelector('.reason').textContent.trim() : null}))""")


def alpha_and_beta(page):
    compare(page)
    add(page, "alpha")
    add(page, "beta")
    page.keyboard.press("Escape")
    page.select_option("#effort-hi", "max")
    page.select_option("#effort-lo", "medium")


def test_opens_on_all_models(open_page, ml):
    page = open_page()
    expect(page.locator("#tab-all")).to_have_attribute("aria-selected", "true")
    scored = ml.classify(ladder_models())
    assert page.locator("#all-table tbody tr").count() == len(scored) == 12
    names = texts(page, "#all-table tbody [data-c=family]")
    assert "Alpha Test 1" in names and "Gamma Test 1" in names
    assert page.locator("#status-age").text_content().startswith("Data is")
    assert page.locator("#status-age").text_content() == "Data is 2 hours old"
    assert "stale" not in (page.locator("#status-age").get_attribute("class") or "")
    assert "95 of 100" in page.locator("#status-quota").text_content()
    assert_fonts_loaded(page, ["Hanken Grotesk"])


def test_all_models_filters(open_page):
    page = open_page()
    page.select_option("#all-creator", "Sample Works")
    assert set(texts(page, "#all-table tbody [data-c=maker]")) == {"Sample Works"}
    page.select_option("#all-creator", "")
    page.fill("#all-filter", "GAMMA")
    assert texts(page, "#all-table tbody [data-c=family]") == ["Gamma Test 1"]


def test_all_models_filter_matches_tags(open_page, ml):
    tagged = model("Iota Test 1 (High, Synthetic Tag)", 28.0, 0.5, slug="iota")
    page = open_page(payload_for(ml, ladder_models() + [tagged]))
    page.fill("#all-filter", "synthetic TAG")
    assert texts(page, "#all-table tbody [data-c=family]") == ["Iota Test 1"]
    assert texts(page, "#all-table tbody [data-c=tags]") == ["Synthetic Tag"]


def test_picker_counts_only_effort_levels(open_page, ml):
    plain = model("Alpha Test 1", 30.0, 1.0, maker=MAKER, slug="alpha-plain")
    page = open_page(payload_for(ml, ladder_models() + [plain]))
    compare(page)
    page.click("#add-model")
    page.fill("#model-search", "alpha")
    expect(page.locator("#model-list li").first).to_contain_text("4 effort levels")


def test_add_from_all_models_table(open_page):
    page = open_page()
    page.locator("#all-table tbody tr", has_text="Beta Test 1").first.locator("input[type=checkbox]").check()
    compare(page)
    assert texts(page, "#chips .chip .fam") == ["Beta Test 1"]


def test_add_models_by_search(open_page):
    page = open_page()
    compare(page)
    expect(page.locator(".empty", has_text="Add a model to start comparing.")).to_be_visible()
    add(page, "beta")
    assert texts(page, "#chips .chip .fam") == ["Beta Test 1"]
    page.fill("#model-search", "BETA")
    entry = page.locator("#model-list li button", has_text="Beta Test 1")
    expect(entry).to_be_disabled()
    expect(entry).to_contain_text("Added")
    page.fill("#model-search", "example lab")
    assert page.locator("#model-list li").count() == 2


def test_picker_keyboard(open_page):
    page = open_page()
    compare(page)
    page.click("#add-model")
    page.fill("#model-search", "test 1")
    second = texts(page, "#model-list li .fam")[1]
    page.press("#model-search", "ArrowDown")
    page.press("#model-search", "Enter")
    assert texts(page, "#chips .chip .fam") == [second]
    page.press("#model-search", "Escape")
    expect(page.locator("#model-search")).to_be_hidden()
    expect(page.locator("#add-model")).to_be_focused()


def test_whole_point_pareto(open_page):
    page = open_page()
    alpha_and_beta(page)
    rows = pareto_rows(page)
    assert [r["label"] for r in rows if r["status"] == "Frontier"] == FRONTIER
    reasons = {r["label"]: r["reason"] for r in rows if r["status"] == "Dominated"}
    assert reasons == {
        "Beta Test 1 Max": "Alpha Test 1 High scores 3 higher for $0.50 less per task",
        "Alpha Test 1 XHigh": "Alpha Test 1 High scores the same for $3.00 less per task",
    }
    assert texts(page, "#findings li") == FINDINGS


def test_decimal_mode_switch(open_page):
    page = open_page()
    alpha_and_beta(page)
    page.click("#mode-decimal")
    expect(page.locator("#mode-decimal")).to_have_attribute("aria-pressed", "true")
    status = {r["label"]: r["status"] for r in pareto_rows(page)}
    assert status["Alpha Test 1 XHigh"] == "Frontier"
    assert "46.2" in page.locator("#ladder-table").text_content()


def step_cells(page):
    return page.locator("#steps-table tbody tr").evaluate_all("""rows => rows.map(r => [
        r.querySelector('[data-c=family]').textContent.trim() + ' ' + r.querySelector('[data-c=effort]').textContent.trim(),
        Number(r.querySelector('[data-c=score]').dataset.v),
        [...r.querySelectorAll('td.step')].map(td => td.textContent.trim())])""")


def test_header_sort(open_page):
    page = open_page()
    alpha_and_beta(page)
    before = {label: cells for label, _, cells in step_cells(page)}
    header = page.locator("#steps-table thead th[data-k=score]")
    header.click()
    expect(header).to_have_attribute("aria-sort", "descending")
    scores = [score for _, score, _ in step_cells(page)]
    assert scores == sorted(scores, reverse=True)
    header.click()
    expect(header).to_have_attribute("aria-sort", "ascending")
    rows = step_cells(page)
    assert [score for _, score, _ in rows] == sorted(scores)
    assert {label: cells for label, _, cells in rows} == before
    assert before["Alpha Test 1 High"][:3] == ["0", "+$3.00", "no gain"]
    header.focus()
    page.keyboard.press("Enter")
    expect(header).to_have_attribute("aria-sort", "descending")


def test_effort_range(open_page):
    page = open_page()
    alpha_and_beta(page)
    page.select_option("#effort-lo", "high")
    assert "Medium" not in texts(page, "#ladder-table tbody th")
    assert "Medium" not in texts(page, "#steps-table tbody [data-c=effort]")
    assert not [r for r in pareto_rows(page) if r["label"].endswith("Medium")]
    assert texts(page, "#ladder-table tbody th") == ["Max", "XHigh", "High"]


def test_limit_of_eight(open_page, ml):
    letters = "ABCDEFGHI"
    payload = payload_for(ml, [model(f"Fam {c} Test (High)", 30.0 + i, 1.0 + i) for i, c in enumerate(letters)])
    page = open_page(payload)
    compare(page)
    for c in letters[:8]:
        add(page, f"fam {c} test")
    assert len(texts(page, "#chips .chip")) == 8
    button = page.locator("#add-model")
    expect(button).to_be_disabled()
    expect(button).to_have_text("Limit of 8 reached")


def test_no_cost_selection(open_page):
    page = open_page()
    compare(page)
    add(page, "delta")
    page.keyboard.press("Escape")
    assert texts(page, "#ladder-table tbody td .num") == ["15"]
    expect(page.locator("#pareto .empty")).to_have_text("None of the selected rows has a cost per task.")
    assert page.locator("#pareto-table").count() == 0


def test_markup_in_names_is_text(open_page, ml):
    # MARKUP holds "(1)", so it can only be a family on its own: with a trailing
    # "(High)" the name rule would see two groups. LADDERED covers the ladder table.
    laddered = 'Kappa <i>x</i> & "Q" | R'
    extra = [model(MARKUP, 25.0, 1.0, slug="zeta"), model(laddered + " (High)", 26.0, 2.0, slug="kappa")]
    page = open_page(payload_for(ml, ladder_models() + extra))
    families = texts(page, "#all-table tbody [data-c=family]")
    assert MARKUP in families and laddered in families
    compare(page)
    page.click("#add-model")
    page.fill("#model-search", "zeta")
    assert texts(page, "#model-list li .fam") == [MARKUP]
    page.press("#model-search", "Enter")
    page.fill("#model-search", "kappa")
    page.press("#model-search", "Enter")
    page.keyboard.press("Escape")
    assert texts(page, "#chips .chip .fam") == [MARKUP, laddered]
    assert laddered in page.locator("#ladder-table thead").text_content()
    assert sorted(r["label"] for r in pareto_rows(page)) == sorted([MARKUP, laddered + " High"])
    assert page.locator("#app img").count() == 0 and page.locator("#app i").count() == 0


def ui_state(page):
    return {
        "view": page.locator("[role=tab][aria-selected=true]").get_attribute("id"),
        "chips": texts(page, "#chips .chip .fam"),
        "hi": page.locator("#effort-hi").input_value(),
        "lo": page.locator("#effort-lo").input_value(),
        "decimal": page.locator("#mode-decimal").get_attribute("aria-pressed"),
        "sort": page.locator("#steps-table thead th[data-k=score]").get_attribute("aria-sort"),
    }


def test_state_restores_from_hash(open_page):
    page = open_page()
    alpha_and_beta(page)
    page.select_option("#effort-lo", "high")
    page.click("#mode-decimal")
    header = page.locator("#steps-table thead th[data-k=score]")
    header.click()
    header.click()
    expected = ui_state(page)
    assert expected["sort"] == "ascending" and expected["chips"] == ["Alpha Test 1", "Beta Test 1"]
    page.reload()
    expect(page.locator("#status-age")).to_be_visible()
    assert ui_state(page) == expected
    fragment = "#" + page.url.split("#", 1)[1]
    fresh = open_page(fragment=fragment)
    assert ui_state(fresh) == expected


def test_storage_restores_without_hash(open_page):
    page = open_page()
    compare(page)
    add(page, "beta")
    page.goto(page.url.split("#", 1)[0])
    expect(page.locator("#status-age")).to_be_visible()
    assert texts(page, "#chips .chip .fam") == ["Beta Test 1"]


def test_malformed_hash_falls_back_to_defaults(open_page):
    page = open_page(fragment="#%7Bnot-json")
    expect(page.locator("#tab-all")).to_have_attribute("aria-selected", "true")
    page = open_page(fragment="#" + quote(json.dumps({"view": "nope", "keys": "x", "mode": 3, "sorts": []})))
    expect(page.locator("#tab-all")).to_have_attribute("aria-selected", "true")


def test_missing_family_chip(open_page):
    gone = json.dumps([MAKER, "Gone Test 9"])
    state = {"view": "compare", "keys": [gone], "mode": "whole"}
    page = open_page(fragment="#" + quote(json.dumps(state), safe=""))
    chip = page.locator("#chips .chip.gone")
    expect(chip).to_contain_text("Gone Test 9 is no longer listed")
    assert page.locator("#ladder-table").count() == 0
    chip.locator("button").click()
    expect(page.locator("#chips .chip")).to_have_count(0)
    expect(page.locator(".empty", has_text="Add a model to start comparing.")).to_be_visible()


def test_changes_panel(open_page, ml):
    current = ladder_models() + [model("New Test 1 (High)", 50.0, 1.0), model("Rho Test 1 (High)", 62.2, 1.0)]
    old_models = [m for m in ladder_models() if m["name"] != "Alpha Test 1 (Medium)"] + [
        model("Alpha Test 1 (Medium)", 38.0, 2.0),
        model("Old Test 1 (High)", 20.0, 1.0),
        model("Rho Test 1 (High)", 61.8, 1.0),
    ]
    previous = snapshot(old_models, when="2026-10-01T00:00:00+00:00", version=4)
    page = open_page(payload_for(ml, current, previous=previous))
    panel = page.locator("#changes")
    if not panel.evaluate("el => el.open"):
        panel.locator("summary").click()
    text = panel.text_content()
    assert "version changed from 4 to 5" in text
    assert texts(panel, "[data-changes=added] li") == ["New Test 1 (High)"]
    assert texts(panel, "[data-changes=removed] li") == ["Old Test 1 (High)"]
    assert "Alpha Test 1 (Medium)" in text and "38 to 40" in text
    assert "Rho Test 1" not in text
    compare(page)
    page.click("#mode-decimal")
    assert "Rho Test 1 (High)" in panel.text_content()


def test_needs_attention(open_page):
    page = open_page()
    attention = page.locator("#needs-attention")
    expect(attention).to_contain_text("Eta Test 1 (High)")
    expect(attention).to_contain_text("Eta Test 1 (High, Preview)")
    families = texts(page, "#all-table tbody [data-c=family]")
    assert "Eta Test 1 (High)" in families and "Eta Test 1 (High, Preview)" in families
    assert "2" in page.locator("#status-attention").text_content()


def test_needs_attention_hidden_when_empty(open_page, ml):
    page = open_page(payload_for(ml, [model("Alpha Test 1 (High)", 40.0, 1.0)]))
    assert page.locator("#needs-attention").count() == 0


def test_stale_highlight(open_page, ml):
    page = open_page(payload_for(ml, checked=(NOW - timedelta(days=3)).isoformat()))
    age = page.locator("#status-age")
    expect(age).to_have_class("age stale")
    expect(age).to_have_text("Data is 3 days old")


def test_copy_refresh_command(open_page):
    page = open_page(init_script="""Object.defineProperty(navigator, 'clipboard', {configurable: true,
        value: {writeText: async (text) => { window.__copied = text; }}});""")
    page.click("#copy-refresh")
    expect(page.locator("#copy-refresh")).to_have_text("Copied")
    assert page.evaluate("window.__copied") == "model_ladder refresh"


def test_copy_refresh_fallback(open_page):
    page = open_page(init_script="""Object.defineProperty(navigator, 'clipboard', {configurable: true,
        value: {writeText: () => Promise.reject(new Error('denied'))}});""")
    page.click("#copy-refresh")
    expect(page.locator(".cmd")).to_have_text("model_ladder refresh")


def test_dark_theme_renders(open_page):
    light = open_page()
    dark = open_page(color_scheme="dark")
    style = "() => { const s = getComputedStyle(document.body); return [s.backgroundColor, s.color]; }"
    light_bg, light_ink = light.evaluate(style)
    dark_bg, dark_ink = dark.evaluate(style)
    assert light_bg != dark_bg
    assert dark_ink != light_ink
