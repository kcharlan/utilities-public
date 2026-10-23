from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlsplit

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Route, expect, sync_playwright

from model_sentinel.browse import server as server_module
from model_sentinel.browse.readonly import open_readonly
from model_sentinel.browse.server import make_server
from tests.browse_fixtures import (
    ENDPOINT_PROVIDER,
    EXAMPLE_PROVIDER,
    OTHER_PROVIDER,
    UNSENT_ERROR_MESSAGE,
    FixtureFacts,
    browse_context,
    browse_settings,
    build_fixture_db,
    build_hosts_fixture_db,
    mark_failed_list_unsent,
)


@contextmanager
def _serve(database_path: Path, facts: FixtureFacts):
    db = open_readonly(database_path)
    server = make_server(browse_context(db), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, facts
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        db.close_all()


@pytest.fixture(scope="module")
def smoke_server(tmp_path_factory: pytest.TempPathFactory):
    database_path = tmp_path_factory.mktemp("browse-smoke") / "fixture.db"
    facts = build_fixture_db(database_path)
    with _serve(database_path, facts) as served:
        yield served


@pytest.fixture(scope="module")
def endpoint_server(tmp_path_factory: pytest.TempPathFactory):
    """A browse server over the fixture history *with* saved endpoint captures."""
    database_path = tmp_path_factory.mktemp("browse-endpoint-smoke") / "fixture.db"
    facts = build_fixture_db(database_path, with_endpoints=True)
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()
    with _serve(database_path, facts) as served:
        yield served
    # The browser only reads endpoint history.
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == before


@pytest.fixture(scope="module")
def hosts_server(tmp_path_factory: pytest.TempPathFactory, request):
    database_path = tmp_path_factory.mktemp("browse-hosts-smoke") / "fixture.db"
    variant = getattr(request, "param", None)
    facts = build_hosts_fixture_db(database_path, with_output_prices=variant == "output_prices", with_many_lists=variant == "many_lists", with_spread_cases=variant == "spread_cases")
    if variant and variant not in ("output_prices", "many_lists", "spread_cases"):
        with sqlite3.connect(database_path) as connection:
            if variant == "legacy":
                tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'endpoint_%'").fetchall()
                for (table,) in tables:
                    connection.execute(f'DROP TABLE "{table}"')
            elif variant == "no_telemetry":
                connection.execute("DROP TABLE endpoint_telemetry")
                connection.execute("DROP TABLE endpoint_telemetry_captures")
            elif variant == "capture_order":
                connection.execute("UPDATE scrapes SET completed_at='2026-10-01T12:00:00+00:00' WHERE scrape_id=?", (facts.scrapes["first"],))
            elif variant == "dossier_samples":
                connection.execute("UPDATE endpoint_telemetry SET uptime_1d=0, uptime_30m=99.9999 WHERE capture_id=? AND list_path=? AND endpoint_key='alpha-fast#0'", (facts.captures["first"], facts.host_grouping_and_ties["path"]))
                connection.execute("DELETE FROM endpoint_telemetry WHERE capture_id=? AND list_path=? AND endpoint_key='alpha-cheap#0'", (facts.captures["first"], facts.host_grouping_and_ties["path"]))
            else:
                raise AssertionError(f"Unknown Hosts fixture variant: {variant}")
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()
    with _serve(database_path, facts) as served:
        yield served
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == before


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def _same_origin(url: str, origin: str) -> bool:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" == origin


@contextmanager
def _guarded_page(context: BrowserContext, origin: str | None = None) -> Iterator[Page]:
    """A page that fails on page errors, unexpected console errors and, given
    `origin`, any request outside that origin (which is also aborted)."""
    outside: list[str] = []
    if origin is not None:
        context.route(
            "**/*",
            lambda route: route.continue_()
            if _same_origin(route.request.url, origin)
            else route.abort(),
        )
        context.on(
            "request",
            lambda request: None
            if _same_origin(request.url, origin)
            else outside.append(request.url),
        )
    instance = context.new_page()
    page_errors: list[str] = []
    console_errors: list[str] = []
    instance.on("pageerror", lambda error: page_errors.append(str(error)))
    instance.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    instance._allowed_console_errors = []
    yield instance
    assert page_errors == []
    assert [
        error
        for error in console_errors
        if not any(allowed in error for allowed in instance._allowed_console_errors)
    ] == []
    assert outside == []


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context()
    try:
        with _guarded_page(context) as instance:
            yield instance
    finally:
        context.close()


@pytest.fixture
def hosts_page(browser: Browser, hosts_server) -> Iterator[Page]:
    context = browser.new_context()
    try:
        with _guarded_page(context, _origin(hosts_server)) as instance:
            yield instance
    finally:
        context.close()


def _hosts_fragment(facts, **changes):
    values = {"view": "hosts", "providers": facts.provider_id, "hasof": facts.scrapes["first"], **changes}
    return "#" + "&".join(f"{key}={quote(str(value), safe=',')}" for key, value in values.items())


def test_hosts_toolbar_menus_do_not_activate_on_open_and_switch_directly(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    before = hosts_page.evaluate("location.hash")
    hosts_page.get_by_role("button", name="Precision condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name="Precision", exact=True)
    expect(dialog.get_by_role("checkbox", name="fp8", exact=True)).to_be_checked()
    assert hosts_page.evaluate("location.hash") == before
    hosts_page.get_by_role("button", name="Tier condition", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(hosts_page.get_by_role("dialog", name="Tier", exact=True)).to_be_visible()
    assert hosts_page.evaluate("location.hash") == before


def test_hosts_empty_results_keep_toolbar_sort_summary_and_clear(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hsort="a:model", quantset="1"))
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_have_count(0)
    summary = hosts_page.locator(".hosts-toolbar .hosts-summary")
    expect(summary.locator(".hosts-sort-summary")).to_contain_text("Model ▲")
    assert summary.evaluate("""node => {
        const sort = node.querySelector('.hosts-sort-summary');
        const excluded = node.querySelector('label');
        const count = node.lastElementChild;
        return Boolean(sort.compareDocumentPosition(excluded) & Node.DOCUMENT_POSITION_FOLLOWING)
            && Boolean(excluded.compareDocumentPosition(count) & Node.DOCUMENT_POSITION_FOLLOWING);
    }""")
    expect(summary).to_contain_text("0 of 135 endpoints · 0 models")
    summary.get_by_role("button", name="Clear sort", exact=True).click()
    expect(hosts_page).not_to_have_url(re.compile("hsort="))
    expect(summary.locator(".hosts-sort-summary")).to_have_count(0)
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_have_count(0)
    hosts_page.get_by_label("Show excluded", exact=True).check()
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()


def test_hosts_history_drawer_close_restores_matching_list_after_other_origin(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    table = hosts_page.get_by_role("table", name="Host comparison")
    shared = table.get_by_role("button", name="synthetic-response-shared", exact=True)
    exact = table.get_by_role("button", name="synthetic-response-exact", exact=True)
    for button in (shared, exact):
        button.click()
        hosts_page.get_by_role("button", name="Close endpoint drawer").click()
        expect(button).to_be_focused()
    hosts_page.go_back()
    expect(hosts_page.get_by_role("dialog", name="synthetic-response-exact", exact=True)).to_be_visible()
    hosts_page.go_back()
    expect(hosts_page.get_by_role("dialog")).to_have_count(0)
    hosts_page.go_back()
    expect(hosts_page.get_by_role("dialog", name="synthetic-response-shared", exact=True)).to_be_visible()
    hosts_page.get_by_role("button", name="Close endpoint drawer").click()
    expect(shared).to_be_focused()


@pytest.mark.parametrize("query", ["", "synthetic-no-matching-model"])
def test_hosts_search_empty_suggestions_omit_active_descendant(hosts_page, hosts_server, query):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    field = hosts_page.get_by_role("combobox", name="Search models", exact=True)
    field.fill(query)
    for key in ("ArrowDown", "ArrowUp", "ArrowDown"):
        field.press(key)
        expect(field).to_have_attribute("aria-expanded", "false")
        expect(hosts_page.locator(".hosts-search-results [role=option]")).to_have_count(0)
        expect(field).not_to_have_attribute("aria-activedescendant")
    field.fill("hosts-sha")
    field.press("ArrowDown")
    expect(field).to_have_attribute("aria-activedescendant", "host-search-0")
    expect(hosts_page.locator("#host-search-0")).to_have_attribute("aria-selected", "true")
    field.press("Enter")
    expect(field).to_have_value("fake-org/hosts-shared")


def test_hosts_sort_headers_stack_history_and_ranking(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    table = hosts_page.get_by_role("table", name="Host comparison")
    model = table.get_by_role("columnheader").filter(has=hosts_page.get_by_role("button", name="Model", exact=True))
    model.get_by_role("button").click()
    expect(model).to_have_attribute("aria-sort", "ascending")
    names = table.locator("tbody tr th button").all_text_contents()
    assert names == sorted(names)
    table.get_by_role("button", name="Hosts", exact=True).click()
    expect(hosts_page.locator(".hosts-sort-summary")).to_contain_text("Sorted by Model ▲ › Hosts ▲")
    expect(table.locator("thead [aria-sort]")).to_have_count(1)
    model.get_by_role("button").click()
    expect(model).to_have_attribute("aria-sort", "descending")
    names = table.locator("tbody tr th button").all_text_contents()
    assert names == sorted(names, reverse=True)
    hosts_page.reload()
    expect(model).to_have_attribute("aria-sort", "descending")
    model.get_by_role("button").click()
    expect(hosts_page.locator(".hosts-sort-summary")).to_contain_text("Hosts ▲")
    expect(model).not_to_have_attribute("aria-sort", "descending")
    hosts_page.go_back()
    expect(model).to_have_attribute("aria-sort", "descending")
    hosts_page.go_forward()
    expect(hosts_page.locator(".hosts-sort-summary")).to_contain_text("Hosts ▲")
    model.get_by_role("button").click()
    expect(hosts_page.locator(".hosts-sort-summary")).to_contain_text("Sorted by Hosts ▲ › Model ▲")
    counts = table.locator("tbody tr").evaluate_all("rows=>rows.map(row=>Number(row.lastElementChild.textContent))")
    assert counts == sorted(counts)
    names = table.locator("tbody tr th button").all_text_contents()
    for count in set(counts):
        tied = [name for name, value in zip(names, counts) if value == count]
        assert tied == sorted(tied)
    hosts_page.get_by_label("Ranking", exact=True).select_option("context")
    expect(hosts_page.locator(".hosts-sort-summary")).to_contain_text("Sorted by Hosts ▲ › Model ▲")
    hosts_page.locator(".hosts-sort-summary").get_by_role("button", name="Clear sort", exact=True).click()
    expect(table.locator("thead [aria-sort]")).to_have_count(0)


def test_hosts_hidden_sorts_canonicalization_and_drawer_history(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    history_length = hosts_page.evaluate("history.length")
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts="Synthetic Alpha", hsort="a:context,d:context,bad,a:host:Synthetic Bogus,a:hosts", dsort="d:host,a:price:missing"))
    table = hosts_page.get_by_role("table", name="Host comparison")
    expect(table.get_by_role("columnheader", name=re.compile("Context"))).to_have_attribute("aria-sort", "ascending")
    expect(hosts_page).not_to_have_url(re.compile("Bogus|bad|missing|d%3Acontext"))
    assert hosts_page.evaluate("history.length") == history_length + 1
    hosts_page.get_by_role("button", name="Remove compared Synthetic Alpha", exact=True).click()
    expect(hosts_page.locator(".hosts-sort-summary")).to_contain_text("Hosts ▲")
    expect(hosts_page.locator(".hosts-sort-summary")).not_to_contain_text("Context")
    hosts_page.go_back()
    expect(table.get_by_role("columnheader", name=re.compile("Context"))).to_have_attribute("aria-sort", "ascending")
    table.get_by_role("button", name="synthetic-response-shared", exact=True).click()
    drawer = hosts_page.get_by_role("dialog", name="synthetic-response-shared", exact=True)
    host = drawer.get_by_role("columnheader", name=re.compile("Host"))
    expect(host).to_have_attribute("aria-sort", "descending")
    assert drawer.locator("tbody tr th").all_text_contents() == ["Synthetic Gamma", "Synthetic Beta", "Synthetic Alpha", "Synthetic Alpha"]
    host.get_by_role("button").click()
    expect(host).not_to_have_attribute("aria-sort", "descending")
    drawer.get_by_role("columnheader", name="Context", exact=True).get_by_role("button").click()
    expect(drawer.locator(".drawer-sort-summary")).to_contain_text("Context ▲")
    drawer.get_by_role("button", name="Close endpoint drawer").click()
    expect(drawer).to_have_count(0)
    hosts_page.go_back()
    expect(drawer).to_be_visible()
    expect(drawer.get_by_role("columnheader", name=re.compile("Context"))).to_have_attribute("aria-sort", "ascending")


def test_hosts_drawer_sort_secondary_groups_exact_missing_and_reopen(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, healthy="1", showx="1", hlist=facts.host_grouping_and_ties["path"], dsort="d:host,a:context"))
    drawer = hosts_page.get_by_role("dialog", name="synthetic-response-shared", exact=True)
    rows = drawer.locator('tbody tr:has(> th[scope="row"])')
    assert rows.locator("th").all_text_contents() == ["Synthetic Beta", "Synthetic Alpha", "Synthetic Alpha", "Synthetic Gamma"]
    tags = lambda: rows.locator("td:nth-child(2)").evaluate_all("cells=>cells.map(cell=>cell.firstChild.textContent)")
    assert tags() == ["beta", "alpha-cheap", "alpha-fast", "gamma"]
    expect(rows.last).to_have_class("is-excluded")
    expect(drawer.locator("thead [aria-sort]")).to_have_count(1)
    expect(drawer.get_by_role("columnheader", name="Context", exact=True)).not_to_have_attribute("aria-sort", "ascending")
    drawer.get_by_role("button", name="Context", exact=True).click()
    expect(drawer.locator(".drawer-sort-summary")).to_contain_text("Sorted by Host ▼ › Context ▼")
    assert tags() == ["beta", "alpha-fast", "alpha-cheap", "gamma"]
    drawer.locator(".drawer-sort-summary").get_by_role("button", name="Clear sort", exact=True).click()
    expect(drawer.locator("thead [aria-sort]")).to_have_count(0)
    expect(drawer.locator(".drawer-sort-summary")).to_contain_text("Click again to reverse, a third time to remove it.")
    _switch_hash(hosts_page, _hosts_fragment(facts, hlist=facts.host_exact_prices["path"], dsort="d:price:pricing.prompt"))
    drawer = hosts_page.get_by_role("dialog", name="synthetic-response-exact", exact=True)
    rows = drawer.locator('tbody tr:has(> th[scope="row"])')
    assert tags() == ["exact-high", "exact-low", "price-missing"]
    drawer.get_by_role("button", name="Close endpoint drawer").click()
    hosts_page.get_by_role("table", name="Host comparison").get_by_role("button", name="synthetic-response-exact", exact=True).click()
    expect(drawer.locator(".drawer-sort-summary")).to_contain_text("▼")
    hosts_page.reload()
    expect(drawer).to_be_visible()
    assert tags() == ["exact-high", "exact-low", "price-missing"]


def test_hosts_compared_host_sort_exact_values_missing_and_hidden_restore(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Beta", hsort="a:host:Synthetic Alpha"))
    table = hosts_page.get_by_role("table", name="Host comparison")
    names = lambda: table.locator("tbody tr th button").all_text_contents()
    expect(table.get_by_role("columnheader", name="Synthetic Alpha", exact=True)).to_have_attribute("aria-sort", "ascending")
    assert names() == ["synthetic-response-shared", "synthetic-response-exact", facts.host_list_identity["missing_id_path"]]
    table.get_by_role("button", name="Synthetic Alpha", exact=True).click()
    expect(table.get_by_role("columnheader", name="Synthetic Alpha", exact=True)).to_have_attribute("aria-sort", "descending")
    assert names() == ["synthetic-response-exact", "synthetic-response-shared", facts.host_list_identity["missing_id_path"]]
    hosts_page.get_by_role("button", name="Remove compared Synthetic Alpha", exact=True).click()
    expect(table.locator("thead [aria-sort]")).to_have_count(0)
    expect(hosts_page.locator(".hosts-sort-summary")).to_have_count(0)
    expect(hosts_page).to_have_url(re.compile("hsort=d%3Ahost%3ASynthetic%20Alpha"))
    hosts_page.go_back()
    expect(table.get_by_role("columnheader", name="Synthetic Alpha", exact=True)).to_have_attribute("aria-sort", "descending")
    assert names() == ["synthetic-response-exact", "synthetic-response-shared", facts.host_list_identity["missing_id_path"]]


@pytest.mark.parametrize("selection", ["enter", "pointer"])
def test_hosts_search_suggestion_consumes_pending_draft(hosts_page, hosts_server, selection):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    field = hosts_page.get_by_role("combobox", name="Search models", exact=True)
    field.fill("hosts-sha")
    if selection == "enter":
        hosts_page.keyboard.press("ArrowDown")
        hosts_page.keyboard.press("Enter")
    else:
        expect(hosts_page.get_by_role("listbox", name="Model suggestions", exact=True)).to_be_visible()
        hosts_page.get_by_role("option", name="fake-org/hosts-shared", exact=True).click()
    chosen = field.input_value()
    assert "hosts-shared" in chosen
    hosts_page.get_by_label("Ranking", exact=True).focus()
    hosts_page.wait_for_timeout(350)
    expect(field).to_have_value(chosen)
    assert "hq=" + quote(chosen, safe="") in hosts_page.evaluate("location.hash")


def test_hosts_search_escape_clears_active_option_and_keeps_input_focus(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    field = hosts_page.get_by_role("combobox", name="Search models", exact=True)
    field.fill("hosts-sha")
    field.press("ArrowDown")
    expect(field).to_have_attribute("aria-activedescendant", "host-search-0")
    field.press("Escape")
    expect(field).to_be_focused()
    expect(field).to_have_attribute("aria-expanded", "false")
    expect(field).not_to_have_attribute("aria-activedescendant")
    expect(hosts_page.get_by_role("listbox", name="Model suggestions", exact=True)).to_have_count(0)


def test_hosts_search_initial_arrow_up_selects_last_suggestion(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    field = hosts_page.get_by_role("combobox", name="Search models", exact=True)
    field.fill("shared")
    field.press("ArrowUp")
    last = hosts_page.get_by_role("option", name="synthetic-response-shared", exact=True)
    expect(last).to_have_attribute("aria-selected", "true")
    field.press("Enter")
    expect(field).to_have_value("synthetic-response-shared")
    hosts_page.wait_for_timeout(350)
    expect(hosts_page).to_have_url(re.compile("hq=synthetic-response-shared"))


def test_hosts_search_keyboard_blur_closes_suggestions_before_another_menu(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    field = hosts_page.get_by_role("combobox", name="Search models", exact=True)
    field.fill("shared")
    suggestions = hosts_page.get_by_role("listbox", name="Model suggestions", exact=True)
    expect(suggestions).to_be_visible()
    field.press("Shift+Tab")
    trigger = hosts_page.get_by_role("button", name="Hosts condition", exact=True)
    expect(trigger).to_be_focused()
    expect(suggestions).to_have_count(0)
    expect(field).to_have_attribute("aria-expanded", "false")
    trigger.press("Enter")
    expect(hosts_page.get_by_role("dialog", name="Hosts", exact=True)).to_be_visible()
    expect(suggestions).to_have_count(0)
    expect(hosts_page).to_have_url(re.compile("hq=shared"))


def test_hosts_option_filter_counts_highlights_and_owned_edits(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, healthy="1"))
    hosts_page.get_by_role("button", name="Precision condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name="Precision", exact=True)
    # 105 bulk + 3 shared + 1 precision + 3 tiny/negative/zero + 2 solo
    # + 3 exact endpoints are normal fp16; Gamma's non-normal one is omitted.
    fp16 = dialog.get_by_role("checkbox", name="fp16", exact=True).locator("..")
    expect(fp16.locator("small")).to_have_text("117")
    dialog.get_by_label("Filter precision…", exact=True).fill("FP1")
    expect(dialog.get_by_role("checkbox")).to_have_count(1)
    expect(dialog.locator("mark")).to_have_text("fp1")
    dialog.get_by_role("checkbox", name="fp16", exact=True).uncheck()
    expect(dialog).to_be_visible()
    expect(hosts_page).to_have_url(re.compile("quantset=1"))
    dialog.get_by_role("button", name="Any", exact=True).click()
    expect(dialog).to_be_visible()
    expect(hosts_page).not_to_have_url(re.compile("quantset="))
    dialog.get_by_label("Filter precision…", exact=True).focus()
    hosts_page.keyboard.press("ArrowDown")
    expect(dialog.get_by_role("checkbox", name="fp16", exact=True)).to_be_focused()
    hosts_page.keyboard.press("Enter")
    expect(dialog.get_by_role("checkbox", name="fp16", exact=True)).not_to_be_checked()
    hosts_page.keyboard.press("Escape")
    hosts_page.get_by_role("button", name="Remove Precision filter", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(hosts_page).not_to_have_url(re.compile("quantset="))
    expect(hosts_page).to_have_url(re.compile("healthy=1"))


def test_hosts_unrelated_navigation_cancels_pending_editor_and_outside_focus(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    hosts_page.get_by_role("button", name="Context condition", exact=True).click()
    hosts_page.get_by_label("Minimum context length", exact=True).fill("128K")
    _switch_hash(hosts_page, _hosts_fragment(facts, rank="context"))
    expect(hosts_page.get_by_role("dialog", name="Context", exact=True)).to_have_count(0)
    hosts_page.wait_for_timeout(350)
    expect(hosts_page).not_to_have_url(re.compile("ctxmin="))
    hosts_page.get_by_role("button", name="Status condition", exact=True).click()
    hosts_page.get_by_label("Ranking", exact=True).click()
    expect(hosts_page.get_by_role("dialog", name="Status", exact=True)).to_have_count(0)
    expect(hosts_page.get_by_label("Ranking", exact=True)).to_be_focused()


def test_hosts_history_owns_date_range_and_clear_all_retains_comparison_settings(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha", healthy="1", rank="context", match="all", showx="1"))
    controls = hosts_page.get_by_role("region", name="Browser controls", exact=True)
    expect(controls.get_by_role("group", name="Date range", exact=True)).to_have_count(0)
    expect(controls.get_by_role("group", name="Detail", exact=True)).to_have_count(0)
    history = hosts_page.get_by_role("region", name="Host history", exact=True)
    history.get_by_label("From", exact=True).fill("2026-09-02")
    history.get_by_label("From", exact=True).press("Tab")
    expect(hosts_page).to_have_url(re.compile("from=2026-09-02"))
    hosts_page.get_by_role("button", name="Clear all", exact=True).click()
    expect(hosts_page.get_by_label("Ranking", exact=True)).to_have_value("context")
    expect(hosts_page.get_by_label("Show excluded", exact=True)).to_be_checked()
    expect(hosts_page).to_have_url(re.compile("match=all"))
    expect(hosts_page).to_have_url(re.compile("hosts=Synthetic%20Alpha"))
    expect(hosts_page.locator(".host-condition-counts")).to_contain_text("No filters. Every endpoint counts.")


def test_hosts_explicit_unavailable_capture_remains_selected(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hasof=facts.scrapes["uncaptured"]))
    expect(hosts_page.get_by_label("Snapshot", exact=True)).to_have_value(str(facts.scrapes["uncaptured"]))
    expect(hosts_page.get_by_label("Snapshot", exact=True).locator("option:checked")).to_contain_text("2026-09-07")
    expect(hosts_page.get_by_text("No endpoint capture was saved for this snapshot.", exact=True)).to_be_visible()


def test_hosts_clear_all_cancels_uncommitted_search_and_restores_visible_text(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, healthy="1"))
    field = hosts_page.get_by_role("combobox", name="Search models", exact=True)
    field.fill("hosts-sha")
    hosts_page.get_by_role("button", name="Clear all", exact=True).click()
    expect(field).to_have_value("")
    hosts_page.wait_for_timeout(350)
    expect(hosts_page).not_to_have_url(re.compile("hq="))


def test_hosts_history_remains_available_when_one_host_has_no_qualifying_rows(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha", quantset="1"))
    expect(hosts_page.get_by_text("No endpoint meets every filter.", exact=False)).to_be_visible()
    expect(hosts_page.get_by_role("region", name="Host history", exact=True).get_by_label("From", exact=True)).to_be_visible()


@pytest.mark.parametrize("hosts_server", ["capture_order"], indirect=True)
def test_hosts_capture_options_follow_capture_time_instead_of_import_id(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    first = hosts_page.get_by_label("Snapshot", exact=True).locator("option").first
    expect(first).to_have_attribute("value", str(facts.scrapes["first"]))
    expect(first).to_have_text("Snapshot 2026-10-01")


@pytest.mark.parametrize("hosts_server", ["many_lists"], indirect=True)
def test_hosts_scrolling_matrix_keeps_header_corner_above_model_column(hosts_page, hosts_server):
    _, facts = hosts_server
    hosts_page.set_viewport_size({"width": 1000, "height": 600})
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Beta,Synthetic Gamma"))
    scroll = hosts_page.locator(".hosts-table-scroll")
    scroll.scroll_into_view_if_needed()
    scroll.evaluate("el => window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top - document.querySelector('.hosts-toolbar').getBoundingClientRect().height)")
    scroll.evaluate("el => { el.scrollLeft = 100; }")
    corner = hosts_page.get_by_role("columnheader", name="Model", exact=True)
    assert corner.evaluate("el => { const b = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2)); }")
    assert scroll.evaluate("el => el.scrollTop === 0 && el.scrollLeft === 100 && el.scrollHeight === el.clientHeight && el.scrollWidth > el.clientWidth")


def test_hosts_conditions_empty_chips_show_excluded_and_clear_all(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, quantset="1"))
    expect(hosts_page.get_by_text("No endpoint meets every filter.", exact=False)).to_contain_text("Precision removes the most (135 endpoints).")
    hosts_page.get_by_label("Show excluded").check()
    matrix = hosts_page.get_by_role("table", name="Host comparison")
    expect(matrix).to_be_visible()
    expect(matrix.locator("tr.is-excluded").first).to_contain_text("No qualifying endpoint")
    matrix.locator("tbody tr").first.get_by_role("button").click()
    expect(hosts_page.get_by_role("dialog").locator("tr.is-excluded").first).to_contain_text("Precision")
    expect(hosts_page.get_by_role("dialog").get_by_role("heading", level=2)).to_be_focused()
    hosts_page.keyboard.press("Escape")
    expect(hosts_page.get_by_role("dialog")).to_have_count(0)
    expect(matrix.locator('[aria-label="best in row"]')).to_have_count(0)
    hosts_page.get_by_role("button", name="Clear all", exact=True).click()
    expect(hosts_page.get_by_label("Show excluded")).to_be_checked()
    expect(matrix.locator("tbody tr").first.locator("td").first).to_contain_text("Synthetic Gamma")
    expect(hosts_page).to_have_url(re.compile(rf"hasof={facts.scrapes['first']}"))


def test_hosts_condition_editor_keyboard_focus_and_empty_precision(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    phrase = hosts_page.get_by_role("button", name="Precision condition", exact=True)
    phrase.focus()
    hosts_page.keyboard.press("Enter")
    dialog = hosts_page.get_by_role("dialog", name="Precision")
    expect(dialog).to_be_visible()
    assert dialog.evaluate("el => !!el.closest('[data-model-sentinel-portal]')")
    hosts_page.keyboard.press("Escape")
    expect(phrase).to_be_focused()
    phrase.click()
    dialog.get_by_role("button", name="16-bit or better", exact=True).click()
    expect(dialog.get_by_role("checkbox", name="fp16", exact=True)).to_be_checked()
    expect(dialog.get_by_role("checkbox", name="fp8", exact=True)).not_to_be_checked()
    expect(dialog.get_by_role("checkbox", name="unknown", exact=True)).to_be_checked()
    dialog.get_by_role("checkbox", name="unknown", exact=True).click()
    dialog.get_by_role("button", name="8-bit or better", exact=True).click()
    expect(dialog.get_by_role("checkbox", name="fp8", exact=True)).to_be_checked()
    expect(dialog.get_by_role("checkbox", name="fp6", exact=True)).not_to_be_checked()
    expect(dialog.get_by_role("checkbox", name="unknown", exact=True)).not_to_be_checked()
    dialog.get_by_role("button", name="16-bit or better", exact=True).click()
    hosts_page.keyboard.press("Escape")
    hosts_page.reload()
    phrase.click()
    expect(dialog.get_by_role("checkbox", name="fp8", exact=True)).not_to_be_checked()


def test_hosts_exact_price_limit_and_condition_reason_order(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Beta", plimit="pricing.prompt:" + facts.host_exact_prices["threshold"]))
    row = hosts_page.locator('tr[data-list-path="' + facts.host_exact_prices["path"] + '"]')
    row.get_by_role("button").click()
    drawer = hosts_page.get_by_role("dialog")
    expect(drawer.locator('tbody tr:not(.is-excluded):has(> th[scope="row"])')).to_contain_text("exact-low")
    expect(drawer.locator("tbody tr.is-excluded").filter(has_text="exact-high")).to_contain_text("Price")
    hosts_page.keyboard.press("Escape")
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts="Synthetic Gamma,Synthetic Alpha", healthy="1", quantset="1", showx="1"))
    shared = hosts_page.locator('tr[data-list-path="' + facts.host_row_admission["shared_path"] + '"]')
    shared.get_by_role("button").click()
    drawer = hosts_page.get_by_role("dialog")
    expect(drawer.locator("tr.is-excluded").filter(has_text="Synthetic Gamma")).to_contain_text("Precision")
    expect(drawer.locator("tr.is-excluded").filter(has_text="Synthetic Alpha").first).to_contain_text("Precision")


def test_hosts_tier_native_identity_and_numeric_typing_replace_history(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, tierset="1", tiers='"null"'))
    hosts_page.get_by_role("button", name="Tier condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name="Tier")
    expect(dialog.get_by_role("checkbox", name='"null"', exact=True)).to_be_checked()
    expect(dialog.get_by_role("checkbox", name="standard", exact=True)).not_to_be_checked()
    expect(dialog.get_by_role("checkbox", name='"standard"', exact=True)).not_to_be_checked()
    hosts_page.keyboard.press("Escape")
    hosts_page.get_by_role("button", name="Context condition", exact=True).click()
    before = hosts_page.evaluate("history.length")
    field = hosts_page.get_by_label("Minimum context length", exact=True)
    field.fill("128K")
    expect(hosts_page).to_have_url(re.compile("ctxmin=128K"))
    field.fill("200K")
    expect(hosts_page).to_have_url(re.compile("ctxmin=200K"))
    assert hosts_page.evaluate("history.length") == before
    hosts_page.keyboard.press("Escape")
    hosts_page.get_by_role("button", name="Clear all", exact=True).click()
    expect(hosts_page).not_to_have_url(re.compile("tierset|tiers|ctxmin"))


@pytest.mark.parametrize(("settings", "condition", "removed"), [
    ({"healthy": "1"}, "Status", 5),
    ({"quantset": "1", "quant": "fp32"}, "Precision", 134),
    ({"upmin": "99.5"}, "Uptime", 134),
    ({"upmin": "99.5", "upmiss": "1"}, "Uptime", 129),
    ({"ctxmin": "200K"}, "Context", 132),
    ({"outmin": "32K"}, "Max output", 5),
    ({"params": "response_format"}, "Supports", 134),
    ({"ntools": "code"}, "Supports", 134),
    ({"caching": "1"}, "Supports", 5),
    ({"tierset": "1", "tiers": '"null"'}, "Tier", 131),
    ({"hq": "HOSTS-SHARED"}, "Model search", 131),
    ({"xhosts": "Synthetic Bulk"}, "Hosts", 105),
    ({"plimit": "pricing.prompt:-1"}, "Price", 134),
    ({"plimit": "pricing.prompt:0"}, "Price", 133),
    ({"plimit": "pricing.prompt:1e-9994"}, "Price", 132),
])
def test_hosts_condition_only_removal_counts_ignore_other_conditions(hosts_page, hosts_server, settings, condition, removed):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, **settings))
    expect(hosts_page.locator(".condition-chip").filter(has_text=condition + ":").locator("small")).to_have_text(f"−{removed}")
    _switch_hash(hosts_page, _hosts_fragment(facts, **{**settings, "hq": "synthetic-response-shared"}))
    expect(hosts_page.locator(".condition-chip").filter(has_text=condition + ":").locator("small")).to_have_text(f"−{removed}")


def test_hosts_all_excluded_any_all_presence_and_empty_copy_precedence(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Missing", healthy="1", quantset="1", showx="1", match="all"))
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_have_count(0)
    hosts_page.get_by_label("Row match").select_option("any")
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()
    expect(hosts_page.locator(".host-no-qualifying")).to_contain_text("Precision removes the most (135 endpoints).")
    hosts_page.locator(".host-no-qualifying button").click()
    expect(hosts_page.locator(".host-no-qualifying")).to_have_count(0)
    expect(hosts_page).not_to_have_url(re.compile("quantset="))
    _switch_hash(hosts_page, _hosts_fragment(facts, hasof=facts.scrapes["empty"], quantset="1"))
    expect(hosts_page.get_by_text("No endpoints were recorded in this capture.", exact=True)).to_be_visible()
    expect(hosts_page.locator(".host-no-qualifying")).to_have_count(0)


def test_hosts_clear_all_preserves_comparison_and_normalizes_bad_conditions(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha", healthy="1", rank="context", match="all", ctxmin="bogus", upmin="101", upwin="invalid", tiers="null,invalid", quant="invalid", showx="invalid", plimit="pricing.prompt:bad"))
    expect(hosts_page).not_to_have_url(re.compile(r"#[^#]*(?:bogus|invalid|101|bad)"))
    hosts_page.get_by_role("button", name="Clear all", exact=True).click()
    expect(hosts_page.get_by_role("region", name="Host summary")).to_be_visible()
    expect(hosts_page).to_have_url(re.compile("hosts=Synthetic%20Alpha"))
    expect(hosts_page).to_have_url(re.compile("providers=" + facts.provider_id))
    expect(hosts_page).to_have_url(re.compile("hasof=" + str(facts.scrapes["first"])))
    expect(hosts_page.get_by_label("Ranking")).to_have_value("context")
    expect(hosts_page.get_by_label("Row match")).to_have_count(0)
    expect(hosts_page).to_have_url(re.compile("match=all"))


def test_hosts_nonempty_chip_hash_activates_and_empty_tier_survives_reload(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, quant="fp32"))
    expect(hosts_page.locator(".condition-chip").filter(has_text="Precision:").locator("small")).to_have_text("−134")
    _switch_hash(hosts_page, _hosts_fragment(facts, tierset="1"))
    expect(hosts_page.locator(".host-no-qualifying")).to_contain_text("Tier removes the most (135 endpoints).")
    hosts_page.reload()
    expect(hosts_page.locator(".host-no-qualifying")).to_be_visible()
    hosts_page.get_by_role("button", name="Tier condition", exact=True).click()
    hosts_page.get_by_role("dialog", name="Tier").get_by_role("button", name="Clear").click()
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()
    expect(hosts_page).not_to_have_url(re.compile("tierset|tiers"))


def test_hosts_toolbar_describes_conditions_and_checkbox_menus_fit_bottom_sheet(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, ctxmin="200K"))
    expect(hosts_page.locator(".host-condition-counts")).to_contain_text("Context: ≥ 200K")
    expect(hosts_page.get_by_role("button", name="Status condition", exact=True)).to_have_attribute("aria-pressed", "false")
    hosts_page.get_by_role("button", name="Precision condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name="Precision")
    expect(dialog).to_be_visible()
    first = dialog.get_by_role("checkbox", name="bf16", exact=True).bounding_box()
    second = dialog.get_by_role("checkbox", name="fp16", exact=True).bounding_box()
    assert second["y"] > first["y"]
    assert abs(second["x"] - first["x"]) < 2
    hosts_page.keyboard.press("Tab")
    assert dialog.evaluate("el => el.contains(document.activeElement)")
    hosts_page.set_viewport_size({"width": 390, "height": 844})
    hosts_page.wait_for_function("() => { const box = document.querySelector('[role=dialog]').getBoundingClientRect(); return box.left >= 0 && box.right <= innerWidth; }")
    rect = dialog.bounding_box()
    assert rect["x"] >= 0 and rect["x"] + rect["width"] <= 390
    assert abs(rect["y"] + rect["height"] - 844) < 2


@pytest.mark.parametrize("hosts_server", ["no_telemetry"], indirect=True)
def test_hosts_missing_telemetry_suspends_uptime_condition(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, upwin="1d", upmin="99.99", healthy="1"))
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()
    expect(hosts_page.get_by_role("button", name="Uptime condition", exact=True)).to_contain_text("paused")
    expect(hosts_page.get_by_role("button", name="Uptime condition", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(hosts_page.locator(".condition-chip").filter(has_text="Status:").locator("small")).to_have_text("−5")
    expect(hosts_page.locator(".host-condition-counts")).to_contain_text("paused")
    expect(hosts_page.locator(".condition-chip").filter(has_text="Uptime:").locator("small")).to_have_count(0)
    expect(hosts_page.get_by_text("Uptime isn't stored for this snapshot yet.", exact=False)).to_contain_text("The next saved scan can backfill it from its archive.")
    hosts_page.get_by_role("button", name="Uptime condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name="Uptime", exact=True)
    expect(dialog.get_by_label("Minimum uptime percent", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("button", name="30 min", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("checkbox", name=re.compile(r"Keep endpoints without uptime"))).to_be_disabled()
    dialog.get_by_role("button", name="Clear", exact=True).click()
    expect(hosts_page.locator(".host-condition-counts")).not_to_contain_text("paused")


def test_hosts_equal_removal_counts_choose_first_condition_and_trap_focus(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, quantset="1", tierset="1"))
    expect(hosts_page.locator(".host-no-qualifying")).to_contain_text("Precision removes the most (135 endpoints).")
    hosts_page.get_by_role("button", name="Precision condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name="Precision")
    expect(dialog.get_by_role("searchbox", name="Filter precision…", exact=True)).to_be_focused()
    hosts_page.keyboard.press("Shift+Tab")
    expect(dialog.get_by_role("button", name="Clear", exact=True)).to_be_focused()
    hosts_page.keyboard.press("Tab")
    expect(dialog.get_by_role("searchbox", name="Filter precision…", exact=True)).to_be_focused()
    hosts_page.keyboard.press("Escape")
    expect(hosts_page.get_by_role("button", name="Precision condition", exact=True)).to_be_focused()


def test_hosts_price_editor_keeps_exact_text_when_closed_before_debounce(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    hosts_page.get_by_role("button", name="Price condition", exact=True).click()
    field = hosts_page.get_by_label("Maximum price", exact=True)
    before = hosts_page.evaluate("history.length")
    field.fill(facts.host_exact_prices["threshold"])
    hosts_page.keyboard.press("Escape")
    expect(hosts_page).to_have_url(re.compile("plimit=pricing.prompt%3A1.000000000000000015"))
    assert hosts_page.evaluate("history.length") == before
    hosts_page.reload()
    hosts_page.get_by_role("button", name="Price condition", exact=True).click()
    expect(field).to_have_value("1.000000000000000015")
    field.fill("-")
    expect(field).to_have_attribute("aria-invalid", "true")
    hosts_page.keyboard.press("Escape")
    expect(hosts_page).to_have_url(re.compile("plimit=pricing.prompt%3A1.000000000000000015"))


@pytest.mark.parametrize("hosts_server", ["output_prices"], indirect=True)
def test_hosts_price_editor_missing_count_tracks_selected_column_before_limit(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    hosts_page.get_by_role("button", name="Price condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name="Price")
    expect(dialog).to_contain_text("Endpoints with missing values: 5")
    hosts_page.get_by_label("Price column", exact=True).select_option("pricing.completion")
    expect(dialog).to_contain_text("Endpoints with missing values: 134")


@pytest.mark.parametrize("hosts_server", ["output_prices"], indirect=True)
def test_hosts_pending_price_draft_commits_to_current_column(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    hosts_page.get_by_role("button", name="Price condition", exact=True).click()
    hosts_page.get_by_label("Maximum price", exact=True).fill("7")
    hosts_page.get_by_label("Price column", exact=True).select_option("pricing.completion")
    expect(hosts_page).to_have_url(re.compile("plimit=pricing.completion%3A7"))
    # Cover pending work after blur/column change, rather than accepting a
    # momentarily correct hash before an obsolete timer fires.
    hosts_page.wait_for_timeout(350)
    expect(hosts_page.get_by_label("Price column", exact=True)).to_have_value("pricing.completion")
    expect(hosts_page).to_have_url(re.compile("plimit=pricing.completion%3A7"))


@pytest.mark.parametrize("hosts_server", ["output_prices"], indirect=True)
def test_hosts_price_editor_target_and_results_follow_back_forward(hosts_page, hosts_server):
    with _responsive_renderer_deadline():
        _, facts = hosts_server
        goto(hosts_page, hosts_server, _hosts_fragment(facts, plimit="pricing.prompt:7"))
        hosts_page.get_by_role("button", name="Price condition", exact=True).click()
        dialog = hosts_page.get_by_role("dialog", name="Price")
        column = hosts_page.get_by_label("Price column", exact=True)
        field = hosts_page.get_by_label("Maximum price", exact=True)

        def assert_constraint(path, missing, removed, rows):
            expect(column).to_have_value(path)
            expect(field).to_have_value("7")
            expect(dialog).to_contain_text(f"Endpoints with missing values: {missing}")
            expect(hosts_page).to_have_url(re.compile("plimit=" + re.escape(quote(path + ":7", safe="")) + r"(?:&|$)"))
            expect(hosts_page.locator(".condition-chip").filter(has_text="Price:").locator("small")).to_have_text(f"−{removed}")
            expect(hosts_page.get_by_role("table", name="Host comparison").locator("tbody tr")).to_have_count(rows)

        assert_constraint("pricing.prompt", 5, 5, 5)
        column.select_option("pricing.completion")
        assert_constraint("pricing.completion", 134, 134, 1)
        hosts_page.go_back()
        assert_constraint("pricing.prompt", 5, 5, 5)
        hosts_page.go_forward()
        assert_constraint("pricing.completion", 134, 134, 1)
        hosts_page.go_back()
        expect(column).to_have_value("pricing.prompt")
        field.fill("8.000000000000000001")
        hosts_page.keyboard.press("Escape")
        expect(hosts_page).to_have_url(re.compile("plimit=pricing.prompt%3A8.000000000000000001(?:&|$)"))


@pytest.mark.parametrize("hosts_server", ["output_prices"], indirect=True)
def test_hosts_cleared_price_limit_keeps_column_for_exact_retyping(hosts_page, hosts_server):
    with _responsive_renderer_deadline():
        _, facts = hosts_server
        goto(hosts_page, hosts_server, _hosts_fragment(facts, plimit="pricing.completion:7"))
        hosts_page.get_by_role("button", name="Price condition", exact=True).click()
        dialog = hosts_page.get_by_role("dialog", name="Price")
        column = hosts_page.get_by_label("Price column", exact=True)
        field = hosts_page.get_by_label("Maximum price", exact=True)
        rows = hosts_page.get_by_role("table", name="Host comparison").locator("tbody tr")
        expect(column).to_have_value("pricing.completion")
        expect(field).to_have_value("7")
        expect(rows).to_have_count(1)
        before = hosts_page.evaluate("history.length")

        field.fill("")
        expect(hosts_page).not_to_have_url(re.compile("plimit="))
        # Allow the committed empty limit and its effects to settle before
        # retyping; an immediate refill would miss the unwanted default reset.
        hosts_page.wait_for_timeout(350)
        expect(column).to_have_value("pricing.completion")
        expect(field).to_have_value("")
        expect(dialog).to_contain_text("Endpoints with missing values: 134")
        expect(hosts_page.locator(".host-condition-counts")).not_to_contain_text("Price")
        expect(rows).to_have_count(7)

        field.fill("8.000000000000000001")
        hosts_page.keyboard.press("Escape")
        expect(hosts_page).to_have_url(re.compile("plimit=pricing.completion%3A8.000000000000000001(?:&|$)"))
        expect(hosts_page.locator(".condition-chip").filter(has_text="Price:").locator("small")).to_have_text("−134")
        expect(rows).to_have_count(1)
        expect(rows.first).to_have_attribute("data-list-path", facts.host_row_admission["shared_path"])
        assert hosts_page.evaluate("history.length") == before
        hosts_page.get_by_role("button", name="Price condition", exact=True).click()
        expect(column).to_have_value("pricing.completion")
        expect(field).to_have_value("8.000000000000000001")
        expect(dialog).to_contain_text("Endpoints with missing values: 134")


@pytest.mark.parametrize("hosts_server", ["output_prices"], indirect=True)
def test_hosts_restored_active_price_target_overrides_inactive_column_draft(hosts_page, hosts_server):
    with _responsive_renderer_deadline():
        _, facts = hosts_server
        goto(hosts_page, hosts_server, _hosts_fragment(facts))
        hosts_page.get_by_role("button", name="Price condition", exact=True).click()
        dialog = hosts_page.get_by_role("dialog", name="Price")
        column = hosts_page.get_by_label("Price column", exact=True)
        column.select_option("pricing.completion")
        hosts_page.evaluate("value => { const hash = new URLSearchParams(location.hash.slice(1)); hash.set('plimit', value); location.hash = hash.toString(); }", "pricing.prompt:7")
        for navigation in (None, "forward"):
            if navigation:
                hosts_page.go_forward()
            expect(column).to_have_value("pricing.prompt")
            expect(hosts_page.get_by_label("Maximum price", exact=True)).to_have_value("7")
            expect(dialog).to_contain_text("Endpoints with missing values: 5")
            expect(hosts_page).to_have_url(re.compile("plimit=pricing.prompt%3A7(?:&|$)"))
            expect(hosts_page.locator(".condition-chip").filter(has_text="Price:").locator("small")).to_have_text("−5")
            expect(hosts_page.get_by_role("table", name="Host comparison").locator("tbody tr")).to_have_count(5)
            if navigation is None:
                hosts_page.go_back()
                expect(hosts_page).not_to_have_url(re.compile("plimit="))
                # Hash navigation precedes the corresponding render. Select
                # an inactive draft only after the old ceiling has disappeared.
                expect(hosts_page.get_by_label("Maximum price", exact=True)).to_have_value("")
                expect(hosts_page.locator(".host-condition-counts")).not_to_contain_text("Price")
                expect(hosts_page.get_by_role("table", name="Host comparison").locator("tbody tr")).to_have_count(7)
                column.select_option("pricing.completion")


@pytest.mark.parametrize("hosts_server", ["output_prices"], indirect=True)
def test_hosts_unrelated_hash_change_dismisses_uncommitted_price_column(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    hosts_page.get_by_role("button", name="Price condition", exact=True).click()
    column = hosts_page.get_by_label("Price column", exact=True)
    column.select_option("pricing.completion")
    expect(hosts_page).not_to_have_url(re.compile("plimit="))
    _switch_hash(hosts_page, _hosts_fragment(facts, rank="context"))
    expect(hosts_page.get_by_role("dialog", name="Price")).to_have_count(0)
    hosts_page.get_by_role("button", name="Price condition", exact=True).click()
    column.select_option("pricing.completion")
    hosts_page.get_by_label("Maximum price", exact=True).fill("7.000000000000000001")
    hosts_page.keyboard.press("Escape")
    expect(hosts_page).to_have_url(re.compile("plimit=pricing.completion%3A7.000000000000000001(?:&|$)"))


@pytest.mark.parametrize("hosts_server", ["output_prices"], indirect=True)
@pytest.mark.parametrize(("prior", "removed"), [("", None), ("7", 134), ("1.000000000000000015", 135)])
def test_hosts_invalid_price_draft_switches_column_with_last_valid_exact_limit(hosts_page, hosts_server, prior, removed):
    with _responsive_renderer_deadline():
        _, facts = hosts_server
        changes = {"plimit": "pricing.prompt:" + prior} if prior else {}
        goto(hosts_page, hosts_server, _hosts_fragment(facts, **changes))
        hosts_page.get_by_role("button", name="Price condition", exact=True).click()
        field = hosts_page.get_by_label("Maximum price", exact=True)
        field.fill("-")
        expect(field).to_have_attribute("aria-invalid", "true")
        hosts_page.get_by_label("Price column", exact=True).select_option("pricing.completion")
        expect(field).to_have_value(prior)
        expect(hosts_page.get_by_label("Price column", exact=True)).to_have_value("pricing.completion")
        hosts_page.wait_for_timeout(350)
        if prior:
            expect(hosts_page).to_have_url(re.compile("plimit=" + re.escape(quote("pricing.completion:" + prior, safe="")) + r"(?:&|$)"))
            expect(hosts_page.locator(".condition-chip").filter(has_text="Price:").locator("small")).to_have_text(f"−{removed}")
            if removed == 134:
                expect(hosts_page.get_by_role("table", name="Host comparison").locator("tbody tr")).to_have_count(1)
            else:
                expect(hosts_page.locator(".host-no-qualifying")).to_contain_text("Price removes the most (135 endpoints).")
        else:
            expect(hosts_page).not_to_have_url(re.compile("plimit="))
            expect(hosts_page.locator(".host-condition-counts")).not_to_contain_text("Price")
        # Cancellation must still win after invalid text and the target switch.
        field.fill("-")
        if prior:
            hosts_page.get_by_role("dialog", name="Price").get_by_role("button", name="Clear", exact=True).click()
        else:
            expect(hosts_page.get_by_role("dialog", name="Price").get_by_role("button", name="Clear", exact=True)).to_have_count(0)
            hosts_page.keyboard.press("Escape")
        hosts_page.wait_for_timeout(350)
        assert "plimit" not in hosts_page.evaluate("location.hash")
        expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()


@pytest.mark.parametrize("hosts_server", ["output_prices"], indirect=True)
def test_hosts_remove_after_price_column_switch_cancels_drafts_without_hanging(hosts_page, hosts_server):
    with _responsive_renderer_deadline():
        _, facts = hosts_server
        goto(hosts_page, hosts_server, _hosts_fragment(facts))
        hosts_page.get_by_role("button", name="Price condition", exact=True).click()
        field = hosts_page.get_by_label("Maximum price", exact=True)
        field.fill("7")
        hosts_page.get_by_label("Price column", exact=True).select_option("pricing.completion")
        hosts_page.wait_for_timeout(350)
        field.fill("8")
        hosts_page.get_by_role("dialog", name="Price").get_by_role("button", name="Clear", exact=True).click()
        hosts_page.wait_for_timeout(350)
        assert "plimit" not in hosts_page.evaluate("location.hash")
        expect(hosts_page.get_by_role("dialog", name="Price")).to_have_count(0)
        expect(hosts_page.get_by_role("button", name="Clear all", exact=True)).to_have_count(0)
        expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()


@contextmanager
def _responsive_renderer_deadline():
    def deadline(signum, frame):
        raise AssertionError("condition editor left the renderer unresponsive")

    previous = signal.signal(signal.SIGALRM, deadline)
    signal.alarm(15)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize("action", ["missing", "window", "preset"])
def test_hosts_pending_uptime_then_deliberate_control_keeps_newest_hash_responsive(hosts_page, hosts_server, action):
    with _responsive_renderer_deadline():
        _, facts = hosts_server
        goto(hosts_page, hosts_server, _hosts_fragment(facts))
        hosts_page.get_by_role("button", name="Uptime condition", exact=True).click()
        hosts_page.get_by_label("Minimum uptime percent", exact=True).fill("99.9")
        if action == "missing":
            hosts_page.get_by_role("checkbox", name=re.compile(r"Keep endpoints without uptime")).check()
        elif action == "window":
            hosts_page.get_by_role("dialog", name="Uptime").get_by_role("button", name="30 min", exact=True).click()
        else:
            hosts_page.get_by_role("dialog", name="Uptime").get_by_role("button", name="99%", exact=True).click()
        hosts_page.wait_for_timeout(350)
        fragment = hosts_page.evaluate("location.hash")
        if action == "missing":
            assert "upmiss=1" in fragment
        elif action == "window":
            assert "upwin=30m" in fragment
        expect(hosts_page.get_by_label("Minimum uptime percent", exact=True)).to_have_value("99" if action == "preset" else "99.9")
        assert ("upmin=99" if action == "preset" else "upmin=99.9") in fragment
        hosts_page.keyboard.press("Escape")
        hosts_page.get_by_role("button", name="Clear all", exact=True).click()
        expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()


@pytest.mark.parametrize(("condition", "field", "first", "second", "hash_key"), [
    ("Context", "Minimum context length", "128K", "200K", "ctxmin"),
    ("Max output", "Minimum max output", "32K", "128K", "outmin"),
    ("Uptime", "Minimum uptime percent", "99", "99.5", "upmin"),
])
def test_hosts_numeric_presets_preserve_back_forward_navigation(hosts_page, hosts_server, condition, field, first, second, hash_key):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    hosts_page.get_by_role("button", name=condition + " condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name=condition)
    before = hosts_page.evaluate("history.length")
    dialog.get_by_role("button", name=first + ("%" if condition == "Uptime" else ""), exact=True).click()
    expect(hosts_page.get_by_label(field, exact=True)).to_have_value(first)
    expect(hosts_page).to_have_url(re.compile(hash_key + "=" + re.escape(first)))
    assert hosts_page.evaluate("history.length") == before + 1
    dialog.get_by_role("button", name=second + ("%" if condition == "Uptime" else ""), exact=True).click()
    expect(hosts_page.get_by_label(field, exact=True)).to_have_value(second)
    hosts_page.go_back()
    expect(hosts_page.get_by_label(field, exact=True)).to_have_value(first)
    hosts_page.go_forward()
    expect(hosts_page.get_by_label(field, exact=True)).to_have_value(second)


def test_hosts_grouping_ties_navigation_and_exact_prices(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Beta"))
    matrix = hosts_page.get_by_role("table", name="Host comparison")
    expect(matrix).to_be_visible()
    tabs = hosts_page.locator(".view-tabs button")
    assert tabs.first.bounding_box()["y"] == tabs.last.bounding_box()["y"]
    shared = matrix.locator("tbody tr").filter(has_text="synthetic-response-shared")
    expect(shared).to_have_count(1)
    expect(shared.locator('[aria-label="best in row"]')).to_have_count(2)
    shared.get_by_role("button").click()
    drawer = hosts_page.get_by_role("dialog")
    expect(drawer).to_contain_text("alpha-fast")
    expect(drawer).to_contain_text("alpha-cheap")
    hosts_page.keyboard.press("Escape")
    exact = matrix.locator("tbody tr").filter(has_text="synthetic-response-exact")
    expect(exact.locator('[aria-label="best in row"]')).to_have_count(1)
    hosts_page.get_by_label("Ranking").select_option("context")
    expect(shared.locator('[aria-label="best in row"]')).to_have_count(1)
    hosts_page.reload()
    expect(hosts_page.get_by_label("Ranking")).to_have_value("context")
    shared.get_by_role("button", name="synthetic-response-shared", exact=True).click()
    hosts_page.get_by_role("dialog").get_by_role("link", name="fake-org/hosts-twin", exact=True).click()
    expect(hosts_page.locator(".model-breadcrumb")).to_contain_text("hosts-twin")
    hosts_page.go_back()
    hosts_page.keyboard.press("Escape")
    expect(matrix).to_be_visible()
    hosts_page.keyboard.press("1")
    expect(hosts_page.locator(".app-shell")).to_have_attribute("data-view", "activity")
    hosts_page.get_by_role("button", name="4 Hosts", exact=True).click()
    expect(hosts_page.locator(".app-shell")).to_have_attribute("data-view", "hosts")
    expect(matrix).to_be_visible()
    hosts_page.keyboard.press("1")
    hosts_page.keyboard.press("4")
    expect(matrix).to_be_visible()


def test_hosts_mapped_and_unmapped_primary_titles_open_drawer_and_dossier(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    matrix = hosts_page.get_by_role("table", name="Host comparison")
    shared = matrix.locator("tbody tr").filter(has_text="synthetic-response-shared")
    shared.get_by_role("button", name="synthetic-response-shared", exact=True).click()
    drawer = hosts_page.get_by_role("dialog", name="synthetic-response-shared", exact=True)
    expect(drawer.get_by_role("link", name="fake-org/hosts-shared", exact=True)).to_be_visible()
    expect(drawer.get_by_role("link", name="fake-org/hosts-twin", exact=True)).to_be_visible()
    drawer.get_by_role("button", name="Open dossier", exact=True).click()
    expect(hosts_page.locator(".model-breadcrumb")).to_contain_text("hosts-shared")
    expect(hosts_page.locator(".dossier-identity code")).to_have_text("fake-org/hosts-shared")
    hosts_page.go_back()
    expect(drawer).to_be_visible()
    hosts_page.keyboard.press("Escape")
    unmapped = matrix.locator("tbody tr").filter(has_text="synthetic-response-unmapped")
    unmapped.get_by_role("button").click()
    expect(hosts_page.get_by_role("dialog").get_by_role("button", name="Open dossier", exact=True)).to_be_disabled()


def test_hosts_profile_precision_rank_difference_history_and_picker(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Gamma"))
    profile = hosts_page.get_by_role("region", name="Host summary")
    expect(profile).to_contain_text("Synthetic Gamma")
    table = hosts_page.get_by_role("table", name="Host comparison")
    expect(table).to_contain_text("+200%")
    expect(table).to_contain_text("3 of 3")
    expect(table).to_contain_text("fp16")
    table.locator("tbody tr").filter(has_text="synthetic-response-shared").get_by_role("button").click()
    hosts_page.get_by_role("dialog").locator("tbody tr").filter(has_text="Synthetic Gamma").get_by_role("button", name="Details", exact=True).click()
    expect(hosts_page.get_by_role("dialog")).to_contain_text('"null"')
    hosts_page.keyboard.press("Escape")
    expect(hosts_page.get_by_role("region", name="Host history")).to_contain_text("Capture")
    hosts_page.get_by_role("button", name="Add host", exact=True).click()
    hosts_page.get_by_label("Find a host…").fill("beta")
    expect(hosts_page.get_by_role("dialog", name="Compare hosts").get_by_role("checkbox")).to_have_count(1)
    hosts_page.get_by_label("Find a host…").fill("")
    hosts_page.get_by_role("checkbox", name="Synthetic Alpha", exact=True).check()
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()


def test_hosts_missing_ranking_empty_capture_and_narrow_layout(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, rank="uptime:5m"))
    expect(hosts_page.get_by_label("Ranking").locator('option[value="uptime:5m"]')).to_have_attribute("disabled", "")
    expect(hosts_page.get_by_label("Ranking")).to_have_value("price:pricing.prompt")
    unranked = hosts_page.get_by_role("table", name="Host comparison").locator("tbody tr").filter(has_text="synthetic-response-unranked")
    expect(unranked).to_contain_text("No values for this ranking")
    hosts_page.set_viewport_size({"width": 390, "height": 844})
    expect(hosts_page.get_by_role("button", name="Add host", exact=True)).to_be_visible()
    assert hosts_page.evaluate("document.documentElement.scrollWidth <= innerWidth"), hosts_page.evaluate("[...document.querySelectorAll('*')].filter(n=>n.getBoundingClientRect().right>innerWidth).map(n=>[n.tagName,n.className,n.getBoundingClientRect().right]).slice(0,15)")
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Beta"))
    scroll = hosts_page.locator(".hosts-table-scroll")
    expect(hosts_page.get_by_role("columnheader", name="Synthetic Alpha", exact=True)).to_be_visible()
    assert scroll.evaluate("node => node.scrollWidth > node.clientWidth")
    title = hosts_page.locator(".hosts-table tbody tr").first.locator("th")
    before = title.bounding_box()["x"]
    scroll.evaluate("node => node.scrollLeft = 200")
    assert abs(title.bounding_box()["x"] - before) <= 1
    assert hosts_page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    _switch_hash(hosts_page, _hosts_fragment(facts, hasof=facts.scrapes["empty"]))
    expect(hosts_page.get_by_text("No endpoints were recorded in this capture.", exact=True)).to_be_visible()


def test_hosts_snapshot_and_history_resource_changes_hide_previous_rows(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha"))
    expect(hosts_page.get_by_role("region", name="Host summary")).to_be_visible()
    held = []
    hosts_page.route(re.compile(r"/api/hosts\?.*scrape_id=" + str(facts.scrapes["empty"]) + r"(?:&|$)"), lambda route: held.append(route))
    _switch_hash(hosts_page, _hosts_fragment(facts, hasof=facts.scrapes["empty"]))
    _wait_for(hosts_page, lambda: held)
    expect(hosts_page.get_by_role("region", name="Host summary")).to_have_count(0)
    held.pop().continue_()
    expect(hosts_page.get_by_text("No endpoints were recorded in this capture.", exact=True)).to_be_visible()


def test_hosts_exact_price_winner_difference_unranked_counts_and_order(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Beta,Synthetic Gamma"))
    rows = hosts_page.get_by_role("table", name="Host comparison").locator("tbody tr")
    expect(rows.first).to_contain_text("/api/v1/models/fake-org/hosts-bare/endpoints")  # The negative price wins before positive rows.
    exact = rows.filter(has_text="synthetic-response-exact")
    expect(exact.locator("td").nth(2).locator('[aria-label="best in row"]')).to_have_attribute("title", "0.00000100000000000000001")
    expect(exact.locator("td").nth(2).locator('[aria-label="best in row"]')).to_have_count(1)
    expect(exact.locator("td").nth(3)).to_contain_text("+<1%")
    expect(exact.locator("td").nth(3).locator("small")).to_have_attribute("title", "Approximate magnitude: +9.99999e-16%")
    expect(exact.locator("td").nth(4)).to_contain_text("—")
    expect(exact.locator("td").last).to_have_text("2")
    hosts_page.get_by_label("Ranking").select_option("context")
    expect(rows.first).to_contain_text("synthetic-response-exact")
    expect(exact.locator("td").nth(4).locator('[aria-label="best in row"]')).to_have_count(1)
    hosts_page.get_by_label("Ranking").select_option("uptime:1d")
    shared = rows.filter(has_text="synthetic-response-shared")
    expect(shared.locator("td").first).to_contain_text("100%")
    expect(shared.locator("td").nth(3)).to_contain_text("−3.00pt")


def test_hosts_single_capture_pending_uptime_and_requested_unavailable_capture(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, providers=facts.single_provider_id, hasof=facts.scrapes["no_prices"], hosts="Synthetic Missing", rank="price:pricing.prompt"))
    expect(hosts_page.get_by_label("Ranking")).to_have_value("context")
    expect(hosts_page.get_by_text("Uptime isn't stored for this snapshot yet.", exact=False)).to_contain_text("The next saved scan can backfill it from its archive.")
    history = hosts_page.get_by_role("region", name="Host history")
    expect(history).to_contain_text("History starts 2026-09-05. Later usable captures add points.")
    expect(history.locator("polyline")).to_have_count(0)
    _switch_hash(hosts_page, _hosts_fragment(facts, hasof=facts.scrapes["uncaptured"]))
    expect(hosts_page.get_by_text("No endpoint capture was saved for this snapshot.", exact=True)).to_be_visible()
    _switch_hash(hosts_page, _hosts_fragment(facts, hasof=facts.scrapes["error"]))
    expect(hosts_page.get_by_text("Endpoint capture failed for this snapshot, so no endpoint models were saved.", exact=True)).to_be_visible()


def test_hosts_row_rules_pin_bound_and_normalization_do_not_trap_back(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Missing", match="all"))
    expect(hosts_page.get_by_text("No qualifying model matches the selected hosts and row rule.", exact=True)).to_be_visible()
    hosts_page.get_by_label("Row match").select_option("any")
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()
    hosts_page.go_back()
    expect(hosts_page.get_by_label("Row match")).to_have_value("all")
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Alpha,Synthetic Invented", rank="invented", match="invalid"))
    expect(hosts_page.get_by_role("region", name="Host summary")).to_be_visible()
    expect(hosts_page).not_to_have_url(re.compile("Synthetic%20Invented"))
    expect(hosts_page).not_to_have_url(re.compile("Synthetic%20Alpha,Synthetic%20Alpha"))
    expect(hosts_page.get_by_label("Ranking")).to_have_value("price:pricing.prompt")
    # Selecting eight distinct observed hosts bounds the ninth selection.
    _switch_hash(hosts_page, _hosts_fragment(facts))
    hosts_page.get_by_role("button", name="Add host", exact=True).click()
    buttons = hosts_page.get_by_role("dialog", name="Compare hosts", exact=True).get_by_role("checkbox")
    expect(buttons).to_have_count(10)
    for index in range(8):
        buttons.nth(index).click()
    expect(buttons.nth(8)).to_be_disabled()


def test_hosts_history_changed_identity_loading_errors_and_partial_coverage(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Solo"))
    history = hosts_page.get_by_role("region", name="Host history")
    expect(history).to_contain_text("Incomplete coverage.")
    # Only the first two captures have uptime: partial and later complete
    # absences must never extend that two-point segment.
    expect(history.locator("polyline")).to_have_count(1)
    expect(history.locator('circle[data-complete="false"] title').first).to_contain_text("partial")
    held = []
    hosts_page.route(re.compile(r"/api/host_history\?.*host=Synthetic%20Alpha"), lambda route: held.append(route))
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts="Synthetic Alpha"))
    _wait_for(hosts_page, lambda: held)
    expect(history.get_by_role("table", name="Host history captures")).to_have_count(0)
    hosts_page._allowed_console_errors.append("503 (Service Unavailable)")
    held.pop().fulfill(status=503, json={"error": "Synthetic history unavailable"})
    expect(history.get_by_role("alert")).to_contain_text("Synthetic history unavailable")
    hosts_page.unroute(re.compile(r"/api/host_history\?.*host=Synthetic%20Alpha"))
    history.get_by_role("button", name="Try again").click()
    expect(history.get_by_role("table", name="Host history captures")).to_be_visible()


def test_hosts_changed_capture_failure_never_displays_previous_matrix(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()
    hosts_page._allowed_console_errors.append("503 (Service Unavailable)")
    pattern = re.compile(r"/api/hosts\?.*scrape_id=" + str(facts.scrapes["second"]) + r"(?:&|$)")
    hosts_page.route(pattern, lambda route: route.fulfill(status=503, json={"error": "Synthetic capture unavailable"}))
    _switch_hash(hosts_page, _hosts_fragment(facts, hasof=facts.scrapes["second"]))
    expect(hosts_page.get_by_role("alert")).to_contain_text("Synthetic capture unavailable")
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_have_count(0)
    hosts_page.unroute(pattern)
    hosts_page.get_by_role("button", name="Try again").click()
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()


def test_hosts_precision_distribution_and_history_truncation(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Beta"))
    profile = hosts_page.get_by_role("region", name="Host summary")
    for precision in ["fp32", "bf16", "fp16", "fp8", "int8", "fp6", "fp4", "mxfp4", "nvfp4", "int4", "unknown", "synthetic-q"]:
        expect(profile.get_by_role("img", name=re.compile("Precision distribution"))).to_have_attribute("aria-label", re.compile(re.escape(precision)))
    expect(profile).to_contain_text("unknown 3")
    hosts_page.get_by_role("table", name="Host comparison").locator("tbody tr").filter(has_text="synthetic-response-shared").get_by_role("button").click()
    hosts_page.get_by_role("dialog").locator("tbody tr").filter(has_text="Synthetic Beta").get_by_role("button", name="Details", exact=True).click()
    expect(hosts_page.get_by_role("dialog")).to_contain_text('"standard"')
    hosts_page.keyboard.press("Escape")
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts="Synthetic Bulk"))
    history = hosts_page.get_by_role("region", name="Host history")
    expect(history).to_contain_text("Showing the 200 most recent endpoint changes; older changes are not shown.")
    expect(history.locator(".endpoint-changes tbody tr")).to_have_count(200)
    expect(history.locator(".endpoint-changes tbody tr").first).to_contain_text("synthetic-response-bulk")


def test_hosts_snapshot_picker_and_unmapped_list_titles(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    matrix = hosts_page.get_by_role("table", name="Host comparison")
    unmapped = matrix.locator("tbody tr").filter(has_text="synthetic-response-unmapped")
    unmapped.get_by_role("button").click()
    expect(hosts_page.get_by_role("dialog").get_by_role("table", name="Observed endpoints").locator("tbody tr")).to_have_count(2)
    hosts_page.keyboard.press("Escape")
    matrix.locator("tbody tr").filter(has_text="fake-org/hosts-bare").get_by_role("button").click()
    expect(hosts_page.get_by_role("dialog").get_by_role("heading", level=2)).to_have_attribute("title", "/api/v1/models/fake-org/hosts-bare/endpoints")
    hosts_page.keyboard.press("Escape")
    hosts_page.get_by_label("Snapshot", exact=True).select_option(str(facts.scrapes["second"]))
    expect(hosts_page.get_by_label("Snapshot", exact=True)).to_have_value(str(facts.scrapes["second"]))
    hosts_page.go_back()
    expect(hosts_page.get_by_label("Snapshot", exact=True)).to_have_value(str(facts.scrapes["first"]))


def test_hosts_provider_change_normalizes_other_provider_capture_without_bad_request(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()
    # A shared global provider control leaves hasof untouched; Hosts must
    # canonicalize it before making an exact-scrape request for a new provider.
    _switch_hash(hosts_page, _hosts_fragment(facts, providers=facts.single_provider_id))
    expect(hosts_page.get_by_label("Snapshot", exact=True)).to_have_value(str(facts.scrapes["no_prices"]))
    expect(hosts_page.get_by_role("alert")).to_have_count(0)
    expect(hosts_page).to_have_url(re.compile(rf"[&#]hasof={facts.scrapes['no_prices']}(?:&|$)"))
    _switch_hash(hosts_page, _hosts_fragment(facts, hasof="invalid"))
    expect(hosts_page.get_by_text("No endpoints were recorded in this capture.", exact=True)).to_be_visible()
    expect(hosts_page).to_have_url(re.compile(rf"[&#]hasof={facts.scrapes['empty']}(?:&|$)"))


@pytest.mark.parametrize(("hosts_server", "legacy"), [("legacy", True), ("no_telemetry", False)], indirect=["hosts_server"])
def test_hosts_legacy_and_missing_telemetry_are_read_only_unavailable_states(hosts_page, hosts_server, legacy):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, rank="uptime:1d"))
    if not legacy:
        expect(hosts_page.get_by_role("table", name="Host comparison")).to_be_visible()
        expect(hosts_page.get_by_label("Ranking")).to_have_value("price:pricing.prompt")
        expect(hosts_page.get_by_label("Ranking").locator('option[value="uptime:1d"]')).to_have_attribute("disabled", "")
        expect(hosts_page.get_by_text("Uptime isn't stored for this snapshot yet. The next saved scan can backfill it from its archive.", exact=True)).to_be_visible()
    else:
        expect(hosts_page.get_by_role("table", name="Host comparison")).to_have_count(0)
        expect(hosts_page.get_by_text("Synthetic Hosts has no saved endpoint capture yet. Saved scans record hosts while endpoint capture is on.", exact=True)).to_be_visible()
    expect(hosts_page.get_by_role("alert")).to_have_count(0)



@pytest.fixture
def endpoint_page(browser: Browser, endpoint_server) -> Iterator[Page]:
    context = browser.new_context()
    try:
        with _guarded_page(context, _origin(endpoint_server)) as instance:
            yield instance
    finally:
        context.close()


def _origin(served) -> str:
    server, _ = served
    return f"http://127.0.0.1:{server.server_address[1]}"


def _base_url(smoke_server) -> str:
    server, _ = smoke_server
    return f"http://127.0.0.1:{server.server_address[1]}/"


def goto(page: Page, smoke_server, fragment: str = "") -> None:
    page.goto(f"{_base_url(smoke_server)}{fragment}")
    expected_view = "activity"
    match = re.search(r"(?:^#|&)view=([^&]+)", fragment)
    if match:
        expected_view = match.group(1)
    expect(page.locator(".app-shell")).to_have_attribute("data-view", expected_view)
    page.wait_for_load_state("networkidle")


def test_boot_tabs_keyboard_and_back_navigation(page: Page, smoke_server) -> None:
    goto(page, smoke_server)
    expect(page.get_by_role("button", name="1 Activity")).to_have_attribute(
        "aria-current", "page"
    )

    page.keyboard.press("2")
    expect(page.locator(".app-shell")).to_have_attribute("data-view", "models")
    expect(page).to_have_url(re.compile(r"#.*view=models"))
    page.get_by_role("button", name="3 Catalog").click()
    expect(page.locator(".app-shell")).to_have_attribute("data-view", "catalog")
    page.go_back()
    expect(page.locator(".app-shell")).to_have_attribute("data-view", "models")


def test_activity_opens_raw_drawer_and_restores_focus(
    page: Page, smoke_server
) -> None:
    _, facts = smoke_server
    price_date = facts.scrape_dates[2].isoformat()
    goto(
        page,
        smoke_server,
        f"#view=activity&providers=example-provider&from={price_date}&to={price_date}",
    )
    expect(page.locator("[data-date]")).to_have_count(180)
    expect(
        page.get_by_role("button", name=re.compile(r"Synthetic Test Model A"))
    ).to_be_visible()

    row = page.get_by_role("row").filter(has_text="Input").last
    row.focus()
    row.click()
    dialog = page.get_by_role("dialog", name="Raw change evidence")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text(re.compile(r"source record / \d+"))
    # B5: Tab from the last focusable control wraps to the first.
    dialog.locator("summary").last.focus()
    page.keyboard.press("Tab")
    expect(dialog.get_by_role("button", name="Close raw change drawer")).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(row).to_be_focused()


def test_activity_explains_equal_length_list_changes(page: Page, smoke_server) -> None:
    _, facts = smoke_server
    model_id, changed_date = facts.equal_length_list_step
    day = changed_date.isoformat()
    goto(
        page,
        smoke_server,
        f"#view=activity&providers=example-provider&from={day}&to={day}&detail=all",
    )

    entry = page.locator("article").filter(has_text=model_id)
    expect(entry.get_by_text("contents changed", exact=True)).to_be_visible()
    expect(entry.get_by_text("1 → 1", exact=True)).to_have_count(0)

    bulk_day = facts.scrape_dates[-1].isoformat()
    goto(
        page,
        smoke_server,
        f"#view=activity&providers=example-provider&from={bulk_day}&to={bulk_day}&detail=all",
    )
    bulk = page.locator("article").filter(has_text="models share this change")
    expect(bulk.get_by_text("contents changed", exact=True)).to_have_count(0)


def test_activity_has_one_detail_control_and_all_reveals_churn(
    page: Page, smoke_server
) -> None:
    _, facts = smoke_server
    day = facts.scrape_dates[1].isoformat()
    goto(
        page,
        smoke_server,
        f"#view=activity&providers=example-provider&from={day}&to={day}",
    )
    expect(page.get_by_role("group", name="Visibility")).to_have_count(0)
    page.get_by_role("group", name="Detail").get_by_role(
        "button", name="All", exact=True
    ).click()
    expect(page).to_have_url(re.compile(r"detail=all"))
    churn = page.locator("article").filter(has_text=facts.benchmark_churn_model)
    expect(churn.get_by_role("row").filter(has_text="Score")).to_be_visible()


def test_activity_folds_churn_summarizes_and_orders_signal(
    page: Page, smoke_server
) -> None:
    _, facts = smoke_server
    squelched_day = facts.scrape_dates[1].isoformat()
    goto(
        page,
        smoke_server,
        f"#view=activity&providers=example-provider&from={squelched_day}&to={squelched_day}",
    )
    expect(
        page.locator("article").filter(has_text=facts.benchmark_churn_model)
    ).to_have_count(0)
    folded = page.get_by_text(
        "1 model changed only in squelched fields", exact=True
    )
    folded.click()
    folded_panel = page.locator("details.folded-line")
    expect(
        folded_panel.get_by_role(
            "button", name=re.compile("Synthetic Test Model A")
        )
    ).to_be_visible()
    folded_panel.get_by_role("button", name="raw", exact=True).click()
    dialog = page.get_by_role("dialog", name="Raw change evidence")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Close raw change drawer").click()
    expect(dialog).to_be_hidden()

    price_day = facts.scrape_dates[2].isoformat()
    goto(
        page,
        smoke_server,
        f"#view=activity&providers=example-provider&from={price_day}&to={price_day}",
    )
    summary = page.get_by_role("navigation", name="Change categories")
    summary.get_by_role("button", name=re.compile(r"Pricing")).click()
    expect(page).to_have_url(re.compile(r"categories=Pricing"))

    mixed_day = facts.scrape_dates[3].isoformat()
    goto(
        page,
        smoke_server,
        f"#view=activity&providers=example-provider&from={mixed_day}&to={mixed_day}",
    )
    expect(page.locator("article").first).to_contain_text(facts.added_model)


def test_activity_range_presets_are_navigable(page: Page, smoke_server) -> None:
    _, facts = smoke_server
    custom_from = facts.scrape_dates[2].isoformat()
    custom_to = facts.scrape_dates[4].isoformat()
    goto(
        page,
        smoke_server,
        f"#view=activity&providers=example-provider&from={custom_from}&to={custom_to}",
    )
    presets = page.get_by_role("group", name="Range presets")
    seven = presets.get_by_role("button", name="7d", exact=True)
    expect(seven).to_have_attribute("aria-pressed", "false")
    seven.click()
    expect(page.get_by_role("textbox", name="From")).to_have_value(
        facts.scrape_dates[1].isoformat()
    )
    expect(page.get_by_role("textbox", name="To")).to_have_value("2026-08-18")
    expect(seven).to_have_attribute("aria-pressed", "true")
    page.go_back()
    expect(page.get_by_role("textbox", name="From")).to_have_value(custom_from)
    expect(page.get_by_role("textbox", name="To")).to_have_value(custom_to)
    expect(presets.get_by_role("button", pressed=True)).to_have_count(0)


def test_models_pin_defaults_aspects_and_hover_timeline(page: Page, smoke_server) -> None:
    goto(page, smoke_server, "#view=models&providers=example-provider")
    page.get_by_role("searchbox", name="Add model").fill("test-model-a")
    option = page.get_by_role("option", name=re.compile("Synthetic Test Model A"))
    expect(option).to_be_visible()
    option.click()
    expect(page.get_by_role("heading", name="Input", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Output", exact=True)).to_be_visible()
    expect(
        page.get_by_role("heading", name="Context length (model)", exact=True)
    ).to_be_visible()
    expect(page).to_have_url(re.compile(r"aspects=.*input_price.*output_price.*context_window"))
    expect(page.locator("canvas").first).to_be_visible()

    plot = page.locator(".u-over").first
    plot.hover(position={"x": 20, "y": 20})
    expect(page.get_by_role("tooltip").first).to_be_visible()
    expect(page.get_by_role("tooltip").first).to_contain_text("test-model-a")


def test_catalog_sort_filter_and_sparkline(page: Page, smoke_server) -> None:
    goto(page, smoke_server, "#view=catalog&providers=example-provider")
    table = page.get_by_role("table")
    expect(table.get_by_role("row")).to_have_count(5)
    expect(table.get_by_text("null", exact=True)).to_have_count(0)
    expect(table.get_by_text("—", exact=True).first).to_be_visible()
    table.get_by_role("button", name=re.compile(r"^Input")).click()
    expect(table.get_by_role("columnheader").filter(has_text="Input")).to_have_attribute(
        "aria-sort", "ascending"
    )
    page.get_by_role("searchbox", name="Filter models").fill("test-model-d")
    expect(table.get_by_role("row")).to_have_count(2)
    page.get_by_role("button", name=re.compile(r"Open Input history")).click()
    dialog = page.get_by_role("dialog", name=re.compile("Input over full history"))
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Open timeline").focus()
    page.keyboard.press("Tab")
    expect(dialog.get_by_role("button", name="Close sparkline")).to_be_focused()


def test_model_dossier_deep_link_timeline_unknown_and_back(page: Page, smoke_server) -> None:
    _, facts = smoke_server
    model_id, _, _, *_ = facts.price_step
    changed_day = facts.scrape_dates[2].isoformat()
    goto(
        page,
        smoke_server,
        f"#view=model&model=example-provider%2F{model_id.replace('/', '%2F')}&at={changed_day}",
    )
    expect(page.locator(".view-tabs [aria-current=page]")).to_have_count(0)
    expect(page.locator(".model-breadcrumb")).to_contain_text("Synthetic Test Model A")
    facts_panel = page.locator(".dossier-facts")
    expect(facts_panel).to_contain_text("Input")
    expect(facts_panel).to_contain_text(f"last changed {changed_day}")
    expect(page.locator(".dossier-edge").filter(has_text="initial")).to_be_visible()
    target = page.locator(f'[data-changelog-date="{changed_day}"]')
    expect(target).to_have_class(re.compile("is-target"))
    assert target.evaluate("element => { const r = element.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; }")

    page.get_by_role("button", name="Timeline", exact=True).click()
    expect(page.locator(".app-shell")).to_have_attribute("data-view", "models")
    expect(page.locator(".timeline-panel").first).to_be_visible()
    page.go_back()
    expect(page.locator(".app-shell")).to_have_attribute("data-view", "model")

    page._allowed_console_errors.append("400 (Bad Request)")
    goto(page, smoke_server, "#view=model&model=example-provider%2Ffake-org%2Fmissing")
    expect(page.get_by_role("heading", name="No saved history for fake-org/missing")).to_be_visible()
    expect(page.get_by_role("searchbox", name="Find model")).to_be_focused()


def test_every_model_surface_and_global_find_open_dossier(page: Page, smoke_server) -> None:
    _, facts = smoke_server
    day = facts.scrape_dates[2].isoformat()
    goto(page, smoke_server, f"#view=activity&providers=example-provider&from={day}&to={day}")
    page.get_by_role("button", name=re.compile("Synthetic Test Model A")).click()
    expect(page).to_have_url(re.compile(r"view=model.*at=2026-08-12"))

    goto(page, smoke_server, "#view=catalog&providers=example-provider")
    page.get_by_role("table").get_by_role("button", name=re.compile("Synthetic Test Model A")).click()
    expect(page.locator(".app-shell")).to_have_attribute("data-view", "model")

    goto(page, smoke_server, "#view=models&providers=example-provider&pins=example-provider%2Ffake-org%2Ftest-model-a")
    page.locator(".pins .model-link").click()
    expect(page.locator(".app-shell")).to_have_attribute("data-view", "model")

    goto(page, smoke_server, "#view=catalog&providers=example-provider")
    page.keyboard.press("/")
    finder = page.get_by_role("searchbox", name="Find model")
    expect(finder).to_be_focused()
    finder.fill("test-model-b")
    expect(page.get_by_role("option", name=re.compile("Synthetic Test Model B"))).to_be_visible()
    finder.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(page.locator(".model-breadcrumb")).to_contain_text("Synthetic Test Model B")


def test_catalog_snapshot_compare_changed_only_presets_and_sticky_column(page: Page, smoke_server) -> None:
    _, facts = smoke_server
    goto(page, smoke_server, "#view=catalog&providers=example-provider")
    as_of = page.get_by_role("textbox", name="As of")
    as_of.fill("2026-08-16")
    expect(as_of).to_have_value("2026-08-15")
    page.get_by_role("button", name="Earlier As of snapshot").click()
    expect(as_of).to_have_value("2026-08-14")
    page.get_by_role("button", name="Later As of snapshot").click()
    expect(as_of).to_have_value("2026-08-15")

    as_of.fill(facts.scrape_dates[2].isoformat())
    page.get_by_role("button", name="Compare with previous").click()
    toggle = page.get_by_role("button", name="Changed only · 1")
    expect(toggle).to_be_visible()
    expect(page.get_by_role("table").get_by_role("row")).to_have_count(2)
    toggle.click()
    expect(page).to_have_url(re.compile(r"changed=0"))
    expect(page.get_by_role("table").get_by_role("row")).to_have_count(5)

    page.get_by_role("button", name="Pricing", exact=True).click()
    expect(page).to_have_url(re.compile(r"cols=.*input_price"))
    # The preset replaces the table with a loading state until its catalog
    # request answers; measuring before then can catch the old table detaching.
    with page.expect_response(lambda response: "/api/catalog?" in response.url):
        page.get_by_role("button", name="All", exact=True).last.click()
    table_wrap = page.locator(".catalog-table-wrap")
    first_model = page.locator('.catalog-table tbody th[scope="row"]').first
    value_cell = page.locator(".catalog-table tbody td").first
    expect(first_model).to_be_visible()
    expect(value_cell).to_be_visible()
    before = first_model.bounding_box(), value_cell.bounding_box()
    table_wrap.evaluate("element => { element.scrollLeft = 400; }")
    after = first_model.bounding_box(), value_cell.bounding_box()
    assert before[0] and after[0] and abs(before[0]["x"] - after[0]["x"]) < 1
    assert before[1] and after[1] and before[1]["x"] != after[1]["x"]


def test_models_default_detail_omits_squelched_rail_marks(page: Page, smoke_server) -> None:
    _, facts = smoke_server
    pin = f"example-provider%2F{facts.benchmark_churn_model.replace('/', '%2F')}"
    goto(page, smoke_server, f"#view=models&providers=example-provider&pins={pin}&from={facts.scrape_dates[0]}&to={facts.scrape_dates[-1]}")
    default_count = page.locator(".event-mark").count()
    page.get_by_role("group", name="Detail").get_by_role("button", name="All", exact=True).click()
    expect(page.locator(".event-mark")).to_have_count(default_count + 5)


def test_theme_choice_survives_reload_without_extra_storage(
    page: Page, smoke_server
) -> None:
    goto(page, smoke_server)
    # D2: appearance is deliberately secondary to the history filters.
    page.get_by_text("Appearance", exact=True).click()
    page.get_by_role("button", name="Dark", exact=True).click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.get_by_text("Appearance", exact=True).click()
    page.get_by_role("button", name="Light", exact=True).click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    page.get_by_role("button", name="System", exact=True).click()
    expect(page.locator("html")).not_to_have_attribute("data-theme", re.compile(".+"))
    assert page.evaluate("Object.keys(localStorage)") == [
        "model_sentinel.browse.theme"
    ]


def test_narrow_viewport_has_no_document_overflow(browser: Browser, smoke_server) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        goto(page, smoke_server)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
    finally:
        context.close()


# ---------------------------------------------------------------------------
# Serving endpoints in the dossier (endpoint-enabled fixture history)
# ---------------------------------------------------------------------------

_ENDPOINT_LOADING = "Reading saved endpoint capture…"
_NOT_CAPTURED = "Provider endpoints weren't captured for this snapshot."


def _dossier_fragment(provider_id: str, model_id: str, extra: str = "") -> str:
    return f"#view=model&model={quote(f'{provider_id}/{model_id}', safe='')}{extra}"


def _endpoint_api(served, model_id: str, scrape_id: int | None = None) -> dict:
    import http.client
    import json

    server, facts = served
    query = f"provider={quote(facts.endpoint.provider_id, safe='')}&model={quote(model_id, safe='')}"
    if scrape_id is not None:
        query += f"&scrape_id={scrape_id}"
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        connection.request("GET", f"/api/endpoints?{query}")
        response = connection.getresponse()
        assert response.status == 200
        return json.loads(response.read())
    finally:
        connection.close()


def _endpoints_section(page: Page):
    return page.get_by_role("region", name="Serving endpoints")


def open_endpoint_dossier(page: Page, served, model_id: str, provider_id: str | None = None):
    _, facts = served
    goto(page, served, _dossier_fragment(provider_id or facts.endpoint.provider_id, model_id))
    section = _endpoints_section(page)
    expect(section).to_be_visible()
    expect(section.get_by_text(_ENDPOINT_LOADING)).to_have_count(0)
    return section


def _switch_hash(page: Page, fragment: str) -> None:
    page.evaluate("fragment => { location.hash = fragment; }", fragment)


@pytest.mark.parametrize("hosts_server", ["dossier_samples"], indirect=True)
@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_dossier_endpoint_capabilities_and_uptime(hosts_page, hosts_server, theme, width):
    _, facts = hosts_server
    hosts_page.set_viewport_size({"width": width, "height": 900})
    goto(hosts_page, hosts_server)
    hosts_page.get_by_text("Appearance", exact=True).click()
    hosts_page.get_by_role("button", name=theme, exact=True).click()
    selected = [facts.scrapes["first"]]
    def observed_snapshot(route):
        response = route.fetch()
        payload = response.json()
        payload["latest_scrape"] = {**payload["latest_scrape"], "scrape_id": selected[0]}
        route.fulfill(response=response, json=payload)
    # ModelView has no historical snapshot picker. As in the existing stale
    # scrape regression, simulate a dossier refresh naming a saved observation.
    hosts_page.route(re.compile(r"/api/model\?"), observed_snapshot)
    goto(hosts_page, hosts_server, _dossier_fragment(facts.provider_id, "fake-org/hosts-shared"))
    section = _endpoints_section(hosts_page)
    table = section.locator("table.endpoint-table")
    expect(table.locator("thead th")).to_have_text(["Endpoint", "Status", "Quantization", "Context length", "Uptime 1d", "Uptime 30m", "Uptime 5m", "Input/1M tokens"])
    rows = table.locator("tbody tr")
    expect(rows.nth(0).locator("td")).to_have_text(["normal", "fp16", "256,000", "0%", "99.9999%", "—", "$2.00"])
    expect(rows.nth(1).locator("td")).to_have_text(["normal", "fp16", "128,000", "—", "—", "—", "$1.00"])
    expect(rows.nth(3).locator("td").first).to_have_text("status 2")
    expect(section.locator(".uptime-unavailable")).to_have_count(0)
    assert hosts_page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width == 390:
        assert table.evaluate("table => table.scrollWidth > table.parentElement.clientWidth")
        table.evaluate("table => table.parentElement.scrollLeft = table.scrollWidth")
        assert table.evaluate("table => table.parentElement.scrollLeft > 0")
    for cell in (rows.nth(0).locator(".capability"), rows.nth(0).locator(".capacity")):
        assert _contrast(hosts_page, cell) >= 4.5
        assert cell.evaluate("cell => getComputedStyle(cell).color !== getComputedStyle(cell.parentElement.querySelector('td')).color")
    # A snapshot switch must replace facts with the selected capture's samples.
    selected[0] = facts.scrapes["second"]
    hosts_page.get_by_role("group", name="Detail").get_by_role("button", name="All", exact=True).click()
    expect(table.locator("tbody tr").nth(0).locator("td")).to_have_text(["normal", "fp16", "512,000", "98%", "—", "—", "$2.00"])
    selected[0] = facts.scrapes["first"]
    goto(hosts_page, hosts_server, _dossier_fragment(facts.provider_id, "fake-org/hosts-unranked"))
    expect(section.locator("table.endpoint-table tbody tr").first.locator("td")).to_have_text(["—", "—", "—", "—", "—", "—"])


@pytest.mark.parametrize("hosts_server", [None, "no_telemetry"], indirect=True)
def test_dossier_missing_uptime_explains_backfill(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _dossier_fragment(facts.single_provider_id, "fake-org/hosts-unranked"))
    section = _endpoints_section(hosts_page)
    expect(section.locator(".uptime-unavailable")).to_have_text("Uptime isn't stored for this snapshot yet. The next saved scan can backfill it from its archive.")
    expect(section.locator("table.endpoint-table tbody tr").first.locator("td")).to_have_text(["—", "—", "—", "—", "—", "—"])


def _wait_for(page: Page, condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting for the browser"
        page.wait_for_timeout(20)


def _api_requests(page: Page, needle: str) -> list[str]:
    seen: list[str] = []
    page.on("request", lambda request: seen.append(request.url) if needle in request.url else None)
    return seen


def test_endpoint_dossier_captured_list_table_changes_and_label_order(
    endpoint_page: Page, endpoint_server
) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.listed_model)
    response = _endpoint_api(endpoint_server, endpoint.listed_model)

    labels = endpoint_page.locator(".dossier-layout > main > section > .section-heading p")
    expect(labels).to_have_text(["02 / latest state", "03 / serving providers", "04 / complete record"])
    expect(endpoint_page.locator(".dossier-layout > main > section > .section-heading h2")).to_have_text(
        ["Current facts", "Serving endpoints", "Changelog"]
    )
    expect(endpoint_page.locator(".dossier-identity > p")).to_have_text("01 / identity")

    table = section.locator("table.endpoint-table")
    third_keys = dict(endpoint.listed_keys_by_capture)[endpoint.third_capture]
    expect(table.locator("tbody th small")).to_have_text(list(third_keys))
    expect(table.locator("thead th")).to_have_text(["Endpoint", "Status", "Quantization", "Context length", "Uptime 1d", "Uptime 30m", "Uptime 5m", "Input/1M tokens", "Output/1M tokens"])
    first = table.locator("tbody tr").first
    expect(first.locator("td")).to_have_text(["normal", "—", "32,000", "—", "99.5%", "—", "$2.00", "$10.00"])
    expect(first.locator("td").nth(6)).to_have_attribute("title", "raw 0.000002")

    capture = section.locator(".endpoint-capture")
    expect(capture.locator(".endpoint-capture-line")).to_have_text(response["capture"]["status_line"])
    expect(capture.locator(".endpoint-capture-line")).to_contain_text(f"partial (capture {endpoint.third_capture})")
    expect(_comparison(section)).to_have_text(f"compared with endpoint capture {endpoint.first_capture}")
    expect(capture).to_contain_text(endpoint.listed_path)

    # Changes keep the API's order and identity.
    rows = section.locator("table.endpoint-changes tbody tr")
    expect(rows).to_have_count(len(response["changes"]))
    expect(rows.locator("th small")).to_have_text([change["endpoint_key"] for change in response["changes"]])
    completion = rows.first
    expect(completion.locator("th span")).to_have_text("Output")
    expect(completion.locator("td.transition")).to_have_text("$8.00→$10.00")
    expect(completion.locator("td.transition")).to_have_class(re.compile(r"\bcost-up\b"))
    added = rows.filter(has_text="Endpoint added")
    expect(added.locator("td.transition")).to_have_text("Input $1.50 · Output $7.00")
    expect(added.locator("td.transition")).to_have_class(re.compile(r"\bendpoint-presence\b"))
    expect(section.locator(".endpoint-truncation")).to_have_text(
        f"{len(response['changes'])} endpoint changes recorded through this snapshot."
    )


def test_endpoint_dossier_shared_list_note_is_derived_from_mappings(
    endpoint_page: Page, endpoint_server
) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.listed_model)
    note = section.locator(".endpoint-shared")
    expect(note).to_have_text(
        f"Shared endpoint list: {endpoint.listed_path} also serves {endpoint.alias_model} (alias)"
        f" and {endpoint.twin_model}. These endpoints belong to the list; this catalog row's price can differ."
    )

    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.twin_model)
    expect(section.locator(".endpoint-shared")).to_have_text(
        f"Shared endpoint list: this model uses {endpoint.listed_model}'s list {endpoint.listed_path},"
        f" which also serves {endpoint.alias_model} (alias) and {endpoint.listed_model}."
        " These endpoints belong to the list; this catalog row's price can differ."
    )

    for unshared in (endpoint.empty_model, endpoint.rebased_model, endpoint.bulk_model):
        section = open_endpoint_dossier(endpoint_page, endpoint_server, unshared)
        expect(section.locator(".endpoint-shared")).to_have_count(0)


def test_endpoint_dossier_alias_uses_differing_leaf_evidence_and_api_ladders(
    endpoint_page: Page, endpoint_server
) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.alias_model)
    response = _endpoint_api(endpoint_server, endpoint.alias_model)
    alias = section.locator(".endpoint-alias")
    expect(alias.locator("h3")).to_have_text(f"Alias of {endpoint.listed_model}")
    # Only the differing leaf is reported as a divergence, with its own values.
    expect(alias.locator(".alias-leaves li")).to_have_text(
        ["Input: alias $2.50 /1M tokens (raw 0.0000025) vs target $2.00 /1M tokens (raw 0.000002)"]
    )
    expect(alias.locator(".alias-match")).to_have_text(
        "Endpoint fake-host-2#0 carries the alias's Input and Output prices"
    )
    expect(section.locator(".endpoint-shared")).to_contain_text(
        f"this model uses {endpoint.listed_model}'s list {endpoint.listed_path}"
    )
    tags = section.locator("table.endpoint-table tbody td.alias-tag")
    expect(tags).to_have_text(["differs", "carries alias prices"])

    ladders = section.locator("figure.endpoint-ladder")
    expect(ladders).to_have_count(len(response["ladders"]))
    ladder = response["ladders"][0]
    figure = ladders.first
    expect(figure.locator("figcaption strong")).to_have_text(ladder["label"])
    points = figure.locator(".ladder-point")
    expect(points).to_have_count(len(ladder["positions"]))
    for index, position in enumerate(ladder["positions"]):
        style = points.nth(index).get_attribute("style") or ""
        placed = re.fullmatch(r"left: ([0-9.e+-]+)%;?", style.strip())
        assert placed and float(placed.group(1)) == pytest.approx(position["position"] * 100)
    expect(figure.locator(".ladder-text li")).to_have_text(
        ["$2.00: endpoint fake-host-1#0; target price", "$2.50: endpoint fake-host-2#0; alias price"]
    )
    # Endpoint dots and alias/target marks are neutral: never a cost color.
    cost_colors = endpoint_page.evaluate(
        "() => { const s = getComputedStyle(document.documentElement);"
        " return [s.getPropertyValue('--cost-up').trim(), s.getPropertyValue('--cost-down').trim()]; }"
    )
    for glyph in figure.locator(".ladder-endpoint, .ladder-mark").all():
        color = glyph.evaluate("element => getComputedStyle(element).backgroundColor")
        assert color not in {_css_rgb(endpoint_page, value) for value in cost_colors}


def _css_rgb(page: Page, value: str) -> str:
    return page.evaluate(
        "value => { const probe = document.createElement('i'); probe.style.color = value;"
        " document.body.appendChild(probe); const color = getComputedStyle(probe).color;"
        " probe.remove(); return color; }",
        value,
    )


def test_endpoint_dossier_reason_states_are_distinct(endpoint_page: Page, endpoint_server) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    expected = {
        endpoint.empty_model: "The provider returned an empty endpoint list for this model at this snapshot.",
        endpoint.no_link_model: "This snapshot's catalog row has no endpoint-list link, so no endpoint list was requested.",
        endpoint.invalid_link_model: "This snapshot's catalog row has a malformed endpoint-list link, so no endpoint list was requested.",
        endpoint.missing_alias_model: "This model is an alias of fake-org/endpoint-nowhere, which is not in this snapshot's catalog, so no endpoint list was resolved.",
        endpoint.cycle_models[0]: "This model's alias chain is a cycle, so no endpoint list was resolved.",
        endpoint.uncaptured_model: f"{_NOT_CAPTURED} This provider's first usable endpoint capture is from 2026-09-01.",
        endpoint.failed_model: "This model's endpoint list failed to fetch, so the saved capture has no endpoints for it.",
        endpoint.error_only_model: "Endpoint capture failed for this snapshot, so no endpoint lists were saved.",
    }
    seen: dict[str, str] = {}
    for model_id, text in expected.items():
        section = open_endpoint_dossier(endpoint_page, endpoint_server, model_id)
        state = section.locator(".endpoint-state")
        expect(state.locator("p").first).to_have_text(text)
        seen[model_id] = state.inner_text()
        expect(section.locator("table.endpoint-table")).to_have_count(0)
    assert len(set(seen.values())) == len(seen)

    # A provider with no usable capture refers to the capture setting instead of a date.
    section = open_endpoint_dossier(
        endpoint_page, endpoint_server, "fake-org/test-model-a", provider_id=EXAMPLE_PROVIDER.provider_id
    )
    expect(section.locator(".endpoint-state p").first).to_have_text(
        f"{_NOT_CAPTURED} See Endpoint capture in the README: saved scans record endpoint lists"
        " for providers whose profile supports it (currently OpenRouter) while MODEL_SENTINEL_ENDPOINT_CAPTURE is on."
    )

    # Valid capture with a missing selected-baseline capture is still shown.
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.rebased_model)
    expect(section.locator("table.endpoint-table tbody tr")).to_have_count(1)
    expect(_comparison(section)).to_have_text(
        "the selected catalog baseline has no endpoint capture, so endpoint lists were not compared"
    )


def test_endpoint_dossier_without_endpoint_tables(browser: Browser, endpoint_server, tmp_path: Path) -> None:
    _, facts = endpoint_server
    database_path = tmp_path / "legacy.db"
    build_fixture_db(database_path, with_endpoints=True)
    # A database created before endpoint capture has none of its tables.
    with sqlite3.connect(database_path) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'endpoint\\_%' ESCAPE '\\'"
            )
        ]
        assert "endpoint_captures" in tables
        for table in tables:
            connection.execute(f'DROP TABLE "{table}"')
    with _serve(database_path, facts) as served:
        context = browser.new_context()
        try:
            with _guarded_page(context, _origin(served)) as page:
                section = open_endpoint_dossier(page, served, facts.endpoint.alias_model)
                expect(section.locator(".endpoint-state p").first).to_have_text(
                    "This database was created before endpoint capture and has no endpoint tables."
                    " See Endpoint capture in the README: saved scans record endpoint lists"
                    " for providers whose profile supports it (currently OpenRouter) while MODEL_SENTINEL_ENDPOINT_CAPTURE is on."
                )
                # The alias is still compared on the catalog snapshot.
                expect(section.locator(".endpoint-alias .alias-leaves li")).to_have_count(1)
                expect(section.locator(".endpoint-alias .alias-match")).to_have_text(
                    "Endpoint matching unavailable: no endpoint lists were captured in this scan"
                )
        finally:
            context.close()


def test_endpoint_dossier_failed_list_shows_evidence_and_local_retry(
    endpoint_page: Page, endpoint_server
) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.failed_model)
    state = section.locator(".endpoint-state")
    code, message = endpoint.failed_error
    expect(section.locator(".section-heading > span")).to_have_text("fetch failed")
    expect(state.locator(".endpoint-failure")).to_have_text(f"{code}: {message}")
    expect(state).to_contain_text(endpoint.failed_path)
    expect(section.locator(".endpoint-gaps li")).to_have_text(
        ["the baseline list failed to fetch; not compared", "the current list failed to fetch; not compared"]
    )
    # The capture had a usable baseline, but this list was never compared.
    _assert_not_compared(
        section, f"this list failed to fetch, so it was not compared with endpoint capture {endpoint.first_capture}"
    )
    _assert_local_retry(endpoint_page, endpoint_server, section)


def test_endpoint_dossier_unsent_list_is_not_called_failed(
    browser: Browser, endpoint_server, tmp_path: Path
) -> None:
    """A list never sent (`budget_exceeded`) shows the API's unsent wording in
    the header, state sentence, gaps, comparison and capture line."""
    _, facts = endpoint_server
    endpoint = facts.endpoint
    database_path = tmp_path / "unsent.db"
    build_fixture_db(database_path, with_endpoints=True)
    mark_failed_list_unsent(database_path, endpoint)
    with _serve(database_path, facts) as served:
        context = browser.new_context()
        try:
            with _guarded_page(context, _origin(served)) as page:
                section = open_endpoint_dossier(page, served, endpoint.failed_model)
                expect(section.locator(".section-heading > span")).to_have_text("not sent")
                state = section.locator(".endpoint-state")
                expect(state.locator("p").first).to_have_text(
                    "This model's endpoint list was not sent before the fetch budget ran out,"
                    " so the saved capture has no endpoints for it."
                )
                expect(state.locator(".endpoint-failure")).to_have_text(f"budget_exceeded: {UNSENT_ERROR_MESSAGE}")
                expect(section.locator(".endpoint-gaps li")).to_have_text(
                    [
                        "the baseline list was not sent before the fetch budget ran out; not compared",
                        "the current list was not sent before the fetch budget ran out; not compared",
                    ]
                )
                _assert_not_compared(
                    section,
                    "this list was not sent before the fetch budget ran out, so it was not compared"
                    f" with endpoint capture {endpoint.first_capture}",
                )
                expect(section.locator(".endpoint-capture-line")).to_have_text(
                    _endpoint_api(served, endpoint.failed_model)["capture"]["status_line"]
                )
                expect(section.locator(".endpoint-capture-line")).to_contain_text(
                    "1 not sent before the fetch budget ran out"
                )
                assert "failed to fetch" not in section.inner_text()
        finally:
            context.close()


def _comparison(section):
    return section.locator(".endpoint-capture dd.endpoint-sentence")


def _assert_not_compared(section, sentence: str) -> None:
    comparison = _comparison(section)
    expect(comparison).to_have_text(sentence)
    assert not comparison.inner_text().casefold().startswith("compared with")


def test_endpoint_dossier_captured_list_renders_its_comparison_gaps(
    endpoint_page: Page, endpoint_server
) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.new_path_model)
    expect(section.locator("table.endpoint-table tbody tr")).to_have_count(1)
    expect(section.locator(".endpoint-gaps li")).to_have_text(["new list with no baseline list; not compared"])
    # Displayed as a sentence.
    assert section.locator(".endpoint-gaps li").inner_text().startswith("New list")
    _assert_not_compared(
        section, f"this list has a comparison gap, so it was not compared with endpoint capture {endpoint.first_capture}"
    )

    # A compared list has no gaps section.
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.listed_model)
    expect(section.locator(".endpoint-gaps")).to_have_count(0)


def _assert_local_retry(page: Page, served, section) -> None:
    retry = section.get_by_role("button", name="Re-read saved capture")
    expect(section.locator(".endpoint-retry")).to_contain_text(
        "Re-reading asks this local history browser again; it does not contact the provider."
    )
    with page.expect_request(lambda request: "/api/endpoints?" in request.url) as request_info:
        retry.click()
    assert _same_origin(request_info.value.url, _origin(served))
    expect(section.get_by_role("button", name="Re-read saved capture")).to_be_enabled()
    expect(section.locator(".endpoint-state")).to_be_visible()


def test_endpoint_minimal_error_capture_roundtrip_in_browser(
    endpoint_page: Page, endpoint_server
) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    # The fixture wrote this capture through Store.save_endpoint_error_capture.
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.error_only_model)
    state = section.locator(".endpoint-state")
    expect(state.locator(".endpoint-failure")).to_have_text(endpoint.error_summary)
    capture = section.locator(".endpoint-capture")
    # The capture line is the reports' own (`capture_status_line`), from the API.
    expect(capture.locator(".endpoint-capture-line")).to_have_text(
        f"error (capture {endpoint.error_capture}): 0 lists requested, 0 attempted, 0 failed,"
        f" 0 mapping failures; error: {endpoint.error_summary}"
    )
    _assert_not_compared(
        section,
        f"no endpoint list was saved for this model, so nothing was compared with endpoint capture {endpoint.third_capture}",
    )
    expect(section.locator(".section-heading > span")).to_have_text("capture failed")
    _assert_local_retry(endpoint_page, endpoint_server, section)


def test_endpoint_dossier_truncated_changes_follow_api_order(
    endpoint_page: Page, endpoint_server
) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.bulk_model)
    response = _endpoint_api(endpoint_server, endpoint.bulk_model)
    assert response["truncated"] is True and len(response["changes"]) == response["limit"]
    rows = section.locator("table.endpoint-changes tbody tr")
    expect(rows).to_have_count(response["limit"])
    expect(section.locator(".endpoint-truncation")).to_have_text(
        f"Showing the {response['limit']} most recent endpoint changes; older changes are not shown."
    )
    shown = rows.evaluate_all(
        "rows => rows.map(row => row.dataset.endpointChangeId)"
    )
    assert shown == [str(change["endpoint_change_id"]) for change in response["changes"]]
    expect(section.locator("table.endpoint-table tbody tr")).to_have_count(105)


def test_endpoint_dossier_api_retry_recovers_from_a_failed_local_request(
    endpoint_page: Page, endpoint_server
) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    endpoint_page._allowed_console_errors.append("503 (Service Unavailable)")
    failures: list[str] = []

    def fail_once(route: Route) -> None:
        if not failures:
            failures.append(route.request.url)
            route.fulfill(status=503, json={"error": "database is busy; retry shortly"})
        else:
            route.fallback()

    endpoint_page.route(re.compile(r"/api/endpoints\?"), fail_once)
    seen = _api_requests(endpoint_page, "/api/endpoints?")
    goto(endpoint_page, endpoint_server, _dossier_fragment(endpoint.provider_id, endpoint.listed_model))
    section = _endpoints_section(endpoint_page)
    banner = section.get_by_role("alert")
    expect(banner).to_contain_text("database is busy; retry shortly")
    expect(section.locator("table.endpoint-table")).to_have_count(0)
    banner.get_by_role("button", name="Try again").click()
    expect(section.locator("table.endpoint-table tbody tr")).to_have_count(2)
    expect(section.get_by_role("alert")).to_have_count(0)
    assert len(seen) == 2
    assert all(_same_origin(url, _origin(endpoint_server)) for url in seen)


def test_endpoint_dossier_held_requests_suppress_stale_endpoints_on_model_switch(
    endpoint_page: Page, endpoint_server
) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.listed_model)
    expect(section.locator("table.endpoint-table tbody tr")).to_have_count(2)

    held_dossiers: list[Route] = []
    held_endpoints: list[Route] = []
    target = quote(endpoint.empty_model, safe="")
    endpoint_page.route(re.compile(rf"/api/model\?.*model={re.escape(target)}"), lambda route: held_dossiers.append(route))
    endpoint_page.route(re.compile(rf"/api/endpoints\?.*model={re.escape(target)}"), lambda route: held_endpoints.append(route))
    _switch_hash(endpoint_page, _dossier_fragment(endpoint.provider_id, endpoint.empty_model))
    _wait_for(endpoint_page, lambda: held_dossiers)

    # The previous dossier is still on screen while its replacement loads, but
    # its endpoints are not, and no endpoint request is made before the
    # replacement dossier (and its scrape ID) arrives.
    expect(endpoint_page.locator(".model-breadcrumb")).to_contain_text("Synthetic endpoint-model-a")
    expect(section.locator("table.endpoint-table")).to_have_count(0)
    expect(section.get_by_text(_ENDPOINT_LOADING)).to_be_visible()
    assert held_endpoints == []

    held_dossiers.pop().fallback()
    expect(endpoint_page.locator(".model-breadcrumb")).to_contain_text("Synthetic endpoint-empty")
    _wait_for(endpoint_page, lambda: held_endpoints)
    assert f"scrape_id={endpoint.third_scrape}" in held_endpoints[0].request.url
    expect(section.locator("table.endpoint-table")).to_have_count(0)
    expect(section.locator(".endpoint-shared")).to_have_count(0)
    expect(section.get_by_text(_ENDPOINT_LOADING)).to_be_visible()

    held_endpoints.pop().fallback()
    expect(section.locator(".endpoint-state p").first).to_have_text(
        "The provider returned an empty endpoint list for this model at this snapshot."
    )


def test_endpoint_dossier_held_requests_suppress_stale_endpoints_on_scrape_switch(
    endpoint_page: Page, endpoint_server
) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.listed_model)
    third_keys = dict(endpoint.listed_keys_by_capture)[endpoint.third_capture]
    second_keys = dict(endpoint.listed_keys_by_capture)[endpoint.second_capture]
    expect(section.locator("table.endpoint-table tbody th small")).to_have_text(list(third_keys))

    # A new saved scan lands between dossier reads: the same model's next
    # dossier response names an earlier, different saved observation.
    def newer_dossier(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["latest_scrape"] = {**payload["latest_scrape"], "scrape_id": endpoint.second_scrape}
        route.fulfill(response=response, json=payload)

    held: list[Route] = []
    endpoint_page.route(re.compile(r"/api/model\?.*detail=all"), newer_dossier)
    endpoint_page.route(
        re.compile(rf"/api/endpoints\?.*scrape_id={endpoint.second_scrape}(?:&|$)"),
        lambda route: held.append(route),
    )
    endpoint_page.get_by_role("group", name="Detail").get_by_role("button", name="All", exact=True).click()
    _wait_for(endpoint_page, lambda: held)
    expect(section.locator("table.endpoint-table")).to_have_count(0)
    expect(section.get_by_text(_ENDPOINT_LOADING)).to_be_visible()

    held.pop().fallback()
    expect(section.locator("table.endpoint-table tbody th small")).to_have_text(list(second_keys))


def _contrast(page: Page, locator) -> float:
    """WCAG contrast of an element's text against its nearest painted background."""
    foreground, background = locator.evaluate(
        """element => {
          const parse = value => (value.match(/[\\d.]+/g) || []).map(Number);
          let node = element, background = null;
          while (node && node.nodeType === 1) {
            const color = parse(getComputedStyle(node).backgroundColor);
            if (color.length === 3 || color[3] > 0) { background = color.slice(0, 3); break; }
            node = node.parentElement;
          }
          return [parse(getComputedStyle(element).color).slice(0, 3), background || [255, 255, 255]];
        }"""
    )

    def luminance(rgb: list[float]) -> float:
        channels = [value / 255 for value in rgb]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_endpoint_dossier_is_legible_in_light_and_dark(
    endpoint_page: Page, endpoint_server, theme: str
) -> None:
    _, facts = endpoint_server
    endpoint = facts.endpoint
    goto(endpoint_page, endpoint_server)
    endpoint_page.get_by_text("Appearance", exact=True).click()
    endpoint_page.get_by_role("button", name=theme, exact=True).click()
    expect(endpoint_page.locator("html")).to_have_attribute("data-theme", theme.lower())
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.alias_model)
    samples = [
        section.locator(".section-heading p"),
        section.locator(".section-heading > span"),
        section.locator("table.endpoint-table tbody td").first,
        section.locator("table.endpoint-table tbody th small").first,
        section.locator(".endpoint-shared"),
        section.locator(".endpoint-capture dd").first,
        section.locator(".endpoint-alias .alias-leaves li").first,
        section.locator(".ladder-text li").first,
        section.locator("table.endpoint-changes td.transition").first,
    ]
    for sample in samples:
        assert _contrast(endpoint_page, sample) >= 4.5, sample
    for model_id in (endpoint.failed_model, endpoint.uncaptured_model):
        section = open_endpoint_dossier(endpoint_page, endpoint_server, model_id)
        assert _contrast(endpoint_page, section.locator(".endpoint-state p").first) >= 4.5


# ---------------------------------------------------------------------------
# Synthetic dossier acceptance: the real browse launch path on an ephemeral port
# ---------------------------------------------------------------------------

_ACCEPTANCE_SCREENSHOTS = "MODEL_SENTINEL_ACCEPTANCE_SCREENSHOTS"


def test_endpoint_synthetic_dossier_acceptance(
    browser: Browser, acceptance_dir: Path, monkeypatch, capsys
) -> None:
    """Serve fixture-defined endpoint dossiers through `run_browse` on port 0
    and inspect them in both maintained themes.

    Screenshots go to this test's private directory; set
    MODEL_SENTINEL_ACCEPTANCE_SCREENSHOTS to also copy them elsewhere for review.
    """
    database_path = acceptance_dir / "acceptance.db"
    facts = build_fixture_db(database_path, with_endpoints=True)
    endpoint = facts.endpoint
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()
    servers = []
    real_make_server = server_module.make_server

    def capture_server(*args, **kwargs):
        instance = real_make_server(*args, **kwargs)
        servers.append(instance)
        return instance

    monkeypatch.setattr(server_module, "make_server", capture_server)
    loaded = SimpleNamespace(
        providers=(EXAMPLE_PROVIDER, OTHER_PROVIDER, ENDPOINT_PROVIDER), settings=browse_settings()
    )
    outcome: list[int] = []
    thread = threading.Thread(
        target=lambda: outcome.append(
            server_module.run_browse(
                db=open_readonly(database_path),
                loaded=loaded,
                port=0,
                open_browser=False,
                initial_provider=None,
                initial_model=f"{endpoint.provider_id}/{endpoint.listed_model}",
            )
        ),
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 10
    printed = ""
    while "Model Sentinel browser: " not in printed:
        assert time.monotonic() < deadline and thread.is_alive(), "browse server did not start"
        time.sleep(0.02)
        printed += capsys.readouterr().out
    launch_url = printed.split("Model Sentinel browser: ", 1)[1].split()[0]
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+/#view=model&model=.+", launch_url)
    origin = launch_url.split("/#", 1)[0]
    assert not origin.endswith(":0")

    dossiers = {
        "captured": (endpoint.listed_model, ".endpoint-table"),
        "alias": (endpoint.alias_model, "figure.endpoint-ladder"),
        "shared-list": (endpoint.twin_model, ".endpoint-shared"),
        "capture-error": (endpoint.error_only_model, ".endpoint-failure"),
        "truncated": (endpoint.bulk_model, ".endpoint-truncation"),
    }
    shots = acceptance_dir / "screens"
    shots.mkdir(mode=0o700)
    try:
        for scheme in ("light", "dark"):
            context = browser.new_context(color_scheme=scheme, viewport={"width": 1280, "height": 900})
            try:
                with _guarded_page(context, origin) as page:
                    page.goto(launch_url)
                    for name, (model_id, marker) in dossiers.items():
                        page.goto(f"{origin}/{_dossier_fragment(endpoint.provider_id, model_id)}")
                        section = _endpoints_section(page)
                        expect(section.locator(marker).first).to_be_visible()
                        expect(section.get_by_text(_ENDPOINT_LOADING)).to_have_count(0)
                        page.wait_for_load_state("networkidle")
                        background = page.evaluate("getComputedStyle(document.body).backgroundColor")
                        assert background == ("rgb(15, 20, 25)" if scheme == "dark" else "rgb(244, 241, 232)")
                        path = shots / f"{name}-{scheme}.png"
                        page.screenshot(path=str(path), full_page=True)
                        assert path.stat().st_size > 0
            finally:
                context.close()
    finally:
        for instance in servers:
            instance.shutdown()
        thread.join(timeout=5)
    assert outcome == [0]
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == before
    target = os.environ.get(_ACCEPTANCE_SCREENSHOTS)
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        for path in sorted(shots.iterdir()):
            shutil.copy2(path, Path(target) / path.name)


def test_hosts_results_row_activation_formats_and_numeric_alignment(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Gamma"))
    table = hosts_page.get_by_role("table", name="Host comparison")
    expect(table.locator("thead th")).to_have_text(["Model", "Synthetic Gamma", "Rank", "Best", "Spread", "Precision", "Context", "Uptime", "Status"])
    shared = table.locator("tbody tr").filter(has_text="synthetic-response-shared")
    expect(shared).to_contain_text("3 of 3")
    expect(shared.locator("td").nth(4)).to_have_text("fp16")
    expect(shared.locator("td").nth(7)).to_have_text("○ status 2")
    expect(shared.locator("td").nth(5).locator("span")).to_have_text("128K")
    expect(shared.locator("td").nth(5).locator("span")).to_have_attribute("title", "128000")
    expect(shared.locator(".model-link")).to_have_attribute("title", "synthetic-response-shared")
    shared.locator("td").nth(1).click()
    expect(shared).to_have_attribute("aria-current", "true")
    hosts_page.keyboard.press("Escape")
    expect(hosts_page.get_by_role("dialog")).to_have_count(0)
    shared.get_by_role("button", name="synthetic-response-shared", exact=True).click()
    expect(hosts_page.get_by_role("dialog")).to_be_visible()
    expect(shared).to_have_attribute("aria-current", "true")
    hosts_page.get_by_role("button", name="Details", exact=True).first.click()
    expect(hosts_page.locator(".endpoint-details-row")).to_contain_text("16-bit")
    hosts_page.keyboard.press("Escape")
    for rank, best in [("price:pricing.prompt", "$1.00"), ("uptime:1d", "100%"), ("context", "256,000"), ("output", "32,000")]:
        _switch_hash(hosts_page, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Beta", rank=rank))
        assert table.locator("thead th").evaluate_all("nodes => nodes.slice(1).every(n => getComputedStyle(n).textAlign === 'right')")
        assert shared.locator("td").evaluate_all("nodes => nodes.every(n => getComputedStyle(n).textAlign === 'right')")
        expect(shared.locator(".hosts-ranking")).to_have_text(best)
        shared.locator("td").first.click()
        expect(hosts_page.get_by_role("dialog")).to_be_visible()
        hosts_page.keyboard.press("Escape")


def test_hosts_summary_compact_facts_missing_uptime_and_narrow_wrapping(hosts_page, hosts_server):
    _, facts = hosts_server
    hosts_page.set_viewport_size({"width": 1440, "height": 1000})
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Beta"))
    profile = hosts_page.get_by_role("region", name="Host summary")
    expect(profile).to_contain_text("models")
    expect(profile).to_contain_text("tags")
    expect(profile).to_contain_text("unknown 3")
    for fact in ["3 models", "16 endpoints", "16 tags", "median uptime 99%", "0 not normal"]:
        expect(profile).to_contain_text(fact)
    assert profile.bounding_box()["height"] <= 60
    expect(profile.locator('.host-precision-mix span[title="unknown: 3"]')).to_have_attribute("style", re.compile("border-strong"))
    hosts_page.set_viewport_size({"width": 390, "height": 844})
    long_name = "Synthetic" + "LongHostName" * 24
    def long_host(route):
        response = route.fetch()
        payload = response.json()
        for host in payload["hosts"]:
            if host["name"] == "Synthetic Beta":
                host["name"] = long_name
        for endpoint in payload["endpoints"]:
            if endpoint["host"] == "Synthetic Beta":
                endpoint["host"] = long_name
        route.fulfill(response=response, json=payload)
    hosts_page.route("**/api/hosts?*", long_host)
    hosts_page.goto("about:blank")
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts=long_name))
    expect(profile.locator("h2")).to_have_text(long_name)
    assert hosts_page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert profile.locator("h2").bounding_box()["width"] <= profile.bounding_box()["width"]
    assert profile.bounding_box()["height"] > 60
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts="Synthetic Missing"))
    expect(profile).to_contain_text("median uptime —")


@pytest.mark.parametrize("overlay", ["menu", "suggestions"])
def test_hosts_drawer_escape_synchronous_overlay_cleanup_preserves_first_key(hosts_page, hosts_server, overlay):
    _, facts = hosts_server
    hosts_page.set_viewport_size({"width": 1600, "height": 1000})
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hq="synthetic", hlist=facts.host_grouping_and_ties["path"]))
    drawer = hosts_page.locator(".endpoint-drawer")
    expect(drawer.get_by_role("heading", level=2)).to_be_focused()
    if overlay == "menu":
        hosts_page.get_by_role("button", name="Precision condition", exact=True).click()
        popup = hosts_page.get_by_role("dialog", name="Precision", exact=True)
    else:
        hosts_page.get_by_role("combobox", name="Search models").focus()
        popup = hosts_page.get_by_role("listbox", name="Model suggestions")
    expect(popup).to_be_visible()
    # Exercise immediate component rendering: descendant Escape cleanup may
    # finish before the same event reaches a window bubble listener.
    hosts_page.evaluate("() => { preact.options.debounceRendering = callback => callback(); }")
    hosts_page.keyboard.press("Escape")
    expect(popup).to_have_count(0)
    hosts_page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    expect(drawer).to_be_visible()
    expect(hosts_page).to_have_url(re.compile("hlist="))
    hosts_page.keyboard.press("Escape")
    expect(drawer).to_have_count(0)
    expect(hosts_page).not_to_have_url(re.compile("hlist="))
    expect(hosts_page.get_by_role("table", name="Host comparison").get_by_role("button", name="synthetic-response-shared", exact=True)).to_be_focused()


def test_hosts_nonmodal_drawer_pointer_toggle_replacement_and_overlay_escape(hosts_page, hosts_server):
    _, facts = hosts_server
    hosts_page.set_viewport_size({"width": 1600, "height": 1000})
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    table = hosts_page.get_by_role("table", name="Host comparison")
    shared = table.locator('tr[data-list-path="' + facts.host_grouping_and_ties["path"] + '"]')
    exact = table.locator('tr[data-list-path="' + facts.host_exact_prices["path"] + '"]')
    shared.locator("th").click(position={"x": 5, "y": 5})
    drawer = hosts_page.locator(".endpoint-drawer")
    expect(drawer).not_to_have_attribute("aria-modal", "true")
    expect(drawer.get_by_role("heading", name="synthetic-response-shared", exact=True)).to_be_focused()
    assert drawer.bounding_box()["width"] == pytest.approx(760, abs=0.01)
    hosts_page.wait_for_function("() => document.querySelector('.endpoint-drawer').getBoundingClientRect().x === 840")
    expect(hosts_page.locator(".drawer-layer")).to_have_count(0)
    shared.locator("th").click(position={"x": 5, "y": 5})
    expect(drawer).to_have_count(0)
    shared.get_by_role("button").click()
    expect(drawer).to_be_visible()
    exact.locator("th").click(position={"x": 5, "y": 5})
    expect(drawer.get_by_role("heading", name="synthetic-response-exact", exact=True)).to_be_focused()
    exact.get_by_role("button").click()
    expect(drawer).to_have_count(0)
    shared.get_by_role("button").click()
    hosts_page.locator(".hosts-toolbar").get_by_role("button", name="Precision condition", exact=True).click()
    expect(hosts_page.get_by_role("dialog", name="Precision", exact=True)).to_be_visible()
    hosts_page.keyboard.press("Escape")
    expect(hosts_page.get_by_role("dialog", name="Precision", exact=True)).to_have_count(0)
    expect(drawer).to_be_visible()
    search = hosts_page.get_by_role("combobox", name="Search models")
    search.fill("synthetic")
    search.press("ArrowDown")
    expect(hosts_page.get_by_role("listbox", name="Model suggestions")).to_be_visible()
    hosts_page.keyboard.press("Escape")
    expect(hosts_page.get_by_role("listbox", name="Model suggestions")).to_have_count(0)
    hosts_page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    expect(drawer).to_be_visible()
    hosts_page.keyboard.press("Escape")
    expect(drawer).to_have_count(0)
    expect(shared.get_by_role("button")).to_be_focused()


@pytest.mark.parametrize("hosts_server", ["output_prices"], indirect=True)
def test_hosts_drawer_hidden_price_sort_survives_lists_and_absent_capture(hosts_page, hosts_server):
    _, facts = hosts_server
    hosts_page.set_viewport_size({"width": 1600, "height": 1000})
    goto(hosts_page, hosts_server, _hosts_fragment(facts, rank="price:pricing.prompt", hlist=facts.host_grouping_and_ties["path"]))
    drawer = hosts_page.get_by_role("dialog")
    output = drawer.get_by_role("columnheader", name="Output", exact=True)
    expect(output).to_have_attribute("title", "/1M tokens")
    output.get_by_role("button").click()
    output.get_by_role("button").click()
    expect(drawer.locator(".drawer-sort-summary")).to_contain_text("Output ▼")
    assert drawer.locator("tbody .endpoint-tag").all_text_contents() == ["alpha-fast", "alpha-cheap", "beta", "gamma"]
    expect(drawer.locator(".hosts-price .hosts-missing")).to_have_count(3)
    table = hosts_page.get_by_role("table", name="Host comparison")
    table.get_by_role("button", name="synthetic-response-exact", exact=True).click()
    expect(drawer.get_by_role("columnheader", name="Output", exact=True)).to_have_count(0)
    expect(drawer.get_by_role("columnheader", name="Input", exact=True)).to_have_count(1)
    expect(drawer.locator(".drawer-sort-summary")).not_to_contain_text("Sorted by")
    expect(drawer.locator(".sort-group-column")).to_have_count(0)
    expect(drawer.locator(".sort-run-band")).to_have_count(0)
    expect(hosts_page).to_have_url(re.compile("dsort=d%3Aprice%3Apricing.completion"))
    table.get_by_role("button", name="synthetic-response-shared", exact=True).click()
    expect(output).to_have_attribute("aria-sort", "descending")
    expect(drawer.locator("tbody .sort-group-column")).to_have_count(4)
    expect(drawer.locator(".sort-run-band")).to_have_count(3)
    assert drawer.locator("tbody .endpoint-tag").all_text_contents() == ["alpha-fast", "alpha-cheap", "beta", "gamma"]
    # A new provider's capture has no completion path: normalization drops it.
    _switch_hash(hosts_page, _hosts_fragment(facts, providers=facts.single_provider_id, hasof=facts.scrapes["no_prices"], dsort="d:price:pricing.completion", hlist=facts.host_grouping_and_ties["path"]))
    expect(hosts_page).not_to_have_url(re.compile("dsort="))


@pytest.mark.parametrize("hosts_server", ["many_lists"], indirect=True)
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_hosts_group_heading_hover_is_inert_but_data_rows_highlight(hosts_page, hosts_server, theme):
    _, facts = hosts_server
    hosts_page.emulate_media(color_scheme=theme)
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hsort="a:hosts,d:model"))
    table = hosts_page.get_by_role("table", name="Host comparison")
    heading = table.locator('th[scope="rowgroup"]').first
    cell = table.locator('tr[data-list-path] th[scope="row"]').first
    hosts_page.mouse.move(0, 0)
    heading_background = heading.evaluate("n => getComputedStyle(n).backgroundColor")
    cell_background = cell.evaluate("n => getComputedStyle(n).backgroundColor")
    heading.hover()
    assert heading.evaluate("n => getComputedStyle(n).backgroundColor") == heading_background
    assert heading.evaluate("n => getComputedStyle(n.parentElement).cursor") == "default"
    cell.hover()
    assert cell.evaluate("n => getComputedStyle(n).backgroundColor") != cell_background
    assert cell.evaluate("n => getComputedStyle(n.parentElement).cursor") == "pointer"


@pytest.mark.parametrize("hosts_server", ["many_lists"], indirect=True)
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_hosts_open_row_keeps_selected_background_on_hover(hosts_page, hosts_server, theme):
    _, facts = hosts_server
    hosts_page.emulate_media(color_scheme=theme)
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hsort="a:hosts,d:model"))
    table = hosts_page.get_by_role("table", name="Host comparison")
    row = table.locator("tr[data-list-path]").first
    row.get_by_role("button").click()
    expect(hosts_page.locator(".endpoint-drawer")).to_be_visible()
    expect(row).to_have_attribute("aria-current", "true")
    cell = row.locator('th[scope="row"]')
    hosts_page.mouse.move(0, 0)
    selected_background = cell.evaluate("n => getComputedStyle(n).backgroundColor")
    ordinary_background = table.locator('tr[data-list-path]:not([aria-current="true"]) th[scope="row"]').first.evaluate("n => getComputedStyle(n).backgroundColor")
    assert selected_background != ordinary_background
    cell.hover()
    assert cell.evaluate("n => getComputedStyle(n).backgroundColor") == selected_background
    expect(row).to_have_attribute("aria-current", "true")


@pytest.mark.parametrize("hosts_server", ["many_lists"], indirect=True)
def test_hosts_sort_grouping_page_headings_bands_and_hidden_primary(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hsort="a:hosts,d:model"))
    table = hosts_page.get_by_role("table", name="Host comparison")
    expect(table.locator("tr[data-list-path]")).to_have_count(50)
    headings = table.locator('th[scope="rowgroup"]')
    expect(headings.first).to_be_visible()
    expect(headings.first).to_contain_text("Hosts")
    assert sum(int(text.split()[-2]) for text in headings.all_text_contents()) == 50
    assert headings.first.evaluate("n=>getComputedStyle(n).borderTopWidth") == "0px"
    assert headings.nth(1).evaluate("n=>getComputedStyle(n).borderTopWidth") == "2px"
    assert headings.evaluate_all("nodes => nodes.every(n => !n.hasAttribute('tabindex') && !n.querySelector('button,a'))")
    headings.first.click()
    expect(hosts_page.get_by_role("dialog")).to_have_count(0)
    hosts_page.get_by_role("button", name="Show 50 more", exact=True).click()
    expect(table.locator("tr[data-list-path]")).to_have_count(100)
    assert sum(int(text.split()[-2]) for text in headings.all_text_contents()) == 100
    _switch_hash(hosts_page, _hosts_fragment(facts, hsort="a:host:Synthetic Alpha,a:model"))
    expect(table.locator('th[scope="rowgroup"]')).to_have_count(0)
    expect(table).to_have_attribute("data-group-column", "1")
    expect(table.locator(".sort-run-band")).to_have_count(0)
    _switch_hash(hosts_page, _hosts_fragment(facts, hsort="a:hosts,d:model", hlist=facts.host_grouping_and_ties["path"], dsort="a:host,d:context", healthy="1", showx="1"))
    drawer = hosts_page.get_by_role("dialog")
    expect(drawer.locator(".sort-not-qualifying")).to_contain_text("Not qualifying")
    assert drawer.locator(".sort-not-qualifying th").evaluate("n=>getComputedStyle(n).borderTopWidth") == "3px"
    expect(drawer.locator(".sort-run-band").first).to_be_visible()
    band = drawer.locator(".sort-run-band").first
    assert band.locator("td").first.evaluate("n=>getComputedStyle(n).backgroundColor") != drawer.locator("tbody tr:not(.sort-run-band) td").first.evaluate("n=>getComputedStyle(n).backgroundColor")
    assert drawer.locator(".sort-run-start").first.locator("th").evaluate("n=>getComputedStyle(n).borderTopWidth") == "2px"
    expect(drawer.get_by_role("table")).to_have_attribute("data-group-column", "1")


def test_hosts_sort_grouping_signed_status_truthful_heading_and_styles(hosts_page, hosts_server):
    _, facts = hosts_server
    def signed_members(route):
        response = route.fetch()
        payload = response.json()
        index = next(index for index, item in enumerate(payload["lists"]) if item["path"] == facts.host_grouping_and_ties["path"])
        members = [endpoint for endpoint in payload["endpoints"] if endpoint["list"] == index]
        assert len(members) == 4
        for endpoint, status in zip(members, [-2, 2, -2, 2]):
            endpoint["status"] = status
        route.fulfill(response=response, json=payload)
    hosts_page.route("**/api/hosts?*", signed_members)
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hlist=facts.host_grouping_and_ties["path"], dsort="a:status,d:host"))
    drawer = hosts_page.get_by_role("dialog")
    heading = drawer.locator('th[scope="rowgroup"]')
    expect(heading).to_have_text("Status absolute status code 2 4 endpoints")
    expect(drawer.locator(".endpoint-tag")).to_have_count(4)
    expect(drawer.locator("tbody .sort-group-column")).to_have_count(4)
    assert drawer.locator("tbody .sort-group-column").first.evaluate("n=>getComputedStyle(n).backgroundColor") != drawer.locator("tbody .endpoint-tag").first.evaluate("n=>getComputedStyle(n).backgroundColor")
    expect(drawer.locator("tbody")).to_contain_text("○ status -2")
    expect(drawer.locator("tbody")).to_contain_text("○ status 2")
    heading.click()
    expect(drawer.locator('button[aria-expanded="true"]')).to_have_count(0)


