from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from importlib import resources
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit

import pytest


ASSETS = resources.files("model_sentinel.browse").joinpath("assets")
VENDOR_PAYLOADS = {
    "preact.umd.js": (
        "10.29.8",
        "https://unpkg.com/preact@10.29.8/dist/preact.umd.js",
        "134b77bc803fa38661dc1b1e44e96eb0bb6a1a00edbb96d34dcde421b2e80b06",
    ),
    "hooks.umd.js": (
        "10.29.8",
        "https://unpkg.com/preact@10.29.8/hooks/dist/hooks.umd.js",
        "5c29238e5dc99df306d7f7fff038591a397cfcfabb59f81fbdef43d670aa0566",
    ),
    "htm.umd.js": (
        "3.1.1",
        "https://unpkg.com/htm@3.1.1/dist/htm.umd.js",
        "7a31776e04bd4afde0d4308177d26f377716fcf7e4bd70be590746d6aa594f08",
    ),
    "uPlot.iife.min.js": (
        "1.6.32",
        "https://unpkg.com/uplot@1.6.32/dist/uPlot.iife.min.js",
        "19c8d4c6ad88929a79f4ae49d6f7161566dfd0ba3d15cc495e974f787eb78f1f",
    ),
    "uPlot.min.css": (
        "1.6.32",
        "https://unpkg.com/uplot@1.6.32/dist/uPlot.min.css",
        "df630c6a8d6f8eeaff264b50f73ce5b114f646ffd9a0bb74f049b0a00135fa04",
    ),
}
LICENSE_PAYLOADS = {
    "preact.LICENSE": (
        "10.29.8",
        "https://unpkg.com/preact@10.29.8/LICENSE",
        "1fe6958409c8c257a70c587a18b6f7f412b179b456630790d30b2ec9a8e4b7d4",
    ),
    "htm.LICENSE": (
        "3.1.1",
        "https://unpkg.com/htm@3.1.1/LICENSE",
        "740725f7252e750af735d0028cc534970772f513331e9f68150fede8fb3ce00f",
    ),
    "uplot.LICENSE": (
        "1.6.32",
        "https://unpkg.com/uplot@1.6.32/LICENSE",
        "8f989229699b4fe2f1a0432d0e9edc338a8a911e250e2d1b01ecd770a5f5b1bd",
    ),
}
EXPECTED_VENDOR_FILES = {*VENDOR_PAYLOADS, *LICENSE_PAYLOADS, "VERSIONS.md"}
EXPECTED_DEPENDENCIES = [
    ("link", "href", "vendor/uPlot.min.css"),
    ("link", "href", "app.css"),
    ("script", "src", "vendor/preact.umd.js"),
    ("script", "src", "vendor/hooks.umd.js"),
    ("script", "src", "vendor/htm.umd.js"),
    ("script", "src", "vendor/uPlot.iife.min.js"),
    ("script", "src", "app.js"),
]


def _read_asset(*parts: str) -> str:
    return ASSETS.joinpath(*parts).read_text(encoding="utf-8")


HTTP_URL = re.compile(r"https?://", re.IGNORECASE)
PROTOCOL_RELATIVE_LITERAL = re.compile(r"//(?=\S)")


def _assert_no_external_url(source: str, *, label: str) -> None:
    assert HTTP_URL.search(source) is None, f"external URL in {label}"
    assert (
        PROTOCOL_RELATIVE_LITERAL.search(source) is None
    ), f"protocol-relative URL in {label}"


def _without_svg_namespace_attributes(source: str) -> str:
    """Mask the namespace URI only inside a real quoted `<svg xmlns=...>` tag."""
    svg_start = re.compile(r"<svg(?=[\s>])", re.IGNORECASE)
    namespace = re.compile(
        r"""(?<![A-Za-z0-9_:-])xmlns\s*=\s*(["'])http://www\.w3\.org/2000/svg\1""",
        re.IGNORECASE,
    )
    output: list[str] = []
    cursor = 0
    while match := svg_start.search(source, cursor):
        index = match.end()
        quote: str | None = None
        escaped = False
        while index < len(source):
            char = source[index]
            if quote is not None:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in {'"', "'"}:
                quote = char
            elif char == ">":
                break
            index += 1
        if index >= len(source):
            break
        output.append(source[cursor : match.start()])
        output.append(namespace.sub('xmlns=""', source[match.start() : index + 1]))
        cursor = index + 1
    output.append(source[cursor:])
    return "".join(output)


