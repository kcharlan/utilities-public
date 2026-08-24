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


def test_empty_history_guidance_uses_display_invocation_as_text() -> None:
    source = _read_asset("app.js")

    assert 'const invocation = meta.display_invocation || "model-sentinel";' in source
    assert "<code>${invocation} scan --save</code>" in source
    assert "<code>model-sentinel scan --save</code>" not in source


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


def test_model_typeahead_portal_escapes_sidebar_and_cleans_up() -> None:
    source = _read_asset("app.js")
    portal = source[
        source.index("function Portal(") : source.index("function TypeaheadOverlay(")
    ]
    host_match = re.search(
        r"const (\w+) = useMemo\(\(\) => \{(?P<factory>.*?)\}, \[\]\);",
        portal,
        re.DOTALL,
    )

    assert host_match is not None
    factory = host_match.group("factory")
    element_match = re.search(r'const (\w+) = document\.createElement\("div"\)', factory)
    assert element_match is not None
    element = re.escape(element_match.group(1))
    assert re.search(rf'{element}\.dataset\.modelSentinelPortal = "typeahead"', factory)
    assert re.search(rf"return {element};", factory)
    host = re.escape(host_match.group(1))
    assert portal.count('document.createElement("div")') == 1
    assert len(re.findall(r"useEffect\(\(\) => \{", portal)) == 2
    assert re.search(rf"document\.body\.appendChild\({host}\)", portal)
    assert re.search(rf"render\(children, {host}\)", portal)
    assert re.search(rf"render\(null, {host}\).*?{host}\.remove\(\)", portal, re.DOTALL)
    assert portal.count("render(null,") == 1
    assert portal.index("render(null,") < portal.index("render(children,")


def test_model_typeahead_placement_tracks_viewport_and_anchor() -> None:
    source = _read_asset("app.js")
    placement = source[
        source.index("function typeaheadPlacement(") : source.index("function Portal(")
    ]

    assert "margin = 8" in placement
    below_match = re.search(
        r"const (\w+) = Math\.max\(0, viewport\.height - anchor\.bottom - margin\);",
        placement,
    )
    above_match = re.search(
        r"const (\w+) = Math\.max\(0, anchor\.top - margin\);", placement
    )
    assert below_match is not None and above_match is not None
    below, above = map(re.escape, (below_match.group(1), above_match.group(1)))
    flip_match = re.search(
        rf"const (\w+) = {below} < 160 && {above} > {below};", placement
    )
    assert flip_match is not None
    flip = re.escape(flip_match.group(1))
    available_match = re.search(
        rf"const (\w+) = {flip} \? {above} : {below};", placement
    )
    assert available_match is not None
    available = re.escape(available_match.group(1))
    width_limit_match = re.search(
        r"const (\w+) = Math\.max\(0, viewport\.width - 2 \* margin\);",
        placement,
    )
    assert width_limit_match is not None
    width_limit = re.escape(width_limit_match.group(1))
    width_match = re.search(
        rf"const (\w+) = Math\.min\(Math\.max\(anchor\.width, 352\), {width_limit}\);",
        placement,
    )
    assert width_match is not None
    width = re.escape(width_match.group(1))
    assert re.search(rf"viewport\.width - margin - {width}", placement)
    assert re.search(rf"Math\.max\(0, Math\.min\({available}, 320\)\)", placement)
    assert re.search(r"\? \{[^}]*bottom: viewport\.height - anchor\.top[^}]*\}", placement)
    assert re.search(r": \{[^}]*top: anchor\.bottom[^}]*\}", placement)
    assert not re.search(r"\? \{[^}]*\btop\s*:", placement)
    assert not re.search(r": \{[^}]*\bbottom\s*:", placement)