@pytest.mark.parametrize("hosts_server", ["many_lists"], indirect=True)
@pytest.mark.parametrize("dimension,value", [("price:pricing.prompt", "$1.00"), ("context", "128,000"), ("uptime:1d", "99%")])
def test_hosts_sort_grouping_best_and_compared_host_follow_ranking(hosts_page, hosts_server, dimension, value):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, rank=dimension, hsort="a:best,d:model"))
    table = hosts_page.get_by_role("table", name="Host comparison")
    expect(table.locator('th[scope="rowgroup"]').filter(has_text="Best " + value).first).to_be_visible()
    assert table.locator('th[scope="rowgroup"] strong').first.evaluate("n=>getComputedStyle(n).fontFamily") == table.locator('tr[data-list-path] .hosts-ranking').first.evaluate("n=>getComputedStyle(n).fontFamily")
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts="Synthetic Alpha", rank=dimension, hsort="a:host:Synthetic Alpha,d:model"))
    expect(table.locator('th[scope="rowgroup"]').filter(has_text="Synthetic Alpha " + value).first).to_be_visible()


@pytest.mark.parametrize("other_names", [False, True])
def test_hosts_drawer_other_names_exclude_heading_identity(hosts_page, hosts_server, other_names):
    _, facts = hosts_server
    def heading_is_mapped_model(route):
        response = route.fetch()
        payload = response.json()
        shared = next(item for item in payload["lists"] if item["path"] == facts.host_grouping_and_ties["path"])
        shared["display_id"] = "fake-org/hosts-shared"
        shared["models"] = ["fake-org/hosts-shared", "fake-org/hosts-twin"] if other_names else ["fake-org/hosts-shared"]
        shared["aliases"] = ["fake-org/hosts-shared", "fake-org/hosts-alias"] if other_names else []
        route.fulfill(response=response, json=payload)
    hosts_page.route("**/api/hosts?*", heading_is_mapped_model)
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hlist=facts.host_grouping_and_ties["path"]))
    drawer = hosts_page.get_by_role("dialog", name="fake-org/hosts-shared", exact=True)
    expect(drawer.get_by_role("button", name="Open dossier", exact=True)).to_be_enabled()
    names = drawer.locator(".endpoint-aliases")
    if other_names:
        expect(names).to_have_text("Also served as fake-org/hosts-twin, fake-org/hosts-alias")
        expect(names.get_by_role("link")).to_have_count(1)
        expect(names.get_by_role("link", name="fake-org/hosts-twin", exact=True)).to_have_attribute("href", re.compile("view=model&model="))
        names.get_by_role("link", name="fake-org/hosts-twin", exact=True).click()
        expect(hosts_page.locator(".dossier-identity code")).to_have_text("fake-org/hosts-twin")
    else:
        expect(names).to_have_count(0)
        drawer.get_by_role("button", name="Open dossier", exact=True).click()
        expect(hosts_page.locator(".dossier-identity code")).to_have_text("fake-org/hosts-shared")