def _assert_authored_source_offline(source: str, *, label: str) -> None:
    """Reject URLs in raw first-party source, including comments.

    This deliberately stronger static policy scans before comment removal, so
    regex/division/template parsing cannot erase an external URL. The sole
    exception is the standard SVG namespace as a quoted `xmlns` attribute
    inside the same actual `<svg ...>` start tag. As a conservative tradeoff,
    no-space line comments such as `//TODO` are forbidden; use `// TODO`.
    """
    _assert_no_external_url(_without_svg_namespace_attributes(source), label=label)


def _assert_js_offline(source: str) -> None:
    _assert_authored_source_offline(source, label="JavaScript")


class _AssetHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.attributes: list[tuple[str, str, str]] = []
        self.elements: list[tuple[int, str, list[tuple[str, str | None]]]] = []
        self.references: list[tuple[str, str, str]] = []
        self.reference_events: list[int] = []
        self.inline_scripts: list[tuple[int, str]] = []
        self.inline_styles: list[tuple[int, str]] = []
        self._capture: tuple[str, int, list[str]] | None = None
        self._event = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._event += 1
        self.elements.append((self._event, tag, attrs))
        values = dict(attrs)
        for name, value in attrs:
            if value is None:
                continue
            self.attributes.append((tag, name, value))
            if name in {"src", "href"}:
                self.references.append((tag, name, value))
                self.reference_events.append(self._event)
        if tag == "script" and "src" not in values:
            self._capture = (tag, self._event, [])
        elif tag == "style":
            self._capture = (tag, self._event, [])

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._capture[2].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture is None or self._capture[0] != tag:
            return
        _, event, chunks = self._capture
        target = self.inline_scripts if tag == "script" else self.inline_styles
        target.append((event, "".join(chunks)))
        self._capture = None


def _parse_html(source: str) -> _AssetHTMLParser:
    parser = _AssetHTMLParser()
    parser.feed(source)
    parser.close()
    return parser


REQUIRED_CSP = {
    "default-src": ("'self'",),
    "connect-src": ("'self'",),
    "script-src": ("'self'", "'unsafe-inline'"),
    "style-src": ("'self'", "'unsafe-inline'"),
    "img-src": ("'self'", "data:"),
    "object-src": ("'none'",),
    "base-uri": ("'none'",),
}


def _assert_csp_contract(source: str) -> None:
    parser = _parse_html(source)
    csp_meta = [
        (event, dict(attrs))
        for event, tag, attrs in parser.elements
        if tag == "meta"
        and (dict(attrs).get("http-equiv") or "").lower()
        == "content-security-policy"
    ]
    assert len(csp_meta) == 1
    event, attributes = csp_meta[0]
    runtime_events = [
        candidate
        for candidate, tag, _ in parser.elements
        if tag in {"script", "link"}
    ]
    assert runtime_events and event < min(runtime_events)

    directives: dict[str, tuple[str, ...]] = {}
    for raw_directive in (attributes.get("content") or "").split(";"):
        parts = raw_directive.split()
        if not parts:
            continue
        name, *values = parts
        assert name not in directives
        directives[name] = tuple(values)
    for name, expected in REQUIRED_CSP.items():
        assert directives.get(name) == expected


def _assert_html_offline(source: str) -> None:
    parser = _parse_html(source)
    svg_namespace = "http://www.w3.org/2000/svg"
    for tag, name, value in parser.attributes:
        if tag == "svg" and name == "xmlns" and value == svg_namespace:
            continue
        _assert_no_external_url(value, label=f"<{tag}> {name}")
    for _, script in parser.inline_scripts:
        _assert_js_offline(script)
    for _, style in parser.inline_styles:
        _assert_authored_source_offline(style, label="inline style")


