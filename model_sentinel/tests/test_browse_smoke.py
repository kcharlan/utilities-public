from __future__ import annotations

import hashlib
import os
import re
import shutil
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
    FixtureFacts,
    browse_context,
    browse_settings,
    build_fixture_db,
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
    expect(table.locator("thead th")).to_have_text(["Endpoint", "Status", "Input/1M tokens", "Output/1M tokens"])
    first = table.locator("tbody tr").first
    expect(first.locator("td")).to_have_text(["0", "$2.00", "$10.00"])
    expect(first.locator("td").nth(1)).to_have_attribute("title", "raw 0.000002")

    capture = section.locator(".endpoint-capture")
    expect(capture).to_contain_text(f"#{endpoint.third_capture} · partial")
    expect(capture).to_contain_text(f"Compared with the capture of snapshot #{endpoint.first_scrape}.")
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
        "Endpoint fake-host-2#0 carries the alias's Input and Output prices."
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
        endpoint.failed_model: "This model's endpoint list failed to fetch during the scan, so the saved capture has no endpoints for it.",
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
        " while MODEL_SENTINEL_ENDPOINT_CAPTURE is on."
    )

    # Valid capture with a missing selected-baseline capture is still shown.
    section = open_endpoint_dossier(endpoint_page, endpoint_server, endpoint.rebased_model)
    expect(section.locator("table.endpoint-table tbody tr")).to_have_count(1)
    expect(section.locator(".endpoint-capture")).to_contain_text(
        "The selected catalog baseline has no endpoint capture, so endpoint lists were not compared."
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
                    " while MODEL_SENTINEL_ENDPOINT_CAPTURE is on."
                )
                # The alias is still compared on the catalog snapshot.
                expect(section.locator(".endpoint-alias .alias-leaves li")).to_have_count(1)
                expect(section.locator(".endpoint-alias .alias-match")).to_have_text(
                    "Endpoint matching unavailable: no endpoint lists were captured in this scan."
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
    expect(state.locator(".endpoint-failure")).to_have_text(f"{code}: {message}")
    expect(state).to_contain_text(endpoint.failed_path)
    expect(state.locator(".endpoint-gaps li")).to_have_text(
        ["the baseline list failed to fetch; not compared", "the current list failed to fetch; not compared"]
    )
    _assert_local_retry(endpoint_page, endpoint_server, section)


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
    expect(capture).to_contain_text(f"#{endpoint.error_capture} · error")
    expect(capture).to_contain_text("0 of 0 paths attempted")
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
    browser: Browser, tmp_path: Path, monkeypatch, capsys
) -> None:
    """Serve fixture-defined endpoint dossiers through `run_browse` on port 0
    and inspect them in both maintained themes.

    Screenshots go to this test's private directory; set
    MODEL_SENTINEL_ACCEPTANCE_SCREENSHOTS to also copy them elsewhere for review.
    """
    database_path = tmp_path / "acceptance.db"
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
    shots = tmp_path / "screens"
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