def test_hosts_drawer_links_units_and_reduced_motion_at_narrow_width(hosts_page, hosts_server):
    _, facts = hosts_server
    def synthetic_unit(route):
        response = route.fetch()
        payload = response.json()
        payload["price_columns"][0]["unit_label"] = "/synthetic request"
        route.fulfill(response=response, json=payload)
    hosts_page.route("**/api/hosts?*", synthetic_unit)
    hosts_page.set_viewport_size({"width": 390, "height": 844})
    hosts_page.emulate_media(reduced_motion="reduce")
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hlist=facts.host_grouping_and_ties["path"]))
    drawer = hosts_page.get_by_role("dialog")
    expect(drawer).to_have_css("animation-name", "none")
    assert drawer.bounding_box()["width"] == 390
    assert drawer.bounding_box()["x"] == 0
    assert hosts_page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    price = drawer.get_by_role("columnheader", name="Input /synthetic request", exact=True)
    expect(price).to_have_attribute("title", "/synthetic request")
    expect(price.locator(".price-unit")).to_have_text("/synthetic request")
    expect(drawer.locator(".endpoint-aliases a")).to_have_count(2)
    drawer.get_by_role("link", name="fake-org/hosts-twin", exact=True).click()
    expect(hosts_page.locator(".dossier-identity code")).to_have_text("fake-org/hosts-twin")
    hosts_page.go_back()
    expect(drawer).to_be_visible()
    expect(drawer.get_by_role("heading", level=2)).to_be_focused()