def _validated_reference(reference: str) -> PurePosixPath:
    parsed = urlsplit(reference)
    path = PurePosixPath(parsed.path)
    assert not parsed.scheme, f"scheme in reference {reference!r}"
    assert not parsed.netloc, f"network location in reference {reference!r}"
    assert not parsed.query, f"query in reference {reference!r}"
    assert not parsed.fragment, f"fragment in reference {reference!r}"
    assert parsed.path, f"empty path in reference {reference!r}"
    assert not path.is_absolute(), f"absolute path in reference {reference!r}"
    assert ".." not in path.parts, f"path traversal in reference {reference!r}"
    return path


def _assert_dependency_contract(source: str) -> _AssetHTMLParser:
    parser = _parse_html(source)
    assert parser.references == EXPECTED_DEPENDENCIES
    assert len(parser.inline_scripts) == 1
    assert not parser.inline_styles
    first_link_event = next(
        event
        for event, (tag, _, _) in zip(
            parser.reference_events, parser.references, strict=True
        )
        if tag == "link"
    )
    assert parser.inline_scripts[0][0] < first_link_event

    links = [attrs for _, tag, attrs in parser.elements if tag == "link"]
    expected_links = [
        {"rel": "stylesheet", "href": reference}
        for tag, _, reference in EXPECTED_DEPENDENCIES
        if tag == "link"
    ]
    assert [dict(attrs) for attrs in links] == expected_links

    scripts = [
        attrs
        for _, tag, attrs in parser.elements
        if tag == "script" and "src" in dict(attrs)
    ]
    expected_scripts = [reference for tag, _, reference in EXPECTED_DEPENDENCIES if tag == "script"]
    expected_script_attributes = [
        {"defer": None, "src": source} for source in expected_scripts
    ]
    assert [dict(attrs) for attrs in scripts] == expected_script_attributes
    return parser


def _table_rows(markdown: str, heading: str) -> dict[str, tuple[str, str, str]]:
    lines = markdown.splitlines()
    try:
        heading_index = lines.index(heading)
        section_end = next(
            (
                index
                for index in range(heading_index + 1, len(lines))
                if lines[index].startswith("## ")
            ),
            len(lines),
        )
        header_index = next(
            index
            for index in range(heading_index + 1, section_end)
            if lines[index].strip()
        )
    except (ValueError, StopIteration) as exc:
        raise ValueError(f"missing manifest section {heading}") from exc
    if lines[header_index].strip() != "| File | Version | Exact source URL | SHA-256 |":
        raise ValueError(f"invalid table header in {heading}")
    separator_index = header_index + 1
    if separator_index >= len(lines) or not re.fullmatch(
        r"\|[-:|]+\|", lines[separator_index].replace(" ", "")
    ):
        raise ValueError(f"invalid table separator in {heading}")

    if any(line.strip() for line in lines[heading_index + 1 : header_index]):
        raise ValueError(f"unexpected content before table in {heading}")

    rows: dict[str, tuple[str, str, str]] = {}
    for line in lines[separator_index + 1 : section_end]:
        if not line.strip():
            continue
        if not line.startswith("|"):
            raise ValueError(f"unexpected content after table in {heading}")
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not all(cells):
            raise ValueError(f"invalid manifest row in {heading}")
        filename, version, url, digest = cells
        if filename in rows:
            raise ValueError(f"duplicate manifest row for {filename}")
        rows[filename] = (version, url, digest)
    return rows


def _validated_manifest_table(
    markdown: str,
    heading: str,
    expected: dict[str, tuple[str, str, str]],
) -> dict[str, tuple[str, str, str]]:
    rows = _table_rows(markdown, heading)
    if rows != expected:
        raise ValueError(f"manifest rows differ in {heading}")
    return rows


def _assert_sha256(payload: bytes, expected: str) -> None:
    assert hashlib.sha256(payload).hexdigest() == expected


def _manifest_fixture(rows: dict[str, tuple[str, str, str]]) -> str:
    body = "\n".join(
        f"| `{filename}` | `{version}` | `{url}` | `{digest}` |"
        for filename, (version, url, digest) in rows.items()
    )
    return (
        "## Runtime payloads\n\n"
        "| File | Version | Exact source URL | SHA-256 |\n"
        "|---|---:|---|---|\n"
        f"{body}"
    )


