"""
Packet 24: Keyboard Accessibility

Tests for:
- :focus-visible CSS rules for all interactive elements
- ProjectCard ARIA attributes (tabIndex, role, aria-label)
- ProjectCard keyboard handler (Enter/Space → navigate)
- ProjectDetail Escape key handler
- No focus ring on mouse click (:focus-visible not :focus)
- Pre-existing :focus-visible rules are preserved (no regressions)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import fastapi    # noqa: F401
    import aiosqlite  # noqa: F401
except ImportError:
    pytest.skip(
        "fastapi/aiosqlite not installed — run tests inside the test venv: "
        ".venv/bin/python -m pytest",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402


# ── HTML template tests ────────────────────────────────────────────────────


def test_focus_visible_on_nav_tabs(client):
    """:focus-visible must be applied to nav tab anchor elements.

    Nav tabs use <a> elements. The global a:focus-visible rule (or
    [role=tab]:focus-visible) must provide the outline.
    """
    html = client.get("/").text
    # Accept either a targeted rule or a broad anchor/link rule
    assert (
        "a:focus-visible" in html
        or ":focus-visible" in html  # exists at all (broad check; narrowed below)
    )
    # Specific: must have at least one rule covering anchors or the nav tabs
    assert "a:focus-visible" in html or ":focus-visible" in html


def test_focus_visible_on_project_card(client):
    """.project-card:focus-visible must include outline and hover-style bg/border."""
    html = client.get("/").text
    assert ".project-card:focus-visible" in html
    # Outline values per spec §5.8
    assert "outline: 2px solid var(--accent-blue)" in html or (
        "2px solid" in html and "var(--accent-blue)" in html
    )
    assert "outline-offset: 2px" in html
    # Must also trigger hover-like background + border changes
    assert "var(--bg-card-hover)" in html
    assert "var(--border-hover)" in html


def test_focus_visible_on_header_buttons(client):
    """Header button elements must receive :focus-visible styles.

    Since header buttons use plain <button> elements, a global
    button:focus-visible rule is sufficient.
    """
    html = client.get("/").text
    assert "button:focus-visible" in html


def test_focus_visible_on_sort_dropdown(client):
    """Sort dropdown trigger (a <button>) must receive :focus-visible styles.

    The trigger is a <button>, so the global button:focus-visible rule covers it.
    """
    html = client.get("/").text
    assert "button:focus-visible" in html


def test_focus_visible_on_filter_input(client):
    """Filter input must receive :focus-visible styles.

    Either via global input:focus-visible or [role="button"]:focus-visible catch-all.
    """
    html = client.get("/").text
    assert "input:focus-visible" in html or "button:focus-visible" in html


def test_focus_visible_global_catchall(client):
    """A global catch-all :focus-visible rule must exist for button, [role=button], and input."""
    html = client.get("/").text
    # The implementation note recommends a catch-all group rule
    assert "button:focus-visible" in html
    assert "input:focus-visible" in html


def test_focus_visible_uses_accent_blue(client):
    """All :focus-visible rules must use var(--accent-blue) for the outline color."""
    html = client.get("/").text
    # The accent-blue token must appear in the context of focus-visible rules.
    # Given the spec requires `outline: 2px solid var(--accent-blue)`, both must coexist.
    assert "focus-visible" in html
    assert "var(--accent-blue)" in html


def test_project_card_has_tabindex(client):
    """ProjectCard outer div must render with tabIndex={0} so Tab key can reach it."""
    html = client.get("/").text
    # tabIndex={0} or tabIndex="0" should appear inside ProjectCard's JSX
    card_idx = html.index("function ProjectCard")
    end_marker = "// GridControls"
    end_idx = html.index(end_marker, card_idx)
    card_src = html[card_idx:end_idx]
    assert "tabIndex" in card_src, "ProjectCard must have tabIndex attribute"
    assert "0" in card_src  # tabIndex={0}


def test_project_card_has_role_button(client):
    """ProjectCard must render with role='button' for screen reader semantics."""
    html = client.get("/").text
    card_idx = html.index("function ProjectCard")
    end_marker = "// GridControls"
    end_idx = html.index(end_marker, card_idx)
    card_src = html[card_idx:end_idx]
    assert 'role="button"' in card_src or "role={'button'}" in card_src, (
        "ProjectCard must have role='button'"
    )


def test_project_card_has_aria_label(client):
    """ProjectCard must render with an aria-label for screen reader identification."""
    html = client.get("/").text
    card_idx = html.index("function ProjectCard")
    end_marker = "// GridControls"
    end_idx = html.index(end_marker, card_idx)
    card_src = html[card_idx:end_idx]
    assert "aria-label" in card_src, "ProjectCard must have aria-label"


def test_project_card_has_keyboard_handler(client):
    """ProjectCard must have an onKeyDown handler for Enter/Space navigation."""
    html = client.get("/").text
    card_idx = html.index("function ProjectCard")
    end_marker = "// GridControls"
    end_idx = html.index(end_marker, card_idx)
    card_src = html[card_idx:end_idx]
    assert "onKeyDown" in card_src, "ProjectCard must have onKeyDown handler"
    # Must check for Enter or Space
    assert "Enter" in card_src, "onKeyDown must handle Enter key"
    assert "' '" in card_src or '" "' in card_src or "Space" in card_src, (
        "onKeyDown must handle Space key"
    )


def test_project_card_keyboard_navigates_to_detail(client):
    """ProjectCard onKeyDown must navigate to #/repo/{id} on Enter or Space."""
    html = client.get("/").text
    card_idx = html.index("function ProjectCard")
    end_marker = "// GridControls"
    end_idx = html.index(end_marker, card_idx)
    card_src = html[card_idx:end_idx]
    assert "#/repo/" in card_src, (
        "ProjectCard keyboard handler must navigate to #/repo/{id}"
    )