def test_hosts_drawer_compact_rows_details_and_failed_reason(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha", healthy="1", hlist=facts.host_grouping_and_ties["path"]))
    drawer = hosts_page.get_by_role("dialog")
    expect(drawer).to_contain_text("3 of 4 endpoints qualify")
    expect(drawer.locator("h2")).to_have_attribute("title", facts.host_grouping_and_ties["path"])
    rows = drawer.locator('tbody tr:has(> th[scope="row"])')
    expect(rows).to_have_count(4)
    assert all(row.bounding_box()["height"] <= 36 for row in rows.all())
    expect(drawer.locator(".host-series-dot")).to_have_count(2)
    expect(drawer.locator(".endpoint-reason").filter(has_text="fails Status")).to_have_count(1)
    expect(drawer.locator("tr:not(.is-excluded) .endpoint-reason")).to_have_text(["", "", ""])
    failed = drawer.locator("tr.is-excluded")
    assert failed.locator(".endpoint-reason").evaluate("el => getComputedStyle(el).opacity") == "1"
    assert failed.locator("th").evaluate("el => getComputedStyle(el).opacity") == "0.5"
    details = drawer.get_by_role("button", name="Details", exact=True).first
    expect(details).to_have_attribute("aria-expanded", "false")
    details.click()
    expect(details).to_have_attribute("aria-expanded", "true")
    expanded = drawer.locator(".endpoint-details-row")
    expect(expanded).to_have_count(1)
    expect(expanded.locator("td")).to_have_attribute("colspan", str(drawer.locator("thead th").count()))
    for fact in ["Max prompt", "Native tools", "Implicit caching", "Service tier", "Uptime 30m", "(16-bit)"]:
        expect(expanded).to_contain_text(fact)
    assert expanded.locator(".host-endpoint-facts").evaluate("el => getComputedStyle(el).whiteSpace") == "normal"
    details.click()
    expect(expanded).to_have_count(0)


def test_hosts_compact_results_drawer_roundtrip_and_copied_url_focus(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Beta"))
    table = hosts_page.get_by_role("table", name="Host comparison")
    shared = table.locator('tr[data-list-path="' + facts.host_grouping_and_ties["path"] + '"]')
    expect(shared.get_by_role("button", name="synthetic-response-shared", exact=True)).to_be_visible()
    assert shared.evaluate("""node => { const sample = document.createElement('span'); sample.textContent = 'Body line'; document.body.append(sample); const line = sample.getBoundingClientRect().height; sample.remove(); return node.getBoundingClientRect().height <= 2 * line; }""")
    expect(shared).to_contain_text("+1 variant")
    expect(shared.locator("details")).to_have_count(0)
    expect(shared.locator('[aria-label="best in row"]')).to_have_count(2)
    expect(shared.locator(".host-spread circle")).to_have_count(3)
    shared.get_by_role("button", name="synthetic-response-shared", exact=True).click()
    drawer = hosts_page.get_by_role("dialog", name="synthetic-response-shared", exact=True)
    expect(drawer).to_be_visible()
    expect(drawer).to_contain_text("4 of 4 endpoints qualify")
    expect(drawer).to_contain_text("Also served as fake-org/hosts-shared, fake-org/hosts-twin, fake-org/hosts-alias")
    expect(drawer.get_by_role("link", name="fake-org/hosts-twin", exact=True)).to_be_visible()
    expect(drawer.get_by_role("table", name="Observed endpoints").locator("tbody tr")).to_have_count(4)
    drawer.get_by_role("button", name="Details", exact=True).first.click()
    for fact in ["Max prompt", "Native tools", "Implicit caching", "Service tier", "Uptime 30m"]:
        expect(drawer.locator(".endpoint-details-row")).to_contain_text(fact)
    copied = hosts_page.url
    hosts_page.keyboard.press("Escape")
    expect(drawer).to_have_count(0)
    expect(shared.get_by_role("button", name="synthetic-response-shared", exact=True)).to_be_focused()
    hosts_page.go_back()
    expect(drawer).to_be_visible()
    hosts_page.go_back()
    expect(drawer).to_have_count(0)
    hosts_page.goto(copied)
    expect(drawer).to_be_visible()
    drawer.get_by_role("button", name="Close endpoint drawer").click()
    expect(shared.get_by_role("button", name="synthetic-response-shared", exact=True)).to_be_focused()


def test_hosts_drawer_unmapped_invalid_path_and_failed_reasons(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hlist="/synthetic/nonexistent"))
    expect(hosts_page).not_to_have_url(re.compile("hlist="))
    row = hosts_page.get_by_role("table", name="Host comparison").locator("tbody tr").filter(has_text="synthetic-response-unmapped")
    row.get_by_role("button", name="synthetic-response-unmapped", exact=True).click()
    drawer = hosts_page.get_by_role("dialog", name="synthetic-response-unmapped", exact=True)
    expect(drawer.get_by_role("button", name="Open dossier", exact=True)).to_be_disabled()
    expect(drawer).to_contain_text("No mapped model")
    hosts_page.keyboard.press("Escape")
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts="Synthetic Gamma", healthy="1", showx="1"))
    shared = hosts_page.get_by_role("table", name="Host comparison").locator('tr[data-list-path="' + facts.host_grouping_and_ties["path"] + '"]')
    expect(shared).not_to_have_class(re.compile("is-excluded"))
    expect(shared).to_contain_text("Synthetic Alpha")
    shared.get_by_role("button", name="synthetic-response-shared", exact=True).click()
    failed = hosts_page.get_by_role("dialog").locator("tr.is-excluded")
    expect(failed).to_have_count(1)
    expect(failed).to_contain_text("Status")