def test_first_party_assets_contain_no_external_urls() -> None:
    _assert_html_offline(_read_asset("index.html"))
    _assert_authored_source_offline(_read_asset("app.css"), label="app.css")
    _assert_js_offline(_read_asset("app.js"))


def test_raw_authored_scanning_rejects_external_urls() -> None:
    cases = [
        ("css", ".panel { background: url(https://evil.invalid/pixel); }"),
        ("js", "fetch('https://evil.invalid/data')"),
        ("js", "const remote = 'https://evil.invalid/data';"),
    ]
    for language, source in cases:
        with pytest.raises(AssertionError):
            _assert_authored_source_offline(source, label=language)


def test_raw_authored_scanning_allows_local_fetch() -> None:
    javascript = """
      fetch("/api/meta");
      fetch("api/activity");
    """
    _assert_js_offline(javascript)


@pytest.mark.parametrize(
    "source",
    [
        'const remote = "//evil.invalid/data";',
        "const remote = `//evil.invalid/data`;",
        ".panel { background: url(//evil.invalid/pixel); }",
        "// //evil.invalid/path",
        "/* //evil.invalid/path */",
        'const remote = "//[2001:db8::1]/path";',
        ".panel { background: url(//[2001:db8::1]/pixel); }",
        'const remote = "//user@example.invalid/path";',
        'const remote = "//%65vil.invalid/path";',
        "//TODO",
    ],
)
def test_protocol_relative_literals_are_rejected(source: str) -> None:
    with pytest.raises(AssertionError):
        _assert_authored_source_offline(source, label="authored source")


def test_html_scanning_uses_actual_attributes_and_inline_languages() -> None:
    external_cases = [
        '<img src="https://evil.invalid/pixel">',
        '<div data-source="//evil.invalid/data"></div>',
        '<script>fetch("https://evil.invalid/data")</script>',
        '<style>.x { background: url(https://evil.invalid/pixel); }</style>',
        '<div xmlns="http://www.w3.org/2000/svg"></div>',
    ]
    for source in external_cases:
        with pytest.raises(AssertionError):
            _assert_html_offline(source)

    allowed = """
      <!-- <script src="https://comment.invalid/app.js"></script> -->
      <svg xmlns="http://www.w3.org/2000/svg"></svg>
      <script>fetch("/api/meta")</script>
      <style>.x { color: inherit; }</style>
    """
    _assert_html_offline(allowed)


@pytest.mark.parametrize(
    "reference",
    [
        "app.js?v=1",
        "app.js#boot",
        "https://evil.invalid/app.js",
        "//evil.invalid/app.js",
        "/app.js",
        "../app.js",
        "data:text/javascript,alert(1)",
    ],
)
def test_unsafe_index_references_are_rejected(reference: str) -> None:
    with pytest.raises(AssertionError):
        _validated_reference(reference)


def test_every_index_reference_is_safe_local_and_exists() -> None:
    parser = _assert_dependency_contract(_read_asset("index.html"))
    for _, _, reference in parser.references:
        path = _validated_reference(reference)
        assert ASSETS.joinpath(*path.parts).is_file(), f"missing {reference!r}"


def test_dependency_contract_ignores_decoys_and_rejects_reordering() -> None:
    decoy = "<!-- vendor/uPlot.min.css app.css vendor/preact.umd.js app.js -->"
    with pytest.raises(AssertionError):
        _assert_dependency_contract(decoy)

    actual = _read_asset("index.html")
    reordered = actual.replace(
        '<link rel="stylesheet" href="vendor/uPlot.min.css">\n'
        '  <link rel="stylesheet" href="app.css">',
        '<link rel="stylesheet" href="app.css">\n'
        '  <link rel="stylesheet" href="vendor/uPlot.min.css">',
    )
    with pytest.raises(AssertionError):
        _assert_dependency_contract(reordered)


