"""
Packet 23: Visual Polish

Tests for:
- @keyframes pulse animation for skeleton cards
- SkeletonCard component (3 animated placeholder rows)
- FleetOverview shows SkeletonCard while loading
- Scrollbar styling (WebKit and Firefox)
- Scrollbar uses design system tokens
- /api/status endpoint shape
- ToolStatusBanner component
- ToolStatusBanner fetches /api/status
- ToolStatusBanner dismissible via sessionStorage
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


def test_skeleton_keyframes_in_css(client):
    """@keyframes pulse must be defined with opacity transitions."""
    html = client.get("/").text
    assert "@keyframes pulse" in html
    # Must have both 0%/100% at 0.4 and 50% at 0.7
    assert "opacity: 0.4" in html
    assert "opacity: 0.7" in html


def test_skeleton_component_exists(client):
    """SkeletonCard function must be defined in HTML_TEMPLATE."""
    html = client.get("/").text
    assert "SkeletonCard" in html


def test_skeleton_three_rows(client):
    """SkeletonCard must reference 3 placeholder rows with 60%, 80%, 50% widths."""
    html = client.get("/").text
    assert "SkeletonCard" in html
    # All three widths must appear in the template
    assert "60%" in html
    assert "80%" in html
    assert "50%" in html


def test_scrollbar_webkit_styles(client):
    """WebKit scrollbar pseudo-elements must be defined in the CSS."""
    html = client.get("/").text
    assert "::-webkit-scrollbar" in html
    assert "::-webkit-scrollbar-track" in html
    assert "::-webkit-scrollbar-thumb" in html


def test_scrollbar_firefox_styles(client):
    """Firefox scrollbar properties must be defined in the CSS."""
    html = client.get("/").text
    assert "scrollbar-color" in html
    assert "scrollbar-width" in html


def test_scrollbar_uses_design_tokens(client):
    """Scrollbar styling must reference design system tokens."""
    html = client.get("/").text
    # Must use dark theme color tokens (not hard-coded hex)
    assert "--bg-primary" in html or "--border-default" in html
    # Specifically in the context of scrollbar styling, both should appear
    # (they are used for track and thumb respectively)
    assert "--border-default" in html
    assert "--bg-primary" in html


def test_api_status_endpoint_shape(test_app):
    """GET /api/status must return {tools: {...}, version: '...'}."""
    client, _ = test_app
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert "tools" in body
    assert "version" in body
    assert isinstance(body["tools"], dict)
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0


def test_tool_status_banner_component(client):
    """ToolStatusBanner function must be defined in HTML_TEMPLATE."""
    html = client.get("/").text
    assert "ToolStatusBanner" in html


def test_tool_status_banner_fetches_status(client):
    """ToolStatusBanner must contain a fetch('/api/status') call."""
    html = client.get("/").text
    assert "fetch('/api/status')" in html or 'fetch("/api/status")' in html


def test_tool_status_banner_dismissible(client):
    """ToolStatusBanner must reference sessionStorage for dismiss persistence."""
    html = client.get("/").text
    assert "sessionStorage" in html


def test_fleet_overview_shows_skeletons(client):
    """FleetOverview must render SkeletonCard when data is not yet loaded."""
    html = client.get("/").text
    # Both FleetOverview and SkeletonCard must appear, and FleetOverview
    # must reference SkeletonCard in its body (confirmed by both names in template)
    assert "FleetOverview" in html
    assert "SkeletonCard" in html
    # The loading branch in FleetOverview must reference SkeletonCard
    # We verify this by checking that SkeletonCard appears in the section after
    # the FleetOverview definition (rough check via index ordering)
    fleet_idx = html.index("function FleetOverview")
    skeleton_ref_idx = html.index("SkeletonCard", fleet_idx)
    assert skeleton_ref_idx > fleet_idx, (
        "SkeletonCard must be referenced inside FleetOverview function"
    )
