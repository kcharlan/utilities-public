from __future__ import annotations

from html.parser import HTMLParser
from importlib import resources
import re

import pytest


ASSETS = resources.files("model_sentinel.browse").joinpath("assets")
REQUIRED_TOKENS = {
    "--ground",
    "--panel",
    "--panel-raised",
    "--ink",
    "--ink-strong",
    "--ink-muted",
    "--cost-up",
    "--cost-down",
    "--capacity",
    "--capability",
    "--dim",
    "--presence-added",
    "--presence-removed",
    "--accent",
    *(f"--heat-{index}" for index in range(4)),
    *(f"--series-{index}" for index in range(1, 9)),
}
PINNED_DARK_TOKENS = {
    "--ground": "#0f1419",
    "--panel": "#1a1f2e",
    "--ink": "#c5cdd8",
    "--ink-strong": "#e8edf4",
    "--cost-up": "#f87171",
    "--cost-down": "#34d399",
    "--capacity": "#fbbf24",
    "--capability": "#60a5fa",
}


def _read(name: str) -> str:
    return ASSETS.joinpath(name).read_text(encoding="utf-8")


def _without_css_comments(source: str) -> str:
    output: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if quote is not None:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
        elif char in {'"', "'"}:
            quote = char
            output.append(char)
            index += 1
        elif char == "/" and following == "*":
            end = source.find("*/", index + 2)
            comment_end = len(source) if end < 0 else end + 2
            comment = source[index:comment_end]
            output.append(" " + "\n" * comment.count("\n"))
            index = comment_end
        else:
            output.append(char)
            index += 1
    return "".join(output)


def _matching_brace(source: str, opening: int) -> int:
    depth = 1
    quote: str | None = None
    escaped = False
    parentheses = 0
    index = opening + 1
    while depth and index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == "/" and following == "*":
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        elif char == "(":
            parentheses += 1
        elif char == ")" and parentheses:
            parentheses -= 1
        elif char == "{" and not parentheses:
            depth += 1
        elif char == "}" and not parentheses:
            depth -= 1
        index += 1
    assert depth == 0, f"unclosed block starting at offset {opening}"
    return index - 1