def test_manifest_tables_are_exact_and_every_vendor_file_is_hashed() -> None:
    markdown = _read_asset("vendor", "VERSIONS.md")
    runtime = _validated_manifest_table(
        markdown, "## Runtime payloads", VENDOR_PAYLOADS
    )
    licenses = _validated_manifest_table(
        markdown, "## License texts", LICENSE_PAYLOADS
    )
    assert {child.name for child in ASSETS.joinpath("vendor").iterdir()} == (
        EXPECTED_VENDOR_FILES
    )
    for filename, (_, _, expected_hash) in {**runtime, **licenses}.items():
        _assert_sha256(ASSETS.joinpath("vendor", filename).read_bytes(), expected_hash)


def test_manifest_parser_rejects_wrong_duplicate_and_extra_rows() -> None:
    valid = _manifest_fixture(VENDOR_PAYLOADS)
    wrong = valid.replace("`10.29.8`", "`10.29.7`", 1)
    first_row = valid.splitlines()[4]
    duplicate = f"{valid}\n{first_row}"
    extra = f"{valid}\n| `other.js` | `1.0.0` | `local` | `{'0' * 64}` |"
    separated_extra = f"{valid}\n\n| `other.js` | `1.0.0` | `local` | `{'0' * 64}` |"
    for manifest in (wrong, duplicate, extra, separated_extra):
        with pytest.raises(ValueError):
            _validated_manifest_table(
                manifest, "## Runtime payloads", VENDOR_PAYLOADS
            )


def test_license_hash_verification_rejects_wrong_bytes() -> None:
    with pytest.raises(AssertionError):
        _assert_sha256(b"not the upstream license", LICENSE_PAYLOADS["preact.LICENSE"][2])


def test_js_regex_quote_cannot_hide_a_following_external_fetch() -> None:
    javascript = 'const quote = /"/; fetch("https://evil.invalid/data");'
    with pytest.raises(AssertionError):
        _assert_js_offline(javascript)


@pytest.mark.parametrize(
    "regex",
    [
        r"/https?:\/\/[^\s]+/gi",
        r"/escaped\\\/slash\/\/[\"']+\/\*marker/giu",
        r"/[/*\"']+\/\/tail/m",
    ],
)
def test_js_regex_content_cannot_hide_a_following_external_url(regex: str) -> None:
    javascript = f'const matcher = {regex}; const remote = "https://evil.invalid";'
    with pytest.raises(AssertionError):
        _assert_js_offline(javascript)


def test_normal_regex_division_and_template_syntax_without_urls_passes() -> None:
    javascript = r"""
      const ratio = total / count;
      const matcher = /[\/"']+\/\*marker/giu;
      const view = html`<span>${ratio}</span>`;
      fetch("/api/meta");
      // comment
    """
    _assert_js_offline(javascript)


def test_template_markup_external_urls_are_rejected() -> None:
    local_template = """
      const view = html`<span>${ {
        value: `${local}`,
        match: /[}]/,
        nested: {enabled: true},
        /* local expression */
      }.value }</span>`;
      fetch("/api/meta");
    """
    _assert_js_offline(local_template)

    external_template = 'const view = html`<img src="https://evil.invalid/pixel">`;'
    with pytest.raises(AssertionError):
        _assert_js_offline(external_template)


def test_htm_svg_namespace_allowance_is_attribute_scoped() -> None:
    svg = (
        'const icon = html`<svg xmlns="http://www.w3.org/2000/svg">'
        "<path /></svg>`;"
    )
    _assert_js_offline(svg)

    wrong_context = (
        'const icon = html`<svg data-source="http://www.w3.org/2000/svg">'
        "<path /></svg>`;"
    )
    with pytest.raises(AssertionError):
        _assert_js_offline(wrong_context)


def test_svg_namespace_allowance_requires_an_actual_svg_start_tag() -> None:
    allowed = (
        "const icon = html`<SVG viewBox='0 0 1 1' "
        "XMLNS='http://www.w3.org/2000/svg'><path /></SVG>`;"
    )
    _assert_js_offline(allowed)


def test_svg_namespace_uri_is_rejected_outside_an_svg_xmlns_attribute() -> None:
    rejected = [
        'const xmlns = "http://www.w3.org/2000/svg";',
        'const options = {xmlns: "http://www.w3.org/2000/svg"};',
        'const view = html`<div xmlns="http://www.w3.org/2000/svg"></div>`;',
        'const text = html`xmlns="http://www.w3.org/2000/svg"`;',
        'const view = html`<svg>http://www.w3.org/2000/svg</svg>`;',
    ]
    for source in rejected:
        with pytest.raises(AssertionError):
            _assert_js_offline(source)


