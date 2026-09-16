from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

from model_sentinel.browse.readonly import open_readonly
from model_sentinel.browse.server import make_server
from tests.browse_fixtures import FixtureFacts, browse_context, build_fixture_db


@pytest.fixture(scope="module")
def smoke_server(tmp_path_factory: pytest.TempPathFactory):
    database_path = tmp_path_factory.mktemp("browse-smoke") / "fixture.db"
    facts = build_fixture_db(database_path)
    db = open_readonly(database_path)
    server = make_server(browse_context(db), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, facts
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    db.close_all()


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context()
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
    context.close()


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
