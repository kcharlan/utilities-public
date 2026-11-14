"""The built page in offline Chromium, opened from file://. Synthetic data only."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pytest
from playwright.sync_api import expect, sync_playwright

from helpers import MAKER, fake_row, fake_source, indexed_ladder_models, ladder_models, model, snapshot

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
    return ml.build_payload({"aa": (snap, previous)}, CONFIG)


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

    def _open(payload=None, *, fragment="", color_scheme="light", width=1280, height=900, init_script=None,
              locale=None, timezone_id=None):
        payload = payload or payload_for(ml)
        path = tmp_path / f"page-{len(opened)}.html"
        path.write_bytes(ml.render_page(payload))
        context = chromium.new_context(viewport={"width": width, "height": height},
                                       color_scheme=color_scheme, service_workers="block", locale=locale, timezone_id=timezone_id)
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


def test_source_bar_lists_every_source(open_page):
    page = open_page()
    assert texts(page, ".sources button") == [
        "Artificial AnalysisChecked 2 hours ago",
        "AI Coding DailyNo data yet",
        "FrontierCode 2.0No data yet",
    ]
    expect(page.locator("#source-aa")).to_have_attribute("aria-pressed", "true")


def synthetic_payload(ml):
    payload = payload_for(ml)
    rows = [fake_row("Invented One", "high", {"test": 60, "category": 40}, {"time": 120, "tokens": 2000}, "Fictional Harness",
                     {"points": 1.234, "number": -2.345, "percent": .1234, "tested": "2026-10-02"}),
            fake_row("Invented One", "medium", {"test": 50, "category": 35}, {"time": 60, "tokens": 1000}, "Fictional Harness",
                     {"points": 3.456, "number": 4.567, "percent": .4567, "tested": "2026-10-03"}),
            fake_row("Invented Two", "high", {"test": 45, "category": 30}, {"time": 180, "tokens": 3000}, "Imaginary Harness"),
            fake_row("Invented Three", "high", {"test": 40, "category": 25}, {}, "Imaginary Harness")]
    rows.append(fake_row("Invented One", "max", {"test": 65, "category": 45}, {"time": 90, "tokens": 1500}, "Fictional Harness"))
    payload["sources"]["aicd"] = fake_source("aicd", rows, available=True,
        indexes=[{"key": "test", "label": "Test Index", "short": "test", "count": 5, "borrowed": False},
                 {"key": "category", "label": "Category", "short": "category", "count": 5, "borrowed": True}],
        axes=[{"key": "time", "label": "Time per prompt", "unit": "time", "per": "per prompt"},
              {"key": "tokens", "label": "Output tokens", "unit": "tokens", "per": "per prompt"}],
        default_axis="time", fetched_at="2026-11-05T10:00:00Z", last_checked="2026-11-05T11:00:00Z",
        published={"date": "2026-10-02", "note": "Invented update"},
        borrowed_notice={"time": "Overall time per prompt for {index}.", "tokens": "Overall output tokens for {index}."},
        extras=[{"path": "extras.points", "label": "Points", "kind": "points"},
                {"path": "extras.number", "label": "Number", "kind": "number2"},
                {"path": "extras.percent", "label": "Percent", "kind": "percent1"},
                {"path": "extras.tested", "label": "Tested", "kind": "date"}])
    return payload


def test_source_without_data(open_page):
    page = open_page()
    page.click("#source-fc")
    expect(page.locator("p.empty")).to_have_text("No data from FrontierCode 2.0 yet. Run model_ladder refresh --source fc.")
    expect(page.locator(".tabs")).to_have_count(0)


def test_failure_banner(open_page, ml):
    payload = synthetic_payload(ml)
    payload["sources"]["aicd"].update(last_attempt="2026-11-05T11:30:00Z", error="Invented failure")
    page = open_page(payload, locale="en-US", timezone_id="UTC")
    page.click("#source-aicd")
    expect(page.locator("#source-error")).to_have_text("The last fetch on Nov 5, 2026, 11:30 AM failed: Invented failure. This page shows data fetched Nov 5, 2026, 10:00 AM.")


def test_quiet_source_note(open_page, ml):
    page = open_page(synthetic_payload(ml), locale="en-US")
    page.click("#source-aicd")
    expect(page.locator("#source-quiet")).to_have_text("No new results from AI Coding Daily since Oct 2, 2026.")


def test_harness_replaces_creator(open_page, ml):
    page = open_page(synthetic_payload(ml))
    page.click("#source-aicd")
    assert "Harness" in page.locator("#all-table th[data-k=maker]").inner_text()
    assert texts(page, "#all-creator option")[0] == "All harnesses"


def test_axis_switch(open_page, ml):
    page = open_page(synthetic_payload(ml))
    page.click("#source-aicd")
    page.click("#axis-tokens")
    page.click("#axis-time")
    assert page.locator("#all-table th[data-k=cost]").inner_text().startswith("Time per prompt")
    assert texts(page, "#all-table tr:has(.pill.f) [data-c=family]") == ["Invented One", "Invented One"]


def test_extra_columns_sort(open_page, ml):
    page = open_page(synthetic_payload(ml), locale="en-US")
    page.click("#source-aicd")
    row = page.locator("#all-table tbody tr").filter(has_text="High").first
    for value in ["1.23", "−2.35", "12.3%", "Oct 2, 2026"]:
        assert value in row.inner_text()
    page.click("#all-table th[data-k='extras.points']")
    assert texts(page, "#all-table tbody tr [data-c='extras.points']") == ["1.23", "3.46", "", "", ""]


def test_date_only_values_keep_their_day(open_page, ml):
    page = open_page(synthetic_payload(ml), locale="en-US", timezone_id="America/Los_Angeles")
    page.click("#source-aicd")
    assert "Oct 2, 2026" in page.locator("#source-aicd").inner_text()
    assert "Oct 2, 2026" in page.locator("#all-table").inner_text()


@pytest.mark.parametrize("fields,expected,classes", [
    ({"available": False}, "No data yet", ["failed"]),
    ({"error": "failure", "last_attempt": "2026-11-05T11:30:00Z"},
     "Fetch failed Nov 5, 2026; showing Nov 5, 2026", ["failed"]),
    ({}, "Updated Oct 2, 2026, checked 1 hour ago", []),
    ({"published": None, "fetched_at": "2026-10-01T00:00:00Z"}, "Checked 1 hour ago", []),
    ({"published": None, "last_checked": "2026-11-03T00:00:00Z"}, "Checked 2 days ago", ["stale"]),
])
def test_source_freshness_lines(open_page, ml, fields, expected, classes):
    payload = synthetic_payload(ml)
    payload["sources"]["aicd"].update(fields)
    page = open_page(payload, locale="en-US", timezone_id="UTC")
    button = page.locator("#source-aicd")
    assert expected in button.inner_text()
    for name in ("failed", "stale"):
        assert (name in (button.get_attribute("class") or "").split()) == (name in classes)


def test_fc_version_banner(open_page, ml, monkeypatch, tmp_path):
    payload = synthetic_payload(ml)
    source = payload["sources"]["aicd"]
    spec = {**ml.SOURCE_SPECS["fc"], "indexes": source["indexes"], "axes": source["axes"],
            "default_axis": "time", "extras": source["extras"], "classify": lambda rows: rows}
    monkeypatch.setitem(ml.SOURCE_SPECS, "fc", spec)
    home = ml.ensure_runtime_home(tmp_path / "saved-fc")
    path = ml.save_snapshot(home, {"models": source["rows"], "index_version": "2.0", "current_version": "2.1", "rate_limit": {}}, NOW, "fc")
    payload["sources"]["fc"] = ml.build_source_entry("fc", ml.read_snapshot(path, "fc"), None, {}, CONFIG)
    page = open_page(payload)
    page.click("#source-fc")
    expect(page.locator("#source-version")).to_have_text("FrontierCode 2.1 is now current; this page shows 2.0.")
    payload["sources"]["fc"]["current_version"] = "2.0"
    same = open_page(payload)
    same.click("#source-fc")
    expect(same.locator("#source-version")).to_have_count(0)


def test_fc_source_end_to_end(open_page, ml, tmp_path):
    from test_source_fc import FC_FIXTURE
    result = {"models": ml.validate_frontiercode(FC_FIXTURE), "index_version": "2.0",
              "current_version": "2.1", "rate_limit": {}}
    path = ml.save_snapshot(tmp_path / "fc-home", result, NOW, "fc")
    saved = ml.read_snapshot(path, "fc")
    page = open_page(ml.build_payload({"aa": (snapshot(ladder_models()), None), "fc": (saved, None)}, CONFIG))
    page.click("#source-fc")
    assert "Score" in page.locator("#index-select").inner_text()
    assert "Harness" in page.locator("#all-table th[data-k=maker]").inner_text()
    assert "Flagged runs" in page.locator("#all-table").inner_text()
    assert "12.5%" in page.locator("#all-table").inner_text()
    assert "Cost per rollout" in page.locator("#all-table").inner_text()
    page.click("#axis-tokens")
    assert "Output tokens per rollout" in page.locator("#all-table").inner_text()
    assert "blocking criterion" in page.locator("#source-notice").inner_text()
    expect(page.locator("#source-version")).to_have_text("FrontierCode 2.1 is now current; this page shows 2.0.")


def test_aicd_source_end_to_end(open_page, ml, tmp_path):
    from test_source_aicd import AICD_FIXTURE
    result = ml.parse_ai_coding_daily(AICD_FIXTURE)
    path = ml.save_snapshot(tmp_path / "aicd-home", result, NOW, "aicd")
    saved = ml.read_snapshot(path, "aicd")
    page = open_page(ml.build_payload({"aa": (snapshot(ladder_models()), None), "aicd": (saved, None)}, CONFIG))
    page.click("#source-aicd")
    expect(page.locator("#axis-time")).to_have_attribute("aria-pressed", "true")
    page.select_option("#index-select", "laravel")
    assert "overall time per prompt" in page.locator("body").inner_text()
    expect(page.locator("svg .stair.borrowed")).to_be_visible()
    expect(page.locator("#all-table tr").filter(has_text="Low").locator(".pill.f")).to_be_visible()
    page.click("#axis-cost")
    assert "overall cost per prompt" in page.locator("body").inner_text().lower()
    assert "No cost" in page.locator("#all-table tr").filter(has_text="Low").inner_text()
    assert "Overall cost per prompt" in page.locator("#all-table th[data-k=cost]").inner_text()
    assert "Laravel" in page.locator("#all-table").inner_text()
    header = page.locator("#all-table th[data-k='scores.laravel']")
    header.click()
    expect(header).to_have_attribute("aria-sort", "ascending")


def test_aicd_changes_version_wording(open_page, ml):
    from test_source_aicd import AICD_FIXTURE
    result = ml.parse_ai_coding_daily(AICD_FIXTURE)
    old = {**result, "index_version": 800, "fetched_at": (NOW - timedelta(days=1)).isoformat()}
    new = {**result, "fetched_at": NOW.isoformat()}
    page = open_page(ml.build_payload({"aa": (snapshot(ladder_models()), None), "aicd": (new, old)}, CONFIG))
    page.click("#source-aicd")
    expect(page.locator("#changes .ver").first).to_have_text("AI Coding Daily changed its maximum from 800 to 900 points. Scores before and after are not comparable.")


def test_per_source_state(open_page, ml):
    page = open_page(synthetic_payload(ml))
    page.click("#source-aicd")
    page.click("#axis-tokens")
    page.select_option("#index-select", "category")
    page.locator("#all-table input[type=checkbox]").first.check()
    page.click("#source-aa")
    page.click("#source-aicd")
    expect(page.locator("#axis-tokens")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#index-select")).to_have_value("category")
    assert page.locator("#all-table input[type=checkbox]:checked").count() > 0


@pytest.mark.parametrize("storage", [False, True])
def test_old_state_migrates_to_aa(open_page, storage):
    old = {"view": "all", "index": "intelligence", "keys": [], "hi": "high", "lo": "medium", "sorts": {}, "mode": "decimal"}
    script = f"localStorage.setItem('model_ladder.state', {json.dumps(json.dumps(old))})" if storage else None
    fragment = "" if storage else "#" + quote(json.dumps(old))
    page = open_page(fragment=fragment, init_script=script)
    state = json.loads(page.evaluate("localStorage.getItem('model_ladder.state')"))
    assert state["source"] == "aa"
    assert state["per"]["aa"]["hi"] == "high"
    assert state["mode"] == "decimal"


@pytest.mark.parametrize("source", ["constructor", "__proto__", "invented-unknown", None, []])
@pytest.mark.parametrize("storage", [False, True])
def test_unknown_source_restores_aa(open_page, source, storage):
    state = {"view": "all", "mode": "whole", "source": source, "per": {}}
    script = f"localStorage.setItem('model_ladder.state', {json.dumps(json.dumps(state))})" if storage else None
    fragment = "" if storage else "#" + quote(json.dumps(state))
    page = open_page(fragment=fragment, init_script=script)
    expect(page.locator("#source-aa")).to_have_attribute("aria-pressed", "true")
    assert json.loads(page.evaluate("localStorage.getItem('model_ladder.state')"))["source"] == "aa"


@pytest.mark.parametrize("axis,header,value,unit,tick,up,down,per_point,note,finding", [
    ("time", "Time per prompt", "2:00", "time", "0:50", "+1:00", "−1:00", "0:06", "takes no more time", "0:02 per point"),
    ("tokens", "Output tokens", "2k tokens", "output tokens", "1k tokens", "+1k tokens", "−1k tokens", "100 tokens", "uses no more output tokens", "33 tokens per point"),
])
def test_axis_strings_follow_axis(open_page, ml, axis, header, value, unit, tick, up, down, per_point, note, finding):
    payload = synthetic_payload(ml)
    payload["sources"]["aicd"]["changes"] = {"from": "2026-11-01T00:00:00Z", "to": "2026-11-05T10:00:00Z",
        "version": None, "added": [], "removed": [], "maxima": {}, "changed": [{"slug": "invented-one-high", "name": "Invented One (high)",
        "scores": {"test": [60, 60], "category": [40, 40]}, "axes": {"time": [60, 120], "tokens": [1000, 2000]}, "extras": {}},
        {"slug": "invented-three-high", "name": "Invented Three (high)", "scores": {"test": [40, 40], "category": [25, 25]},
         "axes": {"time": [None, 60], "tokens": [None, 1000]}, "extras": {}}]}
    page = open_page(payload)
    page.click("#source-aicd")
    page.click("#axis-" + axis)
    assert header in page.locator("#all-table th[data-k=cost]").inner_text()
    assert value in page.locator("#all-table").inner_text()
    assert f"Invented One High: 60.0, {value}" in page.locator("svg circle title").all_text_contents()
    assert tick in page.locator("svg[role=img] text").all_text_contents()
    assert header.lower() in page.locator("svg[role=img]").first.get_attribute("aria-label").lower()
    assert unit in page.locator("svg[role=img]").first.text_content().lower()
    assert "Dominated" in page.locator("#all-table").inner_text()
    assert "No " + unit in page.locator("#all-table").inner_text()
    assert "$" not in page.locator("#all-table").inner_text()
    page.locator("#changes summary").click()
    changes = page.locator("#changes").inner_text()
    assert ("time 1:00 to 2:00" if axis == "time" else "output tokens 1k tokens to 2k tokens") in changes
    assert ("time no time to 1:00" if axis == "time" else "output tokens no output tokens to 1k tokens") in changes
    assert "$" not in changes
    page.locator("#all-table input[type=checkbox]").first.check()
    page.locator("#all-table tr").filter(has_text="Invented Three").locator("input[type=checkbox]").check()
    page.click("#tab-compare")
    assert value in texts(page, "#ladder-table td[data-c=cost]")
    assert "$" not in page.locator("#ladder-table").inner_text()
    assert ("1 selected row has no time and is left out." if axis == "time" else "1 selected row has no output tokens and is left out.") in page.locator("#pareto p.note").inner_text()
    assert header in page.locator("#steps-table").inner_text()
    assert "$" not in page.locator("#steps-table").inner_text()
    assert unit in page.locator("#steps p.note").inner_text().lower()
    assert note in page.locator("#steps-table").inner_text()
    assert up in texts(page, "#steps-table td[data-c='up.cost']")
    assert down in texts(page, "#steps-table td[data-c='down.cost']")
    assert per_point in texts(page, "#steps-table td[data-c='up.perPoint']")
    assert "60.0" in page.locator("#steps-table .raw").all_text_contents()
    assert ("Time per point" if axis == "time" else "Output tokens per point") in page.locator("#steps-table").inner_text()
    assert "$" not in page.locator("#pareto-table").inner_text()
    assert finding in page.locator("#findings").inner_text()
    assert ("Least time per point" if axis == "time" else "Fewest output tokens per point") in page.locator("#findings").inner_text()
    assert ("0:30 less per prompt" if axis == "time" else "500 tokens less per prompt") in page.locator("#pareto-table .reason").inner_text()
    page.select_option("#index-select", "category")
    assert page.locator("#cost-notice").inner_text() == ("Overall time per prompt for Category." if axis == "time" else "Overall output tokens for Category.")
    assert page.locator("#say .note").inner_text() == ("Values in these sentences are overall time per prompt, including time per point." if axis == "time" else "Values in these sentences are overall output tokens, including output tokens per point.")


@pytest.mark.parametrize("axis,label", [("time", "time per prompt"), ("tokens", "output tokens")])
def test_missing_axis_empty_states(open_page, ml, axis, label):
    payload = synthetic_payload(ml)
    for row in payload["sources"]["aicd"]["rows"]:
        row["axes"][axis] = None
    page = open_page(payload)
    page.click("#source-aicd")
    page.click("#axis-" + axis)
    expect(page.locator(".view p.empty")).to_have_text("No scored model has a " + label + ".")
    page.locator("#all-table input[type=checkbox]").first.check()
    page.click("#tab-compare")
    expect(page.locator("#pareto p.empty")).to_have_text("None of the selected rows has a " + label + ".")


def test_changes_extras_and_maxima(open_page, ml, monkeypatch, tmp_path):
    payload = synthetic_payload(ml)
    source = payload["sources"]["aicd"]
    spec = {**ml.SOURCE_SPECS["aicd"], "indexes": source["indexes"], "axes": source["axes"],
            "default_axis": "time", "extras": source["extras"], "classify": lambda rows: rows, "notice": lambda rows: None}
    monkeypatch.setitem(ml.SOURCE_SPECS, "aicd", spec)
    home = ml.ensure_runtime_home(tmp_path / "saved-aicd")
    rows = source["rows"]
    old_rows = [{**row, "extras": {**row["extras"], "points": 1.234}} if row is rows[0] else row for row in rows]
    new_rows = [{**row, "extras": {**row["extras"], "points": 2.345}} if row is rows[0] else row for row in rows]
    old_path = ml.save_snapshot(home, {"models": old_rows, "index_version": 1, "rate_limit": {}, "index_maxima": {"test": 100}}, NOW - timedelta(days=2), "aicd")
    new_path = ml.save_snapshot(home, {"models": new_rows, "index_version": 1, "rate_limit": {}, "index_maxima": {"test": 100}}, NOW - timedelta(days=1), "aicd")
    newest = ml.read_snapshot(new_path, "aicd")
    previous = ml._last_real_change([old_path], newest, "aicd")
    assert previous is not None
    payload["sources"]["aicd"] = ml.build_source_entry("aicd", newest, previous, {}, CONFIG)
    page = open_page(payload)
    page.click("#source-aicd")
    if not page.locator("#changes").get_attribute("open"):
        page.locator("#changes summary").click()
    text = page.locator("#changes").inner_text()
    assert "Points" in text and "1.23" in text and "2.35" in text
    scale_path = ml.save_snapshot(home, {"models": new_rows, "index_version": 1, "rate_limit": {}, "index_maxima": {"test": 200}}, NOW, "aicd")
    scale = ml.read_snapshot(scale_path, "aicd")
    scale_previous = ml._last_real_change([new_path], scale, "aicd")
    assert scale_previous is not None
    payload["sources"]["aicd"] = ml.build_source_entry("aicd", scale, scale_previous, {}, CONFIG)
    scale_page = open_page(payload)
    scale_page.click("#source-aicd")
    scale_page.locator("#changes summary").click()
    text = scale_page.locator("#changes").inner_text()
    assert "Test Index" in text and "100" in text and "200" in text and "not comparable" in text


def test_index_selector_and_borrowed_costs(open_page, ml):
    page = open_page(payload_for(ml, indexed_ladder_models()))
    assert texts(page, "#index-select option") == ["Intelligence Index (12)", "Finance and accounting (8)"]
    expect(page.locator("#index-select")).to_have_value("intelligence")
    assert page.locator("#cost-notice, td.borrowed, path.stair.borrowed").count() == 0
    page.select_option("#all-creator", "Sample Works")
    page.select_option("#index-select", "finance")
    assert page.locator("#all-creator").input_value() == ""
    expect(page.locator("#cost-notice")).to_have_text("Costs here are from the Intelligence Index run. Artificial Analysis publishes no cost for the Finance and accounting index, so every cost, frontier and cost per point on this page pairs these scores with that cost.")
    assert "the Finance and accounting index" in page.locator(".sub").inner_text()
    assert page.locator("#all-table th[data-k=cost]").inner_text().startswith("Overall cost per task")
    assert page.locator("#all-table td[data-c=cost]:not(.borrowed), td[data-c=score].borrowed").count() == 0
    assert page.locator("path.stair.borrowed").count() == 1
    expect(page.locator("#all-table tr:has(.pill.f)")).to_have_count(4)
    assert texts(page, "#all-table tr:has(.pill.f) [data-c=family]") == ["Beta Test 1"] * 4
    alpha_and_beta(page)
    assert page.locator("#steps-table td[data-c='up.cost'].borrowed").count() > 0
    assert page.locator("#say .note").inner_text() == "Costs in these sentences are Intelligence Index costs."
    page.reload()
    assert page.locator("#index-select").input_value() == "finance"
    page.evaluate("history.replaceState(null, '', location.pathname)")
    page.reload()
    assert page.locator("#index-select").input_value() == "finance"
    page.goto(page.url.split('#')[0] + '#' + quote(json.dumps({"index": "unknown"})))
    expect(page.locator("#index-select")).to_have_value("intelligence")


def test_default_index_remains_available_when_only_domain_scores_exist(open_page, ml):
    payload = payload_for(ml, [model("Synthetic Finance (High)", scores={"finance": 42})])
    for fragment in ("", "#" + quote(json.dumps({"index": "healthcare"}))):
        page = open_page(payload, fragment=fragment)
        assert texts(page, "#index-select option") == ["Intelligence Index (0)", "Finance and accounting (1)"]
        assert page.locator("#index-select").input_value() == "intelligence"
        assert "Intelligence Index" in page.locator(".sub").inner_text()
        assert page.locator("#all-table tbody tr").count() == 0
        page.select_option("#index-select", "finance")
        assert page.locator("#index-select").input_value() == "finance"
        assert page.locator("#all-table tbody tr").count() == 1


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


def test_picker_focuses_search_on_open(open_page):
    """Opening the picker must put the cursor in the search box so typing works at once."""
    page = open_page()
    compare(page)
    page.click("#add-model")
    expect(page.locator("#model-search")).to_be_focused()
    page.keyboard.type("beta")
    page.keyboard.press("Enter")
    assert texts(page, "#chips .chip .fam") == ["Beta Test 1"]


def test_pareto_opens_highest_score_first(open_page):
    """Capability descending is the default order; cost breaks ties, so a dominated tie follows its frontier row."""
    page = open_page()
    alpha_and_beta(page)
    labels = [r["label"] for r in pareto_rows(page)]
    assert labels[0] == "Alpha Test 1 Max"
    assert labels.index("Alpha Test 1 High") + 1 == labels.index("Alpha Test 1 XHigh")
    assert labels[-1] == "Beta Test 1 Medium"


def test_whole_point_pareto(open_page):
    page = open_page()
    alpha_and_beta(page)
    rows = pareto_rows(page)
    # The table opens highest score first; FRONTIER is listed in cost order, which is the reverse.
    assert [r["label"] for r in rows if r["status"] == "Frontier"] == FRONTIER[::-1]
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


def test_unscored_selection_survives_index_switches(open_page, ml):
    models = indexed_ladder_models()
    models[0]["evaluations"]["artificial_analysis_finance_and_accounting_index"] = None
    models.append(model("Beta Test 1 (Low)", scores={"finance": 44}))
    page = open_page(payload_for(ml, models))
    compare(page)
    for name in ("alpha", "beta", "gamma"):
        add(page, name)
    page.keyboard.press("Escape")
    colors = page.locator("#chips .dot").evaluate_all("els => els.map(e => getComputedStyle(e).backgroundColor)")
    page.select_option("#index-select", "finance")
    gamma = page.locator("#chips .unscored")
    expect(gamma).to_contain_text("Gamma Test 1 has no Finance score")
    assert gamma.locator("button").count() == 1
    assert page.locator("#chips .dot").evaluate_all("els => els.map(e => getComputedStyle(e).backgroundColor)") == colors
    page.click("#add-model")
    assert "Gamma Test 1" not in page.locator("#model-list").inner_text()
    page.keyboard.press("Escape")
    assert "Gamma Test 1" not in page.locator("#ladder").inner_text()
    for section in ("#ladder", "#steps", "#pareto", "#say"):
        assert "Gamma Test 1" not in page.locator(section).text_content()
    expect(page.locator("#unscored-note")).to_have_text("Not scored in Finance and accounting: Alpha Test 1 Medium, Gamma Test 1 (all levels).")
    assert page.locator("#ladder-table td.none", has_text="No score").count() == 1
    assert "Alpha Test 1 Medium" not in page.locator("#pareto").inner_text()
    assert page.locator("#steps-table tr:has-text('Alpha Test 1'):has-text('Medium')").count() == 0
    page.select_option("#effort-lo", "high")
    expect(page.locator("#unscored-note")).to_have_text("Not scored in Finance and accounting: Gamma Test 1 (all levels).")
    page.select_option("#effort-lo", "low")
    page.select_option("#effort-hi", "medium")
    page.select_option("#effort-lo", "medium")
    assert page.locator("#ladder-table td.none", has_text="No score").count() == 1
    page.select_option("#effort-hi", "max")
    page.select_option("#effort-lo", "low")
    page.select_option("#index-select", "intelligence")
    expect(page.locator("#unscored-note")).to_have_text("Not scored in Intelligence Index: Beta Test 1 Low.")
    assert page.locator("#chips .dot").evaluate_all("els => els.map(e => getComputedStyle(e).backgroundColor)") == colors
    page.select_option("#index-select", "finance")
    page.locator("#chips button[aria-label='Remove Alpha Test 1']").click()
    page.locator("#chips button[aria-label='Remove Beta Test 1']").click()
    expect(page.locator(".empty.box")).to_have_text("None of the selected models has a Finance score.")


def test_ladder_table_fills_the_row_when_the_chart_is_hidden(open_page, ml):
    models = indexed_ladder_models()
    models[0]["evaluations"]["artificial_analysis_finance_and_accounting_index"] = None
    page = open_page(payload_for(ml, models))
    compare(page)
    add(page, "alpha")
    page.keyboard.press("Escape")
    page.select_option("#index-select", "finance")
    expect(page.locator("#ladder svg")).to_have_count(1)
    page.select_option("#effort-hi", "medium")
    page.select_option("#effort-lo", "medium")
    expect(page.locator("#ladder svg")).to_have_count(0)
    assert page.locator("#ladder-table td.none", has_text="No score").count() == 1
    widths = page.evaluate("""() => [document.querySelector('#ladder-table').closest('.box').getBoundingClientRect().width,
        document.querySelector('#ladder').getBoundingClientRect().width]""")
    assert widths[0] == widths[1]


def test_changes_use_selected_index_for_disappearing_score(open_page, ml):
    current = indexed_ladder_models()
    previous = indexed_ladder_models()
    current[0]["evaluations"]["artificial_analysis_finance_and_accounting_index"] = None
    page = open_page(payload_for(ml, current, previous=snapshot(previous)))
    page.locator("#changes summary").click()
    assert "Alpha Test 1 (Medium)" not in page.locator("#changes").inner_text()
    page.select_option("#index-select", "finance")
    expect(page.locator("#changes")).to_contain_text("Alpha Test 1 (Medium): score 30 to no score")


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


def test_copy_refresh_command(open_page, ml):
    page = open_page(synthetic_payload(ml), init_script="""Object.defineProperty(navigator, 'clipboard', {configurable: true,
        value: {writeText: async (text) => { window.__copied = text; }}});""")
    page.click("#source-aicd")
    page.click("#copy-refresh")
    expect(page.locator("#copy-refresh")).to_have_text("Copied")
    assert page.evaluate("window.__copied") == "model_ladder refresh --source aicd"


def test_copy_refresh_fallback(open_page, ml):
    page = open_page(synthetic_payload(ml), init_script="""Object.defineProperty(navigator, 'clipboard', {configurable: true,
        value: {writeText: () => Promise.reject(new Error('denied'))}});""")
    page.click("#source-aicd")
    page.click("#copy-refresh")
    expect(page.locator(".cmd")).to_have_text("model_ladder refresh --source aicd")


def test_dark_theme_renders(open_page):
    light = open_page()
    dark = open_page(color_scheme="dark")
    style = "() => { const s = getComputedStyle(document.body); return [s.backgroundColor, s.color]; }"
    light_bg, light_ink = light.evaluate(style)
    dark_bg, dark_ink = dark.evaluate(style)
    assert light_bg != dark_bg
    assert dark_ink != light_ink