def test_dependency_contract_requires_stylesheet_and_deferred_classic_scripts() -> None:
    actual = _read_asset("index.html")
    mutations = [
        actual.replace(
            '<script defer src="vendor/preact.umd.js">',
            '<script src="vendor/preact.umd.js">',
        ),
        actual.replace(
            '<script defer src="vendor/preact.umd.js">',
            '<script defer async src="vendor/preact.umd.js">',
        ),
        actual.replace(
            '<script defer src="vendor/preact.umd.js">',
            '<script defer type="module" src="vendor/preact.umd.js">',
        ),
        actual.replace(
            '<link rel="stylesheet" href="vendor/uPlot.min.css">',
            '<link rel="preload" href="vendor/uPlot.min.css">',
        ),
        actual.replace(
            '<script defer src="vendor/preact.umd.js">',
            '<script defer type="text/plain" src="vendor/preact.umd.js">',
        ),
        actual.replace(
            '<script defer src="vendor/preact.umd.js">',
            '<script defer nomodule src="vendor/preact.umd.js">',
        ),
        actual.replace(
            '<link rel="stylesheet" href="vendor/uPlot.min.css">',
            '<link disabled rel="stylesheet" href="vendor/uPlot.min.css">',
        ),
        actual.replace(
            '<script defer src="vendor/preact.umd.js">',
            '<script defer data-extra="no" src="vendor/preact.umd.js">',
        ),
    ]
    for mutated in mutations:
        with pytest.raises(AssertionError):
            _assert_dependency_contract(mutated)


def test_app_root_is_not_a_page_wide_live_region() -> None:
    parser = _parse_html(_read_asset("index.html"))
    main_attributes = {
        name: value
        for tag, name, value in parser.attributes
        if tag == "main"
    }
    assert "aria-live" not in main_attributes


def test_activity_frontend_preserves_list_semantics_and_date_local_rollups() -> None:
    source = _read_asset("app.js")

    assert source.index('if (change.kind === "list"') < source.index(
        'if (change.semantic === "cost"'
    )
    assert (
        'return change.list_added && change.list_added.length ? "capability" : "dim";'
        in source
    )
    assert "data.rollups_by_date[day]" in source
    assert "rollupLine(group.date)" in source
    assert "data.rollups.squelched" not in source
    assert "entry.change_ids_by_change[index]" in source
    assert "entry.change_ids[Math.min(index" not in source


def test_heatmap_uses_independent_180_day_range_and_selected_detail() -> None:
    source = _read_asset("app.js")

    assert "from: clamp(shiftDay(state.to, -179), meta.date_span)" in source
    assert "detail=${state.detail}" in source
    assert 'detail === "all"' in source
    assert 'detail === "squelched"' in source


def test_frontend_pages_activity_and_merges_stable_entry_identities() -> None:
    source = _read_asset("app.js")

    assert "function usePagedApi(" in source
    assert "function activityEntryId(" in source
    assert "mergeActivityPages(current.data, data, page)" in source
    assert "api.get(path, {...params, page}" in source
    assert "loadMore" in source
    assert "hasMore" in source
    assert "Load more changes" in source


def test_activity_load_more_is_locked_and_advances_from_server_page() -> None:
    source = _read_asset("app.js")

    assert "const inFlight = useRef(null)" in source
    assert "if (inFlight.current" in source
    assert "state.key !== requestKey" in source
    assert "page: state.data.page + 1" in source
    assert "current.page + 1" not in source
    assert "state.key === requestKey" in source


def test_frontend_replaces_initial_defaults_and_sanitizes_hash_state() -> None:
    source = _read_asset("app.js")

    assert "history.replaceState(" in source
    assert "replaceState(missing)" in source
    assert "function resolveState(meta, state)" in source
    assert "function validDate(" in source
    assert "validDate(state.from) ? clamp(state.from, span) : fallback.from" in source
    assert "validDate(state.to) ? clamp(state.to, span) : fallback.to" in source
    assert "if (resolved.from > resolved.to)" in source
    assert 'resolved.detail = ["default", "all", "squelched"].includes(state.detail)' in source
    assert "class ErrorBoundary extends preact.Component" in source
    assert "<${ErrorBoundary}><${App} /></${ErrorBoundary}>" in source