def _top_level_blocks(source: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    position = 0
    while True:
        opening = source.find("{", position)
        if opening < 0:
            break
        closing = _matching_brace(source, opening)
        blocks.append((source[position:opening].strip(), source[opening + 1 : closing]))
        position = closing + 1
    return blocks


def _block(source: str, selector: str) -> str:
    matches = [body for header, body in _top_level_blocks(source) if header == selector]
    assert len(matches) == 1, f"expected one actual {selector!r} block"
    return matches[0]


def _custom_properties(block: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    segments: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    for index, char in enumerate(block):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == ";":
            segments.append(block[start:index])
            start = index + 1
    segments.append(block[start:])

    for segment in segments:
        match = re.fullmatch(r"\s*(--[a-z0-9-]+)\s*:\s*(.*?)\s*", segment, re.DOTALL)
        if match is None:
            continue
        name, value = match.groups()
        assert value, f"empty custom property {name}"
        assert name not in declarations, f"duplicate custom property {name}"
        declarations[name] = value
    return declarations


def _palette_blocks(source: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    css = _without_css_comments(source)
    light = _custom_properties(_block(css, ":root"))
    dark_media = _block(css, "@media (prefers-color-scheme: dark)")
    system_dark = _custom_properties(
        _block(dark_media, ':root:not([data-theme="light"])')
    )
    explicit_dark = _custom_properties(_block(css, ':root[data-theme="dark"]'))
    return light, system_dark, explicit_dark


def _assert_token_contract(
    light: dict[str, str],
    system_dark: dict[str, str],
    explicit_dark: dict[str, str],
    *,
    required: set[str] = REQUIRED_TOKENS,
) -> None:
    assert set(light) == set(system_dark) == set(explicit_dark)
    assert required <= set(light)


class _ThemeHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._event = 0
        self.link_events: list[int] = []
        self.inline_scripts: list[tuple[int, str]] = []
        self._script: tuple[int, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._event += 1
        values = dict(attrs)
        if tag == "link":
            self.link_events.append(self._event)
        elif tag == "script" and "src" not in values:
            self._script = (self._event, [])

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script[1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            event, chunks = self._script
            self.inline_scripts.append((event, "".join(chunks)))
            self._script = None


def _prepaint_script(source: str) -> str:
    parser = _ThemeHTMLParser()
    parser.feed(source)
    parser.close()
    assert len(parser.inline_scripts) == 1
    assert parser.link_events
    event, script = parser.inline_scripts[0]
    assert event < parser.link_events[0]
    return script


def test_light_and_both_dark_palettes_have_identical_complete_tokens() -> None:
    palettes = _palette_blocks(_read("app.css"))
    _assert_token_contract(*palettes)


def test_both_dark_palettes_pin_the_established_report_colors() -> None:
    _, system_dark, explicit_dark = _palette_blocks(_read("app.css"))
    for name, expected in PINNED_DARK_TOKENS.items():
        assert system_dark[name].lower() == expected
        assert explicit_dark[name].lower() == expected


def test_dark_media_is_guarded_and_explicit_dark_is_supported() -> None:
    css = _without_css_comments(_read("app.css"))
    media = _block(css, "@media (prefers-color-scheme: dark)")
    _block(media, ':root:not([data-theme="light"])')
    _block(css, ':root[data-theme="dark"]')


def test_motion_and_keyboard_focus_preferences_are_accessible() -> None:
    css = _without_css_comments(_read("app.css"))
    reduced_motion = _block(css, "@media (prefers-reduced-motion: reduce)")
    assert re.search(r"animation(?:-duration)?\s*:", reduced_motion)
    focus = _block(css, ":focus-visible")
    assert re.search(r"(?:outline|box-shadow)\s*:", focus)


def test_theme_is_validated_and_stamped_before_actual_stylesheet_tags() -> None:
    script = _prepaint_script(_read("index.html"))
    assert 'model_sentinel.browse.theme' in script
    assert "localStorage.getItem" in script
    assert all(f'"{value}"' in script for value in ("system", "light", "dark"))
    assert re.search(r"includes\s*\(", script)
    assert re.search(r'theme\s*!==\s*["\']system["\']', script)
    assert re.search(r"(?:dataset\.theme|setAttribute\s*\([^)]*data-theme)", script)


def test_prepaint_parser_ignores_comment_decoys_and_rejects_late_script() -> None:
    source = """
      <!-- <script>model_sentinel.browse.theme</script> -->
      <link rel="stylesheet" href="app.css">
      <script>model_sentinel.browse.theme</script>
    """
    with pytest.raises(AssertionError):
        _prepaint_script(source)


def test_theme_parser_ignores_commented_decoy_blocks() -> None:
    css = '/* :root { --decoy: #fff; } */ :root { --real: #000; }'
    root = _block(_without_css_comments(css), ":root")
    assert _custom_properties(root) == {"--real": "#000"}


@pytest.mark.parametrize("declaration", ["--empty: ;", "--empty:"])
def test_theme_parser_rejects_empty_token_values(declaration: str) -> None:
    with pytest.raises(AssertionError):
        _custom_properties(declaration)


def test_theme_contract_rejects_missing_and_light_only_tokens() -> None:
    with pytest.raises(AssertionError):
        _assert_token_contract(
            {"--shared": "a", "--light-only": "b"},
            {"--shared": "c"},
            {"--shared": "c"},
            required={"--shared"},
        )
    with pytest.raises(AssertionError):
        _assert_token_contract(
            {"--shared": "a"},
            {"--shared": "c"},
            {"--shared": "c"},
            required={"--required"},
        )


def test_css_comment_stripping_preserves_comment_markers_inside_strings() -> None:
    css = ':root { --image: "/* quoted marker, not a comment */"; }'
    cleaned = _without_css_comments(css)
    assert "quoted marker, not a comment" in cleaned


@pytest.mark.parametrize(
    "value",
    [
        '"quoted } brace"',
        '"escaped \\" } brace"',
        'url("data:image/svg+xml;utf8,<svg>{<path d=\'M0 0\'/>}</svg>")',
    ],
)
def test_css_block_scanning_ignores_braces_inside_quoted_values(value: str) -> None:
    css = f":root {{ --image: {value}; --ground: #fff; }}"
    declarations = _custom_properties(_block(css, ":root"))
    assert declarations["--image"] == value
    assert declarations["--ground"] == "#fff"
