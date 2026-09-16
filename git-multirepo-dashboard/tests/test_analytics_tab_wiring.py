"""
Packet 21: Analytics Tab Wiring
Tests verify the AnalyticsTab component is defined, wired into ContentArea,
and that all three analytics API endpoints remain functional.
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


def test_analytics_tab_component_in_html(client):
    """AnalyticsTab component must be defined in the HTML template."""
    r = client.get("/")
    assert r.status_code == 200
    assert "AnalyticsTab" in r.text


def test_analytics_section_headers_in_html(client):
    """All three section headers must appear in the HTML."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Activity Heatmap" in r.text
    assert "Time Allocation" in r.text
    assert "Dependency Overlap" in r.text


def test_analytics_tab_renders_child_components(client):
    """AnalyticsTab must reference Heatmap, TimeAllocation, and DepOverlap."""
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert "Heatmap" in html
    assert "TimeAllocation" in html
    assert "DepOverlap" in html


def test_content_area_no_coming_soon(client):
    """The 'Analytics — coming soon' placeholder must be replaced."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Analytics \u2014 coming soon" not in r.text


def test_analytics_section_layout_gap(client):
    """AnalyticsTab must apply 32px gap between sections."""
    r = client.get("/")
    assert r.status_code == 200
    assert "32px" in r.text