def test_heatmap_uses_roving_buttons_without_incomplete_grid_roles() -> None:
    source = _read_asset("app.js")

    assert 'role="grid"' not in source
    assert 'role="gridcell"' not in source
    assert "tabIndex=${day === to ? 0 : -1}" in source
    assert 'event.key === "ArrowLeft"' in source
    assert 'event.key === "Home"' in source
    assert "aria-pressed=${day >= from && day <= to}" in source
    assert 'event.key === "ArrowLeft") target = index - 7' in source
    assert 'event.key === "ArrowRight") target = index + 7' in source
    assert 'event.key === "ArrowUp") target = index - 1' in source
    assert 'event.key === "ArrowDown") target = index + 1' in source


def test_narrow_layout_contract_keeps_outer_shell_bounded() -> None:
    source = _read_asset("app.css")

    assert "minmax(0, 1fr)" in source
    assert ".filter-row > *" in source
    assert "min-width: 0" in source
    assert ".dates input" in source
    assert "width: 100%" in source


def test_models_frontend_fetches_pins_aspects_series_and_events() -> None:
    source = _read_asset("app.js")

    assert "function Models(" in source
    assert "function Pins(" in source
    assert "function AspectPicker(" in source
    assert "function PanelStack(" in source
    assert "function EventRail(" in source
    assert 'useApi("/api/models"' in source
    assert 'useApi("/api/series"' in source
    assert 'useApi("/api/events"' in source
    assert "setTimeout(() => setDebouncedQuery(query), 150)" in source
    assert "meta.pin_limit" in source
    assert "meta.categories" in source
    assert "aspect.squelched" in source


def test_models_aspect_limit_is_enforced_for_hash_and_picker() -> None:
    source = _read_asset("app.js")

    assert "const ASPECT_LIMIT = 12" in source
    assert "const knownAspects = new Set(meta.aspects.map(aspect => aspect.id))" in source
    assert "resolved.aspects = list(state.aspects, knownAspects).slice(0, ASPECT_LIMIT)" in source
    assert "if (selected.length >= ASPECT_LIMIT)" in source
    assert "You can compare at most ${ASPECT_LIMIT} aspects." in source
    assert "toast=${toast}" in source


def test_models_picker_prunes_orphaned_provider_aspects_before_counting() -> None:
    source = _read_asset("app.js")

    assert "const availableIds = new Set(available.map(aspect => aspect.id))" in source
    assert "const visibleSelected = selected.filter(id => availableIds.has(id))" in source
    assert "selected=${visibleSelected}" in source
    assert "selected=${selected}" not in source[source.index("function AspectPicker("):source.index("function cssSeries(")]


def test_models_numeric_panels_use_stepped_synced_uplot_contract() -> None:
    source = _read_asset("app.js")

    assert "uPlot.paths.stepped({align: 1})" in source
    assert "spanGaps: false" in source
    assert 'time: true' in source
    assert 'key: "ms-browse"' in source
    assert "point.completed_at" in source
    assert "getPropertyValue(`--series-${index + 1}`)" in source
    assert "u.setSeries(index, {focus: true})" in source
    assert "setScale" in source
    assert "write({from: localDayFromEpoch(min), to: localDayFromEpoch(max)})" in source
    assert "key=${`${aspect.id}:${themeKey}`}" in source
    assert 'stroke: cssToken("--ink-muted")' in source
    assert 'stroke: cssToken("--border")' in source


def test_models_legend_reset_and_local_date_zoom_regressions() -> None:
    source = _read_asset("app.js")

    assert "record.u.setSeries(null, {focus: false})" in source
    assert "if (!focus)" in source
    assert source.index("if (!focus)") < source.index("record.u.setSeries(index, {focus: true})")
    assert "function localDayFromEpoch(value)" in source
    assert "date.getFullYear()" in source
    assert "date.getMonth() + 1" in source
    assert "date.getDate()" in source
    assert "new Date(value * 1000).toISOString()" not in source