def test_model_typeahead_hides_anchors_outside_viewport_or_sidebar_clip() -> None:
    source = _read_asset("app.js")
    intersection = source[
        source.index("function rectangleIntersection(") : source.index(
            "function typeaheadPlacement("
        )
    ]
    overlay = source[
        source.index("function TypeaheadOverlay(") : source.index("function Pins(")
    ]

    result_match = re.search(r"const (\w+) = \{", intersection)
    assert result_match is not None
    result = re.escape(result_match.group(1))
    assert "left: Math.max(first.left, second.left)" in intersection
    assert "top: Math.max(first.top, second.top)" in intersection
    assert "right: Math.min(first.right, second.right)" in intersection
    assert "bottom: Math.min(first.bottom, second.bottom)" in intersection
    assert re.search(
        rf"{result}\.right > {result}\.left && {result}\.bottom > {result}\.top",
        intersection,
    )
    assert re.search(rf"\? {result}\s*: null", intersection)
    assert "left: 0" in overlay
    assert "top: 0" in overlay
    assert "right: window.innerWidth" in overlay
    assert "bottom: window.innerHeight" in overlay
    clip_match = re.search(r'const (\w+) = \w+\.closest\("\.model-controls"\);', overlay)
    assert clip_match is not None
    clip = re.escape(clip_match.group(1))
    visible_match = re.search(
        rf"const (\w+) = {clip}\s*\? rectangleIntersection\(\w+, {clip}\.getBoundingClientRect\(\)\)\s*: \w+;",
        overlay,
    )
    assert visible_match is not None
    visible = re.escape(visible_match.group(1))
    assert re.search(
        rf"if \(!{visible} \|\| !rectangleIntersection\(\w+, {visible}\)\) \{{\s*setPlacement\(null\);\s*return;",
        overlay,
    )

    scroll_match = re.search(
        r'window\.addEventListener\("scroll", (\w+), true\)', overlay
    )
    assert scroll_match is not None
    schedule = re.escape(scroll_match.group(1))
    assert re.search(
        rf"const {schedule} = \(\) => \{{.*?window\.requestAnimationFrame\(\w+\)",
        overlay,
        re.DOTALL,
    )
    assert "}, [anchorRef, open]);" in overlay


def test_model_typeahead_preserves_listbox_keyboard_contract() -> None:
    source = _read_asset("app.js")
    overlay = source[
        source.index("function TypeaheadOverlay(") : source.index("function Pins(")
    ]
    pins = source[source.index("function Pins(") : source.index("function ambiguousAspectIds(")]

    assert "getBoundingClientRect()" in overlay
    assert "typeaheadPlacement(" in overlay
    resize_match = re.search(r'window\.addEventListener\("resize", (\w+)\)', overlay)
    scroll_match = re.search(r'window\.addEventListener\("scroll", (\w+), true\)', overlay)
    assert resize_match is not None and scroll_match is not None
    assert re.search(
        rf'window\.removeEventListener\("resize", {re.escape(resize_match.group(1))}\)',
        overlay,
    )
    assert re.search(
        rf'window\.removeEventListener\("scroll", {re.escape(scroll_match.group(1))}, true\)',
        overlay,
    )
    observer_match = re.search(r"const (\w+) = new ResizeObserver\(", overlay)
    assert observer_match is not None
    observer = re.escape(observer_match.group(1))
    assert re.search(rf"{observer}\.observe\(", overlay)
    frame_match = re.search(r"let (\w+) = null;", overlay)
    assert frame_match is not None
    frame = re.escape(frame_match.group(1))
    assert re.search(
        rf"if \({frame} !== null\) return;\s*{frame} = window\.requestAnimationFrame",
        overlay,
    )
    assert re.search(rf"window\.cancelAnimationFrame\({frame}\)", overlay)
    assert re.search(rf"{observer}\.disconnect\(\)", overlay)
    assert re.search(
        r"if \(!\w+ \|\| !\w+\.isConnected\) \{\s*setPlacement\(null\);\s*return;",
        overlay,
    )
    assert "placement ?" in overlay
    assert "style=${placement}" in overlay

    listbox_match = re.search(r'const (\w+) = "pin-results";', pins)
    query_match = re.search(r'const \[(\w+), (\w+)\] = useState\(""\);', pins)
    assert listbox_match is not None and query_match is not None
    query, clear_query = map(re.escape, query_match.groups())
    open_match = re.search(rf"const (\w+) = Boolean\({query}\.trim\(\)\);", pins)
    assert open_match is not None
    listbox_id = re.escape(listbox_match.group(1))
    open_state = re.escape(open_match.group(1))
    assert re.search(rf"aria-expanded=\$\{{{open_state}\}}", pins)
    assert re.search(
        rf"aria-controls=\$\{{{open_state} \? {listbox_id} : undefined\}}", pins
    )
    option_match = re.search(
        rf'const (\w+) = document\.getElementById\({listbox_id}\)\?\.querySelector\("button"\)',
        pins,
    )
    assert option_match is not None
    option = re.escape(option_match.group(1))
    assert "event.preventDefault()" in pins
    assert re.search(rf"{option}\.focus\(\)", pins)
    assert "nextElementSibling" not in pins
    assert 'role="listbox"' in pins
    assert 'role="option"' in pins
    assert 'event.key === "Escape"' in pins
    assert len(re.findall(rf'{clear_query}\(""\)', pins)) >= 2
    assert re.search(rf"open=\$\{{{open_state}\}}", pins)