@pytest.mark.parametrize("hosts_server", ["many_lists"], indirect=True)
def test_hosts_pagination_counts_reset_and_pin_limit_geometry(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    table = hosts_page.get_by_role("table", name="Host comparison")
    expect(table.locator("tbody tr")).to_have_count(50)
    expect(hosts_page.locator(".hosts-summary")).to_contain_text("975 of 975 endpoints · 112 models")
    expect(hosts_page.locator(".hosts-pagination")).to_contain_text("Showing 50 of 112 models")
    hosts_page.get_by_role("button", name="Show 50 more", exact=True).click()
    expect(table.locator("tbody tr")).to_have_count(100)
    hosts_page.get_by_role("button", name="Show 50 more", exact=True).click()
    expect(table.locator("tbody tr")).to_have_count(112)
    expect(hosts_page.get_by_role("button", name="Show 50 more", exact=True)).to_have_count(0)
    table.get_by_role("button", name="Model", exact=True).click()
    expect(table.locator("tbody tr")).to_have_count(50)
    hosts_page.go_back()
    expect(table.locator("thead [aria-sort]")).to_have_count(0)
    expect(table.locator("tbody tr")).to_have_count(50)
    hosts_page.get_by_role("button", name="Show 50 more", exact=True).click()
    hosts_page.get_by_label("Ranking", exact=True).select_option("context")
    expect(table.locator("tbody tr")).to_have_count(50)
    hosts_page.go_back()
    expect(hosts_page.get_by_label("Ranking", exact=True)).to_have_value("price:pricing.prompt")
    expect(table.locator("tbody tr")).to_have_count(50)
    hosts_page.get_by_role("button", name="Show 50 more", exact=True).click()
    hosts_page.get_by_label("Show excluded", exact=True).check()
    expect(table.locator("tbody tr")).to_have_count(50)
    hosts = "Synthetic Alpha,Synthetic Beta,Synthetic Gamma,Synthetic Bulk,Synthetic Solo,Synthetic Moved Removed,Synthetic Missing,Synthetic Name Fallback"
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts=hosts))
    expect(table.get_by_role("columnheader")).to_have_count(12)  # Model, Best, Spread, 8 hosts, Hosts.
    for width in [1100, 390]:
        hosts_page.set_viewport_size({"width": width, "height": 600})
        assert hosts_page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        scroll = hosts_page.locator(".hosts-table-scroll")
        assert scroll.evaluate("node => node.scrollWidth > node.clientWidth && node.scrollHeight === node.clientHeight")
        scroll.scroll_into_view_if_needed()
        scroll.evaluate("node => { node.scrollLeft = 300; }")
        header = table.get_by_role("columnheader", name="Model", exact=True)
        first = table.locator("tbody tr").nth(10).locator("th")
        assert abs(first.bounding_box()["x"] - header.bounding_box()["x"]) < 1
        assert header.evaluate("node => getComputedStyle(node).top") == "auto"