def test_models_pointer_zoom_fallback_updates_hash_for_non_mouse_drags() -> None:
    source = _read_asset("app.js")

    assert 'addEventListener("pointerdown"' in source
    assert 'addEventListener("pointerup"' in source
    assert "event.pointerType === \"mouse\"" in source
    assert "u.posToVal(" in source
    assert "queueZoomWrite(" in source
    assert 'removeEventListener("pointerdown"' in source
    assert 'removeEventListener("pointerup"' in source


def test_models_state_strips_and_event_rail_preserve_semantics() -> None:
    source = _read_asset("app.js")
    styles = _read_asset("app.css")

    assert "function StateStrip(" in source
    assert 'aspect.kind === "boolean" || aspect.kind === "list"' in source
    assert 'aspect.kind === "scalar"' in source
    assert 'String(value)' in source
    assert "item.list_hash[index]" in source
    assert 'value === null ? "missing" : value ? "true" : "false"' in source
    assert "function eventTone(event)" in source
    assert 'event.semantic === "cost"' in source
    assert 'event.semantic === "capacity"' in source
    assert 'event.semantic === "coverage"' in source
    assert "openRaw(event.change_id)" in source
    assert "setTimelineCursor(plots, epochForDay(event.date))" in source
    assert ".state-strip-row" in styles
    assert "height: 56px" in styles
    assert ".event-mark.is-squelched" in styles
    assert "opacity: 0.4" in styles


def test_event_rail_allocates_a_distinct_lane_for_every_same_day_event() -> None:
    source = _read_asset("app.js")
    styles = _read_asset("app.css")

    assert "function allocateEventLanes(events)" in source
    assert "const lane = counts.get(event.date) || 0" in source
    assert "counts.set(event.date, lane + 1)" in source
    assert "--rail-lanes: ${lanes.max}" in source
    assert "event.lane" in source
    assert "height: calc(2rem + var(--rail-lanes) * 0.7rem)" in styles


def test_ambiguous_aspects_include_provider_labels_in_picker_and_panels() -> None:
    source = _read_asset("app.js")

    assert "function ambiguousAspectIds(aspects)" in source
    assert "showProvider=${ambiguous.has(aspect.id)}" in source
    assert "providerLabel=${providerLabels[aspect.provider_id]}" in source
    assert 'class="aspect-provider"' in source
    assert 'class="panel-provider"' in source


def test_models_filters_orphaned_aspects_and_only_flips_list_tint_on_change() -> None:
    source = _read_asset("app.js")

    assert "const activeAspects = aspects.filter" in source
    assert "aspects: activeAspects" in source
    assert "function listToneAt(hashes, index)" in source
    assert "hash !== previous" in source
    assert 'listToneAt(aspect.kind === "list" ? item.list_hash : item.values, index)' in source


def test_models_empty_conditional_collections_do_not_render_zero_text() -> None:
    source = _read_asset("app.js")

    assert "return aspects.length ? html`" in source
    assert "squelched.length ? html`" in source
    assert "pins.length ? html`<${EventRail}" in source
    assert "aspects.length && html`" not in source
    assert "squelched.length && html`" not in source
    assert "pins.length && html`<${EventRail}" not in source


@pytest.mark.parametrize(
    "source",
    [
        '// documentation: https://evil.invalid must never be authored\nfetch("/api/meta");',
        '/* background: url(https://evil.invalid/pixel) */ .panel {}',
    ],
)
def test_raw_authored_comments_cannot_contain_external_urls(source: str) -> None:
    with pytest.raises(AssertionError):
        _assert_authored_source_offline(source, label="authored comment")


def test_index_declares_csp_before_any_script_or_stylesheet() -> None:
    _assert_csp_contract(_read_asset("index.html"))


def test_csp_rejects_missing_or_widened_connect_sources() -> None:
    actual = _read_asset("index.html")
    mutations = [
        actual.replace("connect-src 'self';", ""),
        actual.replace("connect-src 'self'", "connect-src *"),
        actual.replace("connect-src 'self'", "connect-src 'self' https:"),
    ]
    for mutated in mutations:
        with pytest.raises(AssertionError):
            _assert_csp_contract(mutated)
