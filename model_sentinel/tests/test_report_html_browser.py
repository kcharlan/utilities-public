"""Chromium checks of the scan report's endpoint and alias HTML.

The reports are written to a fresh temporary directory as the concise and
full-detail companion pair `cli.run_scan` writes, with reciprocal companion
links, and opened from `file://`. Every case fails on a page or console error
and on any request that is not a local `file://` read. All data is synthetic
(`tests/endpoint_report_fixtures.py`).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

from tests.endpoint_report_fixtures import _ep_html, _rich_html_result


def test_parameter_diff_price_placement_is_preserved(page, tmp_path):
    from model_sentinel import reporting
    from model_sentinel.models import FieldChange, ModelDelta
    from tests.test_reporting import _scan_result
    from model_sentinel.conditional_pricing import LiveComparisonIdentity, PricingComparisonEvent
    parameter = FieldChange("supported_parameters", ["synthetic-unchanged", "synthetic-removed"], ["synthetic-unchanged", "synthetic-added"])
    deltas = (
        ModelDelta("changed", "synthetic/capability-only", "Synthetic Capability", (parameter,)),
        ModelDelta("changed", "synthetic/mixed-price", "Synthetic Mixed", (parameter, FieldChange("pricing.prompt", "0.000001", "0.000002"))),
    )
    result = _scan_result(deltas)
    cores = {}
    for delta in deltas:
        event = PricingComparisonEvent(LiveComparisonIdentity("openrouter", delta.provider_model_id, 1, 2), "openrouter", delta.provider_model_id, delta.display_name, "2030-01-02T00:00:00+00:00", None, None, delta.field_changes, None, None)
        cores[event.identity] = reporting.build_model_event_semantic_core(event, result.profile)
    for mode in ("default", "all"):
        path = tmp_path / f"parameter-{mode}.html"
        path.write_text(reporting.render_scan_report(generated_at="2030-01-02T00:00:00+00:00", command="scan", format_name="html", provider_results=[result], semantic_cores=cores, detail_policy=reporting.make_report_detail_policy(mode=mode)), encoding="utf-8")
        _open(page, path)
        mixed = page.locator(".model-card").filter(has=page.locator(".model-card-header code", has_text="synthetic/mixed-price"))
        capability = page.locator(".model-card").filter(has=page.locator(".model-card-header code", has_text="synthetic/capability-only"))
        assert not mixed.evaluate("element => !!element.closest('details')")
        assert capability.evaluate("element => !!element.closest('details')")
        expect(mixed).to_contain_text(re.compile(r"\+\s*synthetic-added"))
        expect(mixed).to_contain_text(re.compile(r"−\s*synthetic-removed"))
        expect(mixed).not_to_contain_text("synthetic-unchanged")
        capability.evaluate("element => element.closest('details').open = true")
        expect(capability).to_be_visible()
        expect(capability).to_contain_text(re.compile(r"\+\s*synthetic-added"))

CONCISE_NAME = "scan_20300102_030406.html"
FULL_NAME = "scan_20300102_030406_full.html"
NARROW = {"width": 375, "height": 812}
DESKTOP = {"width": 1280, "height": 900}


@pytest.fixture(scope="module")
def report_pair(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """The concise and full-detail companions, linked to each other."""
    directory = tmp_path_factory.mktemp("endpoint-html")
    result = _rich_html_result()
    concise = directory / CONCISE_NAME
    full = directory / FULL_NAME
    concise.write_text(_ep_html(result, companion_link=(FULL_NAME, "Full-detail report →")), encoding="utf-8")
    full.write_text(_ep_html(result, "all", companion_link=(CONCISE_NAME, "← Concise report")), encoding="utf-8")
    return {"concise": concise, "full": full}


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(viewport=DESKTOP)
    external: list[str] = []

    def guard(route) -> None:
        if route.request.url.startswith("file://"):
            route.continue_()
        else:
            external.append(route.request.url)
            route.abort()

    context.route("**/*", guard)
    instance = context.new_page()
    page_errors: list[str] = []
    console_errors: list[str] = []
    instance.on("pageerror", lambda error: page_errors.append(str(error)))
    instance.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    try:
        yield instance
    finally:
        context.close()
    assert page_errors == []
    assert console_errors == []
    assert external == []


def _open(page: Page, path: Path, fragment: str = "") -> None:
    page.goto(path.as_uri() + fragment)
    page.wait_for_load_state("load")


def _open_disclosure(page: Page) -> None:
    disclosure = page.locator("details#provider-endpoints")
    if not disclosure.evaluate("element => element.open"):
        disclosure.locator("> summary").click()
    expect(page.locator(".endpoint-list").first).to_be_visible()


def _open_alias_details(page: Page) -> None:
    """Open every alias event's endpoint detail by its own summary."""
    summaries = page.locator("details.alias-detail:not([open]) > summary")
    while summaries.count():
        summaries.first.click()
    expect(page.locator("svg.ladder-svg").first).to_be_visible()