def test_model_typeahead_css_is_fixed_bounded_overlay() -> None:
    styles = _read_asset("app.css")

    def declarations(selector: str) -> str:
        match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", styles)
        assert match is not None, selector
        return match.group(1)

    typeahead = declarations(".typeahead")
    assert "position: fixed" in typeahead
    assert "overflow-y: auto" in typeahead
    assert "z-index: 90" in typeahead
    assert all(
        property_name not in typeahead
        for property_name in ("top:", "right:", "bottom:", "left:", "width:", "max-height:")
    )
    assert "z-index: 100" in declarations(".drawer-layer")
    assert "z-index: 110" in declarations(".spark-layer")
    assert "z-index: 120" in declarations(".toast-region")

    controls = declarations(".model-controls")
    assert "position: sticky" in controls
    assert "max-height: calc(100vh - 11rem)" in controls
    assert "overflow-y: auto" in controls


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
    assert 'listToneAt(aspect.kind === "list" ? item.list_hash : item.values, index)' in source
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


def test_state_strip_exposes_members_and_roving_keyboard_tooltips() -> None:
    source = _read_asset("app.js")
    styles = _read_asset("app.css")

    assert "function stateSegmentLabel(" in source
    assert "item.members[index]" in source
    assert "Actual members:" in source
    assert "function StateStripRow(" in source
    assert "const [activeKey, setActiveKey] = useState(" in source
    assert "const axisKey = point => `${point.provider_id}:${point.scrape_id}`" in source
    assert "if (!axis.some(point => axisKey(point) === activeKey))" in source
    assert "tabIndex=${axisKey(point) === activeKey ? 0 : -1}" in source
    assert "event.currentTarget.tabIndex = -1" not in source
    assert "next.tabIndex = 0" not in source
    assert 'event.key === "ArrowLeft"' in source
    assert 'event.key === "ArrowRight"' in source
    assert 'event.key === "Home"' in source
    assert 'event.key === "End"' in source
    assert "aria-label=${label}" in source
    assert 'role="img"' in source
    assert "setTooltip(label)" in source
    assert 'class="state-tooltip"' in source
    assert "role=\"tooltip\"" in source
    assert ".state-strip-row > .state-tooltip" in styles
    assert "inset-inline: 0.5rem" in styles
    assert "max-width: calc(100% - 1rem)" in styles
    assert ".state-strip-row span:hover::after" not in styles


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


def test_catalog_frontend_uses_provider_scoped_saved_scrapes_and_canonical_defaults() -> None:
    source = _read_asset("app.js")

    assert "function Catalog(" in source
    assert "function Pickers(" in source
    assert "function ColumnChooser(" in source
    assert 'scrape.status === "success" && scrape.saved' in source
    assert "scrape.provider_id === providerId" in source
    assert 'aspect.source === "column"' in source
    assert '["Pricing", "Context & Limits", "Capabilities"].includes(aspect.category)' in source
    assert 'useApi("/api/catalog"' in source
    assert 'page_size: CATALOG_PAGE_SIZE' in source
    assert "patch.asof = String(asOf.scrape_id)" in source
    assert "const requestedColumns = [...new Set((state.cols || []).filter(id => known.has(id)))]" in source
    assert "if (!sameList(state.cols || [], columns)) patch.cols = columns" in source
    assert "disabled=${!catalogScrapes(meta, provider.id).length}" in source
    assert 'const sort = state.sort === "model_id" || columns.includes(state.sort) ? state.sort : "model_id"' in source
    assert 'const dir = ["asc", "desc"].includes(state.dir) ? state.dir : "asc"' in source
    assert "patch.sort = sort" in source
    assert "patch.dir = dir" in source
    assert "function Catalog({meta, state, write, replaceState, themeKey})" in source
    assert "if (Object.keys(patch).length) replaceState(patch)" in source
    assert "replaceState=${replaceState}" in source