def test_hosts_spread_states_row_precedence_and_exact_zero_best(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Gamma", healthy="1", showx="1"))
    table = hosts_page.get_by_role("table", name="Host comparison")
    shared = table.locator("tbody tr").filter(has_text="synthetic-response-shared")
    expect(shared).to_contain_text("Synthetic Alpha")
    expect(shared).not_to_have_class("is-excluded")
    expect(shared.locator("td").nth(0)).to_have_text("—")
    _switch_hash(hosts_page, _hosts_fragment(facts))
    solo = table.locator("tbody tr").filter(has_text="synthetic-response-solo")
    bare = table.locator("tbody tr").filter(has_text="fake-org/hosts-bare")
    expect(bare.get_by_role("img", name="Host value spread")).to_be_visible()
    assert bare.locator("circle").evaluate_all("nodes => nodes.every(n => Number.isFinite(Number(n.getAttribute('cx'))))")
    unranked = table.locator("tbody tr").filter(has_text="synthetic-response-unranked")
    expect(unranked).to_contain_text("No values for this ranking")
    expect(unranked.locator("circle")).to_have_count(0)
    _switch_hash(hosts_page, _hosts_fragment(facts, plimit="pricing.prompt:0", showx="1", hosts="Synthetic Gamma"))
    expect(bare.locator('[aria-label="best in row"]')).to_have_count(1)
    expect(bare.locator("td").nth(0)).to_contain_text("best")
    expect(shared).to_have_class("is-excluded")
    expect(shared).to_contain_text("No qualifying endpoint")
    expect(shared.locator("circle")).to_have_count(0)


def test_hosts_drawer_close_after_filter_removes_row_focuses_results(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hlist=facts.host_grouping_and_ties["path"], quantset="1", dsort="d:host"))
    drawer = hosts_page.get_by_role("dialog", name="synthetic-response-shared", exact=True)
    expect(drawer.get_by_role("heading", level=2)).to_be_focused()
    drawer.get_by_role("button", name="Close endpoint drawer").click()
    expect(hosts_page.locator(".hosts-results-heading")).to_be_focused()
    expect(hosts_page).to_have_url(re.compile("dsort=d%3Ahost"))