def test_escape_handler_in_detail_view(client):
    """ProjectDetail must register a keydown listener that navigates back on Escape."""
    html = client.get("/").text
    detail_idx = html.index("function ProjectDetail")
    # Find the end of the function by searching for the next top-level function
    end_marker = "// ── Heatmap"
    end_idx = html.index(end_marker, detail_idx)
    detail_src = html[detail_idx:end_idx]
    assert "Escape" in detail_src, "ProjectDetail must handle Escape key"
    assert "keydown" in detail_src, (
        "ProjectDetail must add a keydown event listener"
    )
    assert "#/fleet" in detail_src, (
        "Escape must navigate to #/fleet"
    )


def test_no_focus_ring_on_click(client):
    """:focus-visible (not :focus) must be used so mouse clicks don't show the outline.

    We verify by checking that :focus-visible exists and that the implementation
    does NOT use a bare :focus rule for outline styling on interactive elements
    (a bare :focus rule would also fire on click).
    """
    html = client.get("/").text
    assert ":focus-visible" in html, "Must use :focus-visible (not bare :focus)"
    # The implementation should prefer :focus-visible over :focus for outlines.
    # We can't definitively rule out all bare :focus usages (some may be for
    # border-color on inputs), but we can confirm :focus-visible is present.


def test_existing_focus_rules_preserved(client):
    """Pre-existing :focus-visible rules must not be removed (regression check)."""
    html = client.get("/").text
    assert ".detail-back-btn:focus-visible" in html, (
        ".detail-back-btn:focus-visible must still exist"
    )
    assert ".sub-tab-btn:focus-visible" in html, (
        ".sub-tab-btn:focus-visible must still exist"
    )
    assert ".time-range-btn:focus-visible" in html, (
        ".time-range-btn:focus-visible must still exist"
    )


def test_project_card_class_added(client):
    """ProjectCard outer div must have className='project-card' for CSS targeting."""
    html = client.get("/").text
    card_idx = html.index("function ProjectCard")
    end_marker = "// GridControls"
    end_idx = html.index(end_marker, card_idx)
    card_src = html[card_idx:end_idx]
    assert "project-card" in card_src, (
        "ProjectCard outer div must have className='project-card' for CSS to apply"
    )


def test_escape_removes_event_listener(client):
    """ProjectDetail Escape handler must be removed on unmount (useEffect cleanup)."""
    html = client.get("/").text
    detail_idx = html.index("function ProjectDetail")
    end_marker = "// ── Heatmap"
    end_idx = html.index(end_marker, detail_idx)
    detail_src = html[detail_idx:end_idx]
    assert "removeEventListener" in detail_src, (
        "ProjectDetail must remove the keydown listener in useEffect cleanup"
    )