def _no_page_overflow(page: Page) -> None:
    scroll_width, inner_width = page.evaluate(
        "() => [document.documentElement.scrollWidth, window.innerWidth]"
    )
    assert scroll_width <= inner_width, (scroll_width, inner_width)


def test_endpoint_disclosure_is_closed_by_default_and_opens_natively(page: Page, report_pair) -> None:
    for name in ("concise", "full"):
        _open(page, report_pair[name])
        disclosure = page.locator("details#provider-endpoints")
        assert disclosure.evaluate("element => element.open") is False
        expect(disclosure.locator("> summary")).to_contain_text("Provider endpoints —")
        expect(page.locator(".endpoint-list").first).to_be_hidden()
        _open_disclosure(page)
        assert disclosure.evaluate("element => element.open") is True
    # The alias events are on the open page, after the Price Movement card.
    expect(page.locator("#alias-check")).to_be_visible()
    order = page.evaluate(
        "() => Boolean(document.getElementById('price-movement').compareDocumentPosition("
        "document.getElementById('alias-check')) & Node.DOCUMENT_POSITION_FOLLOWING)"
    )
    assert order is True


def test_endpoint_price_and_field_table_columns_align(page: Page, report_pair) -> None:
    _open(page, report_pair["full"])
    _open_disclosure(page)
    tables = page.locator("table.endpoint-price-table")
    assert tables.count() > 1
    for index in range(tables.count()):
        geometry = tables.nth(index).evaluate(
            """table => {
                const box = cell => { const r = cell.getBoundingClientRect(); return [r.left, r.right]; };
                const header = [...table.tHead.rows[0].cells].map(box);
                const rows = [...table.tBodies[0].rows].map(row => [...row.cells].map(box));
                return {header, rows};
            }"""
        )
        header = geometry["header"]
        for row in geometry["rows"]:
            assert len(row) == len(header)
            for (left, right), (head_left, head_right) in zip(row, header):
                assert abs(left - head_left) < 0.5 and abs(right - head_right) < 0.5
    field_tables = page.locator("table.endpoint-field-table")
    assert field_tables.count() >= 1
    columns = field_tables.first.evaluate(
        """table => [...table.tBodies[0].rows]
            .filter(row => row.cells.length === 8)
            .map(row => [...row.cells].map(cell => Math.round(cell.getBoundingClientRect().left)))"""
    )
    assert len(columns) >= 2 and all(row == columns[0] for row in columns)