@pytest.mark.parametrize("hosts_server", ["spread_cases"], indirect=True)
def test_hosts_spread_marks_and_missing_cells(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    table = hosts_page.get_by_role("table", name="Host comparison")
    close = table.locator("tbody tr").filter(has_text="synthetic-response-spread-close")
    svg = close.locator("svg")
    expect(svg).to_have_attribute("width", "150")
    expect(svg).to_have_attribute("height", "18")
    expect(svg.locator("rect")).to_have_attribute("width", "3")
    expect(svg.locator("rect")).to_have_attribute("height", "16")
    expect(svg.locator("circle")).to_have_count(1)
    expect(svg.locator("circle")).to_have_attribute("r", "3")
    expect(svg.locator("circle")).to_have_attribute("opacity", "0.65")
    unranked = table.locator("tbody tr").filter(has_text="synthetic-response-unranked")
    expect(unranked.locator("td").nth(1).locator(".hosts-missing")).to_have_text("—")
    table.get_by_role("button", name="synthetic-response-exact", exact=True).click()
    missing_price = hosts_page.get_by_role("dialog").locator("tbody tr").filter(has_text="price-missing")
    expect(missing_price.locator(".hosts-price .hosts-missing")).to_have_text("—")
    hosts_page.keyboard.press("Escape")
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts="Synthetic Alpha"))
    expect(close.locator("svg")).to_have_attribute("width", "120")
    expect(close.locator('circle[r="5"]')).to_have_count(1)
    expect(close.locator('circle[r="5"]')).to_have_attribute("stroke-width", "1.5")


@pytest.mark.parametrize("hosts_server", ["spread_cases"], indirect=True)
def test_hosts_spread_exact_identity_survives_extreme_and_overlapping_drawings(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts="Synthetic Alpha,Synthetic Beta,Synthetic Gamma"))
    table = hosts_page.get_by_role("table", name="Host comparison")
    row = lambda name: table.locator("tbody tr").filter(has_text="synthetic-response-spread-" + name)
    for name, count in [("tiny-huge", 3), ("signed", 3), ("zero", 3), ("close", 2), ("equal", 0), ("only", 0)]:
        dots = row(name).locator("circle")
        expect(dots).to_have_count(count)
        assert dots.evaluate_all("nodes => nodes.every(n => Number.isFinite(Number(n.getAttribute('cx'))) && Number(n.getAttribute('cx')) >= 5 && Number(n.getAttribute('cx')) <= 145)")
    expect(row("equal").get_by_text("all 2 hosts equal", exact=True)).to_be_visible()
    expect(row("equal").locator("svg")).to_have_count(0)
    expect(row("only").get_by_text("only host", exact=True)).to_be_visible()
    expect(row("only").locator("svg")).to_have_count(0)
    expect(row("close").get_by_role("img", name="Host value spread", exact=True)).to_be_visible()
    expect(row("close").locator('[aria-label="best in row"]')).to_have_count(1)
    expect(row("close").locator("td").nth(3)).to_contain_text("+<1%")
    expect(row("zero").locator('[aria-label="best in row"]')).to_have_count(2)
    expect(row("zero").locator("td").nth(4).locator("small")).to_have_attribute("title", "A percentage gap from zero is undefined.")
    assert row("signed").locator("circle").evaluate_all("nodes => nodes.map(n => Number(n.getAttribute('cx')))") == [5, 75, 145]
    # Both entries remain separately titled and described when drawing precision overlaps.
    expect(row("close").locator("circle title")).to_have_count(2)
    expect(row("close").locator(".hosts-accessible")).to_contain_text("Synthetic Alpha")
    expect(row("close").locator(".hosts-accessible")).to_contain_text("Synthetic Beta")


def test_hosts_chrome_search_clear_and_provider_control(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    expect(hosts_page.locator('body')).to_have_attribute('data-view', 'hosts')
    expect(hosts_page.get_by_role('heading', level=1)).to_have_count(1)
    expect(hosts_page.locator('.filter-bar .providers')).to_have_count(0)
    expect(hosts_page.locator('.filter-bar .find-model')).to_have_count(0)
    expect(hosts_page.get_by_label('Provider', exact=True)).to_be_visible()
    expect(hosts_page.get_by_label('Snapshot', exact=True)).to_have_value(str(facts.scrapes['first']))
    expect(hosts_page.get_by_role('button', name='Clear all', exact=True)).to_have_count(0)
    hosts_page.keyboard.press('/')
    search = hosts_page.get_by_role('combobox', name='Search models', exact=True)
    expect(search).to_be_focused()
    search.fill('shared')
    expect(hosts_page).to_have_url(re.compile('hq=shared'))
    expect(hosts_page.get_by_role('listbox', name='Model suggestions')).to_be_visible()
    option = hosts_page.get_by_role('listbox', name='Model suggestions').get_by_role('option').first
    assert option.bounding_box()['height'] <= option.evaluate('e => parseFloat(getComputedStyle(e).lineHeight) * 1.5')
    before = hosts_page.evaluate('history.length')
    hosts_page.get_by_role('button', name='Clear model search', exact=True).click()
    expect(search).to_have_value('')
    expect(search).to_be_focused()
    hosts_page.wait_for_timeout(350)
    assert 'hq=' not in hosts_page.evaluate('location.hash')
    assert hosts_page.evaluate('history.length') == before + 1
    search.fill('pending-draft')
    hosts_page.get_by_role('button', name='Clear model search', exact=True).click()
    hosts_page.wait_for_timeout(350)
    expect(search).to_have_value('')
    assert 'hq=' not in hosts_page.evaluate('location.hash')
    hosts_page.get_by_text('Appearance', exact=True).click()
    hosts_page.get_by_role('button', name='Dark', exact=True).click()
    expect(hosts_page.locator('html')).to_have_attribute('data-theme', 'dark')
    hosts_page.get_by_text('Appearance', exact=True).click()
    hosts_page.get_by_label('Provider', exact=True).select_option(facts.single_provider_id)
    assert hosts_page.evaluate("new URLSearchParams(location.hash.slice(1)).get('providers')") == facts.single_provider_id + ',' + facts.provider_id
    expect(hosts_page.get_by_label('Snapshot', exact=True)).to_have_value(str(facts.scrapes['no_prices']))
    hosts_page.go_back()
    expect(hosts_page.get_by_label('Provider', exact=True)).to_have_value(facts.provider_id)
    hosts_page.get_by_role('button', name='1 Activity', exact=True).click()
    expect(hosts_page.locator('body')).to_have_attribute('data-view', 'activity')
    expect(hosts_page.locator('.providers')).to_be_visible()


@pytest.mark.parametrize('hosts_server', ['many_lists'], indirect=True)
def test_hosts_page_scroll_keeps_toolbar_and_nonoverflow_header_visible(hosts_page, hosts_server):
    _, facts = hosts_server
    hosts_page.set_viewport_size({'width': 1440, 'height': 1000})
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    rows = hosts_page.locator('.hosts-table tbody tr')
    expect(rows).to_have_count(50)
    assert rows.first.bounding_box()['y'] <= 320
    assert rows.evaluate_all('rows => rows.filter(r => { const b=r.getBoundingClientRect(); return b.top >= 0 && b.bottom <= innerHeight; }).length') >= 18
    hosts_page.get_by_role('button', name='Show 50 more').click()
    hosts_page.evaluate('scrollTo(0, 2000)')
    toolbar = hosts_page.locator('.hosts-toolbar')
    assert abs(toolbar.bounding_box()['y']) < 1
    header = hosts_page.locator('.hosts-table thead th').first
    assert abs(header.bounding_box()['y'] - toolbar.bounding_box()['height']) < 2
    scroll = hosts_page.locator('.hosts-table-scroll')
    assert scroll.evaluate('e => e.scrollHeight === e.clientHeight')
    hosts_page.set_viewport_size({'width': 390, 'height': 844})
    hosts_page.evaluate('scrollTo(0, 2000)')
    assert toolbar.bounding_box()['y'] < 0
    assert hosts_page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('hosts_server', ['output_prices'], indirect=True)
def test_hosts_default_output_ranking_and_configured_chip_summaries(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, healthy='1', ctxmin='200K', upmin='99.5', upwin='30m', tierset='1'))
    expect(hosts_page.get_by_label('Ranking', exact=True)).to_have_value('price:pricing.completion')
    expect(hosts_page.get_by_label('Ranking', exact=True).locator('option:checked')).to_have_text('Rank by output price')
    chips = hosts_page.locator('.host-condition-counts .condition-chip')
    assert chips.evaluate_all('nodes => nodes.map(n => n.textContent.split(":")[0])') == ['Uptime', 'Status', 'Context', 'Tier']
    expect(chips.nth(0)).to_contain_text('Uptime: ≥ 99.5% (30 min)')
    expect(chips.nth(1)).to_contain_text('Status: normal only −5')
    expect(chips.nth(2)).to_contain_text('Context: ≥ 200K −132')
    expect(chips.nth(3)).to_contain_text('Tier: none −135')
    for name in ['Uptime', 'Status', 'Context', 'Tier']:
        expect(hosts_page.get_by_role('button', name=name + ' condition', exact=True)).to_have_attribute('aria-pressed', 'true')
        expect(hosts_page.get_by_role('button', name='Remove ' + name + ' filter', exact=True)).to_be_visible()
    hosts_page.get_by_role('button', name='Clear all', exact=True).click()
    expect(chips).to_have_count(0)
    expect(hosts_page.get_by_role('button', name='Clear all', exact=True)).to_have_count(0)
    expect(hosts_page.get_by_label('Ranking', exact=True)).to_have_value('price:pricing.completion')