def test_catalog_table_supports_filter_sort_paging_and_semantic_diffs() -> None:
    source = _read_asset("app.js")
    styles = _read_asset("app.css")

    assert "function CatalogTable(" in source
    assert 'type="search" value=${draft}' in source
    assert 'aria-sort=${sortAria("model_id")}' in source
    assert "write({sort: aspect.id, dir: nextSortDirection(aspect.id)})" in source
    assert "Math.ceil(data.total / CATALOG_PAGE_SIZE)" in source
    assert "cellChanged(cell)" in source
    assert "semantic(cell.change)" in source
    assert '`catalog-row --presence-${row.presence}`' in source
    assert "position: sticky" in styles
    assert "font-variant-numeric: tabular-nums" in styles
    assert ".--presence-added" in styles
    assert ".--presence-removed" in styles


def test_catalog_suppresses_stale_rows_and_replaces_debounced_search_hashes() -> None:
    source = _read_asset("app.js")
    use_api = source[source.index("function useApi("):source.index("function activityEntryId(")]

    assert "const resourceKey = JSON.stringify([path, params, enabled])" in use_api
    assert "key: resourceKey" in use_api
    assert "fresh: state.key === resourceKey" in use_api
    assert "setState(current => ({...current, loading: true, error: null}))" in use_api
    assert "key: null, loading: true" not in use_api
    assert "function CatalogSearch({value, replaceState})" in source
    assert "setTimeout(() => replaceState({q: draft || null}), 250)" in source
    assert "onInput=${event => setDraft(event.currentTarget.value)}" in source
    assert 'onInput=${event => write({q:' not in source
    assert "const catalogData = request.fresh ? request.data : null" in source


def test_catalog_sparkline_uses_full_series_span_and_links_to_models() -> None:
    source = _read_asset("app.js")

    assert "function SparklinePopover(" in source
    assert 'useApi("/api/series", {models: pin, aspects: aspect.id}' in source
    assert "height: 80" in source
    assert "uPlot.paths.stepped({align: 1})" in source
    assert 'write({view: "models", pins, aspects: [aspect.id]' in source
    assert "Open timeline" in source
    assert 'event.key === "Escape"' in source
    assert "function SparklinePopover({meta, pin, aspect, write, close, themeKey})" in source
    assert "}, [request.data, themeKey])" in source
    assert "themeKey=${themeKey}" in source


def test_catalog_sparkline_traps_focus_inerts_background_and_resizes() -> None:
    source = _read_asset("app.js")
    styles = _read_asset("app.css")
    sparkline = source[source.index("function SparklinePopover("):source.index("function CatalogTable(")]

    assert 'if (event.key !== "Tab") return' in sparkline
    assert "const focusable = panel && [...panel.querySelectorAll" in sparkline
    assert "element.inert = true" in sparkline
    assert "element.inert = false" in sparkline
    assert "const observer = new ResizeObserver" in sparkline
    assert "plot.setSize({width, height: 80})" in sparkline
    assert "observer.disconnect()" in sparkline
    assert ".spark-host .uplot" in styles
    assert "max-width: 100%" in styles[styles.index(".spark-host .uplot"):]


def test_catalog_feed_cross_link_bounds_activity_to_compared_scrapes() -> None:
    source = _read_asset("app.js")

    assert "Show as feed" in source
    assert 'write({view: "activity", providers: [providerId], from: dates[0], to: dates[1]})' in source
    assert "const dates = [compare.date, asOf.date].sort()" in source
    assert "compare.completed_at.slice" not in source
    assert "asOf.completed_at.slice" not in source


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