def test_endpoint_ladders_are_accessible_images_with_text_equivalents(page: Page, report_pair) -> None:
    _open(page, report_pair["concise"])
    _open_disclosure(page)
    _open_alias_details(page)
    ladders = page.get_by_role("img", name=re.compile(r"^Input price ladder: endpoints of "))
    expect(ladders.first).to_be_visible()
    count = page.locator("svg.ladder-svg").count()
    assert count >= 2  # the new divergence and, inside the disclosure, the persisting one
    for index in range(count):
        svg = page.locator("svg.ladder-svg").nth(index)
        described = svg.get_attribute("aria-describedby")
        caption = page.locator(f"#{described}")
        assert caption.evaluate("element => element.tagName") == "FIGCAPTION"
        assert caption.locator("li").count() == svg.locator("g.ladder-point").count()
        # Every placed position carries its own tooltip title.
        assert svg.locator("g.ladder-point > title").count() == svg.locator("g.ladder-point").count()
    first_caption = page.locator("figcaption.ladder-text").first
    expect(first_caption).to_contain_text("alias price")
    expect(first_caption).to_contain_text("target price")
    expect(first_caption).to_contain_text("Not placed: free-host#0 (free)")
    # Neutral marks: no cost color on any ladder glyph.
    fills = page.evaluate(
        """() => [...document.querySelectorAll('.ladder-endpoint, .ladder-mark')]
            .map(node => getComputedStyle(node).fill + '|' + getComputedStyle(node).stroke)"""
    )
    red, green = "rgb(248, 113, 113)", "rgb(52, 211, 153)"
    assert fills and not any(red in value or green in value for value in fills)


def test_alias_rate_card_collapses_detail_and_marks_reference_prices(page: Page, report_pair) -> None:
    violet = "rgb(167, 139, 250)"
    _open(page, report_pair["concise"])
    event = page.locator("#alias-check article.alias-event").first
    # The rate card and its strips are the collapsed view; the ladders wait
    # behind the event's own disclosure.
    expect(event.locator("table.alias-rates")).to_be_visible()
    expect(event.locator(".price-strip").first).to_be_visible()
    detail = event.locator("details.alias-detail")
    assert detail.evaluate("element => element.open") is False
    expect(event.locator("svg.ladder-svg").first).to_be_hidden()
    # Alias and target values, marks and matching dots carry the reference color.
    value = event.locator("td.ref-alias .ref-value").first
    assert value.evaluate("node => getComputedStyle(node).color") == violet
    assert int(value.evaluate("node => getComputedStyle(node).fontWeight")) >= 700
    assert event.locator(".strip-mark-alias").first.evaluate("node => getComputedStyle(node).borderTopColor") == violet
    assert event.locator(".strip-mark-target").first.evaluate("node => getComputedStyle(node).borderTopColor") == violet
    # Raw values ride the page's toggle.
    raw = event.locator("td.ref-alias .ep-raw").first
    expect(raw).to_be_hidden()
    page.locator("#show-raw").check()
    expect(raw).to_be_visible()
    # Opening the detail shows each ladder under its heading, with the
    # reference rows banded apart from the plain endpoint rows.
    detail.locator("> summary").click()
    figure = event.locator("figure.price-ladder").first
    expect(figure.locator("svg.ladder-svg")).to_be_visible()
    expect(figure.locator(".ladder-heading")).to_have_text(re.compile(r"^Input /1M tokens, log scale$"))
    heading_box = figure.locator(".ladder-heading").bounding_box()
    svg_box = figure.locator("svg.ladder-svg").bounding_box()
    assert heading_box["y"] + heading_box["height"] <= svg_box["y"]
    styles = figure.evaluate(
        """figure => [...figure.querySelectorAll('figcaption li')].map(li => ({
            ref: li.classList.contains('ladder-ref'),
            background: getComputedStyle(li).backgroundColor,
            weight: Number(getComputedStyle(li).fontWeight)}))"""
    )
    refs = [style for style in styles if style["ref"]]
    plain = [style for style in styles if not style["ref"]]
    assert refs and plain
    assert all(style["background"] != plain[0]["background"] and style["weight"] >= 600 for style in refs)
    assert figure.locator(".ladder-mark-alias").evaluate("node => getComputedStyle(node).fill") == violet
    # The full-detail companion opens every endpoint detail.
    _open(page, report_pair["full"])
    assert page.locator("details.alias-detail").first.evaluate("element => element.open") is True