def test_hosts_endpoint_drawer_accepts_escape_as_soon_as_visible(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    hosts_page.evaluate('''() => {
        const observer = new MutationObserver(() => {
            if (!document.querySelector('.endpoint-drawer')) return;
            observer.disconnect();
            window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
        });
        observer.observe(document.body, {childList: true, subtree: true});
    }''')
    hosts_page.get_by_role('button', name='synthetic-response-shared', exact=True).click()
    expect(hosts_page).not_to_have_url(re.compile('hlist='))
    expect(hosts_page.get_by_role('dialog')).to_have_count(0)


def test_hosts_capture_and_history_translate_model_copy_without_changing_api(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, hosts='Synthetic Alpha'))
    expect(hosts_page.locator('.host-capture-status')).to_contain_text('8 models requested')
    history = hosts_page.get_by_role('region', name='Host history', exact=True)
    expect(history.get_by_role('columnheader', name='Models', exact=True)).to_be_visible()
    expect(history.get_by_role('table').locator('tbody tr').first).to_contain_text('8 models requested')
    expect(history.locator('svg title').first).to_contain_text('8 models requested')
    _switch_hash(hosts_page, _hosts_fragment(facts, hosts='Synthetic Missing'))
    expect(history.locator('.endpoint-truncation')).to_contain_text('these models')
    payload = hosts_page.request.get(_origin(hosts_server) + '/api/hosts?provider=' + facts.provider_id + '&scrape_id=' + str(facts.scrapes['first'])).json()
    assert '8 lists requested' in payload['capture']['status_line']


def test_hosts_default_ranking_retains_prompt_fallback_with_other_price_columns(hosts_page, hosts_server):
    _, facts = hosts_server

    def alternate_first_column(route):
        response = route.fetch()
        payload = response.json()
        payload['price_columns'].insert(0, {**payload['price_columns'][0], 'path': 'pricing.synthetic-first', 'label': 'Synthetic first'})
        for endpoint in payload['endpoints']:
            if 'pricing.prompt' in endpoint['prices']:
                endpoint['prices']['pricing.synthetic-first'] = endpoint['prices']['pricing.prompt']
        route.fulfill(response=response, json=payload)

    hosts_page.route(re.compile(r'/api/hosts\?'), alternate_first_column)
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    expect(hosts_page.get_by_label('Ranking', exact=True)).to_have_value('price:pricing.prompt')


@pytest.mark.parametrize('width', [319, 390, 1440])
def test_hosts_appearance_options_fit_visible_popup_without_scrolling(hosts_page, hosts_server, width):
    _, facts = hosts_server
    hosts_page.set_viewport_size({'width': width, 'height': 900})
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    hosts_page.get_by_text('Appearance', exact=True).click()
    popup = hosts_page.locator('.appearance > .segmented')
    row = popup.locator(':scope > div')
    assert row.evaluate('e => e.scrollWidth <= e.clientWidth')
    for label, value in [('System', None), ('Light', 'light'), ('Dark', 'dark')]:
        button = popup.get_by_role('button', name=label, exact=True)
        assert button.evaluate('''button => {
            const box = button.getBoundingClientRect();
            const row = button.parentElement.getBoundingClientRect();
            const panel = button.closest('fieldset').getBoundingClientRect();
            const visible = box.left >= Math.max(0, row.left, panel.left)
                && box.right <= Math.min(innerWidth, row.right, panel.right)
                && box.top >= Math.max(0, row.top, panel.top)
                && box.bottom <= Math.min(innerHeight, row.bottom, panel.bottom);
            const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
            return visible && (hit === button || button.contains(hit));
        }''')
        button.click()
        if value is None:
            expect(hosts_page.locator('html')).not_to_have_attribute('data-theme')
        else:
            expect(hosts_page.locator('html')).to_have_attribute('data-theme', value)
        expect(button).to_have_attribute('aria-pressed', 'true')


def test_hosts_menus_fixed_chrome_focus_and_grouped_supports(hosts_page, hosts_server):
    _, facts = hosts_server
    hosts_page.set_viewport_size({"width": 1440, "height": 1000})
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    hosts_page.get_by_role("button", name="Precision condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name="Precision", exact=True)
    search = dialog.get_by_role("searchbox", name="Filter precision…", exact=True)
    expect(search).to_be_focused()
    expect(dialog.get_by_role("button", name="Close", exact=True)).to_have_count(0)
    expect(dialog.locator("header")).to_contain_text("Allow ·")
    expect(dialog.locator("footer")).to_have_text("No effect yet")
    expect(dialog.locator(".condition-presets button")).to_have_text(["16-bit or better", "8-bit or better", "Any"])
    assert dialog.locator("../..").bounding_box()["width"] == 320
    assert dialog.locator("../..").bounding_box()["height"] <= 460
    assert dialog.evaluate("el => el.scrollHeight === el.clientHeight")
    options = dialog.locator(".option-list-options")
    first = dialog.get_by_role("checkbox").first.bounding_box()
    bounds = options.bounding_box()
    assert bounds["y"] <= first["y"] < bounds["y"] + bounds["height"]
    chrome = [dialog.locator("header"), search, dialog.locator(".condition-presets"), dialog.locator("footer")]
    positions = [element.bounding_box() for element in chrome]
    options.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    last = dialog.get_by_role("checkbox").last.bounding_box()
    assert bounds["y"] <= last["y"] < bounds["y"] + bounds["height"]
    assert [element.bounding_box() for element in chrome] == positions
    expect(dialog.get_by_role("checkbox")).to_have_count(12)
    search.fill("fp")
    expect(dialog.locator("mark")).not_to_have_count(0)
    search.press("ArrowDown")
    expect(dialog.get_by_role("checkbox", name="fp32", exact=True)).to_be_focused()
    expect(dialog.locator(".option-row:focus-within")).to_have_count(1)
    hosts_page.keyboard.press("Escape")
    hosts_page.get_by_role("button", name="Supports condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name="Supports", exact=True)
    expect(dialog.get_by_role("searchbox")).to_have_count(1)
    expect(dialog.locator("h4")).to_have_text(["Request parameters", "Native tools", "Caching"])
    expect(dialog.get_by_role("searchbox", name="Filter supports…", exact=True)).to_be_focused()
    expect(dialog.locator("header")).to_contain_text("Require ·")
    dialog.get_by_role("searchbox").fill("caching")
    expect(dialog.get_by_role("checkbox")).to_have_count(1)
    dialog.get_by_role("checkbox", name="implicit caching", exact=True).check()
    expect(hosts_page).to_have_url(re.compile("caching=1"))
    expect(dialog.locator("footer")).to_contain_text("Removes")
    expect(dialog.locator("footer")).to_contain_text("of 135 endpoints")
    dialog.get_by_role("button", name="Clear", exact=True).click()
    expect(hosts_page).not_to_have_url(re.compile("caching="))


def test_hosts_scope_only_normalization_empty_selection_and_history(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, xmode="invalid"))
    expect(hosts_page).not_to_have_url(re.compile("xmode="))
    trigger = hosts_page.get_by_role("button", name="Hosts condition", exact=True)
    trigger.click()
    dialog = hosts_page.get_by_role("dialog", name="Hosts", exact=True)
    dialog.get_by_role("button", name="Only these", exact=True).click()
    expect(trigger).to_have_attribute("aria-pressed", "false")
    expect(dialog.locator("footer")).to_have_text("No effect yet")
    dialog.get_by_role("checkbox", name="Synthetic Alpha", exact=True).check()
    expect(trigger).to_contain_text("only Synthetic Alpha")
    expect(hosts_page).to_have_url(re.compile("xmode=only"))
    only_count = hosts_page.locator(".hosts-count").inner_text()
    dialog.get_by_role("button", name="Exclude these", exact=True).click()
    expect(trigger).to_contain_text("excluding Synthetic Alpha")
    expect(hosts_page.locator(".hosts-count")).not_to_have_text(only_count)
    hosts_page.go_back()
    expect(trigger).to_contain_text("only Synthetic Alpha")
    expect(hosts_page.locator(".hosts-count")).to_have_text(only_count)
    hosts_page.go_forward()
    expect(trigger).to_contain_text("excluding Synthetic Alpha")
    dialog.get_by_role("checkbox", name="Synthetic Alpha", exact=True).uncheck()
    expect(trigger).to_have_attribute("aria-pressed", "false")
    expect(dialog.locator("footer")).to_have_text("No effect yet")


def test_hosts_picker_copy_and_uptime_toggle_price_presets(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    hosts_page.get_by_role("button", name="Add host", exact=True).click()
    picker = hosts_page.get_by_role("dialog", name="Compare hosts", exact=True)
    expect(picker.get_by_role("searchbox", name="Find a host…")).to_be_focused()
    expect(picker.locator("header")).to_contain_text("0 of")
    expect(picker.locator(".option-row small").first).to_contain_text("models")
    expect(picker.locator("footer")).to_have_text("Sorted by models served")
    picker.get_by_role("checkbox", name="Synthetic Alpha", exact=True).check()
    picker.get_by_role("button", name="Clear", exact=True).click()
    expect(hosts_page).not_to_have_url(re.compile(r"[&#]hosts="))
    hosts_page.keyboard.press("Escape")
    hosts_page.get_by_role("button", name="Uptime condition", exact=True).click()
    uptime = hosts_page.get_by_role("dialog", name="Uptime", exact=True)
    expect(uptime.get_by_label("Minimum uptime percent", exact=True)).to_be_focused()
    expect(uptime.get_by_label("Minimum uptime percent", exact=True)).to_have_attribute("placeholder", "e.g. 99.95")
    uptime.get_by_role("button", name="99.9%", exact=True).click()
    expect(uptime.get_by_role("button", name="99.9%", exact=True)).to_have_attribute("aria-pressed", "true")
    uptime.get_by_role("button", name="99.9%", exact=True).click()
    expect(hosts_page).not_to_have_url(re.compile("upmin="))
    uptime.get_by_role("button", name="30 min", exact=True).click()
    expect(hosts_page).to_have_url(re.compile("upwin=30m"))
    hosts_page.keyboard.press("Escape")
    hosts_page.get_by_role("button", name="Price condition", exact=True).click()
    price = hosts_page.get_by_role("dialog", name="Price", exact=True)
    expect(price.get_by_label("Maximum price", exact=True)).to_be_focused()
    price.get_by_label("Maximum price", exact=True).fill("7.000000000000000001")
    price.get_by_role("button", name="≤ $0.5", exact=True).click()
    hosts_page.wait_for_timeout(350)
    expect(price.get_by_label("Maximum price", exact=True)).to_have_value("0.5")
    expect(hosts_page).to_have_url(re.compile("plimit=pricing.prompt%3A0.5"))
    price.get_by_role("button", name="Clear", exact=True).click()
    expect(hosts_page).not_to_have_url(re.compile("plimit="))


def test_hosts_overflowing_options_scroll_under_fixed_chrome_and_zero_counts(hosts_page, hosts_server):
    _, facts = hosts_server

    def add_synthetic_options(route):
        response = route.fetch()
        payload = response.json()
        payload["vocab"]["parameters"] += [f"synthetic-empty-parameter-{index:03}" for index in range(80)]
        route.fulfill(response=response, json=payload)

    hosts_page.route(re.compile(r"/api/hosts\?"), add_synthetic_options)
    hosts_page.set_viewport_size({"width": 1440, "height": 1000})
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    hosts_page.get_by_role("button", name="Supports condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name="Supports", exact=True)
    options = dialog.locator(".option-list-options")
    assert options.evaluate("el => el.scrollHeight > el.clientHeight")
    header = dialog.locator("header").bounding_box()
    footer = dialog.locator("footer").bounding_box()
    search = dialog.get_by_role("searchbox").bounding_box()
    options.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    assert options.evaluate("el => el.scrollTop > 0")
    assert dialog.locator("header").bounding_box() == header
    assert dialog.locator("footer").bounding_box() == footer
    assert dialog.get_by_role("searchbox").bounding_box() == search
    empty = dialog.get_by_role("checkbox", name="synthetic-empty-parameter-079", exact=True).locator("..")
    expect(empty.locator("small")).to_have_text("0")
    assert empty.evaluate("el => getComputedStyle(el).opacity") == "0.45"
    empty.get_by_role("checkbox").check()
    expect(hosts_page).to_have_url(re.compile("params=synthetic-empty-parameter-079"))
    hosts_page.set_viewport_size({"width": 390, "height": 844})
    expect(dialog).to_be_visible()
    hosts_page.wait_for_function("() => document.querySelector('.condition-overlay').getBoundingClientRect().bottom === innerHeight")
    rect = dialog.bounding_box()
    assert rect["height"] <= 844 * .72
    assert rect["x"] >= 0 and rect["x"] + rect["width"] <= 390


@pytest.mark.parametrize("hosts_server", ["no_telemetry"], indirect=True)
def test_hosts_paused_uptime_focus_and_footer_without_close(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, upmin="99.99"))
    hosts_page.get_by_role("button", name="Uptime condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name="Uptime", exact=True)
    expect(dialog.locator("footer")).to_have_text("PausedClear")
    expect(dialog.get_by_role("button", name="Clear", exact=True)).to_be_focused()
    expect(dialog.get_by_role("button", name="Close", exact=True)).to_have_count(0)
    hosts_page.keyboard.press("Tab")
    expect(dialog.get_by_role("button", name="Clear", exact=True)).to_be_focused()
    dialog.get_by_role("button", name="Clear", exact=True).click()
    hosts_page.get_by_role("button", name="Uptime condition", exact=True).click()
    expect(dialog.get_by_role("heading", name="Uptime", exact=True)).to_be_focused()
    expect(dialog.locator("footer")).to_have_text("Paused")
    expect(dialog.get_by_role("button", name="Clear", exact=True)).to_have_count(0)
    hosts_page.keyboard.press("Escape")
    expect(hosts_page.get_by_role("button", name="Uptime condition", exact=True)).to_be_focused()


@pytest.mark.parametrize(("condition", "key", "committed", "field", "preset"), [
    ("Price", "plimit", "pricing.prompt:1", "Maximum price", "≤ $1"),
    ("Context", "ctxmin", "32K", "Minimum context length", "32K"),
])
def test_hosts_reselecting_preset_replaces_pending_draft(hosts_page, hosts_server, condition, key, committed, field, preset):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, **{key: committed}))
    hosts_page.get_by_role("button", name=f"{condition} condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name=condition, exact=True)
    dialog.get_by_label(field, exact=True).fill("7")
    dialog.get_by_role("button", name=preset, exact=True).click()
    expect(dialog.get_by_label(field, exact=True)).to_have_value(committed.split(":")[-1])
    hosts_page.wait_for_timeout(350)
    expect(hosts_page).to_have_url(re.compile(key + "=" + re.escape(quote(committed, safe=""))))


@pytest.mark.parametrize(("condition", "role", "field"), [
    ("Precision", "searchbox", "Filter precision…"),
    ("Tier", "searchbox", "Filter tier…"),
    ("Supports", "searchbox", "Filter supports…"),
    ("Hosts", "searchbox", "Filter hosts…"),
    ("Context", "textbox", "Minimum context length"),
    ("Max output", "textbox", "Minimum max output"),
    ("Price", "textbox", "Maximum price"),
    ("Uptime", "textbox", "Minimum uptime percent"),
    ("Status", "checkbox", "Normal status only"),
])
def test_hosts_each_menu_initial_focus_and_escape(hosts_page, hosts_server, condition, role, field):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    before = hosts_page.evaluate("location.hash")
    trigger = hosts_page.get_by_role("button", name=f"{condition} condition", exact=True)
    trigger.click()
    dialog = hosts_page.get_by_role("dialog", name=condition, exact=True)
    expect(dialog.get_by_role(role, name=field, exact=True)).to_be_focused()
    expect(dialog.get_by_role("button", name="Close", exact=True)).to_have_count(0)
    assert hosts_page.evaluate("location.hash") == before
    hosts_page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(trigger).to_be_focused()


def test_hosts_pending_uptime_recovers_after_snapshot_change(hosts_page, hosts_server):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts, providers=facts.single_provider_id, hasof=facts.scrapes["no_prices"], upmin="99.9"))
    trigger = hosts_page.get_by_role("button", name="Uptime condition", exact=True)
    trigger.click()
    dialog = hosts_page.get_by_role("dialog", name="Uptime", exact=True)
    expect(dialog.get_by_role("button", name="Clear", exact=True)).to_be_focused()
    expect(dialog.locator("footer")).to_have_text("PausedClear")
    expect(dialog.get_by_label("Minimum uptime percent", exact=True)).to_be_disabled()
    hosts_page.keyboard.press("Escape")
    _switch_hash(hosts_page, _hosts_fragment(facts, upmin="99.9"))
    expect(trigger).not_to_contain_text("paused")
    trigger.click()
    expect(dialog.get_by_label("Minimum uptime percent", exact=True)).to_be_focused()
    expect(dialog.get_by_label("Minimum uptime percent", exact=True)).to_have_value("99.9")
    expect(dialog.locator("footer")).to_contain_text("Removes")


@pytest.mark.parametrize("key", ["Tab", "Shift+Tab"])
@pytest.mark.parametrize("hosts_server", ["no_telemetry"], indirect=True)
def test_hosts_paused_unconfigured_uptime_keeps_heading_focus(hosts_page, hosts_server, key):
    _, facts = hosts_server
    goto(hosts_page, hosts_server, _hosts_fragment(facts))
    trigger = hosts_page.get_by_role("button", name="Uptime condition", exact=True)
    trigger.click()
    dialog = hosts_page.get_by_role("dialog", name="Uptime", exact=True)
    heading = dialog.get_by_role("heading", name="Uptime", exact=True)
    expect(heading).to_be_focused()
    expect(dialog.get_by_role("button", name="Clear", exact=True)).to_have_count(0)
    hosts_page.keyboard.press(key)
    expect(heading).to_be_focused()
    hosts_page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(trigger).to_be_focused()


@pytest.mark.parametrize("condition", ["Uptime", "Context", "Max output", "Price"])
def test_hosts_short_viewport_threshold_controls_are_reachable(hosts_page, hosts_server, condition):
    _, facts = hosts_server
    hosts_page.set_viewport_size({"width": 844, "height": 390})
    goto(hosts_page, hosts_server, _hosts_fragment(facts, upmin="99.9", ctxmin="32K", outmin="8K", plimit="pricing.prompt:5"))
    hosts_page.get_by_role("button", name=f"{condition} condition", exact=True).click()
    dialog = hosts_page.get_by_role("dialog", name=condition, exact=True)
    expect(dialog.locator('input[type="text"]')).to_be_focused()
    assert dialog.bounding_box()["width"] == 318
    body = dialog.locator(".condition-form-body")
    assert body.evaluate("el => el.scrollHeight > el.clientHeight")
    assert body.evaluate("el => el.scrollWidth === el.clientWidth")
    assert dialog.locator(".condition-segments").evaluate_all("elements => elements.every(el => el.scrollWidth <= el.clientWidth)")
    measurements = dialog.evaluate("""el => {
        const box = element => { const r = element.getBoundingClientRect(); return {top:r.top, bottom:r.bottom, height:r.height, width:r.width}; };
        return {overlay:box(el.closest('.condition-overlay')),panel:box(el),children:[...el.children].map(child => ({tag:child.tagName, text:child.textContent, ...box(child)}))};
    }""")
    chrome = [dialog.locator("header"), dialog.locator("footer")]
    positions = [element.bounding_box() for element in chrome]
    overlay = measurements["overlay"]
    for position in positions:
        assert overlay["top"] <= position["y"]
        assert position["y"] + position["height"] <= overlay["bottom"]
    for control in dialog.locator("input, select, button").all():
        control.scroll_into_view_if_needed()
        assert control.evaluate("""el => {
            const rect = el.getBoundingClientRect(), hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
            return rect.width > 0 && rect.height > 0 && (hit === el || el.contains(hit));
        }"""), f"Unreachable control {control.get_attribute('aria-label') or control.inner_text()}: {measurements}"
        assert [element.bounding_box() for element in chrome] == positions
    body.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    assert body.evaluate("el => el.scrollTop > 0")
    assert [element.bounding_box() for element in chrome] == positions
    assert dialog.evaluate("el => el.scrollHeight === el.clientHeight")
    assert dialog.locator("../..").evaluate("el => el.scrollTop === 0 && el.scrollHeight === el.clientHeight")


@pytest.mark.parametrize("upmin", ["", "99.9"])
@pytest.mark.parametrize("hosts_server", ["no_telemetry"], indirect=True)
def test_hosts_short_paused_uptime_keeps_chrome_fixed(hosts_page, hosts_server, upmin):
    _, facts = hosts_server
    hosts_page.set_viewport_size({"width": 844, "height": 390})
    goto(hosts_page, hosts_server, _hosts_fragment(facts, upmin=upmin))
    trigger = hosts_page.get_by_role("button", name="Uptime condition", exact=True)
    trigger.click()
    dialog = hosts_page.get_by_role("dialog", name="Uptime", exact=True)
    expected_focus = dialog.get_by_role("button", name="Clear", exact=True) if upmin else dialog.get_by_role("heading", name="Uptime", exact=True)
    expect(expected_focus).to_be_focused()
    body = dialog.locator(".condition-form-body")
    expect(dialog.locator(".uptime-unavailable")).to_be_visible()
    positions = [dialog.locator(tag).bounding_box() for tag in ("header", "footer")]
    body.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    assert body.evaluate("el => el.scrollTop > 0")
    assert [dialog.locator(tag).bounding_box() for tag in ("header", "footer")] == positions
    expect(dialog.locator("footer")).to_contain_text("Paused")
    assert dialog.locator("../..").evaluate("el => el.scrollTop === 0 && el.scrollHeight === el.clientHeight")
    if upmin:
        clear = dialog.get_by_role("button", name="Clear", exact=True)
        assert clear.evaluate("el => { const r=el.getBoundingClientRect(); return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2) === el; }")
        clear.click()
        expect(hosts_page).not_to_have_url(re.compile("upmin="))
    else:
        hosts_page.keyboard.press("Tab")
        expect(expected_focus).to_be_focused()
        hosts_page.keyboard.press("Shift+Tab")
        expect(expected_focus).to_be_focused()
        hosts_page.keyboard.press("Escape")
        expect(trigger).to_be_focused()