def _label_boxes(page: Page) -> list[list[dict]]:
    return page.evaluate(
        """() => [...document.querySelectorAll('svg.ladder-svg')].map(svg => {
            const frame = svg.getBoundingClientRect();
            return [...svg.querySelectorAll('text.ladder-label, text.ladder-domain')].map(text => {
                const r = text.getBoundingClientRect();
                return {left: r.left - frame.left, right: r.right - frame.left,
                        top: r.top - frame.top, bottom: r.bottom - frame.top,
                        width: frame.width, height: frame.height, text: text.textContent};
            });
        })"""
    )


@pytest.mark.parametrize("viewport", [DESKTOP, NARROW], ids=["desktop", "narrow"])
def test_endpoint_ladder_labels_never_collide_and_narrow_pages_do_not_overflow(
    page: Page, report_pair, viewport
) -> None:
    page.set_viewport_size(viewport)
    for name in ("concise", "full"):
        _open(page, report_pair[name])
        _open_disclosure(page)
        _open_alias_details(page)
        _no_page_overflow(page)
        ladders = _label_boxes(page)
        assert ladders
        for boxes in ladders:
            for index, box in enumerate(boxes):
                assert box["left"] >= 0 and box["right"] <= box["width"], box
                assert box["top"] >= 0 and box["bottom"] <= box["height"], box
                for other in boxes[index + 1 :]:
                    overlap = (
                        box["left"] < other["right"] - 0.5
                        and other["left"] < box["right"] - 0.5
                        and box["top"] < other["bottom"] - 0.5
                        and other["top"] < box["bottom"] - 0.5
                    )
                    assert not overlap, (box, other)
    if viewport is NARROW:
        # The ladder keeps its legible size and scrolls inside its own frame.
        scroll = page.locator(".ladder-scroll").first
        assert scroll.evaluate("element => element.scrollWidth > element.clientWidth")
        tables = page.locator(".endpoint-table-wrap")
        assert tables.first.evaluate("element => element.clientWidth <= window.innerWidth")


def test_endpoint_price_cells_keep_raw_evidence(page: Page, report_pair) -> None:
    _open(page, report_pair["concise"])
    _open_disclosure(page)
    cell = page.locator("table.endpoint-price-table td.ep-price.sem-cost-up").first
    assert "0.000001 (1.0e-6) × 1,000,000 = $1.00" in cell.get_attribute("title")
    raw = cell.locator(".ep-raw")
    expect(raw).to_be_hidden()
    page.locator("#show-raw").check()
    expect(raw).to_be_visible()
    expect(raw).to_have_text("0.000001 → 0.000002")
    # The full-detail companion shows raw values by default.
    _open(page, report_pair["full"])
    _open_disclosure(page)
    expect(page.locator("table.endpoint-price-table .ep-raw").first).to_be_visible()


def test_endpoint_cap_navigation_links_the_companions_both_ways(page: Page, report_pair) -> None:
    _open(page, report_pair["concise"])
    _open_disclosure(page)
    concise_lists = page.locator(".endpoint-list").count()
    omitted = page.locator("p.endpoint-omitted")
    expect(omitted).to_contain_text("2 more changed lists not shown")
    omitted.get_by_role("link", name="Full-detail report →").click()
    expect(page).to_have_url(re.compile(re.escape(FULL_NAME) + "#provider-endpoints$"))
    # The landed-on disclosure is the target; the reader opens it natively.
    assert page.evaluate("() => document.querySelector(':target').id") == "provider-endpoints"
    _open_disclosure(page)
    assert page.locator(".endpoint-list").count() == concise_lists + 2
    expect(page.locator("p.endpoint-omitted")).to_have_count(0)
    page.locator("p.endpoint-back").get_by_role("link", name="← Concise report").click()
    expect(page).to_have_url(re.compile(re.escape(CONCISE_NAME) + "#provider-endpoints$"))
    assert page.evaluate("() => document.querySelector(':target').id") == "provider-endpoints"
